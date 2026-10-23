from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

import app
from scripts import submission_worker as worker
from submission_queue import QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST
from tests.test_submission_worker import material_request_task


POLO = "休闲商务POLO-黑色（短袖）"
TSHIRT = "T恤-黑色（短袖）"
LINES = [{"product": POLO, "size": "7XL", "quantity": 1},
         {"product": TSHIRT, "size": "7XL", "quantity": 1}]
EXCEEDED = [{"product": TSHIRT, "field": "T恤-黑色（短袖）申领数量累计",
             "current": 1, "requested": 1, "target": 2, "limit": 1}]
REJECT_PLAN = {"quota_allowed": False, "quota_exceeded": EXCEEDED, "items": []}


@pytest.fixture(autouse=True)
def isolated_quota_schema(monkeypatch):
    # Field discovery must not depend on a developer's live schema cache.
    fields = {name: {"type": 2} for aliases, _limit in app.CORPORATE_APPAREL_QUOTA_FIELDS.values() for name in aliases}
    monkeypatch.setattr(app, "feishu_schema", lambda: {"tables": {app.USER_PERMISSION_TABLE_NAME: {"fields": fields}}})


@pytest.mark.parametrize("lines,current,expected_requested", [
    (LINES, 1, 1),
    ([{"product": POLO, "size": "M", "quantity": 1},
      {"product": POLO, "size": "L", "quantity": 1}], 1, 2),
])
def test_quota_rejection_precedes_inventory_read(lines, current, expected_requested):
    fields = {"用户账号": [{"id": "ou_sales"}],
              "POLO申领数量累计": current,
              "T恤-黑色（短袖）申领数量累计": current}
    with (
        patch.object(app, "ensure_requester_sales_permission"),
        patch.object(app, "ensure_corporate_apparel_quota_fields"),
        patch.object(app, "fresh_feishu_rows", return_value=[{"record_id": "perm", "fields": fields}]),
        patch.object(app, "corporate_apparel_source_client") as source,
    ):
        plan = app.corporate_apparel_request_plan({"requester_open_id": "ou_sales"}, lines)
    assert plan["quota_allowed"] is False
    assert plan["items"] == []
    assert plan["quota_exceeded"][0]["requested"] == expected_requested
    source.assert_not_called()


def test_allowed_plan_still_uses_source_inventory_and_quota_targets():
    with (
        patch.object(app, "ensure_requester_sales_permission"),
        patch.object(app, "ensure_corporate_apparel_quota_fields"),
        patch.object(app, "fresh_feishu_rows", return_value=[{
            "record_id": "perm", "fields": {"用户账号": [{"id": "ou_sales"}]},
        }]),
        patch.object(app, "corporate_apparel_source_client") as source,
        patch.object(app, "corporate_apparel_catalog", return_value={"items": [
            {"product": POLO, "size": "7XL", "available": 3, "system_redeemed": 4},
        ]}),
    ):
        plan = app.corporate_apparel_request_plan({"requester_open_id": "ou_sales"}, LINES[:1])
    assert plan["quota_allowed"] is True
    assert plan["items"][0]["target_system_redeemed"] == 5
    assert plan["quota_targets"][0]["target"] == 1
    source.return_value.list_records.assert_called_once()


def test_rejected_plan_cannot_enter_business_writer():
    with patch.object(app, "refresh_feishu_schema_cache") as refresh:
        with pytest.raises(ValueError, match="只能发送驳回通知"):
            app.submit_feishu_corporate_apparel_request({}, REJECT_PLAN)
    refresh.assert_not_called()


@patch.object(app, "request_model_display_label", side_effect=lambda value, **_: str(value))
def test_rejection_cards_use_tables_hr_recipients_and_no_refund_or_actions(_display):
    with patch.object(app, "enabled_role_open_ids", return_value=["ou_hr"]) as roles:
        targets = app.corporate_apparel_quota_rejection_targets(
            {"requester": "测试人", "requester_open_id": "ou_sales", "material_usage": "入职"},
            LINES, EXCEEDED,
        )
    roles.assert_called_once_with("HR")
    assert [target["audience"] for target in targets] == ["applicant", "hr"]
    for target in targets:
        card = target["card"]
        assert card["header"]["template"] == "red"
        elements = card["body"]["elements"]
        assert all(item["tag"] != "button" for item in elements)
        assert len(next(item for item in elements if item["tag"] == "table")["rows"]) == 2
        reason = elements[1]["content"]
        assert "历史已领取 1 件" in reason
        assert "本次申请 1 件" in reason
        assert "累计上限 1 件" in reason
        assert "申请单号" not in str(card)
        assert "额度已恢复" not in str(card)


def task_with_result(result=None):
    original = material_request_task()
    return replace(original, task_type=QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
                   payload={**original.payload, "lines": LINES}, result=deepcopy(result or {}))


TARGETS = [{"key": "applicant:ou_sales", "audience": "applicant", "recipient_id": "ou_sales", "card": {}},
           {"key": "hr:ou_hr", "audience": "hr", "recipient_id": "ou_hr", "card": {}}]


def test_worker_quota_rejection_completes_without_business_writes():
    task = task_with_result()
    checkpoints = []
    with (
        patch.object(app, "corporate_apparel_request_plan", return_value=REJECT_PLAN),
        patch.object(app, "corporate_apparel_quota_rejection_targets", return_value=TARGETS),
        patch.object(app, "feishu_client", return_value=object()),
        patch("request_withdrawal.send_notice", return_value="om-notice") as send,
        patch.object(app, "submit_feishu_corporate_apparel_request") as write,
        patch.object(app, "feishu_update_record_fields") as update,
        patch.object(app, "execute_corporate_apparel_rejection") as refund,
    ):
        result = worker.process_corporate_apparel_request(task, lambda p: checkpoints.append(deepcopy(p)))
    write.assert_not_called()
    update.assert_not_called()
    refund.assert_not_called()
    assert result["rejected"] and result["business_write_skipped"]
    assert result["notification_done"] and result["rejection_notification_done"]
    assert result["notification_count"] == 2
    assert send.call_count == 2
    assert checkpoints[1]["rejected"]  # Durable before delivery.


def test_partial_notification_retry_resumes_rejection_even_if_quota_changes():
    task = task_with_result()
    saved = []
    with (
        patch.object(app, "corporate_apparel_request_plan", return_value=REJECT_PLAN) as plan,
        patch.object(app, "corporate_apparel_quota_rejection_targets", return_value=TARGETS),
        patch.object(app, "feishu_client", return_value=object()),
        patch("request_withdrawal.send_notice", side_effect=["om-applicant", RuntimeError("timeout")]) as send,
        patch.object(app, "submit_feishu_corporate_apparel_request") as write,
    ):
        with pytest.raises(RuntimeError, match="timeout"):
            worker.process_corporate_apparel_request(task, lambda p: saved.append(deepcopy(p)))
        retry = task_with_result(saved[-1])
        plan.reset_mock()
        send.reset_mock(side_effect=True)
        send.return_value = "om-hr"
        result = worker.process_corporate_apparel_request(retry)
    plan.assert_not_called()
    write.assert_not_called()
    assert send.call_count == 1
    assert send.call_args.args[1] == "ou_hr"
    assert result["notification_count"] == 2
    assert result["rejected"]


def test_unavailable_applicant_does_not_block_rejection_hr_notice():
    with (
        patch.object(app, "corporate_apparel_request_plan", return_value=REJECT_PLAN),
        patch.object(app, "corporate_apparel_quota_rejection_targets", return_value=TARGETS),
        patch.object(app, "feishu_client", return_value=object()),
        patch("request_withdrawal.send_notice", side_effect=[RuntimeError('{"code":230013}'), "om-hr"]),
    ):
        result = worker.process_corporate_apparel_request(task_with_result())
    assert result["rejection_notification_skipped_keys"] == ["applicant:ou_sales"]
    assert result["notification_done"]
    assert result["notification_count"] == 1


def test_completed_rejection_is_idempotent():
    task = task_with_result({"write_plan": REJECT_PLAN, "write_done": True,
                             "rejected": True, "rejection_notification_done": True,
                             "notification_done": True})
    with patch.object(app, "feishu_client") as client:
        result = worker.process_corporate_apparel_request(task)
    client.assert_not_called()
    assert result["rejected"]


def test_successful_old_checkpoint_does_not_recheck_or_reject_existing_request():
    task = task_with_result({"write_plan": {"items": LINES}, "write_done": True,
                             "notification_done": True, "request_no": "REQ-existing"})
    with (
        patch.object(app, "corporate_apparel_request_plan") as plan,
        patch.object(app, "corporate_apparel_quota_rejection_targets") as reject,
        patch.object(app, "submit_feishu_corporate_apparel_request") as write,
    ):
        result = worker.process_corporate_apparel_request(task)
    plan.assert_not_called()
    reject.assert_not_called()
    write.assert_not_called()
    assert result["request_no"] == "REQ-existing"
    assert not result.get("rejected")


def test_business_rejection_is_queue_completion_not_failure():
    task = task_with_result({"write_plan": REJECT_PLAN})
    with (
        patch.object(worker, "process_task", return_value={"rejected": True, "notification_done": True}),
        patch.object(worker, "complete_submission_task") as complete,
        patch.object(worker, "fail_submission_task") as fail,
    ):
        worker.process_claimed_submission_task(Mock(), task)
    complete.assert_called_once()
    fail.assert_not_called()
