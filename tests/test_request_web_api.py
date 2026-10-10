import importlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as legacy_app
from request_web.api import api, build_catalog


web_api = importlib.import_module("request_web.api")


def test_catalog_uses_local_snapshot_and_exposes_all_products():
    catalog = build_catalog()
    assert "代理商支持" in catalog["reasons"]
    assert "代理活动" not in catalog["reasons"]
    assert len(catalog["products"]) == 11
    assert len(catalog["users"]) > 100
    assert catalog["rolesByUser"]
    assert all(product["options"] for product in catalog["products"])
    assert all(product["categoryDefinition"] for product in catalog["products"])
    assert all(isinstance(product["images"], list) for product in catalog["products"])
    assert any(
        product["source"] == "cultural" for product in catalog["adminProducts"]
    )
    assert any(not product["adminOnly"] for product in catalog["adminProducts"])


def test_image_index_returns_every_cached_category_image(tmp_path, monkeypatch):
    attachments = [
        {"file_token": "image-one"},
        {"file_token": "image-two"},
        {"file_token": "image-one"},
    ]
    monkeypatch.setattr(web_api, "ROOT", tmp_path)
    monkeypatch.setattr(
        web_api,
        "_json",
        lambda _name: {
            "tables": {
                "物料品类": [
                    {"fields": {"物料品类": "多图品类", "申领页图片": attachments}}
                ]
            }
        },
    )
    expected = []
    for token in ("image-one", "image-two"):
        filename = web_api.hashlib.sha256(token.encode()).hexdigest()[:20] + ".webp"
        path = tmp_path / "assets" / "request_categories" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(token.encode())
        expected.append(f"/category-assets/{filename}")

    assert web_api._image_index() == {"多图品类": expected}


def test_frontend_html_is_not_cached_across_releases():
    response = TestClient(api).get("/request")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"


def test_missing_hashed_asset_returns_404_instead_of_spa_html():
    response = TestClient(api).get("/assets/index-stale-release.js")

    assert response.status_code == 404
    assert not response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"


def test_admin_catalog_ignores_category_and_material_status_and_visibility(monkeypatch):
    cache = {
        "generated_at": "2026-09-17",
        "products": ["基础品类"],
        "inventory_rows": [{
            "product": "基础品类", "material_code": "MAT-1", "model": "M1",
            "language": "中文", "quantity": 3, "unit_price_rmb": 1,
        }],
        "model_product_lines": {}, "model_display_names": {},
        "category_display_names": {},
    }
    page = {"tables": {
        "用户权限表": [],
        "物料品类": [
            {"record_id": "cat-base", "fields": {"物料品类": "基础品类", "品类定义": "印刷物料", "启用状态": "启用", "是否在申领页显示": "是"}},
            {"record_id": "cat-off", "fields": {"物料品类": "停用品类", "品类定义": "印刷物料", "启用状态": "停用", "是否在申领页显示": "否"}},
            {"record_id": "cat-culture", "fields": {"物料品类": "停用文化周边", "品类定义": "文化周边", "启用状态": "停用", "是否在申领页显示": "否"}},
        ],
        legacy_app.MATERIAL_TABLE_NAME: [
            {"record_id": "mat-base", "fields": {"物料编码": "MAT-1", "物料品类": "基础品类", "产品型号": "M1", "语种": "中文", "当前库存": 3, "启用状态": "启用", "是否在申领页显示": "是"}},
            {"record_id": "mat-hidden", "fields": {"物料编码": "MAT-2", "物料品类": "基础品类", "产品型号": "M2", "语种": "英文", "当前库存": 2, "启用状态": "停用", "是否在申领页显示": "否"}},
            {"record_id": "mat-off", "fields": {"物料编码": "MAT-3", "物料品类": "停用品类", "产品型号": "M3", "语种": "英文", "当前库存": 1, "启用状态": "停用", "是否在申领页显示": "否"}},
        ],
        "文化周边管理库存": [
            {"record_id": "culture-off", "fields": {"物料品类": "停用文化周边", "产品型号": "L", "战区管理": "美洲战区", "当前库存": 4, "是否可以申领": "是"}},
        ],
        "产品型号": [],
    }}

    def fake_json(name):
        if name == "request_form_cache.json":
            return cache
        if name == "contact_departments_cache.json":
            return {"users": [], "departments": []}
        return page

    monkeypatch.setattr(web_api, "_json", fake_json)
    monkeypatch.setattr(web_api, "_image_index", lambda: {})

    catalog = build_catalog()
    by_name = {product["name"]: product for product in catalog["adminProducts"]}

    assert [product["name"] for product in catalog["products"]] == ["基础品类"]
    assert {option["model"] for option in by_name["基础品类"]["options"]} == {"M1", "M2"}
    assert by_name["基础品类"]["adminOnly"] is False
    assert next(option for option in by_name["基础品类"]["options"] if option["model"] == "M2")["adminOnly"] is True
    assert by_name["停用品类"]["adminOnly"] is True
    assert by_name["停用品类"]["categoryDefinition"] == "印刷物料"
    assert by_name["停用文化周边"]["source"] == "cultural"
    assert by_name["停用文化周边"]["categoryDefinition"] == "文化周边"


def test_health_endpoint():
    response = TestClient(api).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _write_live_cache_pointer(
    root: Path, generation: str, *, page_value: str, asset_value: bytes
) -> None:
    (root / "app.py").write_text('APP_VERSION = "V2.8.5"\n', encoding="utf-8")
    (root / "live_cache.py").write_text("# marker\n", encoding="utf-8")
    generation_root = root / "work" / "live-cache" / generation
    (generation_root / "data").mkdir(parents=True, exist_ok=True)
    (generation_root / "assets" / "request_categories").mkdir(
        parents=True, exist_ok=True
    )
    (generation_root / "data" / "page_data_cache.json").write_text(
        json.dumps({"value": page_value}), encoding="utf-8"
    )
    (generation_root / "assets" / "request_categories" / "test.webp").write_bytes(
        asset_value
    )
    pointer = {
        "schema_version": 1,
        "revision": generation,
        "groups": {
            "Material": {
                "generation": generation,
                "version": "V2.8.5",
                "generated_at": "2026-09-18 12:00:00",
                "files": {"data/page_data_cache.json": "unused"},
            },
            "Warehouse": {
                "generation": generation,
                "version": "V2.8.5",
                "generated_at": "2026-09-18 12:00:00",
                "files": {"assets/request_categories/test.webp": "unused"},
            },
        },
    }
    pointer_path = root / "work" / "live-cache" / "current.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")


def test_fastapi_switches_to_new_live_cache_without_restart(tmp_path, monkeypatch):
    root = tmp_path / "web"
    (root / "data").mkdir(parents=True)
    (root / "assets" / "request_categories").mkdir(parents=True)
    (root / "data" / "page_data_cache.json").write_text(
        json.dumps({"value": "root"}), encoding="utf-8"
    )
    (root / "assets" / "request_categories" / "test.webp").write_bytes(b"root")
    monkeypatch.setattr(web_api, "ROOT", root)

    first_generation = "1" * 32
    _write_live_cache_pointer(root, first_generation, page_value="first", asset_value=b"first")
    assert web_api._json("page_data_cache.json")["value"] == "first"
    assert Path(web_api._asset_file("request_categories/test.webp").path) == (
        root / "work" / "live-cache" / first_generation / "assets" / "request_categories" / "test.webp"
    )

    second_generation = "2" * 32
    _write_live_cache_pointer(
        root, second_generation, page_value="second", asset_value=b"second"
    )
    assert web_api._json("page_data_cache.json")["value"] == "second"
    assert Path(web_api._asset_file("request_categories/test.webp").path).read_bytes() == b"second"


def test_fastapi_cache_asset_rejects_path_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(web_api, "ROOT", tmp_path)
    with pytest.raises(HTTPException):
        web_api._asset_file("../outside.txt")


@pytest.mark.parametrize("path", [
    "/request",
    "/cultural",
    "/management/allocation",
    "/management/shipping-schedule",
    "/management/shipping-template",
    "/management/restock",
    "/management/categories",
    "/management/models",
    "/management/languages",
    "/management/regions",
])
def test_direct_route_serves_the_spa(path):
    response = TestClient(api).get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_workspace_excludes_gift_page_and_reads_cached_surfaces():
    payload = TestClient(api).get("/api/workspace").json()
    assert payload["inventory"]
    assert payload["categories"]
    assert payload["models"]
    assert payload["languages"]
    assert "giftProjects" not in payload


def test_cultural_catalog_applies_category_visibility_and_line_claimability(monkeypatch):
    page = {
        "generated_at": "2026-09-10 15:45:31",
        "tables": {
            "物料品类": [
                {"record_id": "cat-visible", "fields": {"物料品类": "文化POLO衫", "品类定义": "文化周边", "是否在申领页显示": "是"}},
                {"record_id": "cat-hidden", "fields": {"物料品类": "文化夹克", "品类定义": "文化周边", "是否在申领页显示": "否"}},
            ],
            "产品型号": [],
            "文化周边管理库存": [
                {"record_id": "visible", "fields": {"物料品类": "文化POLO衫", "产品型号": "M", "战区管理": "美洲战区", "当前库存": 3, "是否可以申领": "是"}},
                {"record_id": "line-hidden", "fields": {"物料品类": "文化POLO衫", "产品型号": "L", "战区管理": "美洲战区", "当前库存": 2, "是否可以申领": "否"}},
                {"record_id": "category-hidden", "fields": {"物料品类": "文化夹克", "产品型号": "M", "战区管理": "美洲战区", "当前库存": 4, "是否可以申领": "是"}},
            ],
        },
    }

    monkeypatch.setattr(
        web_api,
        "_json",
        lambda name: {"users": [], "departments": []} if name == "contact_departments_cache.json" else page,
    )
    monkeypatch.setattr(web_api, "_image_index", lambda: {})

    response = TestClient(api).get("/api/cultural-catalog")

    assert response.status_code == 200
    assert response.json()["maxCulturalShirtQuantity"] == 2
    assert response.json()["maxJacketQuantity"] == 1
    assert response.json()["combinations"] == [{
        "product": "文化POLO衫", "model": "M", "region": "美洲战区",
        "stock": 3, "unitPriceRmb": 0.0,
    }]


def test_fast_enqueue_performs_one_queue_write_without_readback(monkeypatch):
    class QueueClient:
        def __init__(self):
            self.calls = []

        def batch_create_records(self, table_id, records):
            self.calls.append((table_id, records))
            return [{"record_id": "rec-queue"}]

    client = QueueClient()
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue", "tbl-payload"))

    task_id = web_api._enqueue_fast("物料申请写入", "stable-token", {"version": 1})

    assert len(task_id) == 32
    assert len(client.calls) == 1
    table_id, rows = client.calls[0]
    assert table_id == "tbl-queue"
    assert len(rows) == 1
    assert rows[0]["幂等键"] == "stable-token"
    assert rows[0]["载荷JSON"] == '{"version":1}'


def test_fast_enqueue_chunks_large_management_payload(monkeypatch):
    class QueueClient:
        def __init__(self):
            self.calls = []

        def batch_create_records(self, table_id, records):
            self.calls.append((table_id, records))
            return [{"record_id": f"rec-{index}"} for index, _ in enumerate(records)]

    client = QueueClient()
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue", "tbl-payload"))
    monkeypatch.setattr("submission_queue.QUEUE_PAYLOAD_INLINE_LIMIT", 20)
    monkeypatch.setattr("submission_queue.QUEUE_PAYLOAD_CHUNK_SIZE", 10)

    web_api._enqueue_fast("物料品类同步", "large-token", {"rows": ["大型载荷" * 20]})

    assert [call[0] for call in client.calls] == ["tbl-payload", "tbl-queue"]
    marker = json.loads(client.calls[1][1][0]["载荷JSON"])
    assert marker["storage"] == "chunks"
    assert marker["chunks"] == len(client.calls[0][1])


def test_submit_uses_page_snapshot_and_skips_live_permission_validation(monkeypatch):
    observed = {}
    payload = {
        "title": "test",
        "department": "市场部",
        "requester": "测试用户",
        "requester_open_id": "ou-test",
        "customer_name": "客户",
        "country": "中国",
        "recipient_info": "收件信息",
        "freight_payer": "PUDU",
        "material_usage": "测试",
        "submission_token": "stable-token",
        "scheduling_version": 1,
        "accepted_roles": ["区域市场经理"],
        "accepted_date": "2026-09-08",
        "accepted_at_ms": 1788796800000,
        "request_reason": "展会需求",
        "arrival_start": "2026-09-20",
        "arrival_end": "2026-09-20",
    }
    lines = [{"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1}]

    def fake_validate(_draft, *, live):
        observed["live"] = live
        return payload, lines, []

    def fake_enqueue(task_type, idempotency_key, queued_payload):
        observed.update(task_type=task_type, key=idempotency_key, payload=queued_payload)
        return "task-fast"

    monkeypatch.setattr(web_api, "_validate", fake_validate)
    monkeypatch.setattr(web_api, "_enqueue_fast", fake_enqueue)
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {
            "rolesByUser": {"ou-test": ["区域市场经理"]},
            "products": [{"name": "产品单页"}],
            "adminProducts": [],
        },
    )
    monkeypatch.setattr(
        legacy_app,
        "queued_material_request_payload",
        lambda request_payload, request_lines: {
            "request_payload": request_payload,
            "lines": request_lines,
        },
    )

    response = TestClient(api).post(
        "/api/submit",
        json={**payload, "department_id": "od-test", "lines": lines},
    )

    assert response.status_code == 200
    assert response.json()["taskId"] == "task-fast"
    assert observed["live"] is False
    assert observed["key"] == "stable-token"
    assert observed["payload"]["request_payload"]["accepted_roles"] == ["区域市场经理"]
    assert observed["payload"]["request_payload"]["accepted_date"] == "2026-09-08"


def test_cultural_submit_requires_and_queues_material_usage(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, payload: observed.update(
            task_type=task_type, key=key, payload=payload
        )
        or "task-cultural",
    )
    payload = {
        "requester": "测试用户",
        "requester_open_id": "ou-test",
        "department": "市场部",
        "department_id": "od-test",
        "submission_token": "cultural-token",
        "lines": [
            {
                "product": "文化POLO衫",
                "model": "M",
                "region": "品牌&市场营销内部",
                "quantity": 1,
                "remark": "",
            }
        ],
    }

    missing = TestClient(api).post("/api/cultural-submit", json=payload)
    blank = TestClient(api).post(
        "/api/cultural-submit", json={**payload, "material_usage": "   "}
    )
    accepted = TestClient(api).post(
        "/api/cultural-submit", json={**payload, "material_usage": "  上海展会  "}
    )

    assert missing.status_code == 422
    assert blank.status_code == 422
    assert blank.json()["detail"] == "请填写文化衫用途（展会名称）。"
    assert accepted.status_code == 200
    assert accepted.json()["taskId"] == "task-cultural"
    assert observed["payload"]["request_payload"]["material_usage"] == "上海展会"


def test_corporate_apparel_submit_accepts_only_current_reasons(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, payload: observed.update(payload=payload) or "task-apparel",
    )
    monkeypatch.setattr(
        web_api,
        "_json",
        lambda _name: {"tables": {legacy_app.USER_PERMISSION_TABLE_NAME: []}},
    )
    monkeypatch.setattr(
        legacy_app,
        "validate_corporate_apparel_cached_quota",
        lambda *_args, **_kwargs: [],
    )
    payload = {
        "requester": "测试用户",
        "requester_open_id": "ou-test",
        "department": "市场部",
        "submission_token": "apparel-token",
        "lines": [{"product": "T恤-黑色（短袖）", "size": "M", "quantity": 1}],
    }

    missing = TestClient(api).post("/api/corporate-apparel-submit", json=payload)
    assert missing.status_code == 422
    for old_reason in ("出差", "参展：广交会", "特殊情况按需申请，需补OA"):
        rejected = TestClient(api).post(
            "/api/corporate-apparel-submit", json={**payload, "material_usage": old_reason}
        )
        assert rejected.status_code == 422
    for current_reason in ("入职", "销售标配", "OA流程申请（如未提报OA流程，一律驳回，请慎选）"):
        accepted = TestClient(api).post(
            "/api/corporate-apparel-submit", json={**payload, "material_usage": current_reason}
        )
        assert accepted.status_code == 200
        assert observed["payload"]["request_payload"]["material_usage"] == current_reason
    legacy = TestClient(api).post(
        "/api/corporate-apparel-submit", json={**payload, "material_usage": "OA流程申请"}
    )
    assert legacy.status_code == 200
    assert observed["payload"]["request_payload"]["material_usage"] == "OA流程申请（如未提报OA流程，一律驳回，请慎选）"


def test_unified_submit_splits_admin_standard_and_cultural_tasks(monkeypatch):
    observed = []
    payload = {
        "title": "test", "department": "市场部", "department_id": "od-test",
        "requester": "管理员", "requester_open_id": "ou-admin",
        "customer_name": "客户", "country": "中国", "recipient_info": "收件信息",
        "freight_payer": "PUDU", "material_usage": "测试", "submission_token": "mixed-token",
        "scheduling_version": 1, "accepted_roles": ["管理员"], "accepted_date": "2026-09-17",
        "accepted_at_ms": 1789574400000, "request_reason": "其他",
        "arrival_start": "2026-09-20", "arrival_end": "2026-09-20",
    }
    lines = [
        {"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1},
        {"product": "文化POLO衫", "model": "M", "language": "美洲战区", "quantity": 1,
         "source": "cultural", "admin_only": True},
    ]
    monkeypatch.setattr(web_api, "_validate", lambda _draft, *, live: (payload, lines, []))
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {
            "rolesByUser": {"ou-admin": ["管理员"]},
            "products": [{"name": "产品单页"}],
            "adminProducts": [{"name": "文化POLO衫"}],
        },
    )
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, queued: observed.append((task_type, key, queued)) or f"task-{len(observed)}",
    )

    response = TestClient(api).post("/api/submit", json={**payload, "lines": lines})

    assert response.status_code == 200
    assert response.json()["taskIds"] == ["task-1", "task-2"]
    assert [item[1] for item in observed] == ["mixed-token:standard", "mixed-token:cultural"]
    assert observed[0][2]["lines"][0]["product"] == "产品单页"
    assert observed[1][2]["lines"][0]["region"] == "美洲战区"
    assert observed[1][2]["request_payload"]["administrator_override"] is True
    assert observed[1][2]["request_payload"]["material_usage"] == "测试"


def test_admin_only_category_is_rejected_for_non_admin(monkeypatch):
    monkeypatch.setattr(web_api, "_validate", lambda _draft, *, live: ({}, [], []))
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {
            "rolesByUser": {"ou-sales": ["销售"]},
            "products": [{"name": "产品单页"}],
            "adminProducts": [{"name": "文化POLO衫"}],
        },
    )
    response = TestClient(api).post(
        "/api/validate",
        json={
            "title": "test", "department": "市场部", "requester": "销售", "requester_open_id": "ou-sales",
            "customer_name": "客户", "country": "中国", "recipient_info": "收件信息",
            "material_usage": "测试", "request_reason": "其他", "arrival_start": "2026-09-20",
            "arrival_end": "2026-09-20", "lines": [{"product": "文化POLO衫", "model": "M",
            "language": "美洲战区", "quantity": 1, "source": "cultural", "admin_only": True}],
        },
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "已启用的管理员" in response.json()["errors"][0]


def test_page_validation_enforces_cached_sales_lead_time(monkeypatch):
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {"rolesByUser": {"ou-sales": ["销售"]}},
    )
    monkeypatch.setattr(
        web_api,
        "_validate",
        lambda _draft, *, live: ({}, [], []),
    )
    monkeypatch.setattr("order_scheduling.today", lambda: "2026-09-08")

    response = TestClient(api).post(
        "/api/validate",
        json={
            "title": "test",
            "department": "市场部",
            "requester": "销售用户",
            "requester_open_id": "ou-sales",
            "customer_name": "客户",
            "country": "中国",
            "recipient_info": "收件信息",
            "material_usage": "测试",
            "request_reason": "展会需求",
            "arrival_start": "2026-09-10",
            "arrival_end": "2026-09-10",
            "lines": [{"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1}],
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "至少提前7个自然日" in response.json()["errors"][0]


def test_page_validation_keeps_manager_time_exemption(monkeypatch):
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {"rolesByUser": {"ou-manager": ["销售", "区域市场经理"]}},
    )
    monkeypatch.setattr(web_api, "_validate", lambda _draft, *, live: ({}, [], []))
    monkeypatch.setattr("order_scheduling.today", lambda: "2026-09-08")

    response = TestClient(api).post(
        "/api/validate",
        json={
            "title": "test",
            "department": "市场部",
            "requester": "经理用户",
            "requester_open_id": "ou-manager",
            "customer_name": "客户",
            "country": "中国",
            "recipient_info": "收件信息",
            "material_usage": "测试",
            "request_reason": "展会需求",
            "arrival_start": "2026-09-10",
            "arrival_end": "2026-09-10",
            "lines": [{"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"valid": True, "errors": []}


def admin_client():
    client = TestClient(api)
    web_api._ADMIN_SESSIONS.add("test-admin-session")
    client.cookies.set("pudu_admin", "test-admin-session")
    return client


def test_management_catalog_requires_password_and_uses_cached_snapshot():
    assert TestClient(api).get("/api/admin/management-catalog").status_code == 401
    response = admin_client().get("/api/admin/management-catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["categories"]
    assert payload["inventory"]
    assert payload["dimensions"]["model"]
    assert payload["dimensions"]["language"]
    assert payload["dimensions"]["region"]
    assert len(payload["shipping"]["cartonPresets"]) == 8
    assert "Flyers" in payload["shipping"]["packingTypes"]


def test_shipping_invoice_preview_requires_admin_and_normalizes_country_name():
    body = {"template_date": "2026-09-08", "address_code": "Thailand", "address": ""}
    assert TestClient(api).post("/api/admin/shipping/invoice-preview", json=body).status_code == 401

    response = admin_client().post("/api/admin/shipping/invoice-preview", json=body)

    assert response.status_code == 200
    assert response.json() == {"addressCode": "TH", "invoiceNumber": "2026-MKT-TH0908"}


def test_shipping_generate_returns_immediate_workbook_download():
    response = admin_client().post(
        "/api/admin/shipping/generate",
        json={
            "template_date": "2026-09-08",
            "address_code": "US",
            "recipient": {"recipient_name": "Test User", "address": "United States"},
            "lines": [{
                "line_id": "cat-1", "invoice_name": "Flyer", "packing_name": "Flyer",
                "packing_type": "Flyers", "quantity": 10, "unit_price": 1.2,
                "customs_code": "4911101000", "product_model": "sample", "sku": "/",
            }],
            "cartons": [{
                "carton_no": 1, "carton_quantity": 1, "net_weight": 5,
                "gross_weight": 6, "length_cm": 44, "width_cm": 30, "height_cm": 13,
            }],
            "allocations": [{"carton_no": 1, "line_id": "cat-1", "quantity": 10}],
        },
    )

    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    assert "2026-MKT-US0908_INV_PL.xlsx" in response.headers["content-disposition"]


def test_management_restock_queues_existing_worker_payload(monkeypatch):
    observed = {}
    monkeypatch.setattr(legacy_app, "validate_restock_draft", lambda draft: [])
    monkeypatch.setattr(legacy_app, "build_restock_no", lambda token: "RST-TEST")
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, payload: observed.update(
            task_type=task_type, key=key, payload=payload
        ) or "task-restock",
    )
    draft = {
        "operator": "管理员",
        "submission_token": "restock-token",
        "lines": [
            {
                "category_definition": "印刷物料",
                "product": "产品单页",
                "model": "T300",
                "language": "英语",
                "quantity": 10,
            }
        ],
    }
    response = admin_client().post("/api/admin/restock/submit", json=draft)
    assert response.status_code == 200
    assert response.json()["restockNo"] == "RST-TEST"
    assert observed["key"] == "RST-TEST"
    assert observed["payload"]["draft"]["lines"][0]["quantity"] == 10


def test_management_reduce_uses_distinct_queue_task_type(monkeypatch):
    observed = {}
    monkeypatch.setattr(legacy_app, "validate_restock_draft", lambda draft: [])
    monkeypatch.setattr(legacy_app, "build_restock_no", lambda token: "RST-REDUCE")
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, payload: observed.update(task_type=task_type, payload=payload) or "task-reduce",
    )
    response = admin_client().post(
        "/api/admin/restock/submit",
        json={"mode": "reduce", "operator": "管理员", "lines": [{"product": "产品单页", "model": "T300", "language": "英语", "quantity": 10}]},
    )
    assert response.status_code == 200
    assert observed["task_type"] == "库存减库"
    assert observed["payload"]["draft"]["mode"] == "reduce"


def test_dimension_preview_builds_worker_changes_from_cached_associations(monkeypatch):
    snapshot = {
        "categories": [{"record_id": "cat-1", "category": "产品单页", "no_model": False, "no_language": False}],
        "inventory": [],
        "culturalInventory": [],
        "dimensions": {
            "model": [],
            "language": [{"record_id": "lang-1", "name": "英语"}],
            "region": [],
        },
    }
    monkeypatch.setattr(web_api, "_management_snapshot", lambda: snapshot)
    response = admin_client().post(
        "/api/admin/dimension/preview",
        json={
            "kind": "model",
            "operation": "create",
            "name": "T300",
            "status": "启用",
            "selected_keys": [["产品单页", "英语"]],
        },
    )
    assert response.status_code == 200
    assert response.json()["changes"] == [
        {
            "action": "create",
            "category": "产品单页",
            "category_record_id": "cat-1",
            "model": "T300",
            "language": "英语",
            "region": "",
            "quantity": 0,
            "unit_price": 0.0,
            "customs_code": "",
            "status": "启用",
            "request_visible": "是",
        }
    ]


def test_category_submit_preserves_target_value_rows_for_worker(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        web_api,
        "_enqueue_fast",
        lambda task_type, key, payload: observed.update(payload=payload) or "task-category",
    )
    response = admin_client().post(
        "/api/admin/category/submit",
        json={
            "operation": "edit",
            "submission_token": "category-token",
            "sync_args": {
                "old_product": "产品单页",
                "new_product": "产品单页",
                "target_values_rows": [
                    {
                        "model": "T300",
                        "language": "英语",
                        "values": {"quantity": 8, "status": "启用"},
                    }
                ],
            },
            "draft": {"product": "产品单页"},
        },
    )
    assert response.status_code == 200
    assert observed["payload"]["sync_args"]["target_values_rows"][0]["values"]["quantity"] == 8


def test_allocation_pending_requires_admin_and_returns_only_summary(monkeypatch):
    context = {
        "request": {
            "record_id": "request-1", "request_no": "REQ-1", "requester": "申请人",
            "department": "市场部", "request_reason": "展会需求", "status": "待审批",
            "inventory_review_status": "待核实", "inventory_review_version": 2,
        },
        "lines": [{"record_id": "line-1"}], "result": "库存充足",
        "material_rows": [{"large": "must-not-leak"}],
    }
    monkeypatch.setattr(legacy_app, "pending_inventory_review_contexts", lambda: [context])
    monkeypatch.setattr(web_api, "_allocation_operators", lambda _legacy: [{"open_id": "ou-admin", "name": "管理员"}])

    assert TestClient(api).get("/api/admin/allocation/pending").status_code == 401
    response = admin_client().get("/api/admin/allocation/pending")

    assert response.status_code == 200
    assert response.json()["requests"][0]["requestNo"] == "REQ-1"
    assert response.json()["requests"][0]["lineCount"] == 1
    assert "material_rows" not in response.text


def test_signed_card_allocation_context_keeps_live_request_and_cached_options(monkeypatch):
    context = {
        "request": {"record_id": "request-1", "request_no": "REQ-1", "inventory_review_version": 0},
        "request_row": {"fields": {}},
        "lines": [{"record_id": "line-1", "material_record_id": "mat-1", "quantity": 2}],
        "result": "库存充足", "snapshot_at": "2026-09-08 12:00:00",
        "material_rows": [{"record_id": "mat-1", "fields": {}}],
    }
    monkeypatch.setattr(legacy_app, "valid_request_review_access_token", lambda *args: True)
    monkeypatch.setattr(legacy_app, "cached_enabled_admin_open_ids", lambda *args: ["ou-admin"])
    web_api._PENDING_ALLOCATION_CACHE.update(loaded_at=0.0, contexts={})
    monkeypatch.setattr(legacy_app, "request_inventory_review_context", lambda **_kwargs: context)
    monkeypatch.setattr(legacy_app, "load_static_request_form_cache", lambda: {"generated_at": "cache-time"})
    monkeypatch.setattr(legacy_app, "cached_allocation_material_records", lambda *args, **kwargs: [{"record_id": "mat-1", "category": "产品单页", "model": "T300", "language": "英语"}])
    monkeypatch.setattr(web_api, "_allocation_operators", lambda _legacy: [])

    response = TestClient(api).get(
        "/api/allocation/request-1?operator=ou-admin&review_token=signed"
    )

    assert response.status_code == 200
    assert response.json()["signedCardAccess"] is True
    assert response.json()["operatorOpenId"] == "ou-admin"
    assert response.json()["materials"][0]["record_id"] == "mat-1"


def test_allocation_edit_queues_existing_worker_payload(monkeypatch):
    observed = {}
    monkeypatch.setattr(legacy_app, "cached_enabled_admin_open_ids", lambda *args: ["ou-admin"])
    monkeypatch.setattr(
        web_api, "_enqueue_fast",
        lambda task_type, key, payload: observed.update(task_type=task_type, key=key, payload=payload) or "task-allocation",
    )
    response = admin_client().post(
        "/api/allocation/request-1/submit",
        json={
            "operation": "edit",
            "draft": {
                "expected_version": 3, "operator_open_id": "ou-admin", "ship_date": "2026-09-20",
                "change_note": "调整型号", "lines": [
                    {"line_record_id": "line-1", "material_record_id": "mat-2", "quantity": 4, "remark": "替换", "order_required": True}
                ],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["taskId"] == "task-allocation"
    assert observed["task_type"] == "申请物料库存编辑"
    assert observed["payload"]["draft"]["request_id"] == "request-1"
    assert observed["payload"]["draft"]["lines"][0]["order_required"] is True


def test_allocation_order_preview_summarizes_only_printed_order_lines(monkeypatch):
    monkeypatch.setattr(legacy_app, "cached_enabled_admin_open_ids", lambda *args: ["ou-admin"])
    monkeypatch.setattr(
        legacy_app,
        "request_inventory_review_context",
        lambda **_kwargs: {
            "request": {"request_no": "REQ-ORDER", "material_usage": "展会"},
            "lines": [
                {"product": "产品单页", "category_definition": "印刷物料", "model": "T300", "language": "英语", "quantity": 3, "current_stock": 0, "remark": "加厚"},
                {"product": "公仔", "category_definition": "周边礼品", "model": "Bella", "language": "无需语种", "quantity": 2, "current_stock": 0, "remark": ""},
            ],
            "material_rows": [],
            "category_rows": [
                {"record_id": "cat-print", "fields": {"物料品类": "产品单页", "中文页面名称": "产品单页", "品类定义": "印刷物料"}},
                {"record_id": "cat-gift", "fields": {"物料品类": "公仔", "中文页面名称": "公仔", "品类定义": "周边礼品"}},
            ],
        },
    )
    response = admin_client().post(
        "/api/allocation/request-1/order-preview",
        json={"operation": "confirm", "draft": {"operator_open_id": "ou-admin"}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["lineCount"] == 1
    assert payload["totalQuantity"] == 3
    assert payload["lines"][0] == {
        "category": "产品单页", "model": "T300", "language": "英语",
        "quantity": 3, "usage": "展会\n制作备注：加厚",
    }


def test_allocation_order_workbook_download_uses_existing_template(monkeypatch):
    monkeypatch.setattr(legacy_app, "cached_enabled_admin_open_ids", lambda *args: ["ou-admin"])
    monkeypatch.setattr(
        web_api,
        "_allocation_order_preview",
        lambda *_args, **_kwargs: {
            "requestNo": "REQ-ORDER", "workbookAvailable": True,
            "workbookFilename": "物料下单表-REQ-ORDER.xlsx",
            "lines": [{"category": "产品单页", "model": "T300", "language": "英语", "quantity": 3, "usage": "展会"}],
        },
    )
    response = admin_client().post(
        "/api/allocation/request-1/order-workbook",
        json={"operation": "confirm", "draft": {"operator_open_id": "ou-admin"}},
    )
    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
