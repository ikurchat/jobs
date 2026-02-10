"""Per-employee metrics, anomalies, discipline stats.

CLI usage:
    python -m services.analytics summary --tasks t.json --employees e.json --start 2025-02-03 --end 2025-02-09
    python -m services.analytics employee_metrics --tasks t.json --employee-id 1
    python -m services.analytics shift_metrics --tasks t.json --shifts s.json
    python -m services.analytics anomalies --tasks t.json --employees e.json --shifts s.json
    python -m services.analytics discipline --tasks t.json --employees e.json --start 2025-02-03 --end 2025-02-09
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from typing import Any

from config.settings import load_config, output_error, output_json


def _get_val(field: Any) -> str:
    """Extract string value from Baserow field."""
    if isinstance(field, dict):
        return field.get("value", "")
    return str(field) if field else ""


def _get_link_ids(field: Any) -> list[int]:
    """Extract IDs from Baserow link_row field."""
    if isinstance(field, list):
        return [a.get("id") for a in field if isinstance(a, dict) and a.get("id")]
    if isinstance(field, (int, float)):
        return [int(field)]
    return []


def _parse_date(val: Any) -> date | None:
    if not val:
        return None
    try:
        return date.fromisoformat(str(val)[:10])
    except (ValueError, TypeError):
        return None


def _tasks_for_employee(tasks: list[dict], employee_id: int) -> list[dict]:
    """Filter tasks assigned to a specific employee."""
    result = []
    for t in tasks:
        emp_ids = _get_link_ids(t.get("assignee"))
        if employee_id in emp_ids:
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_employee_metrics(tasks: list[dict], employee_id: int) -> dict:
    """Individual metrics for one employee."""
    emp_tasks = _tasks_for_employee(tasks, employee_id)

    total = len(emp_tasks)
    completed = sum(1 for t in emp_tasks if _get_val(t.get("status")) == "done")
    overdue_count = sum(1 for t in emp_tasks if _get_val(t.get("status")) == "overdue")
    in_progress = sum(
        1 for t in emp_tasks if _get_val(t.get("status")) in ("assigned", "in_progress")
    )

    # Average completion time (hours)
    completion_times = []
    for t in emp_tasks:
        if _get_val(t.get("status")) != "done":
            continue
        assigned = t.get("assigned_date")
        completed_d = t.get("completed_date")
        if assigned and completed_d:
            try:
                a = datetime.fromisoformat(str(assigned)[:19])
                c = datetime.fromisoformat(str(completed_d)[:19])
                hours = (c - a).total_seconds() / 3600
                if hours > 0:
                    completion_times.append(hours)
            except (ValueError, TypeError):
                pass

    avg_time = sum(completion_times) / len(completion_times) if completion_times else 0.0
    overdue_rate = overdue_count / total if total > 0 else 0.0
    on_time_rate = completed / total if total > 0 else 0.0

    return {
        "employee_id": employee_id,
        "tasks_total": total,
        "tasks_completed": completed,
        "tasks_overdue": overdue_count,
        "tasks_in_progress": in_progress,
        "avg_completion_time_hours": round(avg_time, 1),
        "overdue_rate": round(overdue_rate, 2),
        "on_time_rate": round(on_time_rate, 2),
    }


def compute_summary(
    tasks: list[dict], employees: list[dict], start: date, end: date
) -> dict:
    """Overall department metrics for a period."""
    # Filter tasks in period
    period_tasks = []
    for t in tasks:
        sd = _parse_date(t.get("source_date") or t.get("assigned_date"))
        cd = _parse_date(t.get("completed_date"))
        if (sd and start <= sd <= end) or (cd and start <= cd <= end):
            period_tasks.append(t)

    total = len(period_tasks)
    completed = sum(1 for t in period_tasks if _get_val(t.get("status")) == "done")
    overdue_count = sum(1 for t in period_tasks if _get_val(t.get("status")) == "overdue")
    in_progress_count = sum(
        1 for t in period_tasks if _get_val(t.get("status")) in ("assigned", "in_progress")
    )

    # Per employee breakdown
    emp_metrics = []
    for emp in employees:
        eid = emp.get("id")
        if eid:
            m = compute_employee_metrics(period_tasks, eid)
            m["fio"] = emp.get("fio", "")
            emp_metrics.append(m)

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "total": total,
        "completed": completed,
        "overdue": overdue_count,
        "in_progress": in_progress_count,
        "employees": emp_metrics,
    }


def compute_shift_metrics(tasks: list[dict], shifts: list[dict]) -> dict:
    """Per-shift statistics."""
    # Count tasks per shift type
    day_tasks = 0
    night_tasks = 0
    day_completed = 0
    night_completed = 0
    handover_count = 0

    for t in tasks:
        shift_info = t.get("assigned_shift")
        if not shift_info:
            continue

        # Try to determine shift type
        status = _get_val(t.get("status"))
        if status == "handed_over":
            handover_count += 1

    # Count from shifts data
    day_shifts = sum(1 for s in shifts if _get_val(s.get("shift_type")) == "day")
    night_shifts = sum(1 for s in shifts if _get_val(s.get("shift_type")) == "night")

    # Simple approximation: tasks divided by shifts
    total_tasks = len(tasks)
    tasks_per_day = total_tasks / max(day_shifts, 1) if day_shifts else 0
    tasks_per_night = total_tasks / max(night_shifts, 1) if night_shifts else 0

    return {
        "day_shifts": day_shifts,
        "night_shifts": night_shifts,
        "tasks_per_day_shift": round(tasks_per_day, 1),
        "tasks_per_night_shift": round(tasks_per_night, 1),
        "handover_count": handover_count,
        "day_vs_night_ratio": round(tasks_per_day / max(tasks_per_night, 0.1), 1) if tasks_per_night else 0,
    }


def detect_anomalies(
    tasks: list[dict],
    employees: list[dict],
    shifts: list[dict] | None = None,
    config: dict | None = None,
) -> list[dict]:
    """Detect workload and performance anomalies."""
    cfg = config or load_config()
    thresholds = cfg.get("analytics", {})
    overload_mult = thresholds.get("overload_multiplier", 2.0)
    chronic_rate = thresholds.get("chronic_overdue_rate", 0.30)
    perf_drop = thresholds.get("performance_drop_threshold", 0.50)
    shift_imbalance = thresholds.get("shift_imbalance_ratio", 3.0)
    stale_mult = thresholds.get("stale_task_multiplier", 3.0)

    anomalies = []

    # Compute per-employee active task counts
    emp_active: dict[int, int] = {}
    for emp in employees:
        eid = emp.get("id")
        if not eid:
            continue
        emp_tasks = _tasks_for_employee(tasks, eid)
        active = sum(
            1 for t in emp_tasks
            if _get_val(t.get("status")) in ("assigned", "in_progress")
        )
        emp_active[eid] = active

    # Average active tasks
    active_vals = [v for v in emp_active.values() if v > 0]
    avg_active = sum(active_vals) / len(active_vals) if active_vals else 0

    for emp in employees:
        eid = emp.get("id")
        fio = emp.get("fio", "?")
        if not eid:
            continue

        active = emp_active.get(eid, 0)

        # Overload
        if avg_active > 0 and active > avg_active * overload_mult:
            anomalies.append({
                "type": "overload",
                "employee": fio,
                "detail": f"{active} задач (среднее {avg_active:.1f})",
                "severity": "warning",
            })

        # Idle with backlog available
        backlog_count = sum(
            1 for t in tasks
            if _get_val(t.get("task_type")) == "backlog"
            and _get_val(t.get("status")) not in ("done", "cancelled")
        )
        if active == 0 and backlog_count > 0:
            anomalies.append({
                "type": "idle",
                "employee": fio,
                "detail": f"0 задач, бэклог: {backlog_count}",
                "severity": "info",
            })

        # Chronic overdue
        metrics = compute_employee_metrics(tasks, eid)
        if metrics["tasks_total"] >= 3 and metrics["overdue_rate"] > chronic_rate:
            anomalies.append({
                "type": "chronic_overdue",
                "employee": fio,
                "detail": f"{metrics['overdue_rate']:.0%} просрочек",
                "severity": "warning",
            })

    # Stale tasks (in_progress too long)
    completion_times = []
    for t in tasks:
        if _get_val(t.get("status")) == "done":
            assigned = t.get("assigned_date")
            completed_d = t.get("completed_date")
            if assigned and completed_d:
                try:
                    a = datetime.fromisoformat(str(assigned)[:19])
                    c = datetime.fromisoformat(str(completed_d)[:19])
                    hours = (c - a).total_seconds() / 3600
                    if hours > 0:
                        completion_times.append(hours)
                except (ValueError, TypeError):
                    pass

    avg_completion = sum(completion_times) / len(completion_times) if completion_times else 48.0
    stale_threshold = avg_completion * stale_mult

    for t in tasks:
        if _get_val(t.get("status")) == "in_progress":
            assigned = t.get("assigned_date")
            if assigned:
                try:
                    a = datetime.fromisoformat(str(assigned)[:19])
                    hours = (datetime.now() - a).total_seconds() / 3600
                    if hours > stale_threshold:
                        anomalies.append({
                            "type": "stale_task",
                            "task": t.get("title", "?"),
                            "detail": f"{hours:.0f}ч в работе (среднее {avg_completion:.0f}ч)",
                            "severity": "warning",
                        })
                except (ValueError, TypeError):
                    pass

    return anomalies


def discipline_report(
    tasks: list[dict], employees: list[dict], start: date, end: date
) -> list[dict]:
    """Formatted discipline data for report generation."""
    result = []
    for emp in employees:
        eid = emp.get("id")
        if not eid or not emp.get("active", True):
            continue
        metrics = compute_employee_metrics(tasks, eid)
        result.append({
            "fio": emp.get("fio", ""),
            "position": emp.get("position", ""),
            "schedule_type": _get_val(emp.get("schedule_type", "")),
            **metrics,
        })
    return result


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
    parser = argparse.ArgumentParser(description="Analytics & anomalies")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sum = sub.add_parser("summary")
    p_sum.add_argument("--tasks", required=True)
    p_sum.add_argument("--employees", required=True)
    p_sum.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_sum.add_argument("--end", required=True, help="YYYY-MM-DD")

    p_emp = sub.add_parser("employee_metrics")
    p_emp.add_argument("--tasks", required=True)
    p_emp.add_argument("--employee-id", type=int, required=True)

    p_shift = sub.add_parser("shift_metrics")
    p_shift.add_argument("--tasks", required=True)
    p_shift.add_argument("--shifts", required=True)

    p_anom = sub.add_parser("anomalies")
    p_anom.add_argument("--tasks", required=True)
    p_anom.add_argument("--employees", required=True)
    p_anom.add_argument("--shifts", default=None)

    p_disc = sub.add_parser("discipline")
    p_disc.add_argument("--tasks", required=True)
    p_disc.add_argument("--employees", required=True)
    p_disc.add_argument("--start", required=True)
    p_disc.add_argument("--end", required=True)

    args = parser.parse_args()

    try:
        if args.command == "summary":
            tasks = _load_json_file(args.tasks)
            employees = _load_json_file(args.employees)
            result = compute_summary(
                tasks, employees,
                date.fromisoformat(args.start),
                date.fromisoformat(args.end),
            )
            output_json(result)

        elif args.command == "employee_metrics":
            tasks = _load_json_file(args.tasks)
            result = compute_employee_metrics(tasks, args.employee_id)
            output_json(result)

        elif args.command == "shift_metrics":
            tasks = _load_json_file(args.tasks)
            shifts = _load_json_file(args.shifts)
            result = compute_shift_metrics(tasks, shifts)
            output_json(result)

        elif args.command == "anomalies":
            tasks = _load_json_file(args.tasks)
            employees = _load_json_file(args.employees)
            shifts = _load_json_file(args.shifts) if args.shifts else None
            result = detect_anomalies(tasks, employees, shifts)
            output_json(result)

        elif args.command == "discipline":
            tasks = _load_json_file(args.tasks)
            employees = _load_json_file(args.employees)
            result = discipline_report(
                tasks, employees,
                date.fromisoformat(args.start),
                date.fromisoformat(args.end),
            )
            output_json(result)

    except (RuntimeError, ValueError, json.JSONDecodeError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
