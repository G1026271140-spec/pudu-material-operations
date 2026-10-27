from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import PatternFill
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from country_codes import COUNTRY_CODE_ALIASES, COUNTRY_CODES


TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "shipping" / "骏博发货模板.xlsx"
DEFAULT_PRODUCT_MODEL = "sample items no commercial Value, Custom purpose only"
DEFAULT_PAYMENT_TERM = "Free of Charge,No commercial Value, Custom purpose only"
DEFAULT_SHIPPING_COST = Decimal("100.00")


@dataclass(frozen=True)
class InvoicePricing:
    original_total: Decimal
    shipping_cost: Decimal
    goods_unit_prices: tuple[Decimal, ...]
    goods_amounts: tuple[Decimal, ...]

    @property
    def goods_total(self) -> Decimal:
        return sum(self.goods_amounts, Decimal("0.00"))


def invoice_pricing(lines: Iterable[ShippingLine], shipping_cost: object = DEFAULT_SHIPPING_COST) -> InvoicePricing:
    """Extract freight from the existing invoice value, never add it on top."""
    line_list = list(lines)
    try:
        freight = Decimal(str(shipping_cost))
        raw_amounts = [Decimal(str(line.unit_price)) * int(line.quantity) for line in line_list]
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise ValueError("运费及货物单价必须为有效数字。") from exc
    if not freight.is_finite() or freight < 0 or any(not n.is_finite() or n < 0 for n in raw_amounts):
        raise ValueError("运费及货物金额必须为非负有限数字。")
    freight = freight.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    raw_total = sum(raw_amounts, Decimal(0))
    original_total = raw_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if freight > original_total:
        raise ValueError(f"货物原总值为 {original_total:.2f} 美元，不足以扣出 {freight:.2f} 美元运费，请调整运费或货物单价。")
    # Unit prices in an invoice must be payable cents. Allocate freight in
    # proportion to the original goods values, then round *unit* prices.
    target = original_total - freight
    units = []
    for line, original in zip(line_list, raw_amounts):
        quantity = int(line.quantity)
        if quantity <= 0:
            raise ValueError("货物数量必须大于零。")
        ideal_unit = (target * original / raw_total / quantity) if raw_total else Decimal(0)
        units.append(ideal_unit.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    # A one-cent unit adjustment can improve the invoice total without adding
    # fractions of a cent to the displayed price. Stop when no move improves it.
    gap = target - sum((unit * int(line.quantity) for unit, line in zip(units, line_list)), Decimal(0))
    while gap:
        choices = []
        for index, line in enumerate(line_list):
            step = Decimal(int(line.quantity)) / 100
            if gap < 0 and units[index] == 0:
                continue
            improvement = abs(gap) - abs(gap - (step if gap > 0 else -step))
            if improvement > 0:
                choices.append((improvement, -index, index, step))
        if not choices:
            break
        _, _, index, step = max(choices)
        units[index] += Decimal('0.01') if gap > 0 else Decimal('-0.01')
        gap += -step if gap > 0 else step
    amounts = tuple(unit * int(line.quantity) for unit, line in zip(units, line_list))
    return InvoicePricing(original_total, freight, tuple(units), amounts)

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


def infer_address_code(address: object) -> str:
    normalized = str(address or "").strip().casefold()
    if not normalized:
        return ""
    compact_code = re.sub(r"[^A-Za-z]", "", normalized).upper()
    if len(normalized) <= 5 and compact_code in COUNTRY_CODES:
        return compact_code
    matches = [
        (len(alias), code)
        for alias, code in COUNTRY_CODE_ALIASES.items()
        if _country_alias_matches(normalized, alias)
    ]
    return max(matches, default=(0, ""))[1]


def _country_alias_matches(normalized: str, alias: str) -> bool:
    if alias.isascii():
        return re.search(
            rf"(?<![a-z]){re.escape(alias)}(?![a-z])",
            normalized,
        ) is not None
    return alias in normalized


def normalize_address_code(value: object) -> str:
    inferred_code = infer_address_code(value)
    if inferred_code:
        return inferred_code
    code = re.sub(r"[^A-Za-z0-9]", "", str(value or "").upper())
    return code[:8]


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


def _write_invoice(ws: Worksheet, lines: list[ShippingLine], pricing: InvoicePricing) -> None:
    start_row, end_row = _prepare_detail_rows(
        ws,
        template_start=16,
        template_end=23,
        desired_count=len(lines) + 1,
        max_col=7,
    )
    for index, (row, line) in enumerate(zip(range(start_row, end_row), lines)):
        ws.cell(row, 1, line.sku or "/")
        ws.cell(row, 2, line.invoice_name)
        ws.cell(row, 3, line.packing_type)
        ws.cell(row, 4, line.product_model or DEFAULT_PRODUCT_MODEL)
        ws.cell(row, 5, int(line.quantity))
        ws.cell(row, 6, float(pricing.goods_unit_prices[index]))
        ws.cell(row, 7, f"=ROUND(E{row}*F{row},2)" if pricing.shipping_cost else f"=E{row}*F{row}")
        ws.cell(row, 5).number_format = "#,##0"
        ws.cell(row, 6).number_format = "0.00"
        ws.cell(row, 7).number_format = "0.00"
    # Freight is an invoice-only service line, not a physical packing item.
    for col, value in enumerate(("/", "Shipping Cost", "N/A", "N/A", 1, float(pricing.shipping_cost), f"=E{end_row}*F{end_row}"), start=1):
        ws.cell(end_row, col, value)
    ws.cell(end_row, 5).number_format = "#,##0"
    ws.cell(end_row, 6).number_format = "0.000"
    ws.cell(end_row, 7).number_format = "0.00"
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


def _clear_workbook_fills(workbook: Workbook) -> None:
    empty_fill = PatternFill()
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                cell.fill = copy(empty_fill)


def generate_shipping_workbook(
    *,
    template_date: date,
    address_code: object,
    recipient: dict[str, object],
    lines: Iterable[ShippingLine],
    cartons: Iterable[Carton],
    allocations: Iterable[CartonAllocation],
    template_path: Path = TEMPLATE_PATH,
    shipping_cost: object = DEFAULT_SHIPPING_COST,
) -> tuple[str, bytes]:
    line_list = list(lines)
    carton_list = list(cartons)
    allocation_list = list(allocations)
    validate_shipping_data(line_list, carton_list, allocation_list)
    pricing = invoice_pricing(line_list, shipping_cost)
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
    _write_invoice(invoice_sheet, line_list, pricing)
    _write_packing_list(packing_sheet, line_list, carton_list, allocation_list)
    _clear_workbook_fills(workbook)
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    output = BytesIO()
    workbook.save(output)
    return invoice_number, output.getvalue()
