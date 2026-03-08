"""SQLite persistence for sed-monitor.

Tables:
  - documents: document metadata (number, date, content, folder, viewed)
  - resolutions: who assigned what to whom on which document
  - document_cards: full card metadata
  - pages: OCR text and image URLs per page
  - sync_log: monitoring sync history
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path("/data/sed_monitor.db")


def get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            number TEXT NOT NULL,
            reg_date TEXT,
            short_content TEXT,
            category TEXT DEFAULT '',
            category_name TEXT DEFAULT '',
            folder_id TEXT,
            folder_name TEXT,
            page_count INTEGER DEFAULT 0,
            is_viewed INTEGER DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            resolution_id TEXT,
            author_name TEXT DEFAULT '',
            author_id TEXT DEFAULT '',
            assignee_name TEXT DEFAULT '',
            assignee_id TEXT DEFAULT '',
            resolution_text TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            status TEXT DEFAULT '',
            resolution_type TEXT DEFAULT '',
            action TEXT DEFAULT '',
            raw_json TEXT DEFAULT '{}',
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
        );

        CREATE TABLE IF NOT EXISTS document_cards (
            doc_id TEXT PRIMARY KEY,
            card_json TEXT NOT NULL DEFAULT '{}',
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
        );

        CREATE TABLE IF NOT EXISTS pages (
            doc_id TEXT NOT NULL,
            page_n INTEGER NOT NULL,
            url TEXT DEFAULT '',
            ocr_text TEXT DEFAULT '',
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (doc_id, page_n),
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            folders_checked INTEGER DEFAULT 0,
            new_documents INTEGER DEFAULT 0,
            new_resolutions INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            error TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_documents_number ON documents(number);
        CREATE INDEX IF NOT EXISTS idx_documents_reg_date ON documents(reg_date);
        CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents(folder_id);
        CREATE INDEX IF NOT EXISTS idx_resolutions_doc ON resolutions(doc_id);
        CREATE INDEX IF NOT EXISTS idx_resolutions_assignee ON resolutions(assignee_name);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Documents CRUD
# ---------------------------------------------------------------------------

def upsert_document(doc: dict) -> bool:
    """Insert or update a document. Returns True if new."""
    conn = get_db()
    now = _now()
    existing = conn.execute(
        "SELECT doc_id FROM documents WHERE doc_id=?", (doc["id"],)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE documents SET
                number=?, reg_date=?, short_content=?, category=?,
                category_name=?, folder_id=?, folder_name=?,
                page_count=?, is_viewed=?, updated_at=?
            WHERE doc_id=?
        """, (
            doc.get("number", ""), doc.get("regDate", ""),
            doc.get("shortContent", ""), doc.get("category", ""),
            doc.get("categoryName", ""), doc.get("folder_id", ""),
            doc.get("folder_name", ""), doc.get("pageCount", 0),
            int(doc.get("isViewed", False)), now, doc["id"],
        ))
        conn.commit()
        conn.close()
        return False

    conn.execute("""
        INSERT INTO documents
        (doc_id, number, reg_date, short_content, category, category_name,
         folder_id, folder_name, page_count, is_viewed, first_seen_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        doc["id"], doc.get("number", ""), doc.get("regDate", ""),
        doc.get("shortContent", ""), doc.get("category", ""),
        doc.get("categoryName", ""), doc.get("folder_id", ""),
        doc.get("folder_name", ""), doc.get("pageCount", 0),
        int(doc.get("isViewed", False)), now, now,
    ))
    conn.commit()
    conn.close()
    return True


def get_document(doc_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def search_documents(query: str, limit: int = 20) -> list[dict]:
    """Search documents by number or content text."""
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM documents
        WHERE number LIKE ? OR short_content LIKE ?
        ORDER BY reg_date DESC LIMIT ?
    """, (f"%{query}%", f"%{query}%", limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unviewed_documents() -> list[dict]:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM documents WHERE is_viewed=0
        ORDER BY reg_date DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_documents(days: int = 7) -> list[dict]:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM documents
        ORDER BY reg_date DESC LIMIT 100
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_documents_by_folder(folder_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM documents WHERE folder_id=?
        ORDER BY reg_date DESC
    """, (folder_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Resolutions CRUD
# ---------------------------------------------------------------------------

def upsert_resolution(doc_id: str, res: dict) -> bool:
    """Insert or update a resolution. Returns True if new."""
    conn = get_db()
    now = _now()
    res_id = res.get("id", "")

    existing = conn.execute(
        "SELECT id FROM resolutions WHERE doc_id=? AND resolution_id=?",
        (doc_id, res_id)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE resolutions SET
                author_name=?, assignee_name=?, resolution_text=?,
                deadline=?, status=?, raw_json=?, updated_at=?
            WHERE id=?
        """, (
            res.get("author_name", ""), res.get("assignee_name", ""),
            res.get("text", ""), res.get("deadline", ""),
            res.get("status", ""), json.dumps(res, ensure_ascii=False),
            now, existing["id"],
        ))
        conn.commit()
        conn.close()
        return False

    conn.execute("""
        INSERT INTO resolutions
        (doc_id, resolution_id, author_name, author_id, assignee_name,
         assignee_id, resolution_text, deadline, status,
         resolution_type, action, raw_json, first_seen_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        doc_id, res_id,
        res.get("author_name", ""), res.get("author_id", ""),
        res.get("assignee_name", ""), res.get("assignee_id", ""),
        res.get("text", ""), res.get("deadline", ""),
        res.get("status", ""), res.get("type", ""),
        res.get("action", ""),
        json.dumps(res, ensure_ascii=False), now, now,
    ))
    conn.commit()
    conn.close()
    return True


def get_resolutions(doc_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM resolutions WHERE doc_id=?
        ORDER BY first_seen_at
    """, (doc_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_my_resolutions(assignee_name: str = "Панков") -> list[dict]:
    """Get all resolutions assigned to me."""
    conn = get_db()
    rows = conn.execute("""
        SELECT r.*, d.number, d.short_content, d.reg_date
        FROM resolutions r
        JOIN documents d ON r.doc_id = d.doc_id
        WHERE r.assignee_name LIKE ?
        ORDER BY r.first_seen_at DESC
    """, (f"%{assignee_name}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def save_pages(doc_id: str, pages: list[dict]) -> int:
    conn = get_db()
    now = _now()
    saved = 0
    for p in pages:
        conn.execute("""
            INSERT OR REPLACE INTO pages (doc_id, page_n, url, ocr_text, fetched_at)
            VALUES (?, ?, ?, ?, ?)
        """, (doc_id, p.get("n", 0), p.get("url", ""), p.get("content", ""), now))
        saved += 1
    conn.commit()
    conn.close()
    return saved


def get_pages(doc_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pages WHERE doc_id=? ORDER BY page_n", (doc_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_document_text(doc_id: str) -> str:
    """Get full OCR text for a document."""
    pages = get_pages(doc_id)
    parts = []
    for p in pages:
        txt = p.get("ocr_text", "")
        if txt:
            parts.append(f"--- Страница {p['page_n'] + 1} ---\n{txt}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def save_card(doc_id: str, card_data: dict) -> None:
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO document_cards (doc_id, card_json, fetched_at)
        VALUES (?, ?, ?)
    """, (doc_id, json.dumps(card_data, ensure_ascii=False), _now()))
    conn.commit()
    conn.close()


def get_card(doc_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM document_cards WHERE doc_id=?", (doc_id,)
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["card"] = json.loads(d.pop("card_json", "{}"))
        return d
    return None


# ---------------------------------------------------------------------------
# Sync Log
# ---------------------------------------------------------------------------

def start_sync(sync_type: str = "scheduled") -> int:
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO sync_log (sync_type, started_at, status)
        VALUES (?, ?, 'running')
    """, (sync_type, _now()))
    conn.commit()
    sync_id = cursor.lastrowid
    conn.close()
    return sync_id


def finish_sync(sync_id: int, folders: int = 0, new_docs: int = 0,
                new_res: int = 0, error: str = "") -> None:
    conn = get_db()
    status = "error" if error else "ok"
    conn.execute("""
        UPDATE sync_log SET
            finished_at=?, folders_checked=?, new_documents=?,
            new_resolutions=?, status=?, error=?
        WHERE id=?
    """, (_now(), folders, new_docs, new_res, status, error, sync_id))
    conn.commit()
    conn.close()


def get_last_sync() -> dict | None:
    conn = get_db()
    row = conn.execute("""
        SELECT * FROM sync_log ORDER BY id DESC LIMIT 1
    """).fetchone()
    conn.close()
    return dict(row) if row else None


def get_stats() -> dict:
    conn = get_db()
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    res = conn.execute("SELECT COUNT(*) FROM resolutions").fetchone()[0]
    pages = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    unviewed = conn.execute("SELECT COUNT(*) FROM documents WHERE is_viewed=0").fetchone()[0]
    conn.close()
    return {
        "total_documents": docs,
        "total_resolutions": res,
        "total_pages": pages,
        "unviewed": unviewed,
    }
