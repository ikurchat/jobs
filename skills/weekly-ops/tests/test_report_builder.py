"""Tests for report_builder service."""

import pytest
from services.report_builder import build_report


def test_build_report_fills_marks(sample_raw_data, config):
    """Planned items should get completion marks from matched tasks."""
    result = build_report(sample_raw_data, config=config)
    planned = result["planned"]
    assert len(planned) > 0
    # At least one item should have a mark
    marks = [p.get("completion_note", "") for p in planned]
    assert any(m for m in marks), f"No marks filled: {marks}"


def test_build_report_unplanned_section(sample_raw_data, config):
    """Unplanned done tasks should appear in unplanned section."""
    result = build_report(sample_raw_data, config=config)
    unplanned = result["unplanned"]
    assert len(unplanned) > 0
    descs = [u.get("description", "") for u in unplanned]
    assert any("внеплановая" in d.lower() for d in descs)


def test_build_report_ll3_dedup(sample_raw_data, config):
    """LL-3: Unplanned items duplicating planned should be excluded."""
    # Add unplanned task that duplicates a planned one
    sample_raw_data["tasks"].append({
        "id": 50,
        "title": "Мониторинг событий информационной безопасности (доп)",
        "status": "done",
        "result": "Дополнительный мониторинг",
        "is_unplanned": True,
    })
    result = build_report(sample_raw_data, config=config)
    # Should have a warning about duplication
    assert len(result["warnings"]) > 0 or len(result["unplanned"]) <= 1


def test_build_report_uses_formulation_memory(sample_raw_data, config):
    """Formulation memory should be used for known patterns."""
    fm = {
        "мониторинг событий информационной безопасности": "Выполнено. Обработано {N} событий."
    }
    result = build_report(sample_raw_data, formulation_mem=fm, config=config)
    planned = result["planned"]
    # Find monitoring item
    for p in planned:
        if "мониторинг" in p.get("description", "").lower():
            assert p.get("mark_source") == "memory"
            break
