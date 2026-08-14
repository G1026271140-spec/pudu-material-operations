import unittest

import shipping_page


class ShippingPageStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.category = {
            "record_id": "category-1",
            "category": "产品单页",
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

    def test_new_carton_copies_previous_carton_values(self) -> None:
        state: dict[str, object] = {
            "shipping_net_weight_1": 12.5,
            "shipping_gross_weight_1": 13.2,
            "shipping_override_cbm_1": True,
            "shipping_length_1": 60.0,
            "shipping_width_1": 40.0,
            "shipping_height_1": 35.0,
            "shipping_cbm_override_1": 0.084,
        }

        shipping_page.initialize_shipping_carton_state(state, 2, 1)

        for suffix in shipping_page.CARTON_FIELD_DEFAULTS:
            self.assertEqual(
                state[f"shipping_{suffix}_2"],
                state[f"shipping_{suffix}_1"],
            )

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
