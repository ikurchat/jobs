"""Notification content generator — briefing, push, weekly summary.

Generates TEXT content for scheduled notifications. The bot's APScheduler handles
timing; this module produces the formatted messages.

CLI usage:
    python -m services.scheduler briefing --date 2025-02-10 --tasks t.json --shifts s.json --regulatory r.json --boss b.json
    python -m services.scheduler handover_push --shifts s.json --tasks t.json
    python -m services.scheduler weekly_summary --start 2025-02-03 --end 2025-02-09 --tasks t.json --employees e.json
    python -m services.scheduler weekend_plan --shifts s.json --tasks t.json --backlog bl.json
    python -m services.scheduler is_working_time
    python -m services.scheduler should_notify --type briefing
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from typing import Any

from config.settings import load_config, output_error, output_json


# ---------------------------------------------------------------------------
# Working time checks
# ---------------------------------------------------------------------------

def is_working_time(now: datetime | None = None, config: dict | None = None) -> bool:
    """Check if current time is within owner's work schedule."""
    now = now or datetime.now()
    cfg = config or load_config()
    schedule = cfg.get("schedule", {}).get("owner_work_hours", {})

    weekday = now.weekday()  # 0=Mon, 6=Sun
    current_time = now.time()

    if weekday >= 5:  # Sat/Sun
        return False

    if weekday <= 3:  # Mon-Thu
        hours = schedule.get("mon_thu", {})
    else:  # Fri
        hours = schedule.get("fri", {})

    if not hours:
        return False

    start = time.fromisoformat(hours.get("start", "09:00"))
    end = time.fromisoformat(hours.get("end", "18:00"))

    return start <= current_time <= end


def should_notify(
    now: datetime | None = None,
    notification_type: str = "briefing",
    config: dict | None = None,
) -> bool:
    """Check if notification should be sent now (working time + right window)."""
    now = now or datetime.now()
    cfg = config or load_config()

    if not is_working_time(now, cfg):
        return False

    schedule = cfg.get("schedule", {})
    current_time = now.time()
    weekday = now.weekday()

    if notification_type == "briefing":
        briefing_time = time.fromisoformat(schedule.get("briefing_time", "09:00"))
        return current_time.hour == briefing_time.hour and current_time.minute < briefing_time.minute + 15

    if notification_type == "push":
        if weekday == 4:  # Friday
            push_time = time.fromisoformat(schedule.get("push_time", {}).get("fri", "15:00"))
        else:
            push_time = time.fromisoformat(schedule.get("push_time", {}).get("mon_thu", "17:00"))
        return current_time.hour == push_time.hour and current_time.minute < push_time.minute + 15

    if notification_type == "anomaly":
        check_times = schedule.get("anomaly_check_times", ["10:00", "14:00"])
        for t_str in check_times:
            t = time.fromisoformat(t_str)
            if current_time.hour == t.hour and current_time.minute < t.minute + 15:
                return True
        return False

    return False


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def _get_status_value(s: Any) -> str:
    """Extract status string from Baserow field (may be dict or str)."""
    if isinstance(s, dict):
        return s.get("value", "")
    return str(s) if s else ""


def _get_link_value(field: Any) -> str:
    """Extract display value from Baserow link_row field."""
    if isinstance(field, list) and field:
        return ", ".join(
            item.get("value", str(item)) if isinstance(item, dict) else str(item)
            for item in field
        )
    if isinstance(field, dict):
        return field.get("value", str(field))
    return str(field) if field else ""


def generate_briefing(
    target_date: date,
    tasks_data: list[dict],
    shifts_data: list[dict],
    regulatory_data: list[dict] | None = None,
    boss_data: list[dict] | None = None,
) -> str:
    """Generate morning briefing text with 🎯 action items first."""
    weekday_names = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    day_name = weekday_names[target_date.weekday()]
    header = f"Доброе утро. Сводка на {target_date.strftime('%d.%m')} ({day_name}):"

    # Categorize tasks
    to_delegate = []
    to_check = []
    to_report = []
    to_close = []
    overdue = []
    today_tasks = []
    in_progress = []
    backlog = []

    for t in tasks_data:
        status = _get_status_value(t.get("status", ""))
        owner_action = _get_status_value(t.get("owner_action", ""))
        task_type = _get_status_value(t.get("task_type", ""))
        title = t.get("title", "?")
        assignee = _get_link_value(t.get("assignee", ""))

        if status == "draft" and task_type == "delegate":
            to_delegate.append(f"- {title} (нет исполнителя)")
        elif owner_action == "check" or (status == "done" and owner_action != "close"):
            to_check.append(f"- {title} ({assignee})")
        elif owner_action == "report" or task_type in ("boss_control", "report_up"):
            deadline = t.get("boss_deadline") or t.get("deadline", "")
            to_report.append(f"- {title} | дедлайн: {deadline}")
        elif status == "done":
            to_close.append(f"- {title} ({assignee})")
        elif status == "overdue":
            overdue.append(f"- {title} | {assignee}")
        elif status in ("assigned", "in_progress"):
            dl = t.get("deadline", "")
            if dl and str(dl)[:10] == target_date.isoformat():
                today_tasks.append(f"- {title} | {assignee}")
            else:
                in_progress.append(f"- {title} | {assignee}")
        elif task_type == "backlog":
            backlog.append(title)

    # Build sections
    sections = [header, ""]

    # 🎯 Action items — always first
    action_items = []
    if to_delegate:
        action_items.append("Делегировать:")
        action_items.extend(to_delegate)
    if to_check:
        action_items.append("Проверить:")
        action_items.extend(to_check)
    if to_report:
        action_items.append("Доложить руководству:")
        action_items.extend(to_report)
    if to_close:
        action_items.append("Закрыть:")
        action_items.extend(to_close)

    if action_items:
        sections.append("🎯 ТЕБЕ НУЖНО СДЕЛАТЬ:")
        sections.extend(action_items)
        sections.append("")

    # ⬆️ Boss control
    boss_items = [
        t for t in tasks_data
        if _get_status_value(t.get("task_type", "")) in ("boss_control", "report_up")
        and _get_status_value(t.get("status", "")) not in ("done", "cancelled")
    ]
    if boss_items:
        sections.append("⬆️ НА КОНТРОЛЕ У РУКОВОДСТВА:")
        for t in boss_items:
            title = t.get("title", "?")
            dl = t.get("boss_deadline") or t.get("deadline", "")
            status = _get_status_value(t.get("status", ""))
            sections.append(f"- {title} | дедлайн: {dl} | {status}")
        sections.append("")

    # 📜 Regulatory
    if regulatory_data:
        upcoming = [
            r for r in regulatory_data
            if _get_status_value(r.get("status", "")) not in ("done",)
        ]
        if upcoming:
            sections.append("📜 РЕГУЛЯТОРНЫЕ ДЕДЛАЙНЫ:")
            for r in upcoming[:5]:
                sections.append(
                    f"- {r.get('regulation', '')} | "
                    f"{r.get('requirement', '')[:60]} | "
                    f"срок: {r.get('deadline', '')} | "
                    f"статус: {_get_status_value(r.get('status', ''))}"
                )
            sections.append("")

    # 👥 Shifts
    from services.shift_manager import who_on_shift
    on_duty = who_on_shift(target_date, shifts_data)
    if on_duty:
        sections.append("👥 СЕЙЧАС НА СМЕНЕ:")
        for s in on_duty:
            emp = _get_link_value(s.get("employee", ""))
            stype = s.get("shift_type", "")
            sstart = s.get("shift_start", "")
            send = s.get("shift_end", "")
            sections.append(f"- {emp} ({stype} {sstart}–{send})")
        sections.append("")

    # 🔴 Overdue
    if overdue:
        sections.append(f"🔴 ПРОСРОЧЕНО ({len(overdue)}):")
        sections.extend(overdue)
        sections.append("")

    # 🟡 Today
    if today_tasks:
        sections.append(f"🟡 СЕГОДНЯ ({len(today_tasks)}):")
        sections.extend(today_tasks)
        sections.append("")

    # 🟢 In progress
    if in_progress:
        sections.append(f"🟢 В РАБОТЕ ({len(in_progress)}):")
        for item in in_progress[:10]:
            sections.append(item)
        if len(in_progress) > 10:
            sections.append(f"  ... и ещё {len(in_progress) - 10}")
        sections.append("")

    # 📋 Backlog
    if backlog:
        old_count = len(backlog)
        sections.append(f"📋 БЭКЛОГ: {old_count} задач")
        sections.append("")

    return "\n".join(sections).strip()


def generate_handover_push(
    now: datetime,
    shifts_data: list[dict],
    tasks_data: list[dict],
) -> str:
    """Generate shift handover notification."""
    from services.shift_manager import current_shift_info, shift_load

    info = current_shift_info(now, shifts_data)
    on_duty = info.get("on_duty", [])
    next_s = info.get("next_shift")

    sections = []
    for duty in on_duty:
        emp = _get_link_value(duty.get("employee", ""))
        stype = duty.get("shift_type", "")
        send = duty.get("shift_end", "")

        # Find unclosed tasks for this employee
        unclosed = []
        for t in tasks_data:
            if _get_status_value(t.get("status", "")) in ("assigned", "in_progress"):
                assignee = t.get("assignee")
                if isinstance(assignee, list):
                    emp_ids = [a.get("id") for a in assignee if isinstance(a, dict)]
                else:
                    emp_ids = []
                # Simplified — just show if employee name matches
                title = t.get("title", "?")
                priority = _get_status_value(t.get("priority", "normal"))
                unclosed.append(f"  {title} (приоритет: {priority})")

        if stype == "day":
            sections.append(f"Дневная смена {emp} заканчивается в {send}.")
        elif stype == "night":
            sections.append(f"Ночная смена {emp} заканчивается в {send}.")

        if unclosed:
            sections.append(f"Незакрытые ({len(unclosed)}):")
            sections.extend(unclosed[:5])

    if next_s:
        next_emp = _get_link_value(next_s.get("employee", ""))
        sections.append(f"\n{next_emp} заступает на {next_s.get('shift_type', '')} в {next_s.get('shift_start', '')}.")
        sections.append("Перенести незакрытые?")

    return "\n".join(sections).strip() if sections else "Нет активных смен для передачи."


def generate_weekly_summary(
    start: date,
    end: date,
    tasks_data: list[dict],
    employees_data: list[dict],
) -> str:
    """Generate weekly statistics summary."""
    # Filter tasks for period
    period_tasks = []
    for t in tasks_data:
        sd = t.get("source_date") or t.get("assigned_date", "")
        if sd:
            try:
                d = date.fromisoformat(str(sd)[:10])
                if start <= d <= end:
                    period_tasks.append(t)
                    continue
            except (ValueError, TypeError):
                pass
        # Include if status changed in period
        cd = t.get("completed_date", "")
        if cd:
            try:
                d = date.fromisoformat(str(cd)[:10])
                if start <= d <= end:
                    period_tasks.append(t)
            except (ValueError, TypeError):
                pass

    total = len(period_tasks)
    completed = sum(1 for t in period_tasks if _get_status_value(t.get("status", "")) == "done")
    overdue_count = sum(1 for t in period_tasks if _get_status_value(t.get("status", "")) == "overdue")
    in_progress_count = sum(
        1 for t in period_tasks
        if _get_status_value(t.get("status", "")) in ("assigned", "in_progress")
    )

    sections = [
        f"📊 ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ ({start.strftime('%d.%m')} — {end.strftime('%d.%m')})",
        "",
        "ОБЩАЯ СТАТИСТИКА:",
        f"- Поставлено: {total} | Выполнено: {completed} | Просрочено: {overdue_count} | В работе: {in_progress_count}",
        "",
    ]

    # Per employee
    emp_stats: dict[str, dict] = {}
    for t in period_tasks:
        assignee = _get_link_value(t.get("assignee", ""))
        if not assignee:
            continue
        if assignee not in emp_stats:
            emp_stats[assignee] = {"total": 0, "done": 0, "overdue": 0}
        emp_stats[assignee]["total"] += 1
        status = _get_status_value(t.get("status", ""))
        if status == "done":
            emp_stats[assignee]["done"] += 1
        elif status == "overdue":
            emp_stats[assignee]["overdue"] += 1

    if emp_stats:
        sections.append("ИСПОЛНИТЕЛИ:")
        for i, (name, stats) in enumerate(sorted(emp_stats.items()), 1):
            total_e = stats["total"]
            on_time = stats["done"]
            rate = f"{on_time / total_e * 100:.0f}%" if total_e else "—"
            marker = "✅" if on_time == total_e else ("🔴" if stats["overdue"] > total_e * 0.3 else "")
            sections.append(f"{i}. {name} — {total_e} задач, {rate} в срок {marker}")
        sections.append("")

    return "\n".join(sections).strip()


def generate_weekend_plan(
    shifts_data: list[dict],
    tasks_data: list[dict],
    backlog_data: list[dict] | None = None,
) -> str:
    """Generate Friday weekend loading proposal."""
    today = date.today()
    # Find Saturday and Sunday
    days_until_sat = (5 - today.weekday()) % 7
    if days_until_sat == 0:
        days_until_sat = 7
    saturday = today + timedelta(days=days_until_sat)
    sunday = saturday + timedelta(days=1)

    from services.shift_manager import who_on_shift

    sections = [f"📋 ПЛАН НА ВЫХОДНЫЕ ({saturday.strftime('%d.%m')}–{sunday.strftime('%d.%m')}):", ""]

    # Show who's on duty
    sections.append("Дежурные на сб–вс:")
    for d, label in [(saturday, "Сб"), (sunday, "Вс")]:
        on_duty = who_on_shift(d, shifts_data)
        for s in on_duty:
            emp = _get_link_value(s.get("employee", ""))
            stype = s.get("shift_type", "")
            sections.append(f"- {label} {stype} ({s.get('shift_start', '')}–{s.get('shift_end', '')}): {emp}")

    # Backlog suggestions
    if backlog_data:
        sections.append("")
        sections.append("Можно передать из бэклога:")
        for i, t in enumerate(backlog_data[:5], 1):
            sections.append(f"{i}. {t.get('title', '?')}")

    sections.append("")
    sections.append("Утвердить? Скорректировать?")

    return "\n".join(sections).strip()


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
    parser = argparse.ArgumentParser(description="Notification content generator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_brief = sub.add_parser("briefing")
    p_brief.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_brief.add_argument("--tasks", required=True)
    p_brief.add_argument("--shifts", required=True)
    p_brief.add_argument("--regulatory", default=None)
    p_brief.add_argument("--boss", default=None)

    p_push = sub.add_parser("handover_push")
    p_push.add_argument("--shifts", required=True)
    p_push.add_argument("--tasks", required=True)

    p_week = sub.add_parser("weekly_summary")
    p_week.add_argument("--start", required=True)
    p_week.add_argument("--end", required=True)
    p_week.add_argument("--tasks", required=True)
    p_week.add_argument("--employees", required=True)

    p_wknd = sub.add_parser("weekend_plan")
    p_wknd.add_argument("--shifts", required=True)
    p_wknd.add_argument("--tasks", required=True)
    p_wknd.add_argument("--backlog", default=None)

    p_work = sub.add_parser("is_working_time")

    p_notify = sub.add_parser("should_notify")
    p_notify.add_argument("--type", required=True, choices=["briefing", "push", "anomaly"])

    args = parser.parse_args()

    try:
        if args.command == "briefing":
            tasks = _load_json_file(args.tasks)
            shifts = _load_json_file(args.shifts)
            regulatory = _load_json_file(args.regulatory) if args.regulatory else None
            d = date.fromisoformat(args.date)
            text = generate_briefing(d, tasks, shifts, regulatory)
            output_json({"text": text})

        elif args.command == "handover_push":
            shifts = _load_json_file(args.shifts)
            tasks = _load_json_file(args.tasks)
            text = generate_handover_push(datetime.now(), shifts, tasks)
            output_json({"text": text})

        elif args.command == "weekly_summary":
            tasks = _load_json_file(args.tasks)
            employees = _load_json_file(args.employees)
            start = date.fromisoformat(args.start)
            end = date.fromisoformat(args.end)
            text = generate_weekly_summary(start, end, tasks, employees)
            output_json({"text": text})

        elif args.command == "weekend_plan":
            shifts = _load_json_file(args.shifts)
            tasks = _load_json_file(args.tasks)
            backlog = _load_json_file(args.backlog) if args.backlog else None
            text = generate_weekend_plan(shifts, tasks, backlog)
            output_json({"text": text})

        elif args.command == "is_working_time":
            result = is_working_time()
            output_json({"is_working_time": result, "now": datetime.now().isoformat()})

        elif args.command == "should_notify":
            result = should_notify(notification_type=args.type)
            output_json({"should_notify": result, "type": args.type})

    except (RuntimeError, ValueError, json.JSONDecodeError, FileNotFoundError) as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
