import json
from pathlib import Path

from material_store.inventory import build


def test_export_has_one_stable_sql_column_per_source_field_and_excludes_shipping():
    root = Path(__file__).resolve().parents[1]
    snapshot = json.loads((root / "config/feishu_field_registry.json").read_text(encoding="utf-8-sig"))
    registry = build(snapshot, root)
    keys = [(row["table_id"], row["field_id"]) for row in registry["fields"]]
    columns = [(row["sql_table"], row["sql_column"]) for row in registry["fields"]]
    assert len(keys) == len(set(keys)) == sum(len(t["fields"]) for t in snapshot["tables"])
    assert len(columns) == len(set(columns))
    assert registry["excluded_pages"] == ["发货模板", "发货排期"]
    assert not {"发货模板", "发货排期"}.intersection(p for f in registry["fields"] for p in f["pages"])
    prices = [row for row in registry["fields"] if row["field_name"] == "单价（人民币）" and row["feishu_type"] == 20]
    assert len(prices) == 2
    assert all(row["source_fields"] for row in prices)
    admin = [row for row in registry["fields"] if row["source"] == "apparel_admin"]
    assert len(admin) == 16
    assert len({row["table_id"] for row in admin}) == 1
    assert next(row for row in admin if row["field_name"] == "最新库存")["feishu_type"] == 20
    assert next(row for row in admin if row["field_name"] == "表格兑换数量")["feishu_type"] == 19
    assert all(row["sources"] or row["mode"] != "系统标识/派生值" for row in registry["api_bindings"])
