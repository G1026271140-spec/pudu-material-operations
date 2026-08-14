from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.worksheet import Worksheet


TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "shipping" / "骏博发货模板.xlsx"
DEFAULT_PRODUCT_MODEL = "sample items no commercial Value, Custom purpose only"
DEFAULT_PAYMENT_TERM = "Free of Charge,No commercial Value, Custom purpose only"

COUNTRY_CODE_ALIASES = {
    "中国": "CN", "china": "CN", "香港": "HK", "hong kong": "HK", "澳门": "MO", "macao": "MO",
    "台湾": "TW", "taiwan": "TW", "美国": "US", "美利坚": "US", "united states": "US", "usa": "US",
    "加拿大": "CA", "canada": "CA", "墨西哥": "MX", "mexico": "MX", "巴西": "BR", "brazil": "BR",
    "阿根廷": "AR", "argentina": "AR", "智利": "CL", "chile": "CL", "秘鲁": "PE", "peru": "PE",
    "哥伦比亚": "CO", "colombia": "CO", "英国": "GB", "united kingdom": "GB", "england": "GB",
    "法国": "FR", "france": "FR", "德国": "DE", "germany": "DE", "意大利": "IT", "italy": "IT",
    "西班牙": "ES", "spain": "ES", "葡萄牙": "PT", "portugal": "PT", "荷兰": "NL", "netherlands": "NL",
    "比利时": "BE", "belgium": "BE", "瑞士": "CH", "switzerland": "CH", "奥地利": "AT", "austria": "AT",
    "波兰": "PL", "poland": "PL", "捷克": "CZ", "czech": "CZ", "匈牙利": "HU", "hungary": "HU",
    "罗马尼亚": "RO", "romania": "RO", "希腊": "GR", "greece": "GR", "瑞典": "SE", "sweden": "SE",
    "挪威": "NO", "norway": "NO", "丹麦": "DK", "denmark": "DK", "芬兰": "FI", "finland": "FI",
    "爱尔兰": "IE", "ireland": "IE", "俄罗斯": "RU", "russia": "RU", "乌克兰": "UA", "ukraine": "UA",
    "土耳其": "TR", "turkey": "TR", "阿联酋": "AE", "united arab emirates": "AE", "uae": "AE",
    "沙特": "SA", "saudi arabia": "SA", "以色列": "IL", "israel": "IL", "埃及": "EG", "egypt": "EG",
    "南非": "ZA", "south africa": "ZA", "尼日利亚": "NG", "nigeria": "NG", "肯尼亚": "KE", "kenya": "KE",
    "印度": "IN", "india": "IN", "巴基斯坦": "PK", "pakistan": "PK", "孟加拉": "BD", "bangladesh": "BD",
    "日本": "JP", "japan": "JP", "韩国": "KR", "south korea": "KR", "korea": "KR",
    "新加坡": "SG", "singapore": "SG", "马来西亚": "MY", "malaysia": "MY", "泰国": "TH", "thailand": "TH",
    "越南": "VN", "vietnam": "VN", "印度尼西亚": "ID", "indonesia": "ID", "印尼": "ID",
    "菲律宾": "PH", "philippines": "PH", "澳大利亚": "AU", "australia": "AU", "新西兰": "NZ", "new zealand": "NZ",
}


@dataclass(frozen=True)
class ShippingLine:
    line_id: str
    invoice_name: str
    packing_name: str
    packing_type: str
    quantity: int
    unit_price: float
    customs_code: str
    product_model: str = DEFAULT_PRODUCT_MODEL
    sku: str = "/"


@dataclass(frozen=True)
class Carton:
    carton_no: int
    carton_quantity: int
    net_weight: float
    gross_weight: float
    length_cm: float
    width_cm: float
    height_cm: float
    cbm_override: float | None = None

    @property
    def dimension_text(self) -> str:
        return "*".join(_compact_number(value) for value in (self.length_cm, self.width_cm, self.height_cm))

    @property
    def cbm(self) -> float:
        if self.cbm_override is not None:
            return float(self.cbm_override)
        return float(self.length_cm * self.width_cm * self.height_cm / 1_000_000)


@dataclass(frozen=True)
class CartonAllocation:
    carton_no: int
    line_id: str
    quantity: int


def _compact_number(value: object) -> str:
    number = float(value or 0)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def normalize_address_code(value: object) -> str:
    code = re.sub(r"[^A-Za-z0-9]", "", str(value or "").upper())
    return code[:8]


def infer_address_code(address: object) -> str:
    normalized = str(address or "").strip().lower()
    if not normalized:
        return ""
    matches = [
        (len(alias), code)
        for alias, code in COUNTRY_CODE_ALIASES.items()
        if alias.lower() in normalized
    ]
    return max(matches, default=(0, ""))[1]


def build_invoice_number(template_date: date, address_code: object) -> str:
    code = normalize_address_code(address_code)
    if not code:
        raise ValueError("收货地址英文缩写不能为空。")
    return f"{template_date:%Y}-MKT-{code}{template_date:%m%d}"


def validate_shipping_data(
    lines: Iterable[ShippingLine],
    cartons: Iterable[Carton],
    allocations: Iterable[CartonAllocation],
) -> None:
    line_list = list(lines)
    carton_list = list(cartons)
    allocation_list = list(allocations)
    if not line_list:
        raise ValueError("请至少填写一条发票物料明细。")
    if not carton_list:
        raise ValueError("请至少填写一个纸箱。")

    line_by_id = {line.line_id: line for line in line_list}
    carton_by_no = {carton.carton_no: carton for carton in carton_list}
    if len(line_by_id) != len(line_list):
        raise ValueError("发票明细标识重复。")
    if len(carton_by_no) != len(carton_list):
        raise ValueError("箱号重复。")

    for carton in carton_list:
        missing_fields = [
            label
            for label, value in (
                ("长", carton.length_cm),
                ("宽", carton.width_cm),
                ("高", carton.height_cm),
                ("毛重", carton.gross_weight),
            )
            if float(value) <= 0
        ]
        if missing_fields:
            raise ValueError(
                f"箱子 {carton.carton_no:02d} 请填写必填项："
                + "、".join(missing_fields)
            )
        if float(carton.net_weight) <= 0:
            raise ValueError(
                f"箱子 {carton.carton_no:02d} 的毛重必须大于自动估算的包材重量。"
            )
        if float(carton.net_weight) >= float(carton.gross_weight):
            raise ValueError(f"箱子 {carton.carton_no:02d} 的净重必须小于毛重。")

    allocated_by_line = {line.line_id: 0 for line in line_list}
    used_cartons: set[int] = set()
    for allocation in allocation_list:
        if allocation.line_id not in line_by_id:
            raise ValueError(f"箱内分配引用了不存在的发票明细：{allocation.line_id}")
        if allocation.carton_no not in carton_by_no:
            raise ValueError(f"箱内分配引用了不存在的箱号：{allocation.carton_no}")
        if int(allocation.quantity) <= 0:
            raise ValueError("箱内分配数量必须大于 0。")
        allocated_by_line[allocation.line_id] += int(allocation.quantity)
        used_cartons.add(allocation.carton_no)

    for line in line_list:
        if not line.invoice_name.strip():
            raise ValueError("商业发票产品名称不能为空。")
        if int(line.quantity) <= 0:
            raise ValueError(f"{line.invoice_name} 的数量必须大于 0。")
        if allocated_by_line[line.line_id] != int(line.quantity):
            raise ValueError(
                f"{line.invoice_name} 的发票数量为 {line.quantity}，"
                f"各箱分配合计为 {allocated_by_line[line.line_id]}。"
            )
    unused_cartons = sorted(set(carton_by_no) - used_cartons)
    if unused_cartons:
        raise ValueError("以下纸箱没有分配物料：" + "、".join(map(str, unused_cartons)))


def _copy_row_style(ws: Worksheet, source_row: int, target_row: int, min_col: int, max_col: int) -> None:
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(min_col, max_col + 1):
        source = ws.cell(source_row, col)
        target = ws.cell(target_row, col)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.protection:
            target.protection = copy(source.protection)


def _remove_merges_in_rows(ws: Worksheet, start_row: int, end_row: int) -> None:
    for merged in list(ws.merged_cells.ranges):
        if merged.max_row >= start_row and merged.min_row <= end_row:
            ws.unmerge_cells(str(merged))


def _prepare_detail_rows(
    ws: Worksheet,
    *,
    template_start: int,
    template_end: int,
    desired_count: int,
    max_col: int,
) -> tuple[int, int]:
    desired_count = max(1, int(desired_count))
    template_count = template_end - template_start + 1
    _remove_merges_in_rows(ws, template_start, ws.max_row)
    if desired_count > template_count:
        ws.insert_rows(template_end + 1, desired_count - template_count)
    elif desired_count < template_count:
        ws.delete_rows(template_start + desired_count, template_count - desired_count)
    end_row = template_start + desired_count - 1
    for row in range(template_start, end_row + 1):
        _copy_row_style(ws, template_start, row, 1, max_col)
        for col in range(1, max_col + 1):
            cell = ws.cell(row, col)
            if not isinstance(cell, MergedCell):
                cell.value = None
    return template_start, end_row


def _write_shared_header(
    ws: Worksheet,
    *,
    invoice_number: str,
    recipient: dict[str, object],
    invoice_date: date,
    packing_list: bool,
) -> None:
    ws["A2"] = f"Invoice Number#:  {invoice_number}"
    for cell, key in (
        ("B5", "contact"),
        ("B6", "company"),
        ("B7", "address"),
        ("B8", "postal_code"),
        ("B9", "phone"),
        ("B10", "email"),
        ("B11", "delivery_term"),
    ):
        ws[cell] = str(recipient.get(key) or "")
    if packing_list:
        ws["E11"] = datetime.combine(invoice_date, datetime.min.time())
        ws["E12"] = invoice_number
    else:
        ws["D11"] = datetime.combine(invoice_date, datetime.min.time())
        ws["B12"] = str(recipient.get("payment_term") or DEFAULT_PAYMENT_TERM)


def _write_invoice(ws: Worksheet, lines: list[ShippingLine]) -> None:
    start_row, end_row = _prepare_detail_rows(
        ws,
        template_start=16,
        template_end=23,
        desired_count=len(lines),
        max_col=7,
    )
    for row, line in zip(range(start_row, end_row + 1), lines):
        ws.cell(row, 1, line.sku or "/")
        ws.cell(row, 2, line.invoice_name)
        ws.cell(row, 3, line.packing_type)
        ws.cell(row, 4, line.product_model or DEFAULT_PRODUCT_MODEL)
        ws.cell(row, 5, int(line.quantity))
        ws.cell(row, 6, float(line.unit_price))
        ws.cell(row, 7, f"=E{row}*F{row}")
        ws.cell(row, 5).number_format = "#,##0"
        ws.cell(row, 6).number_format = "0.000"
        ws.cell(row, 7).number_format = "0.00"
    total_row = end_row + 1
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=6)
    ws.cell(total_row, 7, f"=SUM(G{start_row}:G{end_row})")
    ws.cell(total_row, 7).number_format = "0.00"


def _packing_rows(
    lines: list[ShippingLine],
    cartons: list[Carton],
    allocations: list[CartonAllocation],
) -> list[tuple[Carton, ShippingLine, int]]:
    line_by_id = {line.line_id: line for line in lines}
    carton_by_no = {carton.carton_no: carton for carton in cartons}
    rows = [
        (carton_by_no[allocation.carton_no], line_by_id[allocation.line_id], int(allocation.quantity))
        for allocation in allocations
    ]
    rows.sort(key=lambda item: (item[0].carton_no, lines.index(item[1])))
    return rows


def _write_packing_list(
    ws: Worksheet,
    lines: list[ShippingLine],
    cartons: list[Carton],
    allocations: list[CartonAllocation],
) -> None:
    packing_rows = _packing_rows(lines, cartons, allocations)
    start_row, end_row = _prepare_detail_rows(
        ws,
        template_start=15,
        template_end=22,
        desired_count=len(packing_rows),
        max_col=11,
    )
    carton_ranges: dict[int, list[int]] = {}
    for row, (carton, line, quantity) in zip(range(start_row, end_row + 1), packing_rows):
        carton_ranges.setdefault(carton.carton_no, []).append(row)
        ws.cell(row, 1, carton.carton_no)
        ws.cell(row, 2, line.packing_name or line.invoice_name)
        ws.cell(row, 3, line.packing_type)
        ws.cell(row, 4, line.product_model or DEFAULT_PRODUCT_MODEL)
        ws.cell(row, 5, carton.carton_quantity)
        ws.cell(row, 6, line.customs_code)
        ws.cell(row, 7, quantity)
        ws.cell(row, 8, carton.net_weight)
        ws.cell(row, 9, carton.gross_weight)
        ws.cell(row, 10, carton.dimension_text)
        ws.cell(row, 11, carton.cbm)
        ws.cell(row, 6).number_format = "0"
        ws.cell(row, 7).number_format = "#,##0"
        ws.cell(row, 8).number_format = "0.###"
        ws.cell(row, 9).number_format = "0.###"
        ws.cell(row, 11).number_format = "0.000"

    for row_numbers in carton_ranges.values():
        first, last = min(row_numbers), max(row_numbers)
        if first == last:
            continue
        for col in (1, 5, 8, 9, 10, 11):
            ws.merge_cells(start_row=first, start_column=col, end_row=last, end_column=col)

    total_row = end_row + 1
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=4)
    ws.cell(total_row, 1, "Total :")
    ws.cell(total_row, 5, f"=SUM(E{start_row}:E{end_row})")
    ws.cell(total_row, 7, f"=SUM(G{start_row}:G{end_row})")
    # Merged carton cells ensure each carton contributes to these totals once.
    net_cells = ",".join(f"H{min(rows)}" for rows in carton_ranges.values())
    gross_cells = ",".join(f"I{min(rows)}" for rows in carton_ranges.values())
    cbm_cells = ",".join(f"K{min(rows)}" for rows in carton_ranges.values())
    ws.cell(total_row, 8, f"=SUM({net_cells})")
    ws.cell(total_row, 9, f"=SUM({gross_cells})")
    ws.cell(total_row, 11, f"=SUM({cbm_cells})")
    for col in (5, 7):
        ws.cell(total_row, col).number_format = "#,##0"
    for col in (8, 9):
        ws.cell(total_row, col).number_format = "0.00"
    ws.cell(total_row, 11).number_format = "0.000"


def generate_shipping_workbook(
    *,
    template_date: date,
    address_code: object,
    recipient: dict[str, object],
    lines: Iterable[ShippingLine],
    cartons: Iterable[Carton],
    allocations: Iterable[CartonAllocation],
    template_path: Path = TEMPLATE_PATH,
) -> tuple[str, bytes]:
    line_list = list(lines)
    carton_list = list(cartons)
    allocation_list = list(allocations)
    validate_shipping_data(line_list, carton_list, allocation_list)
    invoice_number = build_invoice_number(template_date, address_code)
    if not template_path.exists():
        raise FileNotFoundError(f"未找到发货模板：{template_path}")

    workbook = load_workbook(template_path)
    invoice_sheet = workbook["INV"]
    packing_sheet = workbook["PL (2)"]
    _write_shared_header(
        invoice_sheet,
        invoice_number=invoice_number,
        recipient=recipient,
        invoice_date=template_date,
        packing_list=False,
    )
    _write_shared_header(
        packing_sheet,
        invoice_number=invoice_number,
        recipient=recipient,
        invoice_date=template_date,
        packing_list=True,
    )
    _write_invoice(invoice_sheet, line_list)
    _write_packing_list(packing_sheet, line_list, carton_list, allocation_list)
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    output = BytesIO()
    workbook.save(output)
    return invoice_number, output.getvalue()
