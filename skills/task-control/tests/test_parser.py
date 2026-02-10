"""Tests for task parser."""

import os
import sys

import pytest

os.environ.setdefault("BASEROW_URL", "https://baserow.example.com")
os.environ.setdefault("BASEROW_TOKEN", "test-token-123")

from services.parser import (
    classify_owner_action,
    deduplicate,
    enrich_tasks,
    validate_tasks,
)


class TestValidation:
    def test_valid_tasks(self):
        tasks = [
            {"title": "Справка по PT", "task_type": "delegate", "assignee_hint": "Кулиш"},
            {"title": "Изучить договор", "task_type": "personal"},
        ]
        result = validate_tasks(tasks)
        assert len(result["valid"]) == 2
        assert len(result["errors"]) == 0

    def test_missing_title(self):
        tasks = [{"task_type": "delegate", "assignee_hint": "Кулиш"}]
        result = validate_tasks(tasks)
        assert len(result["valid"]) == 0
        assert len(result["errors"]) == 1
        assert result["errors"][0]["field"] == "title"

    def test_invalid_task_type(self):
        tasks = [{"title": "Test", "task_type": "invalid_type"}]
        result = validate_tasks(tasks)
        assert len(result["errors"]) == 1
        assert "task_type" in result["errors"][0]["field"]

    def test_delegate_without_assignee(self):
        tasks = [{"title": "Test", "task_type": "delegate"}]
        result = validate_tasks(tasks)
        assert len(result["errors"]) == 1
        assert "assignee" in result["errors"][0]["field"]

    def test_empty_input(self):
        result = validate_tasks([])
        assert len(result["valid"]) == 0
        assert len(result["errors"]) == 0

    def test_10_task_meeting_example(self):
        """Validate the 10-task meeting example from ТЗ."""
        tasks = [
            {"title": "Справка по PT", "task_type": "delegate", "assignee_hint": "Кулиш"},
            {"title": "Отчёты: добавить страны атак", "task_type": "delegate", "assignee_hint": "Меликян"},
            {"title": "Справка по ГосСОПКА", "task_type": "delegate", "assignee_hint": "?"},
            {"title": "Справка по Булычеву", "task_type": "collab"},
            {"title": "Справка по Павлову", "task_type": "collab"},
            {"title": "Аббревиатуры — сначала полностью", "task_type": "skill_update"},
            {"title": "Фактура в приложении", "task_type": "skill_update"},
            {"title": "ИНН обязательно для юрлиц", "task_type": "skill_update"},
            {"title": "Изучить договор с Киберзащитой", "task_type": "personal"},
            {"title": "Перекрёстная аналитика отчётов СОК", "task_type": "backlog"},
        ]
        result = validate_tasks(tasks)
        # Task #3 has "?" as assignee_hint, which should pass validation
        assert len(result["valid"]) == 10
        assert len(result["errors"]) == 0


class TestEnrichment:
    def test_fio_matching(self, sample_employees):
        tasks = [
            {"title": "Task 1", "task_type": "delegate", "assignee_hint": "Кулиш"},
        ]
        result = enrich_tasks(tasks, sample_employees)
        assert result[0]["assignee"] == 3
        assert "Кулиш" in result[0]["assignee_fio"]

    def test_partial_name_match(self, sample_employees):
        tasks = [
            {"title": "Task 1", "task_type": "delegate", "assignee_hint": "Меликян"},
        ]
        result = enrich_tasks(tasks, sample_employees)
        assert result[0]["assignee"] == 4

    def test_unresolved_name(self, sample_employees):
        tasks = [
            {"title": "Task 1", "task_type": "delegate", "assignee_hint": "Незнакомов"},
        ]
        result = enrich_tasks(tasks, sample_employees)
        assert "assignee_hint_unresolved" in result[0]

    def test_control_loop_set(self, sample_employees):
        tasks = [
            {"title": "Boss task", "task_type": "boss_control"},
        ]
        result = enrich_tasks(tasks, sample_employees)
        assert result[0]["control_loop"] == "up"

    def test_owner_action_set(self, sample_employees):
        tasks = [
            {"title": "Delegate", "task_type": "delegate", "assignee_hint": "Кулиш"},
        ]
        result = enrich_tasks(tasks, sample_employees)
        assert result[0]["owner_action"] == "delegate"

    def test_default_status_and_priority(self, sample_employees):
        tasks = [{"title": "Test", "task_type": "personal"}]
        result = enrich_tasks(tasks, sample_employees)
        assert result[0]["status"] == "draft"
        assert result[0]["priority"] == "normal"


class TestDeduplication:
    def test_similar_tasks(self):
        new = [{"title": "Справка по PT для руководства"}]
        existing = [
            {"id": 1, "title": "Справка по PT"},
            {"id": 2, "title": "Отчёт за квартал"},
        ]
        result = deduplicate(new, existing, threshold=0.6)
        assert "possible_duplicate" in result[0]
        assert result[0]["possible_duplicate"]["existing_id"] == 1

    def test_no_duplicates(self):
        new = [{"title": "Полностью уникальная задача"}]
        existing = [{"id": 1, "title": "Справка по PT"}]
        result = deduplicate(new, existing, threshold=0.7)
        assert "possible_duplicate" not in result[0]


class TestClassification:
    def test_done_task_needs_close(self):
        task = {"task_type": "delegate", "status": "done"}
        assert classify_owner_action(task) == "close"

    def test_boss_control_needs_report(self):
        task = {"task_type": "boss_control", "status": "in_progress"}
        assert classify_owner_action(task) == "report"

    def test_draft_delegate_needs_delegation(self):
        task = {"task_type": "delegate", "status": "draft"}
        assert classify_owner_action(task) == "delegate"

    def test_in_progress_delegate_needs_check(self):
        task = {"task_type": "delegate", "status": "in_progress"}
        assert classify_owner_action(task) == "check"
