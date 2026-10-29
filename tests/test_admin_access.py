import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app


class AdminAccessTests(unittest.TestCase):
    def test_application_version_tracks_backend_release(self) -> None:
        self.assertEqual(app.APP_VERSION, "V4.0.6")

    def test_runtime_health_checks_use_fastapi_endpoint(self):
        root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "scripts/publish_live_cache.py",
            "scripts/run_release.ps1",
        ):
            source = (root / relative_path).read_text(encoding="utf-8-sig")
            self.assertIn("/api/health", source)
            self.assertNotIn("/_stcore/health", source)

    def test_submission_queue_module_version_matches_application(self) -> None:
        self.assertEqual(
            app.SUBMISSION_QUEUE_MODULE_VERSION,
            app.REQUIRED_SUBMISSION_QUEUE_MODULE_VERSION,
        )

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

    def test_direct_language_route_initializes_requested_language_once(self) -> None:
        query_params = {"lang": "en"}
        session_state: dict[str, object] = {}
        with (
            patch.object(app.runtime, "request_query", query_params),
            patch.object(app.runtime, "request_state", session_state),
        ):
            self.assertEqual(app.apply_ui_language_from_query(), app.LANGUAGE_EN)
            self.assertEqual(
                session_state[app.UI_LANGUAGE_SESSION_KEY],
                app.LANGUAGE_EN,
            )
            self.assertEqual(
                session_state["request_mobile_ui_language"],
                app.LANGUAGE_EN,
            )

            session_state[app.UI_LANGUAGE_SESSION_KEY] = app.LANGUAGE_ZH
            app.apply_ui_language_from_query()

        self.assertEqual(
            session_state[app.UI_LANGUAGE_SESSION_KEY],
            app.LANGUAGE_ZH,
        )

    def test_invalid_direct_language_route_does_not_change_session(self) -> None:
        session_state: dict[str, object] = {}
        with (
            patch.object(app.runtime, "request_query", {"lang": "fr"}),
            patch.object(app.runtime, "request_state", session_state),
        ):
            self.assertEqual(app.apply_ui_language_from_query(), "")

        self.assertNotIn(app.UI_LANGUAGE_SESSION_KEY, session_state)

    pass  # Retired widget test: test_inventory_review_page_is_available_for_signed_admin_links

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

    pass  # Retired widget test: test_material_management_navigation_does_not_request_fullscreen_loading

    pass  # Retired widget test: test_other_navigation_does_not_request_database_loading_overlay

    def test_internal_material_navigation_clears_loading_overlay(self) -> None:
        session_state: dict[str, object] = {
            app.MATERIAL_MANAGEMENT_CONTROL_KEY: "品类管理",
        }
        with patch.object(app.runtime, "request_state", session_state):
            app.request_material_management_navigation_loading()

        self.assertNotIn(app.MANAGEMENT_NAVIGATION_LOADING_KEY, session_state)

    def test_material_database_page_is_not_exposed(self) -> None:
        self.assertEqual(
            app.MATERIAL_MANAGEMENT_SECTIONS,
            ("采购补库", "品类管理", "型号管理", "语种管理", "战区管理", "仓库位置", "发货模板", "下单排期管理", "项目礼品管理"),
        )
        self.assertNotIn("项目礼品管理", app.MANAGEMENT_WORKBENCH_SECTIONS)
        self.assertNotIn("material_database", app.PAGE_CACHE_TABLES)
        self.assertFalse(hasattr(app, "render_material_database_page"))

    pass  # Retired widget test: test_inventory_query_uses_requested_feishu_table

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

    pass  # Retired widget test: test_locked_cache_publish_does_not_expose_github_link

    pass  # Retired widget test: test_locked_system_connection_does_not_read_secret_status


if __name__ == "__main__":
    unittest.main()
