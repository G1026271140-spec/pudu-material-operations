import unittest
import json
from pathlib import Path
from unittest.mock import patch

import app


class RequestLineLimitTests(unittest.TestCase):
    def test_distributor_support_allows_a_line_over_fifty(self) -> None:
        draft = {
            "department": "市场部",
            "requester": "申请人",
            "customer_name": "客户",
            "country": "国家",
            "recipient_info": "收件信息",
            "freight_payer": app.DEFAULT_FREIGHT_PAYER,
            "material_usage": "代理商支持",
            "request_reason": "代理商支持",
            "lines": [
                {"product": "折页", "model": "PuduBot2", "language": "中文", "quantity": 500}
            ],
        }

        self.assertEqual(app.validate_request_draft(draft), [])

    def test_legacy_reason_is_canonicalized_before_queue_write(self) -> None:
        payload = app.queued_material_request_payload(
            {
                "scheduling_version": 1,
                "request_reason": "代理活动",
                "submission_token": "legacy-reason",
            },
            [],
        )

        self.assertEqual(payload["request_payload"]["request_reason"], "代理商支持")

    def test_distributor_label_changes_without_changing_storage_key(self) -> None:
        draft = {
            "request_reason": "代理商支持",
            "customer_name": "测试代理商",
        }

        self.assertEqual(app.request_customer_display_label(draft), "代理商名称")
        self.assertEqual(draft["customer_name"], "测试代理商")

    def test_submission_accepts_more_than_twenty_lines(self) -> None:
        lines = [
            {
                "product": f"product-{index}",
                "model": "model",
                "language": "language",
                "quantity": 1,
            }
            for index in range(25)
        ]

        with (
            patch.object(app, "refresh_feishu_schema_cache"),
            patch.object(
                app,
                "find_completed_submission",
                return_value=({"fields": {"申请单号": "REQ-1"}}, 25),
            ),
        ):
            self.assertEqual(
                app.submit_feishu_material_request({"submission_token": "token"}, lines),
                ("REQ-1", 25, False),
            )

    def test_other_batch_safety_limits_remain_separate(self) -> None:
        self.assertEqual(app.MAX_RESTOCK_LINE_COUNT, 20)
        self.assertEqual(app.MAX_CULTURAL_REQUEST_LINE_COUNT, 20)

    def test_no_ordinary_request_limit_remains_in_ui_or_editing_services(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_source = (root / "app.py").read_text(encoding="utf-8")
        scheduling_page = (root / "order_scheduling_page.py").read_text(encoding="utf-8")
        scheduling_service = (root / "order_scheduling_service.py").read_text(encoding="utf-8")
        config = json.loads((root / "config/project_config.json").read_text(encoding="utf-8"))
        self.assertNotIn("MAX_REQUEST_LINE_COUNT", app_source + scheduling_page + scheduling_service)
        self.assertNotIn("max_request_line_count", config["runtime"])
        self.assertNotIn("最多采购20种物料", app_source)
        self.assertNotIn("超过采购车", app_source)
        self.assertNotIn("is_agent_activity", scheduling_page)
        self.assertNotIn("单一物料明细数量不能超过 50", scheduling_page)


if __name__ == "__main__":
    unittest.main()
