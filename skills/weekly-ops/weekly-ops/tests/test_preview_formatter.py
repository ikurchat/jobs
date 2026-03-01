"""Tests for preview_formatter service."""

import pytest
from services.preview_formatter import (
    format_plan_blocks,
    format_report_blocks,
    parse_owner_response,
    apply_edits,
)


@pytest.fixture
def plan_items():
    return [
        {"item_number": i, "description": f"Задача {i}", "deadline": f"до {i}.02", "responsible": "Тест"}
        for i in range(1, 8)
    ]


def test_format_plan_blocks_splits(plan_items):
    """Items should be split into blocks of 5."""
    blocks = format_plan_blocks(plan_items, "План на 17.02-21.02", block_size=5)
    assert len(blocks) == 2
    assert "Блок 1/2" in blocks[0]
    assert "Блок 2/2" in blocks[1]


def test_format_plan_blocks_uses_circled_digits(plan_items):
    """Circled digits should be used for numbering."""
    blocks = format_plan_blocks(plan_items[:3], block_size=5)
    assert "①" in blocks[0]
    assert "②" in blocks[0]
    assert "③" in blocks[0]


def test_format_report_blocks_includes_marks():
    """Report blocks should include completion notes."""
    items = [
        {"item_number": 1, "description": "Мониторинг", "completion_note": "Выполнено. 300 событий."},
        {"item_number": 2, "description": "Контроль", "completion_note": "В работе (60%)."},
    ]
    blocks = format_report_blocks(items, block_size=5)
    assert "→ Выполнено" in blocks[0]
    assert "→ В работе" in blocks[0]


def test_parse_approve():
    """'ок' should return approve action."""
    result = parse_owner_response("ок", [])
    assert result["action"] == "approve"


def test_parse_approve_all():
    """'всё ок' should return approve_all action."""
    result = parse_owner_response("всё ок", [])
    assert result["action"] == "approve_all"


def test_parse_edit():
    """'② сроки до пятницы' should return edit."""
    result = parse_owner_response("② сроки до пятницы", [])
    assert result["action"] == "edit"
    assert 2 in result["edits"]


def test_parse_remove():
    """'⑤ убрать' should return removal."""
    result = parse_owner_response("⑤ убрать", [])
    assert 5 in result["removals"]


def test_apply_edits_removes_item():
    """apply_edits should remove items by number."""
    items = [{"item_number": 1, "description": "A"}, {"item_number": 2, "description": "B"}]
    parsed = {"action": "edit", "edits": {}, "additions": [], "removals": [1]}
    result = apply_edits(items, parsed)
    assert len(result) == 1
    assert result[0]["description"] == "B"
    assert result[0]["item_number"] == 1  # renumbered


def test_apply_edits_adds_item():
    """apply_edits should add new items."""
    items = [{"item_number": 1, "description": "A"}]
    parsed = {"action": "edit", "edits": {}, "additions": [{"description": "New task", "deadline": "20.02"}], "removals": []}
    result = apply_edits(items, parsed)
    assert len(result) == 2
    assert result[1]["description"] == "New task"
