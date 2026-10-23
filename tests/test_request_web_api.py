import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as legacy_app
import pending_inventory_sqlite
from request_web.api import api, build_catalog


web_api = importlib.import_module("request_web.api")


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "data/page_data_cache.json").is_file(), reason="Published snapshot integration: source-only handover omits business data")
def test_catalog_uses_local_snapshot_and_exposes_all_products():
    catalog = build_catalog()
    assert "代理商支持" in catalog["reasons"]
    assert "代理活动" not in catalog["reasons"]
    # The published business catalog changes independently of code releases.
    expected = set(web_api._json("request_form_cache.json").get("products", []))
    assert catalog["products"]
    assert {product["name"] for product in catalog["products"]} <= expected
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


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "data/request_form_cache.json").is_file(), reason="Published snapshot integration: source-only handover omits business data")
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


def test_fast_enqueue_performs_one_queue_write(monkeypatch):
    class QueueClient:
        def __init__(self):
            self.calls = []

        def batch_create_records(self, table_id, records):
            self.calls.append((table_id, records))
            return [{"record_id": "rec-queue"}]

    client = QueueClient()
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue", "tbl-payload"))
    monkeypatch.setattr("submission_queue.find_task_by_idempotency_key", lambda *_args: None)

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
    monkeypatch.setattr("submission_queue.find_task_by_idempotency_key", lambda *_args: None)
    monkeypatch.setattr("submission_queue.QUEUE_PAYLOAD_INLINE_LIMIT", 20)
    monkeypatch.setattr("submission_queue.QUEUE_PAYLOAD_CHUNK_SIZE", 10)

    web_api._enqueue_fast("物料品类同步", "large-token", {"rows": ["大型载荷" * 20]})

    assert [call[0] for call in client.calls] == ["tbl-payload", "tbl-queue"]
    marker = json.loads(client.calls[1][1][0]["载荷JSON"])
    assert marker["storage"] == "chunks"
    assert marker["chunks"] == len(client.calls[0][1])


def test_fast_enqueue_reuses_same_token_even_for_concurrent_requests(monkeypatch):
    class QueueClient:
        def __init__(self):
            self.records = []

        def batch_create_records(self, _table_id, records):
            self.records.extend(records)
            return [{"record_id": "rec-first"}]

    client = QueueClient()
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue", "tbl-payload"))

    def find_existing(_client, _key, _table_id):
        if not client.records:
            return None
        fields = client.records[0]
        return SimpleNamespace(
            task_id=fields["任务ID"], task_type=fields["任务类型"],
            payload=json.loads(fields["载荷JSON"]),
        )

    monkeypatch.setattr("submission_queue.find_task_by_idempotency_key", find_existing)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: web_api._enqueue_fast("企业文化衫领取", "same-token", {"version": 1}),
            range(2),
        ))
    assert results[0] == results[1]
    assert len(client.records) == 1
    with pytest.raises(ValueError, match="不同申请内容"):
        web_api._enqueue_fast("企业文化衫领取", "same-token", {"version": 2})
    assert len(client.records) == 1


def test_fast_enqueue_cancels_duplicate_found_after_create(monkeypatch):
    class QueueClient:
        def __init__(self):
            self.updates = []

        def batch_create_records(self, _table_id, _records):
            return [{"record_id": "rec-second"}]

        def update_record(self, *args):
            self.updates.append(args)

    client = QueueClient()
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (client, "tbl-queue", "tbl-payload"))
    checks = iter((None, SimpleNamespace(
        task_id="earlier-task", task_type="企业文化衫领取", payload={"version": 1},
    )))
    monkeypatch.setattr(
        "submission_queue.find_task_by_idempotency_key",
        lambda *_args: next(checks),
    )
    task_id = web_api._enqueue_fast("企业文化衫领取", "same-token", {"version": 1})
    assert task_id == "earlier-task"
    assert client.updates[0][0:2] == ("tbl-queue", "rec-second")
    assert client.updates[0][2]["状态"] == "已取消"


def test_submit_uses_page_snapshot_and_skips_live_permission_validation(monkeypatch):
    monkeypatch.setattr(web_api, "_authenticated_submitter", lambda _request: ("提交用户", "ou-submitter"))
    observed = {}
    monkeypatch.setattr(web_api, "_schedule_submission_receipt", lambda *args: observed.update(receipt=args))
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
    assert observed["receipt"] == ("stable-token", "ou-test", "物料申领", ["task-fast"])
    assert observed["live"] is False
    assert observed["key"] == "stable-token"
    assert observed["payload"]["request_payload"]["accepted_roles"] == ["区域市场经理"]
    assert observed["payload"]["request_payload"]["accepted_date"] == "2026-09-08"


def test_cultural_submit_requires_and_queues_material_usage(monkeypatch):
    monkeypatch.setattr(web_api, "_authenticated_submitter", lambda _request: ("提交用户", "ou-submitter"))
    observed = {}
    monkeypatch.setattr(web_api, "_schedule_submission_receipt", lambda *args: observed.update(receipt=args))
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
    assert observed["receipt"] == ("cultural-token", "ou-test", "文化周边申领", ["task-cultural"])
    assert observed["payload"]["request_payload"]["material_usage"] == "上海展会"


def test_corporate_apparel_submit_accepts_only_current_reasons(monkeypatch):
    monkeypatch.setattr(web_api, "_authenticated_submitter", lambda _request: ("提交用户", "ou-submitter"))
    observed = {}
    monkeypatch.setattr(web_api, "_schedule_submission_receipt", lambda *args: observed.update(receipt=args))
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
    assert observed["receipt"] == ("apparel-token", "ou-test", "企业文化衫领取", ["task-apparel"])
    assert observed["payload"]["request_payload"]["material_usage"] == "OA流程申请（如未提报OA流程，一律驳回，请慎选）"


def test_corporate_apparel_retry_reuses_completed_task_after_quota_changes(monkeypatch):
    monkeypatch.setattr(web_api, "_authenticated_submitter", lambda _request: ("提交用户", "ou-submitter"))
    request = {
        "requester": "测试用户", "requester_open_id": "ou-test", "department": "市场部",
        "material_usage": "入职", "submission_token": "same-token",
        "lines": [{"product": "T恤-黑色（短袖）", "size": "M", "quantity": 1}],
    }
    normalized = web_api.CorporateApparelDraft.model_validate(request).model_dump()
    existing_payload = legacy_app.queued_corporate_apparel_request_payload(
        {key: value for key, value in normalized.items() if key != "lines"},
        normalized["lines"],
    )
    monkeypatch.setattr(web_api, "_json", lambda _name: {"tables": {legacy_app.USER_PERMISSION_TABLE_NAME: []}})
    monkeypatch.setattr(web_api, "_queue_client_and_table", lambda: (object(), "tbl-queue", ""))
    monkeypatch.setattr(
        legacy_app, "validate_corporate_apparel_cached_quota",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("已达到领取上限")),
    )
    monkeypatch.setattr(
        "submission_queue.find_task_by_idempotency_key",
        lambda *_args: SimpleNamespace(
            task_id="original-task", task_type="企业文化衫领取",
            payload=existing_payload, status="已完成",
        ),
    )
    monkeypatch.setattr(web_api, "_enqueue_fast", lambda *_args: pytest.fail("must not enqueue twice"))
    response = TestClient(api).post("/api/corporate-apparel-submit", json=request)
    assert response.status_code == 200
    assert response.json()["taskId"] == "original-task"
    assert response.json()["created"] is False


def test_corporate_apparel_catalog_is_immediate_and_stock_read_is_shared(monkeypatch):
    calls = []

    class Source:
        def list_records(self, table_id):
            calls.append(table_id)
            return [{"available": len(calls)}]

    def fake_catalog(rows, *, source_rows=None):
        return {
            "products": ["Polo"],
            "items": [{
                "record_id": "rec-1", "product": "Polo", "size": "M",
                "available": source_rows[0]["available"] if source_rows else 0,
                "images": ["assets/request_categories/polo.webp"],
            }],
        }

    monkeypatch.setattr(web_api, "_json", lambda name: {
        "tables": {legacy_app.CORPORATE_APPAREL_TABLE_NAME: [{"record_id": "rec-1"}]},
        "users": [{"open_id": "ou-1"}], "departments": [],
    })
    monkeypatch.setattr(legacy_app, "corporate_apparel_catalog", fake_catalog)
    monkeypatch.setattr(legacy_app, "corporate_apparel_source_client", lambda: Source())
    monkeypatch.setitem(web_api._CORPORATE_APPAREL_STOCK_CACHE, "items", None)
    monkeypatch.setitem(web_api._CORPORATE_APPAREL_STOCK_CACHE, "loaded_at", 0.0)
    with TestClient(api) as client:
        catalog = client.get("/api/corporate-apparel-catalog")
        assert catalog.status_code == 200
        assert catalog.headers["cache-control"] == "no-store"
        assert catalog.json()["items"][0]["available"] == 0
        assert catalog.json()["users"] == [{"open_id": "ou-1"}]
        assert calls == []
        first = client.get("/api/corporate-apparel-stock")
        second = client.get("/api/corporate-apparel-stock")
        assert first.headers["cache-control"] == "no-store"
        assert first.json()["items"][0]["available"] == 1
        assert first.json()["items"][0]["images"] == ["/category-assets/polo.webp"]
        assert second.json() == first.json()
        assert len(calls) == 1
        web_api._CORPORATE_APPAREL_STOCK_CACHE["loaded_at"] = 0.0
        refreshed = client.get("/api/corporate-apparel-stock")
        assert refreshed.json()["items"][0]["available"] == 2
        assert len(calls) == 2


def test_corporate_apparel_stock_fails_closed_when_live_source_is_unavailable(monkeypatch):
    class BrokenSource:
        def list_records(self, _table_id):
            raise RuntimeError("source unavailable")

    monkeypatch.setattr(web_api, "_json", lambda _name: {
        "tables": {legacy_app.CORPORATE_APPAREL_TABLE_NAME: []},
    })
    monkeypatch.setattr(legacy_app, "corporate_apparel_source_client", lambda: BrokenSource())
    monkeypatch.setitem(web_api._CORPORATE_APPAREL_STOCK_CACHE, "items", [{"available": 1}])
    monkeypatch.setitem(web_api._CORPORATE_APPAREL_STOCK_CACHE, "loaded_at", 0.0)
    with TestClient(api, raise_server_exceptions=False) as client:
        response = client.get("/api/corporate-apparel-stock")
    assert response.status_code == 500


@pytest.mark.parametrize("role", ["管理员", "区域市场经理"])
def test_unified_submit_splits_full_catalog_standard_and_cultural_tasks(monkeypatch, role):
    monkeypatch.setattr(web_api, "_authenticated_submitter", lambda _request: ("提交用户", "ou-submitter"))
    observed = []
    payload = {
        "title": "test", "department": "市场部", "department_id": "od-test",
        "requester": "目录授权人", "requester_open_id": "ou-privileged",
        "customer_name": "客户", "country": "中国", "recipient_info": "收件信息",
        "freight_payer": "PUDU", "material_usage": "测试", "submission_token": "mixed-token",
        "scheduling_version": 1, "accepted_roles": [role], "accepted_date": "2026-09-17",
        "accepted_at_ms": 1789574400000, "request_reason": "其他",
        "arrival_start": "2026-09-20", "arrival_end": "2026-09-20",
    }
    lines = [
        {"product": "产品单页", "model": "T300", "language": "英语", "quantity": 1},
        {"product": "停用品类", "model": "M1", "language": "英语", "quantity": 1,
         "source": "standard", "admin_only": True},
        {"product": "文化POLO衫", "model": "M", "language": "美洲战区", "quantity": 1,
         "source": "cultural", "admin_only": True},
    ]
    monkeypatch.setattr(web_api, "_validate", lambda _draft, *, live: (payload, lines, []))
    monkeypatch.setattr(
        web_api,
        "build_catalog",
        lambda: {
            "rolesByUser": {"ou-privileged": [role]},
            "products": [{"name": "产品单页"}],
            "adminProducts": [{"name": "停用品类", "adminOnly": True},
                              {"name": "文化POLO衫", "adminOnly": True}],
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
    assert observed[0][2]["lines"][1]["product"] == "停用品类"
    assert observed[1][2]["lines"][0]["region"] == "美洲战区"
    assert observed[1][2]["request_payload"]["administrator_override"] is True
    assert observed[1][2]["request_payload"]["material_usage"] == "测试"
    assert observed[0][2]["request_payload"]["accepted_roles"] == [role]


def test_full_catalog_category_is_rejected_for_sales(monkeypatch):
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
    assert "管理员或区域市场经理" in response.json()["errors"][0]


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


def admin_client(monkeypatch):
    from request_web import feishu_auth

    monkeypatch.setattr(feishu_auth, "credentials", lambda: ("test-app", "test-secret"))
    monkeypatch.setattr(feishu_auth, "own_tenant_key", lambda: "test-tenant")
    admin_open_id = "ou_unit_test_admin"
    # Keep auth real (signed cookie + role lookup), but never require a staff
    # snapshot just to create a test administrator.
    original_json = web_api._json
    def test_json(name):
        try:
            result = original_json(name)
        except FileNotFoundError:
            if name != "page_data_cache.json":
                raise
            result = {"tables": {}}
        if name == "page_data_cache.json":
            from copy import deepcopy
            result = deepcopy(result)
            permissions = result.setdefault("tables", {}).setdefault("用户权限表", [])
            permissions.append({"record_id": "unit-test-permission", "fields": {
                "是否启用": "是", "角色": ["管理员"], "用户账号": [{"id": admin_open_id}],
            }})
        return result
    monkeypatch.setattr(web_api, "_json", test_json)
    client = TestClient(api)
    client.cookies.set("pudu_feishu", feishu_auth.create_session(admin_open_id, "test-tenant"))
    return client


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "data/page_data_cache.json").is_file(), reason="Published snapshot integration: source-only handover omits business data")
def test_management_catalog_requires_admin_identity_and_uses_cached_snapshot(monkeypatch):
    assert TestClient(api).get("/api/admin/management-catalog").status_code == 403
    response = admin_client(monkeypatch).get("/api/admin/management-catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["categories"]
    assert payload["inventory"]
    assert payload["dimensions"]["model"]
    assert payload["dimensions"]["language"]
    assert payload["dimensions"]["region"]
    assert len(payload["shipping"]["cartonPresets"]) == 8
    assert "Flyers" in payload["shipping"]["packingTypes"]


def test_shipping_invoice_preview_requires_admin_and_normalizes_country_name(monkeypatch):
    body = {"template_date": "2026-09-08", "address_code": "Thailand", "address": ""}
    assert TestClient(api).post("/api/admin/shipping/invoice-preview", json=body).status_code == 403

    response = admin_client(monkeypatch).post("/api/admin/shipping/invoice-preview", json=body)

    assert response.status_code == 200
    assert response.json() == {"addressCode": "TH", "invoiceNumber": "2026-MKT-TH0908"}


def test_shipping_generate_returns_immediate_workbook_download(monkeypatch):
    response = admin_client(monkeypatch).post(
        "/api/admin/shipping/generate",
        json={
            "template_date": "2026-09-08",
            "shipping_cost": 0,
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


@pytest.mark.parametrize("cost,expected_cost,status", [(None, 100, 200), (50, 50, 200), (200, 200, 200), (1001, None, 422), (-1, None, 422)])
def test_shipping_freight_default_and_override(monkeypatch, cost, expected_cost, status):
    from io import BytesIO
    from openpyxl import load_workbook

    body = {"template_date": "2026-10-22", "address_code": "US", "recipient": {},
        "lines": [{"line_id": "A", "invoice_name": "Goods", "packing_name": "Goods", "packing_type": "Give aways", "quantity": 10, "unit_price": 100, "customs_code": "1234"}],
        "cartons": [{"carton_no": 1, "carton_quantity": 1, "net_weight": 2, "gross_weight": 3, "length_cm": 40, "width_cm": 30, "height_cm": 20}],
        "allocations": [{"carton_no": 1, "line_id": "A", "quantity": 10}]}
    if cost is not None: body["shipping_cost"] = cost
    response = admin_client(monkeypatch).post("/api/admin/shipping/generate", json=body)
    assert response.status_code == status
    if status == 200:
        invoice = load_workbook(BytesIO(response.content))["INV"]
        assert invoice["B17"].value == "Shipping Cost"
        assert invoice["F17"].value == expected_cost
        assert invoice["E16"].value * invoice["F16"].value + invoice["F17"].value == 1000


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
    response = admin_client(monkeypatch).post("/api/admin/restock/submit", json=draft)
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
    response = admin_client(monkeypatch).post(
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
    response = admin_client(monkeypatch).post(
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
    response = admin_client(monkeypatch).post(
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


@pytest.mark.parametrize("kind,confirmed,name,rows,expected", [
    ("material_rows", True, "", ["mat-1"], 200),
    ("material_rows", True, "", [], 422),
    ("material_rows", False, "", ["mat-1"], 422),
    ("categories", True, "产品单页", ["mat-1"], 200),
    ("categories", True, "其他品类", ["mat-1"], 422),
    ("categories", False, "产品单页", ["mat-1"], 422),
    ("", True, "", ["mat-1"], 422),
])
def test_category_delete_submit_requires_explicit_scope_and_confirmation(monkeypatch, kind, confirmed, name, rows, expected):
    observed = []
    monkeypatch.setattr(web_api, "_enqueue_fast", lambda *args: observed.append(args) or "task-delete")
    response = admin_client(monkeypatch).post("/api/admin/category/submit", json={
        "operation": "delete", "submission_token": "delete-token",
        "draft": {"delete_kind": kind, "category_names": ["产品单页"],
                  "record_ids": rows, "records": [{"record_id": i, "category": "产品单页"} for i in rows],
                  "scope_confirmed": confirmed, "confirmed_category_name": name},
    })
    assert response.status_code == expected
    assert len(observed) == (1 if expected == 200 else 0)
    if expected == 200:
        assert observed[0][2]["draft"]["delete_kind"] == kind
        assert observed[0][2]["draft"]["record_ids"] == rows


def test_allocation_pending_requires_admin_and_returns_only_summary(monkeypatch):
    row = {"record_id": "request-1", "fields": {
        "申请单号": "REQ-1", "申请类型": "普通物料申请", "审批状态": "待审批",
        "库存审查状态": "待核实库存",
    }}
    monkeypatch.setattr(web_api, "_PENDING_ALLOCATION_CACHE", {
        "last_attempt": web_api.time.monotonic(), "refreshing": False, "last_error": "",
    })
    monkeypatch.setattr(pending_inventory_sqlite, "list_pending", lambda: [(row, 1, "2026-10-16")])
    monkeypatch.setattr(web_api, "_allocation_operators", lambda _legacy: [{"open_id": "ou-admin", "name": "管理员"}])

    assert TestClient(api).get("/api/admin/allocation/pending").status_code == 403
    response = admin_client(monkeypatch).get("/api/admin/allocation/pending")

    assert response.status_code == 200
    assert response.json()["requests"][0]["requestNo"] == "REQ-1"
    assert response.json()["requests"][0]["lineCount"] == 1
    assert "material_rows" not in response.text


def test_allocation_operators_use_published_permissions_not_live_feishu(monkeypatch):
    monkeypatch.setattr(
        legacy_app, "cached_enabled_admin_open_ids",
        lambda *_args: (_ for _ in ()).throw(AssertionError("live Feishu read")),
    )
    monkeypatch.setattr(web_api, "_json", lambda name: (
        {"tables": {"用户权限表": [
            {"fields": {"用户账号": [{"id": "ou_admin"}], "角色": ["管理员"], "是否启用": "是"}},
            {"fields": {"用户账号": [{"id": "ou_disabled"}], "角色": ["管理员"], "是否启用": "否"}},
        ]}} if name == "page_data_cache.json" else
        {"users": [{"open_id": "ou_admin", "name": "管理员"}, {"open_id": "ou_disabled", "name": "停用管理员"}]}
    ))

    operators = web_api._allocation_operators(legacy_app)

    assert [user["open_id"] for user in operators] == ["ou_admin"]


def test_pending_allocation_summary_needs_only_request_rows():
    rows = [
        {"record_id": "req-1", "fields": {
            "申请单号": "REQ-1", "申请类型": "普通物料申请", "审批状态": "待审批",
            "库存审查状态": "待核实库存", "库存审查结论": "库存充足",
            "申请明细": [{"record_ids": ["line-1", "line-2"]}],
        }},
        {"record_id": "req-2", "fields": {
            "申请单号": "REQ-2", "申请类型": "普通物料申请", "审批状态": "待审批",
            "库存审查状态": "已核实库存",
        }},
    ]

    summaries = legacy_app.pending_inventory_review_summaries(rows)

    assert len(summaries) == 1
    assert summaries[0]["requestNo"] == "REQ-1"
    assert summaries[0]["lineCount"] == 2


def test_pending_allocation_reads_sqlite_without_starting_live_refresh(monkeypatch):
    client = admin_client(monkeypatch)
    row = {"record_id": "req-1", "fields": {
        "申请单号": "REQ-1", "申请类型": "普通物料申请", "审批状态": "待审批",
        "库存审查状态": "待核实库存", "申请明细": [{"record_ids": ["line-1"]}],
    }}
    monkeypatch.setattr(web_api, "_PENDING_ALLOCATION_CACHE", {
        "last_attempt": 0.0, "refreshing": False, "last_error": "",
    })
    monkeypatch.setattr(pending_inventory_sqlite, "list_pending", lambda: [(row, 1, "2026-10-16")])
    monkeypatch.setattr(web_api, "_PENDING_ALLOCATION_EXECUTOR", SimpleNamespace(
        submit=lambda _fn: (_ for _ in ()).throw(AssertionError("page read started live refresh"))
    ))
    monkeypatch.setattr(web_api, "_allocation_operators", lambda _legacy: [])

    response = client.get("/api/admin/allocation/pending?refresh=true")

    assert response.status_code == 200
    assert response.json()["requests"][0]["requestNo"] == "REQ-1"
    assert response.json()["source"] == "sqlite"
    assert response.json()["refreshing"] is False


def test_pending_allocation_refresh_failure_keeps_last_snapshot(monkeypatch):
    monkeypatch.setattr(web_api, "_PENDING_ALLOCATION_CACHE", {
        "last_attempt": 0.0, "refreshing": True, "last_error": "",
    })
    monkeypatch.setattr(
        pending_inventory_sqlite, "reconcile_live",
        lambda: (_ for _ in ()).throw(RuntimeError("Data not ready")),
    )

    web_api._refresh_pending_allocation()

    assert web_api._PENDING_ALLOCATION_CACHE["refreshing"] is False
    assert "本机" in web_api._PENDING_ALLOCATION_CACHE["last_error"]


def test_pending_allocation_retries_feishu_data_not_ready(monkeypatch):
    attempts = []
    delays = []
    monkeypatch.setattr(web_api, "_PENDING_ALLOCATION_CACHE", {
        "last_attempt": 0.0, "refreshing": True, "last_error": "",
    })

    def reconcile():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("Feishu HTTP 400: 1254607 Data not ready")

    monkeypatch.setattr(pending_inventory_sqlite, "reconcile_live", reconcile)
    monkeypatch.setattr(web_api.time, "sleep", delays.append)

    web_api._refresh_pending_allocation()

    assert len(attempts) == 3
    assert delays == [8, 20]
    assert web_api._PENDING_ALLOCATION_CACHE["last_error"] == ""
    assert web_api._PENDING_ALLOCATION_CACHE["refreshing"] is False


def test_pending_reconciliation_runs_only_on_background_schedule(monkeypatch):
    waits = []
    refreshed = []

    class StopAfterOneRun:
        def wait(self, seconds):
            waits.append(seconds)
            return len(waits) == 2

        def is_set(self):
            return False

    monkeypatch.setattr(web_api, "_PENDING_RECONCILE_STOP", StopAfterOneRun())
    monkeypatch.setattr(web_api, "_PENDING_ALLOCATION_CACHE", {
        "last_attempt": 0.0, "refreshing": False, "last_error": "",
    })
    monkeypatch.setattr(web_api, "_refresh_pending_allocation", lambda: refreshed.append(True))

    web_api._pending_reconcile_loop()

    assert waits == [30, 900]
    assert refreshed == [True]


def test_json_cache_updates_when_published_file_changes(tmp_path, monkeypatch):
    path = tmp_path / "page_data_cache.json"
    path.write_text('{"revision": 1}', encoding="utf-8")
    monkeypatch.setattr(web_api, "resolve_cache_path", lambda _root, _relative: path)

    assert web_api._json("page_data_cache.json")["revision"] == 1
    previous = path.stat()
    path.write_text('{"revision": 2}', encoding="utf-8")
    # Some VM filesystems expose identical timestamps for back-to-back writes.
    # A publication must have distinct file metadata; do not depend on a sleep.
    import os
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
    assert web_api._json("page_data_cache.json")["revision"] == 2


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
    assert response.json()["verifiedLive"] is True


def test_allocation_snapshot_is_read_only_and_skips_feishu(monkeypatch):
    monkeypatch.setattr(legacy_app, "valid_request_review_access_token", lambda *args: True)
    monkeypatch.setattr(legacy_app, "cached_enabled_admin_open_ids", lambda *args: ["ou-admin"])
    monkeypatch.setattr(web_api, "_json", lambda _name: {
        "generated_at": "2026-10-15 16:45:04",
        "tables": {
            legacy_app.REQUEST_TABLE_NAME: [{"record_id": "request-1", "fields": {}}],
            legacy_app.MATERIAL_TABLE_NAME: [],
            legacy_app.CATEGORY_TABLE_NAME: [],
            legacy_app.REQUEST_LINE_TABLE_NAME: [],
        },
    })
    monkeypatch.setattr(pending_inventory_sqlite, "get", lambda _request_id: ({"record_id": "request-1", "fields": {}}, []))
    monkeypatch.setattr(legacy_app, "request_inventory_review_context", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("live read should not run")))
    monkeypatch.setattr(legacy_app, "request_inventory_review_context_from_rows", lambda *_args, **_kwargs: {
        "request": {"record_id": "request-1", "request_no": "REQ-1"},
        "request_row": {"fields": {}}, "lines": [], "result": "库存充足",
        "snapshot_at": "2026-10-15 16:45:04", "material_rows": [], "category_rows": [],
    })
    monkeypatch.setattr(legacy_app, "load_static_request_form_cache", lambda: {"generated_at": "cache-time"})
    monkeypatch.setattr(legacy_app, "cached_allocation_material_records", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_api, "_allocation_operators", lambda _legacy: [])

    response = TestClient(api).get(
        "/api/allocation/request-1?operator=ou-admin&review_token=signed&snapshot=true"
    )

    assert response.status_code == 200
    assert response.json()["verifiedLive"] is False
    assert response.json()["snapshotAt"] == "2026-10-15 16:45:04"


def test_allocation_transient_feishu_error_is_safe_and_retryable(monkeypatch):
    monkeypatch.setattr(legacy_app, "valid_request_review_access_token", lambda *args: True)
    monkeypatch.setattr(legacy_app, "cached_enabled_admin_open_ids", lambda *args: ["ou-admin"])
    monkeypatch.setattr(legacy_app, "request_inventory_review_context", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('Feishu HTTP 400: {"code":1254607,"msg":"Data not ready","log_id":"secret"}')))

    response = TestClient(api).get(
        "/api/allocation/request-1?operator=ou-admin&review_token=signed"
    )

    assert response.status_code == 503
    assert response.headers["X-Pudu-Retryable"] == "1"
    assert "secret" not in response.text
    assert "自动重试" in response.json()["detail"]


def test_allocation_edit_queues_existing_worker_payload(monkeypatch):
    observed = {}
    monkeypatch.setattr(legacy_app, "cached_enabled_admin_open_ids", lambda *args: ["ou-admin"])
    monkeypatch.setattr(
        web_api, "_enqueue_fast",
        lambda task_type, key, payload: observed.update(task_type=task_type, key=key, payload=payload) or "task-allocation",
    )
    response = admin_client(monkeypatch).post(
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


def test_allocation_order_export_endpoints_are_removed(monkeypatch):
    client = admin_client(monkeypatch)
    for name in ("order-preview", "order-workbook"):
        response = client.post(f"/api/allocation/request-1/{name}", json={})
        assert response.status_code == 405


def test_allocation_withdraw_checks_admin_and_stages_deletion(monkeypatch, tmp_path):
    monkeypatch.setenv("PUDU_PENDING_INVENTORY_DB", str(tmp_path / "pending.sqlite3"))
    pending_inventory_sqlite.upsert({"record_id": "recRequest", "fields": {
        "申请单号": "REQ-DELETE", "申请类型": "普通物料申请", "审批状态": "待审批",
        "库存审查状态": "待核实库存", "申请变更次数": "2",
    }}, [{"record_id": "recLine", "fields": {}}])
    observed = []
    monkeypatch.setattr(web_api, "_enqueue_fast", lambda *args: observed.append(args) or "delete-task")
    assert TestClient(api).post("/api/allocation/recRequest/withdraw", json={"expected_version": 2}).status_code == 403
    client = admin_client(monkeypatch)
    assert client.post("/api/allocation/recRequest/withdraw", json={"expected_version": -1}).status_code == 422
    assert not observed
    response = client.post("/api/allocation/recRequest/withdraw", json={"expected_version": 2})
    assert response.status_code == 200
    assert observed[0][0] == "物料申请撤回删除"
    assert observed[0][2]["draft"]["request_id"] == "recRequest"
    assert observed[0][2]["draft"]["operator_open_id"]
    # Acceptance alone does not remove a record before the business write succeeds.
    assert pending_inventory_sqlite.get("recRequest") is not None


def test_receipt_registration_is_local_and_never_waits_on_feishu(monkeypatch):
    import submission_receipts
    observed = []
    monkeypatch.setattr(submission_receipts, "enqueue", lambda *args: observed.append(args))
    monkeypatch.setattr(legacy_app, "feishu_client", lambda: pytest.fail("must not call Feishu on receipt registration"))
    web_api._schedule_submission_receipt("token", "ou_applicant", "物料申领", ["task-1"])
    assert observed == [("token", "ou_applicant", "物料申领", ["task-1"])]
