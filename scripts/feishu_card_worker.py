from __future__ import annotations

import logging
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

import lark_oapi as lark
from lark_oapi import ws
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackCard,
    CallBackToast,
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1


ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as inventory_app
from scripts import inventory_query_bot


REQUEST_CACHE_LOCK = threading.RLock()
REQUEST_CACHE: dict[str, Any] = {"requests": [], "lines": []}
REQUEST_CACHE_READY = threading.Event()
REQUEST_CACHE_REFRESH_SECONDS = 15
BACKGROUND_ACTION_LOCK = threading.RLock()
BACKGROUND_ACTIONS: set[str] = set()
INVENTORY_MESSAGE_LOCK = threading.RLock()
INVENTORY_MESSAGE_IDS: set[str] = set()
INVENTORY_MESSAGE_CACHE_LIMIT = 1000


def refresh_request_cache() -> None:
    started_at = time.perf_counter()
    live_data = inventory_app.fetch_request_maintenance_live_data()
    refreshed = {
        "requests": [
            dict(item)
            for item in list(live_data.get("requests") or [])
            if isinstance(item, dict)
        ],
        "lines": [
            dict(item)
            for item in list(live_data.get("lines") or [])
            if isinstance(item, dict)
        ],
    }
    with REQUEST_CACHE_LOCK:
        REQUEST_CACHE.clear()
        REQUEST_CACHE.update(refreshed)
        REQUEST_CACHE_READY.set()
    logging.info(
        "Request cache refreshed: requests=%s lines=%s seconds=%.2f",
        len(refreshed["requests"]),
        len(refreshed["lines"]),
        time.perf_counter() - started_at,
    )


def request_cache_refresh_loop() -> None:
    while True:
        time.sleep(REQUEST_CACHE_REFRESH_SECONDS)
        try:
            refresh_request_cache()
        except Exception:
            logging.exception("Request cache refresh failed")


def cached_request_data() -> dict[str, list[dict[str, Any]]]:
    if not REQUEST_CACHE_READY.is_set():
        raise RuntimeError("Request data is still loading. Please try again shortly.")
    with REQUEST_CACHE_LOCK:
        return {
            "requests": [dict(item) for item in REQUEST_CACHE["requests"]],
            "lines": [dict(item) for item in REQUEST_CACHE["lines"]],
        }


def processing_card(
    request_no: str,
    *,
    english: bool,
    withdrawing: bool,
) -> dict[str, Any]:
    if withdrawing:
        title = "Withdrawing request" if english else "正在撤回申请"
        content = (
            f"Material request **{request_no}** is being withdrawn. The bot will notify you when it finishes."
            if english
            else f"正在撤回申请单 **{request_no}**。完成后机器人会发送通知，请勿重复操作。"
        )
    else:
        title = "Saving changes" if english else "正在保存修改"
        content = (
            f"Changes to material request **{request_no}** are being saved. The bot will notify you when it finishes."
            if english
            else f"正在保存申请单 **{request_no}** 的修改。完成后机器人会发送通知，请勿重复提交。"
        )
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": plain_text(title),
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": content},
            ]
        },
    }


def send_operator_result(
    operator_open_id: str,
    *,
    english: bool,
    success_zh: str,
    success_en: str,
    error: Exception | None = None,
) -> None:
    client = inventory_app.feishu_client()
    if client is None:
        raise RuntimeError("Feishu message client is not configured.")
    if error is None:
        text = success_en if english else success_zh
    else:
        text = (
            f"Operation failed: {error}"
            if english
            else f"操作失败：{error}"
        )
    client.send_text_message(operator_open_id, text)


def update_cached_request_after_save(
    request_no: str,
    form: dict[str, Any],
    edited_lines: list[dict[str, Any]],
) -> None:
    line_updates = {
        str(item.get("record_id") or ""): item
        for item in edited_lines
    }
    with REQUEST_CACHE_LOCK:
        for request in REQUEST_CACHE["requests"]:
            if str(request.get("request_no") or "") != request_no:
                continue
            request.update(
                {
                    "customer_name": str(form.get("customer_name") or "").strip(),
                    "country": str(form.get("country") or "").strip(),
                    "recipient_info": str(form.get("recipient_info") or "").strip(),
                    "freight_payer": str(form.get("freight_payer") or "").strip(),
                    "material_usage": str(form.get("material_usage") or "").strip(),
                }
            )
        for line in REQUEST_CACHE["lines"]:
            update = line_updates.get(str(line.get("record_id") or ""))
            if update is None:
                continue
            if bool(update.get("delete")) or int(update.get("quantity") or 0) == 0:
                line["status"] = inventory_app.REQUEST_LINE_STATUS_WITHDRAWN
                continue
            line["quantity"] = int(update["quantity"])
            line["remark"] = str(update.get("remark") or "")


def update_cached_request_after_withdraw(request_no: str) -> None:
    with REQUEST_CACHE_LOCK:
        for request in REQUEST_CACHE["requests"]:
            if str(request.get("request_no") or "") == request_no:
                request["status"] = inventory_app.REQUEST_STATUS_WITHDRAWN
        for line in REQUEST_CACHE["lines"]:
            if str(line.get("request_no") or "") == request_no:
                line["status"] = inventory_app.REQUEST_LINE_STATUS_WITHDRAWN


def run_background_action(
    action_key: str,
    operation: Any,
) -> bool:
    with BACKGROUND_ACTION_LOCK:
        if action_key in BACKGROUND_ACTIONS:
            return False
        BACKGROUND_ACTIONS.add(action_key)

    def runner() -> None:
        try:
            operation()
        except Exception:
            logging.exception("Background card action failed: %s", action_key)
        finally:
            with BACKGROUND_ACTION_LOCK:
                BACKGROUND_ACTIONS.discard(action_key)

    threading.Thread(
        target=runner,
        name=f"card-action-{action_key}",
        daemon=True,
    ).start()
    return True


def save_request_in_background(
    request: dict[str, Any],
    request_no: str,
    request_updates: dict[str, Any],
    form: dict[str, Any],
    edited_lines: list[dict[str, Any]],
    operator_open_id: str,
    english: bool,
) -> None:
    error: Exception | None = None
    try:
        with inventory_app.DATA_LOCK:
            inventory_app.update_pending_feishu_request(
                request,
                request_updates,
                edited_lines,
            )
        update_cached_request_after_save(request_no, form, edited_lines)
    except Exception as exc:
        error = exc
        logging.exception("Saving request failed: %s", request_no)
    try:
        send_operator_result(
            operator_open_id,
            english=english,
            success_zh=f"申请单 {request_no} 的修改已保存。",
            success_en=f"Changes to material request {request_no} have been saved.",
            error=error,
        )
    except Exception:
        logging.exception("Sending save result failed: %s", request_no)


def withdraw_request_in_background(
    request: dict[str, Any],
    request_no: str,
    operator_open_id: str,
    english: bool,
) -> None:
    error: Exception | None = None
    try:
        with inventory_app.DATA_LOCK:
            inventory_app.withdraw_pending_feishu_request(
                request,
                "申请人通过机器人卡片撤回",
            )
        update_cached_request_after_withdraw(request_no)
    except Exception as exc:
        error = exc
        logging.exception("Withdrawing request failed: %s", request_no)
    try:
        send_operator_result(
            operator_open_id,
            english=english,
            success_zh=f"申请单 {request_no} 已撤回。",
            success_en=f"Material request {request_no} has been withdrawn.",
            error=error,
        )
    except Exception:
        logging.exception("Sending withdrawal result failed: %s", request_no)


def load_credentials() -> tuple[str, str]:
    with SECRETS_PATH.open("rb") as file:
        secrets = tomllib.load(file)
    app_id = str(secrets.get("FEISHU_APP_ID") or "").strip()
    app_secret = str(secrets.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID or FEISHU_APP_SECRET is not configured.")
    return app_id, app_secret


def plain_text(content: object) -> dict[str, str]:
    return {"tag": "plain_text", "content": str(content or "")}


def input_element(
    name: str,
    label: str,
    value: object,
    *,
    required: bool = False,
) -> dict[str, Any]:
    return {
        "tag": "input",
        "name": name,
        "required": required,
        "label": plain_text(label),
        "placeholder": plain_text(label),
        "default_value": str(value or ""),
        "width": "fill",
    }


def input_columns(
    *elements: dict[str, Any],
    weights: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    column_weights = weights or tuple(1 for _ in elements)
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "12px",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": column_weights[index],
                "elements": [element],
            }
            for index, element in enumerate(elements)
        ],
    }


def response(
    *,
    toast_type: str,
    zh: str,
    en: str,
    card: dict[str, Any] | None = None,
) -> P2CardActionTriggerResponse:
    response = P2CardActionTriggerResponse()
    response.toast = CallBackToast(
        {
            "type": toast_type,
            "content": zh,
            "i18n": {"zh_cn": zh, "en_us": en},
        }
    )
    if card is not None:
        response.card = CallBackCard({"type": "raw", "data": card})
    return response


def request_context(
    request_no: str,
    operator_open_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    live_data = cached_request_data()
    request = next(
        (
            item
            for item in list(live_data.get("requests") or [])
            if str(item.get("request_no") or "") == request_no
        ),
        None,
    )
    if request is None:
        raise RuntimeError("The material request no longer exists.")
    requester_open_id = str(request.get("requester_open_id") or "").strip()
    if not operator_open_id or requester_open_id != operator_open_id:
        raise PermissionError("Only the original applicant can modify or withdraw this request.")
    if str(request.get("status") or "") != inventory_app.REQUEST_STATUS_PENDING:
        raise RuntimeError("Only pending requests can be modified or withdrawn.")
    lines = inventory_app.request_lines_for_request(
        request,
        list(live_data.get("lines") or []),
    )
    lines = [
        line
        for line in lines
        if str(line.get("status") or "") != inventory_app.REQUEST_LINE_STATUS_WITHDRAWN
    ]
    return request, lines


def editor_card(
    request: dict[str, Any],
    lines: list[dict[str, Any]],
    *,
    english: bool,
) -> dict[str, Any]:
    request_no = str(request.get("request_no") or "")
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": (
                f"Edit request **{request_no}** below. Enter 0 to remove a material line; at least one line must remain."
                if english
                else f"请在下方修改申请单 **{request_no}**。数量填 0 可删除该物料，申请单至少保留一条明细。"
            ),
        }
    ]
    form_elements: list[dict[str, Any]] = [
        input_columns(
            input_element(
                "customer_name",
                "Customer name" if english else "客户名称",
                request.get("customer_name"),
            ),
            input_element(
                "country",
                "Country" if english else "国家",
                request.get("country"),
            ),
        ),
        input_element(
            "recipient_info",
            "Recipient information" if english else "收件人信息",
            request.get("recipient_info"),
            required=True,
        ),
        input_columns(
            input_element(
                "freight_payer",
                "Freight payer" if english else "运费承担者",
                request.get("freight_payer"),
            ),
            input_element(
                "material_usage",
                "Purpose" if english else "物料用途",
                request.get("material_usage"),
                required=True,
            ),
            weights=(1, 2),
        ),
    ]
    line_ids: list[str] = []
    for index, line in enumerate(lines):
        line_id = str(line.get("record_id") or "")
        line_ids.append(line_id)
        product = (
            inventory_app.english_material_notification_label(line.get("product"))
            if english
            else inventory_app.request_category_display_label(line.get("product"))
        )
        model = (
            inventory_app.english_material_notification_label(
                line.get("model") or inventory_app.NO_MODEL_TEXT
            )
            if english
            else str(line.get("model") or inventory_app.NO_MODEL_TEXT)
        )
        language = (
            inventory_app.english_material_notification_label(
                line.get("language") or inventory_app.NO_LANGUAGE_TEXT
            )
            if english
            else str(line.get("language") or inventory_app.NO_LANGUAGE_TEXT)
        )
        label = f"{index + 1}. {product} / {model} / {language}"
        form_elements.append(
            {"tag": "markdown", "content": f"**{label}**"}
        )
        form_elements.append(
            input_columns(
                input_element(
                    f"qty_{index}",
                    "Quantity (0 = remove)" if english else "数量（填 0 删除）",
                    int(line.get("quantity") or 0),
                    required=True,
                ),
                input_element(
                    f"remark_{index}",
                    "Remark (optional)" if english else "备注（可选）",
                    line.get("remark"),
                ),
                weights=(1, 2),
            )
        )
    form_elements.append(
        {
            "tag": "column_set",
            "flex_mode": "none",
            "horizontal_spacing": "8px",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "button",
                            "name": "save_request",
                            "text": plain_text("Save changes" if english else "保存修改"),
                            "type": "primary",
                            "action_type": "form_submit",
                            "value": {
                                "action": "save_request",
                                "request_no": request_no,
                                "language": "en" if english else "zh",
                                "line_ids": line_ids,
                            },
                        }
                    ],
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "button",
                            "name": "withdraw_request",
                            "text": plain_text(
                                "Withdraw request" if english else "撤回申请"
                            ),
                            "type": "danger",
                            "action_type": "form_submit",
                            "value": {
                                "action": "withdraw_request",
                                "request_no": request_no,
                                "language": "en" if english else "zh",
                            },
                        }
                    ],
                },
            ],
        }
    )
    elements.append({"tag": "form", "name": "request_editor", "elements": form_elements})
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": plain_text(
                "Modify material request" if english else "修改物料申请"
            ),
        },
        "body": {"elements": elements},
    }


def result_card(
    request_no: str,
    *,
    english: bool,
    withdrawn: bool,
) -> dict[str, Any]:
    if withdrawn:
        title = "Request withdrawn" if english else "申请已撤回"
        content = (
            f"Material request **{request_no}** has been withdrawn and will not enter approval."
            if english
            else f"申请单 **{request_no}** 已撤回，不会再进入审批流程。"
        )
        template = "grey"
    else:
        title = "Changes saved" if english else "修改已保存"
        content = (
            f"Changes to material request **{request_no}** have been saved."
            if english
            else f"申请单 **{request_no}** 的修改已保存。"
        )
        template = "green"
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {"template": template, "title": plain_text(title)},
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }


def confirm_withdraw_card(
    request_no: str,
    *,
    english: bool,
) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red",
            "title": plain_text(
                "Confirm request withdrawal" if english else "确认撤回申请"
            ),
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"Withdraw material request **{request_no}**? It will no longer enter approval."
                        if english
                        else f"确认撤回申请单 **{request_no}**？撤回后不会再进入审批流程。"
                    ),
                },
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "horizontal_spacing": "8px",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": plain_text(
                                        "Confirm withdrawal" if english else "确认撤回"
                                    ),
                                    "type": "danger",
                                    "value": {
                                        "action": "confirm_withdraw",
                                        "request_no": request_no,
                                        "language": "en" if english else "zh",
                                    },
                                }
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": plain_text("Cancel" if english else "取消"),
                                    "type": "default",
                                    "value": {
                                        "action": "open_request_editor",
                                        "request_no": request_no,
                                        "language": "en" if english else "zh",
                                    },
                                }
                            ],
                        },
                    ],
                },
            ]
        },
    }


def handle_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    event = data.event
    action = event.action if event else None
    value = dict(action.value or {}) if action else {}
    action_name = str(value.get("action") or "")
    request_no = str(value.get("request_no") or "").strip()
    operator = event.operator if event else None
    operator_open_id = str(operator.open_id or "") if operator else ""
    english = str(value.get("language") or "") == "en"
    logging.info(
        "Card action received: action=%s request_no=%s operator=%s",
        action_name,
        request_no,
        operator_open_id,
    )
    try:
        request, lines = request_context(request_no, operator_open_id)
        if action_name == "open_request_editor":
            return response(
                toast_type="info",
                zh="已打开申请修改表单。",
                en="The request editor is open.",
                card=editor_card(request, lines, english=english),
            )
        if action_name == "save_request":
            form = dict(action.form_value or {})
            line_ids = [str(item) for item in list(value.get("line_ids") or [])]
            edited_lines: list[dict[str, Any]] = []
            for index, line_id in enumerate(line_ids):
                quantity = int(str(form.get(f"qty_{index}") or "0").strip())
                edited_lines.append(
                    {
                        "record_id": line_id,
                        "quantity": quantity,
                        "remark": str(form.get(f"remark_{index}") or "").strip(),
                        "delete": quantity == 0,
                    }
                )
            request_updates = {
                "客户名称": str(form.get("customer_name") or "").strip(),
                "国家": str(form.get("country") or "").strip(),
                "收件人信息": str(form.get("recipient_info") or "").strip(),
                "运费的承担者": str(form.get("freight_payer") or "").strip(),
                "运费承担者": str(form.get("freight_payer") or "").strip(),
                "用途/活动": str(form.get("material_usage") or "").strip(),
                "用途／活动": str(form.get("material_usage") or "").strip(),
                "物料用途": str(form.get("material_usage") or "").strip(),
            }
            started = run_background_action(
                f"save:{request_no}",
                lambda: save_request_in_background(
                    request,
                    request_no,
                    request_updates,
                    form,
                    edited_lines,
                    operator_open_id,
                    english,
                ),
            )
            if not started:
                return response(
                    toast_type="warning",
                    zh="该申请正在保存，请勿重复提交。",
                    en="This request is already being saved.",
                    card=processing_card(
                        request_no,
                        english=english,
                        withdrawing=False,
                    ),
                )
            return response(
                toast_type="info",
                zh="修改已提交，正在后台保存。",
                en="The changes were submitted and are being saved.",
                card=processing_card(
                    request_no,
                    english=english,
                    withdrawing=False,
                ),
            )
        if action_name == "withdraw_request":
            return response(
                toast_type="warning",
                zh="请再次确认是否撤回申请。",
                en="Please confirm the request withdrawal.",
                card=confirm_withdraw_card(request_no, english=english),
            )
        if action_name == "confirm_withdraw":
            started = run_background_action(
                f"withdraw:{request_no}",
                lambda: withdraw_request_in_background(
                    request,
                    request_no,
                    operator_open_id,
                    english,
                ),
            )
            if not started:
                return response(
                    toast_type="warning",
                    zh="该申请正在撤回，请勿重复操作。",
                    en="This request is already being withdrawn.",
                    card=processing_card(
                        request_no,
                        english=english,
                        withdrawing=True,
                    ),
                )
            return response(
                toast_type="info",
                zh="撤回请求已提交，正在后台处理。",
                en="The withdrawal was submitted and is being processed.",
                card=processing_card(
                    request_no,
                    english=english,
                    withdrawing=True,
                ),
            )
        raise RuntimeError("Unknown card action.")
    except PermissionError as exc:
        logging.warning("Unauthorized card action: %s", exc)
        return response(
            toast_type="error",
            zh="只有原申请人可以修改或撤回该申请。",
            en="Only the original applicant can modify or withdraw this request.",
        )
    except Exception as exc:
        logging.exception("Card action failed")
        return response(
            toast_type="error",
            zh=f"操作失败：{exc}",
            en=f"Operation failed: {exc}",
        )


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
    return "库存查询暂时失败，请稍后重新发送截图。"


def process_inventory_message(message_id: str, image_keys: list[str]) -> None:
    client = inventory_app.feishu_client()
    if client is None:
        logging.error("Inventory query failed: Feishu client is not configured")
        return
    try:
        recognized_text: list[str] = []
        for image_key in image_keys[:3]:
            image = client.download_message_resource(message_id, image_key)
            recognized_text.extend(client.recognize_image_text(image))

        material_rows = inventory_app.fresh_feishu_rows(inventory_app.MATERIAL_TABLE_NAME)
        category_rows = inventory_app.fresh_feishu_rows(inventory_app.CATEGORY_TABLE_NAME)
        inventory_records = inventory_app.feishu_inventory_records_from_rows(
            material_rows,
            category_rows,
            active_only=True,
        )
        category_names = [
            inventory_app.feishu_text(inventory_app.feishu_fields(row), "物料品类")
            for row in category_rows
            if inventory_app.normalize_enabled_status(
                inventory_app.feishu_text(inventory_app.feishu_fields(row), "启用状态")
            )
            == inventory_app.STATUS_ACTIVE
        ]
        queries = inventory_query_bot.parse_inventory_queries(
            recognized_text,
            inventory_records,
            category_names=category_names,
        )
        if not queries:
            client.reply_text_message(
                message_id,
                "没有从截图中识别出完整物料信息。请确保每项都包含品类、产品型号、语种和需求数量。",
                idempotency_key=f"inventory-parse-error:{message_id}",
            )
            return
        results = inventory_query_bot.match_inventory_queries(queries, inventory_records)
        client.reply_interactive_message(
            message_id,
            inventory_query_bot.inventory_result_card(results),
            idempotency_key=f"inventory-result:{message_id}",
        )
        logging.info(
            "Inventory screenshot processed: message_id=%s images=%s items=%s",
            message_id,
            len(image_keys),
            len(results),
        )
    except Exception as exc:
        logging.exception("Inventory screenshot processing failed: %s", message_id)
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
    if not message_id or message_type not in {"image", "post"}:
        return
    if chat_type == "group" and not list(message.mentions or []):
        return
    image_keys = inventory_query_bot.extract_image_keys(message.content)
    if not image_keys or not reserve_inventory_message(message_id):
        return
    threading.Thread(
        target=process_inventory_message,
        args=(message_id, image_keys),
        name=f"inventory-query-{message_id[-8:]}",
        daemon=True,
    ).start()


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    app_id, app_secret = load_credentials()
    try:
        refresh_request_cache()
    except Exception:
        logging.exception("Initial request cache refresh failed")
    threading.Thread(
        target=request_cache_refresh_loop,
        name="request-cache-refresh",
        daemon=True,
    ).start()
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(handle_card_action)
        .register_p2_im_message_receive_v1(handle_inventory_message)
        .build()
    )
    logging.info("Starting Feishu bot worker.")
    ws.Client(
        app_id,
        app_secret,
        log_level=lark.LogLevel.WARNING,
        event_handler=handler,
    ).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
