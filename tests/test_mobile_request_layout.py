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

    def test_phone_toolbar_supports_language_and_navigation(self) -> None:
        self.assertIn('key="request_mobile_toolbar"', SOURCE)
        self.assertIn('key="request_mobile_ui_language"', SOURCE)
        self.assertIn('key="request_mobile_navigation"', SOURCE)

    def test_phone_form_and_catalog_use_two_column_grids(self) -> None:
        self.assertIn('.st-key-request_business_section [data-testid="stHorizontalBlock"]', SOURCE)
        self.assertIn('.st-key-request_catalog_grid {', SOURCE)
        self.assertGreaterEqual(
            SOURCE.count('grid-template-columns: repeat(2, minmax(0, 1fr))'),
            2,
        )


if __name__ == "__main__":
    unittest.main()
