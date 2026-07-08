from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
from feishu_bitable import FeishuBitableClient, FeishuBitableConfig, FeishuBitableError
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo


DEFAULT_PASSWORD = "376493"
NO_MODEL_TEXT = "无需型号"
ACTION_RECEIVE = "物料领取（减少库存）"
ACTION_PURCHASE = "物料采购（增加库存）"
ACTION_OPTIONS = [ACTION_RECEIVE, ACTION_PURCHASE]
DECREASE_ACTIONS = {ACTION_RECEIVE, "出库减少"}
INCREASE_ACTIONS = {ACTION_PURCHASE, "入库增加"}
REQUEST_TABLE_NAME = "物料申请单"
REQUEST_LINE_TABLE_NAME = "申请明细"
REQUEST_NO_PREFIX = "REQ"
REQUEST_FORM_TITLE = "MKT营销物料领取流程(MKT Marketing Materials Collecting Process)"
REQUEST_STATUS_PENDING = "待审批"
REQUEST_STATUS_PARTIAL = "部分发放"
REQUEST_STATUS_ISSUED = "已发放"
REQUEST_LINE_STATUS_PENDING = "待审批"
REQUEST_LINE_STATUS_PARTIAL = "部分发放"
REQUEST_LINE_STATUS_ISSUED = "已发放"
FREIGHT_PAYER_OPTIONS = ["", "申请部门承担", "市场部承担", "客户承担", "其他"]

PRODUCT_COL = "物料品类(Material Category)"
MODEL_COL = "产品型号(Product Model)"
LANGUAGE_COL = "语种(Language)"
QTY_COL = "现存物料数量(Material Quantity)"
PRICE_COL = "单价"
VALUE_COL = "现存物料总价值"
UPDATED_COL = "最后更新时间"

INVENTORY_HEADERS = [
    "物料编码",
    PRODUCT_COL,
    MODEL_COL,
    LANGUAGE_COL,
    QTY_COL,
    PRICE_COL,
    VALUE_COL,
    UPDATED_COL,
]

TRANSACTION_HEADERS = [
    "时间",
    "操作",
    PRODUCT_COL,
    MODEL_COL,
    LANGUAGE_COL,
    "数量",
    "变更前数量",
    "变更后数量",
    "备注",
]

DATA_LOCK = threading.Lock()
DATA_CACHE_TTL_SECONDS = 30
REQUEST_FORM_STATIC_CACHE_PATH = Path(__file__).resolve().parent / "data" / "request_form_cache.json"
REQUEST_FORM_CACHE_LOCK = threading.Lock()
REQUEST_FORM_CACHE_STATE: dict[str, object] = {
    "data": None,
    "refreshing": False,
    "error": "",
    "updated_at": "",
}


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --pudu-ink: #0B1220;
            --pudu-muted: #5B667A;
            --pudu-line: #D8E0EA;
            --pudu-panel: #FFFFFF;
            --pudu-cyan: #00A7B5;
            --pudu-blue: #2563EB;
        }
        .stApp {
            background:
                radial-gradient(circle at 8% 0%, rgba(0, 167, 181, 0.10), transparent 30%),
                linear-gradient(180deg, #F6F9FC 0%, #EEF3F8 100%);
            color: var(--pudu-ink);
        }
        h1, h2, h3 {
            color: var(--pudu-ink);
            font-weight: 760;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0B1220 0%, #121B2D 100%);
        }
        [data-testid="stSidebar"] * {
            color: #EAF2FF;
        }
        [data-testid="stSidebar"] .stCaption {
            color: #AEBBD0;
        }
        div[data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.86);
            border: 1px solid rgba(118, 138, 160, 0.24);
            border-radius: 10px;
            padding: 14px 16px;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.07);
        }
        .stButton > button,
        .stDownloadButton > button,
        div[data-testid="stFormSubmitButton"] button {
            border: 0;
            border-radius: 9px;
            background: linear-gradient(135deg, var(--pudu-cyan), var(--pudu-blue));
            color: #FFFFFF;
            font-weight: 720;
            box-shadow: 0 10px 22px rgba(37, 99, 235, 0.20);
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover,
        div[data-testid="stFormSubmitButton"] button:hover {
            filter: brightness(0.98);
            box-shadow: 0 12px 26px rgba(37, 99, 235, 0.26);
            color: #FFFFFF;
        }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        textarea {
            border-color: var(--pudu-line);
            background-color: rgba(255, 255, 255, 0.92);
        }
        [data-testid="stDataFrame"] {
            border: 1px solid rgba(118, 138, 160, 0.26);
            border-radius: 10px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def get_inventory_password() -> str:
    try:
        return str(st.secrets.get("INVENTORY_VIEW_PASSWORD", DEFAULT_PASSWORD))
    except (FileNotFoundError, KeyError, AttributeError):
        return DEFAULT_PASSWORD


def get_approval_password() -> str:
    try:
        return str(st.secrets.get("APPROVAL_VIEW_PASSWORD", get_inventory_password()))
    except (FileNotFoundError, KeyError, AttributeError):
        return get_inventory_password()


def get_secret_value(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default)).strip()
    except (FileNotFoundError, KeyError, AttributeError):
        return default


def feishu_app_id() -> str:
    return get_secret_value("FEISHU_APP_ID")


def feishu_app_secret() -> str:
    return get_secret_value("FEISHU_APP_SECRET")


def feishu_bitable_app_token() -> str:
    return get_secret_value("FEISHU_BITABLE_APP_TOKEN")


def feishu_configured() -> bool:
    return bool(feishu_app_id() and feishu_app_secret() and feishu_bitable_app_token())


def feishu_config_args() -> tuple[str, str, str]:
    return feishu_app_id(), feishu_app_secret(), feishu_bitable_app_token()


def stop_on_invalid_feishu_config() -> None:
    values = {
        "FEISHU_APP_ID": feishu_app_id(),
        "FEISHU_APP_SECRET": feishu_app_secret(),
        "FEISHU_BITABLE_APP_TOKEN": feishu_bitable_app_token(),
    }
    if all(values.values()):
        return

    missing = [key for key, value in values.items() if not value]
    st.error("应用现在只使用飞书多维表格，请先补齐飞书配置：" + "、".join(missing))
    st.info("请在 Streamlit Secrets 中同时填写 FEISHU_APP_ID、FEISHU_APP_SECRET、FEISHU_BITABLE_APP_TOKEN。")
    st.stop()


def redact_feishu_error(message: str) -> str:
    message = re.sub(r"cli_[A-Za-z0-9]+", "cli_***", message)
    return re.sub(r"https://open\.feishu\.cn/\S+", "[飞书权限配置链接]", message)


def render_feishu_error(exc: FeishuBitableError) -> None:
    message = str(exc)
    st.error("飞书多维表格读取失败，请先检查应用权限和多维表格授权。")
    if "99991672" in message or "scope" in message or "权限" in message:
        st.info("当前飞书应用缺少多维表格读取权限。请在飞书开放平台给应用开通 bitable/base 表格读取权限，并确认该应用已添加到目标多维表格。")
    with st.expander("查看错误详情"):
        st.code(redact_feishu_error(message), language="text")


@st.cache_resource(show_spinner=False)
def get_feishu_bitable_client(app_id: str, app_secret: str, app_token: str) -> FeishuBitableClient:
    return FeishuBitableClient(FeishuBitableConfig(app_id, app_secret, app_token))


def feishu_client() -> FeishuBitableClient | None:
    app_id = feishu_app_id()
    app_secret = feishu_app_secret()
    app_token = feishu_bitable_app_token()
    if not app_id or not app_secret or not app_token:
        return None
    return get_feishu_bitable_client(app_id, app_secret, app_token)


@st.cache_data(show_spinner=False, ttl=300)
def load_feishu_schema_snapshot(app_id: str, app_secret: str, app_token: str) -> dict:
    return get_feishu_bitable_client(app_id, app_secret, app_token).discover_schema()


def feishu_schema() -> dict:
    return load_feishu_schema_snapshot(feishu_app_id(), feishu_app_secret(), feishu_bitable_app_token())


def refresh_feishu_schema_cache() -> None:
    load_feishu_schema_snapshot.clear()


def feishu_table_id(table_name: str) -> str:
    table = feishu_schema().get("tables", {}).get(table_name)
    if not table:
        raise RuntimeError(f"飞书多维表格缺少数据表：{table_name}")
    return str(table["table_id"])


def feishu_table_fields(table_name: str) -> dict:
    table = feishu_schema().get("tables", {}).get(table_name)
    return dict((table or {}).get("fields") or {})


def feishu_has_field(table_name: str, field_name: str) -> bool:
    return field_name in feishu_table_fields(table_name)


def first_feishu_field(table_name: str, candidates: list[str]) -> str:
    fields = feishu_table_fields(table_name)
    for field_name in candidates:
        if field_name in fields:
            return field_name
    return candidates[0] if candidates else ""


def feishu_field_type(table_name: str, field_name: str) -> object:
    return feishu_table_fields(table_name).get(field_name, {}).get("type")


def normalize_feishu_field_value(table_name: str, field_name: str, value: object) -> object | None:
    if value is None:
        return None
    field_type = feishu_field_type(table_name, field_name)
    if field_type == 1:
        return str(value)
    if field_type == 2:
        try:
            return float(value) if isinstance(value, str) and "." in value else int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return value
    if field_type == 5:
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return value
    if field_type in {18, 21}:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if value:
            return [str(value)]
        return None
    return value


def filter_feishu_fields(table_name: str, fields: dict[str, object]) -> dict[str, object]:
    table_fields = feishu_table_fields(table_name)
    result: dict[str, object] = {}
    for key, value in fields.items():
        if key not in table_fields:
            continue
        normalized = normalize_feishu_field_value(table_name, key, value)
        if normalized is not None:
            result[key] = normalized
    return result


def feishu_accepts_plain_value(table_name: str, field_name: str) -> bool:
    field_type = feishu_field_type(table_name, field_name)
    return field_type not in {11, 17, 18, 21, 23}


def feishu_datetime_value(table_name: str, field_name: str, value: datetime) -> object:
    return feishu_timestamp(value)


def is_feishu_field_conversion_error(exc: Exception) -> bool:
    message = str(exc)
    return "FieldConvFail" in message or "125406" in message


def feishu_batch_create_records(table_name: str, records: list[dict[str, object]]) -> list[dict]:
    client = feishu_client()
    if client is None:
        return []
    writable_records = [filter_feishu_fields(table_name, fields) for fields in records]
    writable_records = [fields for fields in writable_records if fields]
    if not writable_records:
        raise RuntimeError(f"{table_name} 没有可写入的匹配字段。")
    try:
        return client.batch_create_records(feishu_table_id(table_name), writable_records)
    except FeishuBitableError as exc:
        if not is_feishu_field_conversion_error(exc):
            raise
        st.cache_data.clear()
        writable_records = [filter_feishu_fields(table_name, fields) for fields in records]
        writable_records = [fields for fields in writable_records if fields]
        return client.batch_create_records(feishu_table_id(table_name), writable_records)


def set_first_plain_field(
    table_name: str,
    fields: dict[str, object],
    candidates: list[str],
    value: object,
) -> None:
    if value in (None, ""):
        return
    for field_name in candidates:
        if feishu_has_field(table_name, field_name) and feishu_accepts_plain_value(table_name, field_name):
            fields[field_name] = value
            return


def feishu_create_record(table_name: str, fields: dict[str, object]) -> dict:
    created = feishu_batch_create_records(table_name, [fields])
    return created[0] if created else {}


def feishu_update_record_fields(table_name: str, record_id: str, fields: dict[str, object]) -> dict:
    client = feishu_client()
    if client is None:
        return {}
    writable_fields = filter_feishu_fields(table_name, fields)
    if not writable_fields:
        return {}
    try:
        return client.update_record(feishu_table_id(table_name), record_id, writable_fields)
    except FeishuBitableError as exc:
        if not is_feishu_field_conversion_error(exc):
            raise
        st.cache_data.clear()
        writable_fields = filter_feishu_fields(table_name, fields)
        if not writable_fields:
            return {}
        return client.update_record(feishu_table_id(table_name), record_id, writable_fields)


def storage_mode_label() -> str:
    return "飞书多维表格"


def count_feishu_table(table_name: str) -> int:
    if table_name == "物料主数据":
        return len(load_feishu_inventory())
    if table_name == "库存流水":
        return len(load_feishu_transactions_dataframe())
    client = feishu_client()
    if client is None:
        return 0
    return len(client.list_records(feishu_table_id(table_name)))


def render_storage_diagnostics() -> None:
    with st.sidebar.expander("存储状态", expanded=False):
        st.write(f"当前存储：**{storage_mode_label()}**")
        st.write(f"FEISHU_APP_ID：{'已读取' if bool(feishu_app_id()) else '未读取'}")
        st.write(f"FEISHU_APP_SECRET：{'已读取' if bool(feishu_app_secret()) else '未读取'}")
        st.write(f"FEISHU_BITABLE_APP_TOKEN：{'已读取' if bool(feishu_bitable_app_token()) else '未读取'}")

        st.caption("为加快页面打开速度，行数统计改为手动检查。")
        if st.button("检查连接并刷新数据", key="refresh_storage_status", width="stretch"):
            st.cache_resource.clear()
            st.cache_data.clear()
            try:
                categories_count = count_feishu_table("物料品类")
                inventory_count = count_feishu_table("物料主数据")
                transactions_count = count_feishu_table("库存流水")
                st.success("飞书多维表格连接成功")
                st.caption(
                    f"品类 {categories_count or 0} 条 / 库存 {inventory_count or 0} 条 / 流水 {transactions_count or 0} 条"
                )
            except Exception as exc:
                st.error("飞书多维表格连接失败")
                st.caption(str(exc))


def unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    return result


def normalize_option_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def parse_custom_values(raw_text: str) -> list[str]:
    parts = re.split(r"[\n,，;；、]+", raw_text)
    return unique_preserve(parts)


def sort_languages(languages: list[str]) -> list[str]:
    unique_languages = unique_preserve(languages)

    def priority(language: str) -> int:
        if "English" in language or "英语" in language:
            return 0
        if "Simplified Chinese" in language or "简中" in language:
            return 1
        return 2

    return sorted(
        unique_languages,
        key=lambda language: (priority(language), unique_languages.index(language)),
    )


def build_inventory_selection_context() -> dict[str, object]:
    options = load_options()
    inventory_df = load_inventory()
    product_models: dict[str, list[str]] = {}
    product_languages: dict[str, list[str]] = {}
    product_model_languages: dict[tuple[str, str], list[str]] = {}
    inventory_product_keys: set[str] = set()

    if not inventory_df.empty:
        for item in inventory_df[[PRODUCT_COL, MODEL_COL, LANGUAGE_COL]].itertuples(index=False):
            product_key = normalize_option_label(item[0])
            model_name = str(item[1]).strip() or NO_MODEL_TEXT
            model_key = normalize_option_label(model_name)
            language_name = str(item[2]).strip()
            inventory_product_keys.add(product_key)
            if model_name and model_name != NO_MODEL_TEXT:
                product_models.setdefault(product_key, []).append(model_name)
            if language_name:
                product_languages.setdefault(product_key, []).append(language_name)
                product_model_languages.setdefault((product_key, model_key), []).append(language_name)

    return {
        "products": options["products"],
        "models": options["models"],
        "languages": sort_languages(options["languages"]),
        "no_model_product_keys": {normalize_option_label(product) for product in options["no_model_products"]},
        "inventory_product_keys": inventory_product_keys,
        "product_models": {key: unique_preserve(values) for key, values in product_models.items()},
        "product_languages": {key: sort_languages(values) for key, values in product_languages.items()},
        "product_model_languages": {
            key: sort_languages(values) for key, values in product_model_languages.items()
        },
        "inventory_df": inventory_df,
    }


def product_model_state(product: str, selection_context: dict[str, object]) -> tuple[bool, list[str]]:
    product_key = normalize_option_label(product)
    product_models = selection_context["product_models"]
    scoped_models = product_models.get(product_key, [])  # type: ignore[union-attr]
    is_no_model_product = product_key in selection_context["no_model_product_keys"] or (
        product_key in selection_context["inventory_product_keys"] and not scoped_models
    )
    return bool(is_no_model_product), list(scoped_models)


def product_language_options(
    product: str,
    model: str,
    selection_context: dict[str, object],
    fallback_languages: list[str] | None = None,
) -> list[str]:
    product_key = normalize_option_label(product)
    model_key = normalize_option_label(model or NO_MODEL_TEXT)
    product_model_languages = selection_context["product_model_languages"]
    product_languages = selection_context["product_languages"]

    scoped_languages = product_model_languages.get((product_key, model_key), [])  # type: ignore[union-attr]
    if not scoped_languages:
        scoped_languages = product_languages.get(product_key, [])  # type: ignore[union-attr]
    if not scoped_languages:
        scoped_languages = fallback_languages or list(selection_context["languages"])
    return sort_languages(list(scoped_languages))


def request_form_cache_from_inventory(
    options: dict,
    inventory_df: pd.DataFrame,
    *,
    source: str,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    if not inventory_df.empty:
        for item in inventory_df.fillna("").itertuples(index=False):
            rows.append(
                {
                    "material_code": str(item[0]),
                    "product": str(item[1]),
                    "model": str(item[2]) or NO_MODEL_TEXT,
                    "language": str(item[3]),
                    "quantity": int(item[4] or 0),
                }
            )
    return {
        "schema_version": 1,
        "source": source,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "products": unique_preserve(list(options.get("products") or [])),
        "no_model_products": unique_preserve(list(options.get("no_model_products") or [])),
        "models": unique_preserve(list(options.get("models") or [])),
        "languages": sort_languages(list(options.get("languages") or [])),
        "inventory_rows": rows,
        "row_count": len(rows),
    }


def build_live_request_form_cache() -> dict[str, object]:
    inventory_df = load_feishu_inventory()
    options = load_feishu_options()
    return request_form_cache_from_inventory(options, inventory_df, source="live_feishu")


@st.cache_data(show_spinner=False)
def load_static_request_form_cache() -> dict[str, object]:
    if not REQUEST_FORM_STATIC_CACHE_PATH.exists():
        return {
            "schema_version": 1,
            "source": "empty",
            "generated_at": "",
            "products": [],
            "no_model_products": [],
            "models": [],
            "languages": [],
            "inventory_rows": [],
            "row_count": 0,
        }
    return json.loads(REQUEST_FORM_STATIC_CACHE_PATH.read_text(encoding="utf-8"))


def request_form_cache_state() -> dict[str, object]:
    with REQUEST_FORM_CACHE_LOCK:
        return dict(REQUEST_FORM_CACHE_STATE)


def set_request_form_cache_state(**updates: object) -> None:
    with REQUEST_FORM_CACHE_LOCK:
        REQUEST_FORM_CACHE_STATE.update(updates)


def refresh_request_form_cache_sync() -> dict[str, object]:
    data = build_live_request_form_cache()
    set_request_form_cache_state(data=data, refreshing=False, error="", updated_at=str(data.get("generated_at") or ""))
    return data


def start_request_form_cache_refresh() -> None:
    state = request_form_cache_state()
    if state.get("refreshing"):
        return
    set_request_form_cache_state(refreshing=True, error="")

    def worker() -> None:
        try:
            refresh_request_form_cache_sync()
        except Exception as exc:
            set_request_form_cache_state(refreshing=False, error=str(exc))

    threading.Thread(target=worker, name="request-form-cache-refresh", daemon=True).start()


def request_form_cache_to_selection_context(cache_data: dict[str, object]) -> dict[str, object]:
    product_models: dict[str, list[str]] = {}
    product_languages: dict[str, list[str]] = {}
    product_model_languages: dict[tuple[str, str], list[str]] = {}
    inventory_product_keys: set[str] = set()
    rows = list(cache_data.get("inventory_rows") or [])
    for item in rows:
        if not isinstance(item, dict):
            continue
        product = str(item.get("product") or "").strip()
        model = str(item.get("model") or "").strip() or NO_MODEL_TEXT
        language = str(item.get("language") or "").strip()
        if not product:
            continue
        product_key = normalize_option_label(product)
        model_key = normalize_option_label(model)
        inventory_product_keys.add(product_key)
        if model and model != NO_MODEL_TEXT:
            product_models.setdefault(product_key, []).append(model)
        if language:
            product_languages.setdefault(product_key, []).append(language)
            product_model_languages.setdefault((product_key, model_key), []).append(language)

    products = unique_preserve(list(cache_data.get("products") or []) + [str(item.get("product") or "") for item in rows if isinstance(item, dict)])
    models = unique_preserve(list(cache_data.get("models") or []) + [str(item.get("model") or "") for item in rows if isinstance(item, dict)])
    languages = sort_languages(unique_preserve(list(cache_data.get("languages") or []) + [str(item.get("language") or "") for item in rows if isinstance(item, dict)]))
    return {
        "products": products,
        "models": [model for model in models if model and model != NO_MODEL_TEXT],
        "languages": languages,
        "no_model_product_keys": {
            normalize_option_label(product) for product in list(cache_data.get("no_model_products") or [])
        },
        "inventory_product_keys": inventory_product_keys,
        "product_models": {key: unique_preserve(values) for key, values in product_models.items()},
        "product_languages": {key: sort_languages(values) for key, values in product_languages.items()},
        "product_model_languages": {
            key: sort_languages(values) for key, values in product_model_languages.items()
        },
        "inventory_df": pd.DataFrame(rows),
        "cache_source": cache_data.get("source", ""),
        "cache_generated_at": cache_data.get("generated_at", ""),
        "cache_row_count": int(cache_data.get("row_count") or len(rows)),
    }


def mark_request_form_dirty() -> None:
    st.session_state["request_form_cache_locked"] = True


def reset_request_form_cache_lock() -> None:
    st.session_state.pop("request_form_cache_locked", None)
    st.session_state.pop("request_form_cache_data", None)


def get_request_form_selection_context() -> dict[str, object]:
    state = request_form_cache_state()
    live_data = state.get("data") if isinstance(state.get("data"), dict) else None
    static_data = load_static_request_form_cache()
    if "request_form_cache_data" not in st.session_state:
        st.session_state["request_form_cache_data"] = live_data or static_data
    elif live_data and not st.session_state.get("request_form_cache_locked"):
        current_generated_at = str(st.session_state["request_form_cache_data"].get("generated_at") or "")
        live_generated_at = str(live_data.get("generated_at") or "")
        if live_generated_at and live_generated_at != current_generated_at:
            st.session_state["request_form_cache_data"] = live_data
    start_request_form_cache_refresh()
    return request_form_cache_to_selection_context(dict(st.session_state["request_form_cache_data"]))


def format_datetime(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value or "")
    return parsed.strftime("%Y-%m-%d %H:%M")


def parse_datetime(value: object) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def selected_values_from_editor(df: pd.DataFrame, id_column: str = "记录ID") -> list[str]:
    if df.empty or "选择" not in df.columns or id_column not in df.columns:
        return []
    selected = df[df["选择"].fillna(False)]
    return [str(value) for value in selected[id_column].tolist() if str(value)]


def apply_inventory_filters(
    df: pd.DataFrame,
    selected_products: list[str],
    selected_models: list[str],
    selected_languages: list[str],
    only_stocked: bool,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if selected_products:
        mask &= df[PRODUCT_COL].isin(selected_products)
    if selected_models:
        model_mask = df[MODEL_COL].isin(selected_models)
        mask &= model_mask
    if selected_languages:
        mask &= df[LANGUAGE_COL].isin(selected_languages)
    if only_stocked:
        mask &= df[QTY_COL] != 0
    return df[mask]


def navigate_to_inventory(key: str, label: str = "查看实时库存表") -> None:
    if st.button(label, key=key, type="primary", width="stretch"):
        st.query_params["view"] = "inventory"
        st.rerun()


def navigate_to_approval(key: str, label: str = "打开审批发放页") -> None:
    if st.button(label, key=key, width="stretch"):
        st.query_params["view"] = "approval"
        st.rerun()


def navigate_to_cache(key: str, label: str = "打开数据缓存页") -> None:
    if st.button(label, key=key, width="stretch"):
        st.query_params["view"] = "cache"
        st.rerun()


def navigate_to_management(key: str, label: str = "返回库存管理") -> None:
    if st.button(label, key=key, width="stretch"):
        st.query_params.clear()
        st.rerun()


def workbook_bytes(df: pd.DataFrame) -> bytes:
    df = df[INVENTORY_HEADERS].fillna("").copy()
    wb = Workbook()
    ws = wb.active
    ws.title = "库存表"
    ws.append(INVENTORY_HEADERS)

    for row in df[INVENTORY_HEADERS].itertuples(index=False, name=None):
        ws.append(list(row))

    header_fill = PatternFill("solid", fgColor="0F766E")
    header_font = Font(color="FFFFFF", bold=True)
    no_model_fill = PatternFill("solid", fgColor="ECFDF5")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    widths = [14, 46, 24, 28, 24, 12, 18, 22]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width

    for row_idx in range(2, ws.max_row + 1):
        if ws.cell(row_idx, 3).value == NO_MODEL_TEXT:
            for col_idx in range(1, ws.max_column + 1):
                ws.cell(row_idx, col_idx).fill = no_model_fill
        ws.cell(row_idx, 5).number_format = "0"
        ws.cell(row_idx, 6).number_format = "0.00"
        ws.cell(row_idx, 7).number_format = "0.00"

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    table = Table(displayName="InventoryTable", ref=f"A1:H{ws.max_row}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_rows_snapshot(table_name: str, app_id: str, app_secret: str, app_token: str) -> list[dict]:
    if not app_id or not app_secret or not app_token:
        return []
    client = get_feishu_bitable_client(app_id, app_secret, app_token)
    schema = load_feishu_schema_snapshot(app_id, app_secret, app_token)
    table = schema.get("tables", {}).get(table_name)
    if not table:
        raise RuntimeError(f"飞书多维表格缺少数据表：{table_name}")
    return client.list_records(str(table["table_id"]))


def feishu_rows(table_name: str) -> list[dict]:
    return load_feishu_rows_snapshot(table_name, *feishu_config_args())


def feishu_record_id(row: dict) -> str:
    return str(row.get("record_id") or row.get("id") or "")


def feishu_fields(row: dict) -> dict:
    return dict(row.get("fields") or {})


def feishu_text(fields: dict, name: str, default: str = "") -> str:
    value = fields.get(name, default)
    if isinstance(value, list):
        if not value:
            return default
        item = value[0]
        if isinstance(item, dict):
            text_arr = item.get("text_arr") or []
            if text_arr:
                return str(text_arr[0])
            return str(item.get("text") or default)
        return str(item)
    if value is None:
        return default
    return str(value)


def feishu_int(fields: dict, name: str, default: int = 0) -> int:
    value = fields.get(name, default)
    if isinstance(value, list):
        value = value[0] if value else default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def feishu_float(fields: dict, name: str, default: float = 0.0) -> float:
    value = fields.get(name, default)
    if isinstance(value, list):
        value = value[0] if value else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def feishu_timestamp(value: object | None = None) -> int:
    if isinstance(value, datetime):
        dt = value
    elif value:
        parsed = pd.to_datetime(value, errors="coerce")
        dt = datetime.now() if pd.isna(parsed) else parsed.to_pydatetime()
    else:
        dt = datetime.now()
    return int(dt.timestamp() * 1000)


def feishu_datetime_text(value: object) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError):
            return str(value)
    return format_datetime(value)


def feishu_link_ids(fields: dict, name: str) -> list[str]:
    value = fields.get(name)
    if value in (None, ""):
        return []

    raw_items = value if isinstance(value, list) else [value]
    record_ids: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            record_ids.append(item)
        elif isinstance(item, dict):
            for key in ("record_id", "id"):
                if item.get(key):
                    record_ids.append(str(item[key]))
            for key in ("record_ids", "link_record_ids"):
                nested = item.get(key) or []
                if isinstance(nested, list):
                    record_ids.extend(str(record_id) for record_id in nested if record_id)
    return unique_preserve(record_ids)


def feishu_text_any(fields: dict, names: list[str], default: str = "") -> str:
    for name in names:
        value = feishu_text(fields, name, "")
        if value:
            return value
    return default


def feishu_int_any(fields: dict, names: list[str], default: int = 0) -> int:
    for name in names:
        if name in fields:
            return feishu_int(fields, name, default)
    return default


def feishu_link_ids_any(fields: dict, names: list[str]) -> list[str]:
    for name in names:
        ids = feishu_link_ids(fields, name)
        if ids:
            return ids
    return []


def feishu_transaction_status(fields: dict) -> str:
    status = feishu_text(fields, "操作状态")
    if status:
        return status
    if fields.get("撤回时间"):
        return "已撤回"
    if feishu_text(fields, "原流水ID"):
        return "冲销记录"
    return "有效"


def feishu_transaction_delta(fields: dict) -> int:
    before_quantity = feishu_int(fields, "变更前数量")
    after_quantity = feishu_int(fields, "变更后数量")
    delta = after_quantity - before_quantity
    if delta != 0:
        return delta
    return feishu_int(fields, "库存变化")


def is_blank_feishu_transaction(fields: dict) -> bool:
    product = feishu_text(fields, "物料品类")
    model = feishu_text(fields, "产品型号") or NO_MODEL_TEXT
    language = feishu_text(fields, "语种")
    note = feishu_text(fields, "备注")
    before_quantity = feishu_int(fields, "变更前数量")
    after_quantity = feishu_int(fields, "变更后数量")
    quantity = feishu_int(fields, "数量", abs(after_quantity - before_quantity))
    return not product and model == NO_MODEL_TEXT and not language and quantity == 0 and not note


def feishu_material_rows() -> list[dict]:
    return feishu_rows("物料主数据")


def feishu_category_rows() -> list[dict]:
    return feishu_rows("物料品类")


def find_feishu_material_by_id(record_id: str) -> dict | None:
    for row in feishu_material_rows():
        if feishu_record_id(row) == record_id:
            return row
    return None


def find_feishu_material_record(product: str, model: str, language: str) -> dict | None:
    key = (product, model or NO_MODEL_TEXT, language)
    return feishu_inventory_index().get(key)


def find_feishu_material_by_code(material_code: str, exclude_record_id: str = "") -> dict | None:
    material_code = material_code.strip()
    for row in feishu_material_rows():
        if exclude_record_id and feishu_record_id(row) == exclude_record_id:
            continue
        if feishu_text(feishu_fields(row), "物料编码") == material_code:
            return row
    return None


def find_feishu_material_duplicate(
    product: str,
    model: str,
    language: str,
    exclude_record_id: str = "",
) -> dict | None:
    product = product.strip()
    model = model.strip() or NO_MODEL_TEXT
    language = language.strip()
    for row in feishu_material_rows():
        if exclude_record_id and feishu_record_id(row) == exclude_record_id:
            continue
        fields = feishu_fields(row)
        if (
            feishu_text(fields, "物料品类") == product
            and (feishu_text(fields, "产品型号") or NO_MODEL_TEXT) == model
            and feishu_text(fields, "语种") == language
        ):
            return row
    return None


def resolve_feishu_material_from_transaction(row: dict) -> dict:
    fields = feishu_fields(row)
    linked_ids = feishu_link_ids(fields, "物料编码")
    for record_id in linked_ids:
        material_row = find_feishu_material_by_id(record_id)
        if material_row is not None:
            return material_row

    product = feishu_text(fields, "物料品类")
    model = feishu_text(fields, "产品型号") or NO_MODEL_TEXT
    language = feishu_text(fields, "语种")
    material_row = find_feishu_material_record(product, model, language)
    if material_row is None:
        raise RuntimeError(f"未找到流水对应物料: {product} / {model} / {language}")
    return material_row


def append_admin_note(existing: str, label: str, note: str) -> str:
    note = note.strip()
    if not note:
        return existing
    suffix = f"{label}：{note}"
    return f"{existing}\n{suffix}" if existing else suffix


def feishu_inventory_index() -> dict[tuple[str, str, str], dict]:
    index: dict[tuple[str, str, str], dict] = {}
    for row in feishu_rows("物料主数据"):
        fields = feishu_fields(row)
        key = (
            feishu_text(fields, "物料品类"),
            feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
            feishu_text(fields, "语种"),
        )
        index[key] = row
    return index


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_inventory_snapshot(app_id: str, app_secret: str, app_token: str) -> pd.DataFrame:
    data: list[list[object]] = []
    for row in load_feishu_rows_snapshot("物料主数据", app_id, app_secret, app_token):
        fields = feishu_fields(row)
        material_code = feishu_text(fields, "物料编码")
        category = feishu_text(fields, "物料品类")
        if not material_code or not category:
            continue
        quantity = feishu_int(fields, "当前库存")
        unit_price = feishu_float(fields, "单价")
        data.append(
            [
                material_code,
                category,
                feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
                feishu_text(fields, "语种"),
                quantity,
                unit_price,
                quantity * unit_price,
                "",
            ]
        )
    return pd.DataFrame(data, columns=INVENTORY_HEADERS)


def load_feishu_inventory() -> pd.DataFrame:
    return load_feishu_inventory_snapshot(*feishu_config_args())


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_options_snapshot(app_id: str, app_secret: str, app_token: str) -> dict:
    categories = load_feishu_rows_snapshot("物料品类", app_id, app_secret, app_token)
    inventory_df = load_feishu_inventory_snapshot(app_id, app_secret, app_token)
    products: list[str] = []
    no_model_products: list[str] = []
    for row in categories:
        fields = feishu_fields(row)
        product = feishu_text(fields, "物料品类")
        if product:
            products.append(product)
        if feishu_text(fields, "是否无需型号") == "是":
            no_model_products.append(product)
    if not products and not inventory_df.empty:
        products = unique_preserve(list(inventory_df[PRODUCT_COL].astype(str)))
    inventory_no_model_products = (
        unique_preserve(list(inventory_df.loc[inventory_df[MODEL_COL] == NO_MODEL_TEXT, PRODUCT_COL].astype(str)))
        if not inventory_df.empty
        else []
    )
    models = unique_preserve(
        [value for value in inventory_df[MODEL_COL].astype(str) if value and value != NO_MODEL_TEXT]
    ) if not inventory_df.empty else []
    languages = unique_preserve(list(inventory_df[LANGUAGE_COL].astype(str))) if not inventory_df.empty else []
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "products": unique_preserve(products),
        "no_model_products": unique_preserve(no_model_products + inventory_no_model_products),
        "models": models,
        "languages": languages,
        "no_model_text": NO_MODEL_TEXT,
        "row_count": len(inventory_df),
    }


def load_feishu_options() -> dict:
    return load_feishu_options_snapshot(*feishu_config_args())


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_transactions_dataframe_snapshot(app_id: str, app_secret: str, app_token: str) -> pd.DataFrame:
    data: list[list[object]] = []
    for row in load_feishu_rows_snapshot("库存流水", app_id, app_secret, app_token):
        fields = feishu_fields(row)
        if not fields or is_blank_feishu_transaction(fields):
            continue
        product = feishu_text(fields, "物料品类")
        model = feishu_text(fields, "产品型号") or NO_MODEL_TEXT
        language = feishu_text(fields, "语种")
        note = feishu_text(fields, "备注")
        before_quantity = feishu_int(fields, "变更前数量")
        after_quantity = feishu_int(fields, "变更后数量")
        quantity = feishu_int(fields, "数量", abs(after_quantity - before_quantity))
        data.append(
            [
                feishu_datetime_text(fields.get("发生时间", "")),
                feishu_text(fields, "流水类型"),
                product,
                model,
                language,
                quantity,
                before_quantity,
                after_quantity,
                note,
            ]
        )
    return pd.DataFrame(data, columns=TRANSACTION_HEADERS)


def load_feishu_transactions_dataframe() -> pd.DataFrame:
    return load_feishu_transactions_dataframe_snapshot(*feishu_config_args())


def feishu_ledger_type(action: str) -> str:
    return action


def create_feishu_ledger(
    material_record_id: str,
    action: str,
    product: str,
    model: str,
    language: str,
    quantity: int,
    before_quantity: int,
    after_quantity: int,
    note: str,
    occurred_at: datetime,
    *,
    status: str = "有效",
    original_ledger_id: str = "",
    source_request_id: str = "",
    source_line_id: str = "",
    source_request_no: str = "",
    idempotency_key: str = "",
) -> dict | None:
    client = feishu_client()
    if client is None:
        return None
    fields: dict[str, object] = {
        "发生时间": feishu_timestamp(occurred_at),
        "流水类型": feishu_ledger_type(action),
        "物料编码": [material_record_id],
        "物料品类": product,
        "产品型号": model or NO_MODEL_TEXT,
        "语种": language,
        "数量": int(quantity),
        "变更前数量": int(before_quantity),
        "变更后数量": int(after_quantity),
        "库存变化": int(after_quantity) - int(before_quantity),
        "幂等键": idempotency_key or f"streamlit:{uuid.uuid4().hex}",
        "操作状态": status,
        "备注": note,
        "关联申请单": [source_request_id] if source_request_id else None,
        "关联申请明细": [source_line_id] if source_line_id else None,
        "关联明细": [source_line_id] if source_line_id else None,
        "关联申请单号": source_request_no or None,
    }
    if original_ledger_id:
        fields["原流水ID"] = original_ledger_id

    created = feishu_batch_create_records("库存流水", [fields])
    return created[0] if created else None


def apply_feishu_changes(changes: list[dict[str, object]]) -> list[list[object]]:
    client = feishu_client()
    if client is None:
        return []

    inventory_index = feishu_inventory_index()
    logs: list[list[object]] = []
    for item in changes:
        product = str(item["product"])
        model = str(item["model"]) or NO_MODEL_TEXT
        language = str(item["language"])
        action = str(item["action"])
        quantity = int(item["quantity"])
        note = str(item["note"]).strip()
        key = (product, model, language)
        row = inventory_index.get(key)
        if row is None:
            raise RuntimeError(f"未找到物料组合: {product} / {model} / {language}")

        fields = feishu_fields(row)
        before_quantity = feishu_int(fields, "当前库存")
        if action in INCREASE_ACTIONS:
            after_quantity = before_quantity + quantity
        elif action in DECREASE_ACTIONS:
            after_quantity = before_quantity - quantity
        else:
            raise RuntimeError(f"不支持的操作: {action}")

        material_record_id = feishu_record_id(row)
        occurred_at = datetime.now()
        client.update_record(
            feishu_table_id("物料主数据"),
            material_record_id,
            {"当前库存": after_quantity},
        )
        create_feishu_ledger(
            material_record_id,
            action,
            product,
            model,
            language,
            quantity,
            before_quantity,
            after_quantity,
            note,
            occurred_at,
        )
        logs.append(
            [
                occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
                action,
                product,
                model,
                language,
                quantity,
                before_quantity,
                after_quantity,
                note,
            ]
        )
    return logs


def next_request_no() -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"{REQUEST_NO_PREFIX}-{today}-"
    max_number = 0
    for row in feishu_rows(REQUEST_TABLE_NAME):
        request_no = feishu_text(feishu_fields(row), "申请单号")
        if request_no.startswith(prefix):
            suffix = request_no.removeprefix(prefix)
            if suffix.isdigit():
                max_number = max(max_number, int(suffix))
    return f"{prefix}{max_number + 1:03d}"


def material_lookup_by_key() -> dict[tuple[str, str, str], dict]:
    return feishu_inventory_index()


def request_note_text(request_payload: dict[str, object], attachment_note: str = "") -> str:
    parts = [
        ("客户名称", request_payload.get("customer_name")),
        ("国家", request_payload.get("country")),
        ("收件人信息", request_payload.get("recipient_info")),
        ("运费承担者", request_payload.get("freight_payer")),
        ("物料用途", request_payload.get("material_usage")),
        ("申请人", request_payload.get("requester")),
        ("岗位", request_payload.get("position")),
        ("相关附件", attachment_note),
    ]
    return "\n".join(f"{label}：{str(value).strip()}" for label, value in parts if str(value or "").strip())


def submit_feishu_material_request(
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> tuple[str, int]:
    refresh_feishu_schema_cache()
    valid_lines = [item for item in lines if int(item.get("quantity") or 0) > 0]
    if not valid_lines:
        raise RuntimeError("请至少填写一条数量大于 0 的物料明细。")

    material_index = material_lookup_by_key()
    seen_keys: set[tuple[str, str, str]] = set()
    prepared_lines: list[dict[str, object]] = []
    for item in valid_lines:
        product = str(item.get("product", "")).strip()
        model = str(item.get("model", "")).strip() or NO_MODEL_TEXT
        language = str(item.get("language", "")).strip()
        remark = str(item.get("remark", "")).strip()
        quantity = int(item.get("quantity") or 0)
        if not product or not model or not language:
            raise RuntimeError("每条明细都需要填写物料品类、产品型号和语种。")
        key = (product, model, language)
        if key in seen_keys:
            raise RuntimeError(f"同一申请单内物料重复，请合并数量：{product} / {model} / {language}")
        seen_keys.add(key)
        material_row = material_index.get(key)
        if material_row is None:
            raise RuntimeError(f"未找到物料组合：{product} / {model} / {language}")
        material_fields = feishu_fields(material_row)
        prepared_lines.append(
            {
                "product": product,
                "model": model,
                "language": language,
                "remark": remark,
                "quantity": quantity,
                "material_record_id": feishu_record_id(material_row),
                "material_code": feishu_text(material_fields, "物料编码"),
                "stock_snapshot": feishu_int(material_fields, "当前库存"),
            }
        )

    request_no = next_request_no()
    now = datetime.now()
    material_usage = str(request_payload.get("material_usage") or "").strip()
    request_fields: dict[str, object] = {
        "申请单号": request_no,
        "标题": request_payload.get("title") or REQUEST_FORM_TITLE,
        "申请部门/区域": request_payload.get("department"),
        "申请部门": request_payload.get("department"),
        "申请部门|区域": request_payload.get("department"),
        "客户名称": request_payload.get("customer_name"),
        "国家": request_payload.get("country"),
        "收件人信息": request_payload.get("recipient_info"),
        "运费的承担者": request_payload.get("freight_payer"),
        "运费承担者": request_payload.get("freight_payer"),
        "业务类型": "物料领取",
        "用途/活动": material_usage,
        "用途|活动": material_usage,
        "物料用途": material_usage,
        "审批状态": REQUEST_STATUS_PENDING,
        "提交时间": feishu_datetime_value(REQUEST_TABLE_NAME, "提交时间", now),
        "备注": request_note_text(request_payload, str(request_payload.get("attachment_note") or "")),
    }
    set_first_plain_field(REQUEST_TABLE_NAME, request_fields, ["申请人", "申请人姓名"], request_payload.get("requester"))
    set_first_plain_field(REQUEST_TABLE_NAME, request_fields, ["岗位", "职位"], request_payload.get("position"))
    set_first_plain_field(REQUEST_TABLE_NAME, request_fields, ["附件说明", "相关附件说明"], request_payload.get("attachment_note"))

    request_record = feishu_create_record(REQUEST_TABLE_NAME, request_fields)
    request_record_id = feishu_record_id(request_record)
    if not request_record_id:
        raise RuntimeError("申请单创建成功但未返回记录 ID。")

    line_records: list[dict[str, object]] = []
    for index, item in enumerate(prepared_lines, start=1):
        material_record_id = str(item["material_record_id"])
        line_fields: dict[str, object] = {
            "明细编号": f"{request_no}-{index:02d}",
            "申请数量": int(item["quantity"]),
            "提交时库存快照": int(item["stock_snapshot"]),
            "审批通过数量": int(item["quantity"]),
            "实际发放数量": 0,
            "明细状态": REQUEST_LINE_STATUS_PENDING,
            "备注": item["remark"],
        }
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["申请单号"], request_no)
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["物料品类"], item["product"])
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["产品型号"], item["model"])
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["语种"], item["language"])
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["物料数量"], int(item["quantity"]))
        for request_field in ["所属申请单", "申请单"]:
            if feishu_has_field(REQUEST_LINE_TABLE_NAME, request_field):
                line_fields[request_field] = request_no if feishu_accepts_plain_value(REQUEST_LINE_TABLE_NAME, request_field) else [request_record_id]
                break
        for material_field in ["物料", "物料编码"]:
            if feishu_has_field(REQUEST_LINE_TABLE_NAME, material_field):
                line_fields[material_field] = (
                    item["material_code"]
                    if feishu_accepts_plain_value(REQUEST_LINE_TABLE_NAME, material_field)
                    else [material_record_id]
                )
        line_records.append(line_fields)

    client = feishu_client()
    if client is None:
        return request_no, 0
    created_line_records: list[dict] = []
    try:
        for start in range(0, len(line_records), 500):
            created_line_records.extend(feishu_batch_create_records(REQUEST_LINE_TABLE_NAME, line_records[start : start + 500]))
    except Exception:
        line_table_id = feishu_table_id(REQUEST_LINE_TABLE_NAME)
        for created_line in created_line_records:
            created_line_id = feishu_record_id(created_line)
            if created_line_id:
                try:
                    client.delete_record(line_table_id, created_line_id)
                except Exception:
                    pass
        try:
            client.delete_record(feishu_table_id(REQUEST_TABLE_NAME), request_record_id)
        except Exception:
            pass
        raise
    return request_no, len(line_records)


def load_feishu_request_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in feishu_rows(REQUEST_TABLE_NAME):
        fields = feishu_fields(row)
        request_no = feishu_text(fields, "申请单号")
        if not request_no:
            continue
        records.append(
            {
                "record_id": feishu_record_id(row),
                "request_no": request_no,
                "title": feishu_text(fields, "标题"),
                "requester": feishu_text_any(fields, ["申请人", "申请人姓名"]),
                "department": feishu_text_any(fields, ["申请部门/区域", "申请部门|区域", "申请部门"]),
                "position": feishu_text_any(fields, ["岗位", "职位"]),
                "customer_name": feishu_text(fields, "客户名称"),
                "country": feishu_text(fields, "国家"),
                "recipient_info": feishu_text(fields, "收件人信息"),
                "freight_payer": feishu_text_any(fields, ["运费的承担者", "运费承担者"]),
                "material_usage": feishu_text_any(fields, ["物料用途", "用途/活动", "用途|活动"]),
                "status": feishu_text(fields, "审批状态"),
                "submitted_at": feishu_datetime_text(fields.get("提交时间", "")),
                "approval_comment": feishu_text(fields, "审批意见"),
            }
        )
    records.sort(key=lambda item: str(item["request_no"]), reverse=True)
    return records


def load_feishu_request_line_records() -> list[dict[str, object]]:
    material_by_id = {feishu_record_id(row): row for row in feishu_material_rows()}
    records: list[dict[str, object]] = []
    for row in feishu_rows(REQUEST_LINE_TABLE_NAME):
        fields = feishu_fields(row)
        request_ids = feishu_link_ids_any(fields, ["所属申请单", "申请单"])
        material_ids = feishu_link_ids_any(fields, ["物料", "物料编码"])
        material_row = material_by_id.get(material_ids[0], {}) if material_ids else {}
        material_fields = feishu_fields(material_row)
        product = feishu_text(fields, "物料品类") or feishu_text(material_fields, "物料品类")
        model = feishu_text(fields, "产品型号") or feishu_text(material_fields, "产品型号") or NO_MODEL_TEXT
        language = feishu_text(fields, "语种") or feishu_text(material_fields, "语种")
        quantity = feishu_int_any(fields, ["申请数量", "物料数量"])
        if not product or not language or quantity <= 0:
            continue
        approved_qty = feishu_int(fields, "审批通过数量", quantity)
        actual_qty = feishu_int(fields, "实际发放数量")
        records.append(
            {
                "record_id": feishu_record_id(row),
                "request_ids": request_ids,
                "request_no": feishu_text_any(fields, ["申请单号", "所属申请单", "申请单"]),
                "material_record_id": material_ids[0] if material_ids else "",
                "product": product,
                "model": model,
                "language": language,
                "quantity": quantity,
                "usage": feishu_text(fields, "物料用途"),
                "remark": feishu_text(fields, "备注"),
                "stock_snapshot": feishu_int(fields, "提交时库存快照"),
                "approved_qty": approved_qty,
                "actual_issue_qty": actual_qty,
                "status": feishu_text(fields, "明细状态") or REQUEST_LINE_STATUS_PENDING,
            }
        )
    return records


def issue_request_lines(
    request: dict[str, object],
    edited_lines: list[dict[str, object]],
    note: str,
) -> list[list[object]]:
    client = feishu_client()
    if client is None:
        return []
    inventory_index = material_lookup_by_key()
    logs: list[list[object]] = []
    issued_line_ids: set[str] = set()
    now = datetime.now()
    request_record_id = str(request["record_id"])
    request_no = str(request["request_no"])

    for line in edited_lines:
        actual_qty = int(line.get("actual_issue_qty") or 0)
        requested_qty = int(line.get("quantity") or 0)
        if actual_qty > requested_qty:
            raise RuntimeError(f"{line['product']} / {line['model']} / {line['language']} 实际发放数量不能大于申请数量。")
        if str(line.get("status")) == REQUEST_LINE_STATUS_ISSUED:
            continue
        previous_actual_qty = int(line.get("previous_actual_issue_qty") or 0)
        issue_delta = actual_qty - previous_actual_qty
        if issue_delta < 0:
            raise RuntimeError(f"{line['product']} / {line['model']} / {line['language']} 实际发放数量不能小于已记录数量。")
        if issue_delta <= 0:
            continue

        material_record_id = str(line.get("material_record_id") or "")
        material_row = None
        if material_record_id:
            material_row = find_feishu_material_by_id(material_record_id)
        if material_row is None:
            material_row = inventory_index.get((str(line["product"]), str(line["model"]) or NO_MODEL_TEXT, str(line["language"])))
        if material_row is None:
            raise RuntimeError(f"未找到物料组合：{line['product']} / {line['model']} / {line['language']}")

        material_fields = feishu_fields(material_row)
        material_record_id = feishu_record_id(material_row)
        before_quantity = feishu_int(material_fields, "当前库存")
        after_quantity = before_quantity - issue_delta
        if after_quantity < 0:
            raise RuntimeError(
                f"{line['product']} / {line['model']} / {line['language']} 当前库存 {before_quantity}，不足以发放 {issue_delta}。"
            )

        client.update_record(feishu_table_id("物料主数据"), material_record_id, {"当前库存": after_quantity})
        ledger_note = f"申请单 {request_no} 实际发放"
        if note.strip():
            ledger_note += f"；{note.strip()}"
        create_feishu_ledger(
            material_record_id,
            ACTION_RECEIVE,
            str(line["product"]),
            str(line["model"]),
            str(line["language"]),
            issue_delta,
            before_quantity,
            after_quantity,
            ledger_note,
            now,
            source_request_id=request_record_id,
            source_line_id=str(line["record_id"]),
            source_request_no=request_no,
            idempotency_key=f"issue:{line['record_id']}:{actual_qty}",
        )

        line_status = REQUEST_LINE_STATUS_ISSUED if actual_qty >= requested_qty else REQUEST_LINE_STATUS_PARTIAL
        feishu_update_record_fields(
            REQUEST_LINE_TABLE_NAME,
            str(line["record_id"]),
            {
                "实际发放数量": actual_qty,
                "审批通过数量": actual_qty,
                "明细状态": line_status,
                "发放时间": feishu_datetime_value(REQUEST_LINE_TABLE_NAME, "发放时间", now),
                "缺货说明": note.strip() if actual_qty < requested_qty else "",
            },
        )
        issued_line_ids.add(str(line["record_id"]))
        logs.append(
            [
                now.strftime("%Y-%m-%d %H:%M:%S"),
                ACTION_RECEIVE,
                str(line["product"]),
                str(line["model"]),
                str(line["language"]),
                issue_delta,
                before_quantity,
                after_quantity,
                ledger_note,
            ]
        )

    if not logs:
        raise RuntimeError("请至少填写一条大于 0 的实际发放数量。")

    all_line_ids = {str(line["record_id"]) for line in edited_lines}
    fully_issued_ids = {
        str(line["record_id"])
        for line in edited_lines
        if str(line["record_id"]) in issued_line_ids
        and int(line.get("actual_issue_qty") or 0) >= int(line.get("quantity") or 0)
    }
    request_status = REQUEST_STATUS_ISSUED if all_line_ids and all_line_ids == fully_issued_ids else REQUEST_STATUS_PARTIAL
    feishu_update_record_fields(
        REQUEST_TABLE_NAME,
        request_record_id,
        {
            "审批状态": request_status,
            "审批时间": feishu_datetime_value(REQUEST_TABLE_NAME, "审批时间", now),
            "审批意见": note.strip(),
        },
    )
    return logs


def find_feishu_transaction_by_id(record_id: str) -> dict | None:
    for row in feishu_rows("库存流水"):
        if feishu_record_id(row) == record_id:
            return row
    return None


def load_feishu_transaction_records(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 1000,
) -> list[dict]:
    records: list[dict] = []
    for row in feishu_rows("库存流水"):
        fields = feishu_fields(row)
        if not fields or is_blank_feishu_transaction(fields):
            continue
        occurred_text = feishu_datetime_text(fields.get("发生时间", ""))
        occurred_at = parse_datetime(occurred_text)
        if start_date and (occurred_at is None or occurred_at.date() < start_date):
            continue
        if end_date and (occurred_at is None or occurred_at.date() > end_date):
            continue

        before_quantity = feishu_int(fields, "变更前数量")
        after_quantity = feishu_int(fields, "变更后数量")
        records.append(
            {
                "record_id": feishu_record_id(row),
                "created_at": occurred_text,
                "created_sort": occurred_at or datetime.min,
                "status": feishu_transaction_status(fields),
                "action": feishu_text(fields, "流水类型"),
                "category": feishu_text(fields, "物料品类"),
                "model": feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
                "language": feishu_text(fields, "语种"),
                "quantity": feishu_int(fields, "数量", abs(after_quantity - before_quantity)),
                "before_quantity": before_quantity,
                "after_quantity": after_quantity,
                "delta": feishu_transaction_delta(fields),
                "note": feishu_text(fields, "备注"),
                "reversed_at": feishu_datetime_text(fields.get("撤回时间", "")),
                "reversal_of": feishu_text(fields, "原流水ID"),
                "material_record_id": (feishu_link_ids(fields, "物料编码") or [""])[0],
            }
        )
    records.sort(key=lambda item: item["created_sort"], reverse=True)
    return records[:limit]


def load_feishu_inventory_records() -> list[dict]:
    records: list[dict] = []
    for row in feishu_material_rows():
        fields = feishu_fields(row)
        if not fields:
            continue
        material_code = feishu_text(fields, "物料编码")
        category = feishu_text(fields, "物料品类")
        if not material_code or not category:
            continue
        quantity = feishu_int(fields, "当前库存")
        unit_price = feishu_float(fields, "单价")
        records.append(
            {
                "record_id": feishu_record_id(row),
                "material_code": material_code,
                "category": category,
                "model": feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
                "language": feishu_text(fields, "语种"),
                "quantity": quantity,
                "unit_price": unit_price,
                "total_value": quantity * unit_price,
                "remark": feishu_text(fields, "备注"),
                "customs_code": feishu_text(fields, "海关编码"),
            }
        )
    records.sort(key=lambda item: (item["category"], item["model"], item["language"], item["material_code"]))
    return records


def load_feishu_category_records() -> list[dict]:
    records: list[dict] = []
    for row in feishu_category_rows():
        fields = feishu_fields(row)
        product = feishu_text(fields, "物料品类")
        if not product:
            continue
        records.append(
            {
                "record_id": feishu_record_id(row),
                "category": product,
                "no_model": feishu_text(fields, "是否无需型号") == "是",
                "status": feishu_text(fields, "启用状态"),
                "created_at": feishu_text(fields, "创建时间"),
                "remark": feishu_text(fields, "备注"),
            }
        )
    records.sort(key=lambda item: item["category"])
    return records


def count_feishu_item_transactions(
    material_record_id: str,
    product: str,
    model: str,
    language: str,
) -> int:
    count = 0
    for row in feishu_rows("库存流水"):
        fields = feishu_fields(row)
        if not fields or is_blank_feishu_transaction(fields):
            continue
        linked_ids = feishu_link_ids(fields, "物料编码")
        if material_record_id and material_record_id in linked_ids:
            count += 1
            continue
        if (
            feishu_text(fields, "物料品类") == product
            and (feishu_text(fields, "产品型号") or NO_MODEL_TEXT) == (model or NO_MODEL_TEXT)
            and feishu_text(fields, "语种") == language
        ):
            count += 1
    return count


def count_feishu_category_transactions(product: str) -> int:
    count = 0
    for row in feishu_rows("库存流水"):
        fields = feishu_fields(row)
        if not fields or is_blank_feishu_transaction(fields):
            continue
        if feishu_text(fields, "物料品类") == product:
            count += 1
    return count


def get_or_create_feishu_category_record(product: str, no_model: bool) -> dict:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书客户端未初始化。")
    existing = find_feishu_category_record(product)
    if existing is not None:
        return existing
    created = client.batch_create_records(
        feishu_table_id("物料品类"),
        [
            {
                "物料品类": product,
                "是否无需型号": "是" if no_model else "否",
                "启用状态": "启用",
                "库存行数": 0,
                "产品型号数量": 0,
                "语种数量": 0,
                "备注": "",
            }
        ],
    )
    if not created:
        raise RuntimeError(f"创建物料品类失败: {product}")
    return created[0]


def revert_feishu_transaction(transaction_record_id: str, note: str) -> list[list[object]]:
    client = feishu_client()
    if client is None:
        return []

    transaction_row = find_feishu_transaction_by_id(transaction_record_id)
    if transaction_row is None:
        raise RuntimeError("未找到要撤回的库存流水。")
    transaction_fields = feishu_fields(transaction_row)
    if feishu_transaction_status(transaction_fields) != "有效":
        raise RuntimeError("只能撤回状态为“有效”的库存流水。")

    material_row = resolve_feishu_material_from_transaction(transaction_row)
    material_record_id = feishu_record_id(material_row)
    material_fields = feishu_fields(material_row)
    product = feishu_text(transaction_fields, "物料品类") or feishu_text(material_fields, "物料品类")
    model = feishu_text(transaction_fields, "产品型号") or feishu_text(material_fields, "产品型号") or NO_MODEL_TEXT
    language = feishu_text(transaction_fields, "语种") or feishu_text(material_fields, "语种")
    current_quantity = feishu_int(material_fields, "当前库存")
    original_delta = feishu_transaction_delta(transaction_fields)
    after_quantity = current_quantity - original_delta
    occurred_at = datetime.now()
    reversal_note = f"撤回流水 {transaction_record_id}"
    if note.strip():
        reversal_note += f"；{note.strip()}"

    client.update_record(
        feishu_table_id("物料主数据"),
        material_record_id,
        {"当前库存": after_quantity},
    )
    client.update_record(
        feishu_table_id("库存流水"),
        transaction_record_id,
        {
            "操作状态": "已撤回",
            "撤回时间": feishu_timestamp(occurred_at),
            "备注": append_admin_note(feishu_text(transaction_fields, "备注"), "撤回备注", note),
        },
    )
    create_feishu_ledger(
        material_record_id,
        "撤回",
        product,
        model,
        language,
        abs(original_delta),
        current_quantity,
        after_quantity,
        reversal_note,
        occurred_at,
        status="冲销记录",
        original_ledger_id=transaction_record_id,
    )
    return [
        [
            occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
            "撤回",
            product,
            model,
            language,
            abs(original_delta),
            current_quantity,
            after_quantity,
            reversal_note,
        ]
    ]


def replace_feishu_transaction(
    transaction_record_id: str,
    action: str,
    product: str,
    model: str,
    language: str,
    quantity: int,
    note: str,
) -> list[list[object]]:
    logs = revert_feishu_transaction(transaction_record_id, f"修正原记录。{note}".strip())
    logs.extend(
        apply_feishu_changes(
            [
                {
                    "action": action,
                    "product": product,
                    "model": model,
                    "language": language,
                    "quantity": int(quantity),
                    "note": note,
                }
            ]
        )
    )
    return logs


def delete_feishu_inventory_item(record_id: str) -> None:
    client = feishu_client()
    if client is None:
        return
    client.delete_record(feishu_table_id("物料主数据"), record_id)


def update_feishu_inventory_item(
    record_id: str,
    material_code: str,
    product: str,
    model: str,
    language: str,
    unit_price: float,
    remark: str,
    customs_code: str,
) -> None:
    client = feishu_client()
    if client is None:
        return
    model = model.strip() or NO_MODEL_TEXT
    category_record = get_or_create_feishu_category_record(product.strip(), model == NO_MODEL_TEXT)
    category_record_id = feishu_record_id(category_record)
    client.update_record(
        feishu_table_id("物料主数据"),
        record_id,
        {
            "物料编码": material_code.strip(),
            "物料品类": product.strip(),
            "产品型号": model,
            "语种": language.strip(),
            "单价": float(unit_price or 0),
            "备注": remark.strip(),
            "海关编码": customs_code.strip(),
            "品类关联": [category_record_id] if category_record_id else [],
        },
    )


def delete_feishu_category(product: str, category_record_id: str) -> None:
    client = feishu_client()
    if client is None:
        return
    for row in feishu_material_rows():
        if feishu_text(feishu_fields(row), "物料品类") == product:
            client.delete_record(feishu_table_id("物料主数据"), feishu_record_id(row))
    client.delete_record(feishu_table_id("物料品类"), category_record_id)


def update_feishu_category(old_product: str, new_product: str, no_model: bool, category_record_id: str) -> None:
    client = feishu_client()
    if client is None:
        return
    new_product = new_product.strip()
    client.update_record(
        feishu_table_id("物料品类"),
        category_record_id,
        {
            "物料品类": new_product,
            "是否无需型号": "是" if no_model else "否",
        },
    )
    for row in feishu_material_rows():
        fields = feishu_fields(row)
        if feishu_text(fields, "物料品类") != old_product:
            continue
        update_fields: dict[str, object] = {
            "物料品类": new_product,
            "品类关联": [category_record_id],
        }
        if no_model:
            update_fields["产品型号"] = NO_MODEL_TEXT
        client.update_record(feishu_table_id("物料主数据"), feishu_record_id(row), update_fields)


def find_feishu_category_record(product: str) -> dict | None:
    for row in feishu_rows("物料品类"):
        if feishu_text(feishu_fields(row), "物料品类") == product:
            return row
    return None


def add_feishu_material_category_payload(product: str, no_model: bool, df: pd.DataFrame) -> int:
    client = feishu_client()
    if client is None:
        return 0

    category_record = find_feishu_category_record(product)
    if category_record is None:
        models = unique_preserve(list(df[MODEL_COL].astype(str)))
        languages = unique_preserve(list(df[LANGUAGE_COL].astype(str)))
        created = client.batch_create_records(
            feishu_table_id("物料品类"),
            [
                {
                    "物料品类": product,
                    "是否无需型号": "是" if no_model else "否",
                    "启用状态": "启用",
                    "库存行数": len(df),
                    "产品型号数量": len(models),
                    "语种数量": len(languages),
                    "备注": "",
                }
            ],
        )
        category_record_id = str((created[0] if created else {}).get("record_id", ""))
    else:
        category_record_id = feishu_record_id(category_record)

    records: list[dict[str, object]] = []
    for row in df[INVENTORY_HEADERS].itertuples(index=False):
        records.append(
            {
                "物料编码": str(row[0]),
                "物料品类": str(row[1]),
                "产品型号": str(row[2]) or NO_MODEL_TEXT,
                "语种": str(row[3]),
                "当前库存": int(row[4]),
                "备注": "",
                "单价": float(row[5] or 0),
                "品类关联": [category_record_id] if category_record_id else [],
            }
        )

    inserted = 0
    for start in range(0, len(records), 500):
        created = client.batch_create_records(feishu_table_id("物料主数据"), records[start : start + 500])
        inserted += len(created)
    return inserted


def load_options() -> dict:
    return load_feishu_options()


def load_inventory() -> pd.DataFrame:
    return load_feishu_inventory()


def load_transactions_dataframe() -> pd.DataFrame:
    return load_feishu_transactions_dataframe()


def next_material_id(df: pd.DataFrame) -> str:
    max_number = 0
    for value in df["物料编码"].astype(str):
        match = re.search(r"(\d+)$", value)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"MAT-{max_number + 1:04d}"


def build_new_material_rows(
    df: pd.DataFrame,
    product: str,
    models: list[str],
    languages: list[str],
) -> tuple[list[list[object]], list[tuple[str, str]]]:
    existing_keys = set(zip(df[PRODUCT_COL], df[MODEL_COL], df[LANGUAGE_COL]))
    next_number = int(next_material_id(df).split("-")[-1])
    rows: list[list[object]] = []
    skipped: list[tuple[str, str]] = []

    for model in models:
        for language in languages:
            key = (product, model, language)
            if key in existing_keys:
                skipped.append((model, language))
                continue
            rows.append(
                [
                    f"MAT-{next_number:04d}",
                    product,
                    model,
                    language,
                    0,
                    0,
                    0,
                    "",
                ]
            )
            next_number += 1
    return rows, skipped


def auth_gate() -> bool:
    if st.session_state.get("inventory_unlocked"):
        return True
    password_setting = get_inventory_password()
    password = st.text_input("请输入查看密码", type="password")
    if password == password_setting:
        st.session_state["inventory_unlocked"] = True
        st.rerun()
    if password:
        st.error("密码不正确")
    return False


def approval_auth_gate() -> bool:
    if st.session_state.get("approval_unlocked"):
        return True
    password = st.text_input("请输入审批密码", type="password", key="approval_password")
    if password == get_approval_password():
        st.session_state["approval_unlocked"] = True
        st.rerun()
    if password:
        st.error("密码不正确")
    return False


def render_sidebar_link() -> None:
    st.sidebar.subheader("审批发放入口")
    navigate_to_approval("sidebar_open_approval", "打开审批发放页")
    st.sidebar.caption("审批发放页需要输入审批密码。部署后复制浏览器地址栏链接，即可分享给对应审批人。")
    st.sidebar.divider()
    st.sidebar.subheader("数据缓存")
    navigate_to_cache("sidebar_open_cache", "打开数据缓存页")
    st.sidebar.caption("登记页会优先读取缓存快照，减少销售打开等待时间。")
    st.sidebar.divider()
    st.sidebar.caption("多人共同管理时，请让所有人访问同一个已部署的 Streamlit 应用地址；本地端口只适合开发和测试。")


def get_row_count() -> int:
    return int(
        st.radio(
            "本次填写物料种类数",
            list(range(1, 11)),
            index=2,
            horizontal=True,
            key="request_line_count",
            on_change=mark_request_form_dirty,
        )
    )


def render_change_form(show_title: bool = True) -> None:
    selection_context = get_request_form_selection_context()
    products = list(selection_context["products"])
    models = unique_preserve([NO_MODEL_TEXT] + list(selection_context["models"]))
    languages = list(selection_context["languages"])

    if show_title:
        st.title("营销物料领取登记")
    else:
        st.subheader("营销物料领取登记")
    st.caption("提交后会先生成申请单和申请明细；审批发放页填写实际发放数量后，才会扣减当前库存。")
    cache_state = request_form_cache_state()
    cache_label = "实时缓存" if selection_context.get("cache_source") == "live_feishu" else "静态缓存"
    cache_status = "同步中" if cache_state.get("refreshing") else "已就绪"
    st.caption(
        f"登记页数据：{cache_label} / {selection_context.get('cache_generated_at') or '-'} / "
        f"{selection_context.get('cache_row_count') or 0} 条 / {cache_status}"
    )

    message = st.session_state.pop("request_submit_message", "")
    if message:
        st.success(message)

    row_count = get_row_count()
    lines: list[dict[str, object]] = []

    st.markdown("**申请信息**")
    title = st.text_input("标题", value=REQUEST_FORM_TITLE, on_change=mark_request_form_dirty)
    info_col_a, info_col_b = st.columns(2)
    department = info_col_a.text_input(
        "申请部门",
        value=get_secret_value("DEFAULT_REQUEST_DEPARTMENT", ""),
        on_change=mark_request_form_dirty,
    )
    requester = info_col_b.text_input(
        "申请人",
        value=get_secret_value("DEFAULT_REQUESTER", ""),
        on_change=mark_request_form_dirty,
    )
    position = info_col_b.text_input(
        "岗位",
        value=get_secret_value("DEFAULT_REQUEST_POSITION", ""),
        on_change=mark_request_form_dirty,
    )

    st.markdown("**业务信息 Business Information**")
    biz_col_a, biz_col_b = st.columns(2)
    customer_name = biz_col_a.text_input("客户名称 Customer Name", on_change=mark_request_form_dirty)
    country = biz_col_b.text_input("国家 Country", on_change=mark_request_form_dirty)
    recipient_info = st.text_area(
        "收件人信息 Recipient Information",
        placeholder="请写明快递地址（包含收件人信息、邮编、具体地址）",
        height=96,
        on_change=mark_request_form_dirty,
    )
    freight_payer = st.selectbox(
        "运费的承担者 Freight Payer",
        FREIGHT_PAYER_OPTIONS,
        on_change=mark_request_form_dirty,
    )
    material_usage = st.text_area(
        "物料用途 Material Usage",
        placeholder="活动物料请注明具体活动名称",
        height=76,
        on_change=mark_request_form_dirty,
    )
    uploaded_files = st.file_uploader(
        "相关附件 Relevant Attachments",
        accept_multiple_files=True,
        on_change=mark_request_form_dirty,
    )
    attachment_note = "\n".join(file.name for file in uploaded_files) if uploaded_files else ""
    if uploaded_files:
        st.caption("当前版本会把附件文件名写入“附件说明/相关附件说明”字段；实际文件仍建议在飞书审批消息或多维表格中补充。")

    st.markdown("**物料明细 Material Details**")
    for index in range(row_count):
        st.caption(f"第 {index + 1} 项")
        product_col, model_col, language_col, qty_col = st.columns([2.3, 1.8, 1.7, 1.1])

        product = product_col.selectbox(
            "物料品类(Material Category)",
            products,
            key=f"request_product_{index}",
            on_change=mark_request_form_dirty,
        )
        is_no_model_product, scoped_models = product_model_state(product, selection_context)
        if is_no_model_product:
            model_options = [NO_MODEL_TEXT]
        elif scoped_models:
            model_options = unique_preserve(scoped_models)
        else:
            model_options = [model for model in models if model != NO_MODEL_TEXT] or [NO_MODEL_TEXT]
        if not model_options:
            model_options = [NO_MODEL_TEXT]
        model_key = f"request_model_{index}"
        if st.session_state.get(model_key) not in model_options:
            st.session_state[model_key] = model_options[0]
        model = model_col.selectbox(
            "产品型号(Product Model)",
            model_options,
            key=model_key,
            disabled=is_no_model_product,
            on_change=mark_request_form_dirty,
        )
        language_options = product_language_options(product, model, selection_context, languages)
        language_key = f"request_language_{index}"
        if st.session_state.get(language_key) not in language_options:
            st.session_state[language_key] = language_options[0] if language_options else ""
        language = language_col.selectbox(
            "语种(Language)",
            language_options,
            key=language_key,
            on_change=mark_request_form_dirty,
        )
        quantity = qty_col.number_input(
            "物料数量",
            min_value=0,
            max_value=1_000_000,
            value=0,
            step=1,
            key=f"request_quantity_{index}",
            on_change=mark_request_form_dirty,
        )
        remark = st.text_input(
            "备注",
            key=f"request_remark_{index}",
            placeholder="可选",
            on_change=mark_request_form_dirty,
        )
        lines.append(
            {
                "product": product,
                "model": model,
                "language": language,
                "quantity": int(quantity),
                "remark": remark,
            }
        )

    submitted = st.button(
        "提交申请",
        type="primary",
        width="stretch",
        on_click=mark_request_form_dirty,
    )

    if submitted:
        payload = {
            "title": title,
            "department": department,
            "requester": requester,
            "position": position,
            "customer_name": customer_name,
            "country": country,
            "recipient_info": recipient_info,
            "freight_payer": freight_payer,
            "material_usage": material_usage,
            "attachment_note": attachment_note,
        }
        missing = [
            label
            for label, value in [
                ("申请人", requester),
                ("客户名称", customer_name),
                ("国家", country),
                ("收件人信息", recipient_info),
                ("运费的承担者", freight_payer),
                ("物料用途", material_usage),
            ]
            if not str(value).strip()
        ]
        if missing:
            st.warning("请补充必填信息：" + "、".join(missing))
            return
        with DATA_LOCK:
            try:
                request_no, line_count = submit_feishu_material_request(payload, lines)
            except Exception as exc:
                st.error("提交申请失败。请检查申请单/申请明细表字段、物料组合和飞书写入权限。")
                st.exception(exc)
                return
        st.cache_data.clear()
        reset_request_form_cache_lock()
        st.session_state["request_submit_message"] = f"已提交申请单 {request_no}，共 {line_count} 条申请明细。"
        st.rerun()


def render_add_category_form() -> None:
    options = load_options()
    existing_products = options["products"]
    existing_models = options["models"]
    existing_languages = sort_languages(options["languages"])

    st.subheader("新增物料品类")
    message = st.session_state.pop("category_added_message", "")
    if message:
        st.success(message)

    with st.form("add_category_form", clear_on_submit=False):
        product = st.text_input(
            "新增物料品类",
            placeholder="例如：新版宣传册(New Brochure)",
        ).strip()
        no_model = st.checkbox(
            "该品类不按产品型号分类",
            help="勾选后会按“品类 + 语种”生成，产品型号统一为“无需型号”。",
        )

        model_col, language_col = st.columns(2)
        selected_models = model_col.multiselect(
            "选择已有产品型号",
            existing_models,
            disabled=no_model,
        )
        custom_models_text = model_col.text_area(
            "自定义产品型号",
            placeholder="可用逗号、分号、顿号或换行分隔",
            disabled=no_model,
            height=92,
        )
        selected_languages = language_col.multiselect(
            "选择已有语种",
            existing_languages,
        )
        custom_languages_text = language_col.text_area(
            "自定义语种",
            placeholder="可用逗号、分号、顿号或换行分隔",
            height=92,
        )

        custom_models = parse_custom_values(custom_models_text)
        custom_languages = parse_custom_values(custom_languages_text)
        models = [NO_MODEL_TEXT] if no_model else unique_preserve(selected_models + custom_models)
        languages = unique_preserve(selected_languages + custom_languages)

        preview_count = len(models) * len(languages) if product and models and languages else 0
        st.caption(f"预计新增 {preview_count} 条库存行。")
        submitted = st.form_submit_button("生成新增物料行", width="stretch")

    if submitted:
        add_material_category(
            product=product,
            models=models,
            languages=languages,
            no_model=no_model,
        )


def add_material_category(
    product: str,
    models: list[str],
    languages: list[str],
    no_model: bool,
) -> None:
    product = product.strip()
    if not product:
        st.error("请填写新增物料品类。")
        return
    if not languages:
        st.error("请至少选择或填写一个语种。")
        return
    if not no_model and not models:
        st.error("请至少选择或填写一个产品型号，或勾选“不按产品型号分类”。")
        return

    with DATA_LOCK:
        options = load_options()
        df = load_inventory()
        product_exists_in_inventory = product in set(df[PRODUCT_COL].astype(str))
        product_exists_in_options = product in set(options["products"])
        if product_exists_in_inventory:
            st.error("该物料品类已存在。如需给已有品类补充型号或语种，可以先使用一个新的品类名称。")
            return
        if product_exists_in_options:
            st.info("检测到该品类选项已存在但没有库存行，本次会补建对应库存行。")

        new_rows, skipped = build_new_material_rows(df, product, models, languages)
        if not new_rows:
            st.warning("没有生成新的库存行，可能这些组合已经存在。")
            return

        new_df = pd.DataFrame(new_rows, columns=INVENTORY_HEADERS)
        if feishu_configured():
            try:
                inserted_count = add_feishu_material_category_payload(product, no_model, new_df)
            except Exception as exc:
                st.error(
                    "新增物料品类写入飞书失败。请检查物料主数据里的“物料编码/物料品类/产品型号/语种”是否为单选字段；"
                    "如是单选，需要先在飞书中补充新选项，或改为文本字段。"
                )
                st.exception(exc)
                return
            if inserted_count <= 0:
                st.warning("没有写入新的库存行，可能这些组合已经存在。")
                return

    skipped_text = f"，跳过 {len(skipped)} 条已存在组合" if skipped else ""
    st.session_state["category_added_message"] = f"已新增物料品类“{product}”，生成 {len(new_rows)} 条库存行{skipped_text}。"
    st.cache_data.clear()
    st.rerun()


def render_download_center(full_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    st.subheader("下载库存数据")
    st.caption("需要下载时再生成文件，避免打开库存页时等待导出文件准备。")

    if st.button("生成/刷新下载文件", key="prepare_inventory_downloads", width="stretch"):
        with st.spinner("正在生成下载文件..."):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            transactions_df = load_transactions_dataframe()
            st.session_state["inventory_download_bundle"] = {
                "timestamp": timestamp,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "full_xlsx": workbook_bytes(full_df),
                "full_csv": full_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                "filtered_xlsx": workbook_bytes(filtered_df),
                "filtered_csv": filtered_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                "transaction_csv": transactions_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
            }

    bundle = st.session_state.get("inventory_download_bundle")
    if not bundle:
        st.info("点击上方按钮后会显示下载链接。筛选条件变化后请重新生成。")
        return

    timestamp = str(bundle["timestamp"])
    st.caption(f"下载文件生成时间：{bundle['created_at']}。筛选条件变化后请重新生成。")

    full_col_a, full_col_b, log_col = st.columns(3)
    full_col_a.download_button(
        "下载完整库存 Excel",
        data=bundle["full_xlsx"],
        file_name=f"完整物料库存表_{timestamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    full_col_b.download_button(
        "下载完整库存 CSV",
        data=bundle["full_csv"],
        file_name=f"完整物料库存表_{timestamp}.csv",
        mime="text/csv",
        width="stretch",
    )
    log_col.download_button(
        "下载库存变更流水",
        data=bundle["transaction_csv"],
        file_name=f"库存变更流水_{timestamp}.csv",
        mime="text/csv",
        width="stretch",
    )

    filtered_col_a, filtered_col_b = st.columns(2)
    filtered_col_a.download_button(
        "下载当前筛选 Excel",
        data=bundle["filtered_xlsx"],
        file_name=f"当前筛选物料库存表_{timestamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    filtered_col_b.download_button(
        "下载当前筛选 CSV",
        data=bundle["filtered_csv"],
        file_name=f"当前筛选物料库存表_{timestamp}.csv",
        mime="text/csv",
        width="stretch",
    )


def render_transaction_admin() -> None:
    st.subheader("库存提交记录修改与撤回")
    message = st.session_state.pop("transaction_admin_message", "")
    if message:
        st.success(message)

    filter_col_a, filter_col_b, filter_col_c, filter_col_d = st.columns([1, 1, 1, 1])
    default_end = date.today()
    default_start = default_end - timedelta(days=30)
    start_date = filter_col_a.date_input("开始日期", value=default_start, key="tx_start_date")
    end_date = filter_col_b.date_input("结束日期", value=default_end, key="tx_end_date")
    status_filter = filter_col_c.selectbox("记录状态", ["有效", "全部", "已撤回", "冲销记录"], key="tx_status_filter")
    limit = int(filter_col_d.number_input("最多显示", min_value=100, max_value=5000, value=1000, step=100, key="tx_limit"))
    if start_date > end_date:
        st.warning("开始日期不能晚于结束日期。")
        return

    records = load_feishu_transaction_records(start_date=start_date, end_date=end_date, limit=limit)
    if status_filter != "全部":
        records = [row for row in records if row["status"] == status_filter]
    if not records:
        st.info("暂无库存提交记录。")
        return

    record_map = {row["record_id"]: row for row in records}
    table_df = pd.DataFrame(
        [
            {
                "选择": False,
                "记录ID": row["record_id"],
                "时间": row["created_at"],
                "状态": row["status"],
                "操作": row["action"],
                "物料品类": row["category"],
                "产品型号": row["model"],
                "语种": row["language"],
                "数量": row["quantity"],
                "变更前": row["before_quantity"],
                "变更后": row["after_quantity"],
                "库存变化": row["delta"],
                "原流水ID": row["reversal_of"],
                "备注": row["note"],
            }
            for row in records
        ]
    )
    metric_col_a, metric_col_b, metric_col_c, metric_col_d = st.columns(4)
    metric_col_a.metric("显示记录", f"{len(table_df):,}")
    metric_col_b.metric("有效记录", f"{int((table_df['状态'] == '有效').sum()):,}")
    metric_col_c.metric("库存净变化", f"{int(table_df['库存变化'].sum()):,}")
    metric_col_d.metric("备注记录", f"{int((table_df['备注'].astype(str) != '').sum()):,}")

    edited_df = st.data_editor(
        table_df,
        width="stretch",
        hide_index=True,
        height=420,
        disabled=[column for column in table_df.columns if column != "选择"],
        column_config={"选择": st.column_config.CheckboxColumn("选择")},
        key="tx_editor",
    )
    selected_ids = selected_values_from_editor(edited_df)
    selected_records = [record_map[item_id] for item_id in selected_ids if item_id in record_map]
    active_selected_ids = [row["record_id"] for row in selected_records if row["status"] == "有效"]
    inactive_count = len(selected_records) - len(active_selected_ids)

    action_col_a, action_col_b, action_col_c = st.columns([1.4, 1, 1])
    revert_note = action_col_a.text_input("批量撤回备注", key="tx_batch_revert_note", placeholder="可选")
    revert_confirmed = action_col_b.checkbox("确认批量撤回", key="tx_batch_revert_confirmed")
    if action_col_c.button("批量撤回选中提交", type="primary", width="stretch", key="tx_batch_revert_button"):
        if not active_selected_ids:
            st.warning("请先勾选至少一条有效提交记录。")
        elif inactive_count:
            st.warning("选中记录包含已撤回或冲销记录，请取消这些记录后再操作。")
        elif not revert_confirmed:
            st.warning("请先勾选确认批量撤回。")
        else:
            with DATA_LOCK:
                try:
                    for transaction_id in active_selected_ids:
                        revert_feishu_transaction(transaction_id, revert_note)
                except Exception as exc:
                    st.error("批量撤回失败。请检查飞书应用是否有物料主数据和库存流水编辑权限。")
                    st.exception(exc)
                    return
            st.session_state["transaction_admin_message"] = f"已撤回 {len(active_selected_ids)} 条提交记录。"
            st.cache_data.clear()
            st.rerun()

    if len(active_selected_ids) == 1:
        selected_id = active_selected_ids[0]
        selected = record_map[selected_id]
        with st.expander("编辑选中提交", expanded=True):
            selection_context = build_inventory_selection_context()
            edit_col_a, edit_col_b, edit_col_c, edit_col_d, edit_col_e = st.columns([2, 1.3, 1.5, 1.1, 1])
            products = unique_preserve([str(selected["category"])] + list(selection_context["products"]))
            replace_product = edit_col_a.selectbox(
                "物料品类",
                products,
                index=products.index(str(selected["category"])) if str(selected["category"]) in products else 0,
                key=f"replace_product_{selected_id}",
            )
            is_no_model_product, scoped_models = product_model_state(replace_product, selection_context)
            old_model = str(selected["model"] or NO_MODEL_TEXT)
            if is_no_model_product:
                edit_col_b.text_input("产品型号", value=NO_MODEL_TEXT, disabled=True, key=f"replace_model_blank_{selected_id}")
                replace_model = NO_MODEL_TEXT
            else:
                replace_models = unique_preserve([old_model] + scoped_models + list(selection_context["models"]))
                replace_model = edit_col_b.selectbox(
                    "产品型号",
                    replace_models,
                    index=replace_models.index(old_model) if old_model in replace_models else 0,
                    key=f"replace_model_{selected_id}",
                )
            scoped_languages = product_language_options(replace_product, replace_model, selection_context)
            languages = unique_preserve([str(selected["language"])] + scoped_languages)
            replace_language = edit_col_c.selectbox(
                "语种",
                languages,
                index=languages.index(str(selected["language"])) if str(selected["language"]) in languages else 0,
                key=f"replace_language_{selected_id}",
            )
            default_action = ACTION_PURCHASE if int(selected["delta"]) > 0 else ACTION_RECEIVE
            replace_action = edit_col_d.selectbox(
                "操作",
                ACTION_OPTIONS,
                index=ACTION_OPTIONS.index(default_action),
                key=f"replace_action_{selected_id}",
            )
            replace_quantity = edit_col_e.number_input(
                "数量",
                min_value=1,
                max_value=1_000_000,
                value=max(int(selected["quantity"] or 1), 1),
                step=1,
                key=f"replace_quantity_{selected_id}_{replace_action}",
            )
            replace_note = st.text_input("修正备注", key=f"replace_note_{selected_id}", placeholder="可选")
            replace_confirmed = st.checkbox("确认撤回原记录并保存修正记录", key=f"replace_confirmed_{selected_id}")
            if st.button("保存选中记录的编辑", type="primary", width="stretch", key=f"replace_transaction_button_{selected_id}"):
                if not replace_confirmed:
                    st.warning("请先勾选确认修正。")
                else:
                    with DATA_LOCK:
                        try:
                            replace_feishu_transaction(
                                selected_id,
                                replace_action,
                                replace_product,
                                replace_model,
                                replace_language,
                                int(replace_quantity),
                                replace_note,
                            )
                        except Exception as exc:
                            st.error("修正失败。请检查选中物料是否存在、飞书字段类型是否允许写入。")
                            st.exception(exc)
                            return
                    st.session_state["transaction_admin_message"] = "已撤回原提交，并保存新的修正提交。"
                    st.cache_data.clear()
                    st.rerun()
    elif len(selected_ids) > 1:
        st.info("已选择多条记录，可批量撤回；如需编辑，请只勾选一条有效记录。")
    else:
        st.caption("勾选一条有效记录可编辑；勾选多条有效记录可批量撤回。")


def render_material_data_admin() -> None:
    st.subheader("库存行修改与删除")
    message = st.session_state.pop("material_admin_message", "")
    if message:
        st.success(message)

    search_text = st.text_input("搜索库存行", key="item_search_text", placeholder="物料编码 / 品类 / 型号 / 语种")
    records = load_feishu_inventory_records()
    if not records:
        st.info("暂无物料行。")
        return

    record_map = {row["record_id"]: row for row in records}
    table_df = pd.DataFrame(
        [
            {
                "选择": False,
                "记录ID": row["record_id"],
                "物料编码": row["material_code"],
                "物料品类": row["category"],
                "产品型号": row["model"],
                "语种": row["language"],
                "库存数量": row["quantity"],
                "单价": row["unit_price"],
                "总价值": row["total_value"],
                "备注": row["remark"],
                "海关编码": row["customs_code"],
            }
            for row in records
        ]
    )
    if search_text.strip():
        search = search_text.strip()
        mask = (
            table_df["物料编码"].astype(str).str.contains(search, case=False, na=False)
            | table_df["物料品类"].astype(str).str.contains(search, case=False, na=False)
            | table_df["产品型号"].astype(str).str.contains(search, case=False, na=False)
            | table_df["语种"].astype(str).str.contains(search, case=False, na=False)
        )
        table_df = table_df[mask].reset_index(drop=True)

    metric_col_a, metric_col_b, metric_col_c = st.columns(3)
    metric_col_a.metric("显示库存行", f"{len(table_df):,}")
    metric_col_b.metric("非零库存行", f"{int((table_df['库存数量'] != 0).sum()):,}" if not table_df.empty else "0")
    metric_col_c.metric("库存合计", f"{int(table_df['库存数量'].sum()):,}" if not table_df.empty else "0")

    edited_df = st.data_editor(
        table_df,
        width="stretch",
        hide_index=True,
        height=420,
        disabled=[column for column in table_df.columns if column != "选择"],
        column_config={"选择": st.column_config.CheckboxColumn("选择")},
        key="item_editor",
    )
    selected_ids = selected_values_from_editor(edited_df)
    selected_records = [record_map[item_id] for item_id in selected_ids if item_id in record_map]

    delete_col_a, delete_col_b, delete_col_c = st.columns([1.5, 1, 1])
    delete_col_a.caption("仅允许删除库存为 0 且没有流水记录的库存行。")
    delete_confirmed = delete_col_b.checkbox("确认批量删除", key="item_batch_delete_confirmed")
    if delete_col_c.button("批量删除选中库存行", type="primary", width="stretch", key="item_batch_delete_button"):
        if not selected_records:
            st.warning("请先勾选至少一条库存行。")
        elif not delete_confirmed:
            st.warning("请先勾选确认批量删除。")
        else:
            blocked: list[str] = []
            for row in selected_records:
                tx_count = count_feishu_item_transactions(row["record_id"], row["category"], row["model"], row["language"])
                if int(row["quantity"] or 0) != 0 or tx_count > 0:
                    blocked.append(f"{row['material_code']}（库存 {row['quantity']}，流水 {tx_count}）")
            if blocked:
                st.error("以下库存行不能删除：" + "；".join(blocked[:8]))
            else:
                with DATA_LOCK:
                    try:
                        for row in selected_records:
                            delete_feishu_inventory_item(row["record_id"])
                    except Exception as exc:
                        st.error("批量删除库存行失败。")
                        st.exception(exc)
                        return
                st.session_state["material_admin_message"] = f"已删除 {len(selected_records)} 条库存行。"
                st.cache_data.clear()
                st.rerun()

    if len(selected_records) == 1:
        item = selected_records[0]
        selected_item_id = item["record_id"]
        current_product = str(item["category"])
        current_model = str(item["model"] or NO_MODEL_TEXT)
        current_language = str(item["language"])
        with st.expander("编辑选中库存行", expanded=True):
            edit_col_a, edit_col_b, edit_col_c, edit_col_d = st.columns([1.2, 2, 1.3, 1.4])
            material_code = edit_col_a.text_input("物料编码", value=str(item["material_code"]), key=f"edit_material_code_{selected_item_id}")
            product = edit_col_b.text_input("物料品类", value=current_product, key=f"edit_material_product_{selected_item_id}")
            no_model = edit_col_c.checkbox("无需型号", value=current_model == NO_MODEL_TEXT, key=f"edit_material_no_model_{selected_item_id}")
            if no_model:
                edit_col_d.text_input("产品型号", value=NO_MODEL_TEXT, disabled=True, key=f"edit_material_model_blank_{selected_item_id}")
                model = NO_MODEL_TEXT
            else:
                model = edit_col_d.text_input("产品型号", value=current_model, key=f"edit_material_model_{selected_item_id}")
            language = st.text_input("语种", value=current_language, key=f"edit_material_language_{selected_item_id}")
            meta_col_a, meta_col_b, meta_col_c = st.columns([1, 1.2, 2])
            unit_price = meta_col_a.number_input(
                "单价",
                min_value=0.0,
                value=float(item["unit_price"] or 0),
                step=0.01,
                key=f"edit_material_price_{selected_item_id}",
            )
            customs_code = meta_col_b.text_input("海关编码", value=str(item["customs_code"]), key=f"edit_material_customs_{selected_item_id}")
            remark = meta_col_c.text_input("备注", value=str(item["remark"]), key=f"edit_material_remark_{selected_item_id}")
            if st.button("保存选中库存行修改", type="primary", width="stretch", key=f"save_inventory_item_edit_{selected_item_id}"):
                tx_count = count_feishu_item_transactions(selected_item_id, current_product, current_model, current_language)
                if not material_code.strip() or not product.strip() or not language.strip():
                    st.error("物料编码、物料品类和语种不能为空。")
                elif tx_count > 0:
                    st.error("该库存行已经有流水记录。为保证历史可追溯，请先撤回相关库存提交后再修改行信息。")
                elif find_feishu_material_by_code(material_code, exclude_record_id=selected_item_id) is not None:
                    st.error("新的物料编码已经存在。")
                elif find_feishu_material_duplicate(product, model, language, exclude_record_id=selected_item_id) is not None:
                    st.error("新的“品类 + 型号 + 语种”组合已经存在。")
                else:
                    with DATA_LOCK:
                        try:
                            update_feishu_inventory_item(
                                selected_item_id,
                                material_code,
                                product,
                                model,
                                language,
                                float(unit_price),
                                remark,
                                customs_code,
                            )
                        except Exception as exc:
                            st.error("修改失败。请检查飞书单选字段是否已有对应选项，或改为文本字段。")
                            st.exception(exc)
                            return
                    st.session_state["material_admin_message"] = "库存行信息已修改。"
                    st.cache_data.clear()
                    st.rerun()
    elif len(selected_records) > 1:
        st.info("已选择多条库存行，可批量删除；如需编辑，请只勾选一条。")
    else:
        st.caption("勾选一条库存行可编辑；勾选多条可批量删除。")


def render_category_admin() -> None:
    st.subheader("物料品类修改与撤回")
    message = st.session_state.pop("category_admin_message", "")
    if message:
        st.success(message)

    categories = load_feishu_category_records()
    inventory_records = load_feishu_inventory_records()
    if not categories:
        st.info("暂无物料品类。")
        return

    summary: dict[str, dict[str, int]] = {}
    for item in inventory_records:
        product = str(item["category"])
        stats = summary.setdefault(
            product,
            {"row_count": 0, "nonzero_count": 0, "quantity_sum": 0, "real_model_count": 0},
        )
        stats["row_count"] += 1
        stats["quantity_sum"] += int(item["quantity"] or 0)
        if int(item["quantity"] or 0) != 0:
            stats["nonzero_count"] += 1
        if str(item["model"] or NO_MODEL_TEXT) != NO_MODEL_TEXT:
            stats["real_model_count"] += 1

    record_map = {row["record_id"]: row for row in categories}
    table_df = pd.DataFrame(
        [
            {
                "选择": False,
                "记录ID": row["record_id"],
                "物料品类": row["category"],
                "无需型号": bool(row["no_model"]),
                "启用状态": row["status"],
                "库存行数": summary.get(row["category"], {}).get("row_count", 0),
                "非零库存行": summary.get(row["category"], {}).get("nonzero_count", 0),
                "库存合计": summary.get(row["category"], {}).get("quantity_sum", 0),
                "备注": row["remark"],
            }
            for row in categories
        ]
    )
    metric_col_a, metric_col_b, metric_col_c = st.columns(3)
    metric_col_a.metric("显示品类", f"{len(table_df):,}")
    metric_col_b.metric("非零库存品类", f"{int((table_df['非零库存行'] > 0).sum()):,}")
    metric_col_c.metric("库存合计", f"{int(table_df['库存合计'].sum()):,}")

    edited_df = st.data_editor(
        table_df,
        width="stretch",
        hide_index=True,
        height=420,
        disabled=[column for column in table_df.columns if column != "选择"],
        column_config={"选择": st.column_config.CheckboxColumn("选择")},
        key="category_editor",
    )
    selected_ids = selected_values_from_editor(edited_df)
    selected_records = [record_map[item_id] for item_id in selected_ids if item_id in record_map]

    delete_col_a, delete_col_b, delete_col_c = st.columns([1.5, 1, 1])
    delete_col_a.caption("仅允许撤回所有库存行为 0 且没有流水记录的品类。")
    delete_confirmed = delete_col_b.checkbox("确认批量撤回", key="category_batch_delete_confirmed")
    if delete_col_c.button("批量撤回选中品类", type="primary", width="stretch", key="category_batch_delete_button"):
        if not selected_records:
            st.warning("请先勾选至少一个物料品类。")
        elif not delete_confirmed:
            st.warning("请先勾选确认批量撤回。")
        else:
            blocked: list[str] = []
            for row in selected_records:
                product = str(row["category"])
                stats = summary.get(product, {"nonzero_count": 0})
                tx_count = count_feishu_category_transactions(product)
                if int(stats.get("nonzero_count", 0)) > 0 or tx_count > 0:
                    blocked.append(f"{product}（非零库存行 {stats.get('nonzero_count', 0)}，流水 {tx_count}）")
            if blocked:
                st.error("以下品类不能撤回：" + "；".join(blocked[:8]))
            else:
                with DATA_LOCK:
                    try:
                        for row in selected_records:
                            delete_feishu_category(str(row["category"]), str(row["record_id"]))
                    except Exception as exc:
                        st.error("批量撤回物料品类失败。")
                        st.exception(exc)
                        return
                st.session_state["category_admin_message"] = f"已撤回 {len(selected_records)} 个物料品类。"
                st.cache_data.clear()
                st.rerun()

    if len(selected_records) == 1:
        category = selected_records[0]
        category_id = str(category["record_id"])
        old_product = str(category["category"])
        stats = summary.get(old_product, {"real_model_count": 0})
        existing_category_names = {str(row["category"]) for row in categories if row["record_id"] != category_id}
        inventory_category_names = {str(row["category"]) for row in inventory_records if str(row["category"]) != old_product}
        with st.expander("编辑选中物料品类", expanded=True):
            edit_col_a, edit_col_b = st.columns([2, 1])
            new_product = edit_col_a.text_input("物料品类名称", value=old_product, key=f"edit_category_name_{category_id}")
            no_model = edit_col_b.checkbox("无需型号", value=bool(category["no_model"]), key=f"edit_category_no_model_{category_id}")
            if st.button("保存选中品类修改", type="primary", width="stretch", key=f"save_category_edit_{category_id}"):
                if not new_product.strip():
                    st.error("物料品类名称不能为空。")
                elif no_model and int(stats.get("real_model_count", 0)) > 0:
                    st.error("该品类已有具体产品型号，不能直接改为无需型号。")
                elif new_product.strip() != old_product and (
                    new_product.strip() in existing_category_names or new_product.strip() in inventory_category_names
                ):
                    st.error("新的物料品类名称已经存在。")
                elif count_feishu_category_transactions(old_product) > 0:
                    st.error("该品类已有流水记录。为保证历史可追溯，请先撤回相关库存提交后再修改品类。")
                else:
                    with DATA_LOCK:
                        try:
                            update_feishu_category(old_product, new_product, no_model, category_id)
                        except Exception as exc:
                            st.error("修改物料品类失败。请检查飞书单选字段是否已有对应选项，或改为文本字段。")
                            st.exception(exc)
                            return
                    st.session_state["category_admin_message"] = "物料品类已修改。"
                    st.cache_data.clear()
                    st.rerun()
    elif len(selected_records) > 1:
        st.info("已选择多个品类，可批量撤回；如需编辑，请只勾选一个。")
    else:
        st.caption("勾选一个品类可编辑；勾选多个可批量撤回。")

def render_edit_revert_page() -> None:
    admin_section = st.radio(
        "修改与撤回类型",
        ["提交记录", "库存行", "物料品类"],
        horizontal=True,
        label_visibility="collapsed",
        key="edit_revert_section",
    )
    if admin_section == "提交记录":
        render_transaction_admin()
    elif admin_section == "库存行":
        render_material_data_admin()
    else:
        render_category_admin()


def apply_changes(changes: list[dict[str, object]]) -> None:
    valid_changes = [item for item in changes if int(item["quantity"]) > 0]
    if not valid_changes:
        st.warning("请至少填写一项数量大于 0 的物料。")
        return

    with DATA_LOCK:
        try:
            logs = apply_feishu_changes(valid_changes)
        except Exception as exc:
            st.error("飞书多维表格库存更新失败。请检查应用是否有可编辑权限，关联字段和字段类型是否正确。")
            st.exception(exc)
            return

    st.success(f"已更新 {len(logs)} 项物料库存。")
    st.dataframe(pd.DataFrame(logs, columns=TRANSACTION_HEADERS), width="stretch", hide_index=True)
    st.cache_data.clear()


def request_lines_for_request(
    request: dict[str, object],
    lines: list[dict[str, object]],
) -> list[dict[str, object]]:
    request_id = str(request["record_id"])
    request_no = str(request["request_no"])
    result: list[dict[str, object]] = []
    for line in lines:
        request_ids = [str(item) for item in line.get("request_ids", [])]
        if request_id in request_ids or str(line.get("request_no", "")) == request_no:
            result.append(line)
    return result


def render_approval_view() -> None:
    st.title("营销物料审批与发放")
    if not approval_auth_gate():
        return

    navigate_to_management("approval_back_to_management")
    st.caption("填写实际发放数量并提交后，系统才会扣减物料主数据并写入库存流水。")

    message = st.session_state.pop("approval_issue_message", "")
    if message:
        st.success(message)

    requests = load_feishu_request_records()
    all_lines = load_feishu_request_line_records()
    active_statuses = {
        REQUEST_LINE_STATUS_PENDING,
        "待发放",
        "已通过",
        REQUEST_LINE_STATUS_PARTIAL,
        "",
    }
    active_requests: list[dict[str, object]] = []
    request_line_map: dict[str, list[dict[str, object]]] = {}
    for request in requests:
        request_lines = [
            line
            for line in request_lines_for_request(request, all_lines)
            if str(line.get("status", "")) in active_statuses
        ]
        if request_lines:
            active_requests.append(request)
            request_line_map[str(request["record_id"])] = request_lines

    if not active_requests:
        st.info("暂无待审批或待发放的申请明细。")
        return

    option_labels = [
        (
            f"{request['request_no']} | {request.get('customer_name') or '未填写客户'} | "
            f"{request.get('country') or '未填写国家'} | {request.get('status') or '未设置状态'}"
        )
        for request in active_requests
    ]
    selected_label = st.selectbox("选择申请单", option_labels, key="approval_request_selector")
    selected_index = option_labels.index(selected_label)
    selected_request = active_requests[selected_index]
    selected_lines = request_line_map[str(selected_request["record_id"])]

    detail_col_a, detail_col_b, detail_col_c = st.columns(3)
    detail_col_a.metric("申请单号", str(selected_request["request_no"]))
    detail_col_b.metric("明细数", f"{len(selected_lines):,}")
    detail_col_c.metric("状态", str(selected_request.get("status") or "未设置"))
    st.caption(
        f"客户：{selected_request.get('customer_name') or '-'}；国家：{selected_request.get('country') or '-'}；"
        f"申请人：{selected_request.get('requester') or '-'}；部门：{selected_request.get('department') or '-'}"
    )
    if selected_request.get("material_usage"):
        st.caption(f"物料用途：{selected_request['material_usage']}")
    if selected_request.get("recipient_info"):
        with st.expander("收件人信息"):
            st.write(selected_request["recipient_info"])

    table_df = pd.DataFrame(
        [
            {
                "记录ID": line["record_id"],
                "物料品类": line["product"],
                "产品型号": line["model"],
                "语种": line["language"],
                "申请数量": int(line["quantity"]),
                "当前库存快照": int(line.get("stock_snapshot") or 0),
                "备注": line.get("remark") or line.get("usage", ""),
                "明细状态": line.get("status", ""),
                "实际发放数量": int(line.get("actual_issue_qty") or line.get("quantity") or 0),
            }
            for line in selected_lines
        ]
    )

    with st.form(f"approval_issue_form_{selected_request['record_id']}"):
        edited_df = st.data_editor(
            table_df,
            width="stretch",
            hide_index=True,
            height=360,
            disabled=[column for column in table_df.columns if column != "实际发放数量"],
            column_config={
                "实际发放数量": st.column_config.NumberColumn(
                    "实际发放数量",
                    min_value=0,
                    max_value=1_000_000,
                    step=1,
                )
            },
            key=f"approval_issue_editor_{selected_request['record_id']}",
        )
        issue_note = st.text_input("审批/发放备注", key=f"approval_issue_note_{selected_request['record_id']}")
        submitted = st.form_submit_button("保存实际发放并扣减库存", type="primary", width="stretch")

    if submitted:
        edited_by_id = {str(row["记录ID"]): row for row in edited_df.to_dict("records")}
        issue_lines: list[dict[str, object]] = []
        for line in selected_lines:
            row = edited_by_id.get(str(line["record_id"]))
            if not row:
                continue
            next_line = dict(line)
            next_line["previous_actual_issue_qty"] = int(line.get("actual_issue_qty") or 0)
            next_line["actual_issue_qty"] = int(row.get("实际发放数量") or 0)
            issue_lines.append(next_line)
        with DATA_LOCK:
            try:
                logs = issue_request_lines(selected_request, issue_lines, issue_note)
            except Exception as exc:
                st.error("审批发放失败。请检查实际发放数量、当前库存、申请明细字段和飞书写入权限。")
                st.exception(exc)
                return
        st.cache_data.clear()
        st.session_state["approval_issue_message"] = (
            f"已处理申请单 {selected_request['request_no']}，完成 {len(logs)} 条实际发放。"
        )
        st.rerun()


def render_inventory_view() -> None:
    st.title("实时物料库存表")
    if not auth_gate():
        return

    navigate_to_management("inventory_back_to_management")
    df = load_inventory()
    st.caption(f"当前存储：{storage_mode_label()}。所有领取、采购、新增品类操作都会直接更新当前存储。")
    product_filter, model_filter, language_filter, stocked_filter = st.columns([2.2, 1.6, 1.6, 1])

    selected_products = product_filter.multiselect(
        "物料品类",
        sorted(df[PRODUCT_COL].unique()),
        key="inventory_filter_products",
    )
    product_scoped_df = df[df[PRODUCT_COL].isin(selected_products)] if selected_products else df

    selected_models = model_filter.multiselect(
        "产品型号",
        sorted(product_scoped_df[MODEL_COL].unique()),
        key="inventory_filter_models",
    )
    selected_languages = language_filter.multiselect(
        "语种",
        sort_languages(list(product_scoped_df[LANGUAGE_COL].unique())),
        key="inventory_filter_languages",
    )
    if "inventory_only_stocked" not in st.session_state:
        st.session_state["inventory_only_stocked"] = True
    only_stocked = stocked_filter.checkbox("仅看非零库存", key="inventory_only_stocked")
    filtered = apply_inventory_filters(
        df,
        selected_products=selected_products,
        selected_models=selected_models,
        selected_languages=selected_languages,
        only_stocked=only_stocked,
    )

    if filtered.empty and only_stocked and int((df[QTY_COL] != 0).sum()) == 0:
        st.warning(
            f"当前默认只显示非零库存物料，但应用内库存数量目前全部为 0。"
            f"完整物料组合仍有 {len(df):,} 条，取消“仅看有库存”即可查看。"
        )
        if st.button("显示全部库存组合", key="show_all_inventory_rows", width="stretch"):
            st.session_state["inventory_only_stocked"] = False
            st.rerun()

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("组合总数", f"{len(filtered):,}")
    metric_b.metric("非零库存组合", f"{int((filtered[QTY_COL] != 0).sum()):,}")
    metric_c.metric("库存总数量", f"{int(filtered[QTY_COL].sum()):,}")
    metric_d.metric("库存总价值", f"{float(filtered[VALUE_COL].sum()):,.2f}")

    st.dataframe(filtered, width="stretch", hide_index=True, height=560)
    render_download_center(df, filtered)


def render_cache_page() -> None:
    st.title("数据缓存")
    static_cache = load_static_request_form_cache()
    state = request_form_cache_state()
    live_cache = state.get("data") if isinstance(state.get("data"), dict) else {}

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("静态缓存行数", f"{int(static_cache.get('row_count') or 0):,}")
    metric_b.metric("静态缓存时间", str(static_cache.get("generated_at") or "-"))
    metric_c.metric("后台状态", "同步中" if state.get("refreshing") else "就绪")
    if state.get("error"):
        st.error(str(state["error"]))

    action_a, action_b, action_c = st.columns([1, 1, 1])
    if action_a.button("刷新当前会话缓存", type="primary", width="stretch"):
        with st.spinner("正在同步飞书数据..."):
            try:
                data = refresh_request_form_cache_sync()
            except Exception as exc:
                st.error("刷新失败")
                st.exception(exc)
                return
        st.session_state["request_form_cache_data"] = data
        st.session_state.pop("request_form_cache_locked", None)
        st.success("当前会话缓存已更新。")
    if action_b.button("后台同步一次", width="stretch"):
        start_request_form_cache_refresh()
        st.success("已开始后台同步。")
    if action_c.button("返回登记页", width="stretch"):
        st.query_params.clear()
        st.rerun()

    display_cache = live_cache or static_cache
    st.subheader("当前可用缓存")
    st.caption(
        f"来源：{display_cache.get('source') or '-'}；"
        f"生成时间：{display_cache.get('generated_at') or '-'}；"
        f"物料行：{int(display_cache.get('row_count') or 0):,}"
    )
    rows = list(display_cache.get("inventory_rows") or [])
    if rows:
        preview_df = pd.DataFrame(rows[:200])
        st.dataframe(preview_df, width="stretch", hide_index=True, height=360)
    else:
        st.info("暂无缓存数据。")


def render_management_page() -> None:
    st.title("物料库存管理")
    management_section = st.radio(
        "管理功能",
        ["库存登记", "新增物料品类", "修改与撤回"],
        horizontal=True,
        label_visibility="collapsed",
        key="management_section",
    )
    if management_section == "库存登记":
        render_change_form(show_title=False)
    elif management_section == "新增物料品类":
        render_add_category_form()
    else:
        render_edit_revert_page()


def main() -> None:
    st.set_page_config(page_title="物料库存管理", layout="wide")
    inject_global_styles()
    stop_on_invalid_feishu_config()
    render_sidebar_link()
    render_storage_diagnostics()

    view = st.query_params.get("view", "")
    try:
        if view == "inventory":
            render_inventory_view()
        elif view == "approval":
            render_approval_view()
        elif view == "cache":
            render_cache_page()
        else:
            render_management_page()
    except FeishuBitableError as exc:
        render_feishu_error(exc)


if __name__ == "__main__":
    main()
