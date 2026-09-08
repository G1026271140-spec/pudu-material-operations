from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")


class MobileRequestLayoutTests(unittest.TestCase):
    def test_phone_rules_are_scoped_to_request_page(self) -> None:
        start = SOURCE.index("/* Dedicated phone layout for the request page.")
        mobile_block = SOURCE[start : SOURCE.index("</style>", start)]
        self.assertIn('.stApp:has(.pudu-request-page-marker)', mobile_block)
        self.assertIn('.st-key-refresh_page_cache_request', mobile_block)

    def test_phone_specification_selector_is_centered_and_compact(self) -> None:
        self.assertIn('inset: 50% auto auto 50% !important;', SOURCE)
        self.assertIn('transform: translate(-50%, -50%) !important;', SOURCE)
        self.assertIn('grid-template-columns: repeat(3, minmax(0, 1fr))', SOURCE)
        self.assertIn('button[aria-pressed="true"]', SOURCE)

    def test_phone_cart_and_submit_actions_are_fixed(self) -> None:
        self.assertIn('.st-key-request_compact_cart {', SOURCE)
        self.assertIn('.st-key-request_preview {', SOURCE)
        self.assertIn('bottom: max(0.6rem, env(safe-area-inset-bottom))', SOURCE)

    def test_request_sections_have_stable_keys(self) -> None:
        self.assertIn('key="request_business_section"', SOURCE)
        self.assertIn('key="request_material_section"', SOURCE)

    def test_request_material_interactions_use_a_fragment(self) -> None:
        builder = SOURCE.split("def render_request_material_builder", 1)[0]
        self.assertTrue(builder.rstrip().endswith("@st.fragment"))
        self.assertIn('st.rerun(scope="app")', SOURCE)
        self.assertIn('st.rerun(scope="fragment")', SOURCE)
        self.assertIn('on_change="rerun"', SOURCE)
        self.assertIn('key="request_compact_cart_panel"', SOURCE)
        self.assertIn("if not specification_popover.open:", SOURCE)

    def test_phone_toolbar_supports_language_and_navigation(self) -> None:
        self.assertIn('key="request_mobile_toolbar"', SOURCE)
        self.assertIn('key="request_mobile_ui_language"', SOURCE)
        self.assertIn('key="request_mobile_navigation"', SOURCE)
        self.assertIn('icon=":material/translate:"', SOURCE)
        self.assertIn('pudu_col.image', SOURCE)
        self.assertIn('app_col.image', SOURCE)

    def test_phone_form_and_catalog_use_two_column_grids(self) -> None:
        self.assertIn('.st-key-request_business_section [data-testid="stHorizontalBlock"]', SOURCE)
        self.assertIn('.st-key-request_catalog_grid {', SOURCE)
        self.assertGreaterEqual(
            SOURCE.count('grid-template-columns: repeat(2, minmax(0, 1fr))'),
            2,
        )

    def test_phone_cart_bottom_sheet_resets_native_popover_transform(self) -> None:
        cart_css = SOURCE.split(
            '[data-testid="stPopoverBody"]:has(.pudu-full-cart-popover-marker)', 1
        )[1]
        self.assertIn('transform: none !important;', cart_css)

    def test_model_line_selector_uses_a_responsive_group_grid(self) -> None:
        self.assertIn('key=f"request_model_line_grid_', SOURCE)
        self.assertIn('for name, options in visible_groups:', SOURCE)

    def test_phone_specification_keeps_models_scrollable_and_actions_fixed(self) -> None:
        self.assertIn('key=f"request_spec_model_scroll_', SOURCE)
        self.assertIn('key=f"request_spec_fixed_', SOURCE)
        self.assertIn('max-height: 34dvh !important;', SOURCE)
        self.assertIn('min-height: 8.5rem !important;', SOURCE)
        self.assertIn('flex: 1 1 0 !important;', SOURCE)
        self.assertIn('position: relative !important;', SOURCE)
        self.assertIn(
            'grid-template-columns: repeat(2, minmax(0, 1fr)) !important;',
            SOURCE,
        )

    def test_phone_compact_specification_window_hugs_single_model_content(self) -> None:
        self.assertIn('mobile_model_complexity = len(model_options)', SOURCE)
        self.assertIn('pudu-mobile-specification-popover-compact', SOURCE)
        self.assertIn('height: auto !important;', SOURCE)
        self.assertIn('overflow: visible !important;', SOURCE)

    def test_phone_toolbar_is_icon_only_without_a_container_frame(self) -> None:
        start = SOURCE.rindex('.st-key-request_mobile_toolbar {')
        toolbar_css = SOURCE[start : SOURCE.index('[data-testid="stHorizontalBlock"]', start)]
        self.assertIn('border: 0 !important;', toolbar_css)
        self.assertIn('background: transparent !important;', toolbar_css)
        self.assertIn('box-shadow: none !important;', toolbar_css)
        self.assertIn('[data-testid="stPopoverButton"]', SOURCE)
        self.assertIn('[aria-hidden="true"]', SOURCE)

    def test_phone_business_labels_reserve_real_layout_height(self) -> None:
        self.assertIn(
            '[data-testid="stElementContainer"]:has(.pudu-section-heading)',
            SOURCE,
        )
        self.assertIn(
            '[data-testid="stElementContainer"]:has(.pudu-field-label)',
            SOURCE,
        )
        self.assertIn('min-height: 1.05rem !important;', SOURCE)

    def test_phone_specification_sections_are_labeled_and_visually_separated(self) -> None:
        self.assertIn('class="pudu-spec-model-heading"', SOURCE)
        self.assertIn('ui_text("型号选择")', SOURCE)
        self.assertIn('.pudu-spec-model-heading {\n                display: none !important;', SOURCE)
        self.assertIn('class="pudu-product-model-label"', SOURCE)
        self.assertIn('ui_text("产品型号")', SOURCE)
        self.assertIn('background: #F3F6FA !important;', SOURCE)
        self.assertIn('background: #EEF8F6 !important;', SOURCE)
        self.assertIn('background: #FFF7ED !important;', SOURCE)

    def test_desktop_model_heading_reserves_space_above_widget_label(self) -> None:
        desktop_rule = SOURCE.split('@media (min-width: 641px)', 1)[1].split(
            '[data-testid="stSidebar"]', 1
        )[0]
        self.assertIn(':has(.pudu-spec-model-heading)', desktop_rule)
        self.assertIn('min-height: 1.35rem !important;', desktop_rule)
        self.assertIn('margin-bottom: 0.45rem !important;', desktop_rule)
        self.assertIn('[data-testid="stWidgetLabel"]', desktop_rule)

    def test_desktop_specification_selector_label_stays_on_one_line(self) -> None:
        desktop_rule = SOURCE.split('@media (min-width: 641px)', 1)[1].split(
            '[data-testid="stSidebar"]', 1
        )[0]
        self.assertIn('font-size: 0.74rem !important;', desktop_rule)
        self.assertIn('white-space: nowrap !important;', desktop_rule)
        self.assertIn('word-break: keep-all !important;', desktop_rule)

    def test_request_specification_has_quantity_presets_and_compact_custom_fields(self) -> None:
        self.assertIn('"快捷数量",', SOURCE)
        self.assertIn('[20, 50]', SOURCE)
        self.assertIn('"自定义数量",', SOURCE)
        self.assertIn('st.columns([0.65, 1.35, 0.9]', SOURCE)
        self.assertIn('label_visibility="hidden"', SOURCE)
        self.assertIn('apply_request_quantity_preset', SOURCE)
        self.assertIn('clear_request_quantity_preset', SOURCE)

    def test_product_model_label_reserves_layout_space_before_product_lines(self) -> None:
        self.assertIn(':has(.pudu-product-model-label)', SOURCE)
        self.assertIn('min-height: 1.25rem !important;', SOURCE)
        self.assertIn('margin-bottom: 0.42rem !important;', SOURCE)

    def test_phone_specification_keeps_add_action_above_short_viewport_chrome(self) -> None:
        self.assertIn('[class*="st-key-request_add_to_cart_"]', SOURCE)
        self.assertIn('position: static !important;', SOURCE)
        self.assertIn('@media (max-height: 760px)', SOURCE)
        self.assertIn('font-size: 0.48rem !important;', SOURCE)
        self.assertIn('min-height: 16px !important;', SOURCE)


if __name__ == "__main__":
    unittest.main()
