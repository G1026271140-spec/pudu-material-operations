import unittest
from unittest.mock import MagicMock, patch

import app


class AdminAccessTests(unittest.TestCase):
    def test_application_version_is_shown_in_sidebar(self) -> None:
        self.assertEqual(app.APP_VERSION, "V1.9.2")

    def test_submission_queue_module_version_matches_application(self) -> None:
        self.assertEqual(
            app.SUBMISSION_QUEUE_MODULE_VERSION,
            app.REQUIRED_SUBMISSION_QUEUE_MODULE_VERSION,
        )

    def test_admin_password_is_independent_from_inventory_password(self) -> None:
        with patch.object(app.st, "secrets", {}):
            self.assertEqual(app.get_approval_password(), "pd123456")
            self.assertEqual(app.get_inventory_password(), "376493")

    def test_submission_success_message_is_bilingual(self) -> None:
        with patch.object(app, "get_ui_language", return_value=app.LANGUAGE_ZH):
            self.assertEqual(
                app.data_submission_success_message(),
                "数据提交成功，请您关注飞书审批进度，感谢您的使用。",
            )
        with patch.object(app, "get_ui_language", return_value=app.LANGUAGE_EN):
            self.assertEqual(
                app.data_submission_success_message(),
                "Data submitted successfully. Please follow the Feishu approval progress. Thank you for using this application.",
            )

    def test_inventory_review_page_is_available_for_signed_admin_links(self) -> None:
        self.assertTrue(callable(app.render_request_inventory_review_page))

    def test_category_navigation_and_workbench_control_use_different_state_keys(self) -> None:
        self.assertNotEqual(
            app.MANAGEMENT_NAVIGATION_KEY,
            app.MANAGEMENT_WORKBENCH_CONTROL_KEY,
        )

    def test_protected_management_sections_share_admin_gate(self) -> None:
        self.assertTrue(app.management_section_requires_admin("物料管理"))

    def test_request_pages_remain_unprotected(self) -> None:
        self.assertFalse(app.management_section_requires_admin("库存登记"))
        self.assertFalse(app.management_section_requires_admin("周边礼品项目"))
        self.assertFalse(app.management_section_requires_admin(""))

    def test_material_management_navigation_does_not_request_fullscreen_loading(self) -> None:
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

        self.assertNotIn(app.MANAGEMENT_NAVIGATION_LOADING_KEY, session_state)
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

    def test_internal_material_navigation_clears_loading_overlay(self) -> None:
        session_state: dict[str, object] = {
            app.MATERIAL_MANAGEMENT_CONTROL_KEY: "品类管理",
        }
        with patch.object(app.st, "session_state", session_state):
            app.request_material_management_navigation_loading()

        self.assertNotIn(app.MANAGEMENT_NAVIGATION_LOADING_KEY, session_state)

    def test_material_database_page_is_not_exposed(self) -> None:
        self.assertEqual(
            app.MATERIAL_MANAGEMENT_SECTIONS,
            ("采购补库", "品类管理", "型号管理", "语种管理", "战区管理", "仓库位置", "发货模板", "项目礼品管理"),
        )
        self.assertNotIn("项目礼品管理", app.MANAGEMENT_WORKBENCH_SECTIONS)
        self.assertNotIn("material_database", app.PAGE_CACHE_TABLES)
        self.assertFalse(hasattr(app, "render_material_database_page"))

    def test_inventory_query_uses_requested_feishu_table(self) -> None:
        container = MagicMock()
        container.__enter__.return_value = container
        with (
            patch.object(app.st, "container", return_value=container) as st_container,
            patch.object(app.st, "link_button") as link_button,
        ):
            app.render_inventory_query_link()

        st_container.assert_called_once_with(key="sidebar_inventory_query")
        link_button.assert_called_once_with(
            "查询库存",
            "https://pudutech.feishu.cn/wiki/G7vbwubTbiagPokSvAiceK8AnZc?table=blkR84ObPdrZr82Y",
            icon=":material/search:",
            width="stretch",
        )

    def test_all_management_pages_avoid_loading_overlay(self) -> None:
        self.assertFalse(app.management_navigation_uses_loading_overlay("物料管理"))
        for section in app.MATERIAL_MANAGEMENT_SECTIONS:
            self.assertFalse(app.management_navigation_uses_loading_overlay(section))
        self.assertFalse(app.management_navigation_uses_loading_overlay("库存登记"))
        self.assertFalse(app.management_navigation_uses_loading_overlay("项目礼品管理"))

    def test_request_edit_and_withdraw_page_is_not_exposed(self) -> None:
        self.assertNotIn("修改与撤回", app.MANAGEMENT_WORKBENCH_SECTIONS)
        self.assertFalse(app.management_navigation_uses_loading_overlay("修改与撤回"))

    def test_approval_and_issuance_page_is_not_exposed(self) -> None:
        self.assertFalse(hasattr(app, "navigate_to_approval"))
        self.assertFalse(hasattr(app, "render_approval_view"))
        self.assertNotIn("approval", app.PAGE_CACHE_TABLES)

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
