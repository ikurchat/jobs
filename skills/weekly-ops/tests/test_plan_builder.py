"""Tests for plan_builder service."""

import pytest
from models.plan_item import PlanItem, PeriodType
from services.plan_builder import build_plan


def test_build_plan_includes_mandatory_items(sample_raw_data, config):
    """Mandatory items (Молотова) must always be present."""
    items = build_plan(sample_raw_data, PeriodType.WEEKLY, config)
    descs = [it.description.lower() for it in items]
    assert any("молотова" in d for d in descs), "Молотова should be in plan"


def test_build_plan_excludes_цок(sample_raw_data, config):
    """ЦОК items must be excluded."""
    sample_raw_data["tasks"].append({
        "id": 99,
        "title": "Задача ЦОК по мониторингу",
        "status": "in_progress",
        "responsible": "ЦОК",
    })
    items = build_plan(sample_raw_data, PeriodType.WEEKLY, config)
    descs = [it.description.lower() for it in items]
    assert not any("цок" in d for d in descs), "ЦОК should be excluded"


def test_build_plan_no_percentages(sample_raw_data, config):
    """LL-8: No percentages in plan items."""
    sample_raw_data["tasks"].append({
        "id": 100,
        "title": "Задача выполнена на 80%",
        "status": "in_progress",
        "responsible": "Тест",
    })
    items = build_plan(sample_raw_data, PeriodType.WEEKLY, config)
    for item in items:
        assert "%" not in item.description, f"Percentage found in: {item.description}"


def test_build_plan_renumbers_items(sample_raw_data, config):
    """Items must be sequentially numbered starting from 1."""
    items = build_plan(sample_raw_data, PeriodType.WEEKLY, config)
    numbers = [it.item_number for it in items]
    assert numbers == list(range(1, len(items) + 1))


def test_build_plan_dedup_existing(sample_raw_data, config):
    """Tasks already in plan_items should not be duplicated."""
    items = build_plan(sample_raw_data, PeriodType.WEEKLY, config)
    descs = [it.description for it in items]
    # "Мониторинг событий ИБ" is both in tasks and plan_items — should not duplicate
    exact_count = sum(1 for d in descs if "мониторинг событий" in d.lower())
    assert exact_count == 1, f"'Мониторинг событий' duplicated {exact_count} times"
