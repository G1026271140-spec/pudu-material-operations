"""Local, disposable index of ordinary requests awaiting inventory review.

Feishu remains authoritative.  Only pending request rows and their request-line
rows live here; confirmed/rejected requests are removed transactionally.
"""
from __future__ import annotations

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def database_path() -> Path:
    configured = os.getenv("PUDU_PENDING_INVENTORY_DB", "").strip()
    if configured:
        return Path(configured)
    local = os.getenv("LOCALAPPDATA")
    return Path(local) / "PuduMaterialOperations" / "pending_inventory.sqlite3" if local else Path.home() / ".pudu-material-operations" / "pending_inventory.sqlite3"


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=15000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS pending_requests (
            request_id TEXT PRIMARY KEY,
            request_no TEXT NOT NULL,
            request_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pending_lines (
            line_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES pending_requests(request_id) ON DELETE CASCADE,
            line_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS pending_lines_request_id ON pending_lines(request_id);
        CREATE TABLE IF NOT EXISTS pending_review_actions (
            action_key TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            draft_json TEXT NOT NULL,
            status TEXT NOT NULL,
            task_id TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS pending_review_actions_request_id
            ON pending_review_actions(request_id);
    """)
    return connection


def _record_id(row: dict) -> str:
    return str(row.get("record_id") or row.get("id") or "").strip()


def _field_text(fields: dict, name: str) -> str:
    value = fields.get(name)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(str(v.get("text") or "") if isinstance(v, dict) else str(v) for v in value).strip()
    return str(value or "").strip()


def is_pending(request_row: dict) -> bool:
    fields = dict(request_row.get("fields") or {})
    return (
        _field_text(fields, "申请类型") == "普通物料申请"
        and _field_text(fields, "审批状态") == "待审批"
        and _field_text(fields, "库存审查状态") != "已核实库存"
    )


def upsert(request_row: dict, line_rows: list[dict]) -> bool:
    request_id = _record_id(request_row)
    if not request_id:
        raise ValueError("申请单缺少飞书记录 ID")
    if not is_pending(request_row):
        delete(request_id)
        return False
    request_no = _field_text(dict(request_row.get("fields") or {}), "申请单号")
    if not request_no:
        raise ValueError("申请单缺少申请单号")
    if not line_rows:
        raise ValueError("未核实申请单缺少申请明细，拒绝缓存不完整单据")
    prepared = []
    for row in line_rows:
        line_id = _record_id(row)
        if not line_id:
            raise ValueError("申请明细缺少飞书记录 ID")
        prepared.append((line_id, request_id, json.dumps(row, ensure_ascii=False, default=str)))
    with _connect() as connection:
        connection.execute(
            "INSERT INTO pending_requests(request_id,request_no,request_json,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(request_id) DO UPDATE SET request_no=excluded.request_no, "
            "request_json=excluded.request_json,updated_at=excluded.updated_at",
            (request_id, request_no, json.dumps(request_row, ensure_ascii=False, default=str),
             datetime.now(timezone.utc).isoformat()),
        )
        connection.execute("DELETE FROM pending_lines WHERE request_id=?", (request_id,))
        connection.executemany(
            "INSERT INTO pending_lines(line_id,request_id,line_json) VALUES(?,?,?)", prepared
        )
    return True


def delete(request_id: str) -> None:
    if not request_id:
        return
    with _connect() as connection:
        connection.execute("DELETE FROM pending_review_actions WHERE request_id=?", (request_id,))
        connection.execute("DELETE FROM pending_requests WHERE request_id=?", (request_id,))


def stage_action(action_key: str, request_id: str, operation: str, draft: dict) -> None:
    if not action_key or not request_id or operation not in {"edit", "confirm", "reject"}:
        raise ValueError("配货操作缺少有效的申请单、类型或提交标识")
    serialized = json.dumps(draft, ensure_ascii=False, sort_keys=True, default=str)
    with _connect() as connection:
        existing = connection.execute(
            "SELECT request_id,operation,draft_json FROM pending_review_actions WHERE action_key=?",
            (action_key,),
        ).fetchone()
        if existing:
            if existing != (request_id, operation, serialized):
                raise ValueError("同一配货提交标识已用于不同操作")
            return
        connection.execute(
            "INSERT INTO pending_review_actions(action_key,request_id,operation,draft_json,status,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (action_key, request_id, operation, serialized, "staged", datetime.now(timezone.utc).isoformat()),
        )


def mark_action(action_key: str, status: str, *, task_id: str = "", error: str = "") -> None:
    if status not in {"queued", "failed"}:
        raise ValueError("无效的本机配货操作状态")
    with _connect() as connection:
        connection.execute(
            "UPDATE pending_review_actions SET status=?,task_id=?,error=? WHERE action_key=?",
            (status, task_id, error[:500], action_key),
        )


def get(request_id: str) -> tuple[dict, list[dict]] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT request_json FROM pending_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if not row:
            return None
        lines = connection.execute(
            "SELECT line_json FROM pending_lines WHERE request_id=? ORDER BY line_id", (request_id,)
        ).fetchall()
    return json.loads(row[0]), [json.loads(line[0]) for line in lines]


def list_pending() -> list[tuple[dict, int, str]]:
    with _connect() as connection:
        rows = connection.execute("""
            SELECT r.request_json, COUNT(l.line_id), r.updated_at
            FROM pending_requests r LEFT JOIN pending_lines l ON l.request_id=r.request_id
            GROUP BY r.request_id ORDER BY r.updated_at DESC
        """).fetchall()
    return [(json.loads(row), count, updated_at) for row, count, updated_at in rows]


def refresh_from_feishu(request_id: str) -> bool:
    """Handle an automation event using direct records, never a full-table scan."""
    import app as legacy

    client = legacy.feishu_client()
    if client is None:
        raise RuntimeError("飞书应用凭据未配置")
    row = client.get_record(legacy.feishu_table_id(legacy.REQUEST_TABLE_NAME), request_id)
    if not row or not is_pending(row):
        delete(request_id)
        return False
    lines = _lines_for_request(client, legacy, row)
    return upsert(row, lines)


def _lines_for_request(client: object, legacy: object, row: dict) -> list[dict]:
    fields = dict(row.get("fields") or {})
    line_table = legacy.feishu_table_id(legacy.REQUEST_LINE_TABLE_NAME)
    line_ids = legacy.feishu_link_ids_any(fields, ["申请明细", "关联申请明细"])
    if line_ids:
        with ThreadPoolExecutor(max_workers=min(8, len(line_ids))) as executor:
            return list(executor.map(lambda line_id: client.get_record(line_table, line_id), line_ids))
    # Manually created requests may not have the reverse-link populated yet.
    request_id = _record_id(row)
    request_no = _field_text(fields, "申请单号")
    return [
        line for line in client.list_records(line_table)
        if request_id in legacy.feishu_link_ids_any(dict(line.get("fields") or {}), ["所属申请单", "申请单"])
        or _field_text(dict(line.get("fields") or {}), "申请单号") == request_no
    ]


def reconcile_live() -> dict[str, int]:
    """Repair missed events.  Read Feishu first; never clear SQLite on a failed read."""
    import app as legacy

    client = legacy.feishu_client()
    if client is None:
        raise RuntimeError("飞书应用凭据未配置")
    request_table = legacy.feishu_table_id(legacy.REQUEST_TABLE_NAME)
    pending = [row for row in client.list_records(request_table) if is_pending(row)]
    complete: list[tuple[dict, list[dict]]] = []
    for row in pending:
        request_no = _field_text(dict(row.get("fields") or {}), "申请单号")
        lines = _lines_for_request(client, legacy, row)
        if not lines:
            raise RuntimeError(f"申请单 {request_no} 尚无明细，暂不替换本机索引")
        complete.append((row, lines))
    existing_ids = {_record_id(row) for row, _, _ in list_pending()}
    current_ids = {_record_id(row) for row, _ in complete}
    for row, lines in complete:
        upsert(row, lines)
    for request_id in existing_ids - current_ids:
        delete(request_id)
    return {"pending": len(complete), "removed": len(existing_ids - current_ids)}
