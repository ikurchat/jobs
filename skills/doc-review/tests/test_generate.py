"""Tests for generate_docx.py — document generation."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Pt, Cm
from docx.oxml.ns import qn

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import load_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def test_dir():
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_content():
    return {
        "title": "Справка о результатах проверки ИБ",
        "addressee": "Директору по безопасности\nИванову Ивану Ивановичу",
        "resume": "В ходе проверки выявлены нарушения политики информационной безопасности.",
        "details": "10 января 2024 года зафиксированы попытки несанкционированного доступа.\n\nИспользовались учётные данные уволенного сотрудника.",
        "conclusions": "Предлагается провести аудит учётных записей и усилить контроль доступа.\n\nСрок исполнения — до 1 марта 2024 года.",
        "appendices": ["Акт проверки от 10.01.2024", "Журнал событий SIEM"],
        "signer_position": "Начальник отдела ИБ",
        "signer_name": "Петров П.П.",
        "executor_name": "Сидоров С.С.",
        "executor_phone": "1234",
    }


# ---------------------------------------------------------------------------
# Tests: document creation
# ---------------------------------------------------------------------------

class TestCreateDocument:
    def test_creates_file(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        result = create_document(sample_content, config, path)
        assert result.exists()
        assert result.suffix == ".docx"

    def test_page_setup(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        section = doc.sections[0]

        # Check margins (with tolerance of 0.1 cm)
        left_cm = section.left_margin / 360000
        right_cm = section.right_margin / 360000
        top_cm = section.top_margin / 360000
        bottom_cm = section.bottom_margin / 360000

        assert abs(left_cm - 3.0) < 0.1, f"Left margin: {left_cm}"
        assert abs(right_cm - 1.0) < 0.1, f"Right margin: {right_cm}"
        assert abs(top_cm - 2.0) < 0.1, f"Top margin: {top_cm}"
        assert abs(bottom_cm - 2.0) < 0.1, f"Bottom margin: {bottom_cm}"

    def test_has_tables(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        # Should have at least: header table, appendix table, signature table
        assert len(doc.tables) >= 3, f"Expected >=3 tables, got {len(doc.tables)}"

    def test_header_table_content(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        header_table = doc.tables[0]

        # Should be 1x2
        assert len(header_table.rows) == 1
        assert len(header_table.columns) == 2

        # Left cell = title
        left_text = header_table.rows[0].cells[0].text
        assert "Справка" in left_text

        # Right cell = addressee
        right_text = header_table.rows[0].cells[1].text
        assert "Иванов" in right_text

    def test_header_table_no_borders(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        header_table = doc.tables[0]

        # Check that borders are set to "none"
        tblPr = header_table._tbl.tblPr
        borders = tblPr.find(qn("w:tblBorders")) if tblPr is not None else None
        if borders is not None:
            for child in borders:
                val = child.get(qn("w:val"))
                assert val in ("none", "nil", None), f"Border {child.tag} has val={val}"

    def test_body_content(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        all_text = " ".join(p.text for p in doc.paragraphs)
        assert "нарушения политики" in all_text
        assert "несанкционированного доступа" in all_text
        assert "аудит учётных записей" in all_text

    def test_appendix_table(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        # Find table with "Приложение:" text
        appendix_found = False
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if "Приложение" in cell.text:
                        appendix_found = True
                        break
        assert appendix_found, "Appendix table not found"

    def test_signature_table(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        # Last table should be signature
        last_table = doc.tables[-1]
        all_text = ""
        for row in last_table.rows:
            for cell in row.cells:
                all_text += cell.text + " "
        assert "Петров" in all_text or "Начальник" in all_text

    def test_footer(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        footer = doc.sections[0].footer
        footer_text = " ".join(p.text for p in footer.paragraphs)
        assert "Сидоров" in footer_text
        assert "1234" in footer_text

    def test_font_in_body(self, test_dir, config, sample_content):
        from generate_docx import create_document

        path = test_dir / "test_v1.docx"
        create_document(sample_content, config, path)

        doc = Document(str(path))
        for p in doc.paragraphs:
            for run in p.runs:
                if run.text.strip():
                    assert run.font.name == "Times New Roman", \
                        f"Font is {run.font.name} for text: {run.text[:50]}"
                    assert run.font.size == Pt(14), \
                        f"Font size is {run.font.size} for text: {run.text[:50]}"

    def test_no_appendix_when_empty(self, test_dir, config, sample_content):
        from generate_docx import create_document

        content = dict(sample_content)
        content["appendices"] = []

        path = test_dir / "test_no_appendix.docx"
        create_document(content, config, path)

        doc = Document(str(path))
        # Should have 2 tables: header + signature (no appendix)
        assert len(doc.tables) == 2


# ---------------------------------------------------------------------------
# Tests: document patching
# ---------------------------------------------------------------------------

class TestPatchDocument:
    def test_patch_creates_new_version(self, test_dir, config, sample_content):
        from generate_docx import create_document, patch_document

        source = test_dir / "report_v1.docx"
        create_document(sample_content, config, source)

        fixes = {"fix_formatting": True}
        result = patch_document(source, fixes, config)
        assert result.exists()
        assert "v2" in result.name

    def test_patch_replaces_paragraph(self, test_dir, config, sample_content):
        from generate_docx import create_document, patch_document

        source = test_dir / "report_v1.docx"
        create_document(sample_content, config, source)

        doc = Document(str(source))
        # Find a non-empty paragraph index
        target_idx = None
        for i, p in enumerate(doc.paragraphs):
            if "нарушения" in p.text:
                target_idx = i
                break

        if target_idx is not None:
            fixes = {
                "replace_paragraphs": {
                    str(target_idx): "Обнаружены серьёзные нарушения."
                }
            }
            result = patch_document(source, fixes, config)
            doc2 = Document(str(result))
            assert "серьёзные" in doc2.paragraphs[target_idx].text


# ---------------------------------------------------------------------------
# Tests: finalization
# ---------------------------------------------------------------------------

class TestFinalize:
    def test_finalize_without_password(self, test_dir, config, sample_content):
        """Finalize should handle missing password gracefully."""
        from generate_docx import create_document, finalize_document
        import os

        source = test_dir / "report_v1.docx"
        create_document(sample_content, config, source)

        # Remove password env var
        old_pwd = os.environ.pop("DOC_DEFAULT_PASSWORD", None)
        try:
            result = finalize_document(source, config)
            # Should still return docx path (possibly unencrypted)
            assert result["docx_path"] is not None
        finally:
            if old_pwd:
                os.environ["DOC_DEFAULT_PASSWORD"] = old_pwd
