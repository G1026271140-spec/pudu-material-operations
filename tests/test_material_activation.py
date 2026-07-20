from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

import app


def material_row(record_id: str, product: str, status: str | None) -> dict:
    fields: dict[str, object] = {
        "物料编码": f"MAT-{record_id}",
        "物料品类": product,
        "产品型号": "M1",
        "语种": "英语",
        "当前库存": 10,
        "单价": 2,
    }
    if status is not None:
        fields["启用状态"] = status
    return {"record_id": record_id, "fields": fields}


class MaterialActivationTests(unittest.TestCase):
    def test_inventory_dataframe_excludes_inactive_and_keeps_legacy_blank_rows(self) -> None:
        df = app.feishu_inventory_dataframe_from_rows(
            [
                material_row("1", "启用品类", app.STATUS_ACTIVE),
                material_row("2", "停用库存行", app.STATUS_INACTIVE),
                material_row("3", "旧数据", None),
            ]
        )

        self.assertEqual(df["物料编码"].tolist(), ["MAT-1", "MAT-3"])

    def test_request_options_require_active_category_and_active_inventory(self) -> None:
        categories = [
            {"record_id": "c1", "fields": {"物料品类": "启用品类", "启用状态": app.STATUS_ACTIVE}},
            {"record_id": "c2", "fields": {"物料品类": "停用品类", "启用状态": app.STATUS_INACTIVE}},
        ]
        inventory_df = pd.DataFrame(
            [
                ["MAT-1", "启用品类", "M1", "英语", 10, 0, 0, ""],
                ["MAT-2", "停用品类", "M1", "英语", 10, 0, 0, ""],
                ["MAT-3", "未配置品类", "M1", "英语", 10, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )

        options = app.feishu_options_from_rows(categories, inventory_df)

        self.assertEqual(options["products"], ["启用品类", "未配置品类"])
        self.assertNotIn("停用品类", options["products"])

    def test_dashboard_excludes_inactive_inventory_records(self) -> None:
        records = [
            {
                "record_id": "1",
                "material_code": "MAT-1",
                "category": "启用",
                "model": "M1",
                "language": "英语",
                "quantity": 10,
                "unit_price": 2,
                "total_value": 20,
                "status": app.STATUS_ACTIVE,
            },
            {
                "record_id": "2",
                "material_code": "MAT-2",
                "category": "停用",
                "model": "M1",
                "language": "英语",
                "quantity": -100,
                "unit_price": 2,
                "total_value": -200,
                "status": app.STATUS_INACTIVE,
            },
        ]

        dashboard_df = app.material_dashboard_dataframe(records)

        self.assertEqual(dashboard_df["记录ID"].tolist(), ["1"])
        self.assertEqual(int(dashboard_df["库存数量"].sum()), 10)

    def test_active_inventory_loader_also_excludes_inactive_categories(self) -> None:
        material_rows = [
            material_row("1", "启用品类", app.STATUS_ACTIVE),
            material_row("2", "停用品类", app.STATUS_ACTIVE),
            material_row("3", "停用库存行", app.STATUS_INACTIVE),
        ]
        category_rows = [
            {"record_id": "c1", "fields": {"物料品类": "启用品类", "启用状态": app.STATUS_ACTIVE}},
            {"record_id": "c2", "fields": {"物料品类": "停用品类", "启用状态": app.STATUS_INACTIVE}},
        ]

        with (
            patch.object(app, "feishu_material_rows", return_value=material_rows),
            patch.object(app, "feishu_category_rows", return_value=category_rows),
        ):
            records = app.load_feishu_inventory_records(active_only=True)

        self.assertEqual([record["record_id"] for record in records], ["1"])

    def test_request_cache_does_not_reintroduce_rows_from_inactive_categories(self) -> None:
        inventory_df = pd.DataFrame(
            [
                ["MAT-1", "启用品类", "M1", "英语", 10, 0, 0, ""],
                ["MAT-2", "停用品类", "M1", "英语", 10, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )
        options = {
            "products": ["启用品类"],
            "no_model_products": [],
            "no_language_products": [],
            "configured_language_products": [],
            "models": ["M1"],
            "languages": ["英语"],
        }

        cache = app.request_form_cache_from_inventory(options, inventory_df, source="test")

        self.assertEqual(cache["row_count"], 1)
        self.assertEqual(cache["inventory_rows"][0]["product"], "启用品类")


if __name__ == "__main__":
    unittest.main()
