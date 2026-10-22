from copy import deepcopy
from unittest.mock import Mock

import pytest

import app


def row(record_id="row-1", quantity=0):
    return {"record_id": record_id, "category": "公仔", "material_code": record_id,
            "model": record_id, "language": "无需语种", "quantity": quantity}


def draft(kind="material_rows", records=None):
    records = [row()] if records is None else records
    return {"delete_kind": kind, "category_names": ["公仔"],
            "record_ids": [r["record_id"] for r in records], "records": records}


@pytest.mark.parametrize("change", [
    {"delete_kind": ""}, {"delete_kind": "invalid"}, {"category_names": []},
    {"record_ids": []}, {"records": []}, {"record_ids": ["row-2"]},
    {"record_ids": ["row-1", "row-1"]},
    {"records": [{**row(), "category": "其他品类"}]},
])
def test_invalid_deletion_scope_fails_before_any_read_or_write(monkeypatch, change):
    refresh = Mock()
    delete = Mock()
    monkeypatch.setattr(app, "refresh_page_cache_tables", refresh)
    monkeypatch.setattr(app, "delete_feishu_category", delete)
    with pytest.raises(ValueError):
        app.execute_category_delete({**draft(), **change}, notify_admins=False)
    refresh.assert_not_called()
    delete.assert_not_called()


def test_empty_selection_never_deletes_category():
    with pytest.raises(ValueError, match="空选择"):
        app.validate_category_delete_draft(draft(records=[]))


def test_entire_empty_category_requires_name_and_checkbox_for_web_submit():
    plan = {**draft("categories", []), "requires_explicit_confirmation": True}
    with pytest.raises(ValueError, match="确认删除范围"):
        app.validate_category_delete_draft(plan, require_confirmation=True)
    plan["scope_confirmed"] = True
    for name in ("", "公仔 ", "其他品类"):
        with pytest.raises(ValueError, match="完整品类名称"):
            app.validate_category_delete_draft({**plan, "confirmed_category_name": name})
    app.validate_category_delete_draft({**plan, "confirmed_category_name": "公仔"})


@pytest.fixture
def worker_data(monkeypatch):
    records = [row("row-1"), row("row-2", 561), row("row-3", 242)]
    monkeypatch.setattr(app, "refresh_page_cache_tables", lambda *_: None)
    monkeypatch.setattr(app, "load_feishu_category_records", lambda: [{"record_id": "cat-1", "category": "公仔"}])
    monkeypatch.setattr(app, "load_feishu_inventory_records", lambda: records)
    delete_row, delete_category, counts = Mock(), Mock(), Mock()
    monkeypatch.setattr(app, "delete_feishu_inventory_item", delete_row)
    monkeypatch.setattr(app, "delete_feishu_category", delete_category)
    monkeypatch.setattr(app, "update_category_inventory_counts", counts)
    return records, delete_row, delete_category, counts


def test_row_deletion_keeps_unselected_rows_and_category(worker_data):
    records, delete_row, delete_category, counts = worker_data
    result = app.execute_category_delete(draft(records=[deepcopy(records[0])]), notify_admins=False)
    assert result["deleted_count"] == 1
    delete_row.assert_called_once_with("row-1")
    delete_category.assert_not_called()
    assert counts.call_args.args[1] == records[1:]


def test_selecting_every_row_still_keeps_category(worker_data):
    records, delete_row, delete_category, counts = worker_data
    app.execute_category_delete(draft(records=deepcopy(records)), notify_admins=False)
    assert delete_row.call_count == 3
    delete_category.assert_not_called()
    assert counts.call_args.args[1] == []


def test_explicit_entire_category_delete_requires_matching_preview(worker_data):
    records, delete_row, delete_category, _ = worker_data
    plan = {**draft("categories", deepcopy(records)), "requires_explicit_confirmation": True,
            "scope_confirmed": True, "confirmed_category_name": "公仔"}
    result = app.execute_category_delete(plan, notify_admins=False)
    assert result["deleted_count"] == 3
    delete_category.assert_called_once_with("公仔", "cat-1")
    delete_row.assert_not_called()


@pytest.mark.parametrize("mutation", ["stock", "transit", "category", "missing", "new"])
def test_changed_live_scope_blocks_deletion(worker_data, mutation):
    records, delete_row, delete_category, _ = worker_data
    plan = draft("categories" if mutation == "new" else "material_rows", deepcopy(records))
    if mutation == "stock": records[0]["quantity"] = 9
    if mutation == "transit": records[0]["in_transit_quantity"] = 20
    if mutation == "category": records[0]["category"] = "其他品类"
    if mutation == "missing": records.pop()
    if mutation == "new": records.append(row("new-row"))
    with pytest.raises(RuntimeError, match="删除前检查未通过"):
        app.execute_category_delete(plan, notify_admins=False)
    delete_row.assert_not_called()
    delete_category.assert_not_called()


def test_cultural_row_uses_correct_table_and_keeps_category(worker_data, monkeypatch):
    _, delete_row, delete_category, _ = worker_data
    monkeypatch.setattr(app, "load_feishu_inventory_records", lambda: [])
    monkeypatch.setattr(app, "load_feishu_category_records", lambda: [{"record_id": "cat-1", "category": "公仔", "category_definition": app.CATEGORY_DEFINITION_CULTURAL}])
    monkeypatch.setattr(app, "fresh_feishu_rows", lambda _: [])
    monkeypatch.setattr(app, "load_cultural_dimension_inventory_records", lambda _: [row()])
    delete_cultural = Mock()
    monkeypatch.setattr(app, "feishu_batch_delete_record_ids", delete_cultural)
    app.execute_category_delete(draft(), notify_admins=False)
    delete_cultural.assert_called_once_with(app.CULTURAL_MATERIAL_TABLE_NAME, ["row-1"])
    delete_row.assert_not_called()
    delete_category.assert_not_called()
