import re
import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app


class FullscreenSyncTests(unittest.TestCase):
    def test_request_form_edits_read_static_cache_without_loading_overlay(self) -> None:
        source = inspect.getsource(app.render_change_form)

        self.assertIn("get_request_form_selection_context()", source)
        self.assertNotIn("st.spinner", source)
        self.assertNotIn("fullscreen_data_sync", source)

    def test_request_success_renders_persistent_fullscreen_overlay(self) -> None:
        with (
            patch.object(app, "get_ui_language", return_value=app.LANGUAGE_ZH),
            patch.object(app.st, "markdown") as markdown,
        ):
            app.render_request_submission_success()

        rendered = markdown.call_args.args[0]
        self.assertIn("pudu-sync-overlay--success", rendered)
        self.assertIn("申请已提交，您可以关闭此页面。", rendered)
        self.assertIn('class="pudu-sync-overlay__close"', rendered)
        self.assertIn('title="返回申请页面"', rendered)
        self.assertIn('href="./"', rendered)
        self.assertNotIn("pudu-sync-overlay__spinner", rendered)
        markdown.assert_called_once_with(rendered, unsafe_allow_html=True)

    def test_request_success_uses_english_message_on_english_page(self) -> None:
        with (
            patch.object(app, "get_ui_language", return_value=app.LANGUAGE_EN),
            patch.object(app.st, "markdown") as markdown,
        ):
            app.render_request_submission_success()

        self.assertIn(
            "Request submitted. You may close this page.",
            markdown.call_args.args[0],
        )

    def test_request_review_shows_success_overlay_instead_of_closing_window(self) -> None:
        source = inspect.getsource(app.render_request_review)

        self.assertIn("render_request_submission_success()", source)
        self.assertNotIn("close_application_window()", source)

    def test_inventory_plan_success_renders_bilingual_fullscreen_overlay(self) -> None:
        with (
            patch.object(app, "get_ui_language", return_value=app.LANGUAGE_ZH),
            patch.object(app.st, "markdown") as markdown,
        ):
            app.render_inventory_plan_submission_success()

        rendered = markdown.call_args.args[0]
        self.assertIn("pudu-sync-overlay--success", rendered)
        self.assertIn("该申请单已提交配货方案，您可以关闭当前页面。", rendered)
        self.assertNotIn("pudu-sync-overlay__spinner", rendered)

        with (
            patch.object(app, "get_ui_language", return_value=app.LANGUAGE_EN),
            patch.object(app.st, "markdown") as english_markdown,
        ):
            app.render_inventory_plan_submission_success()

        self.assertIn(
            "The fulfillment plan for this request has been submitted. You may close this page.",
            english_markdown.call_args.args[0],
        )

    def test_inventory_plan_submission_shows_overlay_instead_of_closing_window(self) -> None:
        source = inspect.getsource(app.render_request_inventory_review_page)

        self.assertIn("render_inventory_plan_submission_success()", source)
        self.assertNotIn("close_application_window()", source)

    def test_overlay_contains_required_message_and_escapes_detail(self) -> None:
        html = app.fullscreen_sync_overlay_html("提交 <测试>")

        self.assertIn("提交 &lt;测试&gt;", html)
        self.assertNotIn("countdown", html)
        self.assertIn('aria-busy="true"', html)

    def test_overlay_css_keeps_responsive_fullscreen_panel(self) -> None:
        source = Path(app.__file__).read_text(encoding="utf-8")

        self.assertIn("width: min(540px, calc(100vw - 2rem))", source)
        self.assertIn("@media (max-width: 520px)", source)

    def test_overlay_clears_busy_state_after_success(self) -> None:
        session_state: dict[str, object] = {}
        overlay = MagicMock()
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "empty", return_value=overlay) as render_overlay,
        ):
            with app.fullscreen_data_sync("正在保存"):
                self.assertTrue(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])

        self.assertFalse(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])
        render_overlay.assert_called_once_with()
        overlay.markdown.assert_called_once_with(
            app.fullscreen_sync_overlay_html("正在保存"), unsafe_allow_html=True
        )
        overlay.empty.assert_called_once_with()

    def test_overlay_clears_busy_state_after_failure(self) -> None:
        session_state: dict[str, object] = {}
        overlay = MagicMock()
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "empty", return_value=overlay),
        ):
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                with app.fullscreen_data_sync():
                    raise RuntimeError("write failed")

        self.assertFalse(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])
        overlay.empty.assert_called_once_with()


    def test_native_loading_spinner_is_not_a_fullscreen_mask(self) -> None:
        source = Path(app.__file__).read_text(encoding="utf-8")
        spinner_css = source.split('[data-testid="stSpinner"] {', 1)[1].split("}", 1)[0]
        self.assertIn("position: static", spinner_css)
        self.assertNotIn("position: fixed", spinner_css)
        self.assertNotIn("backdrop-filter: blur", spinner_css)

    def test_navigation_does_not_add_artificial_wait_or_overlay(self) -> None:
        source = inspect.getsource(app.render_management_page_with_navigation_loading)
        self.assertNotIn("st.spinner", source)
        self.assertNotIn("time.sleep", source)

    def test_button_click_guard_uses_short_repeat_click_window(self) -> None:
        with patch.object(app.st.components.v1, "html") as html:
            app.install_button_click_guard()

        script = html.call_args.args[0]
        self.assertIn("puduClickGuard", script)
        self.assertIn("now + 700", script)
        self.assertIn("stopImmediatePropagation", script)
        html.assert_called_once_with(script, height=0, width=0)

    def test_submission_waits_do_not_use_inline_spinners(self) -> None:
        source = Path(app.__file__).read_text(encoding="utf-8")
        spinner_messages = re.findall(r'with st\.spinner\("([^"]+)"\)', source)
        forbidden_terms = ("提交", "写入", "保存", "删除", "补充库存", "发布")

        self.assertTrue(spinner_messages)
        self.assertFalse(
            [
                message
                for message in spinner_messages
                if any(term in message for term in forbidden_terms)
            ]
        )


class RequestReactMobileLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(app.__file__).parent / "request_web/frontend/src"
        self.css = (root / "styles.css").read_text(encoding="utf-8")
        self.page = (root / "App.tsx").read_text(encoding="utf-8")

    def test_request_page_has_scoped_phone_layout(self) -> None:
        phone = self.css.split(
            "/* Dedicated phone layout for the React material request page. */", 1
        )[1]
        self.assertIn('className="request-page"', self.page)
        self.assertIn("@media (max-width: 850px)", phone)
        self.assertIn(".request-page .grid3", phone)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", phone)
        self.assertIn("bottom: max(8px, env(safe-area-inset-bottom))", phone)

    def test_request_phone_spec_and_review_are_bottom_sheets(self) -> None:
        phone = self.css.split(
            "/* Dedicated phone layout for the React material request page. */", 1
        )[1]
        self.assertIn('className="modal request-spec-modal"', self.page)
        self.assertIn('className="modal review request-review-modal"', self.page)
        self.assertIn(".request-overlay", phone)
        self.assertIn("align-items: flex-end", phone)
        self.assertIn("max-height: min(94dvh, 820px)", phone)
        self.assertIn("env(safe-area-inset-bottom)", phone)

    def test_request_phone_cart_uses_card_rows(self) -> None:
        phone = self.css.split(
            "/* Dedicated phone layout for the React material request page. */", 1
        )[1]
        self.assertIn(".request-page .cartpanel tr", phone)
        self.assertIn("display: grid", phone)
        self.assertIn(".request-page .cartpanel thead", phone)

    def test_request_phone_cards_and_product_lines_use_two_columns(self) -> None:
        phone = self.css.split(
            "/* Dedicated phone layout for the React material request page. */", 1
        )[1]
        self.assertIn(".request-page .cards", phone)
        self.assertIn("aspect-ratio: 1.72", phone)
        self.assertIn(".request-spec-modal .model-line-grid", phone)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", phone)
        self.assertIn(".request-spec-modal .model-line-column", phone)
        self.assertIn("display: contents", phone)
        narrow = phone.split("@media (max-width: 380px)", 1)[1]
        self.assertNotIn(".request-page .cards,", narrow)

    def test_add_to_cart_shows_bilingual_red_notice(self) -> None:
        self.assertIn("cartNotice", self.page)
        self.assertIn('className="toast cart-added-toast"', self.page)
        self.assertIn('t("已加入采购车", "Added to cart")', self.page)


class ReactSidebarCollapseTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(app.__file__).parent / "request_web/frontend/src"
        self.portal = (root / "Portal.tsx").read_text(encoding="utf-8")
        self.css = (root / "portal.css").read_text(encoding="utf-8")

    def test_desktop_sidebar_can_collapse_and_restores_preference(self) -> None:
        self.assertIn('localStorage.getItem("pudu-sidebar-collapsed")', self.portal)
        self.assertIn('localStorage.setItem("pudu-sidebar-collapsed"', self.portal)
        self.assertIn("sidebar-collapsed", self.portal)
        self.assertIn("sidebar-collapse", self.portal)
        self.assertIn("sidebar-expand", self.portal)
        self.assertIn(".portal.sidebar-collapsed .portal-content", self.css)
        self.assertIn("margin-left: 0", self.css)

    def test_phone_navigation_ignores_desktop_collapse_state(self) -> None:
        mobile = self.css.split("@media (max-width: 900px)", 1)[1]
        self.assertIn("transform: none !important", mobile)
        self.assertIn(".sidebar-collapse", mobile)
        self.assertIn(".sidebar-expand", mobile)
        self.assertIn("display: none", mobile)

    def test_sidebar_brand_uses_larger_icons_and_single_line_titles(self) -> None:
        brand = self.css.split(".sidebar-brand {", 1)[1].split(".sidebar-label", 1)[0]
        self.assertIn("width: 100px", brand)
        self.assertIn("width: 46px", brand)
        self.assertGreaterEqual(brand.count("white-space: nowrap"), 2)


class CulturalMobileLayoutTests(unittest.TestCase):
    def test_cultural_page_has_phone_card_and_cart_layout(self) -> None:
        source = (
            Path(app.__file__).parent / "request_web/frontend/src/portal.css"
        ).read_text(encoding="utf-8")

        phone = source.split("@media (max-width: 600px)", 1)[1]
        self.assertIn(".culture-cards", phone)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", phone)
        self.assertIn(".culture-line", phone)
        self.assertIn("min-height: 44px", phone)

    def test_cultural_phone_modals_use_bottom_sheet_and_safe_area(self) -> None:
        source = (
            Path(app.__file__).parent / "request_web/frontend/src/portal.css"
        ).read_text(encoding="utf-8")

        phone = source.split("@media (max-width: 600px)", 1)[1]
        self.assertIn(".cultural-page .overlay", phone)
        self.assertIn("align-items: flex-end", phone)
        self.assertIn("max-height: min(92dvh, 760px)", phone)
        self.assertIn("env(safe-area-inset-bottom)", phone)


class GiftProjectUpdateMonitorTests(unittest.TestCase):
    def test_post_write_does_not_reload_page_or_request_cache(self) -> None:
        with (
            patch.object(app, "refresh_page_cache_tables") as refresh_tables,
            patch.object(app, "refresh_request_form_cache_from_page_data") as refresh_request,
        ):
            app.refresh_page_cache_after_write("category", update_request_form=True)

        refresh_tables.assert_not_called()
        refresh_request.assert_not_called()

    def test_signatures_are_stable_when_row_order_changes(self) -> None:
        first = [
            {"record_id": "2", "fields": {"项目名称": "B"}},
            {"record_id": "1", "fields": {"项目名称": "A"}},
        ]
        second = list(reversed(first))

        self.assertEqual(
            app.stable_feishu_rows_signature(first),
            app.stable_feishu_rows_signature(second),
        )

    def test_signatures_change_when_fields_change(self) -> None:
        first = [{"record_id": "1", "fields": {"物料状态": "已提需"}}]
        second = [{"record_id": "1", "fields": {"物料状态": "到货"}}]

        self.assertNotEqual(
            app.stable_feishu_rows_signature(first),
            app.stable_feishu_rows_signature(second),
        )

    def test_signature_ignores_cached_paths_and_temporary_attachment_urls(self) -> None:
        cached = [
            {
                "record_id": "1",
                "fields": {
                    "物料图片": [
                        {
                            "file_token": "file-1",
                            "name": "gift.png",
                            "type": "image/png",
                            "size": 42,
                            "cached_path": "assets/gift_projects/file-1.webp",
                            "tmp_url": "https://open.feishu.cn/temporary/old",
                            "url": "https://open.feishu.cn/download/old",
                        }
                    ]
                },
            }
        ]
        live = [
            {
                "record_id": "1",
                "fields": {
                    "物料图片": [
                        {
                            "file_token": "file-1",
                            "name": "gift.png",
                            "type": "image/png",
                            "size": 42,
                            "tmp_url": "https://open.feishu.cn/temporary/new",
                            "url": "https://open.feishu.cn/download/new",
                        }
                    ]
                },
            }
        ]

        self.assertEqual(
            app.stable_feishu_rows_signature(cached),
            app.stable_feishu_rows_signature(live),
        )

    def test_cached_pages_remain_available_without_background_polling(self) -> None:
        self.assertEqual(
            set(app.PAGE_CACHE_TABLES),
            {
                "request", "restock", "category", "model_management",
                "language_management", "maintenance", "inventory",
                "gift_projects", "shipping",
                "order_scheduling",
                "cultural_request",
            },
        )
        source = inspect.getsource(app.render_page_cache_toolbar)
        self.assertNotIn("render_page_update_monitor", source)
        self.assertFalse(hasattr(app, "live_page_poll_snapshot"))


if __name__ == "__main__":
    unittest.main()
