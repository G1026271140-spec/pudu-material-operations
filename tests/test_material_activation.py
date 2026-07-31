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
    def test_unit_price_writer_uses_current_usd_field_name(self) -> None:
        fields: dict[str, object] = {}
        with patch.object(
            app,
            "feishu_table_fields",
            return_value={"单价（美元）": {"type": 2}},
        ):
            app.set_feishu_unit_price(app.MATERIAL_TABLE_NAME, fields, 0.06)

        self.assertEqual(fields, {"单价（美元）": 0.06})

    def test_customs_code_writer_converts_numeric_text_for_number_field(self) -> None:
        fields: dict[str, object] = {}
        with patch.object(
            app,
            "feishu_table_fields",
            return_value={"海关编码": {"type": 2}},
        ):
            app.set_feishu_customs_code(app.MATERIAL_TABLE_NAME, fields, "4911101000")

        self.assertEqual(fields, {"海关编码": 4911101000})
        self.assertIsInstance(fields["海关编码"], int)

    def test_customs_code_writer_omits_blank_number_value(self) -> None:
        fields: dict[str, object] = {}
        with patch.object(
            app,
            "feishu_table_fields",
            return_value={"海关编码": {"type": 2}},
        ):
            app.set_feishu_customs_code(app.MATERIAL_TABLE_NAME, fields, "")

        self.assertEqual(fields, {})

    def test_customs_code_writer_rejects_text_for_number_field_early(self) -> None:
        with patch.object(
            app,
            "feishu_table_fields",
            return_value={"海关编码": {"type": 2}},
        ):
            with self.assertRaisesRegex(ValueError, "海关编码为数字字段"):
                app.set_feishu_customs_code(app.MATERIAL_TABLE_NAME, {}, "HS-1")

    def test_customs_code_writer_keeps_text_for_text_field(self) -> None:
        fields: dict[str, object] = {}
        with patch.object(
            app,
            "feishu_table_fields",
            return_value={"海关编码": {"type": 1}},
        ):
            app.set_feishu_customs_code(app.MATERIAL_TABLE_NAME, fields, "HS-1")

        self.assertEqual(fields, {"海关编码": "HS-1"})

    def test_inventory_dataframe_excludes_inactive_and_keeps_legacy_blank_rows(self) -> None:
        df = app.feishu_inventory_dataframe_from_rows(
            [
                material_row("1", "启用品类", app.STATUS_ACTIVE),
                material_row("2", "停用库存行", app.STATUS_INACTIVE),
                material_row("3", "旧数据", None),
            ]
        )

        self.assertEqual(df["物料编码"].tolist(), ["MAT-1", "MAT-3"])

    def test_inventory_dataframe_prefers_current_usd_unit_price_field(self) -> None:
        row = material_row("1", "启用品类", app.STATUS_ACTIVE)
        row["fields"]["单价（美元）"] = 3.5

        df = app.feishu_inventory_dataframe_from_rows([row])

        self.assertEqual(float(df.iloc[0][app.PRICE_COL]), 3.5)

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

        self.assertEqual(options["products"], ["启用品类"])
        self.assertNotIn("停用品类", options["products"])
        self.assertNotIn("未配置品类", options["products"])

    def test_request_models_come_from_active_model_dimension_and_sort_by_family(self) -> None:
        categories = [
            {"record_id": "c1", "fields": {"物料品类": "启用品类", "启用状态": app.STATUS_ACTIVE}},
        ]
        inventory_df = pd.DataFrame(
            [
                ["MAT-1", "启用品类", "Legacy", "英语", 10, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )
        model_rows = [
            {"record_id": "m1", "fields": {"产品型号": "MT1 Vac", "启用状态": app.STATUS_ACTIVE}},
            {"record_id": "m2", "fields": {"产品型号": "MT1", "启用状态": app.STATUS_ACTIVE}},
            {"record_id": "m3", "fields": {"产品型号": "MT1 Max", "启用状态": app.STATUS_ACTIVE}},
            {"record_id": "m4", "fields": {"产品型号": "Retired", "启用状态": app.STATUS_INACTIVE}},
        ]

        options = app.feishu_options_from_rows(categories, inventory_df, model_rows)

        self.assertEqual(options["models"], ["MT1", "MT1 Max", "MT1 Vac"])

    def test_request_languages_come_from_active_language_dimension(self) -> None:
        categories = [
            {"record_id": "c1", "fields": {"物料品类": "启用品类", "启用状态": app.STATUS_ACTIVE}},
        ]
        inventory_df = pd.DataFrame(
            [
                ["MAT-1", "启用品类", "M1", "库存旧语种", 10, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )
        language_rows = [
            {"record_id": "l1", "fields": {"语言种类": "英语(English)", "启用状态": app.STATUS_ACTIVE}},
            {"record_id": "l2", "fields": {"语言种类": "韩语(Korean)", "启用状态": app.STATUS_ACTIVE}},
            {"record_id": "l3", "fields": {"语言种类": "停用语种", "启用状态": app.STATUS_INACTIVE}},
        ]

        options = app.feishu_options_from_rows(categories, inventory_df, language_rows=language_rows)

        self.assertEqual(options["languages"], ["英语(English)", "韩语(Korean)"])
        self.assertNotIn("库存旧语种", options["languages"])
        self.assertNotIn("停用语种", options["languages"])

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

    def test_category_matching_tolerates_bilingual_suffix_differences(self) -> None:
        inventory_df = pd.DataFrame(
            [
                ["MAT-IR", "工业产品线手册IR（Industrial Product Line Brochure）", "M1", "英语", 10, 0, 0, ""],
                ["MAT-CLOTHES", "展会服装", "无型号", "无语种", 10, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )
        options = {
            "products": [
                "工业产品线手册IR(Industrial Product Line Brochure）",
                "展会服装（Clothes）",
            ],
            "no_model_products": [],
            "no_language_products": [],
            "configured_language_products": [],
            "models": ["M1"],
            "languages": ["英语"],
        }

        cache = app.request_form_cache_from_inventory(options, inventory_df, source="test")

        self.assertEqual(cache["row_count"], 2)
        self.assertEqual(
            [row["product"] for row in cache["inventory_rows"]],
            options["products"],
        )

    def test_request_submit_index_tolerates_bilingual_parenthesis_differences(self) -> None:
        material_rows = [
            {
                "record_id": "material-cr-zh",
                "fields": {
                    "物料编码": "MAT-0389",
                    "物料品类": "清洁产品线手册CR（Cleaning Product Line Brochure）",
                    "产品型号": app.NO_MODEL_TEXT,
                    "语种": "简中(Simplified Chinese)",
                    "启用状态": app.STATUS_ACTIVE,
                },
            }
        ]
        category_rows = [
            {
                "record_id": "category-cr",
                "fields": {
                    "物料品类": "清洁产品线手册CR(Cleaning Product Line Brochure）",
                    "启用状态": app.STATUS_ACTIVE,
                },
            }
        ]

        material_index = app.build_request_material_index(material_rows, category_rows)
        lookup_key = app.request_material_match_key(
            "清洁产品线手册CR(Cleaning Product Line Brochure）",
            app.NO_MODEL_TEXT,
            "简中(Simplified Chinese)",
        )

        self.assertEqual(material_index[lookup_key]["record_id"], "material-cr-zh")

        category_rows[0]["fields"]["启用状态"] = app.STATUS_INACTIVE
        self.assertEqual(app.build_request_material_index(material_rows, category_rows), {})

    def test_request_combination_must_exist_in_active_inventory_rows(self) -> None:
        context = app.request_form_cache_to_selection_context(
            {
                "products": ["品类A"],
                "models": ["M1", "M2"],
                "languages": ["英语", "法语"],
                "inventory_rows": [
                    {
                        "material_code": "MAT-1",
                        "product": "品类A",
                        "model": "M1",
                        "language": "英语",
                        "quantity": 0,
                    }
                ],
            }
        )

        self.assertTrue(app.selection_context_has_inventory_combination(context, "品类A", "M1", "英语"))
        self.assertFalse(app.selection_context_has_inventory_combination(context, "品类A", "M2", "法语"))


if __name__ == "__main__":
    unittest.main()
