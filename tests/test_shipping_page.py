import unittest

import shipping_page
from streamlit.testing.v1 import AppTest


def render_shipping_carton_page_fixture() -> None:
    import shipping_page

    shipping_page._render_cartons_and_contents(
        [
            {
                "record_id": "print-1",
                "category": "产品单页",
                "category_definition": shipping_page.CATEGORY_DEFINITION_PRINT,
                "commercial_invoice_name": "Product Flyer",
                "packing_list_product_type": "Flyers",
                "unit_price": 0.06,
                "customs_code": "4911101000",
            },
            {
                "record_id": "gift-1",
                "category": "帆布袋",
                "category_definition": shipping_page.CATEGORY_DEFINITION_GIFT,
                "commercial_invoice_name": "Canvas Bag",
                "packing_list_product_type": "Give aways",
                "unit_price": 2.0,
                "customs_code": "4202920000",
            },
            {
                "record_id": "cultural-1",
                "category": "文化POLO衫",
                "category_definition": shipping_page.CATEGORY_DEFINITION_CULTURAL,
                "commercial_invoice_name": "Cultural Polo Shirt",
                "packing_list_product_type": "Give aways",
                "unit_price": 10.0,
                "customs_code": "6105100090",
            },
        ]
    )


def render_shipping_recipient_page_fixture() -> None:
    from datetime import date

    import shipping_page

    shipping_page._render_recipient_fields(date(2026, 8, 14))


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

    def test_carton_page_renders_two_columns_and_automatic_metrics(self) -> None:
        app_test = AppTest.from_function(
            render_shipping_carton_page_fixture,
            default_timeout=10,
        ).run()

        self.assertFalse(list(app_test.exception))
        self.assertEqual(
            [item.label for item in app_test.pills],
            ["箱型模板（可选）", "印刷物料品类", "周边礼品品类", "文化周边品类"],
        )
        self.assertEqual(
            [item.label for item in app_test.number_input[:5]],
            ["实际箱数", "长（CM） *", "宽（CM） *", "高（CM） *", "毛重（KG） *"],
        )
        self.assertEqual(
            [item.label for item in app_test.metric],
            ["品类", "体积（自动）", "包材重量（自动）", "净重（自动）"],
        )

        pills_by_label = {item.label: item for item in app_test.pills}
        pills_by_label["印刷物料品类"].set_value(["print-1"])
        pills_by_label["周边礼品品类"].set_value(["gift-1"])
        app_test.number_input[1].set_value(50)
        app_test.number_input[2].set_value(40)
        app_test.number_input[3].set_value(25)
        app_test.number_input[4].set_value(15)
        app_test.run()

        self.assertFalse(list(app_test.exception))
        self.assertEqual(app_test.metric[0].value, "2")
        self.assertEqual(app_test.metric[1].value, "0.050 CBM")
        self.assertEqual(app_test.metric[2].value, "1 KG")
        self.assertEqual(app_test.metric[3].value, "14 KG")

    def test_carton_preset_fills_dimensions_and_gross_weight(self) -> None:
        app_test = AppTest.from_function(
            render_shipping_carton_page_fixture,
            default_timeout=10,
        ).run()

        app_test.pills[0].set_value("中大箱")
        app_test.run()

        self.assertFalse(list(app_test.exception))
        self.assertEqual(
            [item.value for item in app_test.number_input[1:5]],
            [68.0, 50.0, 52.0, 14.0],
        )
        self.assertEqual(app_test.metric[1].value, "0.177 CBM")
        self.assertEqual(app_test.metric[2].value, "3 KG")
        self.assertEqual(app_test.metric[3].value, "11 KG")

    def test_manual_carton_edit_clears_selected_preset(self) -> None:
        app_test = AppTest.from_function(
            render_shipping_carton_page_fixture,
            default_timeout=10,
        ).run()

        app_test.pills[0].set_value("中大箱")
        app_test.run()
        app_test.number_input[1].set_value(70.0)
        app_test.run()

        self.assertFalse(list(app_test.exception))
        self.assertIsNone(app_test.pills[0].value)
        self.assertEqual(app_test.number_input[1].value, 70.0)
        self.assertEqual(
            [item.value for item in app_test.number_input[2:5]],
            [50.0, 52.0, 14.0],
        )

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

    def test_shipping_page_uses_compact_two_carton_layout(self) -> None:
        source = open(shipping_page.__file__, encoding="utf-8").read()

        self.assertIn('shipping_recipient_panel', source)
        self.assertIn('shipping_carton_row_', source)
        self.assertIn('shipping_carton_card_', source)
        self.assertIn('st.columns(2, gap="small")', source)
        self.assertIn('@media (max-width: 900px)', source)
        self.assertIn('height=56', source)
        self.assertIn('top_a, top_b, top_c = st.columns([1, 1, 1])', source)
        self.assertIn('row_a = st.columns(4)', source)

    def test_country_name_input_is_replaced_with_address_code(self) -> None:
        app_test = AppTest.from_function(
            render_shipping_recipient_page_fixture,
            default_timeout=10,
        ).run()

        self.assertFalse(list(app_test.exception))
        country_input = app_test.text_input[0]
        self.assertEqual(country_input.label, "国家名称或英文缩写")
        country_input.set_value("泰国")
        app_test.run()

        self.assertFalse(list(app_test.exception))
        self.assertEqual(app_test.text_input[0].value, "TH")
        self.assertEqual(app_test.code[0].value, "2026-MKT-TH0814")

        app_test.text_input[0].set_value("巴拿马")
        app_test.run()

        self.assertFalse(list(app_test.exception))
        self.assertEqual(app_test.text_input[0].value, "PA")
        self.assertEqual(app_test.code[0].value, "2026-MKT-PA0814")

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
