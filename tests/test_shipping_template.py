from __future__ import annotations

import unittest
from datetime import date
from io import BytesIO

from openpyxl import load_workbook

from shipping_template import (
    Carton,
    CartonAllocation,
    ShippingLine,
    build_invoice_number,
    generate_shipping_workbook,
    infer_address_code,
    validate_shipping_data,
)


class ShippingTemplateTests(unittest.TestCase):
    def test_invoice_number_uses_year_code_and_template_date(self) -> None:
        self.assertEqual(build_invoice_number(date(2026, 8, 13), " mx "), "2026-MKT-MX0813")
        self.assertEqual(infer_address_code("墨西哥城客户仓库"), "MX")
        self.assertEqual(infer_address_code("Paris, France"), "FR")

    def test_validation_supports_many_products_per_carton_and_product_split(self) -> None:
        lines = [
            ShippingLine("L1", "Flyers", "Flyers", "flyers", 10, 0.06, "4911101000"),
            ShippingLine("L2", "Doll", "Doll", "give aways", 5, 1.6, "9503002100"),
        ]
        cartons = [
            Carton(1, 1, 2, 3, 40, 30, 20),
            Carton(2, 1, 1, 2, 20, 20, 20),
        ]
        allocations = [
            CartonAllocation(1, "L1", 6),
            CartonAllocation(1, "L2", 5),
            CartonAllocation(2, "L1", 4),
        ]
        validate_shipping_data(lines, cartons, allocations)

    def test_validation_rejects_quantity_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "各箱分配合计"):
            validate_shipping_data(
                [ShippingLine("L1", "Flyers", "Flyers", "flyers", 10, 0.06, "4911101000")],
                [Carton(1, 1, 2, 3, 40, 30, 20)],
                [CartonAllocation(1, "L1", 9)],
            )

    def test_generated_workbook_expands_rows_and_keeps_carton_groups(self) -> None:
        lines = [
            ShippingLine(f"L{index}", f"Invoice {index}", f"Packing {index}", "type", 2, 1.5, "123456")
            for index in range(1, 10)
        ]
        cartons = [Carton(1, 1, 10, 12, 50, 40, 30)]
        allocations = [CartonAllocation(1, line.line_id, 2) for line in lines]
        invoice_number, data = generate_shipping_workbook(
            template_date=date(2026, 8, 13),
            address_code="US",
            recipient={"contact": "A"},
            lines=lines,
            cartons=cartons,
            allocations=allocations,
        )
        workbook = load_workbook(BytesIO(data), data_only=False)
        self.assertEqual(invoice_number, "2026-MKT-US0813")
        self.assertEqual(workbook["INV"]["B24"].value, "Invoice 9")
        self.assertEqual(workbook["INV"]["G25"].value, "=SUM(G16:G24)")
        self.assertIn("A15:A23", {str(value) for value in workbook["PL (2)"].merged_cells.ranges})
        self.assertEqual(workbook["PL (2)"]["G24"].value, "=SUM(G15:G23)")

    def test_generated_workbook_calculates_cbm_and_invoice_amounts(self) -> None:
        _, data = generate_shipping_workbook(
            template_date=date(2026, 8, 13),
            address_code="MX",
            recipient={"contact": "A", "address": "Mexico"},
            lines=[ShippingLine("L1", "Flyer", "Flyer", "Flyers", 10, 0.06, "4911101000")],
            cartons=[Carton(1, 1, 2, 3, 50, 40, 30)],
            allocations=[CartonAllocation(1, "L1", 10)],
        )
        workbook = load_workbook(BytesIO(data), data_only=False)

        self.assertEqual(workbook["INV"]["G16"].value, "=E16*F16")
        self.assertEqual(workbook["PL (2)"]["K15"].value, 0.06)
        self.assertEqual(workbook["PL (2)"]["K16"].value, "=SUM(K15)")
        self.assertEqual(workbook["PL (2)"]["H16"].number_format, "0.00")
        self.assertEqual(workbook["PL (2)"]["I16"].number_format, "0.00")
        self.assertEqual(workbook["PL (2)"]["K16"].number_format, "0.000")


if __name__ == "__main__":
    unittest.main()
