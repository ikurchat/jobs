"""Тесты парсера."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.parser import parse_email, generate_summary


def test_extract_deadlines():
    email = {
        "subject": "Поручение",
        "body_text": "Прошу подготовить до 25.02.2026. Не позднее 01.03.2026 доложить.",
        "body_preview": "Прошу подготовить до 25.02.2026.",
        "sender": "boss@company.ru",
        "sender_name": "Босс",
    }
    result = parse_email(email)
    assert len(result["extracted_deadlines"]) >= 1
    assert "25.02.2026" in str(result["extracted_deadlines"])


def test_extract_people():
    email = {
        "subject": "По задаче",
        "body_text": "Ответственный — Кулиш А.В. Согласовать с Меликяном Д.А.",
        "body_preview": "Ответственный — Кулиш А.В.",
        "sender": "test@test.ru",
        "sender_name": "Test",
    }
    result = parse_email(email)
    assert len(result["mentioned_people"]) >= 1


def test_extract_doc_refs():
    email = {
        "subject": "Согласование приказа № 156/ИБ",
        "body_text": "В соответствии с приказом № 156/ИБ от 10.02.2026",
        "body_preview": "В соответствии с приказом",
        "sender": "test@test.ru",
        "sender_name": "Test",
    }
    result = parse_email(email)
    assert len(result["document_refs"]) >= 1


def test_extract_tasks():
    email = {
        "subject": "Поручения",
        "body_text": "Прошу подготовить справку. Необходимо организовать совещание. Обеспечить контроль исполнения.",
        "body_preview": "Прошу подготовить справку.",
        "sender": "test@test.ru",
        "sender_name": "Test",
    }
    result = parse_email(email)
    assert len(result["potential_tasks"]) >= 2


def test_summary_format():
    email = {
        "subject": "Срочное поручение",
        "body_text": "Подготовить отчёт до завтра",
        "body_preview": "Подготовить отчёт до завтра",
        "sender": "boss@company.ru",
        "sender_name": "Модестов А.В.",
        "priority": "critical",
        "category": "task",
        "proposed_action": "create_task",
        "has_attachments": False,
    }
    result = generate_summary(email)
    assert "summary_text" in result
    assert "Модестов" in result["summary_text"]


if __name__ == "__main__":
    test_extract_deadlines()
    test_extract_people()
    test_extract_doc_refs()
    test_extract_tasks()
    test_summary_format()
    print("All parser tests passed!")
