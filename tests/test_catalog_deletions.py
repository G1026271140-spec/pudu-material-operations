from copy import deepcopy
from unittest.mock import Mock

import pytest

import app
import catalog_deletions as journal
import importlib

web = importlib.import_module("request_web.api")


def test_journal_is_shared_idempotent_and_does_not_mutate_snapshot():
    snapshot = {"tables": {"物料主数据": [
        {"record_id": "deleted", "fields": {"产品型号": "BG1"}},
        {"record_id": "kept", "fields": {"产品型号": "BellaBot", "启用状态": "停用"}},
        {"record_id": "recreated", "fields": {"产品型号": "BG1"}},
    ]}, "row_counts": {"物料主数据": 3}}
    before = deepcopy(snapshot)
    original_revision = journal.revision()
    journal.record_deleted("物料主数据", ["deleted"])
    revision = journal.revision()
    assert revision != original_revision
    journal.record_deleted("物料主数据", ["deleted", "deleted"])
    assert journal.revision() == revision
    filtered = journal.filter_page_snapshot(snapshot)
    assert [row["record_id"] for row in filtered["tables"]["物料主数据"]] == ["kept", "recreated"]
    assert filtered["row_counts"]["物料主数据"] == 2
    assert snapshot == before
    # The next process/module instance sees the same successful deletions.
    assert importlib.reload(journal).deleted_records() == {"物料主数据": {"deleted"}}


def test_failed_source_delete_does_not_hide_record(monkeypatch):
    client = Mock()
    client.delete_record.side_effect = RuntimeError("source refused deletion")
    monkeypatch.setattr(app, "feishu_client", lambda: client)
    monkeypatch.setattr(app, "feishu_table_id", lambda _: "table")
    with pytest.raises(RuntimeError):
        app.delete_feishu_inventory_item("still-exists")
    assert journal.deleted_records() == {}
    client.delete_record.side_effect = None
    app.delete_feishu_inventory_item("now-deleted")
    assert journal.deleted_records() == {app.MATERIAL_TABLE_NAME: {"now-deleted"}}


def test_partial_category_failure_only_hides_successfully_deleted_records(monkeypatch):
    client = Mock()
    client.delete_record.side_effect = [None, RuntimeError("second row failed")]
    monkeypatch.setattr(app, "feishu_client", lambda: client)
    monkeypatch.setattr(app, "feishu_table_id", lambda name: name)
    monkeypatch.setattr(app, "feishu_material_rows", lambda: [
        {"record_id": "first", "fields": {"物料品类": "公仔"}},
        {"record_id": "second", "fields": {"物料品类": "公仔"}},
    ])
    with pytest.raises(RuntimeError, match="second row"):
        app.delete_feishu_category("公仔", "category")
    assert journal.deleted_records() == {app.MATERIAL_TABLE_NAME: {"first"}}


def test_revision_endpoint_is_small_and_not_browser_cached():
    from fastapi.testclient import TestClient

    response = TestClient(web.api).get("/api/catalog/revision")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"revision"}
    assert len(response.json()["revision"]) == 64


@pytest.mark.parametrize("remaining", [[], ["BellaBot"], ["BellaBot", "停用型号"]])
def test_old_request_cache_never_revives_deleted_options_for_any_role(monkeypatch, remaining):
    category = {"record_id": "cat", "fields": {"物料品类": "公仔", "品类定义": "周边礼品"}}
    stale = ["BellaBot", "BG1", "T600"]
    cache = {"products": ["公仔"], "inventory_rows": [
        {"product": "公仔", "model": model, "language": "无需语种", "material_code": model}
        for model in stale
    ]}
    page = {"tables": {app.CATEGORY_TABLE_NAME: [category], app.MATERIAL_TABLE_NAME: [
        {"record_id": model, "fields": {"物料编码": model, "物料品类": "公仔", "产品型号": model,
                                       "语种": "无需语种", "启用状态": "停用", "是否在申领页显示": "否"}}
        for model in remaining
    ]}}
    monkeypatch.setattr(web, "_json", lambda name: cache if name == "request_form_cache.json" else page if name == "page_data_cache.json" else {})
    monkeypatch.setattr(web, "_image_index", lambda: {})
    catalog = web.build_catalog()
    standard = {option["model"] for product in catalog["products"] for option in product["options"]}
    admin = {option["model"] for product in catalog["adminProducts"] for option in product["options"]}
    assert standard == set(stale) & set(remaining)
    assert admin == set(remaining)


def test_api_parsed_cache_observes_deletion_without_file_change(monkeypatch, tmp_path):
    # The parser is mocked below, but the metadata key still needs a real file.
    (tmp_path / "page_data_cache.json").write_text("{}", encoding="utf-8")
    from pathlib import Path
    monkeypatch.setattr(web, "resolve_cache_path", lambda _root, relative: tmp_path / Path(relative).name)
    page = {"tables": {app.MATERIAL_TABLE_NAME: [{"record_id": "old"}, {"record_id": "new"}]}}
    monkeypatch.setattr(web, "_parsed_json_cache", lambda *_: page)
    before = web.catalog_revision()
    journal.record_deleted(app.MATERIAL_TABLE_NAME, ["old"])
    assert web.catalog_revision() != before
    assert [row["record_id"] for row in web._json("page_data_cache.json")["tables"][app.MATERIAL_TABLE_NAME]] == ["new"]
    assert len(page["tables"][app.MATERIAL_TABLE_NAME]) == 2
