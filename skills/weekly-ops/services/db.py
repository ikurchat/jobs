"""SQLite persistence layer for weekly-ops.

Replaces Baserow. Stores plan items, report items, formulation memory,
version history, and owner feedback.

DB path: /data/weekly_ops.db
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path("/data/weekly_ops.db")


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
        CREATE TABLE IF NOT EXISTS plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            period_type TEXT NOT NULL DEFAULT 'weekly',
            item_number INTEGER NOT NULL,
            description TEXT NOT NULL,
            deadline TEXT DEFAULT '',
            responsible TEXT DEFAULT '',
            completion_note TEXT DEFAULT '',
            status TEXT DEFAULT 'planned',
            is_unplanned INTEGER DEFAULT 0,
            linked_task_ids TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plan_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            period_type TEXT NOT NULL DEFAULT 'weekly',
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'draft',
            items_json TEXT NOT NULL,
            total_items INTEGER DEFAULT 0,
            approved_at TEXT,
            docx_path TEXT,
            feedback_summary TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            period_type TEXT NOT NULL DEFAULT 'weekly',
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'draft',
            items_json TEXT NOT NULL,
            total_planned INTEGER DEFAULT 0,
            total_unplanned INTEGER DEFAULT 0,
            approved_at TEXT,
            docx_path TEXT,
            feedback_summary TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS formulation_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_pattern TEXT NOT NULL,
            status_done_text TEXT DEFAULT '',
            status_in_progress_text TEXT DEFAULT '',
            variables TEXT DEFAULT '{}',
            use_count INTEGER DEFAULT 0,
            last_used TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feedback_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            action TEXT NOT NULL,
            item_number INTEGER,
            old_text TEXT DEFAULT '',
            new_text TEXT DEFAULT '',
            owner_comment TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_plan_items_period
            ON plan_items(period_start, period_end);
        CREATE INDEX IF NOT EXISTS idx_plan_versions_period
            ON plan_versions(period_start, period_end);
        CREATE INDEX IF NOT EXISTS idx_report_versions_period
            ON report_versions(period_start, period_end);
        CREATE INDEX IF NOT EXISTS idx_feedback_period
            ON feedback_log(period_start, period_end);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Plan Items CRUD
# ---------------------------------------------------------------------------

def save_plan_items(items: list[dict], period_start: str, period_end: str,
                    period_type: str = "weekly") -> int:
    """Save plan items for a period. Replaces existing items for same period."""
    conn = get_db()
    now = _now()
    # Clear old items for this period
    conn.execute(
        "DELETE FROM plan_items WHERE period_start=? AND period_end=?",
        (period_start, period_end)
    )
    for i, item in enumerate(items, 1):
        conn.execute(
            """INSERT INTO plan_items
               (period_start, period_end, period_type, item_number,
                description, deadline, responsible, completion_note,
                status, is_unplanned, linked_task_ids, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (period_start, period_end, period_type, i,
             item.get("description", ""),
             item.get("deadline", ""),
             item.get("responsible", ""),
             item.get("completion_note", ""),
             item.get("status", "planned"),
             int(item.get("is_unplanned", False)),
             json.dumps(item.get("linked_task_ids", []), ensure_ascii=False),
             now, now)
        )
    conn.commit()
    count = len(items)
    conn.close()
    return count


def get_plan_items(period_start: str, period_end: str) -> list[dict]:
    """Get plan items for a period."""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM plan_items
           WHERE period_start=? AND period_end=?
           ORDER BY item_number""",
        (period_start, period_end)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["linked_task_ids"] = json.loads(d.get("linked_task_ids", "[]"))
        d["is_unplanned"] = bool(d.get("is_unplanned", 0))
        result.append(d)
    return result


def get_active_plan_items() -> list[dict]:
    """Get all plan items with status in_progress/planned (for carrying over)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM plan_items
           WHERE status IN ('planned', 'in_progress', 'carried_over')
           ORDER BY period_start DESC, item_number"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_plan_item_status(item_id: int, status: str,
                            completion_note: str = "") -> bool:
    conn = get_db()
    updates = {"status": status, "updated_at": _now()}
    if completion_note:
        updates["completion_note"] = completion_note
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(
        f"UPDATE plan_items SET {set_clause} WHERE id=?",
        (*updates.values(), item_id)
    )
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Plan/Report Versions
# ---------------------------------------------------------------------------

def save_plan_version(period_start: str, period_end: str,
                      period_type: str, items: list[dict],
                      status: str = "draft",
                      docx_path: str = "") -> int:
    """Save a version of the plan. Returns version number."""
    conn = get_db()
    # Get next version number
    row = conn.execute(
        """SELECT MAX(version) as max_v FROM plan_versions
           WHERE period_start=? AND period_end=?""",
        (period_start, period_end)
    ).fetchone()
    version = (row["max_v"] or 0) + 1

    conn.execute(
        """INSERT INTO plan_versions
           (period_start, period_end, period_type, version, status,
            items_json, total_items, docx_path, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (period_start, period_end, period_type, version, status,
         json.dumps(items, ensure_ascii=False), len(items),
         docx_path, _now())
    )
    conn.commit()
    conn.close()
    return version


def approve_plan_version(period_start: str, period_end: str,
                         version: int, feedback: str = "") -> bool:
    conn = get_db()
    conn.execute(
        """UPDATE plan_versions
           SET status='approved', approved_at=?, feedback_summary=?
           WHERE period_start=? AND period_end=? AND version=?""",
        (_now(), feedback, period_start, period_end, version)
    )
    conn.commit()
    conn.close()
    return True


def get_latest_plan_version(period_start: str, period_end: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM plan_versions
           WHERE period_start=? AND period_end=?
           ORDER BY version DESC LIMIT 1""",
        (period_start, period_end)
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["items"] = json.loads(d.pop("items_json", "[]"))
        return d
    return None


def save_report_version(period_start: str, period_end: str,
                        period_type: str, items: list[dict],
                        status: str = "draft",
                        docx_path: str = "") -> int:
    conn = get_db()
    row = conn.execute(
        """SELECT MAX(version) as max_v FROM report_versions
           WHERE period_start=? AND period_end=?""",
        (period_start, period_end)
    ).fetchone()
    version = (row["max_v"] or 0) + 1

    planned = [i for i in items if not i.get("is_unplanned")]
    unplanned = [i for i in items if i.get("is_unplanned")]

    conn.execute(
        """INSERT INTO report_versions
           (period_start, period_end, period_type, version, status,
            items_json, total_planned, total_unplanned, docx_path, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (period_start, period_end, period_type, version, status,
         json.dumps(items, ensure_ascii=False), len(planned), len(unplanned),
         docx_path, _now())
    )
    conn.commit()
    conn.close()
    return version


def get_latest_report_version(period_start: str, period_end: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM report_versions
           WHERE period_start=? AND period_end=?
           ORDER BY version DESC LIMIT 1""",
        (period_start, period_end)
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["items"] = json.loads(d.pop("items_json", "[]"))
        return d
    return None


# ---------------------------------------------------------------------------
# Feedback Log
# ---------------------------------------------------------------------------

def log_feedback(period_start: str, period_end: str, doc_type: str,
                 action: str, item_number: int = 0,
                 old_text: str = "", new_text: str = "",
                 owner_comment: str = "") -> int:
    """Log owner feedback: edit, delete, add, approve, reject.

    Actions: edit, delete, add, approve_block, approve_all, rewrite
    """
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO feedback_log
           (period_start, period_end, doc_type, action,
            item_number, old_text, new_text, owner_comment, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (period_start, period_end, doc_type, action,
         item_number, old_text, new_text, owner_comment, _now())
    )
    conn.commit()
    feedback_id = cursor.lastrowid
    conn.close()
    return feedback_id


def get_feedback_stats(period_start: str = "", period_end: str = "") -> dict:
    """Get feedback stats, optionally filtered by period."""
    conn = get_db()
    if period_start and period_end:
        rows = conn.execute(
            """SELECT action, COUNT(*) as cnt FROM feedback_log
               WHERE period_start=? AND period_end=?
               GROUP BY action""",
            (period_start, period_end)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT action, COUNT(*) as cnt FROM feedback_log GROUP BY action"
        ).fetchall()
    conn.close()
    return {r["action"]: r["cnt"] for r in rows}


# ---------------------------------------------------------------------------
# Formulation Memory
# ---------------------------------------------------------------------------

def search_formulation(text: str, threshold: float = 0.6) -> dict | None:
    """Find best matching formulation by keyword overlap."""
    words = _significant_words(text)
    if not words:
        return None

    conn = get_db()
    rows = conn.execute("SELECT * FROM formulation_memory").fetchall()
    conn.close()

    best = None
    best_score = 0.0
    for row in rows:
        pattern_words = _significant_words(row["task_pattern"])
        if not pattern_words:
            continue
        overlap = len(words & pattern_words) / max(len(words), len(pattern_words))
        if overlap >= threshold and overlap > best_score:
            best_score = overlap
            best = dict(row)

    return best


def save_formulation(task_pattern: str, status_done_text: str = "",
                     status_in_progress_text: str = "",
                     variables: str = "{}") -> dict:
    """Save or update a formulation."""
    conn = get_db()
    now = _now()

    # Check for existing match (threshold 0.8 for dedup)
    existing = search_formulation(task_pattern, threshold=0.8)
    if existing:
        conn.execute(
            """UPDATE formulation_memory
               SET status_done_text=COALESCE(NULLIF(?, ''), status_done_text),
                   status_in_progress_text=COALESCE(NULLIF(?, ''), status_in_progress_text),
                   variables=?, use_count=use_count+1,
                   last_used=?, updated_at=?
               WHERE id=?""",
            (status_done_text, status_in_progress_text, variables,
             now, now, existing["id"])
        )
        conn.commit()
        conn.close()
        return {"status": "updated", "id": existing["id"]}

    conn.execute(
        """INSERT INTO formulation_memory
           (task_pattern, status_done_text, status_in_progress_text,
            variables, use_count, last_used, created_at, updated_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
        (task_pattern, status_done_text, status_in_progress_text,
         variables, now, now, now)
    )
    conn.commit()
    conn.close()
    return {"status": "created"}


def get_all_formulations_as_dict() -> dict:
    """Returns {task_pattern: status_done_text} for report builder."""
    conn = get_db()
    rows = conn.execute(
        "SELECT task_pattern, status_done_text FROM formulation_memory"
    ).fetchall()
    conn.close()
    return {r["task_pattern"]: r["status_done_text"] for r in rows}


def bulk_save_formulations(approved_items: list[dict]) -> int:
    """Batch-save formulations from approved report items."""
    saved = 0
    for item in approved_items:
        desc = item.get("description", "")
        mark = item.get("completion_note", "")
        if not desc or not mark or mark.startswith("["):
            continue
        done_text = ""
        ip_text = ""
        if mark.startswith("Выполнено") or mark.startswith("выполнено"):
            done_text = mark
        elif mark.startswith("В работе") or mark.startswith("в работе"):
            ip_text = mark
        else:
            done_text = mark
        save_formulation(desc, done_text, ip_text)
        saved += 1
    return saved


def _significant_words(text: str, min_len: int = 3) -> set[str]:
    import re
    return {w.lower() for w in re.findall(r"\w+", text) if len(w) > min_len}
