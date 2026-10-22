from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

import pytest
from openpyxl import load_workbook

from shipping_template import Carton, CartonAllocation, ShippingLine, generate_shipping_workbook, invoice_pricing


def line(name="Goods", quantity=10, price=100):
    return ShippingLine(name, name, name, "Give aways", quantity, price, "1234", product_model="N/A")


def generate(lines, **kwargs):
    return generate_shipping_workbook(template_date=date(2026, 10, 22), address_code="US",
        recipient={"contact": "Sample"}, lines=lines, cartons=[Carton(1, 1, 2, 3, 40, 30, 20)],
        allocations=[CartonAllocation(1, x.line_id, x.quantity) for x in lines], **kwargs)


def test_default_shipping_is_extracted_not_added():
    pricing = invoice_pricing([line()])
    assert pricing.original_total == Decimal("1000.00")
    assert pricing.shipping_cost == Decimal("100.00")
    assert pricing.goods_total == Decimal("900.00")
    assert pricing.goods_total + pricing.shipping_cost == pricing.original_total


def test_distribution_is_proportional_and_zero_goods_stay_zero():
    pricing = invoice_pricing([line("A", 10, 60), line("B", 10, 40), line("Zero", 1, 0)])
    assert pricing.goods_amounts == (Decimal("540"), Decimal("360"), Decimal("0"))


def test_remainder_is_cent_exact_with_awkward_quantities():
    lines = [line("A", 73, 2.213), line("B", 117, 3.321), line("C", 29, 1.019)]
    pricing = invoice_pricing(lines, "100.01")
    assert pricing.original_total == sum((Decimal(str(x.unit_price))*x.quantity for x in lines)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    assert pricing.goods_total + pricing.shipping_cost == pricing.original_total
    assert all(x >= 0 and x == x.quantize(Decimal(".01")) for x in pricing.goods_amounts)


@pytest.mark.parametrize("cost", [-1, "NaN", "Infinity", None, "invalid"])
def test_invalid_shipping_is_rejected(cost):
    with pytest.raises(ValueError): invoice_pricing([line()], cost)


@pytest.mark.parametrize("price", [-1, float("nan"), float("inf")])
def test_invalid_goods_price_is_rejected(price):
    with pytest.raises(ValueError): invoice_pricing([line(price=price)])


def test_insufficient_goods_value_blocks_instead_of_creating_negative_prices():
    with pytest.raises(ValueError, match="不足以扣出"):
        generate([line(quantity=1, price=99.99)])
    pricing = invoice_pricing([line(quantity=1, price=100)])
    assert pricing.goods_total == 0


def test_zero_shipping_is_a_valid_explicit_override():
    pricing = invoice_pricing([line(quantity=1, price=0)], 0)
    assert pricing.goods_total == pricing.shipping_cost == pricing.original_total == 0


def test_invoice_adds_one_shipping_row_but_packing_is_unchanged():
    lines = [line("A", 73, 2.213), line("B", 117, 3.321)]
    _, data = generate(lines)
    wb = load_workbook(BytesIO(data))
    inv, pl = wb["INV"], wb["PL (2)"]
    assert [inv.cell(18, col).value for col in range(1, 8)] == ["/", "Shipping Cost", "N/A", "N/A", 1, 100, "=E18*F18"]
    assert inv["G19"].value == "=SUM(G16:G18)"
    goods_amount = sum(Decimal(str(round(inv.cell(r, 5).value*inv.cell(r, 6).value, 2))) for r in (16, 17))
    assert goods_amount + 100 == invoice_pricing(lines).original_total
    assert inv["G16"].value == "=ROUND(E16*F16,2)"
    assert pl["B15"].value == "A" and pl["B16"].value == "B"
    assert pl["G17"].value == "=SUM(G15:G16)"
    assert not any(c.value == "Shipping Cost" for row in pl for c in row)
    assert lines[0].unit_price == 2.213  # Caller/master prices are not mutated.


def test_shipping_only_appears_once_after_expanded_goods_rows():
    _, data = generate([line(str(i)) for i in range(12)])
    inv = load_workbook(BytesIO(data))["INV"]
    assert inv["B28"].value == "Shipping Cost"
    assert inv["G29"].value == "=SUM(G16:G28)"


def test_shipping_change_preserves_all_packing_cells_and_formats():
    lines = [line("A", 73, 2.213), line("B", 117, 3.321)]
    snapshots = []
    for cost in (0, 100):
        _, data = generate(lines, shipping_cost=cost)
        sheet = load_workbook(BytesIO(data))["PL (2)"]
        snapshots.append([(cell.coordinate, cell.value, cell.number_format, cell.font.name, cell.font.sz) for row in sheet for cell in row])
    assert snapshots[0] == snapshots[1]


def test_many_rounding_cases_keep_original_invoice_total_to_the_cent():
    import random
    randomizer = random.Random(22)
    for _ in range(200):
        lines = [line(str(i), randomizer.randint(1, 2000), randomizer.randint(0, 40000)/1000) for i in range(9)]
        cost = randomizer.randint(0, 10000)/100
        pricing = invoice_pricing(lines, cost)
        assert pricing.goods_total + pricing.shipping_cost == pricing.original_total
        assert all(x >= 0 for x in pricing.goods_amounts)
