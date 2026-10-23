"""Durable, lightweight applicant receipts independent of business writes."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


def database_path() -> Path:
    configured = os.environ.get("PUDU_SUBMISSION_RECEIPTS_DB")
    if configured:
        return Path(configured)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PuduMaterialOperations" / "submission_receipts.sqlite3"


def _connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS receipts (
        receipt_key TEXT PRIMARY KEY, recipient TEXT NOT NULL, kind TEXT NOT NULL,
        tasks TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '', message_id TEXT NOT NULL DEFAULT ''
    )""")
    connection.commit()
    return connection


def enqueue(key: str, recipient: str, kind: str, task_ids: list[str]) -> None:
    if not recipient or not task_ids:
        return
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT OR IGNORE INTO receipts(receipt_key,recipient,kind,tasks) VALUES(?,?,?,?)",
            (key, recipient, kind, "、".join(task_ids)),
        )
    _wake.set()


def deliver_pending() -> None:
    import app as legacy
    from request_withdrawal import send_notice

    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT receipt_key,recipient,kind,tasks,attempts FROM receipts "
            "WHERE status='pending' AND retry_at<=? ORDER BY rowid LIMIT 20", (time.time(),),
        ).fetchall()
    for key, recipient, kind, tasks, attempts in rows:
        if _stop.is_set():
            return
        status, error, message_id = "sent", "", ""
        try:
            client = legacy.feishu_client()
            if client is None:
                raise RuntimeError("飞书应用凭据未配置")
            card = {
                "schema": "2.0",
                "header": {"template": "blue", "title": {"tag": "plain_text", "content": "您的申请已提交"}},
                "body": {"elements": [{"tag": "markdown", "content": (
                    f"您的**{kind}**申请已提交，系统正在处理，请勿重复提交。\n\n"
                    f"提交编号：{tasks}\n\n处理结果将另行通知。"
                )}]},
            }
            message_id = send_notice(client, recipient, card, f"submission-receipt:{key}")
        except Exception as exc:
            error = str(exc)[:1000]
            status = "skipped" if '"code":230013' in error.replace(" ", "") else "pending"
            logging.warning("Submission receipt %s: %s", key, error)
        with closing(_connect()) as connection, connection:
            connection.execute(
                "UPDATE receipts SET status=?,attempts=?,retry_at=?,error=?,message_id=? WHERE receipt_key=?",
                (status, attempts + 1, time.time() + min(600, 10 * 2 ** min(attempts, 6)), error, message_id, key),
            )


def _run() -> None:
    while not _stop.is_set():
        _wake.clear()
        try:
            deliver_pending()
        except Exception:
            logging.exception("Submission receipt dispatcher failed")
        _wake.wait(5)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name="submission-receipts", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=1)
