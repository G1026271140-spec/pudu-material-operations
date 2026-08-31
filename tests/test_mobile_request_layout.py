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

    def test_phone_specification_selector_is_full_screen(self) -> None:
        self.assertIn('height: 100dvh !important;', SOURCE)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))', SOURCE)
        self.assertIn('button[aria-pressed="true"]', SOURCE)

    def test_phone_cart_and_submit_actions_are_fixed(self) -> None:
        self.assertIn('.st-key-request_compact_cart {', SOURCE)
        self.assertIn('.st-key-request_preview {', SOURCE)
        self.assertIn('bottom: max(0.6rem, env(safe-area-inset-bottom))', SOURCE)

    def test_request_sections_have_stable_keys(self) -> None:
        self.assertIn('key="request_business_section"', SOURCE)
        self.assertIn('key="request_material_section"', SOURCE)


if __name__ == "__main__":
    unittest.main()
