"""Load plan items and task data from SQLite for a given period.

CLI usage:
    python -m services.data_loader pull --period-start 2026-02-17 --period-end 2026-02-21
    python -m services.data_loader pull --period-start 2026-02-01 --period-end 2026-02-28 --type monthly
    python -m services.data_loader plan_items --period-start 2026-02-17 --period-end 2026-02-21
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime

from config.settings import load_config, output_error, output_json
from services.db import get_plan_items, get_active_plan_items, get_all_formulations_as_dict


# ---------------------------------------------------------------------------
# Core loaders
# ---------------------------------------------------------------------------

def load_plan_items_for_period(
    period_start: date,
    period_end: date,
) -> list[dict]:
    """Load plan items for a specific period from SQLite."""
    return get_plan_items(str(period_start), str(period_end))


def load_active_tasks() -> list[dict]:
    """Load all active plan items (in_progress/planned/carried_over)."""
    return get_active_plan_items()


def load_all_data(
    config: dict,
    period_start: date,
    period_end: date,
) -> dict:
    """Load all data needed for plan/report generation."""
    plan_items = load_plan_items_for_period(period_start, period_end)
    active = load_active_tasks()

    return {
        "plan_items": plan_items,
        "active_tasks": active,
        "period_start": str(period_start),
        "period_end": str(period_end),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str) -> date:
    """Parse date from string (supports ISO, dd.mm.yyyy)."""
    value = value.strip()
    if not value:
        raise ValueError("Empty date")

    # ISO format: 2026-02-17 or 2026-02-17T...
    if "-" in value and len(value) >= 10:
        return datetime.fromisoformat(value[:10]).date()

    # dd.mm.yyyy
    if "." in value:
        parts = value.split(".")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))

    raise ValueError(f"Cannot parse date: {value}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Data loader for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", help="Pull all data for period")
    p_pull.add_argument("--period-start", required=True, help="YYYY-MM-DD")
    p_pull.add_argument("--period-end", required=True, help="YYYY-MM-DD")
    p_pull.add_argument("--type", default="weekly", choices=["weekly", "monthly"])

    p_items = sub.add_parser("plan_items", help="Pull plan items only")
    p_items.add_argument("--period-start", required=True, help="YYYY-MM-DD")
    p_items.add_argument("--period-end", required=True, help="YYYY-MM-DD")

    args = parser.parse_args()
    config = load_config()

    try:
        start = _parse_date(args.period_start)
        end = _parse_date(args.period_end)

        if args.command == "pull":
            result = load_all_data(config, start, end)
            output_json(result)

        elif args.command == "plan_items":
            items = load_plan_items_for_period(start, end)
            output_json(items)

    except (RuntimeError, ValueError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
