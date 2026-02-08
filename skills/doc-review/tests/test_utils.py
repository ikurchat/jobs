"""Tests for utils.py — shared utilities."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Add parent dir to path so we can import utils
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import (
    load_config,
    cm_to_emu,
    emu_to_cm,
    pt_to_half_points,
    half_points_to_pt,
    get_password,
    create_work_dir,
    cleanup_work_dir,
    cleanup_all_work_dirs,
    parse_version,
    next_version_path,
    sanitize_filename,
    diff_documents,
    is_encrypted,
    output_json,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_default_config(self):
        config = load_config()
        assert "formatting" in config
        assert "page" in config
        assert "structure" in config
        assert config["formatting"]["font_name"] == "Times New Roman"
        assert config["formatting"]["font_size_pt"] == 14

    def test_config_page_values(self):
        config = load_config()
        assert config["page"]["margin_left_cm"] == 3.0
        assert config["page"]["margin_right_cm"] == 1.0
        assert config["page"]["margin_top_cm"] == 2.0
        assert config["page"]["margin_bottom_cm"] == 2.0
        assert config["page"]["width_cm"] == 21.0
        assert config["page"]["height_cm"] == 29.7

    def test_config_thresholds(self):
        config = load_config()
        assert config["thresholds"]["rewrite_format_issues"] == 5
        assert config["thresholds"]["rewrite_content_issues"] == 3


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

class TestConversions:
    def test_cm_to_emu(self):
        assert cm_to_emu(1.0) == 360000
        assert cm_to_emu(2.54) == 914400  # 1 inch

    def test_emu_to_cm(self):
        assert emu_to_cm(360000) == 1.0
        assert abs(emu_to_cm(914400) - 2.54) < 0.001

    def test_roundtrip_cm(self):
        for val in [1.0, 2.5, 3.0, 0.5]:
            assert abs(emu_to_cm(cm_to_emu(val)) - val) < 0.001

    def test_pt_to_half_points(self):
        assert pt_to_half_points(14) == 28
        assert pt_to_half_points(10) == 20

    def test_half_points_to_pt(self):
        assert half_points_to_pt(28) == 14.0
        assert half_points_to_pt(20) == 10.0


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------

class TestGetPassword:
    def test_returns_password_from_env(self):
        with mock.patch.dict(os.environ, {"DOC_DEFAULT_PASSWORD": "test123"}):
            assert get_password() == "test123"

    def test_raises_when_not_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove the var if present
            os.environ.pop("DOC_DEFAULT_PASSWORD", None)
            with pytest.raises(RuntimeError, match="not set"):
                get_password()

    def test_raises_when_empty(self):
        with mock.patch.dict(os.environ, {"DOC_DEFAULT_PASSWORD": ""}):
            with pytest.raises(RuntimeError, match="not set"):
                get_password()


# ---------------------------------------------------------------------------
# Working directory
# ---------------------------------------------------------------------------

class TestWorkDir:
    def setup_method(self):
        self.test_base = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.test_base, ignore_errors=True)

    def test_create_work_dir(self):
        config = {"work_dir": str(self.test_base)}
        work_dir = create_work_dir(config)
        assert work_dir.exists()
        assert work_dir.is_dir()
        assert work_dir.parent == self.test_base

    def test_create_work_dir_unique(self):
        config = {"work_dir": str(self.test_base)}
        d1 = create_work_dir(config)
        d2 = create_work_dir(config)
        assert d1 != d2

    def test_cleanup_work_dir(self):
        config = {"work_dir": str(self.test_base)}
        work_dir = create_work_dir(config)
        # Create a file inside
        (work_dir / "test.txt").write_text("hello")
        cleanup_work_dir(work_dir)
        assert not work_dir.exists()

    def test_cleanup_nonexistent(self):
        # Should not raise
        cleanup_work_dir(Path("/nonexistent/path"))

    def test_cleanup_all_work_dirs(self):
        config = {"work_dir": str(self.test_base)}
        d1 = create_work_dir(config)
        d2 = create_work_dir(config)
        count = cleanup_all_work_dirs(config)
        assert count == 2
        assert not d1.exists()
        assert not d2.exists()


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

class TestVersioning:
    def test_parse_version_with_version(self):
        base, ver = parse_version("report_v1.docx")
        assert base == "report"
        assert ver == 1

    def test_parse_version_higher(self):
        base, ver = parse_version("report_v15.docx")
        assert base == "report"
        assert ver == 15

    def test_parse_version_without_version(self):
        base, ver = parse_version("report.docx")
        assert base == "report"
        assert ver == 0

    def test_parse_version_complex_name(self):
        base, ver = parse_version("my_report_2024_v3.docx")
        assert base == "my_report_2024"
        assert ver == 3

    def test_next_version_path_from_v1(self):
        p = next_version_path(Path("/tmp/report_v1.docx"))
        assert p == Path("/tmp/report_v2.docx")

    def test_next_version_path_from_unversioned(self):
        p = next_version_path(Path("/tmp/report.docx"))
        assert p == Path("/tmp/report_v1.docx")

    def test_next_version_path_preserves_directory(self):
        p = next_version_path(Path("/dev/shm/doc-review/abc/report_v3.docx"))
        assert p.parent == Path("/dev/shm/doc-review/abc")
        assert p.name == "report_v4.docx"


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    def test_basic(self):
        assert sanitize_filename("report.docx") == "report.docx"

    def test_removes_path(self):
        result = sanitize_filename("/etc/passwd")
        assert "/" not in result

    def test_removes_special_chars(self):
        result = sanitize_filename("file<>name|test.docx")
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_empty_becomes_document(self):
        assert sanitize_filename("") == "document"

    def test_spaces_to_underscores(self):
        result = sanitize_filename("my report file.docx")
        assert " " not in result
        assert "my_report_file.docx" == result

    def test_path_traversal(self):
        result = sanitize_filename("../../etc/passwd")
        assert ".." not in result or result == "..etcpasswd"  # path stripped


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

class TestDiffDocuments:
    def setup_method(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_docx(self, path: Path, paragraphs: list[str]):
        from docx import Document
        doc = Document()
        for text in paragraphs:
            doc.add_paragraph(text)
        doc.save(str(path))

    def test_identical_documents(self):
        p1 = self.test_dir / "v1.docx"
        p2 = self.test_dir / "v2.docx"
        self._create_docx(p1, ["Hello", "World"])
        self._create_docx(p2, ["Hello", "World"])

        result = diff_documents(p1, p2)
        assert result["summary"] == "изменений не обнаружено"
        assert len(result["added_paragraphs"]) == 0
        assert len(result["removed_paragraphs"]) == 0

    def test_added_paragraph(self):
        p1 = self.test_dir / "v1.docx"
        p2 = self.test_dir / "v2.docx"
        self._create_docx(p1, ["Hello"])
        self._create_docx(p2, ["Hello", "New paragraph"])

        result = diff_documents(p1, p2)
        assert "добавлено" in result["summary"]

    def test_removed_paragraph(self):
        p1 = self.test_dir / "v1.docx"
        p2 = self.test_dir / "v2.docx"
        self._create_docx(p1, ["Hello", "To be removed"])
        self._create_docx(p2, ["Hello"])

        result = diff_documents(p1, p2)
        assert "удалено" in result["summary"]


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

class TestOutputJson:
    def test_output_json(self, capsys):
        output_json({"status": "ok", "message": "тест"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "ok"
        assert data["message"] == "тест"
