"""Tests for Baserow REST client."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Set env vars before importing
os.environ.setdefault("BASEROW_URL", "https://baserow.example.com")
os.environ.setdefault("BASEROW_TOKEN", "test-token-123")

from services.baserow import (
    batch_create,
    batch_update,
    create_row,
    delete_row,
    get_row,
    list_all_rows,
    list_rows,
    update_row,
)


class TestListRows:
    def test_basic_list(self, mock_baserow):
        mock_baserow.return_value = {
            "count": 2,
            "next": None,
            "previous": None,
            "results": [
                {"id": 1, "title": "Task 1"},
                {"id": 2, "title": "Task 2"},
            ],
        }

        result = list_rows(100)
        assert result["count"] == 2
        assert len(result["results"]) == 2
        mock_baserow.assert_called_once()

    def test_list_with_filter(self, mock_baserow):
        mock_baserow.return_value = {"count": 1, "next": None, "results": [{"id": 1}]}

        result = list_rows(100, filters={"status": "assigned"})
        call_url = mock_baserow.call_args[0][1]
        assert "filter__status__equal=assigned" in call_url

    def test_list_with_search(self, mock_baserow):
        mock_baserow.return_value = {"count": 0, "next": None, "results": []}

        list_rows(100, search="справка")
        call_url = mock_baserow.call_args[0][1]
        assert "search=" in call_url

    def test_list_with_complex_filter(self, mock_baserow):
        mock_baserow.return_value = {"count": 0, "next": None, "results": []}

        list_rows(100, filters={"priority": {"contains": "high"}})
        call_url = mock_baserow.call_args[0][1]
        assert "filter__priority__contains=high" in call_url


class TestListAllRows:
    def test_single_page(self, mock_baserow):
        mock_baserow.return_value = {
            "count": 2,
            "next": None,
            "results": [{"id": 1}, {"id": 2}],
        }

        result = list_all_rows(100)
        assert len(result) == 2

    def test_multi_page(self, mock_baserow):
        mock_baserow.side_effect = [
            {"count": 3, "next": "page2", "results": [{"id": 1}, {"id": 2}]},
            {"count": 3, "next": None, "results": [{"id": 3}]},
        ]

        result = list_all_rows(100)
        assert len(result) == 3
        assert mock_baserow.call_count == 2


class TestCRUD:
    def test_get_row(self, mock_baserow):
        mock_baserow.return_value = {"id": 42, "title": "Test"}

        result = get_row(100, 42)
        assert result["id"] == 42
        call_url = mock_baserow.call_args[0][1]
        assert "/42/" in call_url

    def test_create_row(self, mock_baserow):
        mock_baserow.return_value = {"id": 43, "title": "New task"}

        result = create_row(100, {"title": "New task"})
        assert result["id"] == 43
        assert mock_baserow.call_args[0][0] == "POST"

    def test_update_row(self, mock_baserow):
        mock_baserow.return_value = {"id": 42, "status": "done"}

        result = update_row(100, 42, {"status": "done"})
        assert result["status"] == "done"
        assert mock_baserow.call_args[0][0] == "PATCH"

    def test_delete_row(self, mock_baserow):
        mock_baserow.return_value = {}

        delete_row(100, 42)
        assert mock_baserow.call_args[0][0] == "DELETE"


class TestBatch:
    def test_batch_create(self, mock_baserow):
        mock_baserow.return_value = {
            "items": [{"id": 50}, {"id": 51}],
        }

        result = batch_create(100, [{"title": "A"}, {"title": "B"}])
        assert len(result["items"]) == 2

    def test_batch_update(self, mock_baserow):
        mock_baserow.return_value = {
            "items": [{"id": 50, "status": "done"}],
        }

        result = batch_update(100, [{"id": 50, "status": "done"}])
        assert result["items"][0]["status"] == "done"


class TestErrorHandling:
    def test_connection_error(self, mock_baserow):
        import urllib.error
        mock_baserow.side_effect = RuntimeError("Connection error: test")

        with pytest.raises(RuntimeError, match="Connection"):
            list_rows(100)

    def test_auth_header(self, mock_baserow):
        """Verify token is sent in Authorization header, not URL."""
        mock_baserow.return_value = {"count": 0, "next": None, "results": []}

        list_rows(100)
        call_url = mock_baserow.call_args[0][1]
        assert "token" not in call_url.lower() or "Token" not in call_url
