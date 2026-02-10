"""Task parser — validate, enrich, deduplicate, classify.

CLI usage:
    python -m services.parser validate --tasks tasks.json
    python -m services.parser enrich --tasks tasks.json --employees employees.json
    python -m services.parser deduplicate --new-tasks new.json --existing existing.json
    python -m services.parser classify --task task.json
"""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from typing import Any

from config.settings import output_error, output_json
from models.enums import ControlLoop, OwnerAction, TaskType


# ---------------------------------------------------------------------------
# Task type → control loop mapping
# ---------------------------------------------------------------------------

TYPE_TO_LOOP: dict[str, ControlLoop] = {
    TaskType.DELEGATE.value: ControlLoop.DOWN,
    TaskType.COLLAB.value: ControlLoop.DOWN,
    TaskType.INFORM.value: ControlLoop.DOWN,
    TaskType.BOSS_CONTROL.value: ControlLoop.UP,
    TaskType.REPORT_UP.value: ControlLoop.UP,
    TaskType.REGULATORY.value: ControlLoop.REGULATORY,
    TaskType.SKILL_UPDATE.value: ControlLoop.INTERNAL,
    TaskType.PERSONAL.value: ControlLoop.INTERNAL,
    TaskType.BACKLOG.value: ControlLoop.INTERNAL,
    TaskType.BOSS_DEADLINE.value: ControlLoop.UP,
}

# Task type → owner action mapping
TYPE_TO_ACTION: dict[str, OwnerAction] = {
    TaskType.DELEGATE.value: OwnerAction.DELEGATE,
    TaskType.COLLAB.value: OwnerAction.NONE,
    TaskType.INFORM.value: OwnerAction.DELEGATE,
    TaskType.BOSS_CONTROL.value: OwnerAction.REPORT,
    TaskType.REPORT_UP.value: OwnerAction.REPORT,
    TaskType.REGULATORY.value: OwnerAction.DELEGATE,
    TaskType.SKILL_UPDATE.value: OwnerAction.NONE,
    TaskType.PERSONAL.value: OwnerAction.NONE,
    TaskType.BACKLOG.value: OwnerAction.NONE,
    TaskType.BOSS_DEADLINE.value: OwnerAction.REPORT,
}

# Valid task type codes
VALID_TYPES = {t.value for t in TaskType}
VALID_STATUSES = {"draft", "assigned", "in_progress", "done", "overdue", "cancelled", "handed_over", "waiting_input"}
VALID_PRIORITIES = {"critical", "high", "normal", "low"}


def validate_tasks(tasks: list[dict]) -> dict:
    """Validate task dicts against schema.

    Returns {valid: [...], errors: [{index, field, message}]}.
    """
    valid = []
    errors = []

    for i, task in enumerate(tasks):
        task_errors = []

        # Title required
        if not task.get("title", "").strip():
            task_errors.append({"index": i, "field": "title", "message": "Отсутствует название задачи"})

        # Task type must be valid
        task_type = task.get("task_type", "")
        if task_type and task_type not in VALID_TYPES:
            task_errors.append({
                "index": i,
                "field": "task_type",
                "message": f"Неизвестный тип '{task_type}'. Допустимые: {', '.join(sorted(VALID_TYPES))}",
            })

        # Status must be valid if provided
        status = task.get("status", "")
        if status and status not in VALID_STATUSES:
            task_errors.append({
                "index": i,
                "field": "status",
                "message": f"Неизвестный статус '{status}'",
            })

        # Priority must be valid if provided
        priority = task.get("priority", "")
        if priority and priority not in VALID_PRIORITIES:
            task_errors.append({
                "index": i,
                "field": "priority",
                "message": f"Неизвестный приоритет '{priority}'",
            })

        # delegate requires assignee hint
        if task_type == "delegate" and not task.get("assignee") and not task.get("assignee_hint"):
            task_errors.append({
                "index": i,
                "field": "assignee",
                "message": "Для делегирования нужен исполнитель (или подсказка assignee_hint)",
            })

        if task_errors:
            errors.extend(task_errors)
        else:
            valid.append(task)

    return {"valid": valid, "errors": errors}


def _normalize_fio(fio: str) -> str:
    """Normalize FIO for fuzzy matching."""
    return re.sub(r'\s+', ' ', fio.strip().lower())


def _fio_match_score(name: str, employee_fio: str) -> float:
    """Compute match score between a name hint and an employee FIO.

    Handles partial matches (surname only, first+last, etc.).
    """
    name_norm = _normalize_fio(name)
    fio_norm = _normalize_fio(employee_fio)

    # Exact match
    if name_norm == fio_norm:
        return 1.0

    # Surname match (first word)
    name_parts = name_norm.split()
    fio_parts = fio_norm.split()
    if name_parts and fio_parts and name_parts[0] == fio_parts[0]:
        return 0.9

    # SequenceMatcher for fuzzy
    return SequenceMatcher(None, name_norm, fio_norm).ratio()


def enrich_tasks(
    tasks: list[dict], employees: list[dict]
) -> list[dict]:
    """Resolve assignee_hint to employee IDs using fuzzy name matching.

    Enriches each task with: assignee (ID), assignee_fio, control_loop, owner_action.
    """
    enriched = []
    for task in tasks:
        t = dict(task)

        # Resolve assignee
        hint = t.pop("assignee_hint", None) or ""
        if hint and not t.get("assignee"):
            best_score = 0.0
            best_emp = None
            for emp in employees:
                fio = emp.get("fio", "")
                if not fio:
                    continue
                score = _fio_match_score(hint, fio)
                if score > best_score:
                    best_score = score
                    best_emp = emp

            if best_emp and best_score >= 0.6:
                t["assignee"] = best_emp.get("id")
                t["assignee_fio"] = best_emp.get("fio", "")
                t["assignee_match_score"] = round(best_score, 2)
            else:
                t["assignee_hint_unresolved"] = hint

        # Set control_loop from task_type
        task_type = t.get("task_type", "")
        if task_type and not t.get("control_loop"):
            t["control_loop"] = TYPE_TO_LOOP.get(task_type, ControlLoop.INTERNAL).value

        # Set owner_action from task_type
        if task_type and not t.get("owner_action"):
            t["owner_action"] = TYPE_TO_ACTION.get(task_type, OwnerAction.NONE).value

        # Default status
        if not t.get("status"):
            t["status"] = "draft"

        # Default priority
        if not t.get("priority"):
            t["priority"] = "normal"

        enriched.append(t)

    return enriched


def deduplicate(
    new_tasks: list[dict], existing_tasks: list[dict], threshold: float = 0.7
) -> list[dict]:
    """Flag potential duplicates by title similarity.

    Returns new_tasks with added 'possible_duplicate' field.
    """
    result = []
    for new in new_tasks:
        t = dict(new)
        new_title = _normalize_fio(t.get("title", ""))
        best_match = None
        best_score = 0.0

        for existing in existing_tasks:
            ex_title = _normalize_fio(existing.get("title", ""))
            score = SequenceMatcher(None, new_title, ex_title).ratio()
            if score > best_score:
                best_score = score
                best_match = existing

        if best_score >= threshold and best_match:
            t["possible_duplicate"] = {
                "existing_id": best_match.get("id"),
                "existing_title": best_match.get("title", ""),
                "similarity": round(best_score, 2),
            }

        result.append(t)

    return result


def classify_owner_action(task: dict) -> str:
    """Determine owner_action based on task_type and status."""
    task_type = task.get("task_type", "")
    status = task.get("status", "")

    # Done tasks that owner hasn't closed
    if status == "done":
        return OwnerAction.CLOSE.value

    # Assigned tasks with no check needed yet
    if status in ("assigned", "in_progress"):
        if task_type in (TaskType.BOSS_CONTROL.value, TaskType.REPORT_UP.value):
            return OwnerAction.REPORT.value
        if task_type == TaskType.DELEGATE.value:
            return OwnerAction.CHECK.value

    # Draft tasks need delegation
    if status == "draft" and task_type == TaskType.DELEGATE.value:
        return OwnerAction.DELEGATE.value

    return TYPE_TO_ACTION.get(task_type, OwnerAction.NONE).value


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
    parser = argparse.ArgumentParser(description="Task parser")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--tasks", required=True, help="JSON file with tasks")

    p_enrich = sub.add_parser("enrich")
    p_enrich.add_argument("--tasks", required=True)
    p_enrich.add_argument("--employees", required=True)

    p_dedup = sub.add_parser("deduplicate")
    p_dedup.add_argument("--new-tasks", required=True)
    p_dedup.add_argument("--existing", required=True)
    p_dedup.add_argument("--threshold", type=float, default=0.7)

    p_cls = sub.add_parser("classify")
    p_cls.add_argument("--task", required=True)

    args = parser.parse_args()

    try:
        if args.command == "validate":
            tasks = _load_json_file(args.tasks)
            result = validate_tasks(tasks)
            output_json(result)

        elif args.command == "enrich":
            tasks = _load_json_file(args.tasks)
            employees = _load_json_file(args.employees)
            result = enrich_tasks(tasks, employees)
            output_json(result)

        elif args.command == "deduplicate":
            new_tasks = _load_json_file(args.new_tasks)
            existing = _load_json_file(args.existing)
            result = deduplicate(new_tasks, existing, args.threshold)
            output_json(result)

        elif args.command == "classify":
            task = _load_json_file(args.task)
            if isinstance(task, list):
                task = task[0]
            action = classify_owner_action(task)
            output_json({"owner_action": action})

    except (RuntimeError, ValueError, json.JSONDecodeError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
