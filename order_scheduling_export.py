"""Supplier order-sheet export. Uses the app's existing, user-approved openpyxl.

No network, Base writes, or dependence on the user's Desktop example workbook.
Source allocations stay in Base; the supplier sheet has exactly five columns.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from copy import copy
from datetime import datetime, timedelta, timezone
import math
import unicodedata

from openpyxl import load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from order_scheduling import aggregate_export_rows

HEADERS = ("类型", "物料名称", "语种", "数量", "用途")
TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "templates" / "marketing_material_order.xlsx"


def _wrapped_lines(value: str, width: float) -> int:
    return sum(max(1, math.ceil(sum(2 if unicodedata.east_asian_width(c) in "WF" else 1
                                   for c in line) / (width - 2))) for line in value.split("\n"))


def build_order_workbook(lines: list[dict]) -> bytes:
    rows = aggregate_export_rows(lines)
    if not rows:
        raise ValueError("至少选择一条有效明细后才能生成下单表。")
    if len(rows) > 1_048_575:
        raise ValueError("下单明细超过 Excel 行数上限，请拆分批次。")
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"申请单下载模板不存在：{TEMPLATE_PATH}")
    wb = load_workbook(TEMPLATE_PATH)
    ws = wb.active
    now = datetime.now(timezone(timedelta(hours=8)))
    ws.title = f"{now.month}月{now.day}日营销物料下单"
    template_styles = [copy(ws.cell(2, col)._style) for col in range(1, len(HEADERS) + 1)] if ws.max_row >= 2 else [None] * len(HEADERS)
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    for col, header in enumerate(HEADERS, start=1):
        if ws.cell(1, col).value != header:
            raise ValueError(f"下载模板表头不匹配：第{col}列应为{header}。")
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
                column_width = ws.column_dimensions[get_column_letter(col)].width or 10
                text_lines = max(text_lines, _wrapped_lines(value, column_width))
            else:
                cell.value = value
            if template_styles[col - 1]:
                cell._style = copy(template_styles[col - 1])
            if isinstance(value, str):
                cell.value = value
                cell.data_type = "s"
        ws.row_dimensions[index].height = ws.row_dimensions[2].height
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
