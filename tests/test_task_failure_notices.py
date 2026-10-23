from contextlib import closing
from dataclasses import replace
import json
from unittest.mock import ANY, Mock, patch

import pytest

import app
import task_failure_notices as notices
from scripts import submission_worker as worker
from submission_queue import (
    QUEUE_STATUS_FAILED, QUEUE_STATUS_RETRY,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,
    QUEUE_TASK_TYPE_CULTURAL_REQUEST, QUEUE_TASK_TYPE_ORDER_EDIT,
)
from tests.test_submission_worker import material_request_task


def stored():
    with closing(notices._connect()) as connection:
        return connection.execute(
            "SELECT event_key,event_json,status,sent_json,attempts,error FROM alerts ORDER BY rowid"
        ).fetchall()


@pytest.mark.parametrize("kind,role", [
    (QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST, "HR"),
    (QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT, "HR"),
    (QUEUE_TASK_TYPE_CULTURAL_REQUEST, "管理员"),
    ("营销物料申请", "管理员"),
    (QUEUE_TASK_TYPE_ORDER_EDIT, "管理员"),
])
def test_routes_by_feature_and_persists_context_without_network(kind, role):
    task = replace(material_request_task(), task_type=kind, retry_count=2)
    with patch.object(app, "feishu_client") as client:
        notices.enqueue(task, RuntimeError("源表库存不足"), QUEUE_STATUS_RETRY,
                        progress={"request_no": "REQ-42", "write_done": True})
    client.assert_not_called()
    event = json.loads(stored()[0][1])
    assert event["role"] == role
    assert event["attempt"] == 3
    assert event["error"] == "源表库存不足"
    assert event["request_no"] == "REQ-42"
    assert "payload" not in event


def test_same_attempt_deduplicates_but_next_attempt_and_terminal_have_their_own_event():
    task = material_request_task()
    notices.enqueue(task, "timeout", QUEUE_STATUS_RETRY)
    notices.enqueue(task, "timeout", QUEUE_STATUS_RETRY)
    notices.enqueue(replace(task, retry_count=1), "timeout", QUEUE_STATUS_RETRY)
    notices.enqueue(replace(task, retry_count=2), "timeout", QUEUE_STATUS_FAILED)
    assert len(stored()) == 3
    notices.enqueue(replace(task, lease_expires_at=task.lease_expires_at + 1000),
                    "manually retried and failed again", QUEUE_STATUS_RETRY)
    assert len(stored()) == 4


@pytest.mark.parametrize("kind,expected", [
    (QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST, "ou_hr"),
    (QUEUE_TASK_TYPE_CULTURAL_REQUEST, "ou_admin"),
])
def test_delivers_only_to_enabled_responsible_role_not_applicant(kind, expected):
    notices.enqueue(replace(material_request_task(), task_type=kind), "timeout", QUEUE_STATUS_RETRY)
    with (
        patch.object(app, "feishu_client", return_value=object()),
        patch.object(app, "enabled_role_open_ids", return_value=["ou_hr", "ou_hr"]) as hr,
        patch.object(app, "enabled_admin_open_ids", return_value=["ou_admin", "ou_admin"]) as admins,
        patch("request_withdrawal.send_notice", return_value="om-alert") as send,
        patch.object(app, "feishu_update_record_fields") as business_write,
    ):
        notices.deliver_pending()
        notices.deliver_pending()
    assert send.call_count == 1
    assert send.call_args.args[1] == expected
    business_write.assert_not_called()
    if expected == "ou_hr":
        hr.assert_called_once_with("HR")
        admins.assert_not_called()
    else:
        admins.assert_called_once()
        hr.assert_not_called()
    assert stored()[0][2] == "sent"


def test_failed_recipient_is_retried_without_resending_successful_recipients():
    notices.enqueue(material_request_task(), "timeout", QUEUE_STATUS_FAILED)
    with (
        patch.object(app, "feishu_client", return_value=object()),
        patch.object(app, "enabled_admin_open_ids", return_value=["ou_a", "ou_b"]),
        patch("request_withdrawal.send_notice", side_effect=[RuntimeError("offline"), "om-b"]) as send,
    ):
        notices.deliver_pending()
        first_key = send.call_args_list[0].args[3]
        assert send.call_count == 2  # Failure of first manager does not block second.
        row = stored()[0]
        assert row[2] == "pending"
        assert json.loads(row[3]) == {"ou_b": "om-b"}
        with closing(notices._connect()) as connection, connection:
            connection.execute("UPDATE alerts SET retry_at=0")
        send.reset_mock(side_effect=True)
        send.return_value = "om-a"
        notices.deliver_pending()
    send.assert_called_once()
    assert send.call_args.args[1] == "ou_a"
    assert send.call_args.args[3] == first_key
    assert stored()[0][2] == "sent"


def test_alert_survives_missing_credentials_or_no_enabled_hr():
    notices.enqueue(replace(material_request_task(), task_type=QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST),
                    "timeout", QUEUE_STATUS_FAILED)
    with patch.object(app, "feishu_client", return_value=None):
        notices.deliver_pending()
    assert stored()[0][2] == "pending"
    with closing(notices._connect()) as connection, connection:
        connection.execute("UPDATE alerts SET retry_at=0")
    with (
        patch.object(app, "feishu_client", return_value=object()),
        patch.object(app, "enabled_role_open_ids", return_value=[]),
        patch("request_withdrawal.send_notice") as send,
    ):
        notices.deliver_pending()
    send.assert_not_called()
    assert "未找到已启用的HR" in stored()[0][5]


def test_sensitive_error_is_redacted_and_markup_cannot_mention_users():
    notices.enqueue(material_request_task(),
                    'app_secret="secret1", access_token=secret2 Authorization: Bearer secret3 <at id=all></at>',
                    QUEUE_STATUS_RETRY)
    event = json.loads(stored()[0][1])
    text = json.dumps(notices.notification_card(event), ensure_ascii=False)
    for token in ["secret1", "secret2", "secret3", "<at id=all>"]:
        assert token not in text


@pytest.mark.parametrize("status", [QUEUE_STATUS_RETRY, QUEUE_STATUS_FAILED, "状态回写失败"])
def test_card_distinguishes_retry_failure_and_unconfirmed_state_without_rejection(status):
    notices.enqueue(material_request_task(), "错误原因", status)
    card = notices.notification_card(json.loads(stored()[0][1]))
    assert card["header"]["template"] == "red"
    assert len(card["body"]["elements"]) == 4
    table = card["body"]["elements"][1]
    assert table["tag"] == "table"
    assert all(column["data_type"] == "text" for column in table["columns"])
    text = str(card)
    assert "申请已驳回" in text  # Explicitly says it does NOT imply rejection.
    assert "不代表申请已驳回" in text
    assert "错误原因" in text
    assert "未写入" not in text  # Partially completed writes must not be denied.
    if status == QUEUE_STATUS_RETRY:
        assert "已安排自动重试" in text
    elif status == "状态回写失败":
        assert "未能确认自动重试排期" in text
    else:
        assert "已有检查点仍保留" in text


@pytest.mark.parametrize("status", [QUEUE_STATUS_RETRY, QUEUE_STATUS_FAILED])
def test_worker_enqueues_error_with_latest_checkpoint_and_does_not_rollback(status):
    task = material_request_task()
    def process(_task, checkpoint):
        checkpoint({"request_no": "REQ-latest", "write_done": True})
        raise RuntimeError("通知超时")
    with (
        patch.object(worker, "process_task", side_effect=process),
        patch.object(worker, "checkpoint_submission_task"),
        patch.object(worker, "fail_submission_task", return_value=status),
        patch.object(notices, "enqueue") as enqueue,
        patch.object(app, "enabled_admin_open_ids") as admins,
        patch.object(app, "execute_corporate_apparel_rejection") as rollback,
    ):
        worker.process_claimed_submission_task(Mock(), task)
    enqueue.assert_called_once_with(task, ANY, status,
                                    progress={"request_no": "REQ-latest", "write_done": True})
    assert str(enqueue.call_args.args[1]) == "通知超时"
    admins.assert_not_called()
    rollback.assert_not_called()


def test_worker_state_write_failure_also_generates_a_local_alert():
    with (
        patch.object(worker, "process_task", side_effect=RuntimeError("业务错误")),
        patch.object(worker, "fail_submission_task", side_effect=RuntimeError("飞书不可用")),
        patch.object(notices, "enqueue") as enqueue,
    ):
        worker.process_claimed_submission_task(Mock(), material_request_task())
    assert enqueue.call_args.args[2] == "状态回写失败"
    assert "飞书不可用" in enqueue.call_args.args[1]


def test_alert_enqueue_failure_does_not_erase_queue_failure_state():
    with (
        patch.object(worker, "process_task", side_effect=RuntimeError("timeout")),
        patch.object(worker, "fail_submission_task", return_value=QUEUE_STATUS_RETRY) as fail,
        patch.object(notices, "enqueue", side_effect=RuntimeError("disk full")),
    ):
        worker.process_claimed_submission_task(Mock(), material_request_task())
    fail.assert_called_once()


def test_success_does_not_generate_anomaly_notice():
    with (
        patch.object(worker, "process_task", return_value={"request_no": "REQ-ok"}),
        patch.object(worker, "complete_submission_task"),
        patch.object(notices, "enqueue") as enqueue,
    ):
        worker.process_claimed_submission_task(Mock(), material_request_task())
    enqueue.assert_not_called()
