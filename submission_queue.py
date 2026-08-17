from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from feishu_bitable import FeishuBitableClient


QUEUE_TABLE_NAME = "后台任务队列"
QUEUE_TASK_TYPE_MATERIAL_REQUEST = "营销物料申请"
QUEUE_TASK_TYPE_RESTOCK = "采购补库"
QUEUE_TASK_TYPE_CATEGORY_SYNC = "物料品类同步"
QUEUE_TASK_TYPE_CATEGORY_DELETE = "物料品类删除"
QUEUE_TASK_TYPE_TRANSACTION_REVERT = "库存提交撤回"
QUEUE_TASK_TYPE_TRANSACTION_REPLACE = "库存提交修正"
QUEUE_TASK_TYPE_GIFT_PROJECT = "周边礼品项目"

QUEUE_STATUS_PENDING = "待处理"
QUEUE_STATUS_PROCESSING = "处理中"
QUEUE_STATUS_RETRY = "重试中"
QUEUE_STATUS_COMPLETED = "已完成"
QUEUE_STATUS_FAILED = "失败"
QUEUE_STATUS_CANCELLED = "已取消"

QUEUE_FIELD_TASK_ID = "任务ID"
QUEUE_FIELD_TASK_TYPE = "任务类型"
QUEUE_FIELD_IDEMPOTENCY_KEY = "幂等键"
QUEUE_FIELD_STATUS = "状态"
QUEUE_FIELD_PAYLOAD = "载荷JSON"
QUEUE_FIELD_SUBMITTED_AT = "提交时间"
QUEUE_FIELD_STARTED_AT = "开始时间"
QUEUE_FIELD_COMPLETED_AT = "完成时间"
QUEUE_FIELD_LEASE_EXPIRES_AT = "租约到期时间"
QUEUE_FIELD_RETRY_COUNT = "重试次数"
QUEUE_FIELD_NEXT_RETRY_AT = "下次重试时间"
QUEUE_FIELD_WORKER_ID = "Worker标识"
QUEUE_FIELD_RESULT = "结果JSON"
QUEUE_FIELD_ERROR = "错误信息"

QUEUE_FIELDS: tuple[tuple[str, int], ...] = (
    (QUEUE_FIELD_TASK_ID, 1),
    (QUEUE_FIELD_TASK_TYPE, 1),
    (QUEUE_FIELD_IDEMPOTENCY_KEY, 1),
    (QUEUE_FIELD_STATUS, 1),
    (QUEUE_FIELD_PAYLOAD, 1),
    (QUEUE_FIELD_SUBMITTED_AT, 5),
    (QUEUE_FIELD_STARTED_AT, 5),
    (QUEUE_FIELD_COMPLETED_AT, 5),
    (QUEUE_FIELD_LEASE_EXPIRES_AT, 5),
    (QUEUE_FIELD_RETRY_COUNT, 2),
    (QUEUE_FIELD_NEXT_RETRY_AT, 5),
    (QUEUE_FIELD_WORKER_ID, 1),
    (QUEUE_FIELD_RESULT, 1),
    (QUEUE_FIELD_ERROR, 1),
)

ACTIVE_QUEUE_STATUSES = {
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    QUEUE_STATUS_RETRY,
}


@dataclass(frozen=True)
class SubmissionTask:
    record_id: str
    task_id: str
    task_type: str
    idempotency_key: str
    status: str
    payload: dict[str, Any]
    submitted_at: int
    started_at: int
    completed_at: int
    lease_expires_at: int
    retry_count: int
    next_retry_at: int
    worker_id: str
    result: dict[str, Any]
    error: str


def timestamp_ms() -> int:
    return int(time.time() * 1000)


def _text(value: object) -> str:
    if isinstance(value, list):
        return "".join(_text(item) for item in value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value or "").strip()


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _json_object(value: object) -> dict[str, Any]:
    text = _text(value)
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("后台任务 JSON 必须是对象。")
    return parsed


def task_from_record(record: dict[str, Any]) -> SubmissionTask:
    fields = dict(record.get("fields") or {})
    return SubmissionTask(
        record_id=str(record.get("record_id") or "").strip(),
        task_id=_text(fields.get(QUEUE_FIELD_TASK_ID)),
        task_type=_text(fields.get(QUEUE_FIELD_TASK_TYPE)),
        idempotency_key=_text(fields.get(QUEUE_FIELD_IDEMPOTENCY_KEY)),
        status=_text(fields.get(QUEUE_FIELD_STATUS)),
        payload=_json_object(fields.get(QUEUE_FIELD_PAYLOAD)),
        submitted_at=_integer(fields.get(QUEUE_FIELD_SUBMITTED_AT)),
        started_at=_integer(fields.get(QUEUE_FIELD_STARTED_AT)),
        completed_at=_integer(fields.get(QUEUE_FIELD_COMPLETED_AT)),
        lease_expires_at=_integer(fields.get(QUEUE_FIELD_LEASE_EXPIRES_AT)),
        retry_count=_integer(fields.get(QUEUE_FIELD_RETRY_COUNT)),
        next_retry_at=_integer(fields.get(QUEUE_FIELD_NEXT_RETRY_AT)),
        worker_id=_text(fields.get(QUEUE_FIELD_WORKER_ID)),
        result=_json_object(fields.get(QUEUE_FIELD_RESULT)),
        error=_text(fields.get(QUEUE_FIELD_ERROR)),
    )


def ensure_submission_queue_table(client: FeishuBitableClient) -> str:
    cached_table_id = str(
        getattr(client, "_submission_queue_table_id", "") or ""
    ).strip()
    if cached_table_id:
        return cached_table_id
    matching_tables = [
        table
        for table in client.list_tables()
        if str(table.get("name") or "").strip() == QUEUE_TABLE_NAME
    ]
    if matching_tables:
        table_id = str(matching_tables[0].get("table_id") or "").strip()
    else:
        created = client.create_table(
            QUEUE_TABLE_NAME,
            [
                {"field_name": field_name, "type": field_type}
                for field_name, field_type in QUEUE_FIELDS
            ],
            default_view_name="任务列表",
        )
        table_id = str(created.get("table_id") or "").strip()
    if not table_id:
        raise RuntimeError("后台任务队列表创建成功但未返回 table_id。")

    existing_fields = {
        str(field.get("field_name") or "").strip()
        for field in client.list_fields(table_id)
    }
    for field_name, field_type in QUEUE_FIELDS:
        if field_name not in existing_fields:
            client.create_field(table_id, field_name, field_type)
    setattr(client, "_submission_queue_table_id", table_id)
    return table_id


def list_submission_tasks(
    client: FeishuBitableClient,
    table_id: str | None = None,
) -> list[SubmissionTask]:
    resolved_table_id = table_id or ensure_submission_queue_table(client)
    tasks: list[SubmissionTask] = []
    for record in client.list_records(resolved_table_id):
        try:
            task = task_from_record(record)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if task.record_id and task.task_id:
            tasks.append(task)
    return tasks


def find_task_by_idempotency_key(
    client: FeishuBitableClient,
    idempotency_key: str,
    table_id: str | None = None,
) -> SubmissionTask | None:
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        return None
    matches = [
        task
        for task in list_submission_tasks(client, table_id)
        if task.idempotency_key == normalized_key
        and task.status != QUEUE_STATUS_CANCELLED
    ]
    return min(matches, key=lambda task: (task.submitted_at, task.task_id)) if matches else None


def enqueue_submission_task(
    client: FeishuBitableClient,
    task_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> tuple[SubmissionTask, bool]:
    table_id = ensure_submission_queue_table(client)
    existing = find_task_by_idempotency_key(client, idempotency_key, table_id)
    if existing is not None:
        if existing.status == QUEUE_STATUS_FAILED:
            client.update_record(
                table_id,
                existing.record_id,
                {
                    QUEUE_FIELD_STATUS: QUEUE_STATUS_PENDING,
                    QUEUE_FIELD_RETRY_COUNT: 0,
                    QUEUE_FIELD_NEXT_RETRY_AT: None,
                    QUEUE_FIELD_LEASE_EXPIRES_AT: None,
                    QUEUE_FIELD_WORKER_ID: "",
                    QUEUE_FIELD_ERROR: "",
                },
            )
            return task_from_record(
                {
                    "record_id": existing.record_id,
                    "fields": {
                        QUEUE_FIELD_TASK_ID: existing.task_id,
                        QUEUE_FIELD_TASK_TYPE: existing.task_type,
                        QUEUE_FIELD_IDEMPOTENCY_KEY: existing.idempotency_key,
                        QUEUE_FIELD_STATUS: QUEUE_STATUS_PENDING,
                        QUEUE_FIELD_PAYLOAD: json.dumps(existing.payload, ensure_ascii=False),
                        QUEUE_FIELD_SUBMITTED_AT: existing.submitted_at,
                        QUEUE_FIELD_RETRY_COUNT: 0,
                    },
                }
            ), False
        return existing, False

    now = timestamp_ms()
    task_id = uuid.uuid4().hex
    fields = {
        QUEUE_FIELD_TASK_ID: task_id,
        QUEUE_FIELD_TASK_TYPE: task_type,
        QUEUE_FIELD_IDEMPOTENCY_KEY: idempotency_key.strip(),
        QUEUE_FIELD_STATUS: QUEUE_STATUS_PENDING,
        QUEUE_FIELD_PAYLOAD: json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        QUEUE_FIELD_SUBMITTED_AT: now,
        QUEUE_FIELD_RETRY_COUNT: 0,
    }
    created_rows = client.batch_create_records(table_id, [fields])
    if not created_rows:
        raise RuntimeError("后台任务写入失败，飞书未返回任务记录。")
    created_record = dict(created_rows[0])
    created_record["fields"] = dict(created_record.get("fields") or fields)
    created_task = task_from_record(created_record)

    canonical = find_task_by_idempotency_key(client, idempotency_key, table_id)
    if canonical is not None and canonical.record_id != created_task.record_id:
        client.update_record(
            table_id,
            created_task.record_id,
            {
                QUEUE_FIELD_STATUS: QUEUE_STATUS_CANCELLED,
                QUEUE_FIELD_ERROR: f"重复任务，使用 {canonical.task_id}",
            },
        )
        return canonical, False
    return created_task, True


def claim_next_submission_task(
    client: FeishuBitableClient,
    worker_id: str,
    *,
    lease_seconds: int = 600,
    now_ms: int | None = None,
) -> SubmissionTask | None:
    now = timestamp_ms() if now_ms is None else int(now_ms)
    table_id = ensure_submission_queue_table(client)
    eligible = [
        task
        for task in list_submission_tasks(client, table_id)
        if (
            task.status == QUEUE_STATUS_PENDING
            or (
                task.status == QUEUE_STATUS_RETRY
                and task.next_retry_at <= now
            )
            or (
                task.status == QUEUE_STATUS_PROCESSING
                and task.lease_expires_at <= now
            )
        )
    ]
    if not eligible:
        return None
    task = min(eligible, key=lambda item: (item.submitted_at, item.task_id))
    started_at = task.started_at or now
    lease_expires_at = now + max(30, int(lease_seconds)) * 1000
    client.update_record(
        table_id,
        task.record_id,
        {
            QUEUE_FIELD_STATUS: QUEUE_STATUS_PROCESSING,
            QUEUE_FIELD_STARTED_AT: started_at,
            QUEUE_FIELD_LEASE_EXPIRES_AT: lease_expires_at,
            QUEUE_FIELD_WORKER_ID: worker_id,
            QUEUE_FIELD_ERROR: "",
        },
    )
    return SubmissionTask(
        **{
            **task.__dict__,
            "status": QUEUE_STATUS_PROCESSING,
            "started_at": started_at,
            "lease_expires_at": lease_expires_at,
            "worker_id": worker_id,
            "error": "",
        }
    )


def complete_submission_task(
    client: FeishuBitableClient,
    task: SubmissionTask,
    result: dict[str, Any],
    *,
    completed_at: int | None = None,
) -> None:
    table_id = ensure_submission_queue_table(client)
    client.update_record(
        table_id,
        task.record_id,
        {
            QUEUE_FIELD_STATUS: QUEUE_STATUS_COMPLETED,
            QUEUE_FIELD_COMPLETED_AT: timestamp_ms() if completed_at is None else int(completed_at),
            QUEUE_FIELD_LEASE_EXPIRES_AT: None,
            QUEUE_FIELD_NEXT_RETRY_AT: None,
            QUEUE_FIELD_RESULT: json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            QUEUE_FIELD_ERROR: "",
        },
    )


def checkpoint_submission_task(
    client: FeishuBitableClient,
    task: SubmissionTask,
    result: dict[str, Any],
) -> SubmissionTask:
    table_id = ensure_submission_queue_table(client)
    serialized_result = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    client.update_record(
        table_id,
        task.record_id,
        {QUEUE_FIELD_RESULT: serialized_result},
    )
    return SubmissionTask(
        **{
            **task.__dict__,
            "result": dict(result),
        }
    )


def fail_submission_task(
    client: FeishuBitableClient,
    task: SubmissionTask,
    error: Exception | str,
    *,
    max_retries: int = 10,
    now_ms: int | None = None,
) -> str:
    now = timestamp_ms() if now_ms is None else int(now_ms)
    retry_count = task.retry_count + 1
    terminal = retry_count >= max(1, int(max_retries))
    status = QUEUE_STATUS_FAILED if terminal else QUEUE_STATUS_RETRY
    backoff_seconds = min(900, 5 * (3 ** min(retry_count - 1, 5)))
    next_retry_at = None if terminal else now + backoff_seconds * 1000
    table_id = ensure_submission_queue_table(client)
    client.update_record(
        table_id,
        task.record_id,
        {
            QUEUE_FIELD_STATUS: status,
            QUEUE_FIELD_RETRY_COUNT: retry_count,
            QUEUE_FIELD_NEXT_RETRY_AT: next_retry_at,
            QUEUE_FIELD_LEASE_EXPIRES_AT: None,
            QUEUE_FIELD_ERROR: str(error)[:5000],
        },
    )
    return status


def retry_failed_submission_tasks(client: FeishuBitableClient) -> int:
    table_id = ensure_submission_queue_table(client)
    failed = [
        task
        for task in list_submission_tasks(client, table_id)
        if task.status == QUEUE_STATUS_FAILED
    ]
    for task in failed:
        client.update_record(
            table_id,
            task.record_id,
            {
                QUEUE_FIELD_STATUS: QUEUE_STATUS_PENDING,
                QUEUE_FIELD_RETRY_COUNT: 0,
                QUEUE_FIELD_NEXT_RETRY_AT: None,
                QUEUE_FIELD_LEASE_EXPIRES_AT: None,
                QUEUE_FIELD_WORKER_ID: "",
                QUEUE_FIELD_ERROR: "",
            },
        )
    return len(failed)
