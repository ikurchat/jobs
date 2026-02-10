"""Plan-task correlator — prepare data for Claude's semantic matching.

Claude does the actual semantic comparison. This module prepares structured data
and formats prompts for Claude to evaluate similarity between tasks and plan items.

CLI usage:
    python -m services.correlator get_plan_items --start 2025-02-03 --end 2025-02-09 --plan-items items.json
    python -m services.correlator format_prompt --task task.json --plan-items items.json
    python -m services.correlator apply --task-id 42 --plan-item-id 13 --link true
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from config.settings import output_error, output_json


def get_plan_items_for_period(
    start: date, end: date, plan_items_data: list[dict]
) -> list[dict]:
    """Filter plan items overlapping with the given period.

    Matches items where:
    - period_start <= end AND period_end >= start (overlap)
    - Or deadline falls within [start, end]
    """
    result = []
    for item in plan_items_data:
        item_start = item.get("period_start", "")
        item_end = item.get("period_end", "")

        try:
            if item_start:
                ps = date.fromisoformat(str(item_start)[:10])
            else:
                ps = None
            if item_end:
                pe = date.fromisoformat(str(item_end)[:10])
            else:
                pe = None
        except (ValueError, TypeError):
            continue

        # Check overlap
        overlaps = False
        if ps and pe:
            overlaps = ps <= end and pe >= start
        elif ps:
            overlaps = ps <= end
        elif pe:
            overlaps = pe >= start

        if overlaps:
            result.append(item)

    return result


def format_correlation_prompt(
    task: dict, plan_items: list[dict]
) -> dict:
    """Format a structured prompt for Claude to evaluate similarity.

    Returns {task_summary, candidates: [{item_number, description, responsible, ...}], instruction}.
    """
    task_summary = {
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "assignee": task.get("assignee_fio", task.get("assignee", "")),
        "task_type": task.get("task_type", ""),
    }

    candidates = []
    for item in plan_items:
        responsible = item.get("responsible", "")
        if isinstance(responsible, list):
            responsible = ", ".join(
                r.get("value", str(r)) if isinstance(r, dict) else str(r)
                for r in responsible
            )

        candidates.append({
            "item_number": item.get("item_number", ""),
            "description": item.get("description", ""),
            "responsible": responsible,
            "deadline": item.get("deadline", ""),
            "period_type": item.get("period_type", ""),
            "status": item.get("status", ""),
            "id": item.get("id"),
        })

    instruction = (
        "Оцени семантическое сходство задачи с каждым пунктом плана.\n"
        "Учитывай: тему, ответственного, сроки.\n"
        "Для каждого кандидата дай оценку от 0 до 1.\n"
        "Если сходство >= 0.7 — рекомендуй привязку.\n"
        "Формат ответа: JSON массив [{item_number, similarity, reason}].\n"
        "Если ни один не подходит — верни пустой массив."
    )

    return {
        "task": task_summary,
        "candidates": candidates,
        "instruction": instruction,
    }


def apply_correlation(
    task_id: int,
    plan_item_id: int | None,
    link: bool,
) -> dict:
    """Prepare Baserow update data for task-plan correlation.

    Returns dict to pass to baserow.update_row().
    """
    if link and plan_item_id:
        return {
            "plan_item": [plan_item_id],
            "is_unplanned": False,
        }
    else:
        return {
            "plan_item": [],
            "is_unplanned": True,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_json_file(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    return [data]


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan-task correlator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_items = sub.add_parser("get_plan_items")
    p_items.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_items.add_argument("--end", required=True, help="YYYY-MM-DD")
    p_items.add_argument("--plan-items", required=True, help="JSON file")

    p_prompt = sub.add_parser("format_prompt")
    p_prompt.add_argument("--task", required=True, help="JSON file with single task")
    p_prompt.add_argument("--plan-items", required=True, help="JSON file with plan items")

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--task-id", type=int, required=True)
    p_apply.add_argument("--plan-item-id", type=int, default=None)
    p_apply.add_argument("--link", type=str, default="false", help="true/false")

    args = parser.parse_args()

    try:
        if args.command == "get_plan_items":
            items = _load_json_file(args.plan_items)
            start = date.fromisoformat(args.start)
            end = date.fromisoformat(args.end)
            result = get_plan_items_for_period(start, end, items)
            output_json(result)

        elif args.command == "format_prompt":
            task_data = _load_json_file(args.task)
            if isinstance(task_data, list):
                task_data = task_data[0]
            items = _load_json_file(args.plan_items)
            result = format_correlation_prompt(task_data, items)
            output_json(result)

        elif args.command == "apply":
            link = args.link.lower() in ("true", "1", "yes", "да")
            result = apply_correlation(args.task_id, args.plan_item_id, link)
            output_json(result)

    except (RuntimeError, ValueError, json.JSONDecodeError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
