"""Generic Baserow REST client — CRUD, filter, batch, paginate.

CLI usage:
    python -m services.baserow list <table_id> [--filter '{"field": "value"}'] [--search text] [--order field] [--limit N]
    python -m services.baserow get <table_id> <row_id>
    python -m services.baserow create <table_id> --data '{"field": "value"}'
    python -m services.baserow update <table_id> <row_id> --data '{"field": "value"}'
    python -m services.baserow delete <table_id> <row_id>
    python -m services.baserow batch_create <table_id> --data '[{...}, ...]'
    python -m services.baserow batch_update <table_id> --data '[{"id": 1, ...}, ...]'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from config.settings import get_baserow_token, get_baserow_url, output_error, output_json

# Max retries for 429/5xx errors
MAX_RETRIES = 3
BACKOFF_BASE = 1.0  # seconds


def _make_request(
    method: str,
    url: str,
    data: dict | list | None = None,
    token: str | None = None,
) -> dict | list:
    """Make HTTP request to Baserow API with retry on 429/5xx."""
    _token = token or get_baserow_token()
    headers = {
        "Authorization": f"Token {_token}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8") if data is not None else None

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read().decode("utf-8")
                if not resp_body:
                    return {}
                return json.loads(resp_body)
        except urllib.error.HTTPError as e:
            status = e.code
            if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE * (2 ** attempt)
                time.sleep(wait)
                continue
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Baserow API error {status}: {error_body[:500]}"
            ) from e
        except urllib.error.URLError as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE * (2 ** attempt))
                continue
            raise RuntimeError(f"Connection error: {e}") from e

    raise RuntimeError("Max retries exceeded")


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def list_rows(
    table_id: int,
    filters: dict[str, Any] | None = None,
    search: str | None = None,
    order_by: str | None = None,
    limit: int = 100,
    offset: int = 0,
    token: str | None = None,
) -> dict:
    """List rows with optional filtering, search, ordering, pagination.

    Returns Baserow paginated response: {count, next, previous, results}.
    """
    base_url = get_baserow_url()
    url = f"{base_url}/api/database/rows/table/{table_id}/"

    params = [f"size={limit}", f"page={offset // limit + 1}" if offset else "page=1"]
    params.append("user_field_names=true")

    if search:
        params.append(f"search={urllib.request.quote(search)}")
    if order_by:
        params.append(f"order_by={urllib.request.quote(order_by)}")

    # Baserow filter syntax: filter__field__type=value
    if filters:
        for field_name, value in filters.items():
            if isinstance(value, dict):
                # {field: {type: value}} → filter__field__type=value
                for filter_type, filter_val in value.items():
                    params.append(
                        f"filter__{urllib.request.quote(field_name)}__{filter_type}="
                        f"{urllib.request.quote(str(filter_val))}"
                    )
            else:
                # Simple equality filter
                params.append(
                    f"filter__{urllib.request.quote(field_name)}__equal="
                    f"{urllib.request.quote(str(value))}"
                )

    url = url + "?" + "&".join(params)
    return _make_request("GET", url, token=token)


def list_all_rows(
    table_id: int,
    filters: dict[str, Any] | None = None,
    search: str | None = None,
    order_by: str | None = None,
    token: str | None = None,
) -> list[dict]:
    """Fetch all rows (auto-paginate). Returns flat list of row dicts."""
    all_rows: list[dict] = []
    page = 1
    while True:
        base_url = get_baserow_url()
        url = f"{base_url}/api/database/rows/table/{table_id}/"
        params = [f"size=200", f"page={page}", "user_field_names=true"]

        if search:
            params.append(f"search={urllib.request.quote(search)}")
        if order_by:
            params.append(f"order_by={urllib.request.quote(order_by)}")
        if filters:
            for field_name, value in filters.items():
                if isinstance(value, dict):
                    for filter_type, filter_val in value.items():
                        params.append(
                            f"filter__{urllib.request.quote(field_name)}__{filter_type}="
                            f"{urllib.request.quote(str(filter_val))}"
                        )
                else:
                    params.append(
                        f"filter__{urllib.request.quote(field_name)}__equal="
                        f"{urllib.request.quote(str(value))}"
                    )

        url = url + "?" + "&".join(params)
        resp = _make_request("GET", url, token=token)
        results = resp.get("results", [])
        all_rows.extend(results)
        if not resp.get("next"):
            break
        page += 1

    return all_rows


def get_row(table_id: int, row_id: int, token: str | None = None) -> dict:
    """Get a single row by ID."""
    base_url = get_baserow_url()
    url = f"{base_url}/api/database/rows/table/{table_id}/{row_id}/?user_field_names=true"
    return _make_request("GET", url, token=token)


def create_row(table_id: int, data: dict, token: str | None = None) -> dict:
    """Create a new row. Returns created row."""
    base_url = get_baserow_url()
    url = f"{base_url}/api/database/rows/table/{table_id}/?user_field_names=true"
    return _make_request("POST", url, data=data, token=token)


def update_row(
    table_id: int, row_id: int, data: dict, token: str | None = None
) -> dict:
    """Update an existing row. Returns updated row."""
    base_url = get_baserow_url()
    url = f"{base_url}/api/database/rows/table/{table_id}/{row_id}/?user_field_names=true"
    return _make_request("PATCH", url, data=data, token=token)


def delete_row(table_id: int, row_id: int, token: str | None = None) -> dict:
    """Delete a row."""
    base_url = get_baserow_url()
    url = f"{base_url}/api/database/rows/table/{table_id}/{row_id}/"
    return _make_request("DELETE", url, token=token)


def batch_create(
    table_id: int, items: list[dict], token: str | None = None
) -> dict:
    """Batch create rows. Returns {items: [created rows]}."""
    base_url = get_baserow_url()
    url = f"{base_url}/api/database/rows/table/{table_id}/batch/?user_field_names=true"
    return _make_request("POST", url, data={"items": items}, token=token)


def batch_update(
    table_id: int, items: list[dict], token: str | None = None
) -> dict:
    """Batch update rows. Each item must have 'id' field. Returns {items: [updated rows]}."""
    base_url = get_baserow_url()
    url = f"{base_url}/api/database/rows/table/{table_id}/batch/?user_field_names=true"
    return _make_request("PATCH", url, data={"items": items}, token=token)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Baserow REST client")
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List rows")
    p_list.add_argument("table_id", type=int)
    p_list.add_argument("--filter", type=str, default=None, help="JSON filter dict")
    p_list.add_argument("--search", type=str, default=None)
    p_list.add_argument("--order", type=str, default=None)
    p_list.add_argument("--limit", type=int, default=100)
    p_list.add_argument("--all", action="store_true", help="Fetch all pages")

    # get
    p_get = sub.add_parser("get", help="Get single row")
    p_get.add_argument("table_id", type=int)
    p_get.add_argument("row_id", type=int)

    # create
    p_create = sub.add_parser("create", help="Create row")
    p_create.add_argument("table_id", type=int)
    p_create.add_argument("--data", type=str, required=True, help="JSON row data")

    # update
    p_update = sub.add_parser("update", help="Update row")
    p_update.add_argument("table_id", type=int)
    p_update.add_argument("row_id", type=int)
    p_update.add_argument("--data", type=str, required=True, help="JSON row data")

    # delete
    p_delete = sub.add_parser("delete", help="Delete row")
    p_delete.add_argument("table_id", type=int)
    p_delete.add_argument("row_id", type=int)

    # batch_create
    p_bcreate = sub.add_parser("batch_create", help="Batch create rows")
    p_bcreate.add_argument("table_id", type=int)
    p_bcreate.add_argument("--data", type=str, required=True, help="JSON array of row dicts")

    # batch_update
    p_bupdate = sub.add_parser("batch_update", help="Batch update rows")
    p_bupdate.add_argument("table_id", type=int)
    p_bupdate.add_argument("--data", type=str, required=True, help="JSON array of row dicts with id")

    args = parser.parse_args()

    try:
        if args.command == "list":
            filters = json.loads(args.filter) if args.filter else None
            if args.all:
                result = list_all_rows(
                    args.table_id, filters=filters, search=args.search,
                    order_by=args.order,
                )
            else:
                result = list_rows(
                    args.table_id, filters=filters, search=args.search,
                    order_by=args.order, limit=args.limit,
                )
            output_json(result)

        elif args.command == "get":
            result = get_row(args.table_id, args.row_id)
            output_json(result)

        elif args.command == "create":
            data = json.loads(args.data)
            result = create_row(args.table_id, data)
            output_json(result)

        elif args.command == "update":
            data = json.loads(args.data)
            result = update_row(args.table_id, args.row_id, data)
            output_json(result)

        elif args.command == "delete":
            delete_row(args.table_id, args.row_id)
            output_json({"deleted": True, "row_id": args.row_id})

        elif args.command == "batch_create":
            items = json.loads(args.data)
            result = batch_create(args.table_id, items)
            output_json(result)

        elif args.command == "batch_update":
            items = json.loads(args.data)
            result = batch_update(args.table_id, items)
            output_json(result)

    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
