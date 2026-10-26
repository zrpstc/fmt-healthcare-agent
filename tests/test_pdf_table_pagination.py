"""Oversized assay rows must span pages without dropping any measurements."""

import copy

import pytest
from fpdf import FPDF
from fpdf.fonts import FontFace

from wgs_agent.reporting.fonts import resolve_cjk_fonts
from wgs_agent.tools.report_maker import _generate_fpdf_report, _paginate_pdf_table_rows


def make_pdf():
    pdf = FPDF()
    regular, bold = resolve_cjk_fonts()
    pdf.add_font("WgsCN", "", regular)
    pdf.add_font("WgsCN", "B", bold)
    pdf.add_page()
    pdf.set_font("WgsCN", "", 10)
    return pdf


@pytest.mark.parametrize("ncols", [2, 4, 6])
def test_oversized_cells_preserve_every_character_and_fit_below_heading(ncols):
    pdf = make_pdf()
    widths = tuple(range(1, ncols + 1))
    rows = [
        [f"字段{i}" for i in range(ncols)],
        ["蛋白质及氨基酸"] + [
            (f"菌群{i} Escherichia_coli（0.000123 相对丰度）；" * (80 + i * 20)) + f"END_{i}"
            for i in range(1, ncols)
        ],
        ["常规结果"] + ["0.125" for _ in range(ncols - 1)],
    ]
    before = copy.deepcopy(rows)
    fragments = list(_paginate_pdf_table_rows(pdf, rows, widths))
    assert rows == before
    assert fragments[0] == (0, rows[0])
    assert [cells for index, cells in fragments if index == 2] == [rows[2]]
    continued = [cells for index, cells in fragments if index == 1]
    assert len(continued) > 1
    assert continued[0][0] == rows[1][0]
    assert all(cells[0] == rows[1][0] + "（续）" for cells in continued[1:])
    for column in range(1, ncols):
        assert "".join(cells[column] for cells in continued) == rows[1][column]
    with pdf.table(col_widths=widths, line_height=5, padding=1.4, v_align="TOP") as table:
        for _, cells in fragments:
            table.row(cells)
    assert pdf.page_no() > 1


def test_long_category_itself_is_split_without_losing_text():
    pdf = make_pdf()
    source = ["超长分类名" * 600 + "END_CATEGORY", "菌群结果 " * 900 + "END_RESULT"]
    fragments = [cells for index, cells in _paginate_pdf_table_rows(
        pdf, [["分类", "检测结果"], source], (.34, .66),
    ) if index == 1]
    assert len(fragments) > 1
    for column in range(2):
        assert "".join(cells[column] for cells in fragments) == source[column]


def test_large_score_font_is_used_when_measuring_rows():
    pdf = make_pdf()
    rows = [["A", "B"], ["SCORE", "1234567890 " * 500]]
    face = FontFace(size_pt=18)
    fragments = list(_paginate_pdf_table_rows(pdf, rows, body_style=face))
    with pdf.table(line_height=5, padding=1.4) as table:
        for index, cells in fragments:
            table.row(cells, style=face if index else None)
    assert pdf.page_no() > 1
    assert "".join(cells[1] for index, cells in fragments if index) == rows[1][1]


def test_report_renderer_handles_multiple_long_tables_and_table_of_contents(tmp_path):
    cells = ["蛋白质及氨基酸", "合成通路 0.00059158；" * 200, "降解通路 0.00015787；" * 80,
             "g__Escherichia.s__Escherichia_coli（0.00023323 relative_abundance）；" * 180 + "END_AMINO"]
    md = "\n".join([
        "# 肠道菌群报告", "报告日期：2026-10-26", "## 目录", "- 内容",
        "## 7 膳食底物利用与营养物质代谢", "### 7.3 其他营养物质的合成与降解",
        "| 功能类别 | 合成潜力 | 降解潜力 | 主要贡献菌 |", "| --- | --- | --- | --- |",
        "| " + " | ".join(cells) + " |", "",
        "## 8 肠道代谢", "### 8.1 短链脂肪酸相关功能",
        "| 功能 | 贡献菌 |", "| --- | --- |", "| 乙酸 | " + cells[-1] + " |", "",
        "## 14 综合建议", "END_REPORT",
    ])
    path = tmp_path / "long_report.pdf"
    assert _generate_fpdf_report(md, "LONG_ROWS", str(path)) == str(path)
    assert path.read_bytes().startswith(b"%PDF-")
    assert path.stat().st_size > 1000
