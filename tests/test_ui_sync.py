import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app


class FullscreenSyncTests(unittest.TestCase):
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
        placeholder = MagicMock()
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "empty", return_value=placeholder),
            patch.object(app.time, "sleep"),
        ):
            with app.fullscreen_data_sync("正在保存"):
                self.assertTrue(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])

        self.assertFalse(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])
        placeholder.markdown.assert_called_once()
        placeholder.empty.assert_called_once_with()

    def test_overlay_clears_busy_state_after_failure(self) -> None:
        session_state: dict[str, object] = {}
        placeholder = MagicMock()
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.st, "empty", return_value=placeholder),
            patch.object(app.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                with app.fullscreen_data_sync():
                    raise RuntimeError("write failed")

        self.assertFalse(session_state[app.FULLSCREEN_SYNC_IN_PROGRESS_KEY])
        placeholder.empty.assert_called_once_with()

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

    def test_update_state_only_marks_notice_and_keeps_editor_values(self) -> None:
        session_state: dict[str, object] = {
            "gift_batch_project_name": "项目 A",
            "gift_batch_selected_ids": ["gift-1"],
            "gift_batch_new_line": {"name": "奖牌", "quantity": 20},
        }
        original_editor_values = {
            key: value for key, value in session_state.items()
        }
        with patch.object(app.st, "session_state", session_state):
            changed = app.page_update_state(
                "gift_projects",
                "cached-signature",
                "live-signature",
                "2026-08-14 09:30:00",
            )

        self.assertTrue(changed)
        for key, value in original_editor_values.items():
            self.assertEqual(session_state[key], value)
        self.assertTrue(
            session_state[
                app.page_update_session_key("gift_projects", "update_available")
            ]
        )

    def test_same_signature_does_not_mark_an_update(self) -> None:
        session_state: dict[str, object] = {}
        with patch.object(app.st, "session_state", session_state):
            changed = app.page_update_state("request", "same", "same")

        self.assertFalse(changed)
        self.assertFalse(
            session_state[app.page_update_session_key("request", "update_available")]
        )

    def test_page_polling_covers_every_cached_page(self) -> None:
        self.assertEqual(app.PAGE_DATA_POLL_INTERVAL_SECONDS, 60)
        self.assertEqual(
            set(app.PAGE_CACHE_TABLES),
            {
                "request", "restock", "category", "model_management",
                "language_management", "maintenance", "inventory",
                "gift_projects", "shipping",
            },
        )

    def test_first_monitor_render_defers_live_poll_for_sixty_seconds(self) -> None:
        session_state: dict[str, object] = {}
        with (
            patch.object(app.st, "session_state", session_state),
            patch.object(app.time, "monotonic", return_value=100.0),
            patch.object(app, "live_page_poll_snapshot") as live_poll,
        ):
            app.render_page_update_monitor.__wrapped__("category", "cached-signature")

        live_poll.assert_not_called()
        self.assertEqual(
            session_state[app.page_update_session_key("category", "next_poll_at")],
            160.0,
        )


if __name__ == "__main__":
    unittest.main()
