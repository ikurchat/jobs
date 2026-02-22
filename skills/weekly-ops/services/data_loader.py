"""Load tasks and plan items from Baserow for a given period.

CLI usage:
    python -m services.data_loader pull --period-start 2026-02-17 --period-end 2026-02-21
    python -m services.data_loader pull --period-start 2026-02-01 --period-end 2026-02-28 --type monthly
    python -m services.data_loader plan_items --period-start 2026-02-17 --period-end 2026-02-21
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from config.settings import get_table_id, load_config, output_error, output_json
from services.baserow import list_all_rows


# ---------------------------------------------------------------------------
# Core loaders
# ---------------------------------------------------------------------------

def load_tasks(
    config: dict,
    period_start: date,
    period_end: date,
) -> list[dict]:
    """Load all tasks relevant to the period (LL-10: ALL in_progress/assigned)."""
    table_id = get_table_id(config, "tasks")

    all_tasks = list_all_rows(table_id)

    relevant = []
    for task in all_tasks:
        status = (task.get("status") or "").lower()

        # LL-10: always include active tasks
        if status in ("in_progress", "assigned", "waiting_input"):
            relevant.append(task)
            continue

        # Include done/cancelled if within the period
        if status in ("done", "cancelled", "handed_over"):
            completed_at = task.get("completed_at") or task.get("updated_on") or ""
            if completed_at:
                try:
                    d = _parse_date(completed_at)
                    if period_start <= d <= period_end:
                        relevant.append(task)
                except (ValueError, TypeError):
                    pass
            continue

        # Include tasks with deadline in period
        deadline = task.get("deadline") or ""
        if deadline:
            try:
                d = _parse_date(deadline)
                if period_start <= d <= period_end:
                    relevant.append(task)
            except (ValueError, TypeError):
                pass

    return relevant


def load_plan_items(
    config: dict,
    period_start: date,
    period_end: date,
) -> list[dict]:
    """Load plan_items for a specific period from Baserow."""
    table_id = get_table_id(config, "plan_items")

    # Filter by period_start
    items = list_all_rows(
        table_id,
        filters={"period_start": str(period_start)},
    )

    # Fallback: if no exact match, search by date range
    if not items:
        all_items = list_all_rows(table_id)
        items = [
            it for it in all_items
            if _date_in_range(it.get("period_start", ""), period_start, period_end)
        ]

    return items


def load_regulatory_tracks(
    config: dict,
    period_start: date,
    period_end: date,
) -> list[dict]:
    """Load regulatory tracks with deadlines in period."""
    table_id = get_table_id(config, "regulatory_tracks")
    all_tracks = list_all_rows(table_id)

    relevant = []
    for track in all_tracks:
        dl = track.get("next_deadline") or track.get("deadline") or ""
        if dl:
            try:
                d = _parse_date(dl)
                if period_start <= d <= period_end:
                    relevant.append(track)
            except (ValueError, TypeError):
                pass
        # Also include ongoing tracks
        status = (track.get("status") or "").lower()
        if status in ("in_progress", "not_started") and track not in relevant:
            relevant.append(track)

    return relevant


def load_all_data(
    config: dict,
    period_start: date,
    period_end: date,
) -> dict:
    """Load all data needed for plan/report generation (parallel)."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_tasks = pool.submit(load_tasks, config, period_start, period_end)
        f_plan = pool.submit(load_plan_items, config, period_start, period_end)
        f_reg = pool.submit(load_regulatory_tracks, config, period_start, period_end)

    return {
        "tasks": f_tasks.result(),
        "plan_items": f_plan.result(),
        "regulatory_tracks": f_reg.result(),
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


def _date_in_range(date_str: str, start: date, end: date) -> bool:
    """Check if date_str falls within [start, end]."""
    try:
        d = _parse_date(date_str)
        return start <= d <= end
    except (ValueError, TypeError):
        return False


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
            items = load_plan_items(config, start, end)
            output_json(items)

    except (RuntimeError, ValueError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
