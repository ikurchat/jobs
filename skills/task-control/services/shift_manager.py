"""Shift calendar management — who's on duty, load balance, schedule parsing.

CLI usage:
    python -m services.shift_manager who_on_shift --date 2025-02-10 --shifts shifts.json
    python -m services.shift_manager current_shift --shifts shifts.json
    python -m services.shift_manager shift_load --employee-id 1 --tasks tasks.json
    python -m services.shift_manager next_shift --employee-id 1 --shifts shifts.json
    python -m services.shift_manager parse_schedule --text "Иванов — 1д, 2н, 3о, 4в..."
    python -m services.shift_manager validate --shifts shifts.json
    python -m services.shift_manager calendar --year 2025 --month 2 --shifts shifts.json --employees employees.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, time, timedelta
from typing import Any

from config.settings import output_error, output_json
from models.enums import ScheduleType, ShiftType


# Shift type aliases for parsing
SHIFT_ALIASES: dict[str, ShiftType] = {
    "д": ShiftType.DAY,
    "д.": ShiftType.DAY,
    "дневная": ShiftType.DAY,
    "day": ShiftType.DAY,
    "н": ShiftType.NIGHT,
    "н.": ShiftType.NIGHT,
    "ночная": ShiftType.NIGHT,
    "night": ShiftType.NIGHT,
    "о": ShiftType.REST,
    "о.": ShiftType.REST,
    "отс": ShiftType.REST,
    "отсыпной": ShiftType.REST,
    "rest": ShiftType.REST,
    "в": ShiftType.OFF,
    "в.": ShiftType.OFF,
    "вых": ShiftType.OFF,
    "выходной": ShiftType.OFF,
    "off": ShiftType.OFF,
}

SHIFT_TIMES = {
    ShiftType.DAY: ("08:00", "20:00"),
    ShiftType.NIGHT: ("20:00", "08:00"),
    ShiftType.REST: ("", ""),
    ShiftType.OFF: ("", ""),
}


def who_on_shift(target_date: date, shifts_data: list[dict]) -> list[dict]:
    """Get employees on duty for a given date with shift type.

    Returns list of {employee, shift_type, shift_start, shift_end}.
    """
    result = []
    target_str = target_date.isoformat()
    for s in shifts_data:
        shift_date = s.get("date", "")
        if isinstance(shift_date, str):
            shift_date = shift_date[:10]
        else:
            shift_date = str(shift_date)[:10]

        if shift_date == target_str:
            stype = s.get("shift_type", "")
            if stype in (ShiftType.DAY.value, ShiftType.NIGHT.value):
                result.append({
                    "employee": s.get("employee"),
                    "shift_type": stype,
                    "shift_start": s.get("shift_start", ""),
                    "shift_end": s.get("shift_end", ""),
                })
    return result


def current_shift_info(
    now: datetime, shifts_data: list[dict]
) -> dict[str, Any]:
    """Who's on shift right now, when does it end.

    Returns {on_duty: [{employee, shift_type, shift_end}], next_shift: {...}}.
    """
    today = now.date()
    yesterday = today - timedelta(days=1)
    current_time = now.time()

    on_duty = []

    for s in shifts_data:
        shift_date = str(s.get("date", ""))[:10]
        stype = s.get("shift_type", "")

        # Day shift: same date, 08:00-20:00
        if stype == ShiftType.DAY.value and shift_date == today.isoformat():
            if time(8, 0) <= current_time < time(20, 0):
                on_duty.append({
                    "employee": s.get("employee"),
                    "shift_type": stype,
                    "shift_end": "20:00",
                })

        # Night shift: started yesterday at 20:00, ends today 08:00
        if stype == ShiftType.NIGHT.value and shift_date == yesterday.isoformat():
            if current_time < time(8, 0):
                on_duty.append({
                    "employee": s.get("employee"),
                    "shift_type": stype,
                    "shift_end": "08:00",
                })

        # Night shift: starts today at 20:00
        if stype == ShiftType.NIGHT.value and shift_date == today.isoformat():
            if current_time >= time(20, 0):
                on_duty.append({
                    "employee": s.get("employee"),
                    "shift_type": stype,
                    "shift_end": "08:00 (+1)",
                })

    # Next shift
    next_shift = None
    for s in sorted(shifts_data, key=lambda x: str(x.get("date", ""))):
        shift_date = str(s.get("date", ""))[:10]
        stype = s.get("shift_type", "")
        if stype not in (ShiftType.DAY.value, ShiftType.NIGHT.value):
            continue
        try:
            sd = date.fromisoformat(shift_date)
        except (ValueError, TypeError):
            continue
        if sd > today:
            next_shift = {
                "employee": s.get("employee"),
                "shift_type": stype,
                "date": shift_date,
                "shift_start": s.get("shift_start", ""),
            }
            break
        if sd == today:
            start_str = s.get("shift_start", "")
            try:
                start_time = time.fromisoformat(start_str)
                if start_time > current_time:
                    next_shift = {
                        "employee": s.get("employee"),
                        "shift_type": stype,
                        "date": shift_date,
                        "shift_start": start_str,
                    }
                    break
            except (ValueError, TypeError):
                pass

    return {"on_duty": on_duty, "next_shift": next_shift}


def shift_load(
    employee_id: int, tasks_data: list[dict]
) -> dict[str, int]:
    """Count active tasks for an employee.

    Returns {active_tasks: N, assigned: N, in_progress: N}.
    """
    assigned = 0
    in_progress = 0

    for t in tasks_data:
        # Baserow link_row returns [{"id": X, "value": "..."}] or just an int
        assignee = t.get("assignee")
        if isinstance(assignee, list):
            emp_ids = [a.get("id") for a in assignee if isinstance(a, dict)]
        elif isinstance(assignee, (int, float)):
            emp_ids = [int(assignee)]
        else:
            emp_ids = []

        if employee_id not in emp_ids:
            continue

        status = t.get("status", "")
        if isinstance(status, dict):
            status = status.get("value", "")
        if status == "assigned":
            assigned += 1
        elif status == "in_progress":
            in_progress += 1

    return {
        "active_tasks": assigned + in_progress,
        "assigned": assigned,
        "in_progress": in_progress,
    }


def next_shift_for_employee(
    employee_id: int, shifts_data: list[dict], after_date: date | None = None
) -> dict | None:
    """Find next working shift for a specific employee.

    Returns {date, shift_type, shift_start, shift_end} or None.
    """
    ref_date = after_date or date.today()

    candidates = []
    for s in shifts_data:
        emp = s.get("employee")
        if isinstance(emp, list):
            emp_ids = [a.get("id") for a in emp if isinstance(a, dict)]
        elif isinstance(emp, (int, float)):
            emp_ids = [int(emp)]
        else:
            continue

        if employee_id not in emp_ids:
            continue

        stype = s.get("shift_type", "")
        if isinstance(stype, dict):
            stype = stype.get("value", "")
        if stype not in (ShiftType.DAY.value, ShiftType.NIGHT.value):
            continue

        shift_date = str(s.get("date", ""))[:10]
        try:
            sd = date.fromisoformat(shift_date)
        except (ValueError, TypeError):
            continue

        if sd > ref_date:
            candidates.append({
                "date": shift_date,
                "shift_type": stype,
                "shift_start": s.get("shift_start", ""),
                "shift_end": s.get("shift_end", ""),
            })

    if not candidates:
        return None

    candidates.sort(key=lambda x: x["date"])
    return candidates[0]


def parse_schedule_text(text: str, year: int, month: int) -> list[dict]:
    """Parse schedule text like 'Иванов — 1д, 2н, 3о, 4в, 5д...'

    Returns list of {fio, date, shift_type, shift_start, shift_end}.
    """
    result = []
    # Pattern: FIO — <day><type>, <day><type>, ...
    # Also supports: FIO: 1д 2н 3о 4в
    lines = text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Split FIO from schedule
        sep_match = re.match(r'^(.+?)\s*[—\-:]\s*(.+)$', line)
        if not sep_match:
            continue

        fio = sep_match.group(1).strip()
        schedule_part = sep_match.group(2).strip()

        # Parse day-type pairs: "1д", "2н", "3о", "4в"
        entries = re.findall(r'(\d{1,2})\s*([а-яА-Яa-zA-Z.]+)', schedule_part)

        for day_str, type_str in entries:
            day_num = int(day_str)
            type_lower = type_str.lower().strip(".,;")

            shift_type = SHIFT_ALIASES.get(type_lower)
            if shift_type is None:
                continue

            try:
                shift_date = date(year, month, day_num)
            except ValueError:
                continue

            start, end = SHIFT_TIMES.get(shift_type, ("", ""))
            result.append({
                "fio": fio,
                "date": shift_date.isoformat(),
                "shift_type": shift_type.value,
                "shift_start": start,
                "shift_end": end,
                "month": f"{year:04d}-{month:02d}",
            })

    return result


def validate_schedule(schedule: list[dict]) -> list[str]:
    """Check for conflicts in schedule.

    Returns list of warning strings.
    """
    warnings = []

    # Group by employee
    by_employee: dict[str, list[dict]] = {}
    for s in schedule:
        emp = s.get("fio", s.get("employee", "?"))
        if isinstance(emp, list):
            emp = str(emp)
        by_employee.setdefault(str(emp), []).append(s)

    for emp, entries in by_employee.items():
        entries_sorted = sorted(entries, key=lambda x: x.get("date", ""))

        for i in range(1, len(entries_sorted)):
            prev = entries_sorted[i - 1]
            curr = entries_sorted[i]

            prev_type = prev.get("shift_type", "")
            curr_type = curr.get("shift_type", "")
            prev_date = prev.get("date", "")
            curr_date = curr.get("date", "")

            # Check: night shift should be followed by rest
            if prev_type == ShiftType.NIGHT.value and curr_type == ShiftType.DAY.value:
                try:
                    pd = date.fromisoformat(prev_date)
                    cd = date.fromisoformat(curr_date)
                    if (cd - pd).days == 1:
                        warnings.append(
                            f"{emp}: дневная {curr_date} сразу после ночной {prev_date} "
                            f"(нужен отсыпной)"
                        )
                except (ValueError, TypeError):
                    pass

            # Check: two shifts same day
            if prev_date == curr_date and prev_type in ("day", "night") and curr_type in ("day", "night"):
                warnings.append(
                    f"{emp}: две рабочие смены {prev_date}"
                )

    # Check coverage: each date should have at least one day + one night shift
    by_date: dict[str, list[str]] = {}
    for s in schedule:
        d = s.get("date", "")
        stype = s.get("shift_type", "")
        if stype in (ShiftType.DAY.value, ShiftType.NIGHT.value):
            by_date.setdefault(d, []).append(stype)

    for d, types in sorted(by_date.items()):
        if ShiftType.DAY.value not in types:
            warnings.append(f"{d}: нет дневного дежурного")
        if ShiftType.NIGHT.value not in types:
            warnings.append(f"{d}: нет ночного дежурного")

    return warnings


def generate_month_calendar(
    year: int,
    month: int,
    shifts_data: list[dict],
    employees_data: list[dict],
) -> dict:
    """Generate full monthly calendar.

    Returns {month, employees: [{fio, shifts: [{date, shift_type}]}], coverage: {date: [types]}}.
    """
    month_str = f"{year:04d}-{month:02d}"

    # Filter shifts for this month
    month_shifts = [
        s for s in shifts_data
        if str(s.get("month", "")) == month_str
        or str(s.get("date", ""))[:7] == month_str
    ]

    # Build employee lookup
    emp_lookup = {}
    for e in employees_data:
        eid = e.get("id")
        emp_lookup[eid] = e.get("fio", f"ID:{eid}")

    # Group by employee
    by_employee: dict[str, list[dict]] = {}
    for s in month_shifts:
        emp = s.get("employee")
        if isinstance(emp, list):
            for a in emp:
                if isinstance(a, dict):
                    name = emp_lookup.get(a.get("id"), a.get("value", "?"))
                    by_employee.setdefault(name, []).append({
                        "date": str(s.get("date", ""))[:10],
                        "shift_type": s.get("shift_type", ""),
                    })
        elif isinstance(emp, (int, float)):
            name = emp_lookup.get(int(emp), f"ID:{emp}")
            by_employee.setdefault(name, []).append({
                "date": str(s.get("date", ""))[:10],
                "shift_type": s.get("shift_type", ""),
            })

    # Coverage
    coverage: dict[str, list[str]] = {}
    for s in month_shifts:
        d = str(s.get("date", ""))[:10]
        stype = s.get("shift_type", "")
        if stype in (ShiftType.DAY.value, ShiftType.NIGHT.value):
            coverage.setdefault(d, []).append(stype)

    return {
        "month": month_str,
        "employees": [
            {
                "fio": fio,
                "shifts": sorted(shifts, key=lambda x: x["date"]),
                "total_day": sum(1 for s in shifts if s["shift_type"] == "day"),
                "total_night": sum(1 for s in shifts if s["shift_type"] == "night"),
                "total_rest": sum(1 for s in shifts if s["shift_type"] == "rest"),
                "total_off": sum(1 for s in shifts if s["shift_type"] == "off"),
            }
            for fio, shifts in sorted(by_employee.items())
        ],
        "coverage": dict(sorted(coverage.items())),
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
    parser = argparse.ArgumentParser(description="Shift calendar manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_who = sub.add_parser("who_on_shift")
    p_who.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_who.add_argument("--shifts", required=True, help="JSON file with shifts")

    p_curr = sub.add_parser("current_shift")
    p_curr.add_argument("--shifts", required=True)

    p_load = sub.add_parser("shift_load")
    p_load.add_argument("--employee-id", type=int, required=True)
    p_load.add_argument("--tasks", required=True)

    p_next = sub.add_parser("next_shift")
    p_next.add_argument("--employee-id", type=int, required=True)
    p_next.add_argument("--shifts", required=True)

    p_parse = sub.add_parser("parse_schedule")
    p_parse.add_argument("--text", required=True)
    p_parse.add_argument("--year", type=int, required=True)
    p_parse.add_argument("--month", type=int, required=True)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--shifts", required=True)

    p_cal = sub.add_parser("calendar")
    p_cal.add_argument("--year", type=int, required=True)
    p_cal.add_argument("--month", type=int, required=True)
    p_cal.add_argument("--shifts", required=True)
    p_cal.add_argument("--employees", required=True)

    args = parser.parse_args()

    try:
        if args.command == "who_on_shift":
            shifts = _load_json_file(args.shifts)
            d = date.fromisoformat(args.date)
            result = who_on_shift(d, shifts)
            output_json(result)

        elif args.command == "current_shift":
            shifts = _load_json_file(args.shifts)
            result = current_shift_info(datetime.now(), shifts)
            output_json(result)

        elif args.command == "shift_load":
            tasks = _load_json_file(args.tasks)
            result = shift_load(args.employee_id, tasks)
            output_json(result)

        elif args.command == "next_shift":
            shifts = _load_json_file(args.shifts)
            result = next_shift_for_employee(args.employee_id, shifts)
            output_json(result or {"next_shift": None})

        elif args.command == "parse_schedule":
            result = parse_schedule_text(args.text, args.year, args.month)
            output_json(result)

        elif args.command == "validate":
            shifts = _load_json_file(args.shifts)
            warnings = validate_schedule(shifts)
            output_json({"valid": len(warnings) == 0, "warnings": warnings})

        elif args.command == "calendar":
            shifts = _load_json_file(args.shifts)
            employees = _load_json_file(args.employees)
            result = generate_month_calendar(args.year, args.month, shifts, employees)
            output_json(result)

    except (RuntimeError, ValueError, json.JSONDecodeError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
