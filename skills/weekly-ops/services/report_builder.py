"""Build report from plan items + tasks + formulation memory.

CLI usage:
    python -m services.report_builder build --data /dev/shm/weekly-ops/raw.json --output /dev/shm/weekly-ops/report.json
    python -m services.report_builder build --period-start 2026-02-17 --period-end 2026-02-21
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from config.settings import load_config, output_error, output_json
from config.rules import is_excluded, validate_report_item
from models.plan_item import PlanItem, PlanItemStatus, ReportItem
from services.data_loader import load_all_data, _parse_date


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def build_report(
    raw_data: dict,
    formulation_mem: dict | None = None,
    config: dict | None = None,
) -> dict:
    """Build report items from plan + tasks.

    Returns:
        {
            "planned": [ReportItem.to_dict(), ...],
            "unplanned": [ReportItem.to_dict(), ...],
            "warnings": [str, ...]
        }
    """
    cfg = config or load_config()
    fm = formulation_mem or {}

    plan_items_raw = raw_data.get("plan_items", [])
    tasks = raw_data.get("tasks", [])
    warnings: list[str] = []

    # Build PlanItem objects
    plan_items = [PlanItem.from_baserow(pi) for pi in plan_items_raw]

    # Build report items for planned activities
    planned_reports: list[ReportItem] = []
    for pi in plan_items:
        if pi.is_unplanned:
            continue
        if is_excluded(pi.description):
            continue

        matched = _match_tasks_to_plan_item(pi, tasks)
        mark_text, mark_source = _generate_mark(pi, matched, fm)

        ri = ReportItem(
            plan_item=pi,
            mark_text=mark_text,
            mark_source=mark_source,
            matched_tasks=matched,
        )
        planned_reports.append(ri)

    # Collect unplanned done tasks
    unplanned_reports: list[ReportItem] = []
    planned_descs = [r.plan_item.description for r in planned_reports]

    for task in tasks:
        is_unplanned = task.get("is_unplanned", False)
        status = (task.get("status") or "").lower()

        if not is_unplanned or status != "done":
            continue

        title = task.get("title") or task.get("description") or ""
        if not title or is_excluded(title):
            continue

        # LL-3: check duplication with planned items
        dup_issues = []
        for pd in planned_descs:
            issues = validate_report_item(pd, [title])
            dup_issues.extend(issues)

        if dup_issues:
            warnings.extend(dup_issues)
            continue

        result = task.get("result") or ""
        mark = "Выполнено."
        if result:
            mark += f" {result}."

        pi = PlanItem(
            description=title,
            deadline=task.get("deadline", ""),
            responsible=task.get("responsible", ""),
            is_unplanned=True,
            status=PlanItemStatus.DONE,
            linked_task_ids=[task["id"]] if task.get("id") else [],
        )

        unplanned_reports.append(ReportItem(
            plan_item=pi,
            mark_text=mark.strip(),
            mark_source="auto",
            matched_tasks=[task],
        ))

    # Renumber
    num = 1
    for ri in planned_reports:
        ri.plan_item.item_number = num
        num += 1
    for ri in unplanned_reports:
        ri.plan_item.item_number = num
        num += 1

    return {
        "planned": [ri.to_dict() for ri in planned_reports],
        "unplanned": [ri.to_dict() for ri in unplanned_reports],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Task matching
# ---------------------------------------------------------------------------

def _match_tasks_to_plan_item(pi: PlanItem, tasks: list[dict]) -> list[dict]:
    """Find tasks related to a plan item."""
    matched: list[dict] = []

    for task in tasks:
        if task.get("is_unplanned"):
            continue

        # Priority 1: linked_task_ids
        task_id = task.get("id")
        if task_id and task_id in pi.linked_task_ids:
            matched.append(task)
            continue

        # Priority 2: plan_item_hint
        hint = (task.get("plan_item_hint") or "").lower()
        if hint and hint in pi.description.lower():
            matched.append(task)
            continue

        # Priority 3: keyword overlap
        title = (task.get("title") or "").lower()
        title_words = {w for w in title.split() if len(w) > 3}
        desc_words = {w for w in pi.description.lower().split() if len(w) > 3}
        if title_words and desc_words:
            overlap = title_words & desc_words
            if len(overlap) >= 2:
                matched.append(task)

    return matched


# ---------------------------------------------------------------------------
# Mark generation
# ---------------------------------------------------------------------------

def _generate_mark(
    pi: PlanItem,
    matched_tasks: list[dict],
    formulation_mem: dict,
) -> tuple[str, str]:
    """Generate mark text for a plan item.

    Returns (mark_text, source) where source is "memory"|"auto"|"manual".
    """
    # Try formulation memory first
    mem_text = _lookup_formulation(pi.description, formulation_mem)
    if mem_text:
        return _apply_variables(mem_text, matched_tasks), "memory"

    # Auto-generate from matched tasks
    if not matched_tasks:
        return "[Ожидается уточнение]", "auto"

    parts: list[str] = []
    for task in matched_tasks:
        status = (task.get("status") or "").lower()
        result = task.get("result") or ""
        notes = task.get("notes") or ""
        ref = task.get("regulatory_ref") or ""

        if status == "done":
            line = "Выполнено."
            if result:
                line += f" {result}."
            if ref:
                line += f" {ref}."
        elif status == "in_progress":
            line = "В работе."
            detail = result or notes
            if detail:
                line += f" {detail}."
        elif status == "cancelled":
            line = "Отменено."
            if notes:
                line += f" {notes}."
        else:
            line = "[Ожидается уточнение]"
            detail = result or notes
            if detail:
                line = f"[Ожидается уточнение: {detail}]"

        parts.append(line.strip())

    return " ".join(parts), "auto"


def _lookup_formulation(description: str, mem: dict) -> str | None:
    """Look up formulation from memory by keyword overlap."""
    if not mem:
        return None

    desc_words = {w.lower() for w in description.split() if len(w) > 3}
    if not desc_words:
        return None

    best_match = None
    best_score = 0.0

    for pattern, formulation in mem.items():
        pattern_words = {w.lower() for w in pattern.split() if len(w) > 3}
        if not pattern_words:
            continue
        overlap = desc_words & pattern_words
        score = len(overlap) / min(len(desc_words), len(pattern_words))
        if score > best_score and score >= 0.6:
            best_score = score
            best_match = formulation

    return best_match


def _apply_variables(template: str, tasks: list[dict]) -> str:
    """Replace placeholders like {N_events} with actual values from tasks."""
    if not tasks:
        return template

    # Aggregate simple counters from task results
    aggregated = {}
    for task in tasks:
        result = task.get("result") or ""
        # Extract numbers from result text
        import re
        numbers = re.findall(r'(\d+)', result)
        if numbers:
            aggregated["N"] = numbers[0]

    # Replace placeholders
    for key, val in aggregated.items():
        template = template.replace(f"{{{key}}}", str(val))

    return template


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Report builder for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build report")
    p_build.add_argument("--data", help="Path to raw data JSON")
    p_build.add_argument("--period-start", help="YYYY-MM-DD (alternative to --data)")
    p_build.add_argument("--period-end", help="YYYY-MM-DD")
    p_build.add_argument("--memory", help="Path to formulation memory JSON")
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

        fm = {}
        if args.memory:
            with open(args.memory, "r", encoding="utf-8") as f:
                fm = json.load(f)

        result = build_report(raw_data, fm, config)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            output_json({"path": args.output, "planned": len(result["planned"]),
                         "unplanned": len(result["unplanned"])})
        else:
            output_json(result)

    except (RuntimeError, ValueError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
