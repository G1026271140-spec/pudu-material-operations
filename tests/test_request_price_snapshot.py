import unittest
from unittest.mock import patch

import app


class RequestPriceSnapshotTests(unittest.TestCase):
    def test_number_field_normalization_does_not_truncate_decimal_price(self) -> None:
        with patch.object(app, "feishu_field_type", return_value=2):
            self.assertEqual(
                app.normalize_feishu_field_value(app.MATERIAL_TABLE_NAME, "单价（美元）", 0.06),
                0.06,
            )

    def test_request_subtotal_uses_frozen_rmb_price(self) -> None:
        self.assertEqual(app.request_line_subtotal_rmb(6.77, 3), 20.31)
        self.assertEqual(app.request_line_subtotal_rmb(0.4062, 100), 40.62)

    def test_material_price_prefers_material_formula_value(self) -> None:
        with patch.object(app, "feishu_float", return_value=13.54):
            self.assertEqual(app.request_material_unit_price_rmb({}, 6.77), 13.54)

    def test_material_price_falls_back_to_category_rmb_value(self) -> None:
        with patch.object(app, "feishu_float", return_value=0.0):
            self.assertEqual(app.request_material_unit_price_rmb({}, 6.77), 6.77)

    def test_material_source_price_sync_uses_linked_category_usd(self) -> None:
        material_rows = [
            {
                "record_id": "mat-1",
                "fields": {"品类关联": [{"record_id": "cat-1"}], "单价（美元）": 1.0},
            }
        ]
        category_rows = [
            {"record_id": "cat-1", "fields": {"单价（美元）": 2.0}}
        ]
        with (
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "feishu_accepts_plain_value", return_value=True),
        ):
            updates = app.material_price_sync_updates(material_rows, category_rows)

        self.assertEqual(
            updates,
            [{"record_id": "mat-1", "fields": {"单价（美元）": 2.0}}],
        )


if __name__ == "__main__":
    unittest.main()
