"""Durable, asynchronous operations alerts; never mutate business/quota data."""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from html import escape
from pathlib import Path

from submission_queue import (
    QUEUE_STATUS_FAILED, QUEUE_STATUS_RETRY,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,
)

_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_dispatch_lock = threading.Lock()


def database_path() -> Path:
    configured = os.environ.get("PUDU_TASK_FAILURE_NOTICES_DB")
    return Path(configured) if configured else (
        Path(os.environ.get("LOCALAPPDATA") or Path.home())
        / "PuduMaterialOperations" / "task_failure_notices.sqlite3"
    )


def _connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS alerts (
        event_key TEXT PRIMARY KEY, event_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', sent_json TEXT NOT NULL DEFAULT '{}',
        attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT ''
    )""")
    connection.commit()
    return connection


def safe_error(error: Exception | str) -> str:
    text = re.sub(r"(?i)Bearer\s+[^\s,\"'}]+", "Bearer [REDACTED]", str(error))
    # Retain the actionable error, not any credentials accidentally included in it.
    text = re.sub(
        r'''(?i)((?:access_token|refresh_token|app_secret|authorization|password)["']?\s*[:=]\s*["']?)([^\s,"'}]+)''',
        r"\1[REDACTED]", text,
    )
    return text[:1800]


def enqueue(task, error: Exception | str, status: str, *, progress: dict | None = None) -> None:
    payload = dict(task.payload)
    request = dict(payload.get("request_payload") or {})
    draft = dict(payload.get("draft") or {})
    result = dict(task.result if progress is None else progress)
    attempt = int(task.retry_count) + 1
    role = "HR" if task.task_type in {
        QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
        QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,
    } else "管理员"
    event = {
        "task_id": task.task_id, "task_type": task.task_type,
        "status": status, "attempt": attempt, "role": role,
        "request_no": result.get("request_no") or payload.get("request_no") or draft.get("request_no") or "",
        "requester": request.get("requester") or draft.get("requester") or "",
        "error": safe_error(error),
        "occurred_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Recovery can reset the retry counter to zero. A new claim/lease must still
    # generate its own alert rather than colliding with an older first attempt.
    key = f"{task.task_id}:{task.lease_expires_at}:{attempt}:{status}"
    with closing(_connect()) as connection, connection:
        connection.execute("INSERT OR IGNORE INTO alerts(event_key,event_json) VALUES(?,?)",
                           (key, json.dumps(event, ensure_ascii=False)))
    _wake.set()


def notification_card(event: dict) -> dict:
    retrying = event["status"] == QUEUE_STATUS_RETRY
    state_write_failed = event["status"] not in {QUEUE_STATUS_RETRY, QUEUE_STATUS_FAILED}
    title = "后台任务重试提醒" if retrying else "后台任务异常提醒"
    action = (
        "该次执行未成功，已安排自动重试；系统将按已有检查点继续处理，请勿重复提交。"
        if retrying else
        "任务数据及已有检查点仍保留在后台任务队列，请检查原因后处理。"
    )
    if state_write_failed:
        action = "任务执行及状态回写出现异常，请检查后台任务队列；本次未能确认自动重试排期。"
    rows = [
        ("任务类型", event["task_type"]), ("任务ID", event["task_id"]),
        ("申请单号", event.get("request_no") or "尚未生成 / 未提供"),
        ("状态", event["status"]), ("本次失败次数", str(event["attempt"])),
        ("发生时间", event["occurred_at"]),
    ]
    if event.get("requester"):
        rows.append(("申请人", event["requester"]))
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default", "summary": {"content": title}},
        "header": {"template": "red", "title": {"tag": "plain_text", "content": title}},
        "body": {"direction": "vertical", "padding": "12px 12px 16px 12px", "elements": [
            {"tag": "markdown", "content": f"**{action}**"},
            {"tag": "table", "page_size": 10, "row_height": "auto", "row_max_height": "124px",
             "header_style": {"background_style": "grey", "bold": True, "lines": 1},
             "columns": [
                 {"name": "field", "display_name": "项目", "data_type": "text", "width": "120px"},
                 {"name": "value", "display_name": "内容", "data_type": "text", "width": "auto"},
             ], "rows": [{"field": label, "value": str(value)} for label, value in rows]},
            {"tag": "markdown", "content": f"异常原因：\n{escape(str(event['error']))}"},
            {"tag": "markdown", "text_size": "notation", "content": (
                "这是上述时间发生的任务异常，不代表申请已驳回；可能已有部分数据写入。当前处理状态请以后台任务队列为准。"
            )},
        ]},
    }


def deliver_pending() -> None:
    import app as legacy
    from request_withdrawal import send_notice

    if not _dispatch_lock.acquire(blocking=False):
        return
    try:
        with closing(_connect()) as connection:
            rows = connection.execute(
                "SELECT event_key,event_json,sent_json,attempts FROM alerts "
                "WHERE status='pending' AND retry_at<=? ORDER BY rowid LIMIT 20", (time.time(),),
            ).fetchall()
        recipients_by_role: dict[str, list[str]] = {}
        for key, event_json, sent_json, attempts in rows:
            if _stop.is_set():
                return
            event, sent = json.loads(event_json), json.loads(sent_json)
            errors = []
            try:
                client = legacy.feishu_client()
                if client is None:
                    raise RuntimeError("飞书应用凭据未配置")
                role = event["role"]
                if role not in recipients_by_role:
                    recipients_by_role[role] = list(dict.fromkeys(
                        legacy.enabled_role_open_ids("HR") if role == "HR" else legacy.enabled_admin_open_ids()
                    ))
                recipients = [value for value in recipients_by_role[role] if value]
                if not recipients:
                    raise RuntimeError(f"未找到已启用的{role}，异常通知等待补发。")
                card = legacy._feishu_normalize_card_tables(notification_card(event))
                for recipient in recipients:
                    if recipient in sent:
                        continue
                    try:
                        message_id = send_notice(client, recipient, card, f"task-failure:{key}:{recipient}")
                    except Exception as exc:
                        errors.append(safe_error(exc))
                        continue  # One unavailable manager must not block the others.
                    sent[recipient] = message_id
                    with closing(_connect()) as connection, connection:
                        connection.execute("UPDATE alerts SET sent_json=? WHERE event_key=?",
                                           (json.dumps(sent), key))
                status = "pending" if errors else "sent"
            except Exception as exc:
                errors.append(safe_error(exc))
                status = "pending"
            with closing(_connect()) as connection, connection:
                connection.execute(
                    "UPDATE alerts SET status=?,attempts=?,retry_at=?,error=? WHERE event_key=?",
                    (status, attempts + 1, time.time() + min(600, 10 * 2 ** min(attempts, 6)),
                     "\n".join(errors)[:2000], key),
                )
            if errors:
                logging.warning("Task failure notification %s deferred: %s", key, "; ".join(errors))
    finally:
        _dispatch_lock.release()


def _run() -> None:
    while not _stop.is_set():
        _wake.clear()
        try:
            deliver_pending()
        except Exception:
            logging.exception("Task failure notification dispatcher failed")
        _wake.wait(5)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name="task-failure-notices", daemon=True)
    _thread.start()
    logging.info("Task failure notification dispatcher started: %s", database_path())


def stop() -> None:
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=1)
