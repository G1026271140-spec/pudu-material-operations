"""Supplier order-sheet export. Uses the app's existing, user-approved openpyxl.

No network, Base writes, or dependence on the user's Desktop example workbook.
Source allocations stay in Base; the supplier sheet has exactly five columns.
"""
from __future__ import annotations

from io import BytesIO
import math
import unicodedata

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

from order_scheduling import aggregate_export_rows

HEADERS = ("类型", "物料名称", "语种", "数量", "用途")
WIDTHS = (22, 35, 25, 12, 65)


def _wrapped_lines(value: str, width: float) -> int:
    return sum(max(1, math.ceil(sum(2 if unicodedata.east_asian_width(c) in "WF" else 1
                                   for c in line) / (width - 2))) for line in value.split("\n"))


def build_order_workbook(lines: list[dict]) -> bytes:
    rows = aggregate_export_rows(lines)
    if not rows:
        raise ValueError("至少选择一条有效明细后才能生成下单表。")
    if len(rows) > 1_048_575:
        raise ValueError("下单明细超过 Excel 行数上限，请拆分批次。")
    wb = Workbook()
    ws = wb.active
    ws.title = "物料下单表"
    wb.properties.creator = "PUDU"
    wb.properties.title = "物料下单表"
    ws.append(HEADERS)
    for index, values in enumerate(rows, start=2):
        text_lines = 1
        for col, value in enumerate(values, start=1):
            cell = ws.cell(index, col)
            if isinstance(value, str):
                if len(value) > 32767 or ILLEGAL_CHARACTERS_RE.search(value):
                    raise ValueError(f"下单表第{index}行的{HEADERS[col-1]}含不支持的字符或文字过长。")
                cell.value = value
                # Force literal text, including =/+/-/@ prefixes. Never execute
                # request remarks as Excel formulas or external links.
                cell.data_type = "s"
                text_lines = max(text_lines, _wrapped_lines(value, WIDTHS[col-1]))
            else:
                cell.value = value
                cell.number_format = "#,##0"
            cell.font = Font(name="微软雅黑", size=11, color="152B3C")
            cell.alignment = Alignment(horizontal="right" if col == 4 else "left", vertical="center", wrap_text=True)
            cell.border = Border(bottom=Side(style="hair", color="DFE6EC"))
        ws.row_dimensions[index].height = min(409, max(30, text_lines * 16 + 10))
    for cell in ws[1]:
        cell.font = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1C4B71")
        cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 30
    for index, width in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:E{ws.max_row}"
    ws.sheet_view.showGridLines = False
    ws.print_title_rows = "1:1"
    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=.25, right=.25, top=.35, bottom=.35, header=.15, footer=.15)
    ws.print_area = ws.auto_filter.ref
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
