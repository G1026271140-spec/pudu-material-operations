"""Checkpointed deletion of pending ordinary requests and withdrawal notices."""
from __future__ import annotations

import json
from typing import Callable
from uuid import NAMESPACE_URL, uuid5


def send_notice(client, recipient: str, card: dict, key: str) -> str:
    """Stable Feishu UUID protects retries after a send/checkpoint interruption."""
    response = client._request(
        "POST", "/im/v1/messages", params={"receive_id_type": "open_id"},
        payload={"receive_id": recipient, "msg_type": "interactive",
                 "content": json.dumps(card, ensure_ascii=False),
                 "uuid": uuid5(NAMESPACE_URL, key).hex},
    )
    message_id = str((response.get("data") or {}).get("message_id") or "")
    if not message_id:
        raise RuntimeError("飞书未返回通知消息 ID。")
    return message_id


def withdrawal_card(request_no: str, requester: str, admins: list[str]) -> dict:
    mentions = " ".join(f"<at id={open_id}></at>" for open_id in admins)
    return {
        "schema": "2.0",
        "header": {"template": "red", "title": {"tag": "plain_text", "content": "申请单已撤回"}},
        "body": {"elements": [{"tag": "markdown", "content": (
            f"{requester or '申请人'} 的申请单 **{request_no}** 被撤回。\n\n"
            f"详情请咨询 {mentions or '已启用的管理员'}。"
        )}]},
    }


def process_withdrawal(task, checkpoint: Callable[[dict], None] | None = None) -> dict:
    import app as legacy
    from pending_inventory_sqlite import delete as remove_pending

    if checkpoint is None:
        raise RuntimeError("撤回删除必须使用持久化检查点。")
    draft = dict(task.payload.get("draft") or {})
    progress = dict(task.result)
    request_id = str(draft.get("request_id") or "")

    def save():
        if checkpoint:
            checkpoint(dict(progress))

    client = legacy.feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法撤回申请。")
    admins = legacy.enabled_admin_open_ids()
    if not progress.get("write_done"):
        if str(draft.get("operator_open_id") or "") not in admins:
            raise PermissionError("只有已启用管理员可以删除申请。")
        if not progress.get("request_snapshot"):
            row = client.get_record(legacy.feishu_table_id(legacy.REQUEST_TABLE_NAME), request_id)
            if not row:
                raise ValueError("申请单不存在，请刷新列表。")
            progress["request_snapshot"] = row
            save()  # Retain recipient identity even when the header has been deleted.
        snapshot = dict(progress["request_snapshot"])
        request_no = legacy.feishu_text(legacy.feishu_fields(snapshot), "申请单号")
        if not request_no:
            raise ValueError("申请单缺少单号，无法定位明细。")
        current = next((row for row in client.search_records(
            legacy.feishu_table_id(legacy.REQUEST_TABLE_NAME), "申请单号", request_no,
        ) if legacy.feishu_record_id(row) == request_id), None)
        if current:
            from pending_inventory_sqlite import is_pending
            if not is_pending(current):
                raise ValueError("该申请已不在待核实状态，请刷新后处理。")
            if int(legacy.feishu_text(legacy.feishu_fields(current), "申请变更次数") or 0) != int(draft.get("expected_version") or 0):
                raise ValueError("申请单已发生修改，请刷新后重新删除。")
            progress["request_snapshot"] = current
            save()
        # Re-read surviving lines on retry. Never re-delete stale IDs after a
        # successful batch whose checkpoint could not be persisted.
        survivors = []
        for row in legacy.fresh_feishu_rows(legacy.REQUEST_LINE_TABLE_NAME):
            fields = legacy.feishu_fields(row)
            links = legacy.feishu_link_ids_any(fields, ["所属申请单", "申请单"])
            if request_id in links or (not links and (
                legacy.feishu_text_any(fields, ["所属申请单", "申请单", "申请单号"]) == request_no
                or legacy.feishu_text(fields, "明细编号").startswith(request_no + "-")
            )):
                survivors.append(legacy.feishu_record_id(row))
        targets = set(progress.get("target_line_ids") or []) | set(survivors)
        progress["target_line_ids"] = sorted(targets)
        save()
        removed = set(progress.get("deleted_line_ids") or [])
        for start in range(0, len(survivors), 500):
            batch = survivors[start:start + 500]
            client.batch_delete_records(legacy.feishu_table_id(legacy.REQUEST_LINE_TABLE_NAME), batch)
            removed.update(batch)
            progress["deleted_line_ids"] = sorted(removed)
            save()
        if current:
            client.delete_record(legacy.feishu_table_id(legacy.REQUEST_TABLE_NAME), request_id)
        progress.update(write_done=True, request_no=request_no, deleted_request_id=request_id,
                        deleted_line_count=len(targets))
        save()
    remove_pending(request_id)
    request = legacy.load_feishu_request_records([dict(progress["request_snapshot"])])[0]
    applicant = str(request.get("requester_open_id") or "")
    targets = list(dict.fromkeys([*admins, *([applicant] if applicant else [])]))
    sent = dict(progress.get("notification_message_ids") or {})
    skipped = set(progress.get("notification_skipped_ids") or [])
    card = withdrawal_card(str(progress["request_no"]), str(request.get("requester") or ""), admins)
    for recipient in targets:
        if recipient in sent or recipient in skipped:
            continue
        try:
            sent[recipient] = send_notice(client, recipient, card, f"withdraw:{request_id}:{recipient}")
        except Exception as exc:
            if recipient != applicant or recipient in admins or '"code":230013' not in str(exc).replace(" ", ""):
                raise
            skipped.add(recipient)
        progress.update(notification_message_ids=sent, notification_skipped_ids=sorted(skipped))
        save()
    progress.update(notification_done=True, notification_count=len(sent), withdrawn=True)
    save()
    return progress
