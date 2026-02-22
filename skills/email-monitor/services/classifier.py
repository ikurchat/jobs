"""Классификатор писем: приоритет, категория, предлагаемое действие.

Использует правила из config.json + custom_rules.json + feedback из Baserow.

CLI: python -m services.classifier classify --email email.json
     python -m services.classifier batch --emails emails.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import load_config, get_skill_dir, output_json, output_error
from models.enums import Priority, Category, OwnerAction


def _load_rules() -> dict:
    rules_path = get_skill_dir() / "rules" / "custom_rules.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _score_to_priority(score: int) -> Priority:
    if score >= 9:
        return Priority.CRITICAL
    elif score >= 7:
        return Priority.HIGH
    elif score >= 4:
        return Priority.MEDIUM
    elif score >= 1:
        return Priority.LOW
    return Priority.SPAM


def _detect_category(email_data: dict, config: dict) -> Category:
    subject = (email_data.get("subject", "") or "").lower()
    body = (email_data.get("body_preview", "") or "").lower()
    text = f"{subject} {body}"

    sed_keywords = config.get("sed_keywords", [])
    incident_keywords = config.get("incident_keywords", [])
    task_keywords = config.get("task_keywords", [])

    # СЭД
    sed_hits = sum(1 for kw in sed_keywords if kw.lower() in text)
    if sed_hits >= 2 or "сэд" in text or "документооборот" in text:
        return Category.SED

    # Инциденты
    inc_hits = sum(1 for kw in incident_keywords if kw.lower() in text)
    if inc_hits >= 1:
        return Category.INCIDENT

    # Задачи / поручения
    task_hits = sum(1 for kw in task_keywords if kw.lower() in text)
    if task_hits >= 2:
        return Category.TASK

    # Совещания
    meeting_words = ["совещание", "встреча", "созвон", "meeting", "agenda", "протокол"]
    if any(w in text for w in meeting_words):
        return Category.MEETING

    # Отчёты
    report_words = ["отчёт", "отчет", "справка", "аналитика", "статистика", "report"]
    if any(w in text for w in report_words):
        return Category.REPORT

    # Рассылки
    newsletter_markers = ["unsubscribe", "отписаться", "рассылка", "дайджест", "newsletter"]
    if any(w in text for w in newsletter_markers):
        return Category.NEWSLETTER

    return Category.INFO


def _is_vip_sender(sender: str, sender_name: str, rules: dict) -> tuple[bool, dict | None]:
    sender_lower = sender.lower()
    name_lower = sender_name.lower()
    for vip_key, vip_data in rules.get("vip_senders", {}).items():
        patterns = [p.lower() for p in vip_data.get("patterns", [])]
        email_patterns = [p.lower() for p in vip_data.get("email_patterns", [])]
        if any(p in name_lower or p in sender_lower for p in patterns):
            return True, vip_data
        if any(p in sender_lower for p in email_patterns):
            return True, vip_data
    return False, None


def _has_control_keywords(text: str, config: dict) -> bool:
    control_words = ["контроль", "на контроле", "срок", "дедлайн",
                     "не позднее", "в срок до", "до конца"]
    return any(w in text.lower() for w in control_words)


def classify_email(email_data: dict, feedback_history: list | None = None) -> dict:
    config = load_config()
    rules = _load_rules()
    cls_cfg = config["classification"]

    sender = email_data.get("sender", "")
    sender_name = email_data.get("sender_name", "")
    subject = email_data.get("subject", "")
    body_preview = email_data.get("body_preview", "")
    text = f"{subject} {body_preview}".lower()

    # 1. Базовый скор
    score = cls_cfg["priority_base"]

    # 2. VIP-проверка
    is_vip, vip_data = _is_vip_sender(sender, sender_name, rules)

    # 3. Категория
    category = _detect_category(email_data, config)

    # 4. VIP-буст (Модестов и другие)
    if is_vip and vip_data:
        if category == Category.SED and vip_data.get("sed_override"):
            if _has_control_keywords(text, config):
                score = 10  # Контроль/сроки от VIP = критично
            else:
                score = max(score, 7)  # СЭД от VIP без контроля = high
        else:
            score += cls_cfg["vip_boost"]

    # 5. Категорийные бусты
    if category == Category.SED:
        score += cls_cfg["sed_boost"]
        if _has_control_keywords(text, config):
            score += cls_cfg["control_deadline_boost"]
    elif category == Category.INCIDENT:
        score += cls_cfg["incident_boost"]
    elif category == Category.NEWSLETTER:
        score += cls_cfg["newsletter_penalty"]

    # 6. Ключевые слова-бусты
    for keyword, boost in rules.get("keyword_boosts", {}).items():
        if keyword.lower() in text:
            score += boost

    # 7. Свежесть (если есть дата)
    received = email_data.get("received_at", "")
    if received:
        from datetime import datetime, timedelta, timezone
        try:
            dt = datetime.fromisoformat(received)
            if dt > datetime.now(timezone.utc) - timedelta(hours=24):
                score += cls_cfg["recent_24h_boost"]
        except (ValueError, TypeError):
            pass

    # 8. Непрочитанное
    if email_data.get("is_unread"):
        score += cls_cfg["unread_boost"]

    # 9. Учёт обратной связи (обучение)
    if feedback_history:
        sender_feedbacks = [
            f for f in feedback_history
            if f.get("sender_email", "").lower() == sender.lower()
            and f.get("confidence", 0) >= cls_cfg["confidence_threshold"]
        ]
        if sender_feedbacks:
            # Берём самый уверенный/свежий
            best = max(sender_feedbacks, key=lambda f: f.get("confidence", 0))
            if best.get("learned_priority"):
                priority_map = {"critical": 10, "high": 8, "medium": 5, "low": 2, "spam": 0}
                learned_score = priority_map.get(best["learned_priority"], score)
                # Взвешенное среднее: чем выше confidence, тем больше вес обучения
                conf = best["confidence"]
                score = int(score * (1 - conf) + learned_score * conf)
            if best.get("learned_category"):
                try:
                    category = Category(best["learned_category"])
                except ValueError:
                    pass

    # Ограничиваем 0-10
    score = max(0, min(10, score))
    priority = _score_to_priority(score)

    # 10. Предлагаемое действие
    proposed_action = _propose_action(priority, category, is_vip, feedback_history, sender)

    return {
        "priority": priority.value,
        "priority_score": score,
        "category": category.value,
        "proposed_action": proposed_action.value,
        "is_vip": is_vip,
        "classification_reasons": _build_reasons(is_vip, vip_data, category, score),
    }


def _propose_action(priority: Priority, category: Category,
                     is_vip: bool, feedback_history: list | None,
                     sender: str) -> OwnerAction:
    # Сначала проверяем обученные действия
    if feedback_history:
        sender_actions = [
            f for f in feedback_history
            if f.get("sender_email", "").lower() == sender.lower()
            and f.get("learned_action")
            and f.get("confidence", 0) >= 0.7
        ]
        if sender_actions:
            best = max(sender_actions, key=lambda f: f.get("confidence", 0))
            try:
                return OwnerAction(best["learned_action"])
            except ValueError:
                pass

    # Правила по умолчанию
    if priority == Priority.SPAM:
        return OwnerAction.IGNORE
    if category == Category.NEWSLETTER:
        return OwnerAction.ARCHIVE
    if category == Category.INCIDENT:
        return OwnerAction.ESCALATE if priority >= Priority.HIGH else OwnerAction.MONITOR
    if category == Category.TASK or category == Category.SED:
        if priority >= Priority.HIGH:
            return OwnerAction.CREATE_TASK
        return OwnerAction.MONITOR
    if is_vip:
        return OwnerAction.CREATE_TASK
    if category == Category.MEETING:
        return OwnerAction.REPLY
    return OwnerAction.ARCHIVE


def _build_reasons(is_vip: bool, vip_data: dict | None,
                   category: Category, score: int) -> list[str]:
    reasons = []
    if is_vip:
        note = vip_data.get("note", "VIP") if vip_data else "VIP"
        reasons.append(f"VIP-отправитель: {note}")
    reasons.append(f"Категория: {category.value}")
    reasons.append(f"Скор: {score}/10")
    return reasons


def classify_batch(emails: list[dict], feedback_history: list | None = None) -> list[dict]:
    results = []
    for em in emails:
        cls = classify_email(em, feedback_history)
        em.update(cls)
        results.append(em)
    # Сортируем по приоритету (высший первым)
    results.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="Email classifier")
    sub = parser.add_subparsers(dest="command")

    p_cls = sub.add_parser("classify")
    p_cls.add_argument("--email", required=True, help="JSON file with email data")
    p_cls.add_argument("--feedback", default="", help="JSON file with feedback history")

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("--emails", required=True, help="JSON file with emails array")
    p_batch.add_argument("--feedback", default="", help="JSON file with feedback history")

    args = parser.parse_args()

    feedback = []
    if hasattr(args, "feedback") and args.feedback:
        feedback = json.loads(Path(args.feedback).read_text("utf-8"))

    if args.command == "classify":
        data = json.loads(Path(args.email).read_text("utf-8"))
        output_json(classify_email(data, feedback))
    elif args.command == "batch":
        data = json.loads(Path(args.emails).read_text("utf-8"))
        output_json(classify_batch(data, feedback))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
