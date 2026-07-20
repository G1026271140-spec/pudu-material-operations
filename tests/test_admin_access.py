import unittest
from unittest.mock import MagicMock, patch

import app


class AdminAccessTests(unittest.TestCase):
    def test_category_navigation_and_workbench_control_use_different_state_keys(self) -> None:
        self.assertNotEqual(
            app.MANAGEMENT_NAVIGATION_KEY,
            app.MANAGEMENT_WORKBENCH_CONTROL_KEY,
        )

    def test_protected_management_sections_share_admin_gate(self) -> None:
        self.assertTrue(app.management_section_requires_admin("物料数据库"))
        self.assertTrue(app.management_section_requires_admin("品类管理"))

    def test_request_pages_remain_unprotected(self) -> None:
        self.assertFalse(app.management_section_requires_admin("库存登记"))
        self.assertFalse(app.management_section_requires_admin("修改与撤回"))
        self.assertFalse(app.management_section_requires_admin(""))

    def test_locked_cache_publish_does_not_expose_github_link(self) -> None:
        expander = MagicMock()
        expander.__enter__.return_value = expander
        with (
            patch.object(app.st, "session_state", {}),
            patch.object(app.st, "expander", return_value=expander),
            patch.object(app, "sidebar_admin_auth_gate", return_value=False),
            patch.object(app.st, "link_button") as link_button,
            patch.object(app.st, "button") as button,
        ):
            app.render_github_cache_publish()

        link_button.assert_not_called()
        button.assert_not_called()

    def test_locked_system_connection_does_not_read_secret_status(self) -> None:
        expander = MagicMock()
        expander.__enter__.return_value = expander
        with (
            patch.object(app.st, "session_state", {}),
            patch.object(app.st.sidebar, "expander", return_value=expander),
            patch.object(app, "sidebar_admin_auth_gate", return_value=False),
            patch.object(app, "feishu_app_id") as feishu_app_id,
        ):
            app.render_storage_diagnostics()

        feishu_app_id.assert_not_called()


if __name__ == "__main__":
    unittest.main()
