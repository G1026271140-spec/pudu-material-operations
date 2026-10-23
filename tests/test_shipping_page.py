import unittest

import shipping_page


pass  # Removed retired widget: render_shipping_carton_page_fixture


pass  # Removed retired widget: render_shipping_recipient_page_fixture


class ShippingPageStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.category = {
            "record_id": "category-1",
            "category": "产品单页",
            "category_definition": shipping_page.CATEGORY_DEFINITION_PRINT,
            "commercial_invoice_name": "Product Flyer",
            "packing_list_product_type": "Flyers",
            "unit_price": 1.25,
            "customs_code": "4911101000",
        }

    def test_product_state_uses_category_defaults_without_overwriting_edits(self) -> None:
        state: dict[str, object] = {
            "shipping_product_invoice_name_category-1": "Manual Invoice Name",
        }

        shipping_page.initialize_shipping_product_state(
            state,
            "category-1",
            self.category,
        )

        self.assertEqual(
            state["shipping_product_invoice_name_category-1"],
            "Manual Invoice Name",
        )
        self.assertEqual(
            state["shipping_product_packing_name_category-1"],
            "Product Flyer",
        )
        self.assertEqual(
            state["shipping_product_customs_category-1"],
            "4911101000",
        )

    def test_shipping_category_pool_label_uses_chinese_page_name_only(self) -> None:
        self.assertEqual(
            shipping_page._category_label(
                {
                    "zh_page_name": "产品单页",
                    "category": "产品单页(Product Flyer)",
                    "commercial_invoice_name": "Product Flyer",
                }
            ),
            "产品单页",
        )
        self.assertEqual(
            shipping_page._category_label({"category": "历史物料品类"}),
            "历史物料品类",
        )

    pass  # Removed retired widget: test_carton_page_renders_two_columns_and_automatic_metrics

    pass  # Removed retired widget: test_carton_preset_fills_dimensions_and_gross_weight

    pass  # Removed retired widget: test_manual_carton_edit_clears_selected_preset

    def test_carton_presets_use_requested_dimensions_and_weight_range(self) -> None:
        expected_dimensions = {
            "单页箱": (44, 30, 13),
            "手册箱": (44, 32, 20),
            "易拉宝箱": (80, 30, 35),
            "笔记本礼盒箱": (73, 26, 40),
            "小箱": (43, 27, 17),
            "中小箱": (40, 35, 29),
            "中大箱": (68, 50, 52),
            "大箱": (63, 50, 66),
        }

        self.assertEqual(set(shipping_page.CARTON_PRESETS), set(expected_dimensions))
        for name, dimensions in expected_dimensions.items():
            preset = shipping_page.CARTON_PRESETS[name]
            self.assertEqual(
                (preset["length"], preset["width"], preset["height"]),
                dimensions,
            )
            self.assertGreaterEqual(preset["gross_weight"], 6)
            self.assertLessEqual(preset["gross_weight"], 16)

    pass  # Removed retired widget: test_shipping_page_uses_compact_two_carton_layout

    pass  # Removed retired widget: test_country_name_input_is_replaced_with_address_code

    def test_new_carton_copies_previous_carton_values(self) -> None:
        state: dict[str, object] = {
            "shipping_gross_weight_1": 13.2,
            "shipping_length_1": 60.0,
            "shipping_width_1": 40.0,
            "shipping_height_1": 35.0,
        }

        shipping_page.initialize_shipping_carton_state(state, 2, 1)

        for suffix in shipping_page.CARTON_FIELD_DEFAULTS:
            self.assertEqual(
                state[f"shipping_{suffix}_2"],
                state[f"shipping_{suffix}_1"],
            )

    def test_carton_metrics_are_calculated_from_required_inputs(self) -> None:
        scenarios = [
            (50, 40, 25, 15, 0.05, 1.0, 14.0),
            (60, 40, 50, 30, 0.12, 2.0, 28.0),
            (80, 60, 50, 31, 0.24, 3.0, 28.0),
        ]

        for length, width, height, gross, cbm, packaging, net in scenarios:
            with self.subTest(gross=gross, cbm=cbm):
                calculated_cbm = shipping_page.calculate_carton_cbm(
                    length,
                    width,
                    height,
                )
                calculated_packaging = shipping_page.estimate_packaging_weight(
                    calculated_cbm,
                    gross,
                )
                self.assertAlmostEqual(calculated_cbm, cbm)
                self.assertEqual(calculated_packaging, packaging)
                self.assertEqual(
                    shipping_page.calculate_net_weight(gross, calculated_packaging),
                    net,
                )

    def test_packaging_weight_uses_higher_volume_or_weight_tier(self) -> None:
        self.assertEqual(shipping_page.estimate_packaging_weight(0.04, 20), 2.0)
        self.assertEqual(shipping_page.estimate_packaging_weight(0.2, 10), 3.0)
        self.assertEqual(shipping_page.calculate_net_weight(1, 1), 0.0)

    def test_new_carton_copies_previous_contents_and_quantities(self) -> None:
        state: dict[str, object] = {
            "shipping_carton_categories_1": ["category-1", "category-2"],
            "shipping_carton_item_quantity_1_category-1": 20,
            "shipping_carton_item_quantity_1_category-2": 8,
        }

        shipping_page.initialize_shipping_carton_contents_state(
            state,
            2,
            {"category-1", "category-2"},
            1,
        )

        self.assertEqual(
            state["shipping_carton_categories_2"],
            ["category-1", "category-2"],
        )
        self.assertEqual(
            state["shipping_carton_item_quantity_2_category-1"],
            20,
        )
        self.assertEqual(
            state["shipping_carton_item_quantity_2_category-2"],
            8,
        )

    def test_category_options_are_split_into_definition_pools(self) -> None:
        category_by_id = {
            "print-1": {
                "category_definition": shipping_page.CATEGORY_DEFINITION_PRINT,
            },
            "gift-1": {
                "category_definition": shipping_page.CATEGORY_DEFINITION_GIFT,
            },
            "cultural-1": {
                "category_definition": shipping_page.CATEGORY_DEFINITION_CULTURAL,
            },
            "legacy-1": {"category_definition": ""},
        }

        self.assertEqual(
            shipping_page.shipping_category_pool_options(category_by_id),
            {
                "print": ["print-1"],
                "gift": ["gift-1"],
                "cultural": ["cultural-1"],
                "undefined": ["legacy-1"],
            },
        )

    def test_category_definition_pools_balance_into_two_columns(self) -> None:
        pool_options = {
            "print": [f"print-{index}" for index in range(10)],
            "gift": [f"gift-{index}" for index in range(18)],
            "cultural": ["cultural-1", "cultural-2"],
            "undefined": [],
        }

        self.assertEqual(
            shipping_page.shipping_category_pool_columns(pool_options),
            (
                [
                    ("print", shipping_page.CATEGORY_DEFINITION_PRINT),
                    ("cultural", shipping_page.CATEGORY_DEFINITION_CULTURAL),
                ],
                [("gift", shipping_page.CATEGORY_DEFINITION_GIFT)],
            ),
        )

    def test_existing_carton_selection_migrates_into_definition_pools(self) -> None:
        state: dict[str, object] = {
            "shipping_carton_categories_1": ["print-1", "gift-1"],
        }
        pool_options = {
            "print": ["print-1"],
            "gift": ["gift-1"],
        }

        shipping_page.initialize_shipping_carton_category_pool_state(
            state,
            1,
            pool_options,
        )

        self.assertEqual(state["shipping_carton_categories_print_1"], ["print-1"])
        self.assertEqual(state["shipping_carton_categories_gift_1"], ["gift-1"])
        self.assertEqual(
            shipping_page.shipping_carton_category_pool_selection(
                state,
                1,
                pool_options,
            ),
            ["print-1", "gift-1"],
        )

    def test_carton_contents_remove_stale_and_duplicate_categories(self) -> None:
        state: dict[str, object] = {
            "shipping_carton_categories_1": [
                "category-1",
                "stale-category",
                "category-1",
            ],
        }

        shipping_page.initialize_shipping_carton_contents_state(
            state,
            1,
            {"category-1"},
        )

        self.assertEqual(
            state["shipping_carton_categories_1"],
            ["category-1"],
        )

    def test_same_category_across_cartons_creates_one_invoice_total(self) -> None:
        carton_items = [
            {"carton_no": 1, "category_id": "category-1", "quantity": 100},
            {"carton_no": 1, "category_id": "category-2", "quantity": 20},
            {"carton_no": 2, "category_id": "category-1", "quantity": 50},
        ]

        ordered, totals = shipping_page.aggregate_shipping_carton_items(carton_items)
        allocations = shipping_page.build_shipping_carton_allocations(carton_items)

        self.assertEqual(ordered, ["category-1", "category-2"])
        self.assertEqual(totals, {"category-1": 150, "category-2": 20})
        self.assertEqual(
            [(item.carton_no, item.line_id, item.quantity) for item in allocations],
            [
                (1, "category-1", 100),
                (1, "category-2", 20),
                (2, "category-1", 50),
            ],
        )

    def test_same_category_cannot_repeat_inside_one_carton(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能重复选择"):
            shipping_page.aggregate_shipping_carton_items(
                [
                    {"carton_no": 1, "category_id": "category-1", "quantity": 6},
                    {"carton_no": 1, "category_id": "category-1", "quantity": 4},
                ]
            )


if __name__ == "__main__":
    unittest.main()
