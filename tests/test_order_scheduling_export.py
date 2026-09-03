from io import BytesIO
from openpyxl import load_workbook
import pytest

from order_scheduling_export import build_order_workbook, HEADERS


def sample(**overrides):
    return {"category": "产品单页", "model": "GT3", "language": "英语", "quantity": 50,
            "usage": "展会使用", "remark": "", **overrides}


def test_real_xlsx_has_five_columns_numeric_quantities_and_exact_aggregation():
    content = build_order_workbook([sample(), sample(), sample(model="GT5", remark="加厚纸")])
    wb = load_workbook(BytesIO(content))
    ws = wb.active
    assert wb.sheetnames == ["物料下单表"]
    assert tuple(c.value for c in ws[1]) == HEADERS
    assert ws.max_column == 5 and ws.max_row == 3
    assert ws["D2"].value == 100 and ws["D2"].data_type == "n"
    assert sum(ws.cell(row, 4).value for row in (2, 3)) == 150
    assert ws["E3"].value == "展会使用\n制作备注：加厚纸"
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:E3"
    assert ws.print_title_rows == "$1:$1"
    assert ws.column_dimensions["E"].width == 65


@pytest.mark.parametrize("text", ['=HYPERLINK("https://example.invalid", "x")', '+cmd', '-1+1', '@SUM(A1)', '=1+1'])
def test_export_never_interprets_user_text_as_formula(text):
    ws = load_workbook(BytesIO(build_order_workbook([sample(usage=text, model=text)]))).active
    assert ws["E2"].data_type == ws["B2"].data_type == "s"
    assert ws["E2"].value == text


@pytest.mark.parametrize("lines", [[], [sample(quantity=0)], [sample(quantity=1.5)], [sample(quantity=True)],
                                  [sample(remark="\x00")], [sample(usage="a" * 32768)]])
def test_export_rejects_invalid_data_before_batch_writes(lines):
    with pytest.raises(ValueError):
        build_order_workbook(lines)
