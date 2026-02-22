"""Build plan from raw Baserow data + business rules.

CLI usage:
    python -m services.plan_builder build --data /dev/shm/weekly-ops/raw.json --output /dev/shm/weekly-ops/plan.json
    python -m services.plan_builder build --period-start 2026-02-17 --period-end 2026-02-21
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime

from config.settings import load_config, output_error, output_json
from config.rules import (
    CONTRACTOR_DEPARTMENT,
    CONTRACTOR_REPLACEMENTS,
    EXCLUDE_TOPICS,
    MANDATORY_ITEMS,
    check_mandatory_items,
    is_excluded,
    validate_plan_item,
)
from models.plan_item import PlanItem, PlanItemStatus, PeriodType
from services.data_loader import load_all_data, _parse_date


# ---------------------------------------------------------------------------
# Plan building
# ---------------------------------------------------------------------------

def build_plan(
    raw_data: dict,
    period_type: PeriodType = PeriodType.WEEKLY,
    config: dict | None = None,
) -> list[PlanItem]:
    """Build plan items from raw Baserow data applying all rules."""
    cfg = config or load_config()
    tasks = raw_data.get("tasks", [])
    existing_plan_items = raw_data.get("plan_items", [])
    regulatory_tracks = raw_data.get("regulatory_tracks", [])

    items: list[PlanItem] = []

    # 1. Carry over existing plan items from previous period (if in_progress/carried_over)
    for pi_data in existing_plan_items:
        status = (pi_data.get("status") or "planned").lower()
        if status in ("in_progress", "carried_over", "planned"):
            item = PlanItem.from_baserow(pi_data)
            item.status = PlanItemStatus.PLANNED
            if not is_excluded(item.description):
                items.append(item)

    # 2. Add tasks (assigned, in_progress) not yet in plan
    existing_descs = {it.description.lower() for it in items}
    for task in tasks:
        status = (task.get("status") or "").lower()
        if status not in ("assigned", "in_progress", "waiting_input"):
            continue

        title = task.get("title") or task.get("description") or ""
        if not title or is_excluded(title):
            continue

        # Skip if already in plan (by keyword overlap)
        if _already_in_plan(title, existing_descs):
            continue

        deadline = task.get("deadline") or "В течение недели"
        responsible = task.get("responsible") or task.get("assignee") or ""
        if isinstance(responsible, list):
            responsible = ", ".join(
                r.get("value", str(r)) if isinstance(r, dict) else str(r)
                for r in responsible
            )

        item = PlanItem(
            description=title,
            deadline=_format_deadline(deadline),
            responsible=_clean_responsible(responsible),
            linked_task_ids=[task["id"]] if task.get("id") else [],
        )
        items.append(item)
        existing_descs.add(title.lower())

    # 3. Add regulatory tracks
    for track in regulatory_tracks:
        desc = track.get("description") or track.get("title") or ""
        if not desc or is_excluded(desc):
            continue
        if _already_in_plan(desc, existing_descs):
            continue

        dl = track.get("next_deadline") or track.get("deadline") or ""
        items.append(PlanItem(
            description=desc,
            deadline=_format_deadline(dl),
            responsible=track.get("responsible", "Петров Д.А."),
        ))
        existing_descs.add(desc.lower())

    # 4. Check mandatory items
    missing = check_mandatory_items([it.to_dict() for it in items])
    for m in missing:
        items.insert(0, PlanItem(
            description=m["description"],
            deadline=m["deadline"],
            responsible=m["responsible"],
        ))

    # 5. Apply LL-9: replace contractor FIO
    for item in items:
        item.responsible = _clean_responsible(item.responsible)

    # 6. Validate LL-8 (no percentages), LL-9 (no contractor FIO)
    for item in items:
        issues = validate_plan_item(item.to_dict())
        for issue in issues:
            if "LL-8" in issue:
                item.description = re.sub(r'\d+\s*%', '', item.description).strip()
            if "LL-9" in issue:
                item.responsible = CONTRACTOR_DEPARTMENT

    # 7. Renumber
    for i, item in enumerate(items, 1):
        item.item_number = i

    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _already_in_plan(text: str, existing: set[str]) -> bool:
    """Check by keyword overlap (>= 50% significant words)."""
    text_words = {w for w in text.lower().split() if len(w) > 3}
    if not text_words:
        return False
    for ex in existing:
        ex_words = {w for w in ex.split() if len(w) > 3}
        if not ex_words:
            continue
        overlap = text_words & ex_words
        if len(overlap) / min(len(text_words), len(ex_words)) >= 0.5:
            return True
    return False


def _format_deadline(dl: str) -> str:
    """Format deadline for display."""
    if not dl:
        return "В течение недели"
    try:
        d = _parse_date(dl)
        return f"до {d.strftime('%d.%m.%Y')}"
    except (ValueError, TypeError):
        return dl


def _clean_responsible(name: str) -> str:
    """LL-9: replace contractor FIO with department."""
    if not name:
        return ""
    for fio, replacement in CONTRACTOR_REPLACEMENTS.items():
        if fio.lower() in name.lower():
            return replacement or CONTRACTOR_DEPARTMENT
    return name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Plan builder for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build plan")
    p_build.add_argument("--data", help="Path to raw data JSON")
    p_build.add_argument("--period-start", help="YYYY-MM-DD (alternative to --data)")
    p_build.add_argument("--period-end", help="YYYY-MM-DD")
    p_build.add_argument("--type", default="weekly", choices=["weekly", "monthly"])
    p_build.add_argument("--output", help="Output JSON path")

    args = parser.parse_args()
    config = load_config()

    try:
        if args.data:
            with open(args.data, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        elif args.period_start and args.period_end:
            start = _parse_date(args.period_start)
            end = _parse_date(args.period_end)
            raw_data = load_all_data(config, start, end)
        else:
            output_error("Either --data or --period-start/--period-end required")
            return

        period_type = PeriodType.MONTHLY if args.type == "monthly" else PeriodType.WEEKLY
        items = build_plan(raw_data, period_type, config)

        result = [item.to_dict() for item in items]

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            output_json({"path": args.output, "count": len(result)})
        else:
            output_json(result)

    except (RuntimeError, ValueError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
