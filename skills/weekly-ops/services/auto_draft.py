"""Auto-draft generator for plans and reports.

Generates draft plans (carry-over + active tasks) and draft reports
(plan items + statuses + formulation memory) without requiring
manual data entry. Saves drafts to DB for owner review.

CLI usage:
    python -m services.auto_draft report --period-start 2026-03-02 --period-end 2026-03-06
    python -m services.auto_draft plan --period-start 2026-03-09 --period-end 2026-03-13
    python -m services.auto_draft questions --period-start 2026-03-02 --period-end 2026-03-06
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta

from config.settings import load_config, output_json, output_error
from services.db import (
    get_plan_items,
    get_active_plan_items,
    get_latest_plan_version,
    get_latest_report_version,
    save_plan_items,
    save_plan_version,
    save_report_version,
    search_formulation,
    get_all_formulations_as_dict,
    get_feedback_stats,
)


# ---------------------------------------------------------------------------
# Auto-draft REPORT
# ---------------------------------------------------------------------------

def draft_report(period_start: str, period_end: str,
                 period_type: str = "weekly") -> dict:
    """Generate a draft report based on the approved plan for the period.

    Steps:
    1. Load plan items for the period
    2. For each item, search formulation memory for completion text
    3. Mark items without clear status as needing questions
    4. Save as draft report version

    Returns dict with items, questions, and version info.
    """
    config = load_config()

    # 1. Get plan items for this period
    plan_items = get_plan_items(period_start, period_end)

    if not plan_items:
        # Try to get from latest plan version
        plan_ver = get_latest_plan_version(period_start, period_end)
        if plan_ver and plan_ver.get("items"):
            plan_items = plan_ver["items"]

    if not plan_items:
        return {
            "status": "no_plan",
            "message": f"Нет плана за период {period_start} – {period_end}. "
                       "Сначала нужно создать план.",
            "items": [],
            "questions": [],
        }

    # 2. Build report items from plan
    formulations = get_all_formulations_as_dict()
    report_items = []
    questions = []
    needs_input = []

    for i, item in enumerate(plan_items, 1):
        desc = item.get("description", "") if isinstance(item, dict) else item
        deadline = item.get("deadline", "") if isinstance(item, dict) else ""
        responsible = item.get("responsible", "") if isinstance(item, dict) else ""
        status = item.get("status", "planned") if isinstance(item, dict) else "planned"

        # Search formulation memory
        fm = search_formulation(desc)
        completion_note = ""

        if status == "done":
            # Item already marked done — use its completion note or memory
            completion_note = (item.get("completion_note", "")
                               if isinstance(item, dict) else "")
            if not completion_note and fm and fm.get("status_done_text"):
                completion_note = fm["status_done_text"]
            if not completion_note:
                completion_note = "Выполнено."
        elif status == "in_progress":
            completion_note = (item.get("completion_note", "")
                               if isinstance(item, dict) else "")
            if not completion_note and fm and fm.get("status_in_progress_text"):
                completion_note = fm["status_in_progress_text"]
            if not completion_note:
                # Need to ask owner
                completion_note = "[Требуется уточнение]"
                needs_input.append(i)
        else:
            # planned / carried_over — unclear status
            if fm and fm.get("status_done_text"):
                completion_note = fm["status_done_text"]
            else:
                completion_note = "[Требуется уточнение]"
                needs_input.append(i)

        report_items.append({
            "item_number": i,
            "description": desc,
            "deadline": deadline,
            "responsible": responsible,
            "completion_note": completion_note,
            "is_unplanned": item.get("is_unplanned", False) if isinstance(item, dict) else False,
            "status": status,
            "auto_filled": bool(fm),
        })

    # 3. Generate questions for unclear items
    for idx in needs_input:
        item = report_items[idx - 1]
        questions.append({
            "item_number": idx,
            "description": item["description"],
            "question": f"По пункту {idx} «{item['description'][:80]}» — "
                        "какой статус? Что сделано? (выполнено / в работе X% / перенесено)",
        })

    # 4. Save as draft version
    version = save_report_version(
        period_start, period_end, period_type,
        report_items, status="draft"
    )

    return {
        "status": "draft",
        "version": version,
        "period": f"{period_start} – {period_end}",
        "total_items": len(report_items),
        "auto_filled": sum(1 for it in report_items if it.get("auto_filled")),
        "needs_input": len(needs_input),
        "items": report_items,
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Auto-draft PLAN
# ---------------------------------------------------------------------------

def draft_plan(period_start: str, period_end: str,
               period_type: str = "weekly") -> dict:
    """Generate a draft plan for the next period.

    Steps:
    1. Get carry-over items (in_progress/planned from previous period)
    2. Add mandatory items
    3. Check feedback stats to avoid items owner frequently deletes
    4. Save as draft plan version

    Returns dict with items and version info.
    """
    config = load_config()
    rules = config.get("rules", {})
    mandatory = rules.get("mandatory_items", [])
    exclude_topics = [t.lower() for t in rules.get("exclude_topics", [])]

    # 1. Get previous period's plan to carry over unfinished items
    prev_start, prev_end = _previous_period(period_start, period_end, period_type)

    carry_over = []
    if prev_start and prev_end:
        prev_items = get_plan_items(prev_start, prev_end)
        # Also check latest report to see what was done
        prev_report = get_latest_report_version(prev_start, prev_end)
        done_descs = set()
        if prev_report and prev_report.get("items"):
            for ri in prev_report["items"]:
                note = ri.get("completion_note", "").lower()
                if "выполнено" in note:
                    done_descs.add(ri.get("description", "").lower())

        for item in prev_items:
            desc = item.get("description", "")
            status = item.get("status", "planned")
            # Carry over if not done
            if desc.lower() not in done_descs and status != "done":
                if not _is_excluded(desc, exclude_topics):
                    carry_over.append({
                        "description": desc,
                        "deadline": item.get("deadline", "В течение недели"),
                        "responsible": item.get("responsible", ""),
                        "status": "carried_over",
                        "is_unplanned": False,
                    })

    # 2. Also pull active plan items (across all periods)
    active = get_active_plan_items()
    existing_descs = {it["description"].lower() for it in carry_over}

    for item in active:
        desc = item.get("description", "")
        if (desc.lower() not in existing_descs
                and not _is_excluded(desc, exclude_topics)):
            # Only add if not from current period
            if item.get("period_start") != period_start:
                carry_over.append({
                    "description": desc,
                    "deadline": item.get("deadline", "В течение недели"),
                    "responsible": item.get("responsible", ""),
                    "status": "carried_over",
                    "is_unplanned": False,
                })
                existing_descs.add(desc.lower())

    # 3. Add mandatory items if not already present
    plan_items = list(carry_over)
    for m in mandatory:
        m_desc = m["description"]
        if not _overlaps_any(m_desc, existing_descs):
            plan_items.insert(0, {
                "description": m_desc,
                "deadline": m.get("deadline", "В течение недели"),
                "responsible": m.get("responsible", ""),
                "status": "planned",
                "is_unplanned": False,
            })

    # 4. Check feedback — avoid items owner frequently deletes
    feedback = get_feedback_stats(prev_start or "", prev_end or "")
    # (feedback stats are aggregate — detailed per-item filtering
    #  would require more granular queries, future enhancement)

    # 5. Renumber
    for i, item in enumerate(plan_items, 1):
        item["item_number"] = i

    # 6. Save draft
    count = save_plan_items(plan_items, period_start, period_end, period_type)
    version = save_plan_version(
        period_start, period_end, period_type,
        plan_items, status="draft"
    )

    return {
        "status": "draft",
        "version": version,
        "period": f"{period_start} – {period_end}",
        "total_items": len(plan_items),
        "carried_over": sum(1 for it in plan_items if it.get("status") == "carried_over"),
        "mandatory": sum(1 for it in plan_items if it.get("status") == "planned"),
        "items": plan_items,
    }


# ---------------------------------------------------------------------------
# Questions module
# ---------------------------------------------------------------------------

def generate_questions(period_start: str, period_end: str) -> list[dict]:
    """Generate clarifying questions about plan items for report building.

    Looks at each plan item and generates specific questions to fill gaps
    in the report draft. Questions help owner provide completion status,
    percentages, key results.

    Returns list of question dicts.
    """
    plan_items = get_plan_items(period_start, period_end)

    if not plan_items:
        plan_ver = get_latest_plan_version(period_start, period_end)
        if plan_ver and plan_ver.get("items"):
            plan_items = plan_ver["items"]

    if not plan_items:
        return [{
            "item_number": 0,
            "question": f"Нет плана за {period_start} – {period_end}. Что было сделано на этой неделе?",
            "type": "general",
        }]

    questions = []

    for item in plan_items:
        desc = item.get("description", "")
        status = item.get("status", "planned")
        completion = item.get("completion_note", "")
        num = item.get("item_number", 0)

        # Skip items that already have clear completion notes
        if completion and not completion.startswith("["):
            continue

        # Generate specific question based on task type
        q = _make_question(num, desc, status)
        if q:
            questions.append(q)

    return questions


def format_questions_message(questions: list[dict]) -> str:
    """Format questions as a Telegram message for owner."""
    if not questions:
        return "Все пункты плана имеют отметки. Черновик отчёта готов."

    lines = ["📋 Для подготовки отчёта уточни по следующим пунктам:\n"]

    for q in questions:
        num = q["item_number"]
        lines.append(f"❓ п.{num}: {q['question']}")

    lines.append("\nОтвечай в формате: «п.2 — выполнено, акт подписан»")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _previous_period(start: str, end: str,
                     period_type: str) -> tuple[str, str]:
    """Calculate the previous period dates."""
    try:
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "", ""

    if period_type == "weekly":
        prev_end = s - timedelta(days=1)
        prev_start = prev_end - timedelta(days=(e - s).days)
        # Align to Monday
        while prev_start.weekday() != 0:
            prev_start -= timedelta(days=1)
        # Align end to Friday
        prev_end = prev_start + timedelta(days=4)
    else:
        # Monthly — previous month
        first_day = s.replace(day=1)
        prev_end = first_day - timedelta(days=1)
        prev_start = prev_end.replace(day=1)

    return str(prev_start), str(prev_end)


def _is_excluded(text: str, exclude_topics: list[str]) -> bool:
    """Check if text matches any excluded topic."""
    text_lower = text.lower()
    return any(topic in text_lower for topic in exclude_topics)


def _overlaps_any(text: str, existing: set[str], threshold: float = 0.5) -> bool:
    """Check keyword overlap with existing items."""
    words = {w.lower() for w in text.split() if len(w) > 3}
    if not words:
        return False
    for ex in existing:
        ex_words = {w for w in ex.split() if len(w) > 3}
        if not ex_words:
            continue
        overlap = words & ex_words
        if len(overlap) / min(len(words), len(ex_words)) >= threshold:
            return True
    return False


def _make_question(num: int, desc: str, status: str) -> dict | None:
    """Generate a specific question for a plan item."""
    desc_short = desc[:80] + ("…" if len(desc) > 80 else "")

    # Detect task type for better questions
    desc_lower = desc.lower()

    if any(kw in desc_lower for kw in ["совещание", "встреча", "обсуждение"]):
        return {
            "item_number": num,
            "description": desc,
            "question": f"«{desc_short}» — состоялось? Ключевые решения?",
            "type": "meeting",
        }
    elif any(kw in desc_lower for kw in ["согласование", "утверждение", "подписание"]):
        return {
            "item_number": num,
            "description": desc,
            "question": f"«{desc_short}» — документ согласован/подписан? На каком этапе?",
            "type": "approval",
        }
    elif any(kw in desc_lower for kw in ["мониторинг", "контроль"]):
        return {
            "item_number": num,
            "description": desc,
            "question": f"«{desc_short}» — сколько событий/инцидентов? Ключевые выводы?",
            "type": "monitoring",
        }
    elif any(kw in desc_lower for kw in ["разработка", "подготовка", "создание"]):
        return {
            "item_number": num,
            "description": desc,
            "question": f"«{desc_short}» — готово? Если в работе — какой процент?",
            "type": "development",
        }
    elif any(kw in desc_lower for kw in ["проверка", "аудит", "анализ"]):
        return {
            "item_number": num,
            "description": desc,
            "question": f"«{desc_short}» — проверка завершена? Какие результаты?",
            "type": "audit",
        }
    else:
        return {
            "item_number": num,
            "description": desc,
            "question": f"«{desc_short}» — выполнено / в работе / перенесено?",
            "type": "general",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-draft for weekly-ops")
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="Draft report from plan items")
    p_report.add_argument("--period-start", required=True)
    p_report.add_argument("--period-end", required=True)
    p_report.add_argument("--type", default="weekly", choices=["weekly", "monthly"])

    p_plan = sub.add_parser("plan", help="Draft plan with carry-over")
    p_plan.add_argument("--period-start", required=True)
    p_plan.add_argument("--period-end", required=True)
    p_plan.add_argument("--type", default="weekly", choices=["weekly", "monthly"])

    p_q = sub.add_parser("questions", help="Generate questions for report")
    p_q.add_argument("--period-start", required=True)
    p_q.add_argument("--period-end", required=True)
    p_q.add_argument("--format", default="json", choices=["json", "message"])

    args = parser.parse_args()

    try:
        if args.command == "report":
            result = draft_report(args.period_start, args.period_end, args.type)
            output_json(result)

        elif args.command == "plan":
            result = draft_plan(args.period_start, args.period_end, args.type)
            output_json(result)

        elif args.command == "questions":
            questions = generate_questions(args.period_start, args.period_end)
            if args.format == "message":
                print(format_questions_message(questions))
            else:
                output_json(questions)

    except Exception as e:
        output_error(str(e))


if __name__ == "__main__":
    main()
