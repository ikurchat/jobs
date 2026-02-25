"""Tests for business rules."""

import pytest
from config.rules import (
    validate_plan_item,
    validate_report_item,
    is_excluded,
    check_mandatory_items,
)


def test_ll8_no_percentages():
    """LL-8: Plan items must not contain percentages."""
    item = {"description": "Задача выполнена на 80%"}
    issues = validate_plan_item(item)
    assert any("LL-8" in i for i in issues)


def test_ll8_no_issue_without_percent():
    """LL-8: Normal text should pass."""
    item = {"description": "Мониторинг событий ИБ"}
    issues = validate_plan_item(item)
    assert not any("LL-8" in i for i in issues)


def test_excluded_topics():
    """Excluded topics should be detected."""
    assert is_excluded("Задача по доработке бота")
    assert is_excluded("Настройка скиллов для ЦОК")
    assert not is_excluded("Мониторинг событий ИБ")


def test_mandatory_items_detected():
    """Missing mandatory items should be returned."""
    items = [{"description": "Какая-то задача"}]
    missing = check_mandatory_items(items)
    assert len(missing) > 0
    assert any("Молотова" in m["description"] for m in missing)


def test_mandatory_items_present():
    """When mandatory items are present, nothing should be missing."""
    items = [
        {"description": "Согласование Порядка мониторинга информационной безопасности (Молотова А.В.)"},
        {"description": "Мониторинг событий информационной безопасности"},
        {"description": "Контроль за деятельностью стажёра (Ворожбит)"},
    ]
    missing = check_mandatory_items(items)
    assert len(missing) == 0


def test_ll3_duplicate_detection():
    """LL-3: Duplicates between planned and additional should be detected."""
    plan_desc = "Мониторинг событий информационной безопасности"
    add_descs = ["Мониторинг событий информационной безопасности (дополнительный)"]
    issues = validate_report_item(plan_desc, add_descs)
    assert len(issues) > 0
    assert any("LL-3" in i for i in issues)
