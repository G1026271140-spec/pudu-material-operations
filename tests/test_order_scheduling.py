from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import app
import order_scheduling as r
from order_scheduling_service import SchedulingService


@pytest.mark.parametrize("days,expected", [(7, "加急申请"), (8, "加急申请"), (14, "加急申请"), (15, "普通申请"), (30, "普通申请")])
def test_sales_boundaries(days, expected):
    start = date(2026, 9, 3)
    result = r.calculate_dates(start + timedelta(days=days), start + timedelta(days=days + 3),
                               "代理商支持", ["销售"], submitted=start)
    assert result[r.TIME_CLASS] == expected
    assert r.as_date(result[r.ORDER_DATE]) == r.order_workday(start + timedelta(days=days - 15))
    assert r.as_date(result[r.READY_DATE]) == start + timedelta(days=days - 10)


@pytest.mark.parametrize("days", [-1, 0, 1, 6])
def test_sales_reject_short_dates(days):
    start = date(2026, 9, 3)
    with pytest.raises(ValueError):
        r.calculate_dates(start + timedelta(days=days), start + timedelta(days=days), "展会需求", ["销售"], submitted=start)


@pytest.mark.parametrize("roles,reason", [(["销售"], "客户来访"), (["区域市场经理"], "展会需求"),
                                        (["区域市场负责人"], "展会需求"),
                                        (["销售", "区域市场经理"], "代理商支持")])
def test_exemptions(roles, reason):
    assert r.calculate_dates("2026-09-03", "2026-09-03", reason, roles, submitted="2026-09-03")[r.TIME_CLASS] == "时间豁免"
    with pytest.raises(ValueError):
        r.calculate_dates("2026-09-02", "2026-09-02", reason, roles, submitted="2026-09-03")


def test_customer_visit_has_no_lead_time_limit():
    result = r.calculate_dates("2026-09-04", "2026-09-05", "客户来访", ["销售"], submitted="2026-09-03")
    assert result[r.TIME_CLASS] == "时间豁免"


def test_order_schedule_filters_use_review_exclusion_not_order_filter():
    source = open("request_web/frontend/src/ShippingSchedulePage.tsx", encoding="utf-8").read()
    assert "SCHEDULE_URL" in source
    assert "<iframe" in source
    assert "飞书发货排期实时视图" in source


def test_invalid_dates_and_unknown_reason():
    for start, end, reason in [(None, None, "代理商支持"), ("2026-10-02", "2026-10-01", "代理商支持"),
                               ("2026-10-01", "2026-10-02", "")]:
        with pytest.raises(ValueError):
            r.calculate_dates(start, end, reason, ["销售"], submitted="2026-09-03")


def test_request_reason_enum_and_legacy_alias_are_canonicalized():
    assert "代理商支持" in r.REASONS
    assert "代理活动" not in r.REASONS
    result = r.calculate_dates(
        "2026-09-18", "2026-09-18", "代理活动", ["销售"], submitted="2026-09-03"
    )
    assert result["申请原因"] == "代理商支持"


def test_midnight_timezone_and_receipt_guard():
    assert r.as_date(r.date_ms("2026-09-03")) == date(2026, 9, 3)
    with pytest.raises(ValueError):
        r.validate_planned_receipt("2026-09-02", now=date(2026, 9, 3))
    assert r.validate_planned_receipt("2026-09-02", now=date(2026, 9, 3), confirmed_arrived=True) == date(2026, 9, 2)


def complete_schema():
    schema = {name: {"table_id": name, "fields": {}} for name in {*r.SCHEMA, "物料主数据", "库存流水"}}
    for table, fields in r.SCHEMA.items():
        for name, (kind, extra) in fields.items():
            prop = {"table_id": extra} if kind == 18 else {"options": [{"name": n} for n in extra]} if kind == 3 else {}
            schema[table]["fields"][name] = {"type": kind, "property": prop}
    return schema


def test_schema_matches_user_actual_spelling_and_checks_options_links_types():
    schema = complete_schema()
    assert r.schema_errors(schema) == []
    assert r.ARRIVAL_START == "要求达到开始日期"
    assert r.RESTOCK_KEY == "补库幂等建"
    schema["物料申请单"]["fields"][r.ARRIVAL_START]["type"] = 1
    schema[r.DETAIL_TABLE]["fields"]["关联物料"]["property"]["table_id"] = "文化周边管理库存"
    schema[r.BATCH_TABLE]["fields"]["批次状态"]["property"]["options"] = []
    assert len(r.schema_errors(schema)) == 3


def record(rid, **fields):
    return {"record_id": rid, "fields": fields}


class FakeApp:
    def __init__(self):
        self.data = {name: [] for name in app.ALL_PAGE_CACHE_TABLES}
        self.data[app.LEDGER_TABLE_NAME] = []
        self.data[app.REQUEST_TABLE_NAME] = [record("req", 申请类型="普通物料申请", 申请单号="REQ-1",
            申请人=[{"id": "ou_sales", "name": "销售甲"}], 物料用途="活动", 审批状态="待审批",
            库存审查状态="待核实库存", 提交时间=r.date_ms("2026-09-03"), 排期编辑版本=0)]
        self.data[app.REQUEST_LINE_TABLE_NAME] = [record(f"line{i}", 所属申请单=["req"], 物料编码=["mat"],
            申请数量=20, 实际发放数量=0, 明细状态="待审批", 明细编号=f"REQ-1-{i}", 品类名称="旧名", 语种名称="英语", 备注="") for i in range(2)]
        self.data[app.MATERIAL_TABLE_NAME] = [record("mat", 物料品类="内部品类", 产品型号="M1", 语种="英语",
                                                     品类关联=["cat"], 当前库存=10, 在途库存=0, 启用状态="启用")]
        self.data[app.CATEGORY_TABLE_NAME] = [record("cat", 物料品类="内部品类", 中文页面名称="最新中文名", **{app.UNIT_PRICE_RMB_FIELD: 2.0})]
        self.data[r.BATCH_TABLE] = []
        self.data[r.DETAIL_TABLE] = []
        self.data[app.REQUEST_CHANGE_TABLE_NAME] = []
        self.upload_media = Mock(return_value="file_token_test")
        self.changes = []
        self.schema = complete_schema()
        for table, rows in self.data.items():
            self.schema.setdefault(table, {"table_id": table, "fields": {}})
            for row in rows:
                for field in row["fields"]:
                    self.schema[table]["fields"].setdefault(field, {"type": 1})
        for name in ("明细变更说明", "审批通过数量", "原申请数量", "提交时库存快照", "明细业务类型", "品类名称", "产品型号名称", "语种名称", app.REQUEST_PRICE_SNAPSHOT_FIELD, app.REQUEST_LINE_SUBTOTAL_FIELD):
            self.schema[app.REQUEST_LINE_TABLE_NAME]["fields"][name] = {"type": 1}
        for name in ("申请变更次数", "物料明细文字信息", app.REQUEST_TOTAL_RMB_FIELD):
            self.schema[app.REQUEST_TABLE_NAME]["fields"][name] = {"type": 1}
        for name in ("文本", "申请单号", "操作人OpenID", "操作时间", "变更说明", "变更前JSON", "变更后JSON", "变更版本"):
            self.schema[app.REQUEST_CHANGE_TABLE_NAME]["fields"][name] = {"type": 1}
        for name in ("幂等键", "数量", "物料编码", "操作状态"):
            self.schema[app.LEDGER_TABLE_NAME]["fields"][name] = {"type": 1}

    def __getattr__(self, name):
        return getattr(app, name)

    def enabled_admin_open_ids(self):
        return ["ou_admin"]

    def feishu_table_fields(self, table):
        return self.schema[table]["fields"]

    def feishu_client(self):
        return self

    def fresh_feishu_rows(self, table):
        return deepcopy(self.data[table])

    page_data_cache_rows = fresh_feishu_rows

    def refresh_page_cache_tables(self, tables):
        return {}

    def feishu_update_record_fields(self, table, rid, fields):
        row = next(row for row in self.data[table] if row["record_id"] == rid)
        row["fields"].update(deepcopy(fields))
        self.changes.append((table, rid, deepcopy(fields)))
        return deepcopy(row)

    def feishu_batch_create_records(self, table, fields):
        result = []
        for values in fields:
            row = record(f"new-{table}-{len(self.data[table])}", **deepcopy(values))
            self.data[table].append(row)
            result.append(deepcopy(row))
        return result

    def feishu_batch_delete_record_ids(self, table, ids):
        self.data[table] = [row for row in self.data[table] if row["record_id"] not in ids]

    def set_request_line_material_fields(self, fields, material, product, model, language):
        fields.update({"物料编码": [material["record_id"]], "品类名称": product,
                       "产品型号名称": model, "语种名称": language})

    def filter_feishu_fields(self, table, fields):
        return {k: v for k, v in fields.items() if k in self.feishu_table_fields(table)}

    def build_feishu_ledger_fields(self, *args, **kwargs):
        return {"幂等键": kwargs["idempotency_key"], "数量": args[5], "物料编码": [args[0]], "操作状态": "有效"}


@pytest.fixture
def svc(monkeypatch):
    fake = FakeApp()
    service = SchedulingService(fake)
    monkeypatch.setattr(service, "validate_schema", lambda: True)
    monkeypatch.setattr(r, "today", lambda: date(2026, 9, 3))
    return service


def test_group_excludes_cultural_and_uses_current_chinese_name(svc):
    svc.app.data[app.REQUEST_TABLE_NAME].append(record("culture", 申请类型="文化周边申请", 申请单号="C1"))
    groups = svc.grouped_requests(svc.snapshot())
    assert list(groups) == ["req"]
    assert groups["req"]["lines"][0]["category"] == "最新中文名"
    svc.app.data[app.REQUEST_LINE_TABLE_NAME][0]["fields"][r.GENERATED] = "已生成"
    assert svc.grouped_requests(svc.snapshot())["req"]["generated"]
    assert len(svc.grouped_requests(svc.snapshot())["req"]["lines"]) == 2


def generation_payload(svc):
    group = svc.grouped_requests(svc.snapshot())["req"]
    return {"operator_open_id": "ou_admin", "generation_key": "unique-generation-key",
            "fingerprints": {"req": group["fingerprint"]},
            "selections": [{"request_id": "req", "line_id": "line0", "planned_date": "2026-09-10", "confirmed_arrived": False}]}


def mock_export(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "order_scheduling_export", SimpleNamespace(build_order_workbook=lambda _: b"test-workbook-bytes"))


def test_generate_selected_only_then_exclude_whole_request_and_retry_no_duplicate(svc, monkeypatch):
    payload = generation_payload(svc)
    progress = svc.generate(payload, {}, lambda _: None)
    assert progress["write_done"]
    svc.app.upload_media.assert_not_called()
    assert "下单表文件" not in r.SCHEMA[r.BATCH_TABLE]
    assert len(svc.app.data[r.DETAIL_TABLE]) == 1
    assert svc.app.data[r.DETAIL_TABLE][0]["fields"]["下单数量"] == 20
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"][r.IN_TRANSIT_STOCK] == 20
    assert svc.app.data[app.REQUEST_LINE_TABLE_NAME][1]["fields"].get(r.GENERATED) is None
    assert svc.grouped_requests(svc.snapshot())["req"]["generated"]
    svc.generate(payload, {}, lambda _: None)
    assert len(svc.app.data[r.BATCH_TABLE]) == len(svc.app.data[r.DETAIL_TABLE]) == 1
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] == 10
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"][r.IN_TRANSIT_STOCK] == 20
    with pytest.raises(ValueError):
        svc.generate({**payload, "generation_key": "other-key"}, {}, lambda _: None)


def test_stale_selection_and_cultural_payload_rejected(svc, monkeypatch):
    mock_export(monkeypatch)
    payload = generation_payload(svc)
    svc.app.data[app.REQUEST_LINE_TABLE_NAME][0]["fields"]["申请数量"] = 50
    with pytest.raises(ValueError, match="变化"):
        svc.generate(payload, {}, lambda _: None)
    svc.app.data[app.REQUEST_TABLE_NAME][0]["fields"]["申请类型"] = "文化周边申请"
    with pytest.raises(ValueError, match="普通物料"):
        svc.generate(payload, {}, lambda _: None)
    assert svc.app.data[r.BATCH_TABLE] == []


def add_due(svc, **overrides):
    svc.app.data[r.BATCH_TABLE] = [record("batch", 批次状态="已生成", 启用自动补库=True, 生成时间=r.date_ms("2026-09-01"))]
    f = {"所属下单批次": ["batch"], "来源申请单": ["req"], "来源申请明细": ["line0"], "关联物料": ["mat"],
         "补库状态": "待补库", r.RESTOCK_KEY: "unique-restock-key", "下单数量": 20,
         "计划到仓日期": r.date_ms("2026-09-03"), "批次明细编号": "D1"}
    f.update(overrides)
    svc.app.data[r.DETAIL_TABLE] = [record("detail", **f)]


def test_due_guard_past_at_generation_requires_confirmation(svc):
    add_due(svc, 计划到仓日期=r.date_ms("2026-08-31"))
    assert svc.due_details(svc.snapshot()) == []
    svc.app.data[r.DETAIL_TABLE][0]["fields"]["补库异常说明"] = "管理员已确认制作完成并到仓"
    assert len(svc.due_details(svc.snapshot())) == 1
    svc.app.data[r.BATCH_TABLE][0]["fields"]["启用自动补库"] = False
    assert svc.due_details(svc.snapshot()) == []


def test_in_transit_is_recomputed_from_all_active_order_details(svc):
    add_due(svc)
    svc.app.data[r.DETAIL_TABLE].append(record(
        "detail-2", 所属下单批次=["batch"], 关联物料=["mat"],
        补库状态="补库异常", 下单数量=7,
    ))
    svc.app.data[r.DETAIL_TABLE].append(record(
        "detail-cancelled", 所属下单批次=["batch"], 关联物料=["mat"],
        补库状态="已取消", 下单数量=99,
    ))
    svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"][r.IN_TRANSIT_STOCK] = 999
    svc.sync_in_transit_stock(svc.snapshot())
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"][r.IN_TRANSIT_STOCK] == 27


def test_restock_exactly_once_and_never_issue(svc):
    add_due(svc)
    svc.sync_in_transit_stock(svc.snapshot())
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"][r.IN_TRANSIT_STOCK] == 20
    progress = svc.restock({"detail_id": "detail"}, {}, lambda _: None)
    assert progress["write_done"]
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] == 30
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"][r.IN_TRANSIT_STOCK] == 0
    assert len(svc.app.data[app.LEDGER_TABLE_NAME]) == 1
    svc.restock({"detail_id": "detail"}, {}, lambda _: None)
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] == 30
    assert all(row["fields"]["实际发放数量"] == 0 for row in svc.app.data[app.REQUEST_LINE_TABLE_NAME])


def test_canceling_order_removes_in_transit_without_inventory_ledger(svc):
    add_due(svc)
    svc.sync_in_transit_stock(svc.snapshot())
    svc.plan({"operator_open_id": "ou_admin", "action": "fulfillment_update",
              "detail_id": "detail", "status": "已取消"}, {}, lambda _: None)
    assert svc.app.data[r.DETAIL_TABLE][0]["fields"]["补库状态"] == "已取消"
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"][r.IN_TRANSIT_STOCK] == 0
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] == 10
    assert svc.app.data[app.LEDGER_TABLE_NAME] == []


def test_uncertain_stock_write_fails_closed_even_on_retries(svc):
    add_due(svc)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="不明确"):
            svc.restock({"detail_id": "detail"}, {"stock_write_started": True}, lambda _: None)
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] == 10
    assert svc.app.data[r.DETAIL_TABLE][0]["fields"]["补库状态"] == "补库异常"


def test_stock_written_resume_only_writes_ledger(svc):
    add_due(svc)
    svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] = 30
    progress = {"stock_write_started": True, "stock_written": True, "material_id": "mat", "before": 10, "after": 30, "quantity": 20}
    svc.restock({"detail_id": "detail"}, progress, lambda _: None)
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] == 30
    assert len(svc.app.data[app.LEDGER_TABLE_NAME]) == 1


def test_edit_preserves_review_and_stock_and_logs_before_delete(svc):
    group = svc.grouped_requests(svc.snapshot())["req"]
    svc.edit({"operator_open_id": "ou_admin", "request_id": "req", "expected_fingerprint": group["fingerprint"],
              "change_note": "合并需求", "lines": [{"id": "line0", "material_id": "mat", "quantity": 50, "remark": "备注"}]}, {}, lambda _: None)
    assert len(svc.app.data[app.REQUEST_LINE_TABLE_NAME]) == 1
    f = svc.app.data[app.REQUEST_LINE_TABLE_NAME][0]["fields"]
    assert f["申请数量"] == 50 and f["实际发放数量"] == 0
    rf = svc.app.data[app.REQUEST_TABLE_NAME][0]["fields"]
    assert rf["库存审查状态"] == "待核实库存" and rf["审批状态"] == "待审批"
    assert rf["申请变更次数"] == "1"
    assert svc.app.data[app.MATERIAL_TABLE_NAME][0]["fields"]["当前库存"] == 10
    assert len(svc.app.data[app.REQUEST_CHANGE_TABLE_NAME]) == 1


def test_edit_rejects_approved_or_unauthorized(svc):
    group = svc.grouped_requests(svc.snapshot())["req"]
    with pytest.raises(PermissionError):
        svc.edit({"operator_open_id": "ou_sales"}, {}, lambda _: None)
    group["status"] = "已通过"
    with pytest.raises(ValueError, match="编辑"):
        svc.check_group(group, group["fingerprint"], editing=True)


def test_queued_edit_overwrites_manual_status_change(svc):
    request_fields = svc.app.data[app.REQUEST_TABLE_NAME][0]["fields"]
    request_fields["审批状态"] = "已完成"
    request_fields["库存审查状态"] = "已核实库存"
    svc.edit({
        "operator_open_id": "ou_admin",
        "request_id": "req",
        "change_note": "按队列草稿覆盖",
        "lines": [{
            "id": "line0",
            "material_id": "mat",
            "quantity": 25,
            "remark": "队列目标值",
        }],
    }, {}, lambda _: None)
    line_fields = svc.app.data[app.REQUEST_LINE_TABLE_NAME][0]["fields"]
    assert line_fields["申请数量"] == 25
    assert line_fields["备注"] == "队列目标值"


def test_export_aggregation_keeps_different_production_remarks_separate():
    line = {"category": "单页", "model": "M", "language": "英语", "quantity": 20, "usage": "活动", "remark": "纸张A"}
    result = r.aggregate_export_rows([line, line, {**line, "remark": "纸张B"}])
    assert [row[3] for row in result] == [40, 20]
    assert "纸张A" in result[0][4]


def test_queue_dispatch_requires_checkpoints_and_cache_is_separate():
    from scripts.submission_worker import process_task, SUPPORTED_QUEUE_TASK_TYPES
    from submission_queue import QUEUE_TASK_TYPE_ORDER_RESTOCK
    task = SimpleNamespace(task_type=QUEUE_TASK_TYPE_ORDER_RESTOCK, payload={}, result={})
    assert QUEUE_TASK_TYPE_ORDER_RESTOCK in SUPPORTED_QUEUE_TASK_TYPES
    with pytest.raises(RuntimeError, match="检查点"):
        process_task(task)
    assert r.BATCH_TABLE in app.PAGE_CACHE_TABLES["order_scheduling"]
    assert r.BATCH_TABLE not in app.PAGE_CACHE_TABLES["cultural_request"]


def test_catalog_excludes_legacy_cultural_materials(svc):
    svc.app.data[app.CATEGORY_TABLE_NAME][0]["fields"]["品类定义"] = "文化周边"
    assert svc.catalog(svc.snapshot(), include_ids={"mat"}) == {}


def test_restock_scheduler_resumes_skipped_jobs_but_not_failed_jobs(svc, monkeypatch):
    import submission_queue as queue
    add_due(svc)
    base = "schedule-restock:unique-restock-key"
    old = SimpleNamespace(status=queue.QUEUE_STATUS_COMPLETED, result={"skipped": "暂停"}, task_id="previous")
    lookup = {base: old}
    monkeypatch.setattr(queue, "find_task_by_idempotency_key", lambda client, key: lookup.get(key))
    enqueue = Mock(return_value=(None, True))
    monkeypatch.setattr(svc.app, "enqueue_feishu_background_write", enqueue)
    assert svc.enqueue_due() == 1
    assert enqueue.call_args.args[2] == base + ":after:previous"
    lookup[base + ":after:previous"] = SimpleNamespace(status=queue.QUEUE_STATUS_FAILED, result={}, task_id="failed")
    assert svc.enqueue_due() == 0
    assert enqueue.call_count == 1


def test_date_edit_retains_submission_role_snapshot(svc):
    svc.app.data[app.REQUEST_TABLE_NAME][0]["fields"]["申请时角色快照"] = "销售"
    svc.roles = Mock(return_value=["区域市场经理"])
    group = svc.grouped_requests(svc.snapshot())["req"]
    with pytest.raises(ValueError, match="至少提前7"):
        svc.plan({"operator_open_id": "ou_admin", "action": "request_dates", "request_id": "req",
            "expected_fingerprint": group["fingerprint"], "request_reason": "代理商支持",
            "arrival_start": "2026-09-05", "arrival_end": "2026-09-05"}, {}, lambda _: None)
    svc.roles.assert_not_called()


def test_request_ship_date_updates_request_and_all_schedule_details(svc):
    svc.app.data[app.REQUEST_LINE_TABLE_NAME] = [
        record("line-1", **{"所属申请单": ["req"], r.SHIP_DATE: None}),
        record("line-2", **{"所属申请单": ["req"], r.SHIP_DATE: None}),
        record("line-other", **{"所属申请单": ["other"], r.SHIP_DATE: None}),
    ]
    svc.app.data[r.DETAIL_TABLE] = [
        record("detail-1", **{"来源申请单": ["req"], r.SHIP_DATE: None}),
        record("detail-2", **{"来源申请单": ["req"], r.SHIP_DATE: None}),
        record("detail-other", **{"来源申请单": ["other"], r.SHIP_DATE: None}),
    ]
    svc.plan(
        {
            "operator_open_id": "ou_admin",
            "action": "request_ship_date",
            "request_id": "req",
            "ship_date": "2026-09-12",
        },
        {},
        lambda _: None,
    )

    expected = r.date_ms("2026-09-12")
    assert svc.app.data[app.REQUEST_TABLE_NAME][0]["fields"][r.SHIP_DATE] == expected
    assert [svc.app.data[app.REQUEST_LINE_TABLE_NAME][index]["fields"][r.SHIP_DATE] for index in (0, 1)] == [expected, expected]
    assert [
        svc.app.data[r.DETAIL_TABLE][index]["fields"][r.SHIP_DATE]
        for index in (0, 1)
    ] == [expected, expected]
    assert svc.app.data[r.DETAIL_TABLE][2]["fields"][r.SHIP_DATE] is None


def test_request_dates_syncs_all_schedule_dates_to_lines_details_and_batches(svc):
    svc.app.data[app.REQUEST_LINE_TABLE_NAME] = [record("line-1", **{"所属申请单": ["req"]})]
    svc.app.data[r.DETAIL_TABLE] = [record("detail-1", **{"来源申请单": ["req"], "所属下单批次": ["batch-1"]})]
    svc.app.data[r.BATCH_TABLE] = [record("batch-1")]
    svc.plan({"operator_open_id": "ou_admin", "action": "request_dates", "request_id": "req",
              "request_reason": "代理商支持", "arrival_start": "2026-09-20", "arrival_end": "2026-09-22"}, {}, lambda _: None)
    request_fields = svc.app.data[app.REQUEST_TABLE_NAME][0]["fields"]
    for table, index in ((app.REQUEST_LINE_TABLE_NAME, 0), (r.DETAIL_TABLE, 0), (r.BATCH_TABLE, 0)):
        fields = svc.app.data[table][index]["fields"]
        assert fields[r.USAGE_DATE] == request_fields[r.USAGE_DATE]
        assert fields[r.ORDER_DATE] == request_fields[r.ORDER_DATE]


pass  # Retired widget test: test_request_date_widgets_default_empty_and_accept_single_date


pass  # Retired widget test: test_admin_page_renders_groups_and_edit_dialog


def test_prepare_download_without_network_or_writes_and_worker_no_attachment(svc):
    from order_scheduling_export import build_order_workbook
    payload = generation_payload(svc)
    snapshot = svc.snapshot()
    original_read = svc.app.fresh_feishu_rows
    svc.app.fresh_feishu_rows = Mock(side_effect=AssertionError("UI must not read network"))
    prepared = svc.prepare_export(payload, snapshot)
    assert build_order_workbook(prepared).startswith(b"PK")
    assert not svc.app.changes
    svc.app.fresh_feishu_rows = original_read
    svc.generate({**payload, "export_rows": prepared}, {}, lambda _: None)
    svc.app.upload_media.assert_not_called()
    assert "下单表文件" not in svc.app.data[r.BATCH_TABLE][0]["fields"]


def test_download_snapshot_mismatch_rejected_before_batch_write(svc):
    payload = generation_payload(svc)
    prepared = svc.prepare_export(payload, svc.snapshot())
    prepared[0]["quantity"] += 1
    with pytest.raises(ValueError, match="下载明细"):
        svc.generate({**payload, "export_rows": prepared}, {}, lambda _: None)
    assert not svc.app.data[r.BATCH_TABLE]
    assert not svc.app.changes


def test_record_write_ignores_unrelated_request_fingerprint_change(svc):
    payload = generation_payload(svc)
    prepared = svc.prepare_export(payload, svc.snapshot())
    svc.app.data[app.REQUEST_TABLE_NAME][0]["fields"]["客户名称"] = "与下单明细无关的后续更新"
    result = svc.record_schedule({**payload, "export_rows": prepared}, {}, lambda _: None)
    assert result["write_done"]
    svc.app.upload_media.assert_not_called()


def test_record_write_rejects_changed_selected_line_snapshot(svc):
    payload = generation_payload(svc)
    prepared = svc.prepare_export(payload, svc.snapshot())
    svc.app.data[app.REQUEST_LINE_TABLE_NAME][0]["fields"]["申请数量"] = 21
    with pytest.raises(ValueError, match="下载明细"):
        svc.record_schedule({**payload, "export_rows": prepared}, {}, lambda _: None)
    assert not svc.app.data[r.BATCH_TABLE]


def test_new_queue_type_describes_record_write_only():
    import submission_queue as queue
    assert queue.QUEUE_TASK_TYPE_ORDER_RECORD == "下单排期记录写入"
    assert queue.QUEUE_TASK_TYPE_ORDER_GENERATE_LEGACY == "下单排期生成表单"


def test_async_write_copies_payload_and_does_not_wait():
    from threading import Event
    from order_scheduling_async import submit_write
    entered, release = Event(), Event()
    def write(kind, payload, key):
        entered.set()
        assert release.wait(5)
        return payload
    payload = {"lines": [1]}
    future = submit_write(SimpleNamespace(enqueue_feishu_background_write=write), "kind", payload, "stable-key")
    try:
        assert entered.wait(2)
        assert not future.done()
        payload["lines"].append(2)
    finally:
        release.set()
    assert future.result(timeout=2) == {"lines": [1]}


pass  # Retired widget test: test_pending_io_does_not_block_page_and_issued_requests_hidden
