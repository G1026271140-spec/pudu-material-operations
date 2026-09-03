from __future__ import annotations

import json
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from feishu_bitable import FeishuBitableClient
from project_config import get_setting


SUBMISSION_QUEUE_MODULE_VERSION = 2
QUEUE_TABLE_NAME = str(get_setting("feishu.tables.queue", "后台任务队列"))
QUEUE_PAYLOAD_TABLE_NAME = str(get_setting("feishu.tables.queue_payload", "后台任务载荷"))
QUEUE_PAYLOAD_INLINE_LIMIT = int(get_setting("queue.payload_inline_limit", 12_000))
QUEUE_PAYLOAD_CHUNK_SIZE = int(get_setting("queue.payload_chunk_size", 12_000))
QUEUE_PAYLOAD_FIELD_TASK_ID = "任务ID"
QUEUE_PAYLOAD_FIELD_INDEX = "分片序号"
QUEUE_PAYLOAD_FIELD_CONTENT = "分片内容"
WORKER_REGISTRY_TABLE_NAME = str(get_setting("feishu.tables.worker_registry", "后台任务节点列表"))
LEGACY_WORKER_REGISTRY_TABLE_NAME = str(get_setting("feishu.tables.legacy_worker_registry", "后台Worker节点"))
WORKER_FIELD_NODE_ID = "节点标识"
WORKER_FIELD_HOSTNAME = "电脑名称"
WORKER_FIELD_PRIORITY = "优先级"
WORKER_FIELD_HEARTBEAT = "最后心跳时间"
WORKER_FIELD_VERSION = "应用版本"
WORKER_FIELD_STATUS = "节点状态"
WORKER_FIELD_ENABLED = "是否启用"
WORKER_REGISTRY_FIELDS: tuple[tuple[str, int], ...] = (
    (WORKER_FIELD_NODE_ID, 1),
    (WORKER_FIELD_HOSTNAME, 1),
    (WORKER_FIELD_PRIORITY, 2),
    (WORKER_FIELD_HEARTBEAT, 5),
    (WORKER_FIELD_VERSION, 1),
    (WORKER_FIELD_STATUS, 3),
    (WORKER_FIELD_ENABLED, 3),
)
WORKER_SELECT_PROPERTIES: dict[str, dict[str, object]] = {
    WORKER_FIELD_STATUS: {
        "options": [{"name": "在线"}, {"name": "离线"}],
    },
    WORKER_FIELD_ENABLED: {
        "options": [{"name": "是"}, {"name": "否"}],
    },
}
QUEUE_TASK_TYPE_MATERIAL_REQUEST = "营销物料申请"
QUEUE_TASK_TYPE_CULTURAL_REQUEST = "文化周边申领"
QUEUE_TASK_TYPE_CULTURAL_MANAGEMENT = "文化周边管理"
QUEUE_TASK_TYPE_RESTOCK = "采购补库"
QUEUE_TASK_TYPE_CATEGORY_SYNC = "物料品类同步"
QUEUE_TASK_TYPE_CATEGORY_DELETE = "物料品类删除"
QUEUE_TASK_TYPE_TRANSACTION_REVERT = "库存提交撤回"
QUEUE_TASK_TYPE_TRANSACTION_REPLACE = "库存提交修正"
QUEUE_TASK_TYPE_GIFT_PROJECT = "周边礼品项目"
QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT = "型号语种管理"
QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT = "申请物料库存编辑"
QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM = "申请物料库存确认"
QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER = "库存核实定时提醒"
QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW = "每周待核实库存汇总"
QUEUE_TASK_TYPE_APPROVAL_WRITEBACK_NOTIFY = "审批回写管理员通知"
QUEUE_TASK_TYPE_ORDER_EDIT = "下单排期明细编辑"
QUEUE_TASK_TYPE_ORDER_GENERATE = "下单排期生成表单"
QUEUE_TASK_TYPE_ORDER_PLAN = "下单排期日期调整"
QUEUE_TASK_TYPE_ORDER_RESTOCK = "下单排期自动补库"

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
QUEUE_FIELD_COMPLETION_STATUS = "完成状态"
QUEUE_COMPLETION_UNFINISHED = "未完成"
QUEUE_COMPLETION_COMPLETED = "已完成"

QUEUE_SELECT_PROPERTIES: dict[str, dict[str, object]] = {
    QUEUE_FIELD_COMPLETION_STATUS: {
        "options": [
            {"name": QUEUE_COMPLETION_UNFINISHED},
            {"name": QUEUE_COMPLETION_COMPLETED},
        ],
    },
}

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
    (QUEUE_FIELD_COMPLETION_STATUS, 3),
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
    completion_status: str = QUEUE_COMPLETION_UNFINISHED


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
        completion_status=(
            _text(fields.get(QUEUE_FIELD_COMPLETION_STATUS))
            or (
                QUEUE_COMPLETION_COMPLETED
                if _text(fields.get(QUEUE_FIELD_STATUS))
                in {QUEUE_STATUS_COMPLETED, QUEUE_STATUS_CANCELLED}
                else QUEUE_COMPLETION_UNFINISHED
            )
        ),
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
                {
                    "field_name": field_name,
                    "type": field_type,
                    **(
                        {"property": QUEUE_SELECT_PROPERTIES[field_name]}
                        if field_name in QUEUE_SELECT_PROPERTIES
                        else {}
                    ),
                }
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
            client.create_field(
                table_id,
                field_name,
                field_type,
                QUEUE_SELECT_PROPERTIES.get(field_name),
            )
    setattr(client, "_submission_queue_table_id", table_id)
    ensure_submission_payload_table(client)
    ensure_worker_registry_table(client)
    return table_id


def ensure_submission_payload_table(client: FeishuBitableClient) -> str:
    cached = str(getattr(client, "_submission_payload_table_id", "") or "").strip()
    if cached:
        return cached
    matching = [table for table in client.list_tables() if str(table.get("name") or "").strip() == QUEUE_PAYLOAD_TABLE_NAME]
    if matching:
        table_id = str(matching[0].get("table_id") or "").strip()
    else:
        created = client.create_table(
            QUEUE_PAYLOAD_TABLE_NAME,
            [
                {"field_name": QUEUE_PAYLOAD_FIELD_TASK_ID, "type": 1},
                {"field_name": QUEUE_PAYLOAD_FIELD_INDEX, "type": 2},
                {"field_name": QUEUE_PAYLOAD_FIELD_CONTENT, "type": 1},
            ],
            default_view_name="载荷分片",
        )
        table_id = str(created.get("table_id") or "").strip()
    if not table_id:
        raise RuntimeError("后台任务载荷表创建成功但未返回 table_id。")
    setattr(client, "_submission_payload_table_id", table_id)
    return table_id


def ensure_worker_registry_table(client: FeishuBitableClient) -> str:
    cached = str(getattr(client, "_worker_registry_table_id", "") or "").strip()
    if cached:
        return cached
    tables = client.list_tables()
    matching = [
        table for table in tables
        if str(table.get("name") or "").strip() == WORKER_REGISTRY_TABLE_NAME
    ]
    if not matching:
        matching = [
            table for table in tables
            if str(table.get("name") or "").strip() == LEGACY_WORKER_REGISTRY_TABLE_NAME
        ]
        if matching:
            client.update_table_name(
                str(matching[0].get("table_id") or ""),
                WORKER_REGISTRY_TABLE_NAME,
            )
    if matching:
        table_id = str(matching[0].get("table_id") or "").strip()
    else:
        created = client.create_table(
            WORKER_REGISTRY_TABLE_NAME,
            [
                {
                    "field_name": name,
                    "type": field_type,
                    **(
                        {"property": WORKER_SELECT_PROPERTIES[name]}
                        if name in WORKER_SELECT_PROPERTIES else {}
                    ),
                }
                for name, field_type in WORKER_REGISTRY_FIELDS
            ],
            default_view_name="节点列表",
        )
        table_id = str(created.get("table_id") or "").strip()
    if not table_id:
        raise RuntimeError("后台 Worker 节点表创建成功但未返回 table_id。")
    existing_fields = {
        str(field.get("field_name") or "").strip()
        for field in client.list_fields(table_id)
    }
    for field_name, field_type in WORKER_REGISTRY_FIELDS:
        if field_name not in existing_fields:
            client.create_field(
                table_id,
                field_name,
                field_type,
                WORKER_SELECT_PROPERTIES.get(field_name),
            )
    setattr(client, "_worker_registry_table_id", table_id)
    return table_id


def update_worker_heartbeat(
    client: FeishuBitableClient,
    node_id: str,
    hostname: str,
    priority: int,
    version: str,
    *,
    now_ms: int | None = None,
    heartbeat_timeout_seconds: int = 90,
) -> tuple[bool, str]:
    now = timestamp_ms() if now_ms is None else int(now_ms)
    table_id = ensure_worker_registry_table(client)
    records = client.list_records(table_id)
    create_fields = {
        WORKER_FIELD_NODE_ID: node_id,
        WORKER_FIELD_HOSTNAME: hostname,
        WORKER_FIELD_PRIORITY: max(1, int(priority)),
        WORKER_FIELD_HEARTBEAT: now,
        WORKER_FIELD_VERSION: version,
        WORKER_FIELD_STATUS: "在线",
        WORKER_FIELD_ENABLED: "是",
    }
    heartbeat_fields = {
        WORKER_FIELD_HOSTNAME: hostname,
        WORKER_FIELD_HEARTBEAT: now,
        WORKER_FIELD_VERSION: version,
        WORKER_FIELD_STATUS: "在线",
    }
    own_record = next(
        (
            record for record in records
            if _text(dict(record.get("fields") or {}).get(WORKER_FIELD_NODE_ID)) == node_id
        ),
        None,
    )
    if own_record is None:
        client.batch_create_records(table_id, [create_fields])
    else:
        own_fields = dict(own_record.get("fields") or {})
        if not _text(own_fields.get(WORKER_FIELD_ENABLED)):
            heartbeat_fields[WORKER_FIELD_ENABLED] = "是"
        if _integer(own_fields.get(WORKER_FIELD_PRIORITY)) <= 0:
            heartbeat_fields[WORKER_FIELD_PRIORITY] = max(1, int(priority))
        client.update_record(
            table_id,
            str(own_record.get("record_id") or ""),
            heartbeat_fields,
        )
    refreshed = client.list_records(table_id)
    leader_id = select_worker_leader(
        refreshed,
        now_ms=now,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds,
    ) or node_id
    return leader_id == node_id, leader_id


def select_worker_leader(
    records: list[dict[str, Any]],
    *,
    now_ms: int | None = None,
    heartbeat_timeout_seconds: int = 28_800,
) -> str:
    now = timestamp_ms() if now_ms is None else int(now_ms)
    cutoff = now - max(30, int(heartbeat_timeout_seconds)) * 1000
    active: list[tuple[int, str]] = []
    for record in records:
        record_fields = dict(record.get("fields") or {})
        candidate_id = _text(record_fields.get(WORKER_FIELD_NODE_ID))
        heartbeat = _integer(record_fields.get(WORKER_FIELD_HEARTBEAT))
        enabled = _text(record_fields.get(WORKER_FIELD_ENABLED)) or "是"
        if candidate_id and enabled == "是" and heartbeat >= cutoff:
            active.append((max(1, _integer(record_fields.get(WORKER_FIELD_PRIORITY)) or 100), candidate_id))
    return min(active)[1] if active else ""


def current_worker_leader(
    client: FeishuBitableClient,
    *,
    now_ms: int | None = None,
    heartbeat_timeout_seconds: int = 28_800,
) -> str:
    return select_worker_leader(
        client.list_records(ensure_worker_registry_table(client)),
        now_ms=now_ms,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds,
    )


def _load_chunked_payloads(client: FeishuBitableClient, task_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not task_ids:
        return {}
    grouped: dict[str, list[tuple[int, str]]] = {}
    for record in client.list_records(ensure_submission_payload_table(client)):
        fields = dict(record.get("fields") or {})
        task_id = _text(fields.get(QUEUE_PAYLOAD_FIELD_TASK_ID))
        if task_id not in task_ids:
            continue
        grouped.setdefault(task_id, []).append(
            (_integer(fields.get(QUEUE_PAYLOAD_FIELD_INDEX)), _text(fields.get(QUEUE_PAYLOAD_FIELD_CONTENT)))
        )
    resolved: dict[str, dict[str, Any]] = {}
    for task_id, chunks in grouped.items():
        raw = "".join(content for _, content in sorted(chunks))
        try:
            resolved[task_id] = _json_object(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return resolved


def _records_matching_field(
    client: FeishuBitableClient,
    table_id: str,
    field_name: str,
    value: str,
) -> list[dict[str, Any]]:
    search_records = getattr(client, "search_records", None)
    if callable(search_records):
        return list(search_records(table_id, field_name, value))
    return [
        record
        for record in client.list_records(table_id)
        if _text(dict(record.get("fields") or {}).get(field_name)) == value
    ]


def _load_task_payload(
    client: FeishuBitableClient,
    task: SubmissionTask,
) -> SubmissionTask:
    if task.payload.get("storage") != "chunks":
        return task
    records = _records_matching_field(
        client,
        ensure_submission_payload_table(client),
        QUEUE_PAYLOAD_FIELD_TASK_ID,
        task.task_id,
    )
    chunks = sorted(
        (
            _integer(dict(record.get("fields") or {}).get(QUEUE_PAYLOAD_FIELD_INDEX)),
            _text(dict(record.get("fields") or {}).get(QUEUE_PAYLOAD_FIELD_CONTENT)),
        )
        for record in records
    )
    expected_chunks = _integer(task.payload.get("chunks"))
    raw = "".join(content for _, content in chunks)
    expected_hash = _text(task.payload.get("sha256"))
    if len(chunks) != expected_chunks or hashlib.sha256(raw.encode("utf-8")).hexdigest() != expected_hash:
        raise RuntimeError("后台任务载荷分片校验失败。")
    return SubmissionTask(**{**task.__dict__, "payload": _json_object(raw)})


def _tasks_matching_idempotency_key(
    client: FeishuBitableClient,
    table_id: str,
    idempotency_key: str,
) -> list[SubmissionTask]:
    tasks: list[SubmissionTask] = []
    for record in _records_matching_field(
        client,
        table_id,
        QUEUE_FIELD_IDEMPOTENCY_KEY,
        idempotency_key,
    ):
        try:
            task = _load_task_payload(client, task_from_record(record))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if task.record_id and task.task_id and task.status != QUEUE_STATUS_CANCELLED:
            tasks.append(task)
    return tasks


def list_submission_tasks(
    client: FeishuBitableClient,
    table_id: str | None = None,
) -> list[SubmissionTask]:
    resolved_table_id = table_id or ensure_submission_queue_table(client)
    records = client.list_records(resolved_table_id)
    chunk_task_ids: set[str] = set()
    for record in records:
        fields = dict(record.get("fields") or {})
        payload = _json_object(fields.get(QUEUE_FIELD_PAYLOAD))
        task_id = _text(fields.get(QUEUE_FIELD_TASK_ID))
        if payload.get("storage") == "chunks" or (task_id and not payload):
            chunk_task_ids.add(task_id)
    chunked_payloads = _load_chunked_payloads(client, chunk_task_ids)
    tasks: list[SubmissionTask] = []
    for record in records:
        try:
            task = task_from_record(record)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if task.task_id in chunked_payloads:
            task = SubmissionTask(**{**task.__dict__, "payload": chunked_payloads[task.task_id]})
        if task.record_id and task.task_id:
            tasks.append(task)
    return tasks


def _is_feishu_data_not_ready_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return "1254607" in message or "data not ready" in message


def _list_submission_tasks_with_readiness_retry(
    client: FeishuBitableClient,
    table_id: str,
    *,
    attempts: int = 6,
) -> list[SubmissionTask]:
    for attempt in range(attempts):
        try:
            return list_submission_tasks(client, table_id)
        except Exception as exc:
            if not _is_feishu_data_not_ready_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    return []


def _get_submission_task_with_readiness_retry(
    client: FeishuBitableClient,
    table_id: str,
    record_id: str,
    *,
    attempts: int = 6,
) -> SubmissionTask:
    get_record = getattr(client, "get_record", None)
    for attempt in range(attempts):
        try:
            if callable(get_record):
                record = dict(get_record(table_id, record_id))
            else:
                record = next(
                    item
                    for item in client.list_records(table_id)
                    if str(item.get("record_id") or "") == record_id
                )
            return _load_task_payload(client, task_from_record(record))
        except Exception as exc:
            if not _is_feishu_data_not_ready_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("后台任务写入后无法读取。")


def find_task_by_idempotency_key(
    client: FeishuBitableClient,
    idempotency_key: str,
    table_id: str | None = None,
) -> SubmissionTask | None:
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        return None
    resolved_table_id = table_id or ensure_submission_queue_table(client)
    matches = _tasks_matching_idempotency_key(
        client,
        resolved_table_id,
        normalized_key,
    )
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
                    QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
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
                        QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
                    },
                }
            ), False
        return existing, False

    task_id = uuid.uuid4().hex
    serialized_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    stored_payload = serialized_payload
    payload_table_id = ""
    chunk_record_ids: list[str] = []
    if len(serialized_payload) > QUEUE_PAYLOAD_INLINE_LIMIT:
        payload_table_id = ensure_submission_payload_table(client)
        chunks = [serialized_payload[index:index + QUEUE_PAYLOAD_CHUNK_SIZE] for index in range(0, len(serialized_payload), QUEUE_PAYLOAD_CHUNK_SIZE)]
        created_chunks = client.batch_create_records(
            payload_table_id,
            [
                {QUEUE_PAYLOAD_FIELD_TASK_ID: task_id, QUEUE_PAYLOAD_FIELD_INDEX: index, QUEUE_PAYLOAD_FIELD_CONTENT: content}
                for index, content in enumerate(chunks)
            ],
        )
        if len(created_chunks) != len(chunks):
            raise RuntimeError("后台任务载荷分片未完整写入。")
        chunk_record_ids = [str(row.get("record_id") or "") for row in created_chunks]
        stored_payload = json.dumps(
            {"storage": "chunks", "task_id": task_id, "chunks": len(chunks), "sha256": hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    now = timestamp_ms()
    fields = {
        QUEUE_FIELD_TASK_ID: task_id,
        QUEUE_FIELD_TASK_TYPE: task_type,
        QUEUE_FIELD_IDEMPOTENCY_KEY: idempotency_key.strip(),
        QUEUE_FIELD_STATUS: QUEUE_STATUS_PENDING,
        QUEUE_FIELD_PAYLOAD: stored_payload,
        QUEUE_FIELD_SUBMITTED_AT: now,
        QUEUE_FIELD_RETRY_COUNT: 0,
        QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
    }
    created_rows = client.batch_create_records(table_id, [fields])
    if not created_rows:
        for record_id in chunk_record_ids:
            if record_id:
                client.delete_record(payload_table_id, record_id)
        raise RuntimeError("后台任务写入失败，飞书未返回任务记录。")
    created_record = dict(created_rows[0])
    created_record["fields"] = dict(created_record.get("fields") or fields)
    created_task = task_from_record(created_record)
    expected_payload = _json_object(serialized_payload)
    verified = _get_submission_task_with_readiness_retry(
        client,
        table_id,
        created_task.record_id,
    )
    if verified.task_id != task_id or verified.payload != expected_payload:
        raise RuntimeError("后台任务载荷写入后校验失败，任务未可靠入队。")
    created_task = verified

    canonical = find_task_by_idempotency_key(client, idempotency_key, table_id)
    if canonical is not None and canonical.record_id != created_task.record_id:
        client.update_record(
            table_id,
            created_task.record_id,
            {
                QUEUE_FIELD_STATUS: QUEUE_STATUS_CANCELLED,
                QUEUE_FIELD_ERROR: f"重复任务，使用 {canonical.task_id}",
                QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_COMPLETED,
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
            task.completion_status != QUEUE_COMPLETION_COMPLETED
            and (
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
            QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
        },
    )
    # Base does not expose compare-and-swap updates. Re-read the lease after
    # writing it so a worker that lost a near-simultaneous claim never starts
    # the business write. The node registry remains the primary single-leader
    # guard; this ownership check protects failover and overlapping startups.
    claimed = _get_submission_task_with_readiness_retry(
        client,
        table_id,
        task.record_id,
    )
    if (
        claimed.status != QUEUE_STATUS_PROCESSING
        or claimed.worker_id != worker_id
        or claimed.completion_status == QUEUE_COMPLETION_COMPLETED
        or claimed.lease_expires_at != lease_expires_at
    ):
        return None
    return claimed


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
            QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_COMPLETED,
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
            QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
        },
    )
    return status


def retry_failed_submission_tasks(client: FeishuBitableClient) -> int:
    table_id = ensure_submission_queue_table(client)
    failed = [
        task
        for task in list_submission_tasks(client, table_id)
        if task.status == QUEUE_STATUS_FAILED
        and task.completion_status != QUEUE_COMPLETION_COMPLETED
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
                QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
            },
        )
    return len(failed)


def backfill_submission_completion_status(client: FeishuBitableClient) -> int:
    """Populate the business completion marker for legacy queue records once."""
    table_id = ensure_submission_queue_table(client)
    updates: list[dict[str, object]] = []
    for record in client.list_records(table_id):
        fields = dict(record.get("fields") or {})
        if _text(fields.get(QUEUE_FIELD_COMPLETION_STATUS)):
            continue
        completion_status = (
            QUEUE_COMPLETION_COMPLETED
            if _text(fields.get(QUEUE_FIELD_STATUS))
            in {QUEUE_STATUS_COMPLETED, QUEUE_STATUS_CANCELLED}
            else QUEUE_COMPLETION_UNFINISHED
        )
        updates.append(
            {
                "record_id": str(record.get("record_id") or ""),
                "fields": {QUEUE_FIELD_COMPLETION_STATUS: completion_status},
            }
        )
    if updates:
        client.batch_update_records(table_id, updates)
    return len(updates)
