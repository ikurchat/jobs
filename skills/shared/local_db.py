"""Local SQLite client — drop-in replacement for Baserow REST client.

Same CLI interface as baserow.py:
    python -m services.local_db list <table_name> [--filter '{"field": "value"}'] [--search text] [--order field] [--limit N]
    python -m services.local_db get <table_name> <row_id>
    python -m services.local_db create <table_name> --data '{"field": "value"}'
    python -m services.local_db update <table_name> <row_id> --data '{"field": "value"}'
    python -m services.local_db delete <table_name> <row_id>
    python -m services.local_db batch_create <table_name> --data '[{...}, ...]'
    python -m services.local_db batch_update <table_name> --data '[{"id": 1, ...}, ...]'

Table names are mapped to SQLite table names with br_ prefix.
For backward compatibility, Baserow table IDs are also accepted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Table ID → name mapping (backward compat with Baserow IDs in SKILL.md)
# ---------------------------------------------------------------------------

TABLE_ID_MAP: dict[int, str] = {
    833857: "br_employees",
    833858: "br_shift_schedule",
    833859: "br_tasks",
    833860: "br_plan_items",
    833861: "br_regulatory_tracks",
    833862: "br_task_log",
    833863: "br_skill_updates",  # not created but mapped
    833864: "br_settings",       # not created but mapped
    848121: "br_email_inbox",
    848122: "br_email_feedback",
    848123: "br_sender_profiles",
    851056: "br_formulation_memory",
}

TABLE_NAME_MAP: dict[str, str] = {
    "employees": "br_employees",
    "shift_schedule": "br_shift_schedule",
    "tasks": "br_tasks",
    "plan_items": "br_plan_items",
    "regulatory_tracks": "br_regulatory_tracks",
    "task_log": "br_task_log",
    "sender_profiles": "br_sender_profiles",
    "formulation_memory": "br_formulation_memory",
}


def _resolve_table(table_ref: str | int) -> str:
    """Resolve table reference to SQLite table name."""
    if isinstance(table_ref, int) or (isinstance(table_ref, str) and table_ref.isdigit()):
        table_id = int(table_ref)
        name = TABLE_ID_MAP.get(table_id)
        if not name:
            raise RuntimeError(f"Unknown table ID: {table_id}")
        return name

    ref = str(table_ref).lower().strip()
    if ref.startswith("br_"):
        return ref
    return TABLE_NAME_MAP.get(ref, f"br_{ref}")


def _get_db_path() -> str:
    """Get path to SQLite database."""
    data_dir = os.environ.get("DATA_DIR", "/data")
    return os.path.join(data_dir, "db.sqlite")


def _get_connection() -> sqlite3.Connection:
    """Create SQLite connection with row factory."""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def output_json(data: dict | list) -> None:
    """Print JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def output_error(message: str, code: int = 1) -> None:
    """Print error JSON to stderr and exit."""
    print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dict, parsing JSON fields."""
    d = dict(row)
    for key, val in d.items():
        if isinstance(val, str) and val.startswith(("{", "[")):
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                pass
    return d


def _get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Get column names for a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CRUD operations — same signatures as baserow.py
# ---------------------------------------------------------------------------

def list_rows(
    table_id: int | str,
    filters: dict[str, Any] | None = None,
    search: str | None = None,
    order_by: str | None = None,
    limit: int = 100,
    offset: int = 0,
    token: str | None = None,
) -> dict:
    """List rows with optional filtering, search, ordering, pagination.

    Returns Baserow-compatible response: {count, next, previous, results}.
    """
    table = _resolve_table(table_id)
    conn = _get_connection()
    try:
        columns = _get_columns(conn, table)

        where_clauses = []
        params: list[Any] = []

        # Filters
        if filters:
            for field, value in filters.items():
                if field not in columns:
                    continue
                if isinstance(value, dict):
                    for op, val in value.items():
                        if op == "equal":
                            where_clauses.append(f"{field} = ?")
                            params.append(val)
                        elif op == "not_equal":
                            where_clauses.append(f"{field} != ?")
                            params.append(val)
                        elif op == "contains":
                            where_clauses.append(f"{field} LIKE ?")
                            params.append(f"%{val}%")
                        elif op in ("higher_than", "gt"):
                            where_clauses.append(f"{field} > ?")
                            params.append(val)
                        elif op in ("lower_than", "lt"):
                            where_clauses.append(f"{field} < ?")
                            params.append(val)
                        elif op == "date_after":
                            where_clauses.append(f"{field} >= ?")
                            params.append(val)
                        elif op == "date_before":
                            where_clauses.append(f"{field} <= ?")
                            params.append(val)
                else:
                    where_clauses.append(f"{field} = ?")
                    params.append(value)

        # Search — search across all TEXT columns
        if search:
            search_clauses = []
            for col in columns:
                search_clauses.append(f"{col} LIKE ?")
                params.append(f"%{search}%")
            if search_clauses:
                where_clauses.append(f"({' OR '.join(search_clauses)})")

        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Count
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM {table}{where_sql}", params
        ).fetchone()
        count = count_row[0] if count_row else 0

        # Order
        order_sql = ""
        if order_by:
            # Support "-field" for DESC
            if order_by.startswith("-"):
                order_sql = f" ORDER BY {order_by[1:]} DESC"
            elif order_by.startswith("+"):
                order_sql = f" ORDER BY {order_by[1:]} ASC"
            else:
                order_sql = f" ORDER BY {order_by} ASC"
        else:
            order_sql = " ORDER BY id ASC"

        # Pagination
        limit_sql = f" LIMIT {limit} OFFSET {offset}"

        rows = conn.execute(
            f"SELECT * FROM {table}{where_sql}{order_sql}{limit_sql}", params
        ).fetchall()

        results = [_row_to_dict(r) for r in rows]

        # Baserow-compatible pagination
        has_next = (offset + limit) < count
        return {
            "count": count,
            "next": has_next,
            "previous": offset > 0,
            "results": results,
        }
    finally:
        conn.close()


def list_all_rows(
    table_id: int | str,
    filters: dict[str, Any] | None = None,
    search: str | None = None,
    order_by: str | None = None,
    token: str | None = None,
) -> list[dict]:
    """Fetch all rows. Returns flat list of row dicts."""
    table = _resolve_table(table_id)
    conn = _get_connection()
    try:
        columns = _get_columns(conn, table)

        where_clauses = []
        params: list[Any] = []

        if filters:
            for field, value in filters.items():
                if field not in columns:
                    continue
                if isinstance(value, dict):
                    for op, val in value.items():
                        if op == "equal":
                            where_clauses.append(f"{field} = ?")
                            params.append(val)
                        elif op == "contains":
                            where_clauses.append(f"{field} LIKE ?")
                            params.append(f"%{val}%")
                        elif op in ("higher_than", "gt"):
                            where_clauses.append(f"{field} > ?")
                            params.append(val)
                        elif op in ("lower_than", "lt"):
                            where_clauses.append(f"{field} < ?")
                            params.append(val)
                        elif op == "date_after":
                            where_clauses.append(f"{field} >= ?")
                            params.append(val)
                        elif op == "date_before":
                            where_clauses.append(f"{field} <= ?")
                            params.append(val)
                else:
                    where_clauses.append(f"{field} = ?")
                    params.append(value)

        if search:
            search_clauses = []
            for col in columns:
                search_clauses.append(f"{col} LIKE ?")
                params.append(f"%{search}%")
            if search_clauses:
                where_clauses.append(f"({' OR '.join(search_clauses)})")

        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        order_sql = ""
        if order_by:
            if order_by.startswith("-"):
                order_sql = f" ORDER BY {order_by[1:]} DESC"
            elif order_by.startswith("+"):
                order_sql = f" ORDER BY {order_by[1:]} ASC"
            else:
                order_sql = f" ORDER BY {order_by} ASC"
        else:
            order_sql = " ORDER BY id ASC"

        rows = conn.execute(
            f"SELECT * FROM {table}{where_sql}{order_sql}", params
        ).fetchall()

        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_row(table_id: int | str, row_id: int, token: str | None = None) -> dict:
    """Get a single row by ID."""
    table = _resolve_table(table_id)
    conn = _get_connection()
    try:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Row {row_id} not found in {table}")
        return _row_to_dict(row)
    finally:
        conn.close()


def create_row(table_id: int | str, data: dict, token: str | None = None) -> dict:
    """Create a new row. Returns created row."""
    table = _resolve_table(table_id)
    conn = _get_connection()
    try:
        columns = _get_columns(conn, table)
        # Filter to only valid columns, skip 'id'
        filtered = {}
        for k, v in data.items():
            if k == "id":
                continue
            if k in columns:
                if isinstance(v, (dict, list)):
                    filtered[k] = json.dumps(v, ensure_ascii=False)
                else:
                    filtered[k] = v

        # Add timestamps
        now = _now_iso()
        if "created_at" in columns and "created_at" not in filtered:
            filtered["created_at"] = now
        if "updated_at" in columns and "updated_at" not in filtered:
            filtered["updated_at"] = now

        cols = ", ".join(filtered.keys())
        placeholders = ", ".join("?" for _ in filtered)
        values = list(filtered.values())

        cursor = conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values
        )
        conn.commit()
        row_id = cursor.lastrowid
        return get_row(table_id, row_id)
    finally:
        conn.close()


def update_row(
    table_id: int | str, row_id: int, data: dict, token: str | None = None
) -> dict:
    """Update an existing row. Returns updated row."""
    table = _resolve_table(table_id)
    conn = _get_connection()
    try:
        columns = _get_columns(conn, table)
        filtered = {}
        for k, v in data.items():
            if k == "id":
                continue
            if k in columns:
                if isinstance(v, (dict, list)):
                    filtered[k] = json.dumps(v, ensure_ascii=False)
                else:
                    filtered[k] = v

        if "updated_at" in columns:
            filtered["updated_at"] = _now_iso()

        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [row_id]

        conn.execute(f"UPDATE {table} SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return get_row(table_id, row_id)
    finally:
        conn.close()


def delete_row(table_id: int | str, row_id: int, token: str | None = None) -> dict:
    """Delete a row."""
    table = _resolve_table(table_id)
    conn = _get_connection()
    try:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        conn.commit()
        return {"deleted": True, "row_id": row_id}
    finally:
        conn.close()


def batch_create(
    table_id: int | str, items: list[dict], token: str | None = None
) -> dict:
    """Batch create rows. Returns {items: [created rows]}."""
    created = []
    for item in items:
        row = create_row(table_id, item)
        created.append(row)
    return {"items": created}


def batch_update(
    table_id: int | str, items: list[dict], token: str | None = None
) -> dict:
    """Batch update rows. Each item must have 'id' field."""
    updated = []
    for item in items:
        row_id = item.get("id")
        if not row_id:
            continue
        data = {k: v for k, v in item.items() if k != "id"}
        row = update_row(table_id, row_id, data)
        updated.append(row)
    return {"items": updated}


# Backward compat stubs
def get_baserow_url() -> str:
    return "sqlite://local"

def get_baserow_token() -> str:
    return "local"

MAX_RETRIES = 1
BACKOFF_BASE = 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Local SQLite client (Baserow replacement)")
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List rows")
    p_list.add_argument("table", type=str)
    p_list.add_argument("--filter", type=str, default=None, help="JSON filter dict")
    p_list.add_argument("--search", type=str, default=None)
    p_list.add_argument("--order", type=str, default=None)
    p_list.add_argument("--limit", type=int, default=100)
    p_list.add_argument("--all", action="store_true", help="Fetch all rows")

    # get
    p_get = sub.add_parser("get", help="Get single row")
    p_get.add_argument("table", type=str)
    p_get.add_argument("row_id", type=int)

    # create
    p_create = sub.add_parser("create", help="Create row")
    p_create.add_argument("table", type=str)
    p_create.add_argument("--data", type=str, required=True, help="JSON row data")

    # update
    p_update = sub.add_parser("update", help="Update row")
    p_update.add_argument("table", type=str)
    p_update.add_argument("row_id", type=int)
    p_update.add_argument("--data", type=str, required=True, help="JSON row data")

    # delete
    p_delete = sub.add_parser("delete", help="Delete row")
    p_delete.add_argument("table", type=str)
    p_delete.add_argument("row_id", type=int)

    # batch_create
    p_bcreate = sub.add_parser("batch_create", help="Batch create rows")
    p_bcreate.add_argument("table", type=str)
    p_bcreate.add_argument("--data", type=str, required=True)

    # batch_update
    p_bupdate = sub.add_parser("batch_update", help="Batch update rows")
    p_bupdate.add_argument("table", type=str)
    p_bupdate.add_argument("--data", type=str, required=True)

    args = parser.parse_args()

    try:
        if args.command == "list":
            filters = json.loads(args.filter) if args.filter else None
            if args.all:
                result = list_all_rows(
                    args.table, filters=filters, search=args.search,
                    order_by=args.order,
                )
            else:
                result = list_rows(
                    args.table, filters=filters, search=args.search,
                    order_by=args.order, limit=args.limit,
                )
            output_json(result)

        elif args.command == "get":
            result = get_row(args.table, args.row_id)
            output_json(result)

        elif args.command == "create":
            data = json.loads(args.data)
            result = create_row(args.table, data)
            output_json(result)

        elif args.command == "update":
            data = json.loads(args.data)
            result = update_row(args.table, args.row_id, data)
            output_json(result)

        elif args.command == "delete":
            delete_row(args.table, args.row_id)
            output_json({"deleted": True, "row_id": args.row_id})

        elif args.command == "batch_create":
            items = json.loads(args.data)
            result = batch_create(args.table, items)
            output_json(result)

        elif args.command == "batch_update":
            items = json.loads(args.data)
            result = batch_update(args.table, items)
            output_json(result)

    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
