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
    def test_request_cache_carries_localized_model_page_names(self) -> None:
        inventory = pd.DataFrame(
            [["MAT-1", "Flyer", "P1", "英语", 0, 0, 0, ""]],
            columns=app.INVENTORY_HEADERS,
        )
        options = {
            "products": ["Flyer"], "models": ["P1"], "languages": ["英语"],
            "no_model_products": [], "no_language_products": [],
            "configured_language_products": [], "model_product_lines": {"P1": "SR"},
            "model_display_names": {
                "P1": {app.LANGUAGE_ZH: "送餐机器人 P1", app.LANGUAGE_EN: "P1 Delivery Robot"}
            },
        }
        cache = app.request_form_cache_from_inventory(options, inventory, source="test")
        context = app.request_form_cache_to_selection_context(cache)
        self.assertEqual(
            context["model_display_names"]["P1"],
            {app.LANGUAGE_ZH: "送餐机器人 P1", app.LANGUAGE_EN: "P1 Delivery Robot"},
        )
        self.assertEqual(
            app.request_model_display_label("P1", context["model_display_names"], app.LANGUAGE_ZH),
            "送餐机器人 P1",
        )
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

        self.assertEqual(cache["schema_version"], app.REQUEST_FORM_CACHE_SCHEMA_VERSION)
        self.assertEqual(cache["row_count"], 1)
        self.assertEqual(cache["combination_count"], 1)
        self.assertEqual(cache["inventory_rows"][0]["product"], "启用品类")
        self.assertEqual(
            cache["active_combinations"],
            [
                {
                    "product": "启用品类",
                    "models": [{"model": "M1", "languages": ["英语"]}],
                }
            ],
        )

    def test_request_cache_validation_rejects_tampered_combination_config(self) -> None:
        inventory_df = pd.DataFrame(
            [["MAT-1", "品类A", "M1", "英语", 10, 0, 0, ""]],
            columns=app.INVENTORY_HEADERS,
        )
        options = {
            "products": ["品类A"],
            "no_model_products": [],
            "no_language_products": [],
            "configured_language_products": [],
            "models": ["M1"],
            "languages": ["英语", "法语"],
        }
        cache = app.request_form_cache_from_inventory(options, inventory_df, source="test")
        cache["active_combinations"][0]["models"][0]["languages"] = ["法语"]

        with self.assertRaisesRegex(ValueError, "启用组合配置与物料行不一致"):
            app.validate_request_form_cache(cache, require_data=True)

    def test_request_cache_validation_rejects_orphan_product_config(self) -> None:
        cache = {
            "schema_version": app.REQUEST_FORM_CACHE_SCHEMA_VERSION,
            "products": ["没有启用行的品类"],
            "active_combinations": [],
            "combination_count": 0,
            "inventory_rows": [],
            "row_count": 0,
        }

        with self.assertRaisesRegex(ValueError, "品类配置与启用物料组合不一致"):
            app.validate_request_form_cache(cache)

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
                    app.REQUEST_PAGE_VISIBILITY_FIELD: app.REQUEST_PAGE_VISIBLE_VALUE,
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
                    app.REQUEST_PAGE_VISIBILITY_FIELD: app.REQUEST_PAGE_VISIBLE_VALUE,
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

        material_rows[0]["fields"][app.REQUEST_PAGE_VISIBILITY_FIELD] = "否"
        self.assertEqual(app.build_request_material_index(material_rows, category_rows), {})
        material_rows[0]["fields"][app.REQUEST_PAGE_VISIBILITY_FIELD] = (
            app.REQUEST_PAGE_VISIBLE_VALUE
        )

        category_rows[0]["fields"][app.REQUEST_PAGE_VISIBILITY_FIELD] = "否"
        self.assertEqual(app.build_request_material_index(material_rows, category_rows), {})
        category_rows[0]["fields"][app.REQUEST_PAGE_VISIBILITY_FIELD] = (
            app.REQUEST_PAGE_VISIBLE_VALUE
        )

        category_rows[0]["fields"]["启用状态"] = app.STATUS_INACTIVE
        material_rows[0]["fields"]["启用状态"] = app.STATUS_INACTIVE
        self.assertEqual(
            app.build_request_material_index(material_rows, category_rows)[lookup_key][
                "record_id"
            ],
            "material-cr-zh",
        )

    def test_request_inventory_requires_explicit_request_page_visibility(self) -> None:
        visible = material_row("1", "显示品类", app.STATUS_INACTIVE)
        visible["fields"][app.REQUEST_PAGE_VISIBILITY_FIELD] = app.REQUEST_PAGE_VISIBLE_VALUE
        hidden = material_row("2", "隐藏品类", app.STATUS_ACTIVE)
        hidden["fields"][app.REQUEST_PAGE_VISIBILITY_FIELD] = "否"
        blank = material_row("3", "空白品类", app.STATUS_ACTIVE)

        df = app.feishu_inventory_dataframe_from_rows(
            [visible, hidden, blank],
            request_visible_only=True,
        )

        self.assertEqual(df[app.INVENTORY_HEADERS[0]].tolist(), ["MAT-1"])

    def test_request_options_require_explicit_category_visibility(self) -> None:
        categories = [
            {
                "record_id": "c1",
                "fields": {
                    "物料品类": "显示品类",
                    "启用状态": app.STATUS_INACTIVE,
                    app.REQUEST_PAGE_VISIBILITY_FIELD: app.REQUEST_PAGE_VISIBLE_VALUE,
                },
            },
            {
                "record_id": "c2",
                "fields": {
                    "物料品类": "隐藏品类",
                    "启用状态": app.STATUS_ACTIVE,
                    app.REQUEST_PAGE_VISIBILITY_FIELD: "否",
                },
            },
        ]
        inventory_df = pd.DataFrame(
            [
                ["MAT-1", "显示品类", "M1", "英语", 10, 0, 0, ""],
                ["MAT-2", "隐藏品类", "M1", "英语", 10, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )

        options = app.feishu_options_from_rows(
            categories,
            inventory_df,
            request_visible_only=True,
        )

        self.assertEqual(options["products"], ["显示品类"])

    def test_request_product_lines_include_inactive_model_dimension_rows(self) -> None:
        categories = [
            {
                "record_id": "c1",
                "fields": {
                    "物料品类": "显示品类",
                    "启用状态": app.STATUS_INACTIVE,
                    app.REQUEST_PAGE_VISIBILITY_FIELD: app.REQUEST_PAGE_VISIBLE_VALUE,
                },
            }
        ]
        inventory_df = pd.DataFrame(
            [["MAT-1", "显示品类", "M1", "英语", 10, 0, 0, ""]],
            columns=app.INVENTORY_HEADERS,
        )
        model_rows = [
            {
                "record_id": "model-1",
                "fields": {
                    "产品型号": "M1",
                    "产品线": "IR",
                    "启用状态": app.STATUS_INACTIVE,
                },
            }
        ]

        options = app.feishu_options_from_rows(
            categories,
            inventory_df,
            model_rows,
            request_visible_only=True,
        )

        self.assertEqual(options["models"], ["M1"])
        self.assertEqual(options["model_product_lines"], {"M1": "IR"})

    def test_request_cache_carries_model_product_lines(self) -> None:
        inventory_df = pd.DataFrame(
            [
                ["MAT-1", "品类A", "M1", "英语", 10, 0, 0, ""],
                ["MAT-2", "品类A", "M2", "英语", 10, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )
        options = {
            "products": ["品类A"],
            "no_model_products": [],
            "no_language_products": [],
            "configured_language_products": [],
            "models": ["M1", "M2"],
            "model_product_lines": {"M1": "IR", "M2": "新项目"},
            "languages": ["英语"],
        }

        cache = app.request_form_cache_from_inventory(options, inventory_df, source="test")
        context = app.request_form_cache_to_selection_context(cache)

        self.assertEqual(cache["model_product_lines"], {"M1": "IR", "M2": "新项目"})
        self.assertEqual(
            cache["active_combinations"][0]["models"],
            [
                {"model": "M1", "languages": ["英语"], "product_line": "IR"},
                {"model": "M2", "languages": ["英语"], "product_line": "新项目"},
            ],
        )
        self.assertEqual(context["model_product_lines"], {"M1": "IR", "M2": "新项目"})

    def test_model_product_line_layout_requires_multiple_primary_lines(self) -> None:
        context = {
            "product_models": {"品类A": ["M1", "M2", "M3"]},
            "model_product_lines": {"M1": "IR", "M2": "CR", "M3": "新项目"},
        }

        use_layout, groups = app.product_model_line_groups("品类A", context)

        self.assertTrue(use_layout)
        self.assertEqual(groups, [("IR", ["M1"]), ("CR", ["M2"]), ("新项目", ["M3"])])

        context["model_product_lines"] = {"M1": "IR", "M2": "IR", "M3": ""}
        use_layout, _ = app.product_model_line_groups("品类A", context)
        self.assertFalse(use_layout)

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

    def test_request_options_only_use_combinations_in_enabled_inventory_rows(self) -> None:
        context = app.request_form_cache_to_selection_context(
            {
                "products": ["品类A", "无启用行品类"],
                "models": ["M1", "M2", "维度表额外型号"],
                "languages": ["英语", "法语", app.NO_LANGUAGE_TEXT],
                "inventory_rows": [
                    {
                        "material_code": "MAT-1",
                        "product": "品类A",
                        "model": "M1",
                        "language": "英语",
                        "quantity": 10,
                    },
                    {
                        "material_code": "MAT-2",
                        "product": "品类A",
                        "model": "M2",
                        "language": "法语",
                        "quantity": 0,
                    },
                ],
            }
        )

        self.assertEqual(context["products"], ["品类A"])
        self.assertEqual(app.product_model_state("品类A", context), (False, ["M1", "M2"]))
        self.assertEqual(app.product_language_options("品类A", "M1", context), ["英语"])
        self.assertEqual(app.product_language_options("品类A", "M2", context), ["法语"])
        self.assertNotIn(
            app.NO_LANGUAGE_TEXT,
            app.product_language_options("品类A", "M1", context),
        )

    def test_no_model_and_no_language_only_appear_when_enabled_row_contains_them(self) -> None:
        context = app.request_form_cache_to_selection_context(
            {
                "products": ["无规格品类"],
                "models": ["M1"],
                "languages": ["英语"],
                "inventory_rows": [
                    {
                        "material_code": "MAT-1",
                        "product": "无规格品类",
                        "model": app.NO_MODEL_TEXT,
                        "language": app.NO_LANGUAGE_TEXT,
                        "quantity": 1,
                    }
                ],
            }
        )

        self.assertEqual(
            app.product_model_state("无规格品类", context),
            (True, [app.NO_MODEL_TEXT]),
        )
        self.assertEqual(
            app.product_language_state("无规格品类", app.NO_MODEL_TEXT, context),
            (True, [app.NO_LANGUAGE_TEXT]),
        )

    def test_new_static_cache_replaces_locked_request_session(self) -> None:
        def cache(generated_at: str, languages: list[str]) -> dict[str, object]:
            inventory_rows = [
                {
                    "material_code": f"MAT-{index:04d}",
                    "product": "产品单页",
                    "model": "BellaBot",
                    "language": language,
                    "quantity": 0,
                }
                for index, language in enumerate(languages, start=1)
            ]
            return {
                "schema_version": app.REQUEST_FORM_CACHE_SCHEMA_VERSION,
                "source": "test",
                "generated_at": generated_at,
                "products": ["产品单页"],
                "no_model_products": [],
                "no_language_products": [],
                "configured_language_products": ["产品单页"],
                "models": ["BellaBot"],
                "model_product_lines": {"BellaBot": "SR"},
                "languages": languages,
                "active_combinations": app.request_form_active_combinations(
                    inventory_rows,
                    {"BellaBot": "SR"},
                ),
                "combination_count": len(languages),
                "inventory_rows": inventory_rows,
                "row_count": len(inventory_rows),
            }

        old_cache = cache("2026-08-13 14:27:47", ["英语(English)"])
        new_cache = cache(
            "2026-08-13 14:50:25",
            ["英语(English)", "简中(Simplified Chinese)", "韩语(Korean)"],
        )
        session_state = {
            "request_form_cache_data": old_cache,
            "request_form_cache_locked": True,
        }
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app, "request_form_cache_state", return_value={}),
            patch.object(app, "request_form_cache_from_runtime_page_data", return_value=None),
            patch.object(app, "load_static_request_form_cache", return_value=new_cache),
        ):
            context = app.get_request_form_selection_context()

        self.assertEqual(
            app.product_language_options("产品单页", "BellaBot", context),
            ["英语(English)", "简中(Simplified Chinese)", "韩语(Korean)"],
        )
        self.assertIs(session_state["request_form_cache_data"], new_cache)
        self.assertFalse(session_state["request_form_cache_locked"])


if __name__ == "__main__":
    unittest.main()
