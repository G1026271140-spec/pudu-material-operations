from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SOURCE_PATH = DATA_DIR / "source_materials.xlsx"
INVENTORY_XLSX = DATA_DIR / "inventory.xlsx"
INVENTORY_CSV = DATA_DIR / "inventory.csv"
OPTIONS_JSON = DATA_DIR / "options.json"
TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"

NO_MODEL_TEXT = "无需型号"

INVENTORY_HEADERS = [
    "物料编码",
    "物料品类(Material Category)",
    "产品型号(Product Model)",
    "语种(Language)",
    "现存物料数量(Material Quantity)",
    "单价",
    "现存物料总价值",
    "最后更新时间",
]

TRANSACTION_HEADERS = [
    "时间",
    "操作",
    "物料品类(Material Category)",
    "产品型号(Product Model)",
    "语种(Language)",
    "数量",
    "变更前数量",
    "变更后数量",
    "备注",
]


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _has_fill(cell) -> bool:
    return bool(cell.fill and cell.fill.fill_type)


def read_source() -> tuple[list[dict[str, object]], list[str], list[str]]:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"缺少源文件: {SOURCE_PATH}")

    wb = load_workbook(SOURCE_PATH, data_only=True)
    ws = wb.active

    categories: list[dict[str, object]] = []
    models: list[str] = []
    languages: list[str] = []

    for row in range(2, ws.max_row + 1):
        category = _clean(ws.cell(row, 1).value)
        model = _clean(ws.cell(row, 2).value)
        language = _clean(ws.cell(row, 3).value)

        if category:
            categories.append(
                {
                    "name": category,
                    "no_model": _has_fill(ws.cell(row, 1)),
                }
            )
        if model:
            models.append(model)
        if language:
            languages.append(language)

    return categories, _unique(models), _unique(languages)


def build_inventory_rows() -> tuple[list[list[object]], dict[str, object]]:
    categories, models, languages = read_source()
    rows: list[list[object]] = []
    no_model_products: list[str] = []

    for category in categories:
        category_name = str(category["name"])
        model_values = [NO_MODEL_TEXT] if category["no_model"] else models
        if category["no_model"]:
            no_model_products.append(category_name)

        for model in model_values:
            for language in languages:
                material_id = f"MAT-{len(rows) + 1:04d}"
                rows.append(
                    [
                        material_id,
                        category_name,
                        model,
                        language,
                        0,
                        0,
                        0,
                        "",
                    ]
                )

    options = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "products": [str(item["name"]) for item in categories],
        "no_model_products": no_model_products,
        "models": models,
        "languages": languages,
        "no_model_text": NO_MODEL_TEXT,
        "row_count": len(rows),
    }
    return rows, options


def format_inventory_workbook(path: Path, rows: list[list[object]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "库存表"
    ws.append(INVENTORY_HEADERS)

    for row in rows:
        ws.append(row)

    header_fill = PatternFill("solid", fgColor="0F766E")
    header_font = Font(color="FFFFFF", bold=True)
    thin_fill = PatternFill("solid", fgColor="ECFDF5")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    widths = [14, 46, 24, 28, 24, 12, 18, 22]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width

    for row_idx in range(2, ws.max_row + 1):
        if ws.cell(row_idx, 3).value == NO_MODEL_TEXT:
            for col_idx in range(1, ws.max_column + 1):
                ws.cell(row_idx, col_idx).fill = thin_fill
        ws.cell(row_idx, 5).number_format = "0"
        ws.cell(row_idx, 6).number_format = "0.00"
        ws.cell(row_idx, 7).number_format = "0.00"

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    table_ref = f"A1:H{ws.max_row}"
    table = Table(displayName="InventoryTable", ref=table_ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)

    wb.save(path)


def write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows, options = build_inventory_rows()

    format_inventory_workbook(INVENTORY_XLSX, rows)
    write_csv(INVENTORY_CSV, INVENTORY_HEADERS, rows)
    OPTIONS_JSON.write_text(
        json.dumps(options, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not TRANSACTIONS_CSV.exists():
        write_csv(TRANSACTIONS_CSV, TRANSACTION_HEADERS, [])

    print(f"生成库存组合 {len(rows)} 条")
    print(f"完整库存表: {INVENTORY_XLSX}")


if __name__ == "__main__":
    main()
