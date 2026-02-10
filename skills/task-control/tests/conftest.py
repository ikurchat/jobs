"""Shared fixtures for task-control tests."""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def config():
    """Load test config."""
    from config.settings import load_config
    return load_config()


@pytest.fixture
def sample_employees():
    """4 test employees: 2 shift, 2 office."""
    return [
        {
            "id": 1,
            "fio": "Иванов Иван Иванович",
            "position": "Дежурный специалист",
            "schedule_type": "shift_12h",
            "zone": "SOC мониторинг",
            "strengths": "Реагирование на инциденты",
            "telegram": "@ivanov",
            "active": True,
        },
        {
            "id": 2,
            "fio": "Петров Пётр Петрович",
            "position": "Дежурный специалист",
            "schedule_type": "shift_12h",
            "zone": "SOC мониторинг",
            "strengths": "Анализ логов",
            "telegram": "@petrov",
            "active": True,
        },
        {
            "id": 3,
            "fio": "Кулиш Андрей Сергеевич",
            "position": "Ведущий специалист",
            "schedule_type": "office_5x2",
            "zone": "Документооборот, справки ИБ",
            "strengths": "Подготовка справок, работа с регуляторами",
            "telegram": "@kulish",
            "active": True,
        },
        {
            "id": 4,
            "fio": "Меликян Арам Ашотович",
            "position": "Специалист",
            "schedule_type": "office_5x2",
            "zone": "Отчётность, аналитика",
            "strengths": "Работа с данными, отчёты",
            "telegram": "@melikyan",
            "active": True,
        },
    ]


@pytest.fixture
def sample_tasks():
    """Tasks in various states."""
    return [
        {
            "id": 101,
            "title": "Справка по PT",
            "task_type": "delegate",
            "control_loop": "down",
            "assignee": [{"id": 3, "value": "Кулиш Андрей Сергеевич"}],
            "status": "done",
            "priority": "high",
            "source_date": "2025-02-05",
            "assigned_date": "2025-02-05T10:00:00",
            "completed_date": "2025-02-08T14:30:00",
            "deadline": "2025-02-07",
            "owner_action": "check",
            "plan_item": [{"id": 13}],
            "is_unplanned": False,
        },
        {
            "id": 102,
            "title": "Отчёты: добавить страны атак",
            "task_type": "delegate",
            "control_loop": "down",
            "assignee": [{"id": 4, "value": "Меликян Арам Ашотович"}],
            "status": "in_progress",
            "priority": "normal",
            "source_date": "2025-02-09",
            "assigned_date": "2025-02-09T11:00:00",
            "deadline": "2025-02-14",
            "owner_action": "check",
            "is_unplanned": True,
        },
        {
            "id": 103,
            "title": "Справка по ГосСОПКА",
            "task_type": "delegate",
            "control_loop": "down",
            "assignee": None,
            "status": "draft",
            "priority": "normal",
            "source_date": "2025-02-09",
            "owner_action": "delegate",
            "is_unplanned": True,
        },
        {
            "id": 104,
            "title": "Справка по Булычеву",
            "task_type": "collab",
            "control_loop": "down",
            "status": "waiting_input",
            "priority": "normal",
            "source_date": "2025-02-09",
            "owner_action": "none",
            "is_unplanned": True,
        },
        {
            "id": 105,
            "title": "Статус по инциденту — доклад руководству",
            "task_type": "boss_control",
            "control_loop": "up",
            "status": "in_progress",
            "priority": "high",
            "boss_deadline": "2025-02-12",
            "owner_action": "report",
        },
        {
            "id": 106,
            "title": "Перекрёстная аналитика отчётов",
            "task_type": "backlog",
            "control_loop": "internal",
            "status": "draft",
            "priority": "low",
            "source_date": "2025-02-09",
            "owner_action": "none",
        },
        {
            "id": 107,
            "title": "Изучить договор с Киберзащитой на SOAR",
            "task_type": "personal",
            "control_loop": "internal",
            "status": "assigned",
            "priority": "normal",
            "source_date": "2025-02-09",
            "owner_action": "none",
        },
    ]


@pytest.fixture
def sample_shifts():
    """Month of shift data for Feb 2025."""
    shifts = []
    # Иванов and Петров alternate shifts
    cycle = ["day", "night", "rest", "off"]
    for day in range(1, 29):
        d = date(2025, 2, day)
        # Иванов starts with day on Feb 1
        ivanov_type = cycle[(day - 1) % 4]
        petrov_type = cycle[(day - 1 + 2) % 4]  # offset by 2 (Петров on rest when Иванов is day)

        for emp_id, stype in [(1, ivanov_type), (2, petrov_type)]:
            start, end = ("08:00", "20:00") if stype == "day" else ("20:00", "08:00") if stype == "night" else ("", "")
            shifts.append({
                "id": len(shifts) + 1,
                "employee": [{"id": emp_id, "value": f"Employee {emp_id}"}],
                "date": d.isoformat(),
                "shift_type": stype,
                "shift_start": start,
                "shift_end": end,
                "month": "2025-02",
            })

    return shifts


@pytest.fixture
def sample_plan_items():
    """Plan items for a week."""
    return [
        {
            "id": 10,
            "period_type": "weekly",
            "period_start": "2025-02-03",
            "period_end": "2025-02-09",
            "item_number": 1,
            "description": "Мониторинг инцидентов ИБ",
            "deadline": "02.02–09.02",
            "responsible": [{"id": 1, "value": "Иванов"}, {"id": 2, "value": "Петров"}],
            "status": "in_progress",
        },
        {
            "id": 11,
            "period_type": "weekly",
            "period_start": "2025-02-03",
            "period_end": "2025-02-09",
            "item_number": 2,
            "description": "Ретроспективный анализ событий",
            "deadline": "02.02–09.02",
            "responsible": [{"id": 1, "value": "Иванов"}],
            "status": "done",
            "completion_note": "Выполнено. Отработано 1200 хостов.",
        },
        {
            "id": 13,
            "period_type": "monthly",
            "period_start": "2025-02-01",
            "period_end": "2025-02-28",
            "item_number": 13,
            "description": "Контроль корректного функционирования СЗИ KATAP, подключение агентов EDR",
            "deadline": "Февраль 2025",
            "responsible": [{"id": 3, "value": "Кулиш"}],
            "status": "in_progress",
        },
    ]


@pytest.fixture
def mock_baserow():
    """Mock for Baserow API calls."""
    with patch("services.baserow._make_request") as mock:
        yield mock


@pytest.fixture
def tmp_work_dir(tmp_path):
    """Temporary work directory."""
    return tmp_path
