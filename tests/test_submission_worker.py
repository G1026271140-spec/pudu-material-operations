from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import submission_worker as worker
from submission_queue import (
    QUEUE_STATUS_PROCESSING,
    QUEUE_TASK_TYPE_MATERIAL_REQUEST,
    SubmissionTask,
)


def material_request_task(result: dict | None = None) -> SubmissionTask:
    return SubmissionTask(
        record_id="rec-1",
        task_id="task-12345678",
        task_type=QUEUE_TASK_TYPE_MATERIAL_REQUEST,
        idempotency_key="token-1",
        status=QUEUE_STATUS_PROCESSING,
        payload={
            "version": 1,
            "request_payload": {
                "submission_token": "token-1",
                "requester_open_id": "ou_sales",
            },
            "lines": [
                {
                    "product": "产品单页",
                    "model": "BellaBot",
                    "language": "英语",
                    "quantity": 1,
                }
            ],
        },
        submitted_at=1,
        started_at=2,
        completed_at=0,
        lease_expires_at=3,
        retry_count=0,
        next_retry_at=0,
        worker_id="worker",
        result=dict(result or {}),
        error="",
    )


class SubmissionWorkerTests(unittest.TestCase):
    def test_material_request_runs_idempotent_submission_and_notifications(self) -> None:
        task = material_request_task()
        checkpoints: list[dict] = []
        with (
            patch.object(worker.inventory_app, "refresh_feishu_schema_cache"),
            patch.object(
                worker.inventory_app,
                "cleanup_incomplete_submission_rows",
                return_value=1,
            ) as cleanup,
            patch.object(
                worker.inventory_app,
                "submit_feishu_material_request",
                return_value=("REQ-1", 1, True),
            ) as submit,
            patch.object(
                worker.inventory_app,
                "ensure_requester_sales_permission",
                return_value="created",
            ),
            patch.object(
                worker.inventory_app,
                "notify_enabled_admins_of_material_request",
                return_value=2,
            ),
            patch.object(
                worker.inventory_app,
                "notify_sales_request_received",
                return_value=1,
            ),
        ):
            result = worker.process_material_request(task, checkpoints.append)

        cleanup.assert_called_once_with("token-1")
        submit.assert_called_once()
        self.assertEqual(result["request_no"], "REQ-1")
        self.assertEqual(result["admin_notification_count"], 2)
        self.assertEqual(result["sales_receipt_count"], 1)
        self.assertEqual(result["warnings"], [])
        self.assertTrue(result["request_persisted"])
        self.assertTrue(result["admin_notification_done"])
        self.assertGreaterEqual(len(checkpoints), 4)

    def test_checkpointed_notifications_are_not_repeated(self) -> None:
        task = material_request_task(
            {
                "request_no": "REQ-1",
                "line_count": 1,
                "created_new_request": True,
                "request_persisted": True,
                "sales_permission_result": "created",
                "sales_permission_done": True,
                "admin_notification_count": 2,
                "admin_notification_done": True,
                "sales_receipt_count": 1,
                "sales_receipt_done": True,
                "warnings": [],
            }
        )
        with (
            patch.object(worker.inventory_app, "refresh_feishu_schema_cache"),
            patch.object(worker.inventory_app, "cleanup_incomplete_submission_rows"),
            patch.object(
                worker.inventory_app,
                "submit_feishu_material_request",
                return_value=("REQ-1", 1, False),
            ),
            patch.object(
                worker.inventory_app,
                "ensure_requester_sales_permission",
                return_value="existing",
            ),
            patch.object(
                worker.inventory_app,
                "notify_enabled_admins_of_material_request",
            ) as notify_admins,
            patch.object(
                worker.inventory_app,
                "notify_sales_request_received",
            ) as notify_sales,
        ):
            result = worker.process_material_request(task)

        notify_admins.assert_not_called()
        notify_sales.assert_not_called()
        self.assertTrue(result["created_new_request"])


if __name__ == "__main__":
    unittest.main()
