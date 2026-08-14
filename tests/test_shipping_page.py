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

    def test_new_shipping_line_copies_latest_entry_values(self) -> None:
        state: dict[str, object] = {
            "shipping_category_source": "category-2",
            "shipping_invoice_name_source": "Custom Invoice Name",
            "shipping_packing_name_source": "Custom Packing Name",
            "shipping_packing_type_source": "Brochures",
            "shipping_quantity_source": 36,
            "shipping_unit_price_source": 2.75,
            "shipping_customs_source": "99887766",
            "shipping_model_source": "BellaBot",
            "shipping_sku_source": "SKU-36",
        }

        shipping_page.initialize_shipping_line_state(
            state,
            "target",
            self.category,
            "source",
        )

        for suffix in shipping_page.LINE_FIELD_SUFFIXES:
            self.assertEqual(
                state[f"shipping_{suffix}_target"],
                state[f"shipping_{suffix}_source"],
            )

    def test_existing_shipping_line_values_are_not_overwritten_on_refresh(self) -> None:
        state: dict[str, object] = {
            "shipping_quantity_target": 88,
            "shipping_invoice_name_target": "Manual Name",
        }

        shipping_page.initialize_shipping_line_state(
            state,
            "target",
            self.category,
        )

        self.assertEqual(state["shipping_quantity_target"], 88)
        self.assertEqual(state["shipping_invoice_name_target"], "Manual Name")
        self.assertEqual(state["shipping_customs_target"], "4911101000")

    def test_new_carton_copies_previous_carton_values(self) -> None:
        state: dict[str, object] = {
            "shipping_carton_quantity_1": 4,
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

    def test_first_carton_uses_stable_defaults(self) -> None:
        state: dict[str, object] = {}

        shipping_page.initialize_shipping_carton_state(state, 1)

        self.assertEqual(state["shipping_carton_quantity_1"], 1)
        self.assertEqual(state["shipping_net_weight_1"], 0.0)
        self.assertFalse(state["shipping_override_cbm_1"])


if __name__ == "__main__":
    unittest.main()
