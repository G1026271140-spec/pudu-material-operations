import json
from contextlib import closing
from types import SimpleNamespace

import app
import submission_receipts as receipts


def test_receipt_is_durable_deduplicated_and_sent_to_applicant(monkeypatch):
    sent = []
    client = SimpleNamespace(_request=lambda *args, **kwargs: sent.append(kwargs["payload"]) or {"data": {"message_id": "om-1"}})
    monkeypatch.setattr(app, "feishu_client", lambda: client)
    receipts.enqueue("submission-1", "ou_applicant", "物料申领", ["task-1"])
    receipts.enqueue("submission-1", "ou_applicant", "物料申领", ["task-1"])
    receipts.deliver_pending()
    receipts.deliver_pending()
    assert len(sent) == 1
    assert sent[0]["receive_id"] == "ou_applicant"
    assert "您的申请已提交" in json.loads(sent[0]["content"])["header"]["title"]["content"]
    assert "task-1" in sent[0]["content"]


def test_receipt_retries_failure_with_same_feishu_uuid(monkeypatch):
    sent = []

    def send(*args, **kwargs):
        sent.append(kwargs["payload"])
        if len(sent) == 1:
            raise RuntimeError("temporary network error")
        return {"data": {"message_id": "om-2"}}

    monkeypatch.setattr(app, "feishu_client", lambda: SimpleNamespace(_request=send))
    receipts.enqueue("submission-2", "ou_applicant", "文化周边申领", ["task-2"])
    receipts.deliver_pending()
    with closing(receipts._connect()) as connection, connection:
        assert connection.execute("SELECT status FROM receipts").fetchone()[0] == "pending"
        connection.execute("UPDATE receipts SET retry_at=0")
    receipts.deliver_pending()
    assert len(sent) == 2
    assert sent[0]["uuid"] == sent[1]["uuid"]


def test_bot_unavailable_skips_receipt(monkeypatch):
    def send(*args, **kwargs):
        raise RuntimeError('Feishu HTTP 400: {"code":230013}')

    monkeypatch.setattr(app, "feishu_client", lambda: SimpleNamespace(_request=send))
    receipts.enqueue("submission-3", "ou_applicant", "企业文化衫领取", ["task-3"])
    receipts.deliver_pending()
    with closing(receipts._connect()) as connection:
        assert connection.execute("SELECT status FROM receipts").fetchone()[0] == "skipped"
