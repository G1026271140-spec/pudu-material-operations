from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import app


class NoLanguageRuleTests(unittest.TestCase):
    def selection_context(
        self,
        *,
        explicit_products: list[str] | None = None,
        configured_products: list[str] | None = None,
    ) -> dict[str, object]:
        return app.request_form_cache_to_selection_context(
            {
                "products": ["公仔(Plush Toy)", "普通宣传册", "活动礼品"],
                "no_model_products": [],
                "no_language_products": explicit_products or [],
                "configured_language_products": configured_products or [],
                "models": ["BellaBot"],
                "languages": ["英语(English)", "德语(German)"],
                "inventory_rows": [
                    {
                        "product": "公仔(Plush Toy)",
                        "model": "BellaBot",
                        "language": "英语(English)",
                        "quantity": 1000,
                    },
                    {
                        "product": "普通宣传册",
                        "model": "BellaBot",
                        "language": "英语(English)",
                        "quantity": 1000,
                    },
                    {
                        "product": "普通宣传册",
                        "model": "BellaBot",
                        "language": "德语(German)",
                        "quantity": 1000,
                    },
                ],
            }
        )

    def test_default_no_language_product_is_forced_to_single_option(self) -> None:
        disabled, languages = app.product_language_state(
            "公仔(Plush Toy)",
            "BellaBot",
            self.selection_context(),
        )

        self.assertTrue(disabled)
        self.assertEqual(languages, [app.NO_LANGUAGE_TEXT])

    def test_explicit_no_language_category_uses_same_rule(self) -> None:
        disabled, languages = app.product_language_state(
            "活动礼品",
            "BellaBot",
            self.selection_context(explicit_products=["活动礼品"]),
        )

        self.assertTrue(disabled)
        self.assertEqual(languages, [app.NO_LANGUAGE_TEXT])

    def test_explicit_language_rule_can_override_default_category(self) -> None:
        disabled, languages = app.product_language_state(
            "公仔(Plush Toy)",
            "BellaBot",
            self.selection_context(configured_products=["公仔(Plush Toy)"]),
        )

        self.assertFalse(disabled)
        self.assertEqual(languages, ["英语(English)"])

    def test_normal_category_keeps_scoped_languages(self) -> None:
        disabled, languages = app.product_language_state(
            "普通宣传册",
            "BellaBot",
            self.selection_context(),
        )

        self.assertFalse(disabled)
        self.assertEqual(languages, ["英语(English)", "德语(German)"])

    def test_no_language_rows_create_one_inventory_row_per_model(self) -> None:
        rows, skipped = app.build_new_material_rows(
            app.pd.DataFrame(columns=app.INVENTORY_HEADERS),
            "活动礼品",
            ["BellaBot", "KettyBot Pro"],
            [app.NO_LANGUAGE_TEXT],
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual({row[3] for row in rows}, {app.NO_LANGUAGE_TEXT})
        self.assertEqual(skipped, [])

    def test_existing_category_record_receives_no_language_rule(self) -> None:
        client = Mock()
        client.batch_create_records.return_value = [{"record_id": "material-a"}]
        df = app.pd.DataFrame(
            [
                [
                    "MAT-0001",
                    "活动礼品",
                    "BellaBot",
                    app.NO_LANGUAGE_TEXT,
                    0,
                    0,
                    0,
                    "",
                ]
            ],
            columns=app.INVENTORY_HEADERS,
        )

        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "find_feishu_category_record", return_value={"record_id": "category-a"}),
            patch.object(app, "feishu_update_record_fields") as update_category,
            patch.object(app, "feishu_table_id", return_value="material-table"),
        ):
            inserted = app.add_feishu_material_category_payload(
                "活动礼品",
                False,
                True,
                df,
            )

        self.assertEqual(inserted, 1)
        update_category.assert_called_once()
        self.assertEqual(update_category.call_args.args[2]["是否无需语种"], "是")


if __name__ == "__main__":
    unittest.main()
