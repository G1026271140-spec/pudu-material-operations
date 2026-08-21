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
from submission_queue import (
    QUEUE_STATUS_FAILED,
    QUEUE_TASK_TYPE_CATEGORY_DELETE,
    QUEUE_TASK_TYPE_CATEGORY_SYNC,
    QUEUE_TASK_TYPE_GIFT_PROJECT,
    QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT,
    QUEUE_TASK_TYPE_MATERIAL_REQUEST,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT,
    QUEUE_TASK_TYPE_RESTOCK,
    QUEUE_TASK_TYPE_TRANSACTION_REPLACE,
    QUEUE_TASK_TYPE_TRANSACTION_REVERT,
    SubmissionTask,
    checkpoint_submission_task,
    claim_next_submission_task,
    complete_submission_task,
    ensure_submission_queue_table,
    fail_submission_task,
    retry_failed_submission_tasks,
)


DEFAULT_POLL_SECONDS = 5.0
DEFAULT_LEASE_SECONDS = 600
MAX_RETRIES = 10
RELOAD_EXIT_CODE = 75
ALREADY_RUNNING_EXIT_CODE = 76


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


def process_task(
    task: SubmissionTask,
    checkpoint: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    if task.task_type == QUEUE_TASK_TYPE_MATERIAL_REQUEST:
        return process_material_request(task, checkpoint)
    payload = dict(task.payload)
    if task.task_type == QUEUE_TASK_TYPE_RESTOCK:
        lines = inventory_app.submit_inventory_restock(dict(payload["draft"]))
        notified = inventory_app.notify_enabled_admins_of_restock(dict(payload["draft"]), lines)
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
        return inventory_app.execute_dimension_management(dict(payload["draft"]))
    if task.task_type == QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT:
        return inventory_app.execute_request_inventory_edit(dict(payload["draft"]))
    if task.task_type == QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM:
        return inventory_app.execute_request_inventory_confirm(dict(payload["draft"]))
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


def process_one(worker_name: str) -> bool:
    client = inventory_app.feishu_client()
    if client is None:
        raise RuntimeError("飞书配置缺失，后台任务 Worker 无法启动。")
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


def run_forever(poll_seconds: float) -> bool:
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
            processed = process_one(name)
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
        if args.retry_failed:
            count = retry_failed_submission_tasks(client)
            logging.info("Requeued %s failed tasks", count)
        if args.setup:
            return 0
        if args.once:
            name = worker_id()
            while process_one(name):
                pass
            return 0
        return RELOAD_EXIT_CODE if run_forever(args.poll_seconds) else 0
    finally:
        release_single_instance_mutex(mutex_handle)


if __name__ == "__main__":
    sys.exit(main())
