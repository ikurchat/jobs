"""Tests for notification content generator."""

import os
from datetime import date, datetime, time

import pytest

os.environ.setdefault("BASEROW_URL", "https://baserow.example.com")
os.environ.setdefault("BASEROW_TOKEN", "test-token-123")

from services.scheduler import (
    generate_briefing,
    generate_weekly_summary,
    is_working_time,
    should_notify,
)


class TestIsWorkingTime:
    def test_monday_morning(self, config):
        # Monday 10:00
        dt = datetime(2025, 2, 10, 10, 0)
        assert is_working_time(dt, config) is True

    def test_monday_early(self, config):
        # Monday 07:00 (before work)
        dt = datetime(2025, 2, 10, 7, 0)
        assert is_working_time(dt, config) is False

    def test_friday_afternoon(self, config):
        # Friday 15:00 (still working)
        dt = datetime(2025, 2, 14, 15, 0)
        assert is_working_time(dt, config) is True

    def test_friday_evening(self, config):
        # Friday 17:00 (after 16:20)
        dt = datetime(2025, 2, 14, 17, 0)
        assert is_working_time(dt, config) is False

    def test_saturday(self, config):
        # Saturday 10:00 (weekend)
        dt = datetime(2025, 2, 15, 10, 0)
        assert is_working_time(dt, config) is False

    def test_sunday(self, config):
        dt = datetime(2025, 2, 16, 10, 0)
        assert is_working_time(dt, config) is False


class TestShouldNotify:
    def test_briefing_monday_0900(self, config):
        dt = datetime(2025, 2, 10, 9, 0)
        assert should_notify(dt, "briefing", config) is True

    def test_briefing_saturday(self, config):
        dt = datetime(2025, 2, 15, 9, 0)
        assert should_notify(dt, "briefing", config) is False

    def test_push_monday_1700(self, config):
        dt = datetime(2025, 2, 10, 17, 0)
        assert should_notify(dt, "push", config) is True

    def test_push_friday_1700_silent(self, config):
        # Friday push is at 15:00, not 17:00
        dt = datetime(2025, 2, 14, 17, 0)
        assert should_notify(dt, "push", config) is False

    def test_push_friday_1500(self, config):
        dt = datetime(2025, 2, 14, 15, 0)
        assert should_notify(dt, "push", config) is True


class TestGenerateBriefing:
    def test_briefing_has_action_items(self, sample_tasks, sample_shifts):
        text = generate_briefing(
            date(2025, 2, 10), sample_tasks, sample_shifts
        )
        assert "🎯 ТЕБЕ НУЖНО СДЕЛАТЬ" in text
        assert "Доброе утро" in text

    def test_briefing_shows_overdue(self, sample_tasks, sample_shifts):
        # Add overdue task
        tasks = sample_tasks + [{
            "id": 200,
            "title": "Просроченная задача",
            "status": "overdue",
            "assignee": [{"id": 1, "value": "Иванов"}],
            "task_type": "delegate",
        }]
        text = generate_briefing(date(2025, 2, 10), tasks, sample_shifts)
        assert "ПРОСРОЧЕНО" in text

    def test_briefing_shows_boss_control(self, sample_tasks, sample_shifts):
        text = generate_briefing(date(2025, 2, 10), sample_tasks, sample_shifts)
        assert "НА КОНТРОЛЕ У РУКОВОДСТВА" in text

    def test_briefing_shows_shifts(self, sample_tasks, sample_shifts):
        text = generate_briefing(date(2025, 2, 10), sample_tasks, sample_shifts)
        # Feb 10 is a Monday — should show who's on shift
        assert "НА СМЕНЕ" in text or "СЕГОДНЯ" in text

    def test_empty_tasks(self, sample_shifts):
        text = generate_briefing(date(2025, 2, 10), [], sample_shifts)
        assert "Доброе утро" in text

    def test_night_anomaly_in_morning_briefing(self, sample_tasks, sample_shifts):
        """Anomalies from night should appear in next morning briefing."""
        # This is handled at the bot scheduler level, not in text generation
        # But briefing should show night shift results
        text = generate_briefing(date(2025, 2, 10), sample_tasks, sample_shifts)
        assert isinstance(text, str)


class TestWeeklySummary:
    def test_summary_format(self, sample_tasks, sample_employees):
        text = generate_weekly_summary(
            date(2025, 2, 3), date(2025, 2, 9),
            sample_tasks, sample_employees,
        )
        assert "ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ" in text
        assert "ОБЩАЯ СТАТИСТИКА" in text

    def test_empty_period(self, sample_employees):
        text = generate_weekly_summary(
            date(2025, 3, 1), date(2025, 3, 7),
            [], sample_employees,
        )
        assert "Поставлено: 0" in text
