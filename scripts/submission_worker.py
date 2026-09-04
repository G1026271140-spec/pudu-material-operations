from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as inventory_app
from project_config import get_setting
from submission_queue import (
    QUEUE_TASK_TYPE_ORDER_EDIT,
    QUEUE_TASK_TYPE_ORDER_GENERATE,
    QUEUE_TASK_TYPE_ORDER_GENERATE_LEGACY,
    QUEUE_TASK_TYPE_ORDER_PLAN,
    QUEUE_TASK_TYPE_ORDER_RESTOCK,
    QUEUE_STATUS_FAILED,
    QUEUE_TASK_TYPE_CATEGORY_DELETE,
    QUEUE_TASK_TYPE_CATEGORY_SYNC,
    QUEUE_TASK_TYPE_CULTURAL_REQUEST,
    QUEUE_TASK_TYPE_CULTURAL_MANAGEMENT,
    QUEUE_TASK_TYPE_GIFT_PROJECT,
    QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT,
    QUEUE_TASK_TYPE_MATERIAL_REQUEST,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT,
    QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER,
    QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW,
    QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY,
    QUEUE_TASK_TYPE_RESTOCK,
    QUEUE_TASK_TYPE_TRANSACTION_REPLACE,
    QUEUE_TASK_TYPE_TRANSACTION_REVERT,
    SubmissionTask,
    checkpoint_submission_task,
    claim_next_submission_task,
    backfill_submission_completion_status,
    complete_submission_task,
    current_worker_leader,
    ensure_submission_queue_table,
    fail_submission_task,
    retry_failed_submission_tasks,
    update_worker_heartbeat,
)


DEFAULT_POLL_SECONDS = float(get_setting("submission_worker.poll_seconds", 5.0))
DEFAULT_LEASE_SECONDS = int(get_setting("submission_worker.lease_seconds", 600))
MAX_RETRIES = int(get_setting("submission_worker.max_retries", 10))
RELOAD_EXIT_CODE = 75
ALREADY_RUNNING_EXIT_CODE = 76
DEFAULT_WORKER_PRIORITY = int(get_setting("submission_worker.priority", 100))
WORKER_LEADERSHIP_CHECK_INTERVAL_SECONDS = int(get_setting("submission_worker.leadership_check_interval_seconds", 60))
WORKER_HEARTBEAT_INTERVAL_SECONDS = int(get_setting("submission_worker.heartbeat_interval_seconds", 21_600))
WORKER_HEARTBEAT_TIMEOUT_SECONDS = int(get_setting("submission_worker.heartbeat_timeout_seconds", 28_800))
INVENTORY_REVIEW_SCHEDULE_CHECK_INTERVAL_SECONDS = int(get_setting("submission_worker.inventory_review_schedule_check_interval_seconds", 300))
_LEADERSHIP_STATE: dict[str, object] = {
    "checked_at": 0.0,
    "is_leader": False,
    "leader_id": "",
    "heartbeat_at": 0.0,
}
_INVENTORY_REVIEW_SCHEDULER_STATE: dict[str, float] = {"checked_at": 0.0}
SUPPORTED_QUEUE_TASK_TYPES = {
    QUEUE_TASK_TYPE_ORDER_EDIT,
    QUEUE_TASK_TYPE_ORDER_GENERATE,
    QUEUE_TASK_TYPE_ORDER_GENERATE_LEGACY,
    QUEUE_TASK_TYPE_ORDER_PLAN,
    QUEUE_TASK_TYPE_ORDER_RESTOCK,
    QUEUE_TASK_TYPE_MATERIAL_REQUEST,
    QUEUE_TASK_TYPE_CULTURAL_REQUEST,
    QUEUE_TASK_TYPE_CULTURAL_MANAGEMENT,
    QUEUE_TASK_TYPE_RESTOCK,
    QUEUE_TASK_TYPE_CATEGORY_SYNC,
    QUEUE_TASK_TYPE_CATEGORY_DELETE,
    QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,
    QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER,
    QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW,
    QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY,
    QUEUE_TASK_TYPE_TRANSACTION_REVERT,
    QUEUE_TASK_TYPE_TRANSACTION_REPLACE,
    QUEUE_TASK_TYPE_GIFT_PROJECT,
}


def repository_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def worker_node_id() -> str:
    return socket.gethostname().strip().casefold()


def worker_has_leadership(client: object, priority: int) -> bool:
    now = time.monotonic()
    if now - float(_LEADERSHIP_STATE.get("checked_at") or 0) < WORKER_LEADERSHIP_CHECK_INTERVAL_SECONDS:
        return bool(_LEADERSHIP_STATE.get("is_leader"))
    node_id = worker_node_id()
    heartbeat_due = (
        now - float(_LEADERSHIP_STATE.get("heartbeat_at") or 0)
        >= WORKER_HEARTBEAT_INTERVAL_SECONDS
    )
    if heartbeat_due:
        is_leader, leader_id = update_worker_heartbeat(
            client,
            node_id,
            socket.gethostname(),
            priority,
            inventory_app.APP_VERSION,
            heartbeat_timeout_seconds=WORKER_HEARTBEAT_TIMEOUT_SECONDS,
        )
        _LEADERSHIP_STATE["heartbeat_at"] = now
    else:
        leader_id = current_worker_leader(
            client,
            heartbeat_timeout_seconds=WORKER_HEARTBEAT_TIMEOUT_SECONDS,
        ) or node_id
        is_leader = leader_id == node_id
    previous_leader = str(_LEADERSHIP_STATE.get("leader_id") or "")
    _LEADERSHIP_STATE.update(
        {"checked_at": now, "is_leader": is_leader, "leader_id": leader_id}
    )
    if leader_id != previous_leader:
        logging.info(
            "Queue leader is %s; current node=%s priority=%s",
            leader_id,
            node_id,
            priority,
        )
    return is_leader


def configure_logging() -> Path:
    configured_log_dir = os.environ.get("PUDU_SUBMISSION_WORKER_LOG_DIR")
    log_dir = (
        Path(configured_log_dir)
        if configured_log_dir
        else Path(os.environ.get("LOCALAPPDATA") or ROOT / "work")
        / "PuduSubmissionWorker"
        / "logs"
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "worker.log"
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not root_logger.handlers:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
    return log_path


def process_material_request(
    task: SubmissionTask,
    checkpoint: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    request_payload = dict(task.payload.get("request_payload") or {})
    lines = [
        dict(line)
        for line in list(task.payload.get("lines") or [])
        if isinstance(line, dict)
    ]
    submission_token = str(request_payload.get("submission_token") or "").strip()
    if not submission_token or submission_token != task.idempotency_key:
        raise RuntimeError("后台任务的申请幂等键不一致。")

    progress = dict(task.result)
    warnings = [
        str(item)
        for item in list(progress.get("warnings") or [])
        if str(item).strip()
    ]

    def save_progress() -> None:
        progress["warnings"] = list(dict.fromkeys(warnings))
        if checkpoint is not None:
            checkpoint(dict(progress))

    inventory_app.refresh_feishu_schema_cache()
    inventory_app.cleanup_incomplete_submission_rows(submission_token)
    request_no, line_count, created_during_attempt = (
        inventory_app.submit_feishu_material_request(request_payload, lines)
    )
    created_new_request = bool(
        progress.get("created_new_request", created_during_attempt)
    )
    progress.update(
        {
            "request_no": request_no,
            "line_count": line_count,
            "created_new_request": created_new_request,
            "request_persisted": True,
        }
    )
    save_progress()

    if not progress.get("sales_permission_done"):
        try:
            progress["sales_permission_result"] = (
                inventory_app.ensure_requester_sales_permission(request_payload)
            )
        except Exception as exc:
            warnings.append(f"申请人销售权限自动登记失败：{exc}")
            progress["sales_permission_result"] = "failed"
        progress["sales_permission_done"] = True
        save_progress()

    if not progress.get("admin_notification_done"):
        try:
            progress["admin_notification_count"] = (
                inventory_app.notify_enabled_admins_of_material_request(
                    request_no,
                    request_payload,
                    lines,
                )
            )
        except Exception as exc:
            warnings.append(f"管理员通知发送失败：{exc}")
            progress["admin_notification_count"] = 0
        progress["admin_notification_done"] = True
        save_progress()

    if not progress.get("sales_receipt_done"):
        try:
            progress["sales_receipt_count"] = inventory_app.notify_sales_request_received(
                request_no,
                request_payload,
                lines,
            )
        except Exception as exc:
            warnings.append(f"申请人回执发送失败：{exc}")
            progress["sales_receipt_count"] = 0
        progress["sales_receipt_done"] = True
        save_progress()

    return progress


def process_cultural_request(
    task: SubmissionTask,
    checkpoint: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    request_payload = dict(task.payload.get("request_payload") or {})
    lines = [
        dict(line) for line in list(task.payload.get("lines") or []) if isinstance(line, dict)
    ]
    token = str(request_payload.get("submission_token") or "").strip()
    if not token or token != task.idempotency_key:
        raise RuntimeError("后台任务的文化周边申请幂等键不一致。")
    progress = dict(task.result)
    warnings = [str(item) for item in list(progress.get("warnings") or []) if str(item).strip()]

    def save_progress() -> None:
        progress["warnings"] = list(dict.fromkeys(warnings))
        if checkpoint is not None:
            checkpoint(dict(progress))

    if not progress.get("quota_checked"):
        quota = inventory_app.cultural_request_quota_snapshot(request_payload, lines)
        progress.update(
            {
                "quota_checked": True,
                "quota_allowed": bool(quota["allowed"]),
                "quota_current_quantity": int(quota["current_quantity"]),
                "quota_requested_quantity": int(quota["requested_quantity"]),
                "quota_target_quantity": int(quota["target_quantity"]),
                "quota_permission_record_id": str(quota["permission_record_id"]),
            }
        )
        save_progress()

    if not progress.get("quota_allowed"):
        if not progress.get("rejection_notification_done"):
            progress["rejection_notification_counts"] = (
                inventory_app.notify_cultural_request_rejected(
                    request_payload,
                    int(progress.get("quota_current_quantity") or 0),
                    int(progress.get("quota_requested_quantity") or 0),
                )
            )
            progress["rejection_notification_done"] = True
            save_progress()
        progress.update({"rejected": True, "write_done": True, "notification_done": True})
        save_progress()
        return progress

    if not progress.get("quota_reserved") and not progress.get("quota_updated"):
        inventory_app.update_cultural_request_cumulative_quantity(
            str(progress.get("quota_permission_record_id") or ""),
            int(progress.get("quota_target_quantity") or 0),
        )
        progress["quota_reserved"] = True
        progress["quota_updated"] = True
        save_progress()

    if not progress.get("write_done"):
        request_no, line_count, created_new = inventory_app.submit_feishu_cultural_request(
            request_payload, lines
        )
        progress.update(
            {
                "write_done": True,
                "request_no": request_no,
                "line_count": line_count,
                "created_new_request": created_new,
            }
        )
        save_progress()
    if not progress.get("notification_done"):
        try:
            counts = inventory_app.notify_cultural_request(
                str(progress.get("request_no") or ""), request_payload, lines
            )
            progress["notification_counts"] = counts
            inventory_app.feishu_update_record_fields(
                inventory_app.REQUEST_TABLE_NAME,
                inventory_app.feishu_record_id(
                    inventory_app.submission_token_rows(token)[0]
                ),
                {"文化周边通知状态": "已发送"},
            )
        except Exception as exc:
            warnings.append(f"文化周边通知发送失败：{exc}")
            progress["notification_counts"] = {"applicant": 0, "admins": 0}
        progress["notification_done"] = True
        save_progress()
    return progress


def process_task(
    task: SubmissionTask,
    checkpoint: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    if task.task_type in {QUEUE_TASK_TYPE_ORDER_EDIT, QUEUE_TASK_TYPE_ORDER_GENERATE,
                         QUEUE_TASK_TYPE_ORDER_GENERATE_LEGACY,
                         QUEUE_TASK_TYPE_ORDER_PLAN, QUEUE_TASK_TYPE_ORDER_RESTOCK}:
        from order_scheduling_service import SchedulingService
        service = SchedulingService(inventory_app)
        method = {QUEUE_TASK_TYPE_ORDER_EDIT: service.edit,
                  QUEUE_TASK_TYPE_ORDER_GENERATE: service.record_schedule,
                  QUEUE_TASK_TYPE_ORDER_GENERATE_LEGACY: service.record_schedule,
                  QUEUE_TASK_TYPE_ORDER_PLAN: service.plan, QUEUE_TASK_TYPE_ORDER_RESTOCK: service.restock}[task.task_type]
        if checkpoint is None:
            raise RuntimeError("排期写入必须使用持久化检查点，禁止无检查点执行。")
        with inventory_app.DATA_LOCK:
            return method(dict(task.payload), dict(task.result), checkpoint)
    if task.task_type == QUEUE_TASK_TYPE_MATERIAL_REQUEST:
        return process_material_request(task, checkpoint)
    if task.task_type == QUEUE_TASK_TYPE_CULTURAL_REQUEST:
        return process_cultural_request(task, checkpoint)
    if task.task_type == QUEUE_TASK_TYPE_CULTURAL_MANAGEMENT:
        result = inventory_app.execute_cultural_material_management(dict(task.payload.get("draft") or {}))
        return dict(result)
    payload = dict(task.payload)
    if task.task_type == QUEUE_TASK_TYPE_RESTOCK:
        progress = dict(task.result)
        if not progress.get("write_done"):
            lines = inventory_app.submit_inventory_restock(dict(payload["draft"]))
            progress.update({"write_done": True, "lines": lines})
            if checkpoint is not None:
                checkpoint(progress)
        else:
            lines = [dict(item) for item in list(progress.get("lines") or []) if isinstance(item, dict)]
        notified = int(progress.get("notification_count") or 0)
        if not progress.get("notification_done"):
            notified = inventory_app.notify_enabled_admins_of_restock(dict(payload["draft"]), lines)
            progress.update({"notification_done": True, "notification_count": notified})
            if checkpoint is not None:
                checkpoint(progress)
        return {"line_count": len(lines), "notification_count": notified}
    if task.task_type == QUEUE_TASK_TYPE_CATEGORY_SYNC:
        progress = dict(task.result)
        if not progress.get("write_done"):
            sync_result = inventory_app.sync_feishu_category_inventory(
                **inventory_app.deserialize_category_sync_args(dict(payload["sync_args"]))
            )
            result = {
                "target_count": int(sync_result.get("target_count") or 0),
                "created_count": int(sync_result.get("created_count") or 0),
                "updated_count": int(sync_result.get("updated_count") or 0),
                "deleted_count": int(sync_result.get("deleted_count") or 0),
                "quantity_difference": int(sync_result.get("quantity_difference") or 0),
                "target_quantity": int(sync_result.get("target_quantity") or 0),
                "models": list(sync_result.get("models") or []),
                "languages": list(sync_result.get("languages") or []),
            }
            progress.update({"write_done": True, "write_result": result})
            if checkpoint is not None:
                checkpoint(progress)
        else:
            result = dict(progress.get("write_result") or {})
        draft = dict(payload.get("draft") or {})
        notice_kind = str(payload.get("notification_kind") or "")
        notified = int(progress.get("notification_count") or 0)
        if not progress.get("notification_done"):
            if notice_kind == "create":
                notified = inventory_app.notify_enabled_admins_of_category_create(draft, result)
            elif notice_kind == "edit":
                notified = inventory_app.notify_enabled_admins_of_category_edit(draft, result)
            progress.update({"notification_done": True, "notification_count": notified})
            if checkpoint is not None:
                checkpoint(progress)
        return {
            "target_count": int(result.get("target_count") or 0),
            "created_count": int(result.get("created_count") or 0),
            "updated_count": int(result.get("updated_count") or 0),
            "deleted_count": int(result.get("deleted_count") or 0),
            "notification_count": notified,
        }
    if task.task_type == QUEUE_TASK_TYPE_CATEGORY_DELETE:
        progress = dict(task.result)
        draft = dict(payload["draft"])
        if not progress.get("write_done"):
            delete_result = inventory_app.execute_category_delete(
                draft,
                notify_admins=False,
            )
            progress.update({
                "write_done": True,
                "deleted_count": int(delete_result.get("deleted_count") or 0),
            })
            if checkpoint is not None:
                checkpoint(progress)
        notified = int(progress.get("notification_count") or 0)
        if not progress.get("notification_done"):
            notified = inventory_app.notify_enabled_admins_of_category_delete({
                **draft,
                "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            progress.update({"notification_done": True, "notification_count": notified})
            if checkpoint is not None:
                checkpoint(progress)
        return {
            "deleted_count": int(progress.get("deleted_count") or 0),
            "notification_count": notified,
        }
    if task.task_type == QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT:
        progress = dict(task.result)
        draft = dict(payload["draft"])
        if not progress.get("write_done"):
            result = inventory_app.execute_dimension_management(draft)
            progress.update({"write_done": True, "write_result": dict(result)})
            if checkpoint is not None:
                checkpoint(progress)
        else:
            result = dict(progress.get("write_result") or {})
        notified = int(progress.get("notification_count") or 0)
        if not progress.get("notification_done"):
            notified = inventory_app.notify_enabled_admins_of_dimension_management(draft, result)
            progress.update({"notification_done": True, "notification_count": notified})
            if checkpoint is not None:
                checkpoint(progress)
        return {**result, "notification_count": notified}
    if task.task_type == QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT:
        return inventory_app.execute_request_inventory_edit(dict(payload["draft"]))
    if task.task_type == QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM:
        return inventory_app.execute_request_inventory_confirm(dict(payload["draft"]))
    if task.task_type == QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER:
        request_id = str(payload.get("request_id") or "")
        return {
            "request_id": request_id,
            "notification_count": inventory_app.notify_enabled_admins_of_inventory_review_reminder(
                request_id,
                reason="计划核实时间已到",
                mark_scheduled_reminder=True,
            ),
        }
    if task.task_type == QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW:
        return {
            "iso_year": int(payload.get("iso_year") or 0),
            "iso_week": int(payload.get("iso_week") or 0),
            "notification_count": inventory_app.notify_weekly_pending_inventory_reviews(),
        }
    if task.task_type == QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY:
        request_no = str(payload.get("request_no") or "")
        instance_code = str(payload.get("instance_code") or "")
        progress = dict(task.result)
        if inventory_app.approval_writeback_is_complete(request_no):
            if not progress.get("custom_material_cleanup_done"):
                progress["custom_material_cleanup_count"] = (
                    inventory_app.cleanup_custom_materials_for_request(request_no)
                )
                progress["custom_material_cleanup_done"] = True
                if checkpoint is not None:
                    checkpoint(progress)
            if not progress.get("success_notified"):
                progress["success_notification_count"] = (
                    inventory_app.notify_enabled_admins_of_approval_writeback(
                        request_no, instance_code, succeeded=True
                    )
                )
                progress["success_notified"] = True
                if checkpoint is not None:
                    checkpoint(progress)
            return progress
        # A writeback loop can be in progress when an older workflow enqueues
        # this task. Keep early retries silent; only repeated incompleteness is
        # treated as a genuine anomaly.
        if task.retry_count >= 3 and not progress.get("failure_notified"):
            progress["failure_notification_count"] = (
                inventory_app.notify_enabled_admins_of_approval_writeback(
                    request_no, instance_code, succeeded=False
                )
            )
            progress["failure_notified"] = True
            if checkpoint is not None:
                checkpoint(progress)
        raise RuntimeError(f"申请单 {request_no} 的审批回写尚未完整完成，等待修复后重试。")
    if task.task_type == QUEUE_TASK_TYPE_TRANSACTION_REVERT:
        ids = [str(value) for value in list(payload.get("transaction_ids") or [])]
        for transaction_id in ids:
            inventory_app.revert_feishu_transaction(transaction_id, str(payload.get("note") or ""))
        return {"reverted_count": len(ids)}
    if task.task_type == QUEUE_TASK_TYPE_TRANSACTION_REPLACE:
        logs = inventory_app.replace_feishu_transaction(**dict(payload["args"]))
        return {"log_count": len(logs)}
    if task.task_type == QUEUE_TASK_TYPE_GIFT_PROJECT:
        operation = str(payload.get("operation") or "")
        args = dict(payload.get("args") or {})
        if operation == "existing":
            result = inventory_app.create_gift_project_request(**args)
        elif operation == "new":
            result = inventory_app.create_new_gift_project_request(**args)
        elif operation == "batch":
            result = inventory_app.process_gift_project_batch(args)
        else:
            raise RuntimeError(f"不支持的周边礼品任务操作：{operation}")
        if operation == "batch":
            return dict(result)
        return {"completed": True}
    raise RuntimeError(f"不支持的后台任务类型：{task.task_type}")


def notify_terminal_failure(task: SubmissionTask, error: Exception) -> None:
    request_payload = dict(task.payload.get("request_payload") or {})
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    try:
        recipients = list(inventory_app.enabled_admin_open_ids())
    except Exception:
        logging.exception("Loading administrators for terminal task failure failed")
        recipients = []
    if requester_open_id.startswith("ou_"):
        recipients.append(requester_open_id)
    recipients = list(dict.fromkeys(recipient for recipient in recipients if recipient))
    client = inventory_app.feishu_client()
    if client is None:
        return
    message = (
        f"后台写入任务“{task.task_type}”处理失败。任务ID：{task.task_id[:8]}。"
        "任务数据仍保留在“后台任务队列”，请管理员检查 Worker 日志后重试。"
        f"\n错误：{str(error)[:500]}"
    )
    for recipient in recipients:
        try:
            client.send_text_message(recipient, message)
        except Exception:
            logging.exception("Sending terminal task failure notification failed: %s", recipient)


def process_one(
    worker_name: str,
    worker_priority: int = DEFAULT_WORKER_PRIORITY,
) -> bool:
    client = inventory_app.feishu_client()
    if client is None:
        raise RuntimeError("飞书配置缺失，后台任务 Worker 无法启动。")
    if not worker_has_leadership(client, worker_priority):
        return False
    task = claim_next_submission_task(
        client,
        worker_name,
        lease_seconds=DEFAULT_LEASE_SECONDS,
    )
    if task is None:
        return False
    logging.info("Claimed task %s (%s)", task.task_id, task.task_type)
    try:
        result = process_task(
            task,
            checkpoint=lambda progress: checkpoint_submission_task(
                client,
                task,
                progress,
            ),
        )
        complete_submission_task(client, task, result)
        logging.info("Completed task %s: %s", task.task_id, result.get("request_no"))
    except Exception as exc:
        status = fail_submission_task(
            client,
            task,
            exc,
            max_retries=MAX_RETRIES,
        )
        logging.exception("Task %s failed with status %s", task.task_id, status)
        if status == QUEUE_STATUS_FAILED:
            notify_terminal_failure(task, exc)
    return True


def run_forever(poll_seconds: float, worker_priority: int) -> bool:
    name = worker_id()
    started_revision = repository_revision()
    logging.info(
        "Submission worker started: %s; app_version=%s; revision=%s",
        name,
        inventory_app.APP_VERSION,
        started_revision or "unknown",
    )
    while True:
        try:
            scheduler_now = time.monotonic()
            if (
                worker_has_leadership(inventory_app.feishu_client(), worker_priority)
                and scheduler_now - float(_INVENTORY_REVIEW_SCHEDULER_STATE.get("checked_at") or 0)
                >= INVENTORY_REVIEW_SCHEDULE_CHECK_INTERVAL_SECONDS
            ):
                # A temporary Feishu read failure must not turn the normal
                # five-second queue poll into an aggressive Base scan loop.
                _INVENTORY_REVIEW_SCHEDULER_STATE["checked_at"] = scheduler_now
                created = inventory_app.enqueue_inventory_review_scheduled_tasks()
                if created:
                    logging.info("Enqueued %s inventory review reminder tasks", created)
                try:
                    from order_scheduling_service import SchedulingService
                    scheduled = SchedulingService(inventory_app).enqueue_due()
                    if scheduled:
                        logging.info("Enqueued %s order scheduling restock tasks", scheduled)
                except Exception:
                    # Scheduling is isolated; a schema/read failure must not stop existing tasks.
                    logging.exception("Order scheduling scan failed; ordinary queue processing continues")
            processed = process_one(name, worker_priority)
        except Exception:
            logging.exception("Submission worker polling failed")
            processed = False
        if not processed:
            time.sleep(max(1.0, poll_seconds))
        current_revision = repository_revision()
        if started_revision and current_revision and current_revision != started_revision:
            logging.warning(
                "Repository revision changed from %s to %s; reloading worker.",
                started_revision,
                current_revision,
            )
            return True


def acquire_single_instance_mutex() -> int:
    if os.name != "nt":
        return 0
    import ctypes

    kernel32 = ctypes.windll.kernel32
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    create_mutex.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    raw_handle = create_mutex(None, False, "Local\\PuduSubmissionWorker")
    handle = int(raw_handle or 0)
    if not handle:
        raise OSError("无法创建 Windows Worker 单实例锁。")
    if int(kernel32.GetLastError()) == 183:
        close_handle(ctypes.c_void_p(handle))
        return -1
    return handle


def release_single_instance_mutex(handle: int) -> None:
    if os.name == "nt" and handle > 0:
        import ctypes

        close_handle = ctypes.windll.kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        close_handle(ctypes.c_void_p(handle))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PUDU recoverable submission worker")
    parser.add_argument("--once", action="store_true", help="Process queued tasks and exit")
    parser.add_argument("--setup", action="store_true", help="Create or repair the queue table and exit")
    parser.add_argument("--retry-failed", action="store_true", help="Move failed tasks back to pending")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--worker-priority", type=int, default=DEFAULT_WORKER_PRIORITY)
    args = parser.parse_args(argv)

    log_path = configure_logging()
    mutex_handle = acquire_single_instance_mutex()
    if mutex_handle < 0:
        logging.info("Submission worker is already running; retrying takeover shortly.")
        return ALREADY_RUNNING_EXIT_CODE
    try:
        client = inventory_app.feishu_client()
        if client is None:
            raise RuntimeError("飞书配置缺失，后台任务 Worker 无法启动。")
        table_id = ensure_submission_queue_table(client)
        logging.info("Submission queue ready: %s; log=%s", table_id, log_path)
        backfilled = backfill_submission_completion_status(client)
        if backfilled:
            logging.info("Backfilled completion state for %s queue tasks", backfilled)
        if args.setup:
            return 0
        recover_unfinished = args.retry_failed or worker_has_leadership(
            client,
            args.worker_priority,
        )
        if recover_unfinished:
            count = retry_failed_submission_tasks(client)
            logging.info("Recovered %s unfinished failed tasks", count)
        if args.once:
            name = worker_id()
            while process_one(name, args.worker_priority):
                pass
            return 0
        return RELOAD_EXIT_CODE if run_forever(args.poll_seconds, args.worker_priority) else 0
    finally:
        release_single_instance_mutex(mutex_handle)


if __name__ == "__main__":
    sys.exit(main())
