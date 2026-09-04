from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path

import lark_oapi as lark
from lark_oapi import ws
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackToast,
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)


ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as inventory_app
from scripts import inventory_query_bot


INVENTORY_MESSAGE_LOCK = threading.RLock()
INVENTORY_MESSAGE_IDS: set[str] = set()
INVENTORY_MESSAGE_CACHE_LIMIT = 1000


def load_credentials() -> tuple[str, str]:
    with SECRETS_PATH.open("rb") as file:
        secrets = tomllib.load(file)
    app_id = str(secrets.get("FEISHU_APP_ID") or "").strip()
    app_secret = str(secrets.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID or FEISHU_APP_SECRET is not configured.")
    return app_id, app_secret


def reserve_inventory_message(message_id: str) -> bool:
    with INVENTORY_MESSAGE_LOCK:
        if message_id in INVENTORY_MESSAGE_IDS:
            return False
        if len(INVENTORY_MESSAGE_IDS) >= INVENTORY_MESSAGE_CACHE_LIMIT:
            INVENTORY_MESSAGE_IDS.clear()
        INVENTORY_MESSAGE_IDS.add(message_id)
        return True


def inventory_query_error_text(error: Exception) -> str:
    message = str(error)
    if "exceeds" in message.lower() or "5 mb" in message.lower():
        return "截图超过 5 MB，暂时无法识别。请压缩图片后重新发送。"
    if any(
        marker in message
        for marker in (
            "99991672",
            "99991679",
            "optical_char_recognition",
            "im:message:readonly",
        )
    ):
        return "机器人暂时缺少截图识别或消息读取权限，请联系应用管理员检查权限配置。"
    return "库存查询暂时失败，请稍后重新发送查询内容。"


def process_inventory_message(
    message_id: str,
    image_keys: list[str],
    text_segments: list[str] | None = None,
) -> None:
    client = inventory_app.feishu_client()
    if client is None:
        logging.error("Inventory query failed: Feishu client is not configured")
        return
    try:
        recognized_text = [
            str(segment).strip()
            for segment in list(text_segments or [])
            if str(segment).strip()
        ]
        for image_key in image_keys[:3]:
            image = client.download_message_resource(message_id, image_key)
            recognized_text.extend(client.recognize_image_text(image))

        material_rows = inventory_app.fresh_feishu_rows(inventory_app.MATERIAL_TABLE_NAME)
        category_rows = inventory_app.fresh_feishu_rows(inventory_app.CATEGORY_TABLE_NAME)
        inventory_records = inventory_app.feishu_inventory_records_from_rows(
            material_rows,
            category_rows,
            active_only=False,
        )
        category_names = [
            inventory_app.feishu_text(inventory_app.feishu_fields(row), "物料品类")
            for row in category_rows
        ]
        queries = inventory_query_bot.parse_inventory_queries(
            recognized_text,
            inventory_records,
            category_names=category_names,
            require_quantity=bool(image_keys),
            allow_fuzzy=not image_keys,
        )
        if not queries:
            if not image_keys and not any(
                inventory_query_bot.has_inventory_query_intent(segment)
                for segment in recognized_text
            ):
                return
            requirement = "品类、产品型号、语种和需求数量" if image_keys else "品类、产品型号和语种"
            client.reply_text_message(
                message_id,
                f"没有识别出完整物料信息。请确保每项都包含{requirement}。",
                idempotency_key=f"inventory-parse-error:{message_id}",
            )
            return
        queries = inventory_query_bot.expand_fuzzy_inventory_queries(
            queries,
            inventory_records,
        )
        if (
            not image_keys
            and not any(query.category for query in queries)
            and not any(
                inventory_query_bot.has_inventory_query_intent(segment)
                for segment in recognized_text
            )
        ):
            return
        results = inventory_query_bot.match_inventory_queries(queries, inventory_records)
        client.reply_interactive_message(
            message_id,
            inventory_query_bot.inventory_result_card(results),
            idempotency_key=f"inventory-result:{message_id}",
        )
        logging.info(
            "Inventory query processed: message_id=%s images=%s items=%s",
            message_id,
            len(image_keys),
            len(results),
        )
    except Exception as exc:
        logging.exception("Inventory query processing failed: %s", message_id)
        try:
            client.reply_text_message(
                message_id,
                inventory_query_error_text(exc),
                idempotency_key=f"inventory-error:{message_id}",
            )
        except Exception:
            logging.exception("Sending inventory query error failed: %s", message_id)


def handle_inventory_message(data: P2ImMessageReceiveV1) -> None:
    event = data.event
    message = event.message if event else None
    sender = event.sender if event else None
    if message is None or (sender is not None and str(sender.sender_type or "") == "bot"):
        return
    message_id = str(message.message_id or "").strip()
    message_type = str(message.message_type or "").strip()
    chat_type = str(message.chat_type or "").strip()
    if not message_id or message_type not in {"image", "post", "text"}:
        return
    if chat_type == "group" and not list(message.mentions or []):
        return
    image_keys = inventory_query_bot.extract_image_keys(message.content)
    message_text = inventory_query_bot.extract_message_text(message.content)
    text_segments = [message_text] if message_text else []
    if (
        not image_keys
        and text_segments
        and not inventory_query_bot.has_inventory_query_intent(message_text)
    ):
        return
    if (not image_keys and not text_segments) or not reserve_inventory_message(message_id):
        return
    threading.Thread(
        target=process_inventory_message,
        args=(message_id, image_keys, text_segments),
        name=f"inventory-query-{message_id[-8:]}",
        daemon=True,
    ).start()


def card_action_response(kind: str, content: str) -> P2CardActionTriggerResponse:
    response = P2CardActionTriggerResponse()
    response.toast = CallBackToast({"type": kind, "content": content})
    return response


def process_card_action_async(
    *,
    action_key: str,
    action_name: str,
    value: dict[str, object],
    form_value: dict[str, object],
    operator_open_id: str,
    message_id: str,
) -> None:
    request_id = str(value.get("request_id") or "").strip()
    if not request_id and action_name.startswith("save_inventory_edit__"):
        parts = action_name.split("__")
        request_id = parts[1] if len(parts) == 3 else ""
    if not request_id and action_name.startswith("save_inventory_reminder__"):
        parts = action_name.split("__")
        request_id = parts[1] if len(parts) == 2 else ""
    try:
        if operator_open_id not in inventory_app.enabled_admin_open_ids():
            raise PermissionError("只有已启用管理员可以处理库存确认。")
        if action_key == "edit_request_inventory":
            if not message_id:
                raise RuntimeError("飞书未返回卡片消息标识，请在最新卡片中重试。")
            card = inventory_app.request_inventory_card_edit_form(request_id)
            client = inventory_app.feishu_client()
            if client is None:
                raise RuntimeError("飞书未配置，无法更新库存编辑卡片。")
            client.update_interactive_message(message_id, card)
            return
        if action_name.startswith("save_inventory_edit__"):
            parts = action_name.split("__")
            if len(parts) != 3:
                raise RuntimeError("编辑表单标识无效，请打开最新卡片重试。")
            request_id = parts[1]
            version = int(parts[2] or 0)
            draft = inventory_app.request_inventory_card_edit_draft(
                request_id,
                version,
                operator_open_id,
                form_value,
            )
            inventory_app.enqueue_feishu_background_write(
                inventory_app.QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT,
                {"draft": draft},
                idempotency_key=(
                    f"request-inventory-card-edit:{request_id}:{version}:"
                    f"{hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()}"
                ),
            )
            return
        if action_name.startswith("save_inventory_reminder__"):
            schedule_value = str(form_value.get("reminder_schedule") or "").strip()
            inventory_app.execute_inventory_review_reminder_schedule(
                request_id,
                operator_open_id,
                schedule_value,
            )
            context = inventory_app.request_inventory_review_context(request_id=request_id)
            request = dict(context["request"])
            client = inventory_app.feishu_client()
            if client is None:
                raise RuntimeError("飞书未配置，无法更新库存提醒卡片。")
            card = inventory_app.material_request_notification_card(
                str(request.get("request_no") or ""),
                request,
                list(context.get("lines") or []),
                review_context=context,
                operator_open_id=operator_open_id,
            )
            client.update_interactive_message(message_id, card)
            return
        if action_key == "confirm_request_inventory":
            version = int(value.get("version") or 0)
            inventory_app.execute_request_inventory_confirm(
                {
                    "request_id": request_id,
                    "expected_version": version,
                    "operator_open_id": operator_open_id,
                }
            )
            return
        if action_key == "reject_request_inventory":
            result = inventory_app.execute_request_inventory_reject(
                {
                    "request_id": request_id,
                    "expected_version": int(value.get("version") or 0),
                    "operator_open_id": operator_open_id,
                }
            )
            client = inventory_app.feishu_client()
            if client is not None and message_id:
                client.update_interactive_message(
                    message_id,
                    inventory_app.material_request_rejection_card(
                        str(result.get("request_no") or value.get("request_no") or "")
                    ),
                )
            return
        raise RuntimeError("暂不支持该卡片操作。")
    except Exception as exc:
        logging.exception(
            "Asynchronous card action failed: action=%s name=%s message=%s",
            action_key,
            action_name,
            message_id,
        )
        if message_id and request_id:
            try:
                client = inventory_app.feishu_client()
                if client is not None:
                    if not action_name.startswith("save_inventory_reminder__"):
                        error_card = inventory_app.request_inventory_card_edit_form(
                            request_id,
                            error_message=str(exc),
                        )
                        client.update_interactive_message(message_id, error_card)
            except Exception:
                logging.exception("Updating card with asynchronous action error failed")


def handle_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    event = data.event
    action = event.action if event else None
    value = dict(action.value or {}) if action and isinstance(action.value, dict) else {}
    operator = event.operator if event else None
    operator_open_id = str(operator.open_id or "").strip() if operator else ""
    action_name = str(getattr(action, "name", "") or "") if action else ""
    action_key = str(value.get("action") or "")
    if action_key not in {
        "edit_request_inventory",
        "confirm_request_inventory",
        "reject_request_inventory",
    } and not action_name.startswith(("save_inventory_edit__", "save_inventory_reminder__")):
        return card_action_response("warning", "暂不支持该卡片操作。")
    context = getattr(event, "context", None) if event else None
    message_id = str(getattr(context, "open_message_id", "") or "")
    threading.Thread(
        target=process_card_action_async,
        kwargs={
            "action_key": action_key,
            "action_name": action_name,
            "value": value,
            "form_value": dict(getattr(action, "form_value", {}) or {}),
            "operator_open_id": operator_open_id,
            "message_id": message_id,
        },
        name=f"card-action-{(message_id or 'unknown')[-8:]}",
        daemon=True,
    ).start()
    return card_action_response("success", "正在处理，请稍候，卡片将自动更新。")


def main() -> int:
    configured_log_directory = os.environ.get("PUDU_FEISHU_CARD_WORKER_LOG_DIR")
    log_directory = (
        Path(configured_log_directory)
        if configured_log_directory
        else Path(os.environ.get("LOCALAPPDATA") or ROOT / "work") / "PuduFeishuCardWorker" / "logs"
    )
    log_directory.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_directory / "worker.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[file_handler],
    )
    app_id, app_secret = load_credentials()
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_inventory_message)
        .register_p2_card_action_trigger(handle_card_action)
        .build()
    )
    logging.info("Starting Feishu inventory query worker.")
    ws.Client(
        app_id,
        app_secret,
        log_level=lark.LogLevel.WARNING,
        event_handler=handler,
    ).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
