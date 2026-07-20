from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs" / f"feishu_bitable_migration_xlsx_{date.today():%Y%m%d}"

INVENTORY_XLSX = DATA_DIR / "inventory.xlsx"
INVENTORY_CSV = DATA_DIR / "inventory.csv"
OPTIONS_JSON = DATA_DIR / "options.json"
TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"

NO_MODEL_TEXT = "无需型号"

SOURCE_INVENTORY_HEADERS = {
    "material_code": "物料编码",
    "category": "物料品类(Material Category)",
    "model": "产品型号(Product Model)",
    "language": "语种(Language)",
    "quantity": "现存物料数量(Material Quantity)",
    "unit_price": "单价",
    "total_value": "现存物料总价值",
    "updated_at": "最后更新时间",
}

SOURCE_TRANSACTION_HEADERS = {
    "created_at": "时间",
    "action": "操作",
    "category": "物料品类(Material Category)",
    "model": "产品型号(Product Model)",
    "language": "语种(Language)",
    "quantity": "数量",
    "before_quantity": "变更前数量",
    "after_quantity": "变更后数量",
    "note": "备注",
}


TABLES = {
    "material_categories": {
        "sheet": "物料品类",
        "file": "01_物料品类_material_categories.xlsx",
        "source": "旧库存数据: material_categories",
        "headers": [
            "原系统ID",
            "物料品类",
            "是否无需型号",
            "启用状态",
            "库存行数",
            "产品型号数量",
            "语种数量",
            "创建时间",
            "备注",
        ],
    },
    "inventory_items": {
        "sheet": "物料主数据",
        "file": "02_物料主数据_inventory_items.xlsx",
        "source": "旧库存数据: inventory_items",
        "headers": [
            "物料编码",
            "物料品类",
            "产品型号",
            "语种",
            "当前库存",
            "备注",
            "单价",
            "海关编码",
        ],
    },
    "inventory_transactions": {
        "sheet": "库存流水",
        "file": "03_库存流水_inventory_transactions.xlsx",
        "source": "旧库存数据: inventory_transactions",
        "headers": [
            "原系统ID",
            "发生时间",
            "流水类型",
            "物料编码",
            "物料品类",
            "产品型号",
            "语种",
            "数量",
            "变更前数量",
            "变更后数量",
            "库存变化",
            "幂等键",
            "操作人",
            "操作状态",
            "撤回时间",
            "原流水ID",
            "备注",
        ],
    },
    "material_request": {
        "sheet": "物料申请单",
        "file": "04_物料申请单_material_request.xlsx",
        "source": "新增飞书表",
        "headers": [
            "申请单号",
            "申请人",
            "申请部门/区域",
            "业务类型",
            "物料用途",
            "用途/活动",
            "期望发放日期",
            "审批状态",
            "市场负责人",
            "审批意见",
            "提交时间",
            "审批时间",
            "备注",
        ],
    },
    "material_request_line": {
        "sheet": "申请明细",
        "file": "05_申请明细_material_request_line.xlsx",
        "source": "新增飞书表",
        "headers": [
            "明细编号",
            "所属申请单",
            "物料编码",
            "物料名称",
            "申请数量",
            "提交时库存快照",
            "审批通过数量",
            "实际发放数量",
            "实际发放物料编码",
            "实际发放物料品类",
            "实际发放产品型号",
            "实际发放语种",
            "明细状态",
            "发放人",
            "发放时间",
            "出库流水编号",
            "缺货说明",
            "备注",
        ],
    },
    "stock_operation_batch": {
        "sheet": "库存批量操作",
        "file": "06_库存批量操作_stock_operation_batch.xlsx",
        "source": "新增飞书表",
        "headers": [
            "批次号",
            "操作类型",
            "操作人",
            "批次状态",
            "总条数",
            "成功条数",
            "失败条数",
            "错误信息",
        ],
    },
}


FIELD_DICTIONARY = {
    "material_categories": [
        ("id", "原系统ID", "bigserial", "text/number", "可选，仅用于追溯旧库 ID；当前迁移源没有真实旧系统 ID。"),
        ("category", "物料品类", "text unique", "text", "物料品类名称，唯一。"),
        ("no_model", "是否无需型号", "boolean", "single_select/checkbox", "是/否。"),
        ("created_at", "创建时间", "timestamptz", "datetime", "旧库创建时间；没有历史值时可留空。"),
    ],
    "inventory_items": [
        ("material_code", "物料编码", "text unique", "text", "如 MAT-0001，建议设为唯一字段。"),
        ("category", "物料品类", "text", "link/single_select/text", "关联或对应物料品类。"),
        ("model", "产品型号", "text", "single_select/text", "无型号品类填“无需型号”。"),
        ("language", "语种", "text", "single_select/text", "物料语言。"),
        ("quantity", "当前库存", "integer", "number", "迁移时点库存。"),
        ("remark", "备注", "new", "text", "按当前飞书物料主数据格式预留，现有库存源无对应字段。"),
        ("unit_price", "单价", "numeric", "currency/number", "当前系统单价。"),
        ("customs_code", "海关编码", "new", "text", "按当前飞书物料主数据格式预留，现有库存源无对应字段。"),
    ],
    "inventory_transactions": [
        ("id", "原系统ID", "bigserial", "text/number", "可选，仅用于追溯旧库 ID。"),
        ("created_at", "发生时间", "timestamptz", "datetime", "流水发生时间。"),
        ("action", "流水类型", "text", "single_select", "物料领取、物料采购、盘点设为、撤回等。"),
        ("category/model/language", "物料组合", "text", "link/text", "用于定位物料主数据。"),
        ("quantity", "数量", "integer", "number", "原流水数量。"),
        ("before_quantity", "变更前数量", "integer", "number", "变更前库存。"),
        ("after_quantity", "变更后数量", "integer", "number", "变更后库存。"),
        ("note", "备注", "text", "long_text", "操作说明。"),
        ("reversed_at", "撤回时间", "timestamptz", "datetime", "原流水被撤回的时间。"),
        ("reversal_of", "原流水ID", "bigint", "link/text", "冲销流水对应的原流水。"),
    ],
    "material_request": [
        ("request_no", "申请单号", "new", "auto_number/text", "销售申请主单编号。"),
        ("requester", "申请人", "new", "user", "销售申请人。"),
        ("business_type", "业务类型", "new", "single_select", "物料领取/物料采购/盘点调整。"),
        ("material_usage", "物料用途", "new", "text", "整张申请单的物料用途或活动名称。"),
        ("request_status", "审批状态", "new", "single_select", "草稿、待审批、待发放、已发放等。"),
    ],
    "material_request_line": [
        ("line_no", "明细编号", "new", "auto_number/text", "申请明细编号。"),
        ("request", "所属申请单", "new", "link", "关联物料申请单。"),
        ("material", "物料编码/物料名称", "new", "link", "关联物料主数据。"),
        ("request_qty", "申请数量", "new", "number", "销售申请数量。"),
        ("approved_qty", "审批通过数量", "new", "number", "市场审批通过数量。"),
        ("actual_issue_qty", "实际发放数量", "new", "number", "最终发放并扣库存的数量。"),
        ("actual_material_code", "实际发放物料编码", "new", "text", "管理员最终发放的物料编码。"),
        ("actual_category", "实际发放物料品类", "new", "text", "管理员最终发放的物料品类。"),
        ("actual_model", "实际发放产品型号", "new", "text", "管理员最终发放的产品型号。"),
        ("actual_language", "实际发放语种", "new", "text", "管理员最终发放的语种。"),
        ("remark", "备注", "new", "text", "单条明细备注，可留空。"),
        ("ledger", "出库流水编号", "new", "link", "关联库存流水。"),
    ],
    "stock_operation_batch": [
        ("batch_no", "批次号", "new", "auto_number/text", "批量发放/入库/撤回批次。"),
        ("operation_type", "操作类型", "new", "single_select", "批量发放/批量入库/批量撤回。"),
        ("batch_status", "批次状态", "new", "single_select", "草稿/处理中/成功/部分成功/失败。"),
        ("error_message", "错误信息", "new", "long_text", "批处理失败原因。"),
    ],
}


SELECT_OPTIONS = {
    "是否无需型号": ["是", "否"],
    "启用状态": ["启用", "停用"],
    "业务类型": ["物料领取", "物料采购", "盘点调整"],
    "审批状态": ["草稿", "待审批", "审批中", "已通过", "已驳回", "待发放", "部分发放", "已发放", "已取消"],
    "明细状态": ["待审批", "待发放", "部分发放", "已发放", "缺货", "取消"],
    "流水类型": ["物料领取（减少库存）", "物料采购（增加库存）", "入库增加", "出库减少", "盘点设为", "撤回"],
    "操作状态": ["有效", "已撤回", "冲销记录"],
    "操作类型": ["批量发放", "批量入库", "批量撤回"],
    "批次状态": ["草稿", "处理中", "成功", "部分成功", "失败"],
}


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def to_int(value: object) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def to_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def normalize_bool(value: object) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    text = clean(value).lower()
    return "是" if text in {"true", "1", "yes", "y", "是"} else "否"


def load_options() -> dict:
    if not OPTIONS_JSON.exists():
        return {"no_model_products": []}
    return json.loads(OPTIONS_JSON.read_text(encoding="utf-8"))


def read_inventory_rows() -> list[dict[str, object]]:
    if INVENTORY_XLSX.exists():
        wb = load_workbook(INVENTORY_XLSX, data_only=True)
        ws = wb.active
        headers = [clean(cell.value) for cell in ws[1]]
        records: list[dict[str, object]] = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(cell not in (None, "") for cell in row):
                continue
            record = dict(zip(headers, row))
            records.append(
                {
                    key: record.get(source_header, "")
                    for key, source_header in SOURCE_INVENTORY_HEADERS.items()
                }
            )
        return records

    if INVENTORY_CSV.exists():
        with INVENTORY_CSV.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            return [
                {
                    key: row.get(source_header, "")
                    for key, source_header in SOURCE_INVENTORY_HEADERS.items()
                }
                for row in reader
            ]

    raise FileNotFoundError(f"缺少库存源文件: {INVENTORY_XLSX} 或 {INVENTORY_CSV}")


def read_transaction_rows() -> list[dict[str, object]]:
    if not TRANSACTIONS_CSV.exists():
        return []
    with TRANSACTIONS_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [
            {
                key: row.get(source_header, "")
                for key, source_header in SOURCE_TRANSACTION_HEADERS.items()
            }
            for row in reader
            if any(clean(value) for value in row.values())
        ]


def build_material_code_map(inventory_rows: list[dict[str, object]]) -> dict[tuple[str, str, str], str]:
    result: dict[tuple[str, str, str], str] = {}
    for row in inventory_rows:
        key = (clean(row["category"]), clean(row["model"]) or NO_MODEL_TEXT, clean(row["language"]))
        result[key] = clean(row["material_code"])
    return result


def build_table_rows() -> dict[str, list[list[object]]]:
    options = load_options()
    inventory_source = read_inventory_rows()
    transaction_source = read_transaction_rows()
    no_model_products = set(options.get("no_model_products", []))
    material_code_map = build_material_code_map(inventory_source)

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in inventory_source:
        grouped[clean(row["category"])].append(row)

    category_rows: list[list[object]] = []
    categories = unique(list(options.get("products", [])) + [clean(row["category"]) for row in inventory_source])
    for category in categories:
        rows = grouped.get(category, [])
        models = unique([clean(row["model"]) or NO_MODEL_TEXT for row in rows])
        languages = unique([clean(row["language"]) for row in rows])
        no_model = category in no_model_products or (bool(models) and all(model == NO_MODEL_TEXT for model in models))
        category_rows.append(
            [
                "",
                category,
                "是" if no_model else "否",
                "启用",
                len(rows),
                len(models),
                len(languages),
                "",
                "",
            ]
        )

    inventory_rows: list[list[object]] = []
    for row in inventory_source:
        category = clean(row["category"])
        model = clean(row["model"]) or NO_MODEL_TEXT
        language = clean(row["language"])
        quantity = to_int(row["quantity"])
        unit_price = to_float(row["unit_price"])
        inventory_rows.append(
            [
                clean(row["material_code"]),
                category,
                model,
                language,
                quantity,
                "",
                unit_price,
                "",
            ]
        )

    transaction_rows: list[list[object]] = []
    for index, row in enumerate(transaction_source, start=1):
        category = clean(row["category"])
        model = clean(row["model"]) or NO_MODEL_TEXT
        language = clean(row["language"])
        before_quantity = to_int(row["before_quantity"])
        after_quantity = to_int(row["after_quantity"])
        action = clean(row["action"])
        transaction_rows.append(
            [
                "",
                clean(row["created_at"]),
                action,
                material_code_map.get((category, model, language), ""),
                category,
                model,
                language,
                to_int(row["quantity"]),
                before_quantity,
                after_quantity,
                after_quantity - before_quantity,
                f"legacy:{index:06d}",
                "",
                "有效",
                "",
                "",
                clean(row["note"]),
            ]
        )

    return {
        "material_categories": category_rows,
        "inventory_items": inventory_rows,
        "inventory_transactions": transaction_rows,
        "material_request": [],
        "material_request_line": [],
        "stock_operation_batch": [],
    }


def add_validations(ws, headers: list[str], row_count: int) -> None:
    max_row = 1048576
    for col_idx, header in enumerate(headers, start=1):
        options = SELECT_OPTIONS.get(header)
        if not options:
            continue
        formula = '"' + ",".join(options) + '"'
        validation = DataValidation(type="list", formula1=formula, allow_blank=True)
        ws.add_data_validation(validation)
        column_letter = get_column_letter(col_idx)
        validation.add(f"{column_letter}2:{column_letter}{max_row}")


def format_sheet(ws, headers: list[str], rows: list[list[object]], table_name: str) -> None:
    ws.append(headers)
    for row in rows:
        ws.append(row)

    header_fill = PatternFill("solid", fgColor="155E75")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for index, header in enumerate(headers, start=1):
        max_len = max([len(str(header))] + [len(str(row[index - 1])) for row in rows[:200] if index <= len(row)])
        width = min(max(max_len + 2, 12), 42)
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width

    for row_idx in range(2, ws.max_row + 1):
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row_idx, col_idx)
            if header in {"当前库存", "库存行数", "产品型号数量", "语种数量", "数量", "变更前数量", "变更后数量", "库存变化", "申请数量", "审批通过数量", "实际发放数量", "总条数", "成功条数", "失败条数"}:
                cell.number_format = "0"
            elif header in {"单价", "库存总价值"}:
                cell.number_format = "0.00"

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    add_validations(ws, headers, len(rows))

    if rows:
        table_ref = f"A1:{ws.cell(ws.max_row, len(headers)).coordinate}"
        table = Table(displayName=table_name, ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(table)


def save_single_table(path: Path, sheet_name: str, headers: list[str], rows: list[list[object]], table_name: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    format_sheet(ws, headers, rows, table_name)
    wb.save(path)


def save_combined_workbook(path: Path, table_rows: dict[str, list[list[object]]]) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for index, (table_key, info) in enumerate(TABLES.items(), start=1):
        ws = wb.create_sheet(str(info["sheet"]))
        format_sheet(ws, list(info["headers"]), table_rows[table_key], f"Table{index:02d}")
    wb.save(path)


def save_field_dictionary(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "字段字典"
    headers = ["表API", "表名", "来源", "字段API/来源", "字段名", "原类型", "飞书建议类型", "说明"]
    ws.append(headers)
    for table_key, fields in FIELD_DICTIONARY.items():
        info = TABLES[table_key]
        for field in fields:
            ws.append([table_key, info["sheet"], info["source"], *field])
    format_dictionary_sheet(ws)
    wb.save(path)


def format_dictionary_sheet(ws) -> None:
    header_fill = PatternFill("solid", fgColor="334155")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = [24, 18, 34, 22, 20, 18, 22, 72]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    table_rows = build_table_rows()

    for index, (table_key, info) in enumerate(TABLES.items(), start=1):
        save_single_table(
            OUTPUT_DIR / str(info["file"]),
            str(info["sheet"]),
            list(info["headers"]),
            table_rows[table_key],
            f"SingleTable{index:02d}",
        )

    save_combined_workbook(OUTPUT_DIR / "飞书多维表格数据库_六表合并.xlsx", table_rows)
    save_field_dictionary(OUTPUT_DIR / "飞书多维表格_字段字典.xlsx")

    summary = {
        table_key: {
            "sheet": TABLES[table_key]["sheet"],
            "file": TABLES[table_key]["file"],
            "rows": len(rows),
            "source": TABLES[table_key]["source"],
        }
        for table_key, rows in table_rows.items()
    }
    (OUTPUT_DIR / "生成摘要.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"输出目录: {OUTPUT_DIR}")
    for table_key, item in summary.items():
        print(f"{table_key}: {item['rows']} rows -> {item['file']}")


if __name__ == "__main__":
    main()
