import unittest
from unittest.mock import patch

import app


class FeishuLinkTests(unittest.TestCase):
    def test_material_table_url_uses_default_tenant_and_table_id(self) -> None:
        def secret_value(name: str, default: str = "") -> str:
            values = {"FEISHU_BITABLE_APP_TOKEN": "base-token"}
            return values.get(name, default)

        with (
            patch.object(app, "get_secret_value", side_effect=secret_value),
            patch.object(app, "feishu_table_id", return_value="tbl-material"),
        ):
            result = app.feishu_bitable_web_url(app.MATERIAL_TABLE_NAME)

        self.assertEqual(
            result,
            "https://pudutech.feishu.cn/base/base-token?table=tbl-material",
        )

    def test_configured_base_url_keeps_other_query_and_targets_material_table(self) -> None:
        def secret_value(name: str, default: str = "") -> str:
            values = {
                "FEISHU_BITABLE_WEB_URL": (
                    "https://example.feishu.cn/base/base-token?from=streamlit&table=old&view=old-view"
                )
            }
            return values.get(name, default)

        with (
            patch.object(app, "get_secret_value", side_effect=secret_value),
            patch.object(app, "feishu_table_id", return_value="tbl-material"),
        ):
            result = app.feishu_bitable_web_url(app.MATERIAL_TABLE_NAME)

        self.assertIn("from=streamlit", result)
        self.assertIn("table=tbl-material", result)
        self.assertNotIn("view=", result)


if __name__ == "__main__":
    unittest.main()
