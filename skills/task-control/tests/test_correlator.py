"""Tests for plan-task correlator."""

import os
from datetime import date

import pytest

os.environ.setdefault("BASEROW_URL", "https://baserow.example.com")
os.environ.setdefault("BASEROW_TOKEN", "test-token-123")

from services.correlator import (
    apply_correlation,
    format_correlation_prompt,
    get_plan_items_for_period,
)


class TestGetPlanItems:
    def test_matching_period(self, sample_plan_items):
        result = get_plan_items_for_period(
            date(2025, 2, 3), date(2025, 2, 9), sample_plan_items
        )
        assert len(result) == 3  # All items overlap with this period

    def test_no_match(self, sample_plan_items):
        result = get_plan_items_for_period(
            date(2025, 3, 1), date(2025, 3, 7), sample_plan_items
        )
        assert len(result) == 0

    def test_partial_overlap(self, sample_plan_items):
        # Monthly item overlaps with date range in Feb
        result = get_plan_items_for_period(
            date(2025, 2, 15), date(2025, 2, 21), sample_plan_items
        )
        # Only monthly item (#13) should match
        assert len(result) == 1
        assert result[0]["id"] == 13


class TestFormatPrompt:
    def test_prompt_structure(self, sample_plan_items):
        task = {
            "title": "Проверить агенты EDR на серверах",
            "description": "Убедиться что агенты EDR подключены на всех серверах",
            "assignee_fio": "Кулиш Андрей Сергеевич",
            "task_type": "delegate",
        }

        result = format_correlation_prompt(task, sample_plan_items)

        assert "task" in result
        assert "candidates" in result
        assert "instruction" in result
        assert result["task"]["title"] == "Проверить агенты EDR на серверах"
        assert len(result["candidates"]) == 3

    def test_empty_plan_items(self):
        task = {"title": "Test", "task_type": "delegate"}
        result = format_correlation_prompt(task, [])
        assert len(result["candidates"]) == 0

    def test_responsible_extraction(self, sample_plan_items):
        task = {"title": "Test"}
        result = format_correlation_prompt(task, sample_plan_items)
        # Check that responsible is properly extracted
        for c in result["candidates"]:
            assert isinstance(c["responsible"], str)

    def test_multi_candidate_ranking_data(self, sample_plan_items):
        """Verify prompt includes enough data for Claude to rank candidates."""
        task = {
            "title": "Контроль агентов EDR",
            "description": "Проверка подключения EDR агентов",
            "assignee_fio": "Кулиш",
        }
        result = format_correlation_prompt(task, sample_plan_items)

        # Should include item #13 which is most similar
        ids = [c["id"] for c in result["candidates"]]
        assert 13 in ids

        # Each candidate should have all required fields
        for c in result["candidates"]:
            assert "description" in c
            assert "responsible" in c
            assert "id" in c


class TestApplyCorrelation:
    def test_link_task_to_plan(self):
        result = apply_correlation(42, 13, link=True)
        assert result["plan_item"] == [13]
        assert result["is_unplanned"] is False

    def test_mark_as_unplanned(self):
        result = apply_correlation(42, None, link=False)
        assert result["plan_item"] == []
        assert result["is_unplanned"] is True

    def test_reject_link(self):
        result = apply_correlation(42, 13, link=False)
        assert result["is_unplanned"] is True
