from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class RequestInventoryReviewTests(unittest.TestCase):
    def test_zero_and_negative_inventory_are_insufficient(self) -> None:
        self.assertEqual(
            app.request_inventory_review_result(
                [
                    {"quantity": 1, "current_stock": 0},
                    {"quantity": 1, "current_stock": -2},
                ]
            ),
            app.INVENTORY_RESULT_INSUFFICIENT,
        )
        self.assertEqual(
            app.request_inventory_review_result(
                [
                    {"quantity": 1, "current_stock": 2},
                    {"quantity": 3, "current_stock": 1},
                ]
            ),
            app.INVENTORY_RESULT_PARTIAL,
        )

    def test_confirm_rechecks_inventory_and_writes_review_fields(self) -> None:
        context = {
            "request": {
                "record_id": "request-1",
                "request_no": "REQ-1",
                "inventory_review_status": app.INVENTORY_REVIEW_PENDING,
                "inventory_review_version": 2,
            },
            "lines": [
                {
                    "record_id": "line-1",
                    "current_stock": 0,
                    "inventory_status": "库存不足，需要制作",
                }
            ],
            "result": app.INVENTORY_RESULT_INSUFFICIENT,
        }
        with (
            patch.object(app, "enabled_admin_open_ids", return_value=["ou_admin"]),
            patch.object(app, "request_inventory_review_context", return_value=context),
            patch.object(app, "feishu_datetime_value", return_value=123456),
            patch.object(app, "feishu_batch_update_record_fields", return_value=1) as update_lines,
            patch.object(app, "feishu_update_record_fields") as update_request,
            patch.object(app, "notify_enabled_admins_of_material_request", return_value=1) as notify,
        ):
            result = app.execute_request_inventory_confirm(
                {
                    "request_id": "request-1",
                    "expected_version": 2,
                    "operator_open_id": "ou_admin",
                }
            )

        update_lines.assert_called_once_with(
            app.REQUEST_LINE_TABLE_NAME,
            [
                {
                    "record_id": "line-1",
                    "fields": {
                        "库存审查时库存": "0",
                        "库存满足状态": "库存不足，需要制作",
                    },
                }
            ],
        )
        request_fields = update_request.call_args.args[2]
        self.assertEqual(request_fields["库存审查状态"], app.INVENTORY_REVIEW_CONFIRMED)
        self.assertEqual(request_fields["库存审查结论"], app.INVENTORY_RESULT_INSUFFICIENT)
        self.assertEqual(request_fields["库存审查人"], [{"id": "ou_admin"}])
        notify.assert_called_once()
        self.assertTrue(result["confirmed"])


if __name__ == "__main__":
    unittest.main()
