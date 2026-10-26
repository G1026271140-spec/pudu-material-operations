from datetime import datetime, timezone

import pytest

import app
from allocation_display import required_arrival_fields
from request_web.api import _allocation_summary


@pytest.mark.parametrize("fields,expected", [
    ({}, ("", "", "")),
    ({"物料要求到达时间": "2026-11-02 16:30"}, ("2026-11-02 16:30", "", "")),
    ({"要求达到开始日期": "2026-11-02", "要求到达结束日期": "2026-11-04"}, ("", "2026-11-02", "2026-11-04")),
    ({"要求到达开始日期": "2026/11/02", "要求到达结束日期": "2026/11/02"}, ("", "2026-11-02", "2026-11-02")),
    ({"物料要求到达时间": [{"text": "2026-11-02"}]}, ("2026-11-02", "", "")),
    ({"物料发货时间": "2026-11-01", "物料到货时间": "2026-11-03", "物料使用时间": "2026-11-04"}, ("", "", "")),
    ({"物料要求到达时间": "展会前一日"}, ("展会前一日", "", "")),
])
def test_arrival_fields_preserve_source_meaning(fields, expected):
    result = required_arrival_fields(fields)
    assert tuple(result.values()) == expected


def test_milliseconds_are_formatted_in_china_timezone_not_server_timezone():
    timestamp = int(datetime(2026, 11, 1, 16, tzinfo=timezone.utc).timestamp() * 1000)
    result = required_arrival_fields({"要求达到开始日期": timestamp})
    assert result["required_arrival_start"] == "2026-11-02"


def test_list_and_detail_both_get_arrival_without_stock_or_network_reads(monkeypatch):
    row = {"record_id": "request-arrival", "fields": {
        "申请单号": "REQ-ARRIVAL", "申请类型": "普通物料申请", "审批状态": "待审批",
        "要求达到开始日期": "2026-11-02", "要求到达结束日期": "2026-11-04",
    }}
    monkeypatch.setattr(app, "fresh_feishu_rows", lambda *_args: pytest.fail("Unexpected source read"))
    record = app.load_feishu_request_records([row])[0]
    assert record["required_arrival_start"] == "2026-11-02"
    summary = app.pending_inventory_review_summaries([row])[0]
    assert summary["requiredArrivalStart"] == "2026-11-02"
    assert summary["requiredArrivalEnd"] == "2026-11-04"
    assert _allocation_summary({"request": record})["requiredArrivalEnd"] == "2026-11-04"


def test_snapshot_and_live_context_use_the_same_arrival_parser():
    row = {"record_id": "request-arrival", "fields": {"申请单号": "REQ-ARRIVAL", "物料要求到达时间": "2026-11-02"}}
    context = app.request_inventory_review_context_from_rows(row, [], [], [])
    assert context["request"]["required_arrival_time"] == "2026-11-02"
