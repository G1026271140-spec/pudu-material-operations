from __future__ import annotations

import hashlib
import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
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
    response.set_cookie("pudu_admin", secrets.token_urlsafe(32), httponly=True, secure=False, samesite="strict", max_age=3600)
    return {"unlocked": True}


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
def _queue_client_and_table() -> tuple[Any, str]:
    import app as legacy
    from submission_queue import QUEUE_TABLE_NAME

    client = legacy.feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建后台申请任务。")
    table = next((row for row in client.list_tables() if str(row.get("name") or "").strip() == QUEUE_TABLE_NAME), None)
    table_id = str((table or {}).get("table_id") or "").strip()
    if not table_id:
        raise RuntimeError("未找到后台任务队列表。")
    return client, table_id


def _enqueue_fast(task_type: str, idempotency_key: str, payload: dict[str, Any]) -> str:
    from submission_queue import (
        QUEUE_COMPLETION_UNFINISHED, QUEUE_FIELD_COMPLETION_STATUS,
        QUEUE_FIELD_IDEMPOTENCY_KEY, QUEUE_FIELD_PAYLOAD, QUEUE_FIELD_RETRY_COUNT,
        QUEUE_FIELD_STATUS, QUEUE_FIELD_SUBMITTED_AT, QUEUE_FIELD_TASK_ID,
        QUEUE_FIELD_TASK_TYPE, QUEUE_PAYLOAD_INLINE_LIMIT, QUEUE_STATUS_PENDING,
        timestamp_ms,
    )

    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > QUEUE_PAYLOAD_INLINE_LIMIT:
        raise RuntimeError("申请内容超过队列单条载荷限制，请减少明细后重试。")
    client, table_id = _queue_client_and_table()
    task_id = uuid4().hex
    rows = client.batch_create_records(table_id, [{
        QUEUE_FIELD_TASK_ID: task_id, QUEUE_FIELD_TASK_TYPE: task_type,
        QUEUE_FIELD_IDEMPOTENCY_KEY: idempotency_key, QUEUE_FIELD_STATUS: QUEUE_STATUS_PENDING,
        QUEUE_FIELD_PAYLOAD: serialized, QUEUE_FIELD_SUBMITTED_AT: timestamp_ms(),
        QUEUE_FIELD_RETRY_COUNT: 0, QUEUE_FIELD_COMPLETION_STATUS: QUEUE_COMPLETION_UNFINISHED,
    }])
    if not rows:
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
