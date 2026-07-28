from __future__ import annotations

import logging
import sys
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


ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as inventory_app


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
    live_data = inventory_app.fetch_request_maintenance_live_data()
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
                f"Edit request **{request_no}** below. All quantities must be positive integers."
                if english
                else f"请在下方修改申请单 **{request_no}**。所有数量必须为正整数。"
            ),
        }
    ]
    form_elements: list[dict[str, Any]] = [
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
        input_element(
            "recipient_info",
            "Recipient information" if english else "收件人信息",
            request.get("recipient_info"),
            required=True,
        ),
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
            input_element(
                f"qty_{index}",
                f"{label} - Quantity" if english else f"{label} - 数量",
                int(line.get("quantity") or 0),
                required=True,
            )
        )
        form_elements.append(
            input_element(
                f"remark_{index}",
                f"{label} - Remark" if english else f"{label} - 备注",
                line.get("remark"),
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
            with inventory_app.DATA_LOCK:
                inventory_app.update_pending_feishu_request(
                    request,
                    request_updates,
                    edited_lines,
                )
            return response(
                toast_type="success",
                zh="申请修改已保存。",
                en="The request changes have been saved.",
                card=result_card(request_no, english=english, withdrawn=False),
            )
        if action_name == "withdraw_request":
            return response(
                toast_type="warning",
                zh="请再次确认是否撤回申请。",
                en="Please confirm the request withdrawal.",
                card=confirm_withdraw_card(request_no, english=english),
            )
        if action_name == "confirm_withdraw":
            with inventory_app.DATA_LOCK:
                inventory_app.withdraw_pending_feishu_request(
                    request,
                    "申请人通过机器人卡片撤回",
                )
            return response(
                toast_type="success",
                zh="申请已撤回。",
                en="The request has been withdrawn.",
                card=result_card(request_no, english=english, withdrawn=True),
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


def main() -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    app_id, app_secret = load_credentials()
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(handle_card_action)
        .build()
    )
    logging.info("Starting Feishu card callback worker.")
    ws.Client(
        app_id,
        app_secret,
        log_level=lark.LogLevel.WARNING,
        event_handler=handler,
    ).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
