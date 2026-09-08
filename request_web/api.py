from __future__ import annotations

import hashlib
import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DIST = ROOT / "request_web" / "frontend" / "dist"


def _json(name: str) -> dict[str, Any]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _image_index() -> dict[str, str]:
    page = _json("page_data_cache.json")
    result: dict[str, str] = {}
    for row in page.get("tables", {}).get("物料品类", []):
        fields = row.get("fields", {})
        product = str(fields.get("物料品类") or "").strip()
        attachments = fields.get("申领页图片") or []
        if not product or not attachments:
            continue
        token = str(attachments[0].get("file_token") or "")
        if not token:
            continue
        filename = hashlib.sha256(token.encode()).hexdigest()[:20] + ".webp"
        if (ROOT / "assets" / "request_categories" / filename).is_file():
            result[product] = f"/category-assets/{filename}"
    return result


def build_catalog() -> dict[str, Any]:
    cache = _json("request_form_cache.json")
    contacts = _json("contact_departments_cache.json")
    images = _image_index()
    product_lines = cache.get("model_product_lines", {})
    display_names = cache.get("model_display_names", {})
    category_display_names = cache.get("category_display_names", {})
    page = _json("page_data_cache.json")
    roles_by_user: dict[str, list[str]] = {}
    for row in page.get("tables", {}).get("用户权限表", []):
        fields = row.get("fields", {})
        if str(fields.get("是否启用") or "").strip() != "是":
            continue
        accounts = fields.get("用户账号") or []
        if isinstance(accounts, dict):
            accounts = [accounts]
        for account in accounts:
            open_id = str(account.get("id") or account.get("open_id") or "").strip() if isinstance(account, dict) else ""
            if open_id:
                roles_by_user[open_id] = sorted({str(role) for role in fields.get("角色", []) if str(role).strip()})
    combinations: dict[str, list[dict[str, Any]]] = {}
    for row in cache.get("inventory_rows", []):
        product = str(row.get("product") or "").strip()
        combinations.setdefault(product, []).append(
            {
                "materialCode": row.get("material_code", ""),
                "model": row.get("model", "无需型号"),
                "modelDisplay": display_names.get(row.get("model", "无需型号"), {}).get("zh", row.get("model", "无需型号")),
                "productLine": product_lines.get(row.get("model", "无需型号"), ""),
                "language": row.get("language", "无需语种"),
                "stock": int(row.get("quantity") or 0),
                "unitPriceRmb": float(row.get("unit_price_rmb") or 0),
            }
        )
    return {
        "generatedAt": cache.get("generated_at"),
        "products": [
            {"name": name, "nameDisplay": category_display_names.get(name, {}), "image": images.get(name), "options": combinations.get(name, [])}
            for name in cache.get("products", [])
        ],
        "users": contacts.get("users", []),
        "departments": contacts.get("departments", []),
        "rolesByUser": roles_by_user,
        "reasons": ["代理活动", "展会需求", "客户来访", "其他"],
    }


class MaterialLine(BaseModel):
    product: str
    model: str
    language: str
    quantity: int = Field(gt=0, le=1_000_000)
    remark: str = ""
    current_stock: int = 0
    inventory_status: str = ""
    is_custom_material: bool = False


class RequestDraft(BaseModel):
    title: str
    department: str
    department_id: str = ""
    requester: str
    requester_open_id: str
    customer_name: str
    country: str
    recipient_info: str
    freight_payer: str = "PUDU"
    material_usage: str
    submission_token: str = Field(default_factory=lambda: uuid4().hex)
    scheduling_version: int = 1
    accepted_roles: list[str] = Field(default_factory=list)
    accepted_date: str = ""
    accepted_at_ms: int = 0
    request_reason: str
    arrival_start: str
    arrival_end: str
    lines: list[MaterialLine]


class PasswordAttempt(BaseModel):
    password: str


class CulturalLine(BaseModel):
    product: str
    model: str
    region: str
    quantity: int = Field(gt=0, le=2)
    remark: str = ""


class CulturalDraft(BaseModel):
    requester: str
    requester_open_id: str
    department: str
    department_id: str = ""
    submission_token: str = Field(default_factory=lambda: uuid4().hex)
    lines: list[CulturalLine]


api = FastAPI(title="PUDU Material Operations - Request API")
api.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
api.mount("/category-assets", StaticFiles(directory=ROOT / "assets" / "request_categories"), name="category-assets")
api.mount("/app-assets", StaticFiles(directory=ROOT / "assets"), name="app-assets")
_ADMIN_SESSIONS: set[str] = set()


@api.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/api/catalog")
def catalog() -> dict[str, Any]:
    return build_catalog()


@api.get("/api/cultural-catalog")
def cultural_catalog() -> dict[str, Any]:
    page = _json("page_data_cache.json")
    contacts = _json("contact_departments_cache.json")
    images = _image_index()
    rows = page.get("tables", {}).get("文化周边管理库存", [])
    combinations = []
    for row in rows:
        fields = row.get("fields", {})
        combinations.append({
            "product": _field_text(fields.get("物料品类")),
            "model": _field_text(fields.get("产品型号")),
            "region": _field_text(fields.get("战区管理")),
            "stock": int(fields.get("当前库存") or 0),
            "unitPriceRmb": float(fields.get("单价（人民币）") or 0),
        })
    return {
        "generatedAt": page.get("generated_at"),
        "combinations": combinations,
        "images": images,
        "categoryLabels": _json("request_form_cache.json").get("category_display_names", {}),
        "users": contacts.get("users", []),
        "departments": contacts.get("departments", []),
        "maxTotalQuantity": 2,
    }


@api.post("/api/admin/unlock")
def admin_unlock(attempt: PasswordAttempt, response: Response) -> dict[str, bool]:
    import app as legacy

    if not secrets.compare_digest(attempt.password, legacy.get_approval_password()):
        raise HTTPException(status_code=401, detail="密码不正确")
    token = secrets.token_urlsafe(32)
    _ADMIN_SESSIONS.add(token)
    response.set_cookie("pudu_admin", token, httponly=True, secure=False, samesite="strict", max_age=3600)
    return {"unlocked": True}


def require_admin(pudu_admin: str = Cookie(default="")) -> str:
    if not pudu_admin or pudu_admin not in _ADMIN_SESSIONS:
        raise HTTPException(status_code=401, detail="管理页面需要密码解锁。")
    return pudu_admin


@api.get("/api/admin/status")
def admin_status(pudu_admin: str = Cookie(default="")) -> dict[str, bool]:
    return {"unlocked": bool(pudu_admin and pudu_admin in _ADMIN_SESSIONS)}


def _management_snapshot() -> dict[str, Any]:
    import app as legacy

    page = _json("page_data_cache.json")
    tables = page.get("tables", {})
    category_rows = list(tables.get(legacy.CATEGORY_TABLE_NAME, []))
    material_rows = list(tables.get(legacy.MATERIAL_TABLE_NAME, []))
    model_rows = list(tables.get(legacy.MODEL_TABLE_NAME, []))
    language_rows = list(tables.get(legacy.LANGUAGE_TABLE_NAME, []))
    region_rows = list(tables.get(legacy.REGION_TABLE_NAME, []))
    cultural_rows = list(tables.get(legacy.CULTURAL_MATERIAL_TABLE_NAME, []))
    categories = legacy.feishu_category_records_from_rows(category_rows)
    inventory = legacy.feishu_inventory_records_from_rows(
        material_rows, category_rows, active_only=False
    )
    restock_inventory = [dict(item) for item in inventory]
    inventory_category_keys = {
        legacy.normalize_category_match_key(item.get("category")) for item in inventory
    }
    restock_inventory.extend(
        {
            "record_id": "",
            "material_code": "",
            "category": str(category.get("category") or ""),
            "model": legacy.NO_MODEL_TEXT,
            "language": legacy.NO_LANGUAGE_TEXT,
            "quantity": 0,
            "unit_price": float(category.get("unit_price") or 0),
            "status": str(category.get("status") or legacy.STATUS_INACTIVE),
            "request_visible": str(category.get("request_visible") or legacy.REQUEST_PAGE_HIDDEN_VALUE),
            "synthetic": True,
        }
        for category in categories
        if category.get("no_model")
        and category.get("no_language")
        and legacy.normalize_category_match_key(category.get("category"))
        not in inventory_category_keys
    )
    cultural = legacy.load_cultural_dimension_inventory_records(cultural_rows)
    return {
        "generatedAt": page.get("generated_at"),
        "categories": categories,
        "inventory": inventory,
        "restockInventory": restock_inventory,
        "culturalInventory": cultural,
        "dimensions": {
            "model": legacy.dimension_management_records("model", model_rows),
            "language": legacy.dimension_management_records("language", language_rows),
            "region": legacy.dimension_management_records("region", region_rows),
        },
        "categoryDefinitions": list(legacy.CATEGORY_DEFINITION_OPTIONS),
        "packingTypes": list(legacy.PACKING_LIST_PRODUCT_TYPE_OPTIONS),
        "statuses": list(legacy.MATERIAL_STATUS_OPTIONS),
        "visibilityOptions": list(legacy.REQUEST_PAGE_VISIBILITY_OPTIONS),
        "modelTypes": list(legacy.MODEL_TYPE_OPTIONS),
        "noModelText": legacy.NO_MODEL_TEXT,
        "noLanguageText": legacy.NO_LANGUAGE_TEXT,
        "maxRestockLines": legacy.MAX_RESTOCK_LINE_COUNT,
    }


@api.get("/api/admin/management-catalog")
def management_catalog(_: str = Depends(require_admin)) -> dict[str, Any]:
    return _management_snapshot()


@api.post("/api/admin/restock/submit")
def management_restock_submit(
    draft: dict[str, Any], _: str = Depends(require_admin)
) -> dict[str, Any]:
    import app as legacy
    from submission_queue import QUEUE_TASK_TYPE_RESTOCK

    errors = legacy.validate_restock_draft(draft)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    token = str(draft.get("submission_token") or uuid4().hex)
    normalized = {
        **draft,
        "submission_token": token,
        "restock_no": str(draft.get("restock_no") or legacy.build_restock_no(token)),
    }
    try:
        task_id = _enqueue_fast(
            QUEUE_TASK_TYPE_RESTOCK,
            str(normalized["restock_no"]),
            {"draft": normalized},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"采购补库任务未能进入后台队列：{exc}") from exc
    return {"accepted": True, "taskId": task_id, "restockNo": normalized["restock_no"]}


@api.post("/api/admin/dimension/preview")
def management_dimension_preview(
    draft: dict[str, Any], _: str = Depends(require_admin)
) -> dict[str, Any]:
    import app as legacy

    snapshot = _management_snapshot()
    kind = str(draft.get("kind") or "")
    if kind not in {"model", "language", "region"}:
        raise HTTPException(status_code=422, detail="不支持的基础维度类型。")
    operation = str(draft.get("operation") or "")
    records = list(snapshot["dimensions"][kind])
    record_id = str(draft.get("record_id") or "")
    current = next((item for item in records if item["record_id"] == record_id), None)
    if operation != "create" and current is None:
        raise HTTPException(status_code=422, detail="所选记录不存在，请刷新后重试。")
    name = str(draft.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="请填写名称。")
    duplicate = next(
        (
            item for item in records
            if legacy.normalize_option_label(item["name"]).casefold()
            == legacy.normalize_option_label(name).casefold()
            and item["record_id"] != record_id
        ),
        None,
    )
    if operation != "delete" and duplicate:
        raise HTTPException(status_code=422, detail="名称已经存在。")
    changes = legacy.dimension_association_plan(
        kind,
        operation,
        str((current or {}).get("name") or name),
        name,
        list(draft.get("selected_keys") or []),
        list(snapshot["culturalInventory"] if kind == "region" else snapshot["inventory"]),
        list(snapshot["categories"]),
    )
    return {"draft": {**draft, "changes": changes}, "changes": changes}


@api.post("/api/admin/dimension/submit")
def management_dimension_submit(
    draft: dict[str, Any], _: str = Depends(require_admin)
) -> dict[str, Any]:
    from submission_queue import QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT

    try:
        task_id = _enqueue_fast(
            QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT,
            str(draft.get("submission_token") or uuid4().hex),
            {"draft": draft},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"基础维度任务未能进入后台队列：{exc}") from exc
    return {"accepted": True, "taskId": task_id}


@api.post("/api/admin/category/submit")
def management_category_submit(
    body: dict[str, Any], _: str = Depends(require_admin)
) -> dict[str, Any]:
    import app as legacy
    from submission_queue import QUEUE_TASK_TYPE_CATEGORY_DELETE, QUEUE_TASK_TYPE_CATEGORY_SYNC

    operation = str(body.get("operation") or "")
    token = str(body.get("submission_token") or uuid4().hex)
    try:
        if operation == "delete":
            draft = dict(body.get("draft") or {})
            task_id = _enqueue_fast(
                QUEUE_TASK_TYPE_CATEGORY_DELETE, token, {"draft": draft}
            )
        else:
            raw_sync_args = dict(body.get("sync_args") or {})
            if "target_values_rows" in raw_sync_args and "target_values" not in raw_sync_args:
                raw_sync_args = legacy.deserialize_category_sync_args(raw_sync_args)
            sync_args = legacy.serialize_category_sync_args(raw_sync_args)
            task_id = _enqueue_fast(
                QUEUE_TASK_TYPE_CATEGORY_SYNC,
                token,
                {
                    "sync_args": sync_args,
                    "draft": dict(body.get("draft") or {}),
                    "notification_kind": "create" if operation == "create" else "edit",
                },
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"品类管理任务未能进入后台队列：{exc}") from exc
    return {"accepted": True, "taskId": task_id}


def _field_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(filter(None, (_field_text(item) for item in value)))
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or value.get("id") or "")
    return str(value or "")


@api.get("/api/workspace")
def workspace() -> dict[str, Any]:
    request_cache = _json("request_form_cache.json")
    page = _json("page_data_cache.json")
    tables = page.get("tables", {})

    def rows(table: str, fields: list[str]) -> list[dict[str, Any]]:
        result = []
        for row in tables.get(table, []):
            source = row.get("fields", {})
            result.append({"recordId": row.get("record_id", ""), **{name: _field_text(source.get(name)) for name in fields}})
        return result

    inventory = [
        {
            "物料编码": row.get("material_code", ""), "物料品类": row.get("product", ""),
            "产品型号": row.get("model", ""), "语种": row.get("language", ""),
            "库存数量": int(row.get("quantity") or 0), "单价（人民币）": float(row.get("unit_price_rmb") or 0),
            "库存价值": round(int(row.get("quantity") or 0) * float(row.get("unit_price_rmb") or 0), 2),
        }
        for row in request_cache.get("inventory_rows", [])
    ]
    return {
        "generatedAt": page.get("generated_at"),
        "inventory": inventory,
        "categories": rows("物料品类", ["物料品类", "中文页面名称", "英文页面名称", "品类定义", "启用状态", "是否在申领页显示", "是否无需型号", "是否无需语种"]),
        "models": rows("产品型号", ["产品型号", "中文页面名称", "英文页面名称", "产品线", "型号类型", "启用状态"]),
        "languages": rows("物料语种", ["语种", "中文页面名称", "英文页面名称", "启用状态"]),
        "regions": rows("战区管理", ["战区名称", "中文页面名称", "英文页面名称", "启用状态"]),
        "cultural": rows("文化周边管理库存", ["物料品类", "产品型号", "战区管理", "当前库存", "单价（人民币）", "备注"]),
        "requests": rows("物料申请单", ["申请单号", "标题", "申请人姓名", "申请部门", "审批状态", "库存审查状态", "申请原因", "物料使用时间"]),
        "orderBatches": rows("物料下单批次", ["下单批次号", "批次状态", "生成人", "生成时间", "启用自动补库", "备注"]),
        "warehouse": _json("warehouse_location_cache.json"),
    }


def _validate(draft: RequestDraft, *, live: bool) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    import app as legacy

    data = draft.model_dump()
    lines = data.pop("lines")
    errors = legacy.validate_request_draft(
        {**data, "lines": lines}, include_live_schedule_validation=live
    )
    return data, lines, errors


def _cached_schedule_errors(draft: RequestDraft) -> list[str]:
    """Validate page timing rules from the local permission snapshot only."""
    import order_scheduling as scheduling_rules

    roles = build_catalog().get("rolesByUser", {}).get(draft.requester_open_id) or ["销售"]
    try:
        scheduling_rules.calculate_dates(
            draft.arrival_start,
            draft.arrival_end,
            draft.request_reason,
            list(roles),
            submitted=scheduling_rules.today(),
        )
    except Exception as exc:
        return [str(exc)]
    return []


@lru_cache(maxsize=1)
def _queue_client_and_table() -> tuple[Any, str, str]:
    import app as legacy
    from submission_queue import QUEUE_PAYLOAD_TABLE_NAME, QUEUE_TABLE_NAME

    client = legacy.feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建后台申请任务。")
    tables = client.list_tables()
    table = next((row for row in tables if str(row.get("name") or "").strip() == QUEUE_TABLE_NAME), None)
    table_id = str((table or {}).get("table_id") or "").strip()
    if not table_id:
        raise RuntimeError("未找到后台任务队列表。")
    payload_table = next(
        (row for row in tables if str(row.get("name") or "").strip() == QUEUE_PAYLOAD_TABLE_NAME),
        None,
    )
    payload_table_id = str((payload_table or {}).get("table_id") or "").strip()
    return client, table_id, payload_table_id


def _enqueue_fast(task_type: str, idempotency_key: str, payload: dict[str, Any]) -> str:
    from submission_queue import (
        QUEUE_COMPLETION_UNFINISHED, QUEUE_FIELD_COMPLETION_STATUS,
        QUEUE_FIELD_IDEMPOTENCY_KEY, QUEUE_FIELD_PAYLOAD, QUEUE_FIELD_RETRY_COUNT,
        QUEUE_FIELD_STATUS, QUEUE_FIELD_SUBMITTED_AT, QUEUE_FIELD_TASK_ID,
        QUEUE_FIELD_TASK_TYPE, QUEUE_PAYLOAD_INLINE_LIMIT, QUEUE_STATUS_PENDING,
        QUEUE_PAYLOAD_CHUNK_SIZE, QUEUE_PAYLOAD_FIELD_CONTENT,
        QUEUE_PAYLOAD_FIELD_INDEX, QUEUE_PAYLOAD_FIELD_TASK_ID,
        timestamp_ms,
    )

    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    client, table_id, payload_table_id = _queue_client_and_table()
    task_id = uuid4().hex
    stored_payload = serialized
    chunk_record_ids: list[str] = []
    if len(serialized) > QUEUE_PAYLOAD_INLINE_LIMIT:
        if not payload_table_id:
            raise RuntimeError("未找到后台任务载荷表，无法保存大型任务。")
        chunks = [
            serialized[index:index + QUEUE_PAYLOAD_CHUNK_SIZE]
            for index in range(0, len(serialized), QUEUE_PAYLOAD_CHUNK_SIZE)
        ]
        created_chunks = client.batch_create_records(
            payload_table_id,
            [
                {
                    QUEUE_PAYLOAD_FIELD_TASK_ID: task_id,
                    QUEUE_PAYLOAD_FIELD_INDEX: index,
                    QUEUE_PAYLOAD_FIELD_CONTENT: content,
                }
                for index, content in enumerate(chunks)
            ],
        )
        if len(created_chunks) != len(chunks):
            raise RuntimeError("后台任务载荷分片未完整写入。")
        chunk_record_ids = [str(row.get("record_id") or "") for row in created_chunks]
        stored_payload = json.dumps(
            {
                "storage": "chunks",
                "task_id": task_id,
                "chunks": len(chunks),
                "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    try:
        rows = client.batch_create_records(table_id, [{
            QUEUE_FIELD_TASK_ID: task_id, QUEUE_FIELD_TASK_TYPE: task_type,
            QUEUE_FIELD_IDEMPOTENCY_KEY: idempotency_key, QUEUE_FIELD_STATUS: QUEUE_STATUS_PENDING,
            QUEUE_FIELD_PAYLOAD: stored_payload, QUEUE_FIELD_SUBMITTED_AT: timestamp_ms(),
            QUEUE_FIELD_RETRY_COUNT: 0, QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
        }])
    except Exception:
        for record_id in chunk_record_ids:
            if record_id:
                client.delete_record(payload_table_id, record_id)
        raise
    if not rows:
        for record_id in chunk_record_ids:
            if record_id:
                client.delete_record(payload_table_id, record_id)
        raise RuntimeError("申请未能写入后台任务队列。")
    return task_id


@api.post("/api/validate")
def validate(draft: RequestDraft) -> dict[str, Any]:
    _, _, errors = _validate(draft, live=False)
    if not errors:
        errors.extend(_cached_schedule_errors(draft))
    return {"valid": not errors, "errors": errors}


@api.post("/api/submit")
def submit(draft: RequestDraft) -> dict[str, Any]:
    payload, lines, errors = _validate(draft, live=False)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    try:
        from app import queued_material_request_payload
        from submission_queue import QUEUE_TASK_TYPE_MATERIAL_REQUEST

        task_id = _enqueue_fast(QUEUE_TASK_TYPE_MATERIAL_REQUEST, draft.submission_token, queued_material_request_payload(payload, lines))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"申请未能进入后台队列：{exc}") from exc
    return {"accepted": True, "created": True, "taskId": task_id, "status": "待处理"}


@api.post("/api/cultural-submit")
def cultural_submit(draft: CulturalDraft) -> dict[str, Any]:
    if not draft.requester_open_id or not draft.requester:
        raise HTTPException(status_code=422, detail="请选择申请人。")
    try:
        import app as legacy

        lines = [line.model_dump() for line in draft.lines]
        legacy.validate_cultural_request_quantity(lines)
        from submission_queue import QUEUE_TASK_TYPE_CULTURAL_REQUEST

        request_payload = {key: value for key, value in draft.model_dump().items() if key != "lines"}
        task_id = _enqueue_fast(QUEUE_TASK_TYPE_CULTURAL_REQUEST, draft.submission_token, legacy.queued_cultural_request_payload(request_payload, lines))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"accepted": True, "created": True, "taskId": task_id, "status": "待处理"}


if DIST.is_dir():
    api.mount("/static", StaticFiles(directory=DIST / "assets"), name="request-static")

    @api.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        candidate = (DIST / path).resolve()
        if path and DIST.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
