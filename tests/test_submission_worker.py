from __future__ import annotations

import unittest
import threading
import time
from unittest.mock import Mock, patch

from scripts import submission_worker as worker
from submission_queue import (
    QUEUE_STATUS_PROCESSING,
    QUEUE_TASK_TYPE_CATEGORY_DELETE,
    QUEUE_TASK_TYPE_CATEGORY_SYNC,
    QUEUE_TASK_TYPE_CULTURAL_REQUEST,
    QUEUE_TASK_TYPE_CULTURAL_REQUEST_REJECT,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
    QUEUE_TASK_TYPE_MATERIAL_REQUEST,
    QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER,
    QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW,
    QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY,
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


def category_task(
    task_type: str,
    payload: dict,
    result: dict | None = None,
    retry_count: int = 0,
) -> SubmissionTask:
    return SubmissionTask(
        record_id="rec-category",
        task_id="task-category",
        task_type=task_type,
        idempotency_key="category-token",
        status=QUEUE_STATUS_PROCESSING,
        payload=payload,
        submitted_at=1,
        started_at=2,
        completed_at=0,
        lease_expires_at=3,
        retry_count=retry_count,
        next_retry_at=0,
        worker_id="worker",
        result=dict(result or {}),
        error="",
    )


def cultural_request_task(result: dict | None = None) -> SubmissionTask:
    task = material_request_task(result)
    return SubmissionTask(
        **{
            **task.__dict__,
            "task_type": QUEUE_TASK_TYPE_CULTURAL_REQUEST,
            "payload": {
                "version": 1,
                "request_payload": {
                    "submission_token": "token-1",
                    "requester": "申请人",
                    "requester_open_id": "ou_sales",
                },
                "lines": [
                    {
                        "product": "文化POLO衫",
                        "model": "M",
                        "region": "美洲战区",
                        "quantity": 1,
                    }
                ],
            },
        }
    )


class SubmissionWorkerTests(unittest.TestCase):
    def test_duplicate_corporate_task_is_cancelled_before_quota_write(self) -> None:
        original = material_request_task()
        task = SubmissionTask(**{
            **original.__dict__, "task_type": QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
            "result": {},
        })
        client = Mock()
        with (
            patch.object(worker, "find_task_by_idempotency_key", return_value=SubmissionTask(**{
                **task.__dict__, "task_id": "earlier-task", "record_id": "earlier-record",
            })),
            patch.object(worker, "ensure_submission_queue_table", return_value="queue-table"),
            patch.object(worker, "process_task") as process,
        ):
            worker.process_claimed_submission_task(client, task)
        process.assert_not_called()
        client.update_record.assert_called_once_with(
            "queue-table", task.record_id,
            {
                worker.QUEUE_FIELD_STATUS: worker.QUEUE_STATUS_CANCELLED,
                worker.QUEUE_FIELD_ERROR: "重复任务，使用 earlier-task",
                worker.QUEUE_FIELD_COMPLETION_STATUS: worker.QUEUE_COMPLETION_COMPLETED,
            },
        )

    def test_run_forever_processes_notification_while_writer_is_active(self) -> None:
        writer = material_request_task()
        notification = SubmissionTask(**{
            **writer.__dict__, "task_id": "notification-1",
            "task_type": QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
            "result": {"write_plan": {"items": []}, "write_done": True, "request_no": "REQ-1"},
        })
        queued = [writer, notification]
        started: set[str] = set()
        all_started = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        outcome: list[bool] = []

        def fake_claim(_client, _name, *, eligible_predicate, **_kwargs):
            for task in list(queued):
                if eligible_predicate(task):
                    queued.remove(task)
                    return task
            return None

        def fake_process(_client, task):
            with lock:
                started.add(task.task_id)
                if len(started) == 2:
                    all_started.set()
            release.wait(5)

        def revision():
            return "new" if all_started.is_set() else "old"

        previous_checked_at = worker._INVENTORY_REVIEW_SCHEDULER_STATE["checked_at"]
        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker, "worker_has_leadership", return_value=True),
            patch.object(worker, "claim_next_submission_task", side_effect=fake_claim),
            patch.object(worker, "process_claimed_submission_task", side_effect=fake_process),
            patch.object(worker, "repository_revision", side_effect=revision),
            patch.object(worker, "INVENTORY_REVIEW_SCHEDULE_CHECK_INTERVAL_SECONDS", 10**9),
        ):
            worker._INVENTORY_REVIEW_SCHEDULER_STATE["checked_at"] = time.monotonic()
            thread = threading.Thread(target=lambda: outcome.append(worker.run_forever(0, 100)), daemon=True)
            thread.start()
            try:
                self.assertTrue(all_started.wait(5), "writer and notification should overlap")
            finally:
                release.set()
                thread.join(5)
                worker._INVENTORY_REVIEW_SCHEDULER_STATE["checked_at"] = previous_checked_at
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [True])

    def test_parallel_lane_only_admits_checkpointed_corporate_notifications(self) -> None:
        writer = material_request_task()
        notification = SubmissionTask(**{
            **writer.__dict__, "task_id": "notification-1",
            "task_type": QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
            "result": {"write_plan": {"items": []}, "write_done": True, "request_no": "REQ-1"},
        })
        second_notification = SubmissionTask(**{
            **notification.__dict__, "task_id": "notification-2",
        })
        third_notification = SubmissionTask(**{
            **notification.__dict__, "task_id": "notification-3",
        })
        uncheckpointed = SubmissionTask(**{
            **notification.__dict__, "task_id": "not-yet-written", "result": {},
        })

        self.assertTrue(worker.notification_only_task(notification))
        self.assertFalse(worker.notification_only_task(uncheckpointed))
        self.assertTrue(worker.can_run_alongside(notification, [writer]))
        self.assertTrue(worker.can_run_alongside(second_notification, [writer, notification]))
        self.assertFalse(worker.can_run_alongside(third_notification, [writer, notification, second_notification]))
        self.assertFalse(worker.can_run_alongside(uncheckpointed, [writer]))
        self.assertFalse(worker.can_run_alongside(notification, [notification]))
        self.assertTrue(worker.can_run_alongside(writer, [notification]))

    def test_corporate_apparel_reject_marks_notification_complete_after_card_updates(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,
            {"draft": {"request_no": "REQ-1", "operator_open_id": "ou-hr"}},
        )
        client = Mock()
        with (
            patch.object(worker.inventory_app, "corporate_apparel_rejection_plan", return_value={"context": {}}),
            patch.object(worker.inventory_app, "execute_corporate_apparel_rejection", return_value={"request_no": "REQ-1", "rejected": True}),
            patch.object(worker.inventory_app, "feishu_client", return_value=client),
            patch.object(worker.inventory_app, "corporate_apparel_rejection_targets", return_value=[{
                "key": "hr:ou-hr", "recipient_id": "ou-hr", "message_id": "om-card-1", "card": {"schema": "2.0"},
            }]),
            patch.object(worker.inventory_app, "corporate_apparel_request_context", return_value={"request": {"record_id": "request-1"}}),
            patch.object(worker.inventory_app, "feishu_update_record_fields") as update,
        ):
            result = worker.process_corporate_apparel_request_reject(task)

        self.assertTrue(result["notification_done"])
        client.update_interactive_message.assert_called_once_with("om-card-1", {"schema": "2.0"})
        update.assert_called_once_with(
            worker.inventory_app.REQUEST_TABLE_NAME, "request-1", {"文化周边通知状态": "驳回已通知"}
        )

    def test_cultural_reject_reverses_business_write_then_updates_cards(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_CULTURAL_REQUEST_REJECT,
            {"draft": {"request_no": "REQ-1", "operator_open_id": "ou-admin"}},
        )
        client = Mock()
        targets = [{
            "key": "admin:ou-admin",
            "audience": "admins",
            "recipient_id": "ou-admin",
            "message_id": "om-card-1",
            "card": {"schema": "2.0"},
        }]
        checkpoints: list[dict] = []
        with (
            patch.object(
                worker.inventory_app,
                "execute_cultural_request_rejection",
                return_value={"request_no": "REQ-1", "rejected": True},
            ) as reject,
            patch.object(worker.inventory_app, "feishu_client", return_value=client),
            patch.object(
                worker.inventory_app,
                "cultural_request_rejection_targets",
                return_value=targets,
            ),
            patch.object(
                worker.inventory_app,
                "cultural_request_context",
                return_value={"request": {"record_id": "request-1"}, "lines": []},
            ),
            patch.object(worker.inventory_app, "feishu_update_record_fields") as update,
        ):
            result = worker.process_cultural_request_reject(task, checkpoints.append)

        reject.assert_called_once_with(task.payload["draft"])
        client.update_interactive_message.assert_called_once_with(
            "om-card-1", {"schema": "2.0"}
        )
        update.assert_called_once_with(
            worker.inventory_app.REQUEST_TABLE_NAME,
            "request-1",
            {"文化周边通知状态": "驳回已通知"},
        )
        self.assertTrue(result["write_done"])
        self.assertTrue(result["notification_done"])

    def test_inventory_review_reminder_task_sends_current_card(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER,
            {"request_id": "request-1", "scheduled_at_ms": 123},
        )
        with patch.object(
            worker.inventory_app,
            "notify_enabled_admins_of_inventory_review_reminder",
            return_value=2,
        ) as notify:
            result = worker.process_task(task)

        self.assertEqual(result["notification_count"], 2)
        notify.assert_called_once_with(
            "request-1",
            reason="计划核实时间已到",
            mark_scheduled_reminder=True,
        )

    def test_weekly_inventory_review_task_sends_digest(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW,
            {"iso_year": 2026, "iso_week": 36},
        )
        with patch.object(
            worker.inventory_app,
            "notify_weekly_pending_inventory_reviews",
            return_value=2,
        ) as notify:
            result = worker.process_task(task)

        self.assertEqual(result["notification_count"], 2)
        notify.assert_called_once_with()

    def test_cultural_request_rejects_before_business_write_when_quota_exceeded(self) -> None:
        task = cultural_request_task()
        checkpoints: list[dict] = []
        with (
            patch.object(
                worker.inventory_app,
                "cultural_request_quota_snapshot",
                return_value={
                    "allowed": False,
                    "current_quantity": 2,
                    "requested_quantity": 1,
                    "target_quantity": 3,
                    "current_jacket_quantity": 0,
                    "requested_jacket_quantity": 0,
                    "target_jacket_quantity": 0,
                    "quota_label": "文化衫",
                    "quota_limit": 2,
                    "permission_record_id": "rec-permission",
                },
            ),
            patch.object(worker.inventory_app, "notify_cultural_request_rejected", return_value={"applicant": 1, "admins": 2}) as rejected_notice,
            patch.object(worker.inventory_app, "submit_feishu_cultural_request") as submit,
            patch.object(worker.inventory_app, "update_cultural_request_cumulative_quantity") as update_quota,
        ):
            result = worker.process_cultural_request(task, checkpoints.append)

        rejected_notice.assert_called_once()
        submit.assert_not_called()
        update_quota.assert_not_called()
        self.assertTrue(result["rejected"])
        self.assertTrue(result["write_done"])

    def test_cultural_request_updates_quota_after_idempotent_business_write(self) -> None:
        task = cultural_request_task()
        call_order: list[str] = []
        with (
            patch.object(
                worker.inventory_app,
                "cultural_request_quota_snapshot",
                return_value={
                    "allowed": True,
                    "current_quantity": 1,
                    "requested_quantity": 1,
                    "target_quantity": 2,
                    "current_jacket_quantity": 0,
                    "requested_jacket_quantity": 0,
                    "target_jacket_quantity": 0,
                    "quota_label": "文化衫",
                    "quota_limit": 2,
                    "permission_record_id": "rec-permission",
                },
            ),
            patch.object(worker.inventory_app, "submit_feishu_cultural_request", side_effect=lambda *args: (call_order.append("write") or ("REQ-1", 1, True))) as submit,
            patch.object(worker.inventory_app, "update_cultural_request_cumulative_quantity", side_effect=lambda *args: call_order.append("reserve")) as update_quota,
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker.inventory_app, "cultural_request_notification_targets", return_value=[]),
            patch.object(worker.inventory_app, "send_feishu_interactive_message"),
            patch.object(worker.inventory_app, "submission_token_rows", return_value=[{"record_id": "rec-request"}]),
            patch.object(worker.inventory_app, "feishu_update_record_fields"),
        ):
            result = worker.process_cultural_request(task)

        submit.assert_called_once()
        update_quota.assert_called_once_with("rec-permission", 2, 0)
        self.assertEqual(call_order[:2], ["write", "reserve"])
        self.assertTrue(result["quota_reserved"])
        self.assertTrue(result["quota_updated"])

    def test_cultural_request_write_failure_does_not_consume_quota(self) -> None:
        task = cultural_request_task()
        with (
            patch.object(
                worker.inventory_app,
                "cultural_request_quota_snapshot",
                return_value={
                    "allowed": True,
                    "current_quantity": 0,
                    "requested_quantity": 1,
                    "target_quantity": 1,
                    "current_jacket_quantity": 0,
                    "requested_jacket_quantity": 0,
                    "target_jacket_quantity": 0,
                    "quota_label": "文化衫",
                    "quota_limit": 2,
                    "permission_record_id": "rec-permission",
                },
            ),
            patch.object(
                worker.inventory_app,
                "submit_feishu_cultural_request",
                side_effect=RuntimeError("未找到文化周边库存组合"),
            ),
            patch.object(
                worker.inventory_app,
                "update_cultural_request_cumulative_quantity",
            ) as update_quota,
        ):
            with self.assertRaisesRegex(RuntimeError, "未找到文化周边库存组合"):
                worker.process_cultural_request(task)

        update_quota.assert_not_called()

    def test_cultural_request_resumes_quota_after_checkpointed_write(self) -> None:
        task = cultural_request_task({
            "quota_checked": True,
            "quota_allowed": True,
            "quota_target_quantity": 1,
            "quota_target_jacket_quantity": 0,
            "quota_permission_record_id": "rec-permission",
            "write_done": True,
            "request_no": "REQ-1",
        })
        with (
            patch.object(worker.inventory_app, "submit_feishu_cultural_request") as submit,
            patch.object(
                worker.inventory_app,
                "update_cultural_request_cumulative_quantity",
            ) as update_quota,
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker.inventory_app, "cultural_request_notification_targets", return_value=[]),
            patch.object(worker.inventory_app, "submission_token_rows", return_value=[{"record_id": "rec-request"}]),
            patch.object(worker.inventory_app, "feishu_update_record_fields"),
        ):
            result = worker.process_cultural_request(task)

        submit.assert_not_called()
        update_quota.assert_called_once_with("rec-permission", 1, 0)
        self.assertTrue(result["quota_updated"])

    def test_cultural_notification_failure_retries_without_marking_done(self) -> None:
        task = cultural_request_task({
            "quota_checked": True,
            "quota_allowed": True,
            "quota_reserved": True,
            "quota_updated": True,
            "write_done": True,
            "request_no": "REQ-1",
        })
        targets = [{
            "key": "applicant:ou_sales",
            "audience": "applicant",
            "recipient_id": "ou_sales",
            "card": {"schema": "2.0"},
        }]
        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker.inventory_app, "cultural_request_notification_targets", return_value=targets),
            patch.object(worker.inventory_app, "send_feishu_interactive_message", side_effect=RuntimeError("send failed")),
            patch.object(worker.inventory_app, "feishu_update_record_fields") as update,
        ):
            with self.assertRaisesRegex(RuntimeError, "send failed"):
                worker.process_cultural_request(task)
        update.assert_not_called()

    def test_cultural_notification_resume_skips_already_sent_recipient(self) -> None:
        task = cultural_request_task({
            "quota_checked": True,
            "quota_allowed": True,
            "quota_reserved": True,
            "quota_updated": True,
            "write_done": True,
            "request_no": "REQ-1",
            "notification_sent_keys": ["applicant:ou_sales"],
        })
        targets = [
            {"key": "applicant:ou_sales", "audience": "applicant", "recipient_id": "ou_sales", "card": {}},
            {"key": "admin:ou_admin", "audience": "admins", "recipient_id": "ou_admin", "card": {}},
        ]
        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker.inventory_app, "cultural_request_notification_targets", return_value=targets),
            patch.object(worker.inventory_app, "send_feishu_interactive_message") as send,
            patch.object(worker.inventory_app, "submission_token_rows", return_value=[{"record_id": "rec-request"}]),
            patch.object(worker.inventory_app, "feishu_update_record_fields"),
        ):
            result = worker.process_cultural_request(task)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], "ou_admin")
        self.assertTrue(result["notification_done"])

    def test_cultural_unavailable_applicant_is_skipped_but_admin_is_notified(self) -> None:
        task = cultural_request_task({
            "quota_checked": True, "quota_allowed": True, "quota_reserved": True,
            "quota_updated": True, "write_done": True, "request_no": "REQ-1",
        })
        targets = [
            {"key": "applicant:ou_sales", "audience": "applicant", "recipient_id": "ou_sales", "card": {}},
            {"key": "admin:ou_admin", "audience": "admins", "recipient_id": "ou_admin", "card": {}},
        ]
        def send(_client, recipient_id, _card):
            if recipient_id == "ou_sales":
                raise RuntimeError('Feishu HTTP 400: {"code":230013,"msg":"Bot has NO availability to this user."}')
            return "om-admin"
        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker.inventory_app, "cultural_request_notification_targets", return_value=targets),
            patch.object(worker.inventory_app, "send_feishu_interactive_message", side_effect=send) as deliver,
            patch.object(worker.inventory_app, "submission_token_rows", return_value=[{"record_id": "rec-request"}]),
            patch.object(worker.inventory_app, "feishu_update_record_fields"),
        ):
            result = worker.process_cultural_request(task)
        self.assertTrue(result["notification_done"])
        self.assertEqual(result["notification_skipped_keys"], ["applicant:ou_sales"])
        self.assertEqual(result["notification_counts"], {"applicant": 0, "admins": 1})
        self.assertEqual(deliver.call_count, 2)

    def test_corporate_unavailable_applicant_is_skipped_and_hr_receives_card(self) -> None:
        original = material_request_task()
        task = SubmissionTask(**{
            **original.__dict__, "task_type": QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
            "result": {"write_plan": {"items": []}, "write_done": True, "request_no": "REQ-1"},
        })
        targets = [
            {"key": "applicant:ou_sales", "audience": "applicant", "recipient_id": "ou_sales", "card": {}},
            {"key": "hr:ou_hr", "audience": "hr", "recipient_id": "ou_hr", "card": {}},
        ]
        checkpoints: list[dict] = []
        def send(_client, recipient_id, _card):
            if recipient_id == "ou_sales":
                raise RuntimeError('Feishu HTTP 400: {"code":230013,"msg":"Bot has NO availability to this user."}')
            return "om-hr"
        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker.inventory_app, "corporate_apparel_notification_targets", return_value=targets),
            patch.object(worker.inventory_app, "send_feishu_interactive_message", side_effect=send) as deliver,
            patch.object(worker.inventory_app, "corporate_apparel_request_context", return_value={"request": {"record_id": "rec-request"}}),
            patch.object(worker.inventory_app, "feishu_update_record_fields") as update,
            patch.object(worker.inventory_app, "submit_feishu_corporate_apparel_request") as rewrite,
        ):
            result = worker.process_corporate_apparel_request(task, checkpoints.append)
        rewrite.assert_not_called()
        self.assertTrue(result["notification_done"])
        self.assertEqual(result["notification_skipped_keys"], ["applicant:ou_sales"])
        self.assertEqual(result["notification_sent_keys"], ["hr:ou_hr"])
        self.assertEqual(result["notification_count"], 1)
        self.assertEqual(deliver.call_count, 2)
        update.assert_called_once()
        self.assertTrue(any(item.get("notification_skipped_keys") for item in checkpoints))

    def test_unavailable_hr_still_retries_instead_of_being_skipped(self) -> None:
        original = material_request_task()
        task = SubmissionTask(**{
            **original.__dict__, "task_type": QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
            "result": {"write_plan": {"items": []}, "write_done": True, "request_no": "REQ-1"},
        })
        targets = [{"key": "hr:ou_hr", "audience": "hr", "recipient_id": "ou_hr", "card": {}}]
        with (
            patch.object(worker.inventory_app, "feishu_client", return_value=object()),
            patch.object(worker.inventory_app, "corporate_apparel_notification_targets", return_value=targets),
            patch.object(worker.inventory_app, "send_feishu_interactive_message", side_effect=RuntimeError('Feishu HTTP 400: {"code":230013}')),
        ):
            with self.assertRaisesRegex(RuntimeError, "230013"):
                worker.process_corporate_apparel_request(task)

    def test_approval_writeback_success_notifies_and_completes(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY,
            {"request_no": "REQ-1", "instance_code": "instance-1"},
        )
        checkpoints: list[dict] = []
        with (
            patch.object(worker.inventory_app, "approval_writeback_is_complete", return_value=True),
            patch.object(
                worker.inventory_app,
                "cleanup_custom_materials_for_request",
                return_value=2,
            ) as cleanup,
            patch.object(
                worker.inventory_app,
                "notify_enabled_admins_of_approval_writeback",
                return_value=2,
            ) as notify,
        ):
            result = worker.process_task(task, checkpoints.append)

        notify.assert_called_once_with("REQ-1", "instance-1", succeeded=True)
        cleanup.assert_called_once_with("REQ-1")
        self.assertTrue(result["custom_material_cleanup_done"])
        self.assertEqual(result["custom_material_cleanup_count"], 2)
        self.assertTrue(result["success_notified"])
        self.assertEqual(result["success_notification_count"], 2)

    def test_approval_writeback_failure_uses_common_alert_instead_of_duplicate_notice(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY,
            {"request_no": "REQ-1", "instance_code": "instance-1"},
            retry_count=3,
        )
        checkpoints: list[dict] = []
        with (
            patch.object(worker.inventory_app, "approval_writeback_is_complete", return_value=False),
            patch.object(
                worker.inventory_app,
                "notify_enabled_admins_of_approval_writeback",
                return_value=2,
            ) as notify,
        ):
            with self.assertRaisesRegex(RuntimeError, "等待修复后重试"):
                worker.process_task(task, checkpoints.append)

        notify.assert_not_called()
        self.assertEqual(checkpoints, [])

    def test_approval_writeback_in_progress_retries_without_false_alarm(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY,
            {"request_no": "REQ-1", "instance_code": "instance-1"},
        )
        with (
            patch.object(worker.inventory_app, "approval_writeback_is_complete", return_value=False),
            patch.object(
                worker.inventory_app,
                "notify_enabled_admins_of_approval_writeback",
            ) as notify,
        ):
            with self.assertRaisesRegex(RuntimeError, "等待修复后重试"):
                worker.process_task(task)

        notify.assert_not_called()

    def test_category_sync_retry_does_not_repeat_data_write(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_CATEGORY_SYNC,
            {"sync_args": {}, "draft": {"product": "品类A"}, "notification_kind": "edit"},
            {
                "write_done": True,
                "write_result": {"target_count": 2, "updated_count": 2},
            },
        )
        checkpoints: list[dict] = []
        with (
            patch.object(worker.inventory_app, "sync_feishu_category_inventory") as sync,
            patch.object(worker.inventory_app, "notify_enabled_admins_of_category_edit", return_value=3) as notify,
        ):
            result = worker.process_task(task, checkpoints.append)

        sync.assert_not_called()
        notify.assert_called_once()
        self.assertEqual(result["notification_count"], 3)
        self.assertTrue(checkpoints[-1]["notification_done"])

    def test_category_delete_checkpoints_write_before_notification(self) -> None:
        task = category_task(
            QUEUE_TASK_TYPE_CATEGORY_DELETE,
            {"draft": {"category_names": ["品类A"], "records": []}},
        )
        checkpoints: list[dict] = []
        with (
            patch.object(
                worker.inventory_app,
                "execute_category_delete",
                return_value={"deleted_count": 4},
            ) as delete,
            patch.object(worker.inventory_app, "notify_enabled_admins_of_category_delete", return_value=2),
        ):
            result = worker.process_task(task, checkpoints.append)

        delete.assert_called_once_with(task.payload["draft"], notify_admins=False)
        self.assertTrue(checkpoints[0]["write_done"])
        self.assertTrue(checkpoints[-1]["notification_done"])
        self.assertEqual(result, {"deleted_count": 4, "notification_count": 2})

    def test_main_requests_retry_when_another_worker_is_exiting(self) -> None:
        with (
            patch.object(worker, "configure_logging"),
            patch.object(worker, "acquire_single_instance_mutex", return_value=-1),
            patch.object(worker, "release_single_instance_mutex") as release,
        ):
            exit_code = worker.main([])

        self.assertEqual(exit_code, worker.ALREADY_RUNNING_EXIT_CODE)
        release.assert_not_called()

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
