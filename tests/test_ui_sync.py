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

    def test_success_closes_window_without_rendering_overlay(self) -> None:
        with patch.object(app.st, "html") as html:
            app.close_application_window()

        rendered = html.call_args.args[0]
        self.assertIn("window.close()", rendered)
        self.assertNotIn("pudu-sync-overlay", rendered)
        self.assertNotIn("即将自动关闭应用", rendered)
        html.assert_called_once_with(rendered, unsafe_allow_javascript=True)

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
        spinner = MagicMock()
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "spinner", return_value=spinner) as render_spinner,
        ):
            with app.fullscreen_data_sync("正在保存"):
                self.assertTrue(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])

        self.assertFalse(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])
        render_spinner.assert_called_once_with("正在保存", show_time=False)
        spinner.__enter__.assert_called_once_with()
        spinner.__exit__.assert_called_once()

    def test_overlay_clears_busy_state_after_failure(self) -> None:
        session_state: dict[str, object] = {}
        spinner = MagicMock()
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "spinner", return_value=spinner),
        ):
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                with app.fullscreen_data_sync():
                    raise RuntimeError("write failed")

        self.assertFalse(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])
        spinner.__exit__.assert_called_once()

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


class GiftProjectUpdateMonitorTests(unittest.TestCase):
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
            },
        )
        source = inspect.getsource(app.render_page_cache_toolbar)
        self.assertNotIn("render_page_update_monitor", source)
        self.assertFalse(hasattr(app, "live_page_poll_snapshot"))


if __name__ == "__main__":
    unittest.main()
