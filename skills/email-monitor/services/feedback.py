"""Система обучения на обратной связи owner'а.

Хранит feedback в Baserow, строит профили отправителей,
повышает confidence при подтверждении паттернов.

CLI: python -m services.feedback record --sender EMAIL --action ACTION [--priority PRI] [--category CAT]
     python -m services.feedback profile --sender EMAIL
     python -m services.feedback history [--sender EMAIL] [--limit N]
     python -m services.feedback stats
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    load_config, get_baserow_token, get_baserow_url,
    output_json, output_error
)
from models.enums import Priority, Category, OwnerAction, PatternType

try:
    import requests
except ImportError:
    requests = None


def _baserow_headers() -> dict:
    return {
        "Authorization": f"Token {get_baserow_token()}",
        "Content-Type": "application/json",
    }


def _baserow_url(table_id: int, row_id: int | None = None) -> str:
    base = get_baserow_url()
    if row_id:
        return f"{base}/api/database/rows/table/{table_id}/{row_id}/"
    return f"{base}/api/database/rows/table/{table_id}/"


def _get_table_id(table_name: str) -> int:
    cfg = load_config()
    tid = cfg["baserow"]["tables"].get(table_name, 0)
    if not tid:
        output_error(f"Table ID для '{table_name}' не настроен в config.json")
    return tid


def record_feedback(sender_email: str, sender_name: str = "",
                    action: str = "", priority: str = "",
                    category: str = "", pattern_value: str = "") -> dict:
    """Записать обратную связь owner'а."""
    if not requests:
        return {"error": "requests не установлен", "fallback": "local"}

    table_id = _get_table_id("email_feedback")
    cfg = load_config()["learning"]

    # Ищем существующий feedback для этого отправителя
    existing = _find_feedback(table_id, sender_email)

    if existing:
        # Обновляем: повышаем confidence
        row = existing
        new_confidence = min(1.0, row.get("confidence", 0.5) + cfg["confidence_increment"])
        new_times = row.get("times_confirmed", 1) + 1
        update_data = {
            "confidence": new_confidence,
            "times_confirmed": new_times,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if action:
            update_data["learned_action"] = action
        if priority:
            update_data["learned_priority"] = priority
        if category:
            update_data["learned_category"] = category

        resp = requests.patch(
            _baserow_url(table_id, row["id"]),
            headers=_baserow_headers(),
            json=update_data,
        )
        resp.raise_for_status()
        return {
            "status": "updated",
            "id": row["id"],
            "confidence": new_confidence,
            "times_confirmed": new_times,
        }
    else:
        # Новая запись
        data = {
            "sender_email": sender_email,
            "sender_name": sender_name,
            "pattern_type": PatternType.SENDER.value,
            "pattern_value": pattern_value or sender_email,
            "learned_action": action,
            "learned_priority": priority,
            "learned_category": category,
            "confidence": 0.5,
            "times_confirmed": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        resp = requests.post(
            _baserow_url(table_id),
            headers=_baserow_headers(),
            json=data,
        )
        resp.raise_for_status()
        return {"status": "created", "id": resp.json().get("id")}


def _find_feedback(table_id: int, sender_email: str) -> dict | None:
    """Найти feedback по отправителю."""
    params = {
        "user_field_names": "true",
        "search": sender_email,
        "size": 1,
    }
    resp = requests.get(
        _baserow_url(table_id),
        headers=_baserow_headers(),
        params=params,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    for r in results:
        if r.get("sender_email", "").lower() == sender_email.lower():
            return r
    return None


def get_feedback_history(sender_email: str = "", limit: int = 100) -> list[dict]:
    """Получить историю feedback."""
    if not requests:
        return []

    table_id = _get_table_id("email_feedback")
    params = {
        "user_field_names": "true",
        "size": limit,
        "order_by": "-updated_at",
    }
    if sender_email:
        params["search"] = sender_email

    resp = requests.get(
        _baserow_url(table_id),
        headers=_baserow_headers(),
        params=params,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def get_sender_profile(sender_email: str) -> dict:
    """Построить профиль отправителя из feedback-истории."""
    history = get_feedback_history(sender_email)
    if not history:
        return {"email": sender_email, "status": "unknown", "total_feedbacks": 0}

    # Агрегируем
    actions = {}
    priorities = {}
    categories = {}
    total_conf = 0.0

    for fb in history:
        if fb.get("sender_email", "").lower() != sender_email.lower():
            continue
        a = fb.get("learned_action", "")
        p = fb.get("learned_priority", "")
        c = fb.get("learned_category", "")
        conf = fb.get("confidence", 0.5)

        if a:
            actions[a] = actions.get(a, 0) + conf
        if p:
            priorities[p] = priorities.get(p, 0) + conf
        if c:
            categories[c] = categories.get(c, 0) + conf
        total_conf += conf

    def _top(d: dict) -> str:
        return max(d, key=d.get) if d else ""

    return {
        "email": sender_email,
        "name": history[0].get("sender_name", "") if history else "",
        "default_action": _top(actions),
        "default_priority": _top(priorities),
        "default_category": _top(categories),
        "total_feedbacks": len(history),
        "avg_confidence": round(total_conf / len(history), 2) if history else 0,
        "status": "profiled",
    }


def get_stats() -> dict:
    """Общая статистика по обучению."""
    history = get_feedback_history(limit=500)
    if not history:
        return {"total": 0, "unique_senders": 0, "avg_confidence": 0}

    senders = set()
    total_conf = 0.0
    action_counts = {}

    for fb in history:
        senders.add(fb.get("sender_email", "").lower())
        total_conf += fb.get("confidence", 0)
        a = fb.get("learned_action", "")
        if a:
            action_counts[a] = action_counts.get(a, 0) + 1

    return {
        "total_feedbacks": len(history),
        "unique_senders": len(senders),
        "avg_confidence": round(total_conf / len(history), 2),
        "action_distribution": action_counts,
        "top_confident": sorted(
            history, key=lambda x: x.get("confidence", 0), reverse=True
        )[:5],
    }


def main():
    parser = argparse.ArgumentParser(description="Feedback & learning system")
    sub = parser.add_subparsers(dest="command")

    p_rec = sub.add_parser("record")
    p_rec.add_argument("--sender", required=True, help="Email отправителя")
    p_rec.add_argument("--sender-name", default="")
    p_rec.add_argument("--action", default="", help="OwnerAction value")
    p_rec.add_argument("--priority", default="", help="Priority value")
    p_rec.add_argument("--category", default="", help="Category value")

    p_prof = sub.add_parser("profile")
    p_prof.add_argument("--sender", required=True)

    p_hist = sub.add_parser("history")
    p_hist.add_argument("--sender", default="")
    p_hist.add_argument("--limit", type=int, default=100)

    sub.add_parser("stats")

    args = parser.parse_args()

    if args.command == "record":
        output_json(record_feedback(
            args.sender, args.sender_name,
            args.action, args.priority, args.category
        ))
    elif args.command == "profile":
        output_json(get_sender_profile(args.sender))
    elif args.command == "history":
        output_json(get_feedback_history(args.sender, args.limit))
    elif args.command == "stats":
        output_json(get_stats())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
