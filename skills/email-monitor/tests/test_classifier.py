"""Тесты классификатора."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.classifier import classify_email, classify_batch


def test_modestov_critical():
    """Письмо от Модестова = critical."""
    email = {
        "sender": "modestov@company.ru",
        "sender_name": "Модестов А.В.",
        "subject": "Поручение по результатам совещания",
        "body_preview": "Прошу подготовить справку по инциденту до 20.02.2026",
    }
    result = classify_email(email)
    assert result["priority"] == "critical"
    assert result["is_vip"] is True
    assert result["priority_score"] >= 9


def test_modestov_sed_without_control():
    """СЭД от Модестова без контрольных слов = high, не medium."""
    email = {
        "sender": "sed@company.ru",
        "sender_name": "Модестов (СЭД)",
        "subject": "Информационное письмо",
        "body_preview": "Направляю для сведения документ",
    }
    result = classify_email(email)
    assert result["priority_score"] >= 7
    assert result["priority"] in ("critical", "high")


def test_modestov_sed_with_control():
    """СЭД от Модестова с контролем/сроками = critical."""
    email = {
        "sender": "sed@company.ru",
        "sender_name": "Модестов (СЭД)",
        "subject": "На контроле: исполнение поручения",
        "body_preview": "Срок исполнения до 25.02.2026. Прошу доложить.",
    }
    result = classify_email(email)
    assert result["priority"] == "critical"
    assert result["priority_score"] == 10


def test_newsletter_low():
    """Рассылка = низкий приоритет."""
    email = {
        "sender": "digest@vendor.com",
        "sender_name": "Weekly Digest",
        "subject": "Your weekly security newsletter",
        "body_preview": "Click here to unsubscribe from this newsletter",
    }
    result = classify_email(email)
    assert result["priority_score"] <= 3
    assert result["category"] == "newsletter"
    assert result["proposed_action"] == "archive"


def test_incident_high():
    """Инцидент ИБ = высокий приоритет."""
    email = {
        "sender": "soc@company.ru",
        "sender_name": "SOC Alert",
        "subject": "Critical: обнаружена атака на периметр",
        "body_preview": "Зафиксирована попытка эксплуатации уязвимости CVE-2026-1234",
    }
    result = classify_email(email)
    assert result["priority_score"] >= 7
    assert result["category"] == "incident"


def test_feedback_learning():
    """Классификатор учитывает feedback."""
    email = {
        "sender": "petrov@company.ru",
        "sender_name": "Петров И.И.",
        "subject": "Отчёт за неделю",
        "body_preview": "Направляю отчёт по SOC за прошлую неделю",
    }
    feedback = [
        {
            "sender_email": "petrov@company.ru",
            "learned_priority": "high",
            "learned_action": "create_task",
            "learned_category": "report",
            "confidence": 0.85,
        }
    ]
    result = classify_email(email, feedback)
    # С feedback confidence 0.85, скор должен сместиться к high (8)
    assert result["priority_score"] >= 6
    assert result["proposed_action"] == "create_task"


def test_batch_sort():
    """Батч-классификация сортирует по приоритету."""
    emails = [
        {"sender": "info@newsletter.com", "sender_name": "", "subject": "News",
         "body_preview": "unsubscribe from newsletter"},
        {"sender": "modestov@company.ru", "sender_name": "Модестов",
         "subject": "Срочно", "body_preview": "Немедленно доложить"},
        {"sender": "user@company.ru", "sender_name": "Обычный",
         "subject": "Вопрос", "body_preview": "Подскажите пожалуйста"},
    ]
    result = classify_batch(emails)
    # Модестов должен быть первым
    assert result[0]["sender_name"] == "Модестов"
    assert result[0]["priority_score"] >= 9


if __name__ == "__main__":
    test_modestov_critical()
    test_modestov_sed_without_control()
    test_modestov_sed_with_control()
    test_newsletter_low()
    test_incident_high()
    test_feedback_learning()
    test_batch_sort()
    print("All tests passed!")
