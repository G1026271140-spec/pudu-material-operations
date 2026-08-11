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
        self.assertTrue(app.management_section_requires_admin("物料管理"))

    def test_request_pages_remain_unprotected(self) -> None:
        self.assertFalse(app.management_section_requires_admin("库存登记"))
        self.assertFalse(app.management_section_requires_admin(""))

    def test_material_management_navigation_requests_fullscreen_loading(self) -> None:
        session_state: dict[str, object] = {}
        query_params = MagicMock()
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "query_params", query_params),
            patch.object(app.st, "button", return_value=True),
            patch.object(app.st, "rerun") as rerun,
        ):
            app.navigate_to_management_section(
                "sidebar_open_material_management",
                "物料管理",
                "物料管理",
                ":material/inventory_2:",
            )

        self.assertEqual(
            session_state[app.MANAGEMENT_NAVIGATION_LOADING_KEY],
            "物料管理",
        )
        query_params.clear.assert_called_once_with()
        rerun.assert_called_once_with()

    def test_other_navigation_does_not_request_database_loading_overlay(self) -> None:
        session_state: dict[str, object] = {}
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "query_params", MagicMock()),
            patch.object(app.st, "button", return_value=True),
            patch.object(app.st, "rerun"),
        ):
            app.navigate_to_management_section(
                "sidebar_open_request",
                "库存登记",
                "库存登记",
                ":material/edit_note:",
            )

        self.assertNotIn(app.MANAGEMENT_NAVIGATION_LOADING_KEY, session_state)

    def test_internal_material_navigation_requests_fullscreen_loading(self) -> None:
        session_state: dict[str, object] = {
            app.MATERIAL_MANAGEMENT_CONTROL_KEY: "物料数据库",
        }
        with patch.object(app.st, "session_state", session_state):
            app.request_material_management_navigation_loading()

        self.assertEqual(
            session_state[app.MANAGEMENT_NAVIGATION_LOADING_KEY],
            "物料数据库",
        )

    def test_all_material_management_pages_use_loading_overlay(self) -> None:
        self.assertTrue(app.management_navigation_uses_loading_overlay("物料管理"))
        for section in app.MATERIAL_MANAGEMENT_SECTIONS:
            self.assertTrue(app.management_navigation_uses_loading_overlay(section))
        self.assertFalse(app.management_navigation_uses_loading_overlay("库存登记"))

    def test_request_edit_and_withdraw_page_is_not_exposed(self) -> None:
        self.assertNotIn("修改与撤回", app.MANAGEMENT_WORKBENCH_SECTIONS)
        self.assertFalse(app.management_navigation_uses_loading_overlay("修改与撤回"))

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
