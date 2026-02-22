"""Аналитика почты: статистика, трудозатраты, отчётность.

Собирает данные из email_inbox для включения в отчёты task-control.
Показывает: объём переписки, распределение по категориям,
трудозатраты по типам работ, нагрузка от СЭД.

CLI: python -m services.analytics summary --period weekly [--start YYYY-MM-DD]
     python -m services.analytics effort --period weekly [--start YYYY-MM-DD]
     python -m services.analytics sed_stats --period weekly
     python -m services.analytics report_data --period weekly
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    load_config, get_baserow_token, get_baserow_url,
    output_json, output_error
)

try:
    import requests
except ImportError:
    requests = None

MAX_RETRIES = 3
BACKOFF_BASE = 1.0


def _baserow_headers() -> dict:
    return {
        "Authorization": f"Token {get_baserow_token()}",
        "Content-Type": "application/json",
    }


def _get_table_id(name: str) -> int:
    cfg = load_config()
    return cfg["baserow"]["tables"].get(name, 0)


def _list_rows(table_id: int, filters: dict | None = None, size: int = 200) -> list[dict]:
    """Получает строки из Baserow с пагинацией."""
    if not requests:
        return []
    url = f"{get_baserow_url()}/api/database/rows/table/{table_id}/"
    params = {"user_field_names": "true", "size": size}
    if filters:
        params.update(filters)

    all_rows = []
    page = 1
    while True:
        params["page"] = page
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, headers=_baserow_headers(), params=params, timeout=15)
                if resp.status_code == 429:
                    import time
                    time.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException:
                if attempt == MAX_RETRIES - 1:
                    raise
        data = resp.json()
        all_rows.extend(data.get("results", []))
        if not data.get("next"):
            break
        page += 1
    return all_rows


def _parse_date(val) -> date | None:
    if not val:
        return None
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _period_range(period: str, start: str | None = None) -> tuple[date, date]:
    """Вычисляет начало и конец периода."""
    today = date.today()
    if start:
        period_start = date.fromisoformat(start)
    elif period == "weekly":
        period_start = today - timedelta(days=today.weekday())  # Понедельник
    elif period == "monthly":
        period_start = today.replace(day=1)
    elif period == "daily":
        period_start = today
    else:
        period_start = today - timedelta(days=7)

    if period == "weekly":
        period_end = period_start + timedelta(days=6)
    elif period == "monthly":
        next_month = period_start.replace(day=28) + timedelta(days=4)
        period_end = next_month - timedelta(days=next_month.day)
    elif period == "daily":
        period_end = period_start
    else:
        period_end = today

    return period_start, min(period_end, today)


def _filter_by_period(rows: list[dict], start: date, end: date) -> list[dict]:
    """Фильтрует строки по периоду (поле received_at)."""
    result = []
    for r in rows:
        d = _parse_date(r.get("received_at"))
        if d and start <= d <= end:
            result.append(r)
    return result


def compute_summary(period: str = "weekly", start: str | None = None) -> dict:
    """Общая статистика почты за период."""
    table_id = _get_table_id("email_inbox")
    if not table_id:
        return {"error": "email_inbox table not configured"}

    rows = _list_rows(table_id)
    period_start, period_end = _period_range(period, start)
    filtered = _filter_by_period(rows, period_start, period_end)

    # Счётчики
    total = len(filtered)
    by_priority = Counter()
    by_category = Counter()
    by_status = Counter()
    by_action = Counter()
    vip_count = 0
    with_attachments = 0
    sed_count = 0

    for r in filtered:
        p = r.get("priority")
        if isinstance(p, dict):
            p = p.get("value", "")
        by_priority[p or "unknown"] += 1

        c = r.get("category")
        if isinstance(c, dict):
            c = c.get("value", "")
        by_category[c or "unknown"] += 1

        s = r.get("status")
        if isinstance(s, dict):
            s = s.get("value", "")
        by_status[s or "unknown"] += 1

        a = r.get("owner_decision") or r.get("proposed_action") or ""
        if a:
            by_action[a] += 1

        if r.get("is_vip"):
            vip_count += 1
        if r.get("has_attachments"):
            with_attachments += 1
        if (isinstance(r.get("category"), dict) and r["category"].get("value") == "sed") or r.get("category") == "sed":
            sed_count += 1

    return {
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_emails": total,
        "by_priority": dict(by_priority),
        "by_category": dict(by_category),
        "by_status": dict(by_status),
        "by_action": dict(by_action),
        "vip_emails": vip_count,
        "sed_emails": sed_count,
        "with_attachments": with_attachments,
    }


def compute_effort(period: str = "weekly", start: str | None = None) -> dict:
    """Трудозатраты по почте за период."""
    table_id = _get_table_id("email_inbox")
    if not table_id:
        return {"error": "email_inbox table not configured"}

    rows = _list_rows(table_id)
    period_start, period_end = _period_range(period, start)
    filtered = _filter_by_period(rows, period_start, period_end)

    total_minutes = 0
    by_effort_category = defaultdict(int)
    by_email_category = defaultdict(int)

    for r in filtered:
        minutes = r.get("effort_minutes") or 0
        if isinstance(minutes, str):
            try:
                minutes = int(minutes)
            except ValueError:
                minutes = 0
        total_minutes += minutes

        ec = r.get("effort_category")
        if isinstance(ec, dict):
            ec = ec.get("value", "")
        if ec and minutes:
            by_effort_category[ec] += minutes

        cat = r.get("category")
        if isinstance(cat, dict):
            cat = cat.get("value", "")
        if cat and minutes:
            by_email_category[cat] += minutes

    total_hours = round(total_minutes / 60, 1)
    emails_count = len(filtered)

    return {
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_emails": emails_count,
        "total_effort_minutes": total_minutes,
        "total_effort_hours": total_hours,
        "avg_minutes_per_email": round(total_minutes / emails_count, 1) if emails_count else 0,
        "by_effort_type": dict(by_effort_category),
        "by_email_category": dict(by_email_category),
        "effort_labels": {
            "sed_review": "Рассмотрение СЭД",
            "sed_execution": "Исполнение поручений СЭД",
            "incident_response": "Реагирование на инциденты",
            "report_preparation": "Подготовка отчётов/справок",
            "meeting_prep": "Подготовка к совещаниям",
            "correspondence": "Деловая переписка",
            "other": "Прочее",
        },
    }


def compute_sed_stats(period: str = "weekly", start: str | None = None) -> dict:
    """Детальная статистика по СЭД."""
    table_id = _get_table_id("email_inbox")
    if not table_id:
        return {"error": "email_inbox table not configured"}

    rows = _list_rows(table_id)
    period_start, period_end = _period_range(period, start)
    filtered = _filter_by_period(rows, period_start, period_end)

    sed_rows = []
    for r in filtered:
        cat = r.get("category")
        if isinstance(cat, dict):
            cat = cat.get("value", "")
        if cat == "sed":
            sed_rows.append(r)

    # Группировка по автору резолюции
    by_author = Counter()
    by_status = Counter()
    with_deadlines = 0
    overdue_risk = 0

    for r in sed_rows:
        author = r.get("sed_resolution_author") or "Не указан"
        by_author[author] += 1

        s = r.get("status")
        if isinstance(s, dict):
            s = s.get("value", "")
        by_status[s or "new"] += 1

        if r.get("sed_deadline") or r.get("extracted_deadlines"):
            with_deadlines += 1
            # Проверяем на риск просрочки
            deadline_str = r.get("sed_deadline") or ""
            if deadline_str:
                try:
                    dl = datetime.strptime(deadline_str, "%d.%m.%Y").date()
                    if dl <= date.today() + timedelta(days=2):
                        overdue_risk += 1
                except ValueError:
                    pass

    return {
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_sed": len(sed_rows),
        "by_resolution_author": dict(by_author),
        "by_status": dict(by_status),
        "with_deadlines": with_deadlines,
        "overdue_risk": overdue_risk,
    }


def compute_report_data(period: str = "weekly", start: str | None = None) -> dict:
    """Полные данные для включения в отчёт task-control.

    Возвращает готовый блок для секции 'Работа с электронной почтой'.
    """
    summary = compute_summary(period, start)
    effort = compute_effort(period, start)
    sed = compute_sed_stats(period, start)

    # Формируем текстовое описание для отчёта
    lines = []
    lines.append(f"За период {summary['period_start']} — {summary['period_end']}:")
    lines.append(f"Обработано писем: {summary['total_emails']}")

    if summary["by_category"]:
        cat_labels = {
            "sed": "СЭД", "task": "поручения", "report": "отчёты",
            "incident": "инциденты", "info": "информационные",
            "meeting": "совещания", "external": "внешние", "newsletter": "рассылки",
        }
        cat_parts = []
        for cat, count in sorted(summary["by_category"].items(), key=lambda x: -x[1]):
            label = cat_labels.get(cat, cat)
            cat_parts.append(f"{label} — {count}")
        lines.append(f"Категории: {', '.join(cat_parts)}")

    if summary["vip_emails"]:
        lines.append(f"От руководства (VIP): {summary['vip_emails']}")

    if effort["total_effort_hours"]:
        lines.append(f"Трудозатраты: {effort['total_effort_hours']} ч.")
        if effort["by_effort_type"]:
            for etype, minutes in sorted(effort["by_effort_type"].items(), key=lambda x: -x[1]):
                label = effort["effort_labels"].get(etype, etype)
                hours = round(minutes / 60, 1)
                lines.append(f"  — {label}: {hours} ч.")

    if sed["total_sed"]:
        lines.append(f"СЭД: {sed['total_sed']} документов")
        if sed["overdue_risk"]:
            lines.append(f"  ⚠ Риск просрочки: {sed['overdue_risk']}")

    return {
        "summary": summary,
        "effort": effort,
        "sed_stats": sed,
        "report_text": "\n".join(lines),
        "report_section_title": "Работа с электронной почтой",
    }


def main():
    parser = argparse.ArgumentParser(description="Email analytics")
    sub = parser.add_subparsers(dest="command")

    for cmd in ["summary", "effort", "sed_stats", "report_data"]:
        p = sub.add_parser(cmd)
        p.add_argument("--period", default="weekly", choices=["daily", "weekly", "monthly"])
        p.add_argument("--start", default=None, help="Start date YYYY-MM-DD")

    args = parser.parse_args()

    funcs = {
        "summary": compute_summary,
        "effort": compute_effort,
        "sed_stats": compute_sed_stats,
        "report_data": compute_report_data,
    }

    if args.command in funcs:
        output_json(funcs[args.command](args.period, args.start))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
