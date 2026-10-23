import unittest
from unittest.mock import patch

import app


class RequestCartTests(unittest.TestCase):
    def test_runtime_proxy_resolves_current_app_api_without_module_lookup(self) -> None:
        self.assertIs(app.APP_RUNTIME.fresh_feishu_rows, app.fresh_feishu_rows)
        self.assertEqual(app.APP_RUNTIME.LANGUAGE_EN, app.LANGUAGE_EN)

    pass  # Retired widget assertion: test_request_preview_callback_only_records_intent

    def test_compact_cart_toggle_stays_in_session_state(self) -> None:
        state = {}
        with patch.object(app.runtime, "request_state", state):
            app.toggle_request_compact_cart()
            self.assertTrue(state["request_compact_cart_open"])
            app.toggle_request_compact_cart()
            self.assertFalse(state["request_compact_cart_open"])

    def test_category_image_uses_cached_attachment_field(self) -> None:
        rows = [
            {
                "fields": {
                    "物料品类": "产品单页(Product Flyer)",
                    app.REQUEST_CATEGORY_IMAGE_FIELD: [
                        {"file_token": "request-image-token"}
                    ],
                }
            }
        ]
        with (
            patch.object(app, "safe_feishu_rows", return_value=rows),
            patch.object(app.Path, "is_file", return_value=True),
        ):
            chinese_path = app.request_category_image_path("产品单页(Product Flyer)")

        self.assertIsNotNone(chinese_path)
        self.assertEqual(chinese_path.name, "a4b4218f2fc4da2656b1.webp")

    def test_category_without_image_uses_placeholder_path(self) -> None:
        with patch.object(app, "safe_feishu_rows", return_value=[]):
            self.assertIsNone(app.request_category_image_path("定制LOGO书包(Customized PUDU bag)"))

    def test_chinese_category_label_hides_bilingual_suffix(self) -> None:
        with patch.object(app.runtime, "request_state", {app.UI_LANGUAGE_SESSION_KEY: app.LANGUAGE_ZH}):
            self.assertEqual(
                app.request_category_display_label(
                    "工业产品线手册IR(Industrial Product Line Brochure）"
                ),
                "工业产品线手册IR",
            )

    def test_catalog_search_matches_bilingual_product_name(self) -> None:
        products = ["产品单页(Product Flyer)", "冰箱贴(Fridge Magnet)"]

        self.assertEqual(
            app.filter_request_catalog_products(products, "fridge"),
            ["冰箱贴(Fridge Magnet)"],
        )
        self.assertEqual(
            app.filter_request_catalog_products(products, "产品"),
            ["产品单页(Product Flyer)"],
        )

    def test_adding_the_same_material_merges_quantity(self) -> None:
        lines = [
            {
                "product": "冰箱贴(Fridge Magnet)",
                "model": "无型号",
                "language": "英语(English)",
                "quantity": 2,
                "remark": "old",
            }
        ]
        next_line = {
            "product": "冰箱贴(Fridge Magnet)",
            "model": "无型号",
            "language": "英语(English)",
            "quantity": 3,
            "remark": "new",
        }

        updated, merged = app.add_request_material_to_cart(lines, next_line)

        self.assertTrue(merged)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["quantity"], 5)
        self.assertEqual(updated[0]["remark"], "new")
        self.assertEqual(lines[0]["quantity"], 2)

    def test_adding_a_new_material_keeps_existing_lines(self) -> None:
        lines = [
            {
                "product": "冰箱贴(Fridge Magnet)",
                "model": "无型号",
                "language": "英语(English)",
                "quantity": 1,
                "remark": "",
            }
        ]
        next_line = {
            "product": "产品单页(Product Flyer)",
            "model": "P1",
            "language": "英语(English)",
            "quantity": 4,
            "remark": "",
        }

        updated, merged = app.add_request_material_to_cart(lines, next_line)

        self.assertFalse(merged)
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[1], next_line)

    def test_multi_select_only_builds_valid_inventory_combinations(self) -> None:
        context = {
            "product_model_languages": {
                ("产品手册", "P1"): ["英语", "日语"],
                ("产品手册", "P2"): ["英语"],
            }
        }

        lines = app.build_request_cart_selection_lines(
            context,
            "产品手册",
            ["P1", "P2"],
            ["英语", "日语"],
            3,
            "展会",
        )

        self.assertEqual(
            [(line["model"], line["language"]) for line in lines],
            [("P1", "英语"), ("P1", "日语"), ("P2", "英语")],
        )
        self.assertTrue(all(line["quantity"] == 3 for line in lines))
        self.assertTrue(all(line["remark"] == "展会" for line in lines))

    def test_custom_material_uses_one_free_text_value_for_all_dimensions(self) -> None:
        line = app.build_custom_request_material_line("新款宣传册 20份", 20, "急用")

        self.assertEqual(line["product"], "新款宣传册 20份")
        self.assertEqual(line["model"], "新款宣传册 20份")
        self.assertEqual(line["language"], "新款宣传册 20份")
        self.assertEqual(line["quantity"], 20)
        self.assertEqual(line["remark"], "急用")
        self.assertTrue(line["is_custom_material"])

        payload = app.queued_material_request_payload(
            {"submission_token": "submit-1"},
            [line],
        )
        self.assertTrue(payload["lines"][0]["is_custom_material"])

    def test_cart_state_normalization_preserves_custom_material_marker(self) -> None:
        custom_line = app.build_custom_request_material_line("新品", 50, "")
        session_state = {"request_material_lines": [custom_line]}

        with patch.object(app.runtime, "request_state", session_state):
            normalized = app.get_request_material_lines()
            payload = app.queued_material_request_payload(
                {"submission_token": "submit-custom"}, normalized
            )

        self.assertTrue(normalized[0]["is_custom_material"])
        self.assertTrue(session_state["request_material_lines"][0]["is_custom_material"])
        self.assertTrue(payload["lines"][0]["is_custom_material"])

    def test_custom_material_master_row_is_zero_priced_and_idempotent(self) -> None:
        item = app.build_custom_request_material_line("新款宣传册 20份", 20, "")
        created = {
            "record_id": "material-custom-1",
            "fields": {
                "物料品类": "新款宣传册 20份",
                "产品型号": "新款宣传册 20份",
                "语种": "新款宣传册 20份",
            },
        }
        rows = []
        with (
            patch.object(app, "parse_feishu_inventory_record", return_value=None),
            patch.object(app, "next_material_codes_from_records", return_value=["MAT-9999"]),
            patch.object(app, "set_yes_no_field") as set_yes_no,
            patch.object(app, "set_feishu_unit_price") as set_price,
            patch.object(app, "feishu_create_record", return_value=created) as create_record,
        ):
            result = app.ensure_custom_request_material(rows, item, "submit-1")

        self.assertEqual(result, created)
        self.assertEqual(rows, [created])
        set_yes_no.assert_called_once_with(app.MATERIAL_TABLE_NAME, unittest.mock.ANY, "是否临时物料", True)
        set_price.assert_called_once_with(app.MATERIAL_TABLE_NAME, unittest.mock.ANY, 0)
        fields = create_record.call_args.args[1]
        self.assertEqual(fields["当前库存"], 0)
        self.assertEqual(fields[app.REQUEST_PAGE_VISIBILITY_FIELD], app.REQUEST_PAGE_HIDDEN_VALUE)

    def test_model_multi_select_only_offers_languages_shared_by_every_model(self) -> None:
        context = {
            "product_model_languages": {
                ("产品手册", "P1"): ["英语", "日语"],
                ("产品手册", "P2"): ["英语"],
            }
        }

        self.assertEqual(
            app.request_language_options_for_models(
                context,
                "产品手册",
                ["P1", "P2"],
            ),
            ["英语"],
        )

    def test_stale_widget_selections_are_removed_when_inventory_options_change(self) -> None:
        state = {
            "models": ["已停用型号", "M1"],
            "language": "已停用语种",
        }

        with patch.object(app.runtime, "request_state", state):
            app.normalize_request_option_state(
                "models",
                ["M1", "M2"],
                multiple=True,
            )
            app.normalize_request_option_state(
                "language",
                ["英语"],
                multiple=False,
            )

        self.assertEqual(state["models"], ["M1"])
        self.assertIsNone(state["language"])

    def test_language_does_not_default_to_first_available_option(self) -> None:
        state = {"language": None}
        with patch.object(app.runtime, "request_state", state):
            selected = app.ensure_request_language_default(
                "language",
                ["英语", "简中"],
            )

        self.assertIsNone(selected)
        self.assertIsNone(state["language"])

    def test_model_multi_select_does_not_preselect_first_option(self) -> None:
        state = {"models": []}
        with patch.object(app.runtime, "request_state", state):
            app.normalize_request_option_state(
                "models",
                ["M1", "M2"],
                multiple=True,
            )

        self.assertEqual(state["models"], [])

    def test_request_estimated_total_uses_cached_rmb_prices(self) -> None:
        context = {
            "unit_price_rmb_by_combination": {
                ("产品单页", "M1", "英语"): 2.5,
                ("产品手册", "无需型号", "无需语种"): 8.0,
            }
        }
        lines = [
            {"product": "产品单页", "model": "M1", "language": "英语", "quantity": 4},
            {"product": "产品手册", "model": app.NO_MODEL_TEXT, "language": app.NO_LANGUAGE_TEXT, "quantity": 2},
            {"product": "自定义", "model": "自定义", "language": "自定义", "quantity": 99, "is_custom_material": True},
        ]

        self.assertEqual(app.request_estimated_total_rmb(lines, context), 26.0)

    def test_enabling_one_multi_select_turns_the_other_off(self) -> None:
        state = {
            "model_multi": True,
            "language_multi": True,
        }

        with patch.object(app.runtime, "request_state", state):
            app.enforce_request_cart_exclusive_multi_select(
                "model_multi",
                "language_multi",
            )

        self.assertTrue(state["model_multi"])
        self.assertFalse(state["language_multi"])
        self.assertTrue(state["request_form_cache_locked"])

    pass  # Retired widget test: test_successful_cart_addition_shows_right_side_toast_once


if __name__ == "__main__":
    unittest.main()
