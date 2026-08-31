import unittest

import app


class StreamlitChromeTests(unittest.TestCase):
    def test_native_toolbar_and_viewer_badge_are_hidden(self) -> None:
        source = open(app.__file__, encoding="utf-8").read()
        for selector in (
            '[data-testid="stToolbar"]',
            '[data-testid="stStatusWidget"]',
            '[data-testid="stDecoration"]',
            '[data-testid="stHeader"]',
            '[class*="viewerBadge"]',
        ):
            self.assertIn(selector, source)

    def test_client_toolbar_uses_minimal_mode(self) -> None:
        config = (app.Path(app.__file__).resolve().parent / ".streamlit" / "config.toml").read_text(
            encoding="utf-8"
        )
        self.assertIn('toolbarMode = "minimal"', config)


if __name__ == "__main__":
    unittest.main()
