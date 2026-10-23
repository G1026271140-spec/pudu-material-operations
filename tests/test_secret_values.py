from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import app


class SecretValueTests(unittest.TestCase):
    def test_streamlit_secret_takes_precedence_over_environment(self) -> None:
        with (
            patch.object(app.st, "secrets", {"EXAMPLE_SECRET": "streamlit-value"}),
            patch.dict(os.environ, {"EXAMPLE_SECRET": "environment-value"}),
        ):
            value = app.get_secret_value("EXAMPLE_SECRET")

        self.assertEqual(value, "streamlit-value")

    def test_environment_is_used_without_streamlit_secrets(self) -> None:
        with (
            patch.object(app.st, "secrets", {}),
            patch.dict(os.environ, {"EXAMPLE_SECRET": "environment-value"}),
        ):
            value = app.get_secret_value("EXAMPLE_SECRET")

        self.assertEqual(value, "environment-value")

    def test_default_is_used_when_secret_is_missing(self) -> None:
        with (
            patch.object(app.st, "secrets", {}),
            patch.dict(os.environ, {}, clear=True),
        ):
            value = app.get_secret_value("EXAMPLE_SECRET", "fallback")

        self.assertEqual(value, "fallback")


if __name__ == "__main__":
    unittest.main()
