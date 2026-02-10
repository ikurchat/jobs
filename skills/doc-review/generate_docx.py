"""Document generation, patching, PDF conversion and encryption for doc-review skill.

CLI modes:
    python generate_docx.py create --input <content.json>
    python generate_docx.py patch --source <file.docx> --fixes <fixes.json>
    python generate_docx.py finalize --source <file.docx>

All operations happen in /dev/shm. Output is JSON on stdout.
"""

import argparse
import json
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

import shutil

from utils import (
    load_config,
    create_work_dir,
    cleanup_work_dir,
    encrypt_docx,
    encrypt_pdf,
    convert_to_pdf,
    next_version_path,
    sanitize_filename,
    output_json,
    output_error,
)


# ---------------------------------------------------------------------------
# Document formatting helpers
# ---------------------------------------------------------------------------

def _apply_paragraph_format(paragraph, config: dict) -> None:
    """Apply standard formatting to a paragraph from config."""
    fmt = config["formatting"]
    pf = paragraph.paragraph_format

    # Alignment
    alignment_map = {
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }
    pf.alignment = alignment_map.get(fmt["alignment"], WD_ALIGN_PARAGRAPH.JUSTIFY)

    # Line spacing
    pf.line_spacing = fmt["line_spacing"]

    # First line indent
    if fmt.get("first_line_indent_cm"):
        pf.first_line_indent = Cm(fmt["first_line_indent_cm"])

    # Space before/after
    pf.space_before = Pt(fmt.get("space_before_pt", 0))
    pf.space_after = Pt(fmt.get("space_after_pt", 0))


def _set_cyrillic_fonts(run, font_name: str) -> None:
    """Set all font faces for Cyrillic support."""
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)
    rFonts.set(qn("w:cs"), font_name)
    rFonts.set(qn("w:eastAsia"), font_name)


def _apply_run_format(run, config: dict, bold: bool = False) -> None:
    """Apply standard font formatting to a run from config."""
    fmt = config["formatting"]
    run.font.name = fmt["font_name"]
    run.font.size = Pt(fmt["font_size_pt"])
    run.bold = bold

    # Ensure Times New Roman works for Cyrillic
    _set_cyrillic_fonts(run, fmt["font_name"])


def _add_formatted_paragraph(doc, text: str, config: dict, bold: bool = False) -> None:
    """Add a paragraph with standard formatting."""
    p = doc.add_paragraph()
    _apply_paragraph_format(p, config)
    # Strip leading tabs — firstLine indent handles the red line
    run = p.add_run(text.lstrip("\t"))
    _apply_run_format(run, config, bold=bold)


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

def _remove_table_borders(table) -> None:
    """Remove all visible borders from a table."""
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)

    borders = OxmlElement("w:tblBorders")
    for border_name in ["top", "left", "bottom", "right", "insideH", "insideV"]:
        border = OxmlElement(f"w:{border_name}")
        border.set(qn("w:val"), "none")
        border.set(qn("w:sz"), "0")
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), "auto")
        borders.append(border)

    # Remove existing borders element if any
    existing = tblPr.find(qn("w:tblBorders"))
    if existing is not None:
        tblPr.remove(existing)
    tblPr.append(borders)

    # Also remove cell borders
    for row in table.rows:
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            cell_borders = OxmlElement("w:tcBorders")
            for border_name in ["top", "left", "bottom", "right"]:
                border = OxmlElement(f"w:{border_name}")
                border.set(qn("w:val"), "none")
                border.set(qn("w:sz"), "0")
                border.set(qn("w:space"), "0")
                border.set(qn("w:color"), "auto")
                cell_borders.append(border)
            existing_cb = tcPr.find(qn("w:tcBorders"))
            if existing_cb is not None:
                tcPr.remove(existing_cb)
            tcPr.append(cell_borders)


def _set_cell_margins(cell, top=0, bottom=0, left=0, right=0) -> None:
    """Set explicit cell margins (padding) in twips. 0 = no padding."""
    tcPr = cell._tc.get_or_add_tcPr()
    existing = tcPr.find(qn("w:tcMar"))
    if existing is not None:
        tcPr.remove(existing)
    tcMar = OxmlElement("w:tcMar")
    for side, val in [("top", top), ("bottom", bottom),
                      ("start", left), ("end", right)]:
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        tcMar.append(el)
    tcPr.append(tcMar)


def _set_cell_text(cell, text: str, config: dict, bold: bool = False) -> None:
    """Set text in a table cell with standard formatting."""
    # Remove extra paragraphs via XML, keep only the first one
    tc = cell._tc
    p_elements = tc.findall(qn("w:p"))
    for p_elem in p_elements[1:]:
        tc.remove(p_elem)

    p = cell.paragraphs[0]
    p.clear()
    _apply_paragraph_format(p, config)
    # Remove indents inside table cells — they clip text and add junk offsets
    p.paragraph_format.first_line_indent = None
    p.paragraph_format.left_indent = None
    run = p.add_run(text)
    _apply_run_format(run, config, bold=bold)


def _set_table_grid(table, col_widths_twips: list[int]) -> None:
    """Set tblGrid with explicit gridCol widths and full-width tblW.

    This is the authoritative way to control column widths in OOXML.
    Word uses tblGrid/gridCol as the ground truth; cell.width and tblW
    alone are often ignored.

    Args:
        table: python-docx Table object.
        col_widths_twips: List of column widths in twips (1/1440 inch).
    """
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)

    total_twips = sum(col_widths_twips)

    # --- tblW: total table width ---
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:w"), str(total_twips))
    tblW.set(qn("w:type"), "dxa")

    # --- Remove tblLayout fixed (let Word auto-fit) ---
    tblLayout = tblPr.find(qn("w:tblLayout"))
    if tblLayout is not None:
        tblPr.remove(tblLayout)

    # --- tblGrid: column definitions ---
    old_grid = tbl.find(qn("w:tblGrid"))
    if old_grid is not None:
        tbl.remove(old_grid)

    new_grid = OxmlElement("w:tblGrid")
    for w in col_widths_twips:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(w))
        new_grid.append(col)

    # tblGrid must come right after tblPr in the XML
    tblPr_index = list(tbl).index(tblPr)
    tbl.insert(tblPr_index + 1, new_grid)

    # --- Cell widths (tcW) must match gridCol ---
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            if i < len(col_widths_twips):
                tcPr = cell._tc.get_or_add_tcPr()
                tcW = tcPr.find(qn("w:tcW"))
                if tcW is None:
                    tcW = OxmlElement("w:tcW")
                    tcPr.insert(0, tcW)
                tcW.set(qn("w:w"), str(col_widths_twips[i]))
                tcW.set(qn("w:type"), "dxa")


def _set_cell_numbered_list(cell, items: list[str], config: dict) -> None:
    """Fill a table cell with a clean numbered list — no extra indents.

    Each item becomes a separate paragraph: "1. text", "2. text", etc.
    No hanging indent — items sit flush at the left edge of the cell.
    """
    # Remove all paragraphs except the first via XML
    tc = cell._tc
    p_elements = tc.findall(qn("w:p"))
    for p_elem in p_elements[1:]:
        tc.remove(p_elem)
    if cell.paragraphs:
        cell.paragraphs[0].clear()

    for i, item in enumerate(items):
        if i == 0:
            p = cell.paragraphs[0]
        else:
            p = cell.add_paragraph()

        _apply_paragraph_format(p, config)
        # No indent in table cells — clean flush-left alignment
        p.paragraph_format.first_line_indent = None
        p.paragraph_format.left_indent = None

        run = p.add_run(f"{i + 1}. {item}")
        _apply_run_format(run, config)


def _page_width_twips(config: dict) -> int:
    """Return usable page width (between margins) in twips."""
    page = config["page"]
    width_cm = page["width_cm"] - page["margin_left_cm"] - page["margin_right_cm"]
    return int(width_cm / 2.54 * 1440)


def _create_1x2_table(doc, left_text: str, right_text: str, config: dict,
                       left_bold: bool = False, right_bold: bool = False,
                       right_align_right: bool = False,
                       left_pct: float = 0.5):
    """Create a 1x2 table without borders spanning full page width.

    Args:
        right_align_right: If True, right cell text is right-aligned.
        left_pct: Left column share (0..1). Default 0.5 (50/50).
    Returns the created table.
    """
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    _remove_table_borders(table)

    # Set proper grid with explicit column widths
    total_twips = _page_width_twips(config)
    left_twips = int(total_twips * left_pct)
    right_twips = total_twips - left_twips
    _set_table_grid(table, [left_twips, right_twips])

    _set_cell_text(table.rows[0].cells[0], left_text, config, bold=left_bold)
    _set_cell_text(table.rows[0].cells[1], right_text, config, bold=right_bold)

    # Right-align right cell if requested
    if right_align_right:
        for p in table.rows[0].cells[1].paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    return table


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

def _setup_page(doc, config: dict) -> None:
    """Configure page size and margins from config."""
    page = config["page"]
    section = doc.sections[0]

    section.page_width = Cm(page["width_cm"])
    section.page_height = Cm(page["height_cm"])
    section.left_margin = Cm(page["margin_left_cm"])
    section.right_margin = Cm(page["margin_right_cm"])
    section.top_margin = Cm(page["margin_top_cm"])
    section.bottom_margin = Cm(page["margin_bottom_cm"])


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

def _make_footer_run(paragraph, text: str, config: dict) -> None:
    """Add a run to a footer paragraph with proper formatting."""
    footer_cfg = config["structure"]["footer"]
    font_name = config["formatting"]["font_name"]
    font_size = footer_cfg.get("font_size_pt", 12)

    run = paragraph.add_run(text)
    run.font.name = font_name
    run.font.size = Pt(font_size)
    run.font.color.rgb = RGBColor(0, 0, 0)

    # Set Cyrillic font faces
    _set_cyrillic_fonts(run, font_name)


def _apply_footer_paragraph_format(paragraph) -> None:
    """Apply zero-spacing single-line format to a footer paragraph."""
    pf = paragraph.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE


def _clear_footer_xml(footer) -> None:
    """Properly clear footer by removing all child elements from XML."""
    footer_element = footer._element
    for child in list(footer_element):
        footer_element.remove(child)


def _clear_header_xml(header) -> None:
    """Clear header XML completely, removing SDT elements and adding empty paragraph."""
    header_element = header._element
    for child in list(header_element):
        header_element.remove(child)
    # Add one empty paragraph (required by OOXML)
    empty_p = OxmlElement("w:p")
    header_element.append(empty_p)


def _remove_title_page_flag(section) -> None:
    """Remove <w:titlePg/> from sectPr to disable 'Different First Page'."""
    sectPr = section._sectPr
    title_pg = sectPr.find(qn("w:titlePg"))
    if title_pg is not None:
        sectPr.remove(title_pg)


def _calc_executor_spacers(doc, config: dict) -> int:
    """Calculate number of spacer paragraphs needed to push executor table to page bottom.

    Estimates total content height in points, determines which page the signature
    lands on, and calculates remaining space on that page minus executor height.
    Returns number of 12pt single-spaced empty paragraphs needed.
    """
    body = doc.element.body
    usable_h_pt = _page_usable_height_pt(config)
    content_h_pt = 0.0

    for child in body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'sectPr':
            continue
        if tag == 'tbl':
            # Estimate table height: count paragraphs across all cells
            paras = child.findall(f'.//{qn("w:p")}')
            content_h_pt += len(paras) * 14 * 1.5  # rough: 14pt * 1.5 spacing per para
        elif tag == 'p':
            text = ''.join(n.text or '' for n in child.iter(qn('w:t')))
            sz_el = child.find(f'.//{qn("w:sz")}')
            font_pt = int(sz_el.get(qn('w:val'), '28')) / 2 if sz_el is not None else 14
            pPr = child.find(qn('w:pPr'))
            spacing = pPr.find(qn('w:spacing')) if pPr is not None else None
            if spacing is not None:
                line_val = int(spacing.get(qn('w:line'), '360'))
            else:
                line_val = 360
            line_mult = line_val / 240

            if not text.strip():
                content_h_pt += font_pt * line_mult
            else:
                chars_per_line = 80
                lines = max(1, len(text) / chars_per_line)
                content_h_pt += lines * font_pt * line_mult

    # Which page does this land on?
    page_num = int(content_h_pt // usable_h_pt) + 1
    used_on_last_page = content_h_pt - (page_num - 1) * usable_h_pt

    # Executor table = 2 lines * 12pt = 24pt
    executor_h_pt = 24
    remaining = usable_h_pt - used_on_last_page - executor_h_pt

    if remaining <= 0:
        return 0

    spacer_h = 12  # 12pt single-spaced empty paragraph
    return max(0, int(remaining / spacer_h) - 1)  # -1 for safety margin


def _page_usable_height_pt(config: dict) -> float:
    """Return usable page height (between margins) in points."""
    page = config["page"]
    h_cm = page["height_cm"] - page["margin_top_cm"] - page["margin_bottom_cm"]
    return h_cm / 2.54 * 72


def _create_executor_table(doc, executor_name: str, executor_phone: str, config: dict) -> None:
    """Add executor info as invisible (borderless) 1x1 table at the very end of body.

    Automatically calculates spacer paragraphs to push the table to the bottom
    of the page where the signature is located.

    executor_name MUST be full name (Фамилия Имя Отчество).
    """
    footer_cfg = config["structure"]["footer"]
    font_name = config["formatting"]["font_name"]
    font_size = footer_cfg.get("font_size_pt", 12)

    # Calculate and add spacers
    spacer_count = _calc_executor_spacers(doc, config)
    for _ in range(spacer_count):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pf.first_line_indent = None
        # 12pt invisible run to set line height
        run = p.add_run()
        run.font.size = Pt(12)

    # Create 1x1 invisible table
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    _remove_table_borders(table)

    cell = table.rows[0].cells[0]
    _set_cell_margins(cell, top=0, bottom=0, left=0, right=0)

    # Remove default paragraph, build from scratch
    tc = cell._tc
    for p_elem in tc.findall(qn("w:p")):
        tc.remove(p_elem)

    def _make_executor_para(text):
        p = OxmlElement("w:p")
        pPr = OxmlElement("w:pPr")
        jc = OxmlElement("w:jc")
        jc.set(qn("w:val"), "left")
        pPr.append(jc)
        ind = OxmlElement("w:ind")
        ind.set(qn("w:firstLine"), "0")
        ind.set(qn("w:left"), "0")
        pPr.append(ind)
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:before"), "0")
        spacing.set(qn("w:after"), "0")
        spacing.set(qn("w:line"), "240")
        spacing.set(qn("w:lineRule"), "auto")
        pPr.append(spacing)
        p.append(pPr)

        r = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        rFonts = OxmlElement("w:rFonts")
        rFonts.set(qn("w:ascii"), font_name)
        rFonts.set(qn("w:hAnsi"), font_name)
        rFonts.set(qn("w:cs"), font_name)
        rFonts.set(qn("w:eastAsia"), font_name)
        rPr.append(rFonts)
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(font_size * 2))
        rPr.append(sz)
        szCs = OxmlElement("w:szCs")
        szCs.set(qn("w:val"), str(font_size * 2))
        rPr.append(szCs)
        r.append(rPr)
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = text
        r.append(t)
        p.append(r)
        return p

    tc.append(_make_executor_para(executor_name))
    tc.append(_make_executor_para(executor_phone))


def _setup_page_numbering(doc, config: dict) -> None:
    """Page numbering from page 2: centered, 14pt TNR. Page 1 = nothing."""
    section = doc.sections[0]
    sectPr = section._sectPr

    # Enable differentFirst
    title_pg = sectPr.find(qn("w:titlePg"))
    if title_pg is None:
        title_pg = OxmlElement("w:titlePg")
        sectPr.append(title_pg)

    font_name = config["formatting"]["font_name"]
    pg_cfg = config.get("page_numbering", {})
    font_size = pg_cfg.get("font_size_pt", 14)

    # First page header — empty
    first_header = section.first_page_header
    first_header.is_linked_to_previous = False
    _clear_header_xml(first_header)

    # First page footer — empty
    first_footer = section.first_page_footer
    first_footer.is_linked_to_previous = False
    _clear_footer_xml(first_footer)

    # Default header (pages 2+): empty line + PAGE field centered
    header = section.header
    header.is_linked_to_previous = False
    _clear_header_xml(header)

    # Empty line above number
    p_spacer = header.add_paragraph()
    p_spacer.paragraph_format.space_before = Pt(0)
    p_spacer.paragraph_format.space_after = Pt(0)
    p_spacer.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

    # PAGE field
    p = header.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)

    # fldChar begin
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run_begin = p.add_run()
    run_begin.font.name = font_name
    run_begin.font.size = Pt(font_size)
    _set_cyrillic_fonts(run_begin, font_name)
    run_begin._element.append(fld_begin)

    # instrText " PAGE "
    run_instr = p.add_run()
    run_instr.font.name = font_name
    run_instr.font.size = Pt(font_size)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    run_instr._element.append(instr)

    # fldChar end
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run_end = p.add_run()
    run_end.font.name = font_name
    run_end.font.size = Pt(font_size)
    run_end._element.append(fld_end)

    # Default footer — empty
    footer = section.footer
    footer.is_linked_to_previous = False
    _clear_footer_xml(footer)


def _create_signature_table(doc, position: str, name: str, config: dict):
    """Signature table: 62/38 grid, name with 18 spaces + center + firstLine=567."""
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _remove_table_borders(table)

    total_twips = _page_width_twips(config)
    sig_cfg = config["structure"].get("signature", {})
    ratio = sig_cfg.get("grid_ratio", [62, 38])
    left_twips = int(total_twips * ratio[0] / 100)
    right_twips = total_twips - left_twips
    _set_table_grid(table, [left_twips, right_twips])

    for cell in table.rows[0].cells:
        _set_cell_margins(cell, top=0, bottom=0, left=0, right=0)

    # Left: position
    _set_cell_text(table.rows[0].cells[0], position, config)
    for p in table.rows[0].cells[0].paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Right: И.О. Фамилия with spaces
    cell_right = table.rows[0].cells[1]
    tc = cell_right._tc
    p_elements = tc.findall(qn("w:p"))
    for p_elem in p_elements[1:]:
        tc.remove(p_elem)

    p0 = cell_right.paragraphs[0]
    p0.clear()
    spaces = sig_cfg.get("right_cell_spaces", 18)
    first_line = sig_cfg.get("right_cell_first_line", 567)
    p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pPr = p0._element.get_or_add_pPr()
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        pPr.append(ind)
    ind.set(qn("w:firstLine"), str(first_line))
    p0.paragraph_format.space_before = Pt(0)
    p0.paragraph_format.space_after = Pt(0)

    run = p0.add_run(" " * spaces + name)
    _apply_run_format(run, config)

    # Empty p1
    cell_right.add_paragraph()

    return table


def _setup_footer(doc, executor_name: str, executor_phone: str, config: dict) -> None:
    """Add footer with executor info: name on line 1, phone on line 2.

    executor_name MUST be the full name (Фамилия Имя Отчество), NOT initials.
    executor_phone is the internal phone number.
    """
    section = doc.sections[0]

    # Remove "Different First Page" flag so footer shows on page 1
    _remove_title_page_flag(section)

    # Clear any existing header SDT/PAGE elements (bug 5)
    header = section.header
    header.is_linked_to_previous = False
    _clear_header_xml(header)

    # Properly clear existing footer XML (bug 4)
    footer = section.footer
    footer.is_linked_to_previous = False
    _clear_footer_xml(footer)

    # Line 1: executor name
    p1 = footer.add_paragraph()
    _apply_footer_paragraph_format(p1)
    _make_footer_run(p1, executor_name, config)

    # Line 2: phone number
    p2 = footer.add_paragraph()
    _apply_footer_paragraph_format(p2)
    _make_footer_run(p2, executor_phone, config)


# ---------------------------------------------------------------------------
# Document creation
# ---------------------------------------------------------------------------

def create_document(content: dict, config: dict, output_path: Path) -> Path:
    """Create a new .docx document from structured content.

    Args:
        content: Dict with keys:
            - title: str — document title
            - addressee: str — "Должность\\nФИО"
            - resume: str — resume block text
            - details: str — details block text
            - conclusions: str — conclusions block text
            - appendices: list[str] — optional list of appendix items
            - signer_position: str — signer's position
            - signer_name: str — signer's full name
            - executor_name: str — executor's FULL name for footer
              (Фамилия Имя Отчество, NOT initials)
            - executor_phone: str — internal phone number for footer
        config: Parsed config.json.
        output_path: Where to save the document.

    Returns:
        Path to created file.
    """
    doc = Document()
    _setup_page(doc, config)

    # --- Header table ---
    title = content.get("title", "")
    addressee = content.get("addressee", "")
    header_table = _create_1x2_table(doc, title, addressee, config,
                                      left_bold=False, right_align_right=True,
                                      left_pct=0.6)
    # Header table only: zero cell margins so addressee right edge sits
    # exactly at the page right margin; left-align title (not justify).
    for cell in header_table.rows[0].cells:
        _set_cell_margins(cell, left=0, right=0)
    # Title cell: left-aligned, not justified
    for p in header_table.rows[0].cells[0].paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Add spacers before title in left cell
    cell0 = header_table.rows[0].cells[0]
    tc0 = cell0._tc
    title_p = cell0.paragraphs[0]._element
    for _ in range(4):
        empty_p = OxmlElement("w:p")
        pPr_el = OxmlElement("w:pPr")
        sp = OxmlElement("w:spacing")
        sp.set(qn("w:after"), "0")
        sp.set(qn("w:before"), "0")
        sp.set(qn("w:line"), "276")
        sp.set(qn("w:lineRule"), "auto")
        pPr_el.append(sp)
        empty_p.append(pPr_el)
        tc0.insert(tc0.index(title_p), empty_p)

    # --- Two empty lines after header ---
    _add_formatted_paragraph(doc, "", config)
    _add_formatted_paragraph(doc, "", config)

    # --- Body: three blocks ---
    # Block 1: Resume
    resume_text = content.get("resume", "")
    if resume_text:
        for para_text in resume_text.split("\n\n"):
            if para_text.strip():
                _add_formatted_paragraph(doc, para_text.strip(), config)

    # Block 2: Details
    details_text = content.get("details", "")
    if details_text:
        for para_text in details_text.split("\n\n"):
            if para_text.strip():
                _add_formatted_paragraph(doc, para_text.strip(), config)

    # Block 3: Conclusions
    conclusions_text = content.get("conclusions", "")
    if conclusions_text:
        for para_text in conclusions_text.split("\n\n"):
            if para_text.strip():
                _add_formatted_paragraph(doc, para_text.strip(), config)

    # --- Appendix table (optional) ---
    appendices = content.get("appendices", [])
    if appendices:
        _add_formatted_paragraph(doc, "", config)
        appendix_label = config["structure"]["appendix"]["left_cell_text"]
        appendix_table = _create_1x2_table(doc, appendix_label, "", config)
        # Fill right cell with properly indented numbered list
        _set_cell_numbered_list(appendix_table.rows[0].cells[1], appendices, config)

    # --- Signature table (1×2, border=nil, position left, name right) ---
    _add_formatted_paragraph(doc, "", config)
    signer_position = content.get("signer_position", "")
    signer_name = content.get("signer_name", "")
    _create_signature_table(doc, signer_position, signer_name, config)

    # --- Executor in body (NOT footer) ---
    executor_name = content.get("executor_name", "")
    executor_phone = content.get("executor_phone", "")
    if executor_name:
        _create_executor_table(doc, executor_name, executor_phone, config)

    # --- Page numbering from page 2 ---
    _setup_page_numbering(doc, config)

    doc.save(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# Document patching
# ---------------------------------------------------------------------------

def patch_document(source_path: Path, fixes: dict, config: dict,
                   output_path: Path | None = None) -> Path:
    """Apply fixes to an existing document.

    Args:
        source_path: Path to source .docx.
        fixes: Dict with fix instructions:
            - fix_formatting: bool — reapply all font/margin/spacing
            - fix_structure: bool — rebuild structural tables
            - replace_paragraphs: dict[str, str] — index -> new text
            - add_paragraphs: list[{"after": int, "text": str}]
            - remove_paragraphs: list[int] — indices to remove
        config: Parsed config.json.
        output_path: Where to save. Defaults to next version.

    Returns:
        Path to the patched document.
    """
    out_path = output_path or next_version_path(source_path)
    doc = Document(str(source_path))

    # Fix formatting
    if fixes.get("fix_formatting"):
        _fix_all_formatting(doc, config)

    # Fix page setup
    if fixes.get("fix_page_setup"):
        _setup_page(doc, config)

    # Fix header table grid (bug 12)
    if fixes.get("fix_header_table") and doc.tables:
        _fix_header_table_grid(doc.tables[0], config)

    # Fix appendix table grid/margins
    if fixes.get("fix_appendix_table") and len(doc.tables) > 1:
        _fix_appendix_table(doc.tables[1], config)

    # Replace paragraphs
    replacements = fixes.get("replace_paragraphs", {})
    for idx_str, new_text in replacements.items():
        idx = int(idx_str)
        if 0 <= idx < len(doc.paragraphs):
            p = doc.paragraphs[idx]
            # Clear existing runs and add new one with proper formatting
            for run in p.runs:
                run.text = ""
            if p.runs:
                p.runs[0].text = new_text
                _apply_run_format(p.runs[0], config)
            else:
                run = p.add_run(new_text)
                _apply_run_format(run, config)

    doc.save(str(out_path))
    return out_path


def _fix_header_table_grid(table, config: dict) -> None:
    """Fix header table: set full-width grid (60/40), right-align right cell.

    Does NOT delete paragraphs — empty paragraphs in cell[0] serve as
    vertical spacers to position the title below the addressee.
    """
    if len(table.columns) != 2:
        return
    total_twips = _page_width_twips(config)
    left_twips = int(total_twips * 0.6)
    right_twips = total_twips - left_twips
    _set_table_grid(table, [left_twips, right_twips])

    # Zero cell margins so text reaches the page margins exactly
    for cell in table.rows[0].cells:
        _set_cell_margins(cell, left=0, right=0)

    # Remove indents from header table cells
    for cell in table.rows[0].cells:
        for p in cell.paragraphs:
            p.paragraph_format.first_line_indent = None
            p.paragraph_format.left_indent = None

    # Title cell: left-aligned (not justify)
    for p in table.rows[0].cells[0].paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Right-align right cell (addressee)
    for p in table.rows[0].cells[1].paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _fix_appendix_table(table, config: dict) -> None:
    """Fix appendix table: set grid (20/80), zero cell margins, clean indents.

    Does NOT touch numPr — preserves Word's native numbering in right cell.
    """
    if len(table.columns) != 2:
        return
    total_twips = _page_width_twips(config)
    left_twips = int(total_twips * 0.2)
    right_twips = total_twips - left_twips
    _set_table_grid(table, [left_twips, right_twips])

    # Zero cell margins for tight layout
    for cell in table.rows[0].cells:
        _set_cell_margins(cell, left=0, right=0)

    # Remove table borders (border=nil on table + all cells)
    _remove_table_borders(table)

    # Clean indents in cells, but preserve numPr
    for cell in table.rows[0].cells:
        for p in cell.paragraphs:
            if not _has_numPr(p):
                p.paragraph_format.first_line_indent = None
                p.paragraph_format.left_indent = None


def _has_numPr(paragraph) -> bool:
    """Check if a paragraph has Word numbering (numPr) attached."""
    pPr = paragraph._element.find(qn("w:pPr"))
    return pPr is not None and pPr.find(qn("w:numPr")) is not None


def _fix_all_formatting(doc, config: dict) -> None:
    """Reapply correct formatting to all paragraphs and runs.

    Special cases:
    - Body paragraphs with leading \\t: strip the tab (firstLine handles indent).
    - Table cell paragraphs with numPr: do NOT override indent (would break
      Word's native numbering layout).
    """
    for paragraph in doc.paragraphs:
        _apply_paragraph_format(paragraph, config)
        for run in paragraph.runs:
            # Strip leading tabs — firstLine indent handles the red line
            if run.text.startswith("\t"):
                run.text = run.text.lstrip("\t")
            _apply_run_format(run, config)

    # Fix tables (text formatting + grid)
    for i, table in enumerate(doc.tables):
        # Fix header table grid (first table)
        if i == 0 and len(table.columns) == 2:
            _fix_header_table_grid(table, config)
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _apply_paragraph_format(paragraph, config)
                    # Preserve Word numbering indent — don't clobber with firstLine
                    if _has_numPr(paragraph):
                        paragraph.paragraph_format.first_line_indent = None
                        paragraph.paragraph_format.left_indent = None
                    for run in paragraph.runs:
                        _apply_run_format(run, config)


# ---------------------------------------------------------------------------
# Finalization (encrypt + PDF)
# ---------------------------------------------------------------------------

def finalize_document(source_path: Path, config: dict) -> dict:
    """Finalize a document: encrypt .docx, convert to PDF, encrypt PDF.

    Returns:
        {
            "docx_path": str,
            "pdf_path": str | null,
            "encrypted": true
        }
    """
    result = {
        "docx_path": None,
        "pdf_path": None,
        "encrypted": False,
    }

    # Step 1: Encrypt .docx
    encrypted_docx = source_path.parent / f"final_{source_path.name}"
    try:
        shutil.copy2(str(source_path), str(encrypted_docx))
        encrypt_docx(encrypted_docx)
        result["docx_path"] = str(encrypted_docx)
        result["encrypted"] = True
    except Exception as e:
        # If encryption fails, use unencrypted version
        result["docx_path"] = str(source_path)
        result["encryption_error"] = str(e)

    # Step 2: Convert to PDF
    pdf_path = convert_to_pdf(source_path, source_path.parent)
    if pdf_path:
        # Step 3: Encrypt PDF
        encrypted_pdf = source_path.parent / f"final_{pdf_path.name}"
        try:
            shutil.copy2(str(pdf_path), str(encrypted_pdf))
            encrypt_pdf(encrypted_pdf)
            result["pdf_path"] = str(encrypted_pdf)
            # Remove unencrypted PDF
            pdf_path.unlink(missing_ok=True)
        except Exception as e:
            result["pdf_path"] = str(pdf_path)
            result["pdf_encryption_error"] = str(e)
    else:
        result["pdf_path"] = None
        result["pdf_note"] = "LibreOffice не доступен, PDF не создан"

    # Step 4: Remove unencrypted source if encryption succeeded
    if result["encrypted"] and encrypted_docx.exists():
        source_path.unlink(missing_ok=True)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate/edit .docx documents")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # create
    p_create = subparsers.add_parser("create", help="Create new document from JSON")
    p_create.add_argument("--input", type=Path, required=True,
                          help="JSON file with document content")
    p_create.add_argument("--output", type=Path, default=None,
                          help="Output .docx path")
    p_create.add_argument("--config", type=Path, default=None)

    # patch
    p_patch = subparsers.add_parser("patch", help="Apply fixes to existing document")
    p_patch.add_argument("--source", type=Path, required=True,
                         help="Source .docx file")
    p_patch.add_argument("--fixes", type=Path, required=True,
                         help="JSON file with fixes")
    p_patch.add_argument("--output", type=Path, default=None)
    p_patch.add_argument("--config", type=Path, default=None)

    # finalize
    p_final = subparsers.add_parser("finalize", help="Encrypt + PDF + encrypt PDF")
    p_final.add_argument("--source", type=Path, required=True,
                         help="Source .docx file to finalize")
    p_final.add_argument("--config", type=Path, default=None)

    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except Exception as e:
        output_error(f"Config error: {e}", code=2)

    work_dir = None
    try:
        if args.mode == "create":
            with open(args.input, "r", encoding="utf-8") as f:
                content = json.load(f)

            if not args.output:
                work_dir = create_work_dir(config)
                title = content.get("title", "document")
                safe_name = sanitize_filename(title)
                out_path = work_dir / f"{safe_name}_v1.docx"
            else:
                out_path = args.output

            result_path = create_document(content, config, out_path)
            output_json({
                "mode": "create",
                "output_path": str(result_path),
                "status": "ok",
            })

        elif args.mode == "patch":
            with open(args.fixes, "r", encoding="utf-8") as f:
                fixes = json.load(f)

            result_path = patch_document(
                args.source, fixes, config, args.output
            )
            output_json({
                "mode": "patch",
                "source_path": str(args.source),
                "output_path": str(result_path),
                "status": "ok",
            })

        elif args.mode == "finalize":
            result = finalize_document(args.source, config)
            result["mode"] = "finalize"
            result["status"] = "ok"
            output_json(result)

    except Exception as e:
        output_error(str(e))
    finally:
        if work_dir:
            cleanup_work_dir(work_dir)


if __name__ == "__main__":
    main()
