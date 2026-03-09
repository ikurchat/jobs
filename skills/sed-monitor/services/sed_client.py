"""HTTP client for СЭД Практика via sed-proxy sidecar.

Token-based auth:
  - Token (DNSID + auth_token) stored in /data/sed_token.json
  - Token lives ~182 days, survives password changes
  - Password NEVER stored — only used interactively to obtain token
  - If token is dead → error, owner re-authenticates manually

All requests go through sed-proxy (plain HTTP), which handles GOST TLS.
"""

import json
import logging
import re
import tempfile
import time
from pathlib import Path

import requests

from config.settings import get_proxy_url, get_token, get_user_id, save_token

log = logging.getLogger("sed-client")

# Session state (in-memory)
_session: requests.Session | None = None
_dnsid: str = ""
_auth_token: str = ""
_token_loaded: bool = False


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
    parts.append(f"last_login_u_id={get_user_id()}")
    return "; ".join(parts)


def _load_token() -> bool:
    """Load token from file into memory. Returns True if loaded."""
    global _dnsid, _auth_token, _token_loaded

    if _token_loaded and _dnsid and _auth_token:
        return True

    token = get_token()
    if not token:
        return False

    _dnsid = token.get("dnsid", "")
    _auth_token = token.get("auth_token", "")
    _token_loaded = bool(_dnsid and _auth_token)
    return _token_loaded


def _check_token_alive() -> bool:
    """Verify current token is still valid by making a test request."""
    if not _dnsid or not _auth_token:
        return False

    proxy = get_proxy_url()
    sess = _get_session()
    try:
        resp = sess.get(
            f"{proxy}/web/?url=mont/auth-code/status",
            headers={"X-SED-Cookies": _cookies_header()},
            timeout=10,
        )
        # Non-empty response (even error) = token alive
        return bool(resp.text.strip())
    except Exception:
        return False


def _ensure_auth() -> bool:
    """Ensure we have a valid token. No password flow — token only."""
    if _load_token():
        return True

    log.error(
        "SED token not found. Run: "
        "python3 $SED token <dnsid> <auth_token>"
    )
    return False


def set_token(dnsid: str, auth_token: str) -> bool:
    """Set token manually (called from CLI after interactive auth)."""
    global _dnsid, _auth_token, _token_loaded

    _dnsid = dnsid
    _auth_token = auth_token
    _token_loaded = True
    save_token(dnsid, auth_token)
    log.info("Token saved")
    return True


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
    """Get documents in a folder. Returns {list, hasMore}."""
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
    q = """query($keyword: String, $ps: Int) {
        documentListFiltered(pageSize: $ps, filter: { keyword: $keyword }) {
            list { id number regDate shortContent isViewed category categoryName pageCount }
            hasMore
        }
    }"""
    data = _graphql(q, variables={"keyword": keyword, "ps": page_size})
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


def download_page_image(url: str, save_to: Path) -> bool:
    """Download a single page image via sed-proxy. Returns True on success."""
    if not _ensure_auth():
        return False

    proxy = get_proxy_url()
    sess = _get_session()
    try:
        resp = sess.get(
            f"{proxy}/file{url}",
            headers={"X-SED-Cookies": _cookies_header()},
            timeout=30,
        )
        if resp.status_code == 200 and len(resp.content) > 100:
            save_to.parent.mkdir(parents=True, exist_ok=True)
            save_to.write_bytes(resp.content)
            return True
        return False
    except Exception as e:
        log.error(f"Failed to download page image: {e}")
        return False


def download_document_pdf(doc_id: str, output_path: Path | None = None) -> Path | None:
    """Download all pages and assemble into PDF."""
    pages = get_pages(doc_id)
    if not pages:
        log.warning(f"No pages for document {doc_id}")
        return None

    with tempfile.TemporaryDirectory(prefix="sed_doc_") as tmpdir:
        image_paths = []
        for p in sorted(pages, key=lambda x: x.get("n", 0)):
            url = p.get("url", "")
            if not url:
                continue
            img_path = Path(tmpdir) / f"page_{p.get('n', 0):03d}.jpg"
            if download_page_image(url, img_path):
                image_paths.append(img_path)
            time.sleep(0.3)

        if not image_paths:
            return None

        if output_path is None:
            output_path = Path(f"/tmp/sed_doc_{doc_id}.pdf")

        try:
            from PIL import Image
            images = [Image.open(p).convert("RGB") for p in image_paths]
            images[0].save(output_path, "PDF", save_all=True,
                           append_images=images[1:])
            return output_path
        except ImportError:
            try:
                import img2pdf
                with open(output_path, "wb") as f:
                    f.write(img2pdf.convert([str(p) for p in image_paths]))
                return output_path
            except ImportError:
                log.error("Neither Pillow nor img2pdf available")
                return None


def check_connectivity() -> dict:
    """Check if sed-proxy and SED server are reachable."""
    proxy = get_proxy_url()
    sess = _get_session()
    result = {"proxy": False, "sed": False, "token": False}
    try:
        resp = sess.get(f"{proxy}/health", timeout=5)
        result["proxy"] = resp.status_code == 200
    except Exception:
        return result

    try:
        resp = sess.get(f"{proxy}/alive", timeout=15)
        result["sed"] = bool(re.search(r"DNSID=", resp.text))
    except Exception:
        return result

    if _load_token():
        result["token"] = _check_token_alive()

    return result
