"""Near-real-time, idempotent reconciliation after a Base exchange-record webhook."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.reconcile_corporate_apparel_quotas import (
    _chunks,
    _client,
    _int,
    _person_id,
    build_plan,
)

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
OVERLAY_PATH = ROOT / "work" / "corporate_exchange_permission_overlay.json"


def _plan_visible(plan: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    by_record = {str(row.get("record_id") or ""): dict(row.get("fields") or {}) for row in rows}
    by_user = {
        _person_id(dict(row.get("fields") or {}), "用户账号"): dict(row.get("fields") or {})
        for row in rows
    }
    for update in plan["updates"]:
        fields = by_record.get(str(update["record_id"]), {})
        if any(_int(fields.get(name)) < int(value) for name, value in update["fields"].items()):
            return False
    for create in plan["creates"]:
        open_id = _person_id(create, "用户账号")
        fields = by_user.get(open_id, {})
        if not fields or any(
            _int(fields.get(name)) < int(value)
            for name, value in create.items()
            if name not in {"用户编号", "用户账号", "角色", "是否启用"}
        ):
            return False
    return True


def reconcile_and_publish_overlay() -> dict[str, int]:
    """Use authoritative Base rows; never add a webhook's quantity blindly."""
    client = _client()
    plan = build_plan(client)
    for chunk in _chunks(plan["updates"]):
        client.batch_update_records(plan["table_id"], chunk)
    for chunk in _chunks(plan["creates"]):
        client.batch_create_records(plan["table_id"], chunk)

    rows: list[dict[str, Any]] = []
    for attempt in range(6):
        rows = client.list_records(plan["table_id"])
        if _plan_visible(plan, rows):
            break
        if attempt < 5:
            time.sleep(1)
    else:
        raise RuntimeError("兑换份额已写入，但权限表尚未返回最新值；等待定时任务补偿。")

    OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = OVERLAY_PATH.with_name(f"{OVERLAY_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps({"generated_at": datetime.now().isoformat(), "rows": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, OVERLAY_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    return {"updated": len(plan["updates"]), "created": len(plan["creates"])}


def current_permission_rows(cache_path: Path, cached_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer a webhook-published permission snapshot newer than the static cache."""
    try:
        if OVERLAY_PATH.stat().st_mtime_ns <= cache_path.stat().st_mtime_ns:
            return cached_rows
        data = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
        rows = data.get("rows")
        return rows if isinstance(rows, list) else cached_rows
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return cached_rows


class ExchangeSyncRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="exchange-sync")
        self._running = False
        self._pending: set[str] = set()
        self.last_result: dict[str, Any] = {}

    def trigger(self, record_id: str) -> None:
        with self._lock:
            self._pending.add(record_id)
            if self._running:
                return
            self._running = True
            self._executor.submit(self._run)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"running": self._running, "pending": len(self._pending),
                    "last_result": dict(self.last_result)}

    def _run(self) -> None:
        while True:
            with self._lock:
                records = sorted(self._pending)
                self._pending.clear()
            try:
                result = reconcile_and_publish_overlay()
                with self._lock:
                    self.last_result = {"status": "ok", "records": len(records), **result}
                LOGGER.info("Corporate exchange sync completed for %s record(s): %s", len(records), result)
            except Exception as exc:
                with self._lock:
                    self.last_result = {"status": "failed", "records": len(records), "error": str(exc)}
                LOGGER.exception("Corporate exchange sync failed")
            with self._lock:
                if not self._pending:
                    self._running = False
                    return


runner = ExchangeSyncRunner()
