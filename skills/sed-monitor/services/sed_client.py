"""HTTP client for СЭД Практика via sed-proxy sidecar.

Authentication flow:
  1. GET /alive → parse DNSID from response headers
  2. POST /auth → parse auth_token from response headers
  3. POST /graphql with cookies → GraphQL queries

All requests go through sed-proxy (plain HTTP), which handles GOST TLS.
"""

import json
import logging
import re
import time
from urllib.parse import urlencode

import requests

from config.settings import get_auth, get_proxy_url, load_config

log = logging.getLogger("sed-client")

# Session state
_session: requests.Session | None = None
_dnsid: str = ""
_auth_token: str = ""
_auth_time: float = 0
_AUTH_TTL = 3600  # re-auth every hour


# ---------------------------------------------------------------------------
# Session / Auth
# ---------------------------------------------------------------------------

def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.timeout = 30
    return _session


def _cookies_header() -> str:
    """Build cookie string for X-SED-Cookies header."""
    parts = []
    if _dnsid:
        parts.append(f"DNSID={_dnsid}")
    if _auth_token and _dnsid:
        parts.append(f"auth_token_n_{_dnsid}={_auth_token}")
    auth = get_auth()
    parts.append(f"last_login_u_id={auth['user_id']}")
    return "; ".join(parts)


def _parse_dnsid(raw: str) -> str:
    """Extract DNSID from proxy response (includes raw HTTP headers)."""
    m = re.search(r"DNSID=([a-zA-Z0-9_-]+)", raw)
    return m.group(1) if m else ""


def _parse_auth_token(raw: str, dnsid: str) -> str:
    """Extract auth_token from proxy response headers."""
    pattern = rf"auth_token_n_{re.escape(dnsid)}=([a-zA-Z0-9_-]+)"
    m = re.search(pattern, raw)
    return m.group(1) if m else ""


def authenticate(force: bool = False) -> bool:
    """Authenticate to SED. Returns True on success."""
    global _dnsid, _auth_token, _auth_time

    if not force and _auth_token and (time.time() - _auth_time) < _AUTH_TTL:
        return True

    proxy = get_proxy_url()
    auth = get_auth()
    sess = _get_session()

    # Step 1: GET /alive → DNSID
    try:
        resp = sess.get(f"{proxy}/alive")
        _dnsid = _parse_dnsid(resp.text)
        if not _dnsid:
            log.error("Failed to get DNSID from /alive")
            return False
        log.info(f"Got DNSID: {_dnsid[:8]}...")
    except Exception as e:
        log.error(f"Alive request failed: {e}")
        return False

    # Step 2: POST /auth → auth_token
    query = urlencode({"uri": "/", "DNSID": _dnsid})
    form_data = urlencode({
        "DNSID": _dnsid,
        "group_id": auth["group_id"],
        "login": auth["login"],
        "user_id": auth["user_id"],
        "password": auth["password"],
        "x": "",
    })
    referer = f"https://doc.rscc.ru:444/auth.php?uri=%2F&DNSID={_dnsid}"

    try:
        resp = sess.post(
            f"{proxy}/auth",
            data=form_data.encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-SED-Query": query,
                "X-SED-Referer": referer,
            },
        )
        _auth_token = _parse_auth_token(resp.text, _dnsid)
        if not _auth_token:
            log.error("Failed to get auth_token from /auth")
            return False
        _auth_time = time.time()
        log.info("SED authentication successful")
        return True
    except Exception as e:
        log.error(f"Auth request failed: {e}")
        return False


def _ensure_auth() -> bool:
    """Ensure we have a valid session."""
    return authenticate()


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------

def _graphql(query: str, variables: dict | None = None) -> dict | None:
    """Execute a GraphQL query against SED API."""
    if not _ensure_auth():
        return None

    proxy = get_proxy_url()
    sess = _get_session()
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    try:
        resp = sess.post(
            f"{proxy}/graphql",
            json=payload,
            headers={"X-SED-Cookies": _cookies_header()},
        )
        data = resp.json()
        if "errors" in data:
            log.warning(f"GraphQL errors: {data['errors']}")
        return data.get("data")
    except Exception as e:
        log.error(f"GraphQL request failed: {e}")
        return None


# ---------------------------------------------------------------------------
# API Methods
# ---------------------------------------------------------------------------

def get_folders(parent_id: str | None = None) -> list[dict]:
    """Get list of folders (optionally under a parent)."""
    if parent_id:
        q = f'{{ folderList(parentId: "{parent_id}") {{ list {{ id name type hasDocuments hasFolders }} }} }}'
    else:
        q = "{ folderList { list { id name type hasDocuments hasFolders } } }"
    data = _graphql(q)
    if data and "folderList" in data:
        return data["folderList"].get("list", [])
    return []


def get_documents(folder_id: str, page_size: int = 50,
                  offset_key: str | None = None) -> dict:
    """Get documents in a folder. Returns {list, hasMore, offsetKey}."""
    if offset_key:
        q = f'''{{ documentList(folderId: "{folder_id}", pageSize: {page_size}, offsetKey: "{offset_key}") {{
            list {{ id number regDate shortContent isViewed category categoryName documentKind pageCount }}
            hasMore
        }} }}'''
    else:
        q = f'''{{ documentList(folderId: "{folder_id}", pageSize: {page_size}) {{
            list {{ id number regDate shortContent isViewed category categoryName documentKind pageCount }}
            hasMore
        }} }}'''
    data = _graphql(q)
    if data and "documentList" in data:
        dl = data["documentList"]
        return {
            "list": dl.get("list", []),
            "hasMore": dl.get("hasMore", False),
        }
    return {"list": [], "hasMore": False}


def get_document(doc_id: str) -> dict | None:
    """Get single document details."""
    q = f'''{{ document(id: "{doc_id}") {{
        id number regDate shortContent category categoryName
        documentKind pageCount hasContent
    }} }}'''
    data = _graphql(q)
    if data and "document" in data:
        return data["document"]
    return None


def search_documents(keyword: str, page_size: int = 50) -> list[dict]:
    """Search documents by keyword (number, content)."""
    q = """query($keyword: String) {
        documentListFiltered(pageSize: $ps, filter: { keyword: $keyword }) {
            list { id number regDate shortContent isViewed category categoryName pageCount }
            hasMore
        }
    }""".replace("$ps", str(page_size))
    data = _graphql(q, variables={"keyword": keyword})
    if data and "documentListFiltered" in data:
        return data["documentListFiltered"].get("list", [])
    return []


def get_resolutions(doc_id: str) -> list[dict]:
    """Get resolutions for a document."""
    q = f'''{{ resolutionList(documentId: "{doc_id}") {{
        list {{
            id text status type action deadline
            author {{ id name }}
            assignee {{ id name }}
        }}
    }} }}'''
    data = _graphql(q)
    if data and "resolutionList" in data:
        rlist = data["resolutionList"].get("list", [])
        # Flatten author/assignee into top-level fields
        result = []
        for r in rlist:
            flat = dict(r)
            author = flat.pop("author", {}) or {}
            assignee = flat.pop("assignee", {}) or {}
            flat["author_name"] = author.get("name", "")
            flat["author_id"] = author.get("id", "")
            flat["assignee_name"] = assignee.get("name", "")
            flat["assignee_id"] = assignee.get("id", "")
            result.append(flat)
        return result
    return []


def get_pages(doc_id: str, page_size: int = 50) -> list[dict]:
    """Get document pages with OCR text."""
    q = f'''{{ documentPages(documentId: "{doc_id}", pageSize: {page_size}, pageNumber: 1, offset: 0) {{
        list {{ n url content width height }}
    }} }}'''
    data = _graphql(q)
    if data and "documentPages" in data:
        return data["documentPages"].get("list", [])
    return []


def get_card(doc_id: str, category: str = "") -> dict | None:
    """Get document card (full metadata)."""
    if category:
        q = f'{{ card(documentId: "{doc_id}", category: "{category}") }}'
    else:
        q = f'{{ card(documentId: "{doc_id}") }}'
    data = _graphql(q)
    if data and "card" in data:
        card = data["card"]
        if isinstance(card, str):
            try:
                return json.loads(card)
            except json.JSONDecodeError:
                return {"raw": card}
        return card
    return None


def get_counters() -> dict | None:
    """Get SED counters (unread counts etc)."""
    data = _graphql("{ counters }")
    if data and "counters" in data:
        return data["counters"]
    return None


def check_connectivity() -> dict:
    """Check if sed-proxy and SED server are reachable."""
    proxy = get_proxy_url()
    result = {"proxy": False, "sed": False, "auth": False}
    try:
        resp = requests.get(f"{proxy}/health", timeout=5)
        result["proxy"] = resp.status_code == 200
    except Exception:
        return result

    try:
        resp = requests.get(f"{proxy}/alive", timeout=15)
        dnsid = _parse_dnsid(resp.text)
        result["sed"] = bool(dnsid)
    except Exception:
        return result

    result["auth"] = authenticate(force=True)
    return result
