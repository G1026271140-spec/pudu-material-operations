from copy import deepcopy
from types import SimpleNamespace

import pytest

import app
import pending_inventory_sqlite as pending
import request_withdrawal as withdrawal
from scripts import submission_worker
from submission_queue import QUEUE_TASK_TYPE_REQUEST_WITHDRAW


def setup_request(monkeypatch, tmp_path):
    monkeypatch.setenv("PUDU_PENDING_INVENTORY_DB", str(tmp_path / "pending.sqlite3"))
    request = {"record_id": "recRequest", "fields": {
        "申请单号": "REQ-TEST-001", "申请类型": "普通物料申请", "审批状态": "待审批",
        "库存审查状态": "待核实库存", "申请变更次数": "2",
        "申请人": [{"id": "ou_applicant", "name": "测试申请人"}],
    }}
    line = {"record_id": "recLine", "fields": {"所属申请单": ["recRequest"], "明细编号": "REQ-TEST-001-01"}}
    other = {"record_id": "recOther", "fields": {"所属申请单": ["recOtherRequest"], "明细编号": "REQ-OTHER-01"}}
    state = {"request": request, "lines": [line, other], "deletes": [], "sends": []}

    def delete_batch(table, ids):
        state["deletes"].extend(ids)
        state["lines"] = [row for row in state["lines"] if row["record_id"] not in ids]

    def delete_request(table, record_id):
        state["deletes"].append(record_id)
        state["request"] = None

    def send(client, recipient, card, key):
        state["sends"].append(recipient)
        return "om-" + recipient

    client = SimpleNamespace(
        get_record=lambda table, record_id: state["request"],
        search_records=lambda *args: [state["request"]] if state["request"] else [],
        batch_delete_records=delete_batch, delete_record=delete_request,
    )
    monkeypatch.setattr(app, "feishu_client", lambda: client)
    monkeypatch.setattr(app, "feishu_table_id", lambda name: name)
    monkeypatch.setattr(app, "enabled_admin_open_ids", lambda: ["ou_admin"])
    monkeypatch.setattr(app, "fresh_feishu_rows", lambda table: list(state["lines"]))
    monkeypatch.setattr(withdrawal, "send_notice", send)
    pending.upsert(request, [line])
    task = SimpleNamespace(
        task_type=QUEUE_TASK_TYPE_REQUEST_WITHDRAW, result={},
        payload={"draft": {"request_id": "recRequest", "operator_open_id": "ou_admin", "expected_version": 2}},
    )
    return task, state


def test_withdraw_deletes_only_target_and_notifies_admin_and_applicant(monkeypatch, tmp_path):
    task, state = setup_request(monkeypatch, tmp_path)
    result = submission_worker.process_task(task, lambda progress: None)
    assert state["deletes"] == ["recLine", "recRequest"]
    assert state["sends"] == ["ou_admin", "ou_applicant"]
    assert pending.get("recRequest") is None
    assert result["withdrawn"] is True
    card = withdrawal.withdrawal_card("REQ-TEST-001", "申请人", ["ou_admin"])
    assert "被撤回" in card["body"]["elements"][0]["content"]
    assert "<at id=ou_admin>" in card["body"]["elements"][0]["content"]


def test_withdraw_resumes_notifications_without_redeleting(monkeypatch, tmp_path):
    task, state = setup_request(monkeypatch, tmp_path)

    def fail_applicant(client, recipient, card, key):
        if recipient == "ou_applicant":
            raise RuntimeError("temporary network error")
        state["sends"].append(recipient)
        return "om-admin"

    monkeypatch.setattr(withdrawal, "send_notice", fail_applicant)
    checkpoint = lambda progress: setattr(task, "result", deepcopy(progress))
    with pytest.raises(RuntimeError, match="temporary"):
        withdrawal.process_withdrawal(task, checkpoint)
    assert task.result["write_done"] is True
    monkeypatch.setattr(withdrawal, "send_notice", lambda c, r, card, key: state["sends"].append(r) or "om-applicant")
    withdrawal.process_withdrawal(task, checkpoint)
    assert state["deletes"] == ["recLine", "recRequest"]
    assert state["sends"] == ["ou_admin", "ou_applicant"]


def test_withdraw_recovers_after_header_delete_checkpoint_failure(monkeypatch, tmp_path):
    task, state = setup_request(monkeypatch, tmp_path)

    def checkpoint(progress):
        if progress.get("write_done"):
            raise RuntimeError("checkpoint failed")
        task.result = deepcopy(progress)

    with pytest.raises(RuntimeError, match="checkpoint failed"):
        withdrawal.process_withdrawal(task, checkpoint)
    assert state["request"] is None
    result = withdrawal.process_withdrawal(task, lambda progress: None)
    assert result["withdrawn"] is True
    assert state["deletes"] == ["recLine", "recRequest"]


@pytest.mark.parametrize("change", ["version", "confirmed", "cultural", "nonadmin"])
def test_withdraw_refuses_stale_or_ineligible_request(monkeypatch, tmp_path, change):
    task, state = setup_request(monkeypatch, tmp_path)
    fields = state["request"]["fields"]
    if change == "version":
        fields["申请变更次数"] = "3"
    elif change == "confirmed":
        fields["库存审查状态"] = "已核实库存"
    elif change == "cultural":
        fields["申请类型"] = "文化周边申请"
    else:
        task.payload["draft"]["operator_open_id"] = "ou_sales"
    with pytest.raises((ValueError, PermissionError)):
        withdrawal.process_withdrawal(task, lambda progress: None)
    assert not state["deletes"]
    assert not state["sends"]
