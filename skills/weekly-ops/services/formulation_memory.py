"""Formulation memory — thin wrapper over db.py for CLI compatibility.

All persistence logic lives in services.db (SQLite).

CLI usage:
    python -m services.formulation_memory list
    python -m services.formulation_memory search --text "мониторинг событий ИБ"
    python -m services.formulation_memory save --pattern "мониторинг ИБ" --done-text "Выполнено."
    python -m services.formulation_memory get_all_as_dict
"""

from __future__ import annotations

import argparse
import json

from config.settings import load_config, output_error, output_json
from services.db import (
    search_formulation,
    save_formulation,
    get_all_formulations_as_dict,
    bulk_save_formulations,
    get_db,
)


def list_all() -> list[dict]:
    """List all formulations from SQLite."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM formulation_memory ORDER BY use_count DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Formulation memory for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all formulations")

    p_search = sub.add_parser("search", help="Search formulation by text")
    p_search.add_argument("--text", required=True)

    p_save = sub.add_parser("save", help="Save formulation")
    p_save.add_argument("--pattern", required=True)
    p_save.add_argument("--done-text", default="")
    p_save.add_argument("--in-progress-text", default="")
    p_save.add_argument("--variables", default="{}", help="JSON dict of variables")

    sub.add_parser("get_all_as_dict", help="Get all as {pattern: done_text} dict")

    args = parser.parse_args()

    try:
        if args.command == "list":
            output_json(list_all())

        elif args.command == "search":
            result = search_formulation(args.text)
            if result:
                output_json(result)
            else:
                output_json({"match": None, "text": args.text})

        elif args.command == "save":
            result = save_formulation(
                args.pattern, args.done_text, args.in_progress_text, args.variables
            )
            output_json(result)

        elif args.command == "get_all_as_dict":
            result = get_all_formulations_as_dict()
            output_json(result)

    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
