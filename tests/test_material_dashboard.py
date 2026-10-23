import unittest

import app


def inventory_record(
    record_id: str,
    category: str,
    model: str,
    language: str,
    quantity: int,
    unit_price: float,
) -> dict:
    return {
        "record_id": record_id,
        "material_code": f"MAT-{record_id}",
        "category": category,
        "model": model,
        "language": language,
        "quantity": quantity,
        "unit_price": unit_price,
        "total_value": quantity * unit_price,
    }


class MaterialDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            inventory_record("1", "Brochure", "P1", "English", -5, 2),
            inventory_record("2", "Brochure", "P2", "Chinese", 0, 4),
            inventory_record("3", "Gift", "No model", "No language", 50, 3),
            inventory_record("4", "Gift", "P3", "English", 500, 5),
        ]

    def test_stock_status_respects_negative_zero_and_low_threshold(self) -> None:
        self.assertEqual(app.material_stock_status(-1, 100), "负库存")
        self.assertEqual(app.material_stock_status(0, 100), "零库存")
        self.assertEqual(app.material_stock_status(100, 100), "低库存")
        self.assertEqual(app.material_stock_status(101, 100), "正常库存")

    def test_dashboard_filters_are_shared_with_inventory_details(self) -> None:
        dashboard_df = app.material_dashboard_dataframe(self.records)
        filtered = app.apply_material_dashboard_filters(
            dashboard_df,
            categories=["Gift"],
            models=[],
            languages=[],
            stock_statuses=["低库存"],
            low_stock_threshold=100,
        )

        self.assertEqual(filtered["记录ID"].tolist(), ["3"])
        self.assertEqual(filtered["库存状态"].tolist(), ["低库存"])

    def test_dashboard_summary_and_category_grouping_include_negative_stock(self) -> None:
        dashboard_df = app.material_dashboard_dataframe(self.records)
        summary = app.material_dashboard_summary(dashboard_df)
        grouped = app.material_dashboard_grouped_data(
            dashboard_df,
            "物料品类",
            "库存数量",
        )

        self.assertEqual(summary["combination_count"], 4)
        self.assertEqual(summary["quantity_sum"], 545)
        self.assertEqual(summary["total_value"], 2640.0)
        self.assertEqual(summary["negative_count"], 1)
        self.assertEqual(summary["zero_count"], 1)
        self.assertEqual(
            dict(zip(grouped["物料品类"], grouped["库存数量"])),
            {"Gift": 550, "Brochure": -5},
        )


if __name__ == "__main__":
    unittest.main()
