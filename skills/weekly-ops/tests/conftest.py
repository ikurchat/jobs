"""Shared test fixtures for weekly-ops."""

import json
import pytest
from datetime import date


@pytest.fixture
def sample_tasks():
    return [
        {
            "id": 1,
            "title": "Мониторинг событий информационной безопасности",
            "status": "in_progress",
            "responsible": "Управление ИБ",
            "deadline": "2026-02-21",
            "result": "Обработано 312 событий, 2 инцидента",
            "is_unplanned": False,
        },
        {
            "id": 2,
            "title": "Справка по взаимодействию с ГосСОПКА",
            "status": "done",
            "responsible": "Сидоров А.В.",
            "deadline": "2026-02-19",
            "result": "Справка утверждена (рег. №42-ИБ)",
            "completed_at": "2026-02-19",
            "is_unplanned": False,
        },
        {
            "id": 3,
            "title": "Внеплановая проверка инцидента",
            "status": "done",
            "responsible": "Петров Д.А.",
            "deadline": "2026-02-18",
            "result": "Инцидент закрыт",
            "is_unplanned": True,
        },
    ]


@pytest.fixture
def sample_plan_items():
    return [
        {
            "id": 10,
            "item_number": 1,
            "description": "Мониторинг событий информационной безопасности",
            "deadline": "В течение недели",
            "responsible": "Управление ИБ",
            "status": "planned",
            "period_start": "2026-02-17",
            "is_unplanned": False,
        },
        {
            "id": 11,
            "item_number": 2,
            "description": "Согласование Порядка мониторинга информационной безопасности (Молотова А.В.)",
            "deadline": "В течение недели",
            "responsible": "Управление ИБ",
            "status": "planned",
            "period_start": "2026-02-17",
            "is_unplanned": False,
        },
    ]


@pytest.fixture
def sample_raw_data(sample_tasks, sample_plan_items):
    return {
        "tasks": sample_tasks,
        "plan_items": sample_plan_items,
        "regulatory_tracks": [],
        "period_start": "2026-02-17",
        "period_end": "2026-02-21",
    }


@pytest.fixture
def config():
    return {
        "baserow": {"tables": {"tasks": 1, "plan_items": 2, "regulatory_tracks": 3, "formulation_memory": 4}},
        "rules": {
            "mandatory_items": [
                {
                    "description": "Согласование Порядка мониторинга информационной безопасности (Молотова А.В.)",
                    "deadline": "В течение недели",
                    "responsible": "Управление ИБ",
                }
            ],
            "exclude_topics": ["цок", "доработка бота"],
        },
        "report": {
            "columns": ["№ п/п", "Мероприятия", "Сроки проведения", "Ответственный", "Отметка о выполнении"],
            "font_name": "Times New Roman",
            "font_size_pt": 12,
            "title_font_size_pt": 14,
            "page": {"width_cm": 29.7, "height_cm": 21.0, "margin_left_cm": 3.0, "margin_right_cm": 1.0, "margin_top_cm": 2.0, "margin_bottom_cm": 2.0},
            "col_widths_pct": [6, 38, 16, 20, 20],
        },
        "preview": {"block_size": 5},
        "formulation_memory": {"match_threshold": 0.6, "min_word_length": 3},
        "work_dir": "/dev/shm/weekly-ops",
    }
