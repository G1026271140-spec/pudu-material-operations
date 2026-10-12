from __future__ import annotations

import base64
import json
import hashlib
import hmac
import os
import re
import threading
import time
import unicodedata
import uuid
from collections import Counter
from collections.abc import MutableMapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from html import escape
from io import BytesIO
from pathlib import Path
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

import pandas as pd
import streamlit as st
from feishu_bitable import FeishuBitableClient, FeishuBitableConfig, FeishuBitableError
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo
from shipping_page import render_shipping_template_page
from project_config import get_setting
from live_cache import read_manifest, resolve_cache_path
from submission_queue import (
    SUBMISSION_QUEUE_MODULE_VERSION,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_FAILED,
    QUEUE_TASK_TYPE_CATEGORY_DELETE,
    QUEUE_TASK_TYPE_CATEGORY_SYNC,
    QUEUE_TASK_TYPE_CULTURAL_REQUEST,
    QUEUE_TASK_TYPE_CULTURAL_REQUEST_REJECT,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST,
    QUEUE_TASK_TYPE_CORPORATE_APPAREL_REQUEST_REJECT,
    QUEUE_TASK_TYPE_CULTURAL_MANAGEMENT,
    QUEUE_TASK_TYPE_GIFT_PROJECT,
    QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT,
    QUEUE_TASK_TYPE_MATERIAL_REQUEST,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,
    QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT,
    QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER,
    QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW,
    QUEUE_TASK_TYPE_RESTOCK,
    QUEUE_TASK_TYPE_TRANSACTION_REPLACE,
    QUEUE_TASK_TYPE_TRANSACTION_REVERT,
    SubmissionTask,
    enqueue_submission_task,
    ensure_submission_queue_table,
    find_task_by_idempotency_key,
)
from ui_i18n import (
    LANGUAGE_EN,
    LANGUAGE_ZH,
    SUPPORTED_UI_LANGUAGES,
    install_streamlit_ui_translation,
    normalize_ui_language,
    translate_ui_text,
)


class _AppRuntimeProxy:
    """Resolve app APIs from this script without relying on Streamlit's module name."""

    def __getattr__(self, name: str) -> object:
        try:
            return globals()[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


APP_RUNTIME = _AppRuntimeProxy()


DEFAULT_PASSWORD = "376493"
DEFAULT_APPROVAL_PASSWORD = "pd123456"
# 提交版本逐次递增；V0.9.9 的下一版进位为 V1.0.0，不使用 V0.9.10。
APP_VERSION = "V3.1.9"
REQUIRED_SUBMISSION_QUEUE_MODULE_VERSION = 2
if SUBMISSION_QUEUE_MODULE_VERSION != REQUIRED_SUBMISSION_QUEUE_MODULE_VERSION:
    raise RuntimeError(
        "后台队列模块版本不一致，请重新部署完整应用版本。"
    )
NO_MODEL_TEXT = "无需型号"
NO_LANGUAGE_TEXT = "无需语种"
MODEL_TYPE_FIELD = "型号类型"
MODEL_TYPE_REGULAR = "普通物料"
MODEL_TYPE_CULTURAL = "文化周边"
MODEL_TYPE_OPTIONS = (MODEL_TYPE_REGULAR, MODEL_TYPE_CULTURAL)
DEFAULT_NO_LANGUAGE_PRODUCTS = (
    "公仔(Plush Toy)",
    "开瓶器&冰箱贴(Bottle Opener & Fridge Magnet)",
    "笔记本礼盒(Notebook Gift Box)",
    "定制LOGO书包(Customized PUDU bag)",
    "展会服装",
)
ACTION_RECEIVE = "物料领取（减少库存）"
ACTION_PURCHASE = "物料采购（增加库存）"
ACTION_OPTIONS = [ACTION_RECEIVE, ACTION_PURCHASE]
DECREASE_ACTIONS = {ACTION_RECEIVE, "出库减少"}
INCREASE_ACTIONS = {ACTION_PURCHASE, "入库增加"}
REQUEST_TABLE_NAME = str(get_setting("feishu.tables.request", "物料申请单"))
REQUEST_LINE_TABLE_NAME = str(get_setting("feishu.tables.request_line", "申请明细"))
REQUEST_CHANGE_TABLE_NAME = str(get_setting("feishu.tables.request_change", "申请物料变更记录表"))
MATERIAL_TABLE_NAME = str(get_setting("feishu.tables.material", "物料主数据"))
CATEGORY_TABLE_NAME = str(get_setting("feishu.tables.category", "物料品类"))
MODEL_TABLE_NAME = str(get_setting("feishu.tables.model", "产品型号"))
LANGUAGE_TABLE_NAME = str(get_setting("feishu.tables.language", "物料语种"))
LEDGER_TABLE_NAME = str(get_setting("feishu.tables.ledger", "库存流水"))
USER_PERMISSION_TABLE_NAME = str(get_setting("feishu.tables.user_permission", "用户权限表"))
GIFT_PROJECT_TABLE_NAME = str(get_setting("feishu.tables.gift_project", "项目周边礼品物料筹备详情list"))
CULTURAL_MATERIAL_TABLE_NAME = str(get_setting("feishu.tables.cultural_material", "文化周边管理库存"))
CORPORATE_APPAREL_TABLE_NAME = str(
    get_setting("feishu.tables.corporate_apparel", "文化周边编码及库存数量")
)
CORPORATE_APPAREL_SOURCE_TABLE_ID = str(
    get_setting("feishu.tables.corporate_apparel_source_table_id", "tbledtC3RafsHNh0")
)
CULTURAL_CLAIMABLE_FIELD = "是否可以申领"
CULTURAL_CLAIMABLE_YES = "是"
CULTURAL_CLAIMABLE_NO = "否"
REGION_TABLE_NAME = str(get_setting("feishu.tables.region", "战区管理"))
MODEL_LINK_FIELD_CANDIDATES = ("型号关联", "产品型号 2")
LANGUAGE_LINK_FIELD_CANDIDATES = ("语种关联", "物料语种", "语言种类 2")
AUTO_REQUEST_MODEL_CATEGORIES = (
    "产品单页(Product Flyer )",
    "产品易拉宝(Product Roll-Up)",
)
UNIT_PRICE_FIELD_CANDIDATES = ("单价（美元）", "单价")
UNIT_PRICE_RMB_FIELD = "单价（人民币）"
REQUEST_PRICE_SNAPSHOT_FIELD = "申请时单价（人民币）"
REQUEST_LINE_SUBTOTAL_FIELD = "费用小计（人民币）"
REQUEST_TOTAL_RMB_FIELD = "费用合计（人民币）"
GIFT_PROJECT_CATEGORY_LINK_FIELD = "物料品类关联"
COMMERCIAL_INVOICE_NAME_FIELD = "商业发票产品名称"
PACKING_LIST_PRODUCT_TYPE_FIELD = "装箱单产品类型"
PACKING_LIST_PRODUCT_TYPE_OPTIONS = ("Flyers", "Brochures", "Banners", "Give aways")
STATUS_ACTIVE = "启用"
STATUS_INACTIVE = "停用"
MATERIAL_STATUS_OPTIONS = (STATUS_ACTIVE, STATUS_INACTIVE)
CATEGORY_DEFINITION_PRINT = "印刷物料"
CATEGORY_DEFINITION_GIFT = "周边礼品"
CATEGORY_DEFINITION_CULTURAL = "文化周边"
CATEGORY_DEFINITION_OPTIONS = (
    CATEGORY_DEFINITION_PRINT,
    CATEGORY_DEFINITION_GIFT,
    CATEGORY_DEFINITION_CULTURAL,
)
UNDEFINED_CATEGORY_DEFINITION = "未定义"
GIFT_PROJECT_STATUS_REQUESTED = "已提需"
INVENTORY_ZERO_SINCE_FIELD = "库存归零时间"
INVENTORY_AUTO_DISABLE_DAYS = int(get_setting("runtime.inventory_auto_disable_days", 14))
CATEGORY_CREATE_STAGE_KEY = "category_create_stage"
CATEGORY_CREATE_DRAFT_KEY = "category_create_draft"
CATEGORY_EDIT_STAGE_KEY = "category_edit_stage"
CATEGORY_EDIT_DRAFT_KEY = "category_edit_draft"
CATEGORY_DELETE_STAGE_KEY = "category_delete_stage"
CATEGORY_DELETE_DRAFT_KEY = "category_delete_draft"
REQUEST_NO_PREFIX = "REQ"
RESTOCK_NO_PREFIX = "RST"
REQUEST_FORM_TITLE = "MKT营销物料领取流程(MKT Marketing Materials Collecting Process)"
REQUEST_STATUS_PENDING = "待审批"
REQUEST_STATUS_WITHDRAWN = "已撤回"
REQUEST_LINE_STATUS_PENDING = "待审批"
REQUEST_LINE_STATUS_WITHDRAWN = "已撤回"
INVENTORY_REVIEW_PENDING = "待核实库存"
INVENTORY_REVIEW_EDITING = "编辑处理中"
INVENTORY_REVIEW_CONFIRMED = "已核实库存"
INVENTORY_REVIEW_REMINDER_AT_FIELD = "计划库存核实时间"
INVENTORY_REVIEW_REMINDER_STATUS_FIELD = "库存核实提醒状态"
INVENTORY_REVIEW_LAST_REMINDER_FIELD_CANDIDATES = (
    "库存核实最后提醒时间",
    "库存合适最后提醒时间",
)
INVENTORY_REVIEW_REMINDER_PENDING = "待提醒"
INVENTORY_REVIEW_REMINDER_SENT = "已提醒"
INVENTORY_REVIEW_REMINDER_NONE = "无需提醒"
INVENTORY_RESULT_SUFFICIENT = "库存充足"
INVENTORY_RESULT_PARTIAL = "部分库存不足"
INVENTORY_RESULT_INSUFFICIENT = "全部库存不足"
DEFAULT_STREAMLIT_APP_URL = str(
    get_setting(
        "deployment.streamlit_app_url",
        "https://pudu-material-inventory-ndgbxrpkkrzgkbapvhzvix.streamlit.app/",
    )
)
DEFAULT_LOCAL_APP_URL = str(
    get_setting(
        "deployment.custom_domain",
        "https://pudu-material-operations.gaohongyuan.me/",
    )
)
FREIGHT_PAYER_OPTIONS = [
    "申请部门承担",
    "市场部承担",
    "客户承担",
    "普渡付款(PUDU)",
    "其他",
]
DEFAULT_FREIGHT_PAYER = "普渡付款(PUDU)"
REQUEST_MANUAL_PRODUCT_ORDER = (
    "工业产品线手册IR",
    "清洁产品线手册CR",
    "配送线产品手册DR",
    "具身线产品手册ER",
)
GITHUB_REPOSITORY = str(get_setting("project.github_repository", "G1026271140-spec/pudu-material-operations"))
GITHUB_CACHE_WORKFLOW_FILE = str(get_setting("project.cache_workflow_file", "refresh-static-cache.yml"))
GITHUB_CACHE_WORKFLOW_URL = (
    f"https://github.com/{GITHUB_REPOSITORY}/actions/workflows/{GITHUB_CACHE_WORKFLOW_FILE}"
)

CATEGORY_OPTION_POOL = st.components.v2.component(
    "category_option_pool",
    html='<div class="option-pool" role="listbox"></div>',
    css="""
        .option-pool {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            width: 100%;
            padding: 2px 0 6px;
        }
        .option-pool.is-grouped {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            align-items: start;
            gap: 8px;
        }
        .option-group {
            min-width: 0;
            padding: 7px;
            border: 1px solid color-mix(in srgb, var(--st-text-color) 16%, transparent);
            border-radius: 6px;
            background: color-mix(in srgb, var(--st-secondary-background-color) 74%, transparent);
        }
        .option-group-title {
            margin: 0 0 5px;
            color: color-mix(in srgb, var(--st-text-color) 78%, transparent);
            font-size: 12px;
            font-weight: 700;
        }
        .option-group-items {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }
        .option-group-empty {
            color: color-mix(in srgb, var(--st-text-color) 52%, transparent);
            font-size: 11px;
        }
        .option-item {
            display: inline-flex;
            align-items: center;
            min-height: 38px;
            max-width: 100%;
            padding: 0;
            overflow: hidden;
            color: var(--st-text-color);
            background: var(--st-secondary-background-color);
            border: 1px solid color-mix(in srgb, var(--st-text-color) 20%, transparent);
            border-radius: 7px;
        }
        .option-item.is-selected {
            color: #ffffff;
            background: #13758a;
            border-color: #0d5f70;
            box-shadow: inset 0 0 0 1px #0d5f70, 0 2px 6px rgba(13, 95, 112, 0.24);
        }
        .option-pool.is-danger .option-item.is-selected {
            color: #ffffff;
            background: #c93648;
            border-color: #a92535;
            box-shadow: inset 0 0 0 1px #a92535, 0 2px 6px rgba(169, 37, 53, 0.24);
        }
        .option-main,
        .option-edit {
            min-height: 38px;
            color: inherit;
            background: transparent;
            border: 0;
            cursor: pointer;
        }
        .option-main {
            min-width: 0;
            padding: 7px 11px;
            font: inherit;
            font-weight: 650;
            text-align: left;
            overflow-wrap: anywhere;
        }
        .option-item.is-selected .option-main::before {
            content: '✓';
            display: inline-block;
            margin-right: 7px;
            font-weight: 800;
        }
        .option-edit {
            width: 36px;
            flex: 0 0 36px;
            border-left: 1px solid color-mix(in srgb, currentColor 18%, transparent);
            font-size: 17px;
        }
        .option-main:hover,
        .option-edit:hover {
            background: color-mix(in srgb, currentColor 7%, transparent);
        }
        .option-meta {
            display: block;
            margin-top: 1px;
            color: color-mix(in srgb, currentColor 70%, transparent);
            font-size: 12px;
            font-weight: 450;
        }
        .option-pool.is-compact {
            gap: 5px;
            padding: 0 0 3px;
        }
        .option-pool.is-compact .option-item {
            min-height: 29px;
            border-radius: 5px;
        }
        .option-pool.is-compact .option-main,
        .option-pool.is-compact .option-edit {
            min-height: 29px;
        }
        .option-pool.is-compact .option-main {
            padding: 4px 7px;
            font-size: 12px;
            line-height: 1.18;
        }
        .option-pool.is-compact .option-item.is-selected .option-main::before {
            margin-right: 4px;
        }
        .option-pool.is-compact .option-meta {
            display: inline;
            margin: 0 0 0 5px;
            font-size: 10px;
        }
        @media (max-width: 760px) {
            .option-pool.is-grouped {
                grid-template-columns: 1fr;
            }
        }
    """,
    js="""
        export default function(component) {
            const { data, parentElement, setStateValue, setTriggerValue } = component;
            const root = parentElement.querySelector('.option-pool');
            root.innerHTML = '';
            root.classList.toggle('is-danger', Boolean(data.danger));
            root.classList.toggle('is-compact', Boolean(data.compact));
            root.classList.toggle('is-grouped', Boolean(data.grouped));
            const selected = data.multi
                ? new Set(Array.isArray(data.selected) ? data.selected : [])
                : new Set(data.selected ? [data.selected] : []);
            let clickTimer = null;

            const syncSelectionStyles = () => {
                for (const item of root.querySelectorAll('.option-item')) {
                    const isSelected = selected.has(item.dataset.value);
                    item.classList.toggle('is-selected', isSelected);
                    item.setAttribute('aria-selected', isSelected ? 'true' : 'false');
                }
            };

            const commitSelection = (value) => {
                if (data.multi) {
                    if (selected.has(value)) selected.delete(value);
                    else selected.add(value);
                    syncSelectionStyles();
                    setStateValue('selected', Array.from(selected));
                } else {
                    selected.clear();
                    selected.add(value);
                    syncSelectionStyles();
                    setStateValue('selected', value);
                }
            };

            const renderOption = (target, option) => {
                const item = document.createElement('div');
                item.className = 'option-item';
                item.dataset.value = option.value;
                item.classList.toggle('is-selected', selected.has(option.value));
                item.setAttribute('role', 'option');
                item.setAttribute('aria-selected', selected.has(option.value) ? 'true' : 'false');

                const main = document.createElement('button');
                main.type = 'button';
                main.className = 'option-main';
                main.innerHTML = `<span>${option.label}</span>${option.meta ? `<span class="option-meta">${option.meta}</span>` : ''}`;
                if (data.editable) {
                    main.onclick = () => {
                        clickTimer = window.setTimeout(() => commitSelection(option.value), 230);
                    };
                    main.ondblclick = (event) => {
                        event.preventDefault();
                        if (clickTimer) window.clearTimeout(clickTimer);
                        setStateValue('selected', data.multi ? [option.value] : option.value);
                        setTriggerValue('edit', option.value);
                    };
                } else {
                    main.onclick = () => commitSelection(option.value);
                }
                item.appendChild(main);

                if (data.editable) {
                    const edit = document.createElement('button');
                    edit.type = 'button';
                    edit.className = 'option-edit';
                    edit.setAttribute('aria-label', `编辑 ${option.label}`);
                    edit.title = `编辑 ${option.label}`;
                    edit.textContent = '✎';
                    edit.onclick = () => {
                        if (clickTimer) window.clearTimeout(clickTimer);
                        setStateValue('selected', option.value);
                        setTriggerValue('edit', option.value);
                    };
                    item.appendChild(edit);
                }
                target.appendChild(item);
            };

            if (data.grouped) {
                const groupedOptions = new Map();
                for (const option of data.options || []) {
                    const groupName = option.group || '其他';
                    if (!groupedOptions.has(groupName)) groupedOptions.set(groupName, []);
                    groupedOptions.get(groupName).push(option);
                }
                const configuredOrder = Array.isArray(data.group_order) ? data.group_order : [];
                const groupNames = [
                    ...configuredOrder,
                    ...Array.from(groupedOptions.keys()).filter((name) => !configuredOrder.includes(name)),
                ];
                for (const groupName of groupNames) {
                    const groupOptions = groupedOptions.get(groupName) || [];
                    const group = document.createElement('section');
                    group.className = 'option-group';
                    const title = document.createElement('div');
                    title.className = 'option-group-title';
                    title.textContent = `${groupName} · ${groupOptions.length}`;
                    group.appendChild(title);
                    const items = document.createElement('div');
                    items.className = 'option-group-items';
                    if (groupOptions.length) {
                        for (const option of groupOptions) renderOption(items, option);
                    } else {
                        const empty = document.createElement('div');
                        empty.className = 'option-group-empty';
                        empty.textContent = '暂无选项';
                        items.appendChild(empty);
                    }
                    group.appendChild(items);
                    root.appendChild(group);
                }
            } else {
                for (const option of data.options || []) renderOption(root, option);
            }
            return () => {
                if (clickTimer) window.clearTimeout(clickTimer);
            };
        }
    """,
)
INVENTORY_QUERY_URL = (
    "https://pudutech.feishu.cn/wiki/G7vbwubTbiagPokSvAiceK8AnZc"
    "?table=blkR84ObPdrZr82Y"
)

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
DATA_CACHE_TTL_SECONDS = int(get_setting("runtime.data_cache_ttl_seconds", 30))
MAX_RESTOCK_LINE_COUNT = 20
MAX_CULTURAL_REQUEST_LINE_COUNT = 20
ADMIN_MANAGEMENT_SECTIONS = frozenset({"物料管理"})
MANAGEMENT_NAVIGATION_KEY = "management_section"
MANAGEMENT_NAVIGATION_LOADING_KEY = "management_navigation_loading"
FULLSCREEN_SYNC_IN_PROGRESS_KEY = "_fullscreen_sync_in_progress"
MANAGEMENT_WORKBENCH_CONTROL_KEY = "management_section_control"
MANAGEMENT_WORKBENCH_SECTIONS = ("库存登记",)
MATERIAL_MANAGEMENT_CONTROL_KEY = "material_management_section"
MATERIAL_MANAGEMENT_SECTIONS = (
    "采购补库",
    "品类管理",
    "型号管理",
    "语种管理",
    "战区管理",
    "仓库位置",
    "发货模板",
    "下单排期管理",
    "项目礼品管理",
)
MATERIAL_DASHBOARD_MODULES = (
    "概览指标",
    "品类库存数量",
    "品类库存价值",
    "语种分布",
    "库存预警",
)
MATERIAL_STOCK_STATUSES = ("负库存", "零库存", "低库存", "正常库存")
DEFAULT_LOW_STOCK_THRESHOLD = int(get_setting("runtime.default_low_stock_threshold", 100))
UI_LANGUAGE_SESSION_KEY = "ui_language"
UI_LANGUAGE_QUERY_SESSION_KEY = "ui_language_query_value"
REQUEST_CONTACT_USER_LOOKUP_KEY = "_request_contact_user_by_id"
REQUEST_FORM_CACHE_SCHEMA_VERSION = 6
REQUEST_PAGE_VISIBILITY_FIELD = "是否在申领页显示"
REQUEST_CATEGORY_IMAGE_FIELD = "申领页图片"
REQUEST_PAGE_VISIBLE_VALUE = "是"
REQUEST_PAGE_HIDDEN_VALUE = "否"
REQUEST_PAGE_VISIBILITY_OPTIONS = (REQUEST_PAGE_VISIBLE_VALUE, REQUEST_PAGE_HIDDEN_VALUE)
PRIMARY_MODEL_PRODUCT_LINES = ("IR", "CR", "SR", "GR")
REQUEST_FORM_STATIC_CACHE_PATH = Path(__file__).resolve().parent / "data" / "request_form_cache.json"
PAGE_DATA_STATIC_CACHE_PATH = Path(__file__).resolve().parent / "data" / "page_data_cache.json"
WAREHOUSE_LOCATION_CACHE_PATH = (
    Path(__file__).resolve().parent / "data" / "warehouse_location_cache.json"
)
CONTACT_DEPARTMENT_STATIC_CACHE_PATH = (
    Path(__file__).resolve().parent / "data" / "contact_departments_cache.json"
)
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "app-icon.png"
PUDU_BLUE_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "pudu-logo-blue.png"
REQUEST_CATEGORY_IMAGE_DIR = (
    Path(__file__).resolve().parent / "assets" / "request_categories"
)
REQUEST_FORM_CACHE_LOCK = threading.Lock()
REQUEST_FORM_CACHE_STATE: dict[str, object] = {
    "data": None,
    "refreshing": False,
    "error": "",
    "updated_at": "",
}
ALL_PAGE_CACHE_TABLES = (
    CATEGORY_TABLE_NAME,
    MODEL_TABLE_NAME,
    LANGUAGE_TABLE_NAME,
    MATERIAL_TABLE_NAME,
    LEDGER_TABLE_NAME,
    REQUEST_TABLE_NAME,
    REQUEST_LINE_TABLE_NAME,
    GIFT_PROJECT_TABLE_NAME,
    CULTURAL_MATERIAL_TABLE_NAME,
    CORPORATE_APPAREL_TABLE_NAME,
    REGION_TABLE_NAME,
    USER_PERMISSION_TABLE_NAME,
    "物料下单批次",
    "物料下单批次明细",
)
REQUEST_FORM_CACHE_TABLES = (
    CATEGORY_TABLE_NAME,
    MODEL_TABLE_NAME,
    LANGUAGE_TABLE_NAME,
    MATERIAL_TABLE_NAME,
)
PAGE_CACHE_TABLES = {
    "request": REQUEST_FORM_CACHE_TABLES,
    "restock": (CATEGORY_TABLE_NAME, MODEL_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME),
    "category": (CATEGORY_TABLE_NAME, MODEL_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME),
    "model_management": (MODEL_TABLE_NAME, MATERIAL_TABLE_NAME),
    "language_management": (LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME),
    "maintenance": ALL_PAGE_CACHE_TABLES,
    "inventory": (CATEGORY_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME),
    "gift_projects": (CATEGORY_TABLE_NAME, MATERIAL_TABLE_NAME, GIFT_PROJECT_TABLE_NAME),
    "cultural_request": (
        CATEGORY_TABLE_NAME,
        MODEL_TABLE_NAME,
        CULTURAL_MATERIAL_TABLE_NAME,
        REGION_TABLE_NAME,
    ),
    "shipping": (CATEGORY_TABLE_NAME,),
    "order_scheduling": (REQUEST_TABLE_NAME, REQUEST_LINE_TABLE_NAME, MATERIAL_TABLE_NAME,
                         CATEGORY_TABLE_NAME, MODEL_TABLE_NAME, LANGUAGE_TABLE_NAME,
                         USER_PERMISSION_TABLE_NAME, "物料下单批次", "物料下单批次明细"),
}
OPTIONAL_PAGE_CACHE_TABLES = {LANGUAGE_TABLE_NAME}
def page_update_session_key(page_key: str, suffix: str) -> str:
    return f"page_update_{page_key}_{suffix}"


def get_ui_language() -> str:
    try:
        return normalize_ui_language(st.session_state.get(UI_LANGUAGE_SESSION_KEY, LANGUAGE_ZH))
    except (AttributeError, KeyError):
        return LANGUAGE_ZH


def apply_ui_language_from_query() -> str:
    """Apply a stable URL language without overriding later in-page changes."""
    requested = str(st.query_params.get("lang", "")).strip().casefold()
    if requested not in SUPPORTED_UI_LANGUAGES:
        return ""
    if st.session_state.get(UI_LANGUAGE_QUERY_SESSION_KEY) != requested:
        st.session_state[UI_LANGUAGE_SESSION_KEY] = requested
        st.session_state["request_mobile_ui_language"] = requested
        st.session_state[UI_LANGUAGE_QUERY_SESSION_KEY] = requested
    return requested


def ui_text(value: object) -> str:
    return str(translate_ui_text(value, get_ui_language()))


def data_submission_success_message() -> str:
    if get_ui_language() == LANGUAGE_EN:
        return (
            "Data submitted successfully. Please follow the Feishu approval progress. "
            "Thank you for using this application."
        )
    return "数据提交成功，请您关注飞书审批进度，感谢您的使用。"


def request_option_display_label(value: object) -> str:
    text = str(value or "").strip()
    if get_ui_language() != LANGUAGE_EN:
        return text
    english_parts = re.findall(r"[（(]([^()（）]*[A-Za-z][^()（）]*)[）)]", text)
    if english_parts:
        return english_parts[-1].strip()
    return str(translate_ui_text(text, LANGUAGE_EN))


def normalize_model_display_names(value: object) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    for model, labels in dict(value or {}).items():
        canonical = str(model or "").strip()
        if not canonical or not isinstance(labels, dict):
            continue
        normalized[canonical] = {
            LANGUAGE_ZH: str(labels.get(LANGUAGE_ZH) or labels.get("zh") or canonical).strip(),
            LANGUAGE_EN: str(labels.get(LANGUAGE_EN) or labels.get("en") or canonical).strip(),
        }
    return normalized


def request_model_display_label(
    value: object,
    model_display_names: object | None = None,
    language: str | None = None,
) -> str:
    canonical = str(value or "").strip() or NO_MODEL_TEXT
    labels = normalize_model_display_names(
        model_display_names
        if model_display_names is not None
        else load_static_request_form_cache().get("model_display_names", {})
    ).get(canonical, {})
    target_language = normalize_ui_language(language or get_ui_language())
    return str(labels.get(target_language) or canonical)


def normalize_category_display_names(value: object) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    for category, labels in dict(value or {}).items():
        canonical = str(category or "").strip()
        if not canonical or not isinstance(labels, dict):
            continue
        normalized[canonical] = {
            LANGUAGE_ZH: str(labels.get(LANGUAGE_ZH) or labels.get("zh") or "").strip(),
            LANGUAGE_EN: str(labels.get(LANGUAGE_EN) or labels.get("en") or "").strip(),
        }
    return normalized


def request_category_display_label(
    value: object,
    category_display_names: object | None = None,
    language: str | None = None,
) -> str:
    canonical = str(value or "").strip()
    target_language = normalize_ui_language(language or get_ui_language())
    labels = normalize_category_display_names(
        category_display_names
        if category_display_names is not None
        else load_static_request_form_cache().get("category_display_names", {})
    ).get(canonical, {})
    configured_label = str(labels.get(target_language) or "").strip()
    if configured_label and configured_label != canonical:
        return configured_label
    if target_language == LANGUAGE_EN:
        return request_option_display_label(canonical)
    chinese_label = re.split(r"[（(]", canonical, maxsplit=1)[0].strip()
    return chinese_label or canonical


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --pudu-ink: #172A3D;
            --pudu-muted: #5B6975;
            --pudu-subtle: #7F8C96;
            --pudu-line: #D6E0E6;
            --pudu-control-line: #BBC9D2;
            --pudu-line-soft: #E6ECEF;
            --pudu-panel: #FFFFFF;
            --pudu-canvas: #F4F7F8;
            --pudu-blue: #174C7A;
            --pudu-blue-hover: #103B62;
            --pudu-blue-soft: #EAF2F8;
            --pudu-navy: #123E6D;
            --pudu-navy-soft: #EDF4F9;
            --pudu-teal: #167F83;
            --pudu-teal-soft: #EAF7F5;
            --pudu-coral: #EF6648;
            --pudu-coral-soft: #FFF1EC;
            --pudu-gold: #D99528;
            --pudu-gold-soft: #FFF7E7;
            --pudu-green: #20A162;
            --pudu-amber: #B86B13;
            --pudu-red: #C83F32;
            --pudu-required-bg: #FFF5F4;
            --pudu-required-line: #E5A29B;
            --pudu-required-focus: #C95A50;
        }
        html, body, [class*="css"] {
            font-family: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            letter-spacing: 0;
        }
        html, body {
            background: var(--pudu-canvas) !important;
            color-scheme: light;
        }
        .stApp {
            background: var(--pudu-canvas);
            color: var(--pudu-ink);
        }
        [data-testid="stAppViewContainer"] {
            background: var(--pudu-canvas);
        }
        [data-testid="stAppViewContainer"] [data-stale="true"],
        [data-testid="stAppViewContainer"] .stale {
            opacity: 1 !important;
            filter: none !important;
        }
        [data-testid="stHeader"] {
            height: 0;
            min-height: 0;
            background: transparent;
            border: 0;
            box-shadow: none;
            pointer-events: none;
        }
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarCollapseButton"] {
            position: fixed !important;
            top: 50vh !important;
            left: 12px !important;
            z-index: 1001 !important;
            width: 52px !important;
            transform: translateY(-50%) !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto;
        }
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarCollapseButton"] button {
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
        }
        [data-testid="stSidebarCollapseButton"] button {
            width: 44px;
            height: 44px;
            min-width: 44px;
            min-height: 44px;
            padding: 0 !important;
            border: 1px solid var(--pudu-line) !important;
            border-radius: 10px !important;
            background: rgba(255, 255, 255, 0.96) !important;
            color: var(--pudu-navy) !important;
            box-shadow: 0 2px 8px rgba(31, 35, 41, 0.12) !important;
        }
        [data-testid="stSidebarCollapseButton"] button svg {
            width: 22px !important;
            height: 22px !important;
        }
        [data-testid="stSidebarCollapseButton"] button:hover {
            border-color: #9FB8CB !important;
            background: var(--pudu-blue-soft) !important;
        }
        [data-testid="stMainBlockContainer"] {
            width: 100%;
            max-width: none;
            padding: 0.65rem 2.25rem 4rem;
        }
        h1, h2, h3 {
            color: var(--pudu-ink);
            font-weight: 650;
            letter-spacing: 0;
        }
        h1 { font-size: 1.875rem; line-height: 1.3; }
        h2 { font-size: 1.375rem; line-height: 1.4; }
        h3 { font-size: 1.125rem; line-height: 1.45; }
        p, label, [data-testid="stCaptionContainer"] {
            letter-spacing: 0;
        }
        [data-testid="stSidebar"] {
            background: #F6F9FA;
            border-right: 1px solid var(--pudu-line);
        }
        [data-testid="stSidebar"][aria-expanded="true"] {
            width: 260px !important;
            min-width: 260px !important;
            max-width: 260px !important;
        }
        [data-testid="stSidebar"] * {
            color: var(--pudu-ink);
        }
        [data-testid="stSidebar"] .stCaption {
            color: var(--pudu-muted);
        }
        [data-testid="stSidebarContent"] {
            padding-top: 0;
        }
        [data-testid="stSidebarUserContent"] {
            padding-top: 0.25rem !important;
        }
        [data-testid="stSidebar"] hr {
            margin: 1rem 0;
            border-color: var(--pudu-line-soft);
        }
        [data-testid="stSidebar"] .stButton > button,
        [data-testid="stSidebar"] [data-testid="stLinkButton"] > a {
            justify-content: flex-start;
            min-height: 36px;
            padding: 0 0.6rem;
            font-size: 0.78rem;
            background: #FFFFFF;
            border: 1px solid var(--pudu-line);
            color: var(--pudu-ink);
            box-shadow: none;
            transition: transform 180ms ease, background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
        }
        [data-testid="stSidebar"] .stButton > button:hover,
        [data-testid="stSidebar"] [data-testid="stLinkButton"] > a:hover {
            background: var(--pudu-blue-soft);
            border-color: #9FB8CB;
            color: var(--pudu-blue);
            transform: scale(1.025);
            box-shadow: 0 5px 14px rgba(24, 66, 92, 0.12);
        }
        .st-key-sidebar_cache_publish [data-testid="stLinkButton"] > a,
        .st-key-sidebar_cache_publish .stButton > button {
            justify-content: center !important;
            text-align: center !important;
        }
        .st-key-sidebar_cache_publish [data-testid="stExpander"] summary > span {
            justify-content: center !important;
        }
        .st-key-sidebar_open_request button {
            border-left: 3px solid var(--pudu-navy) !important;
        }
        .st-key-sidebar_open_material_management button {
            border-left: 3px solid var(--pudu-teal) !important;
        }
        .st-key-sidebar_inventory_query [data-testid="stLinkButton"] > a {
            border-left: 3px solid var(--pudu-gold) !important;
        }
        .st-key-sidebar_open_category button {
            border-left: 3px solid var(--pudu-gold) !important;
        }
        .st-key-sidebar_open_request button:disabled {
            background: var(--pudu-navy-soft) !important;
            color: var(--pudu-navy) !important;
            opacity: 1;
        }
        .st-key-sidebar_open_material_management button:disabled {
            background: var(--pudu-teal-soft) !important;
            color: #116A6E !important;
            opacity: 1;
        }
        .st-key-sidebar_open_category button:disabled {
            background: var(--pudu-gold-soft) !important;
            color: #8A5B13 !important;
            opacity: 1;
        }
        .st-key-sidebar_brand {
            margin-bottom: 0.65rem;
            padding: 0 0 0.65rem;
            border-bottom: 1px solid var(--pudu-line);
        }
        .st-key-sidebar_corporate_logo {
            position: fixed;
            top: 10px;
            left: 24px;
            z-index: 1002;
            width: 64px;
            height: 42px;
            margin: 0;
            overflow: hidden;
            pointer-events: none;
        }
        .st-key-sidebar_corporate_logo [data-testid="stImage"] {
            width: 64px;
            height: 42px;
            margin: 0;
            overflow: hidden;
        }
        .st-key-sidebar_corporate_logo [data-testid="stImage"] img {
            width: 98px !important;
            max-width: none !important;
            height: auto !important;
            transform: translateX(-17px);
            object-fit: contain;
        }
        [data-testid="stSidebar"][aria-expanded="false"] .st-key-sidebar_corporate_logo {
            display: none !important;
        }
        .st-key-sidebar_brand [data-testid="stImage"] {
            width: 64px;
            padding: 2px;
            border: 1px solid #C9D8E0;
            border-radius: 8px;
            background: #FFFFFF;
            overflow: hidden;
        }
        .st-key-sidebar_brand [data-testid="stImage"] img {
            width: 58px !important;
            height: 58px !important;
            object-fit: cover;
        }
        .pudu-brand-name {
            color: var(--pudu-ink) !important;
            font-size: 0.86rem;
            font-weight: 680;
            line-height: 1.35;
        }
        .pudu-brand-subtitle {
            color: var(--pudu-muted) !important;
            font-size: 0.66rem;
            margin-top: 0.1rem;
        }
        .pudu-sidebar-label {
            color: var(--pudu-subtle) !important;
            font-size: 0.66rem;
            font-weight: 650;
            margin: 0.15rem 0 0.5rem;
            text-transform: uppercase;
        }
        .st-key-sidebar_data_system_group {
            gap: 0.75rem !important;
            padding: 0;
            border: 0;
            border-radius: 0;
            background: transparent;
        }
        .st-key-sidebar_data_system_group .pudu-sidebar-label {
            margin: 0.15rem 0 0.5rem;
        }
        .pudu-sidebar-system-heading {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            margin: 0.15rem 0 0.5rem;
        }
        .pudu-sidebar-system-heading .pudu-sidebar-label {
            margin: 0;
        }
        .pudu-app-version {
            color: var(--pudu-muted) !important;
            font-size: 0.68rem;
            font-weight: 600;
            white-space: nowrap;
        }
        .st-key-sidebar_data_system_group [data-testid="stExpander"] {
            margin-top: 0.5rem;
        }
        .pudu-page-header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1.5rem;
            margin: 0 -0.5rem 1.35rem;
            padding: 0.9rem 0.5rem 1.05rem;
            border-top: 1px solid #D9E4EA;
            border-bottom: 1px solid #D9E4EA;
            background: #F8FBFC;
        }
        [data-testid="stHorizontalBlock"]:has(.pudu-page-header) {
            align-items: center;
            margin: 0 -0.5rem 1.35rem;
            padding: 0.9rem 0.5rem 1.05rem;
            border-top: 1px solid #D9E4EA;
            border-bottom: 1px solid #D9E4EA;
            background: #F8FBFC;
        }
        [data-testid="stHorizontalBlock"]:has(.pudu-page-header) .pudu-page-header {
            margin: 0;
            padding: 0;
            border: 0;
            background: transparent;
        }
        .pudu-page-kicker {
            color: var(--pudu-teal);
            font-size: 0.75rem;
            font-weight: 680;
            margin-bottom: 0.4rem;
        }
        .pudu-page-title {
            margin: 0;
            color: var(--pudu-ink);
            font-size: 1.875rem;
            font-weight: 680;
            line-height: 1.28;
        }
        .pudu-page-subtitle {
            max-width: 760px;
            margin: 0.45rem 0 0;
            color: var(--pudu-muted);
            font-size: 0.875rem;
            line-height: 1.65;
        }
        [class*="st-key-refresh_page_cache_"] button {
            min-height: 44px !important;
            border: 1px solid #164E7A !important;
            border-radius: 9px !important;
            background: #1F5C8D !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            box-shadow: 0 5px 14px rgba(31, 92, 141, 0.24) !important;
        }
        [class*="st-key-refresh_page_cache_"] button:hover {
            border-color: #0E3D62 !important;
            background: #164E7A !important;
            color: #FFFFFF !important;
            transform: translateY(-1px);
            box-shadow: 0 7px 18px rgba(31, 92, 141, 0.30) !important;
        }
        .pudu-section-heading {
            display: flex;
            align-items: flex-start;
            gap: 0.8rem;
            margin: 0 0 1rem;
        }
        .pudu-section-index {
            display: grid;
            place-items: center;
            min-width: 28px;
            height: 28px;
            border-radius: 6px;
            background: var(--pudu-navy-soft);
            color: var(--pudu-navy);
            font-size: 0.75rem;
            font-weight: 700;
        }
        .pudu-section-title {
            color: var(--pudu-ink);
            font-size: 1rem;
            font-weight: 650;
            line-height: 1.45;
        }
        .pudu-section-description {
            margin-top: 0.16rem;
            color: var(--pudu-muted);
            font-size: 0.78rem;
            line-height: 1.5;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-section-heading) > [data-testid="stVerticalBlock"] {
            padding: 1.05rem 1.15rem;
            border-color: var(--pudu-line) !important;
            border-radius: 8px !important;
            background: var(--pudu-panel);
            box-shadow: none;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-section-tone-navy) > [data-testid="stVerticalBlock"] {
            border-color: #C8D9E5 !important;
            border-top: 3px solid var(--pudu-navy) !important;
            background: var(--pudu-navy-soft);
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-section-tone-teal) > [data-testid="stVerticalBlock"] {
            border-color: #C4E0DC !important;
            border-top: 3px solid var(--pudu-teal) !important;
            background: var(--pudu-teal-soft);
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-section-tone-coral) > [data-testid="stVerticalBlock"] {
            border-color: #F0D1C8 !important;
            border-top: 3px solid var(--pudu-coral) !important;
            background: var(--pudu-coral-soft);
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-section-tone-gold) > [data-testid="stVerticalBlock"] {
            border-color: #EAD9B3 !important;
            border-top: 3px solid var(--pudu-gold) !important;
            background: var(--pudu-gold-soft);
        }
        .pudu-section-tone-teal .pudu-section-index {
            background: #D5EFEB;
            color: #116A6E;
        }
        .pudu-section-tone-coral .pudu-section-index {
            background: #FADDD5;
            color: #A6422D;
        }
        .pudu-section-tone-gold .pudu-section-index {
            background: #F6E6BD;
            color: #815712;
        }
        div[data-testid="stMetric"] {
            min-height: 102px;
            background: #FBFDFD;
            border: 1px solid var(--pudu-line);
            border-top: 3px solid var(--pudu-teal);
            border-radius: 8px;
            padding: 0.95rem 1rem;
            box-shadow: none;
        }
        [data-testid="stMetricLabel"] {
            color: var(--pudu-muted);
            font-size: 0.78rem;
        }
        [data-testid="stMetricValue"] {
            color: var(--pudu-ink);
            font-size: 1.55rem;
            font-weight: 670;
        }
        button[kind="primary"] {
            min-height: 40px;
            border: 1px solid var(--pudu-blue) !important;
            border-radius: 6px !important;
            background: var(--pudu-blue) !important;
            color: #FFFFFF;
            font-weight: 620;
            box-shadow: none !important;
        }
        button[kind="primary"]:hover {
            border-color: var(--pudu-blue-hover) !important;
            background: var(--pudu-blue-hover) !important;
        }
        button[kind="secondary"] {
            min-height: 40px;
            border: 1px solid var(--pudu-line) !important;
            border-radius: 6px !important;
            background: #FFFFFF !important;
            color: var(--pudu-ink) !important;
            font-weight: 570;
            box-shadow: none !important;
        }
        button[kind="secondary"]:hover {
            border-color: #94B3C5 !important;
            background: var(--pudu-blue-soft) !important;
            color: var(--pudu-blue) !important;
        }
        button[kind="tertiary"] {
            min-height: 36px;
            border-radius: 6px !important;
            color: var(--pudu-blue) !important;
        }
        .stButton button p,
        .stDownloadButton button p {
            letter-spacing: 0;
        }
        div[data-baseweb="select"] > div,
        [data-testid="stSelectbox"] div[role="group"],
        [data-testid="stMultiSelect"] div[role="group"],
        div[data-baseweb="input"] > div,
        textarea {
            border: 1px solid var(--pudu-control-line) !important;
            border-radius: 6px !important;
            background-color: #FFFFFF;
            box-shadow: none !important;
        }
        input,
        textarea,
        div[data-baseweb="select"] * {
            color: var(--pudu-ink) !important;
        }
        input::placeholder,
        textarea::placeholder {
            color: #7C8993 !important;
            opacity: 1;
        }
        div[data-baseweb="select"] > div:focus-within,
        [data-testid="stSelectbox"] div[role="group"]:focus-within,
        [data-testid="stMultiSelect"] div[role="group"]:focus-within,
        div[data-baseweb="input"] > div:focus-within,
        textarea:focus {
            border-color: var(--pudu-blue) !important;
            box-shadow: 0 0 0 2px rgba(23, 76, 122, 0.13) !important;
        }
        [data-testid="stTextInputRootElement"],
        [data-testid="stTextAreaRootElement"],
        [data-testid="stNumberInputContainer"] {
            min-height: 40px;
            border: 1px solid var(--pudu-control-line) !important;
            border-radius: 6px !important;
            background: #FFFFFF !important;
        }
        [data-testid="stTextInputRootElement"]:focus-within,
        [data-testid="stTextAreaRootElement"]:focus-within,
        [data-testid="stNumberInputContainer"]:focus-within {
            border-color: var(--pudu-blue) !important;
            box-shadow: 0 0 0 2px rgba(23, 76, 122, 0.13) !important;
        }
        [data-testid="stTextInputRootElement"]:has(input:disabled),
        [data-testid="stTextAreaRootElement"]:has(textarea:disabled),
        [data-testid="stSelectbox"] div[role="group"]:has(input:disabled),
        [data-testid="stMultiSelect"] div[role="group"]:has(input:disabled) {
            background: #F5F6F8 !important;
        }
        .pudu-required-control-marker {
            display: none;
        }
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] [data-testid="stTextInputRootElement"],
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] [data-testid="stTextAreaRootElement"],
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] [data-testid="stNumberInputContainer"],
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] div[data-baseweb="select"] > div,
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] textarea {
            border-color: var(--pudu-required-line) !important;
            background: var(--pudu-required-bg) !important;
        }
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] [data-testid="stTextInputRootElement"]:focus-within,
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] [data-testid="stTextAreaRootElement"]:focus-within,
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] [data-testid="stNumberInputContainer"]:focus-within,
        [data-testid="stElementContainer"]:has(.pudu-required-control-marker)
        + [data-testid="stElementContainer"] div[data-baseweb="select"] > div:focus-within {
            border-color: var(--pudu-required-focus) !important;
            box-shadow: 0 0 0 2px rgba(201, 90, 80, 0.12) !important;
        }
        .pudu-readonly-required-control {
            display: flex;
            align-items: center;
            min-height: 40px;
            padding: 0.45rem 0.75rem;
            border: 1px solid var(--pudu-required-line);
            border-radius: 6px;
            background: var(--pudu-required-bg);
            color: var(--pudu-subtle);
            font-size: 0.9rem;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }
        .pudu-readonly-required-control.has-value {
            color: var(--pudu-ink);
        }
        [data-testid="stFileUploaderDropzone"] {
            min-height: 90px;
            border: 1px dashed #BFC4CC;
            border-radius: 8px;
            background: var(--pudu-gold-soft);
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--pudu-line);
            border-radius: 8px;
            overflow: hidden;
            background: #FFFFFF;
        }
        [data-testid="stDataEditor"] {
            border: 1px solid var(--pudu-line);
            border-radius: 8px;
            overflow: hidden;
            background: #FFFFFF;
        }
        .pudu-fixed-recipient {
            display: grid;
            grid-template-columns: minmax(110px, 0.18fr) 1fr;
            gap: 0.75rem;
            align-items: start;
            margin: 0.65rem 0 0.95rem;
            padding: 0.8rem 0.95rem;
            border: 1px solid #C4E0DC;
            border-left: 3px solid var(--pudu-teal);
            border-radius: 8px;
            background: var(--pudu-teal-soft);
        }
        .pudu-fixed-recipient-label {
            color: var(--pudu-teal);
            font-size: 0.78rem;
            font-weight: 700;
        }
        .pudu-fixed-recipient-value {
            color: var(--pudu-ink);
            font-size: 0.88rem;
            line-height: 1.55;
            overflow-wrap: anywhere;
            white-space: pre-wrap;
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            gap: 0.25rem;
            border-bottom: 1px solid var(--pudu-line);
        }
        [data-testid="stTabs"] [data-baseweb="tab"] {
            min-height: 44px;
            padding: 0 0.9rem;
            color: var(--pudu-muted);
            font-weight: 570;
        }
        [data-testid="stTabs"] [aria-selected="true"] {
            color: var(--pudu-teal);
        }
        div[role="radiogroup"] {
            display: flex;
            width: fit-content;
            max-width: 100%;
            gap: 0.25rem;
            padding: 0.25rem;
            border-radius: 8px;
            background: #E8EEF1;
        }
        div[role="radiogroup"] label {
            min-height: 34px;
            margin: 0 !important;
            padding: 0.35rem 0.75rem;
            border-radius: 6px;
        }
        div[role="radiogroup"] label:has(input:checked) {
            background: #FFFFFF;
            color: var(--pudu-navy) !important;
            outline: 1px solid #C7D7E2;
            box-shadow: 0 1px 2px rgba(31, 35, 41, 0.10);
        }
        [data-testid="stExpander"] {
            border: 1px solid var(--pudu-line) !important;
            border-radius: 8px !important;
            background: #FFFFFF;
        }
        [data-testid="stAlert"] {
            border-radius: 8px;
            box-shadow: none;
        }
        [data-testid="stSpinner"] {
            position: static;
            display: block;
            padding: 0.35rem 0;
            background: transparent;
            backdrop-filter: none;
        }
        [data-testid="stSpinner"] > div {
            width: fit-content !important;
            min-width: 0;
            max-width: 100%;
            padding: 0;
            border: 0;
            background: transparent;
            box-shadow: none;
        }
        [data-testid="stSpinner"] p {
            color: var(--pudu-ink);
            font-size: 0.9rem;
            font-weight: 600;
        }
        [data-testid="stCaptionContainer"] {
            color: var(--pudu-muted);
            font-size: 0.78rem;
        }
        .pudu-field-label {
            display: flex;
            align-items: baseline;
            flex-wrap: wrap;
            gap: 0.25rem 0.65rem;
            color: var(--pudu-ink);
            font-size: 0.82rem;
            font-weight: 540;
            margin: 0 0 0.35rem;
        }
        /* Compact material-request workspace. The marker keeps these density
           changes scoped to the request page instead of shrinking admin tools. */
        .stApp:has(.pudu-request-page-marker) [data-testid="stMainBlockContainer"] {
            padding-top: 0.3rem;
        }
        .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar {
            display: none;
        }
        .stApp:has(.pudu-request-page-marker) .st-key-request_catalog_grid {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 0.75rem;
            align-items: start;
        }
        [class*="st-key-request_model_line_grid_"] {
            display: grid !important;
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 0.5rem !important;
            align-items: start !important;
        }
        [class*="st-key-request_quantity_presets_"] [data-testid="stButtonGroup"] > div:last-child {
            display: grid !important;
            grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
            gap: 0.3rem !important;
        }
        [class*="st-key-request_quantity_presets_"] [data-testid="stButtonGroup"] button {
            width: 100% !important;
            min-width: 0 !important;
            padding-inline: 0.35rem !important;
            white-space: nowrap !important;
        }
        @media (min-width: 641px) {
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] [data-testid="stPopover"] > button {
                font-size: 0.74rem !important;
                white-space: nowrap !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] [data-testid="stPopover"] > button p,
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] [data-testid="stPopover"] > button span {
                font-size: inherit !important;
                line-height: 1.1 !important;
                white-space: nowrap !important;
                overflow-wrap: normal !important;
                word-break: keep-all !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_spec_model_scroll_"]
            [data-testid="stElementContainer"]:has(.pudu-spec-model-heading) {
                min-height: 1.35rem !important;
                margin-bottom: 0.45rem !important;
                overflow: visible !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_spec_model_scroll_"]
            .pudu-spec-model-heading {
                margin: 0 !important;
                line-height: 1.35 !important;
                font-weight: 750 !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_spec_model_scroll_"]
            [data-testid="stWidgetLabel"] {
                margin-top: 0.1rem !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_spec_model_scroll_"]
            [data-testid="stElementContainer"]:has(.pudu-product-model-label) {
                min-height: 1.25rem !important;
                margin-bottom: 0.42rem !important;
                overflow: visible !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_spec_model_scroll_"]
            .pudu-product-model-label {
                margin: 0 !important;
                font-size: 0.88rem !important;
                line-height: 1.2 !important;
                font-weight: 650 !important;
            }
        }
        [data-testid="stSidebar"][aria-expanded="false"] {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            z-index: 1000 !important;
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;
            transform: none !important;
            background: transparent !important;
            border-right: 0 !important;
            overflow: visible !important;
        }
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarHeader"] {
            position: static !important;
            width: 0 !important;
            height: 0 !important;
            min-height: 0 !important;
            padding: 0 !important;
            overflow: visible !important;
        }
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"] {
            position: static !important;
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;
            overflow: visible !important;
        }
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarUserContent"],
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNav"],
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarResizeHandle"] {
            display: none !important;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-page-header {
            margin-bottom: 0.7rem;
            padding-top: 0.45rem;
            padding-bottom: 0.65rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-page-kicker {
            margin-bottom: 0.18rem;
            font-size: 0.68rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-page-title {
            font-size: 1.55rem;
            line-height: 1.18;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-page-subtitle {
            margin-top: 0.2rem;
            font-size: 0.78rem;
            line-height: 1.4;
        }
        .stApp:has(.pudu-request-page-marker) [data-testid="stLayoutWrapper"]:has(.pudu-section-heading) > [data-testid="stVerticalBlock"] {
            padding: 0.7rem 0.85rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-section-heading {
            gap: 0.55rem;
            margin-bottom: 0.55rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-section-index {
            min-width: 24px;
            height: 24px;
            font-size: 0.68rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-section-title {
            font-size: 0.88rem;
            line-height: 1.3;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-section-description,
        .stApp:has(.pudu-request-page-marker) [data-testid="stCaptionContainer"] {
            font-size: 0.7rem;
            line-height: 1.35;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-field-label {
            margin-bottom: 0.2rem;
            font-size: 0.73rem;
            gap: 0.15rem 0.45rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-inline-required-hint {
            font-size: 0.67rem;
        }
        .stApp:has(.pudu-request-page-marker) div[data-baseweb="input"],
        .stApp:has(.pudu-request-page-marker) div[data-baseweb="select"] > div {
            min-height: 36px;
            font-size: 0.8rem;
        }
        .stApp:has(.pudu-request-page-marker) input,
        .stApp:has(.pudu-request-page-marker) textarea,
        .stApp:has(.pudu-request-page-marker) [data-baseweb="select"] {
            font-size: 0.8rem;
        }
        .stApp:has(.pudu-request-page-marker) .st-key-request_requester_open_id [data-baseweb="select"] > div,
        .stApp:has(.pudu-request-page-marker) .st-key-request_requester_manual [data-baseweb="input"] {
            border-color: var(--pudu-required-line) !important;
        }
        .stApp:has(.pudu-request-page-marker) .st-key-request_requester_open_id [data-baseweb="select"] > div:focus-within,
        .stApp:has(.pudu-request-page-marker) .st-key-request_requester_manual [data-baseweb="input"]:focus-within {
            border-color: var(--pudu-required-focus) !important;
        }
        .stApp:has(.pudu-request-page-marker) [data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }
        .stApp:has(.pudu-request-page-marker) [data-testid="stHorizontalBlock"] {
            gap: 0.7rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-generated-title {
            min-height: 34px;
            margin-bottom: 0.5rem;
            padding: 0.38rem 0.6rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-generated-title span {
            font-size: 0.7rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-generated-title strong {
            font-size: 0.8rem;
        }
        .stApp:has(.pudu-request-page-marker) [class*="st-key-request_product_card_"] > [data-testid="stVerticalBlock"] {
            min-height: 235px;
            padding: 0.48rem !important;
        }
        .stApp:has(.pudu-request-page-marker) [class*="st-key-request_product_card_"] [data-testid="stImage"] img,
        .stApp:has(.pudu-request-page-marker) [class*="st-key-request_product_card_"] .pudu-product-image-placeholder {
            height: 96px;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-product-card-kicker {
            font-size: 0.61rem;
        }
        .stApp:has(.pudu-request-page-marker) .pudu-product-card-title {
            min-height: 2.1rem;
            font-size: 0.76rem;
            line-height: 1.35;
        }
        .pudu-required-star {
            color: var(--pudu-red);
            font-weight: 700;
        }
        .pudu-inline-required-hint {
            color: #B42318;
            font-size: 0.76rem;
            font-weight: 700;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }
        .pudu-generated-title {
            display: flex;
            align-items: center;
            gap: 0.8rem;
            min-height: 40px;
            margin-bottom: 0.85rem;
            padding: 0.55rem 0.75rem;
            border-left: 3px solid var(--pudu-navy);
            background: rgba(255, 255, 255, 0.72);
        }
        .pudu-generated-title span {
            flex: 0 0 auto;
            color: var(--pudu-muted);
            font-size: 0.78rem;
        }
        .pudu-generated-title strong {
            min-width: 0;
            overflow-wrap: anywhere;
            color: var(--pudu-ink);
            font-size: 0.9rem;
            font-weight: 650;
        }
        .pudu-material-list-status {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.8rem 0 0.55rem;
            color: var(--pudu-muted);
            font-size: 0.8rem;
        }
        .pudu-material-list-status strong {
            color: var(--pudu-coral);
            font-size: 0.9rem;
        }
        .pudu-product-card-marker,
        .pudu-gift-card-marker,
        .pudu-cart-marker,
        .pudu-full-cart-popover-marker,
        .pudu-specification-popover-marker,
        .pudu-gift-detail-drawer-marker {
            display: none;
        }
        .pudu-request-cost-summary {
            display: flex;
            align-items: baseline;
            gap: 0.65rem;
            margin: 0.45rem 0 0.55rem;
            padding: 0.55rem 0.8rem;
            border-left: 4px solid var(--pudu-teal);
            border-radius: 7px;
            background: rgba(255, 255, 255, 0.72);
            color: var(--pudu-ink);
        }
        .pudu-request-cost-summary span {
            color: var(--pudu-muted);
            font-size: 0.82rem;
            font-weight: 700;
        }
        .pudu-request-cost-summary strong {
            color: var(--pudu-navy);
            font-size: 1.22rem;
            line-height: 1;
        }
        .pudu-request-cost-summary small {
            color: var(--pudu-muted);
            font-size: 0.72rem;
        }
        .st-key-request_compact_cart button {
            border-color: #C9472D !important;
            background: #E25B3F !important;
            color: #FFFFFF !important;
            font-weight: 750 !important;
            box-shadow: 0 4px 12px rgba(226, 91, 63, 0.24) !important;
        }
        .st-key-request_compact_cart button:hover {
            border-color: #A93724 !important;
            background: #C9472D !important;
            color: #FFFFFF !important;
        }
        [data-testid="stToast"] {
            min-width: min(430px, calc(100vw - 2rem)) !important;
            min-height: 82px !important;
            padding: 1rem 1.15rem !important;
            border: 1px solid #B83A24 !important;
            border-radius: 12px !important;
            background: linear-gradient(135deg, #F26B4F 0%, #C9472D 100%) !important;
            color: #FFFFFF !important;
            box-shadow: 0 12px 32px rgba(180, 55, 34, 0.34) !important;
            animation: pudu-toast-slide-in 420ms cubic-bezier(0.2, 0.82, 0.3, 1)
                both !important;
        }
        [data-testid="stToast"] p,
        [data-testid="stToast"] span,
        [data-testid="stToast"] svg {
            color: #FFFFFF !important;
            fill: #FFFFFF !important;
            font-weight: 750 !important;
            font-size: 1rem !important;
        }
        [data-testid="stPopoverBody"] [data-testid="stButtonGroup"] button[aria-pressed="true"] {
            border: 2px solid #0B57D0 !important;
            background: #0B57D0 !important;
            color: #FFFFFF !important;
            box-shadow: 0 0 0 3px rgba(11, 87, 208, 0.18) !important;
            font-weight: 800 !important;
        }
        [data-testid="stPopoverBody"] [data-testid="stButtonGroup"] button[aria-pressed="true"] p,
        [data-testid="stPopoverBody"] [data-testid="stButtonGroup"] button[aria-pressed="true"] span,
        [data-testid="stPopoverBody"] [data-testid="stButtonGroup"] button[aria-pressed="true"] svg {
            color: #FFFFFF !important;
            fill: #FFFFFF !important;
        }
        [class*="st-key-request_custom_material_"] [data-testid="stCheckbox"] label p {
            color: #D92D20 !important;
            font-weight: 800 !important;
        }
        @keyframes pudu-toast-slide-in {
            0% {
                transform: translateX(calc(100% + 42px));
                opacity: 0;
            }
            72% {
                transform: translateX(-8px);
                opacity: 1;
            }
            100% {
                transform: translateX(0);
                opacity: 1;
            }
        }
        [data-testid="stPopoverBody"]:has(.pudu-full-cart-popover-marker) {
            width: min(1320px, calc(100vw - 2rem)) !important;
            max-width: min(1320px, calc(100vw - 2rem)) !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-full-cart-popover-marker) > div {
            width: 100% !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) {
            max-width: min(1180px, calc(100vw - 1.5rem)) !important;
            max-height: calc(100vh - 1.5rem) !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-compact) {
            width: min(680px, calc(100vw - 1.5rem)) !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-medium) {
            width: min(900px, calc(100vw - 1.5rem)) !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-wide) {
            width: min(1180px, calc(100vw - 1.5rem)) !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) > div {
            width: 100% !important;
            gap: 0.28rem !important;
            padding: 0.65rem !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) p,
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) label,
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) button {
            font-size: 0.78rem !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) [data-testid="stVerticalBlock"] {
            gap: 0.28rem !important;
        }
        [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] > div:last-child {
            display: grid !important;
            grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
            gap: 0.3rem !important;
            width: 100% !important;
        }
        [class*="st-key-request_language_pills_"]:has(.pudu-language-columns-2) [data-testid="stButtonGroup"] > div:last-child {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        }
        [class*="st-key-request_language_pills_"]:has(.pudu-language-columns-3) [data-testid="stButtonGroup"] > div:last-child {
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        }
        [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] button {
            width: 100% !important;
            min-width: 0 !important;
            justify-content: center !important;
        }
        [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] button[aria-pressed="true"] {
            border: 2px solid #0B57D0 !important;
            background: #0B57D0 !important;
            color: #FFFFFF !important;
            box-shadow: 0 0 0 3px rgba(11, 87, 208, 0.22), 0 4px 10px rgba(11, 87, 208, 0.22) !important;
            font-weight: 800 !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        [data-testid="stButtonGroup"] > div:last-child:has(> button:only-child) {
            display: flex !important;
            width: 100% !important;
            justify-content: flex-start !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        [data-testid="stButtonGroup"] > div:last-child > button:only-child {
            width: auto !important;
            min-width: 7.5rem !important;
            max-width: min(100%, 24rem) !important;
            padding-left: 1.35rem !important;
            padding-right: 1.35rem !important;
            flex: 0 0 auto !important;
        }
        [class*="st-key-request_product_card_"] > [data-testid="stVerticalBlock"] {
            min-height: 286px;
            gap: 0.35rem;
            padding: 0.7rem !important;
            border-color: #D8E1E8 !important;
            border-radius: 10px !important;
            background: linear-gradient(145deg, #FFFFFF 0%, #F6FAFC 100%);
            transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
            transform-origin: center center;
        }
        [class*="st-key-request_product_card_"]:hover > [data-testid="stVerticalBlock"] {
            z-index: 3;
            transform: translateY(-3px) scale(1.015);
            border-color: #8FB1C9 !important;
            box-shadow: 0 9px 22px rgba(22, 58, 79, 0.14);
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        [data-testid="stButtonGroup"] button {
            transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease !important;
            transform-origin: center center;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        [data-testid="stButtonGroup"] button:hover {
            z-index: 2;
            transform: translateY(-1px) scale(1.025);
            border-color: #2672B9 !important;
            box-shadow: 0 5px 12px rgba(38, 114, 185, 0.17) !important;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        [data-testid="stButtonGroup"] button[aria-pressed="true"] {
            z-index: 2;
            transform: translateY(-1px) scale(1.025);
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        [data-testid="stCheckbox"] label,
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        .stButton > button,
        [class*="st-key-request_product_card_"] [data-testid="stPopover"] > button {
            transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease !important;
            transform-origin: center center;
        }
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        [data-testid="stCheckbox"] label:hover,
        [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
        .stButton > button:hover,
        [class*="st-key-request_product_card_"] [data-testid="stPopover"] > button:hover {
            transform: translateY(-1px) scale(1.018);
            box-shadow: 0 5px 12px rgba(38, 114, 185, 0.14) !important;
        }
        [class*="st-key-request_product_card_"] [data-testid="stImage"] img {
            width: 100%;
            height: 142px;
            border: 1px solid #E2E8ED;
            border-radius: 8px;
            background: #F7F9FA;
            object-fit: contain;
        }
        .pudu-product-image-placeholder {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 142px;
            border: 1px dashed #C8D2DA;
            border-radius: 8px;
            background: #F2F5F7;
            color: var(--pudu-muted);
            font-size: 0.78rem;
            font-weight: 600;
        }
        .pudu-product-card-kicker {
            color: var(--pudu-teal);
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .pudu-product-card-title {
            min-height: 2.4rem;
            color: var(--pudu-ink);
            font-size: 0.92rem;
            font-weight: 700;
            line-height: 1.45;
            overflow-wrap: anywhere;
        }
        .st-key-request_compact_cart button,
        .st-key-request_preview button {
            transition: transform 160ms ease, border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease !important;
            transform-origin: center center;
        }
        .st-key-request_compact_cart button:hover,
        .st-key-request_preview button:hover {
            z-index: 3;
            transform: translateY(-2px) scale(1.025);
            box-shadow: 0 7px 16px rgba(24, 66, 92, 0.2) !important;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-card-marker) > [data-testid="stVerticalBlock"] {
            min-height: 390px;
            gap: 0.42rem;
            padding: 0.75rem !important;
            border-color: #D8E1E8 !important;
            border-radius: 8px !important;
            background: #FFFFFF;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-card-marker) [data-testid="stImage"] img {
            width: 100%;
            height: 174px;
            border: 1px solid #E2E8ED;
            border-radius: 6px;
            background: #F7F9FA;
            object-fit: contain;
        }
        .pudu-gift-card-meta {
            min-height: 2.6rem;
            color: var(--pudu-muted);
            font-size: 0.78rem;
            line-height: 1.55;
            overflow-wrap: anywhere;
        }
        .pudu-gift-card-price {
            color: var(--pudu-navy);
            font-size: 0.84rem;
            font-weight: 700;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) {
            min-height: 360px;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) > [data-testid="stVerticalBlock"] {
            min-height: 360px;
            height: 360px;
            display: flex !important;
            flex-direction: column;
            gap: 0.42rem;
            padding: 0.7rem !important;
            border-color: #D8E1E8 !important;
            border-radius: 8px !important;
            background: #FFFFFF;
            overflow: hidden;
            box-sizing: border-box;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) [data-testid="stElementContainer"]:has([data-testid="stImage"]),
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) [data-testid="stElementContainer"]:has(.pudu-product-image-placeholder) {
            height: 105px;
            min-height: 105px;
            margin-bottom: 0.35rem !important;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) [data-testid="stImage"],
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) .pudu-product-image-placeholder {
            height: 105px;
            min-height: 105px;
            margin: 0 !important;
            box-sizing: border-box;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) [data-testid="stImage"] img {
            width: 100%;
            height: 105px;
            border: 1px solid #E2E8ED;
            border-radius: 6px;
            background: #F7F9FA;
            object-fit: contain;
        }
        .pudu-project-progress-card-marker { display: none; }
        .pudu-project-progress-title {
            display: block;
            height: 1.45rem;
            margin-top: 0.1rem;
            padding-top: 0;
            color: var(--pudu-ink);
            font-size: 0.82rem;
            font-weight: 750;
            line-height: 1.4;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .pudu-project-progress-status {
            display: inline-block;
            width: fit-content;
            margin: 0 0 0.35rem;
            padding: 0.24rem 0.4rem;
            border: 1px solid #B9C7D2;
            border-radius: 6px;
            color: #17324D;
            background: #EAF0F4;
            font-size: 0.72rem;
            font-weight: 800;
            line-height: 1.25;
        }
        .pudu-project-progress-status--requested { background: #FFF3CD; border-color: #E8C96A; }
        .pudu-project-progress-status--design { background: #E5F1FF; border-color: #9EC5F8; }
        .pudu-project-progress-status--production { background: #FFE8D8; border-color: #F2B27C; }
        .pudu-project-progress-status--arrived { background: #E3F5E9; border-color: #91D3A4; }
        .pudu-project-progress-status--stock { background: #DDF5F2; border-color: #82C9C1; }
        .pudu-project-progress-meta {
            min-height: 3.35rem;
            margin-top: 0.22rem;
            padding: 0.45rem 0;
            border-top: 1px solid #E7EDF1;
            border-bottom: 1px solid #E7EDF1;
            color: var(--pudu-muted);
            font-size: 0.7rem;
            line-height: 1.55;
            overflow-wrap: anywhere;
        }
        .pudu-project-progress-note-label { margin-top: 0.45rem; color: var(--pudu-ink); font-size: 0.7rem; font-weight: 750; }
        .pudu-project-progress-note {
            min-height: 2.25rem;
            margin-top: 0.2rem;
            margin-bottom: 0;
            color: var(--pudu-ink);
            font-size: 0.7rem;
            line-height: 1.55;
            overflow: hidden;
            overflow-wrap: anywhere;
            display: -webkit-box;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) [data-testid="stElementContainer"]:has(.stButton) {
            margin-top: auto;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) .stButton button {
            min-height: 2.35rem;
            padding: 0.35rem 0.45rem;
            font-size: 0.78rem;
            font-weight: 700;
            white-space: nowrap;
        }
        .pudu-project-progress-stage-marker { display: none; }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) {
            margin: 0 0 0.45rem !important;
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details {
            border: 0 !important;
            background: transparent !important;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details[open] {
            display: grid;
            grid-template-columns: 7.5rem minmax(0, 1fr);
            column-gap: 0.8rem;
            align-items: stretch;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details:not([open]) {
            display: block;
            width: 7.5rem;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details:not([open]) > div {
            display: none !important;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details > summary {
            grid-column: 1;
            min-height: 3rem;
            padding: 0.65rem 0.45rem 0.95rem !important;
            align-items: center;
            justify-content: center;
            clip-path: polygon(0 0, 100% 0, 100% 78%, 50% 100%, 0 78%);
            background: #EAF0F4;
            font-size: 0.72rem;
            font-weight: 750;
            text-align: center;
            transition: transform 180ms ease, background-color 180ms ease, min-height 180ms ease;
        }
        [data-testid="stExpander"]:has(.pudu-project-stage-requested) details > summary { background: #E7EDF2; }
        [data-testid="stExpander"]:has(.pudu-project-stage-sourcing) details > summary { background: #FFF0B8; }
        [data-testid="stExpander"]:has(.pudu-project-stage-confirm) details > summary { background: #DDF3F0; }
        [data-testid="stExpander"]:has(.pudu-project-stage-design) details > summary { background: #FFE3CC; }
        [data-testid="stExpander"]:has(.pudu-project-stage-arrived) details > summary { background: #DDF1E3; }
        [data-testid="stExpander"]:has(.pudu-project-stage-shipped) details > summary { background: #E9E1F5; }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details > summary:hover {
            z-index: 2;
            transform: scale(1.045);
            background: #DDE8EE;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details[open] > summary {
            min-height: 5rem;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details > summary svg {
            display: none;
        }
        [data-testid="stExpander"]:has(.pudu-project-progress-stage-marker) details > div {
            grid-column: 2;
            min-width: 0;
            padding: 0.65rem 0.7rem 0.8rem 0 !important;
            border: 0 !important;
            background: transparent !important;
        }
        .pudu-project-empty-stage {
            padding: 0.8rem 0.25rem;
            color: #8A99A5;
            font-size: 0.76rem;
            line-height: 1.5;
        }
        .st-key-gift_project_page_mode [data-testid="stRadio"] > div {
            gap: 1rem;
        }
        .st-key-gift_project_page_mode label {
            min-width: 9rem;
            padding: 0.65rem 1.2rem !important;
            justify-content: center;
            border: 1px solid #A9C7E8;
            border-radius: 6px;
            background: #F4F8FC;
            color: #174A7A;
            font-weight: 750;
            transition: transform 180ms ease, background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
        }
        .st-key-gift_project_page_mode label:hover { transform: scale(1.035); box-shadow: 0 5px 14px rgba(38, 114, 185, 0.16); }
        .st-key-gift_project_page_mode label:has(input:checked) {
            border-color: #2672B9;
            background: #2672B9;
            color: #FFFFFF;
        }
        .st-key-gift_project_page_mode label > div:first-child { display: none; }
        .pudu-gift-catalog-card-marker,
        .pudu-gift-new-category-card-marker { display: none; }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker),
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) {
            height: 268px;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) {
            min-height: 268px;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) > [data-testid="stVerticalBlock"] {
            height: 268px;
            min-height: 268px;
            display: flex !important;
            flex-direction: column;
            gap: 0.42rem;
            padding: 0.65rem !important;
            overflow: hidden;
            box-sizing: border-box;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) [data-testid="stElementContainer"]:has([data-testid="stImage"]),
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) [data-testid="stElementContainer"]:has(.pudu-product-image-placeholder) {
            height: 112px;
            min-height: 112px;
            margin-bottom: 0.28rem !important;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) [data-testid="stImage"],
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) .pudu-product-image-placeholder {
            height: 112px;
            min-height: 112px;
            box-sizing: border-box;
            margin: 0 !important;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) [data-testid="stImage"] img {
            height: 112px;
            object-fit: contain;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) [data-testid="stElementContainer"]:has(.pudu-gift-catalog-title) {
            height: 2.85rem;
            min-height: 2.85rem;
        }
        .pudu-gift-catalog-title {
            height: 2.85rem;
            min-height: 2.85rem;
            overflow: hidden;
            display: -webkit-box;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
            font-size: 0.74rem;
            font-weight: 800;
            line-height: 1.35;
            color: #12263A;
            word-break: break-word;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) [data-testid="stElementContainer"]:has(.stButton) {
            margin-top: auto;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) .stButton button {
            min-height: 2.35rem;
            padding: 0.35rem 0.45rem;
            font-size: 0.78rem;
            font-weight: 700;
            line-height: 1.15;
            white-space: nowrap;
        }
        .pudu-gift-batch-cart {
            margin: 0.7rem 0 1rem;
            padding: 0.85rem 1rem;
            border: 1px solid #B9D9D3;
            border-radius: 8px;
            background: #ECF8F6;
        }
        .pudu-gift-batch-cart-marker { display: none; }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-batch-cart-marker) > [data-testid="stVerticalBlock"] {
            margin: 0.7rem 0 1rem;
            padding: 0.85rem 1rem !important;
            border: 1px solid #B9D9D3 !important;
            border-radius: 8px !important;
            background: #ECF8F6;
        }
        .pudu-gift-batch-item-marker { display: none; }
        [data-testid="stHorizontalBlock"]:has(.pudu-gift-batch-item-marker) {
            min-height: 3rem;
            align-items: center;
            gap: 0.75rem;
            padding: 0.4rem 0;
            border-top: 1px solid #CDE4E0;
        }
        .pudu-gift-batch-item-name {
            color: #12263A;
            font-size: 0.82rem;
            font-weight: 800;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }
        .pudu-gift-batch-item-meta {
            color: #53706E;
            font-size: 0.72rem;
            font-weight: 650;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }
        [data-testid="stHorizontalBlock"]:has(.pudu-gift-batch-item-marker) .stButton button {
            min-height: 2rem;
            padding: 0.3rem 0.45rem;
            font-size: 0.72rem;
            white-space: nowrap;
        }
        .pudu-gift-new-category-card {
            min-height: 78px;
            padding: 0.55rem 0.6rem;
            border: 1px dashed #1B8A86;
            border-radius: 7px;
            background: #E8F7F5;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 0.18rem;
        }
        .pudu-gift-new-category-card h3 {
            margin: 0;
            color: #0A5F5C;
            font-size: 1.08rem;
            font-weight: 900;
            line-height: 1.12;
        }
        .pudu-gift-new-category-card p {
            margin: 0;
            color: #3D6665;
            font-size: 0.64rem;
            font-weight: 650;
            line-height: 1.18;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) > [data-testid="stVerticalBlock"] {
            height: 268px;
            min-height: 268px;
            display: flex !important;
            flex-direction: column;
            gap: 0.16rem;
            padding: 0.6rem !important;
            overflow: hidden;
            box-sizing: border-box;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stWidgetLabel"] {
            min-height: 0;
            margin-bottom: 0.05rem;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stWidgetLabel"] p {
            font-size: 0.68rem;
            line-height: 1.1;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stTextInput"],
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stNumberInput"] {
            margin-bottom: 0 !important;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stTextInput"] input,
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stNumberInput"] input {
            min-height: 1.92rem;
            padding: 0.2rem 0.45rem;
            font-size: 0.74rem;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stHorizontalBlock"] {
            gap: 0.28rem;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) [data-testid="stElementContainer"]:has(.stButton) {
            margin-top: auto;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) .stButton button {
            min-height: 2.35rem;
            padding: 0.35rem 0.45rem;
            font-size: 0.78rem;
            font-weight: 750;
            white-space: nowrap;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker) > [data-testid="stVerticalBlock"],
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker) > [data-testid="stVerticalBlock"],
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker) > [data-testid="stVerticalBlock"] {
            transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-project-progress-card-marker):hover > [data-testid="stVerticalBlock"],
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-catalog-card-marker):hover > [data-testid="stVerticalBlock"],
        [data-testid="stLayoutWrapper"]:has(.pudu-gift-new-category-card-marker):hover > [data-testid="stVerticalBlock"] {
            z-index: 2;
            transform: translateY(-3px) scale(1.015);
            border-color: #9DB9CC !important;
            box-shadow: 0 9px 22px rgba(22, 58, 79, 0.14);
        }
        div[role="dialog"]:has(.pudu-gift-detail-drawer-marker) {
            animation: pudu-detail-drawer-in 240ms ease-out both;
        }
        div[role="dialog"]:has(.pudu-gift-detail-drawer-marker) > div {
            width: min(520px, 94vw) !important;
            max-width: min(520px, 94vw) !important;
            height: 100vh;
            max-height: 100vh !important;
            margin: 0 0 0 auto !important;
            border-radius: 0 !important;
        }
        @keyframes pudu-detail-drawer-in {
            from { transform: translateX(100%); opacity: 0.7; }
            to { transform: translateX(0); opacity: 1; }
        }
        .pudu-fixed-rule-row {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.5rem;
            margin: 0.35rem 0 0.9rem;
        }
        .pudu-fixed-rule-row div {
            min-width: 0;
            padding: 0.55rem 0.65rem;
            border: 1px solid var(--pudu-line);
            border-radius: 6px;
            background: var(--pudu-teal-soft);
            color: var(--pudu-ink);
            font-size: 0.76rem;
            overflow-wrap: anywhere;
        }
        .pudu-fixed-rule-row span {
            display: block;
            margin-bottom: 0.12rem;
            color: var(--pudu-muted);
            font-size: 0.68rem;
        }
        @media (max-width: 720px) {
            .pudu-fixed-rule-row {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-cart-marker) > [data-testid="stVerticalBlock"] {
            gap: 0.55rem;
            padding: 0.8rem 0.95rem !important;
            border-color: #B7D9D4 !important;
            border-radius: 10px !important;
            background: linear-gradient(90deg, #F0FAF8 0%, #FFFFFF 100%);
        }
        .pudu-cart-summary {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }
        .pudu-cart-summary strong {
            color: var(--pudu-navy);
            font-size: 1rem;
        }
        .pudu-cart-summary span {
            color: var(--pudu-muted);
            font-size: 0.8rem;
        }
        .pudu-review-field {
            min-height: 58px;
            padding: 0.2rem 0.15rem 0.65rem;
            border-bottom: 1px solid var(--pudu-line);
        }
        .pudu-review-field span {
            display: block;
            margin-bottom: 0.28rem;
            color: var(--pudu-muted);
            font-size: 0.75rem;
        }
        .pudu-review-field strong {
            display: block;
            overflow-wrap: anywhere;
            color: var(--pudu-ink);
            font-size: 0.88rem;
            font-weight: 600;
            line-height: 1.5;
        }
        .pudu-review-metrics {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin-bottom: 1rem;
            border-top: 3px solid var(--pudu-teal);
            border-right: 1px solid var(--pudu-line);
            border-bottom: 1px solid var(--pudu-line);
            border-left: 1px solid var(--pudu-line);
            border-radius: 8px;
            background: #FFFFFF;
            overflow: hidden;
        }
        .pudu-review-metric {
            min-width: 0;
            padding: 0.75rem 1rem;
            border-right: 1px solid var(--pudu-line);
        }
        .pudu-review-metric:last-child {
            border-right: 0;
        }
        .pudu-review-metric span {
            display: block;
            margin-bottom: 0.2rem;
            color: var(--pudu-muted);
            font-size: 0.75rem;
        }
        .pudu-review-metric strong {
            color: var(--pudu-ink);
            font-size: 1.35rem;
            font-weight: 680;
        }
        .pudu-review-metric small {
            display: block;
            margin-top: 0.22rem;
            color: var(--pudu-muted);
            font-size: 0.66rem;
            line-height: 1.35;
        }
        .pudu-review-metric-cost {
            background: #F4FBFA;
        }
        .pudu-review-metric-cost strong {
            color: var(--pudu-teal);
        }
        hr {
            border-color: var(--pudu-line-soft);
        }
        [data-testid="stAppDeployButton"],
        [data-testid="stMainMenuButton"],
        [data-testid="stExpandSidebarButton"],
        [data-testid="stToolbar"],
        [data-testid="stStatusWidget"],
        [data-testid="stDecoration"],
        [data-testid="stHeader"],
        [class*="viewerBadge"],
        [class*="ViewerBadge"] {
            display: none !important;
        }
        .pudu-sync-overlay {
            position: fixed;
            inset: 0;
            z-index: 1000000;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
            background: rgba(244, 247, 248, 0.88);
            backdrop-filter: blur(3px);
            cursor: wait;
            pointer-events: all;
        }
        .pudu-sync-overlay--success {
            cursor: default;
            background: rgba(238, 247, 244, 0.94);
        }
        .pudu-sync-overlay--success .pudu-sync-overlay__panel {
            position: relative;
            justify-content: center;
            border-color: #8FC8B5;
            text-align: center;
        }
        .pudu-sync-overlay__close {
            position: absolute;
            top: 0.35rem;
            right: 0.5rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2rem;
            height: 2rem;
            border-radius: 50%;
            color: #126B55;
            font-size: 1.45rem;
            font-weight: 600;
            line-height: 1;
            text-decoration: none;
            transition: background-color 0.15s ease, transform 0.15s ease;
        }
        .pudu-sync-overlay__close:hover,
        .pudu-sync-overlay__close:focus-visible {
            background: #E0F2EC;
            color: #0B5845;
            transform: scale(1.08);
            outline: none;
        }
        .pudu-sync-overlay--success .pudu-sync-overlay__copy strong {
            color: #126B55;
            font-size: 1.08rem;
        }
        .pudu-sync-overlay__panel {
            display: flex;
            align-items: center;
            gap: 1rem;
            width: min(540px, calc(100vw - 2rem));
            padding: 1.05rem 1.25rem;
            border: 1px solid #B9CBD4;
            border-radius: 8px;
            background: #FFFFFF;
            box-shadow: 0 18px 48px rgba(23, 42, 61, 0.2);
        }
        .pudu-sync-overlay__spinner {
            width: 28px;
            height: 28px;
            flex: 0 0 28px;
            border: 3px solid #D8E8ED;
            border-top-color: var(--pudu-teal);
            border-radius: 50%;
            animation: pudu-sync-spin 0.8s linear infinite;
        }
        .pudu-sync-overlay__copy {
            display: grid;
            flex: 1 1 auto;
            align-items: center;
            min-width: 0;
            min-height: 2rem;
        }
        .pudu-sync-overlay__copy strong {
            display: block;
            margin: 0;
            color: var(--pudu-ink);
            font-size: 1rem;
            font-weight: 680;
            line-height: 1.5;
            letter-spacing: 0;
        }
        .pudu-update-ticker {
            width: 100%;
            margin: 0.15rem 0 0.75rem;
            overflow: hidden;
            border: 1px solid #E1C16E;
            border-radius: 5px;
            background: #FFF9E9;
            color: #755313;
        }
        .pudu-update-ticker__track {
            display: inline-block;
            min-width: 100%;
            padding: 0.32rem 0;
            white-space: nowrap;
            font-size: 0.75rem;
            line-height: 1.4;
            animation: pudu-update-scroll 15s linear infinite;
        }
        .pudu-update-ticker__track::before,
        .pudu-update-ticker__track::after {
            content: '';
            display: inline-block;
            width: 100%;
        }
        @keyframes pudu-sync-spin {
            to { transform: rotate(360deg); }
        }
        @keyframes pudu-update-scroll {
            from { transform: translateX(0); }
            to { transform: translateX(-100%); }
        }
        @media (prefers-reduced-motion: reduce) {
            .pudu-sync-overlay__spinner,
            .pudu-update-ticker__track {
                animation: none;
            }
            .pudu-update-ticker__track {
                display: block;
                padding: 0.32rem 0.55rem;
                white-space: normal;
            }
            .pudu-update-ticker__track::before,
            .pudu-update-ticker__track::after {
                display: none;
            }
        }
        @media (max-width: 900px) {
            [data-testid="stMainBlockContainer"] {
                padding: 0.65rem 1rem 3rem;
            }
            .pudu-page-header {
                align-items: flex-start;
                flex-direction: column;
                gap: 0.8rem;
            }
            .pudu-page-title {
                font-size: 1.55rem;
            }
            [data-testid="stHorizontalBlock"] {
                gap: 0.75rem;
            }
        }
        @media (max-width: 520px) {
            .pudu-sync-overlay__panel {
                gap: 0.8rem;
                padding: 0.95rem 1rem;
            }
            .pudu-sync-overlay__copy strong {
                font-size: 0.94rem;
                line-height: 1.5;
            }
        }
        @media (max-width: 640px) {
            [data-testid="stMainBlockContainer"] {
                padding-left: 0.75rem;
                padding-right: 0.75rem;
            }
            div[role="radiogroup"] {
                width: 100%;
                overflow-x: auto;
            }
            div[role="radiogroup"] label {
                flex: 0 0 auto;
            }
            [data-testid="stLayoutWrapper"]:has(.pudu-section-heading) > [data-testid="stVerticalBlock"] {
                padding: 0.9rem;
            }
            .pudu-generated-title {
                align-items: flex-start;
                flex-direction: column;
                gap: 0.2rem;
            }
            .pudu-review-metric {
                padding: 0.65rem 0.55rem;
            }
            .pudu-review-metric span {
                font-size: 0.68rem;
            }
            .pudu-review-metric strong {
                font-size: 1.1rem;
            }
            .pudu-review-metrics {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .pudu-review-metric:nth-child(2) {
                border-right: 0;
            }
            .pudu-review-metric-cost {
                grid-column: 1 / -1;
                border-top: 1px solid var(--pudu-line);
                border-right: 0;
                padding-block: 0.58rem;
            }
            .pudu-review-metric-cost small {
                font-size: 0.62rem;
            }
            /* Dedicated phone layout for the request page. Every selector is
               scoped by the request marker so desktop and admin pages retain
               their current layout and behavior. */
            .stApp:has(.pudu-request-page-marker) [data-testid="stSidebar"],
            .stApp:has(.pudu-request-page-marker) [data-testid="stSidebarCollapsedControl"],
            .stApp:has(.pudu-request-page-marker) [data-testid="stSidebarCollapseButton"],
            .stApp:has(.pudu-request-page-marker) [data-testid="stExpandSidebarButton"] {
                display: none !important;
            }
            .stApp:has(.pudu-request-page-marker) [data-testid="stMainBlockContainer"] {
                max-width: 100% !important;
                padding: 0.3rem 0.55rem 6.5rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-page-header {
                margin: 0 0 0.45rem !important;
                padding: 0.25rem 0.15rem 0.5rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-page-kicker,
            .stApp:has(.pudu-request-page-marker) .pudu-page-subtitle,
            .stApp:has(.pudu-request-page-marker) .st-key-refresh_page_cache_request {
                display: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-page-title {
                font-size: 1.35rem !important;
                line-height: 1.2 !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [data-testid="stLayoutWrapper"]:has(.pudu-section-heading) > [data-testid="stVerticalBlock"] {
                gap: 0.45rem !important;
                padding: 0.72rem !important;
                border-radius: 12px !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-section-heading {
                margin-bottom: 0.35rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-section-description,
            .stApp:has(.pudu-request-page-marker) .pudu-generated-title {
                display: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-field-label {
                display: block !important;
                margin-bottom: 0.22rem !important;
                font-size: 0.82rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-inline-required-hint {
                display: block !important;
                margin-top: 0.1rem;
                font-size: 0.68rem !important;
                line-height: 1.35 !important;
            }
            .stApp:has(.pudu-request-page-marker) div[data-baseweb="input"],
            .stApp:has(.pudu-request-page-marker) div[data-baseweb="select"] > div,
            .stApp:has(.pudu-request-page-marker) .stButton > button,
            .stApp:has(.pudu-request-page-marker) [data-testid="stPopover"] > button {
                min-height: 44px !important;
            }
            .stApp:has(.pudu-request-page-marker) textarea {
                min-height: 84px !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] > [data-testid="stVerticalBlock"] {
                min-height: 0 !important;
                gap: 0.38rem !important;
                padding: 0.58rem !important;
                border-radius: 12px !important;
                transform: none !important;
                box-shadow: none !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] [data-testid="stImage"] img,
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] .pudu-product-image-placeholder {
                height: 108px !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-product-card-title {
                min-height: 0 !important;
                font-size: 0.92rem !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] [data-testid="stPopover"] > button {
                min-height: 48px !important;
                font-size: 0.92rem !important;
                font-weight: 750 !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) {
                position: fixed !important;
                inset: 0 !important;
                z-index: 1000001 !important;
                width: 100vw !important;
                min-width: 100vw !important;
                max-width: 100vw !important;
                height: 100dvh !important;
                max-height: 100dvh !important;
                margin: 0 !important;
                border-radius: 0 !important;
                overflow-y: auto !important;
                overscroll-behavior: contain;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) > div {
                gap: 0.55rem !important;
                min-height: 100% !important;
                padding: max(0.85rem, env(safe-area-inset-top)) 0.75rem
                    max(1.2rem, env(safe-area-inset-bottom)) !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
            [data-testid="stButtonGroup"] > div:last-child,
            [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] > div:last-child {
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                gap: 0.55rem !important;
                width: 100% !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
            [data-testid="stButtonGroup"] button {
                min-width: 0 !important;
                min-height: 46px !important;
                padding: 0.55rem 0.65rem !important;
                overflow-wrap: anywhere;
                white-space: normal !important;
                transform: none !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
            [data-testid="stButtonGroup"] button[aria-pressed="true"] {
                border-color: #0B57D0 !important;
                background: #0B57D0 !important;
                color: #FFFFFF !important;
                box-shadow: 0 0 0 3px rgba(11, 87, 208, 0.2) !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_compact_cart,
            .stApp:has(.pudu-request-page-marker) .st-key-request_preview {
                position: fixed !important;
                bottom: max(0.6rem, env(safe-area-inset-bottom));
                z-index: 999999 !important;
                margin: 0 !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_compact_cart {
                left: 0.65rem;
                width: calc(34vw - 0.8rem) !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_preview {
                right: 0.65rem;
                width: calc(66vw - 0.8rem) !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_compact_cart button,
            .stApp:has(.pudu-request-page-marker) .st-key-request_preview button {
                min-height: 52px !important;
                border-radius: 12px !important;
                box-shadow: 0 9px 24px rgba(21, 52, 73, 0.2) !important;
                transform: none !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-full-cart-popover-marker) {
                position: fixed !important;
                inset: auto 0 0 0 !important;
                transform: none !important;
                width: 100vw !important;
                max-width: 100vw !important;
                max-height: 82dvh !important;
                border-radius: 16px 16px 0 0 !important;
                overflow-y: auto !important;
            }
            /* Phone storefront refinement: compact two-column form and catalog,
               with category details in a single centered scroll surface. */
            .stApp:has(.pudu-request-page-marker) [data-testid="stMainBlockContainer"] {
                padding: 2.75rem 0.4rem 5.25rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar {
                display: flex !important;
                position: fixed !important;
                top: max(0.35rem, env(safe-area-inset-top));
                left: 0.4rem;
                z-index: 1000000 !important;
                width: 10.15rem !important;
                margin: 0 !important;
                padding: 0 !important;
                border: 0 !important;
                border-radius: 0 !important;
                background: transparent !important;
                box-shadow: none !important;
                backdrop-filter: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar [data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: 3.8rem 1.45rem 1.85rem 1.85rem !important;
                gap: 0.4rem !important;
                align-items: center !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar [data-testid="column"] {
                width: auto !important;
                min-width: 0 !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar [data-testid="stImage"] {
                margin: 0 !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar [data-testid="stImage"] img {
                display: block !important;
                width: 100% !important;
                height: 1.25rem !important;
                object-fit: contain !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar [data-testid="stImage"] button {
                display: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar [data-testid="stPopoverButton"] {
                min-height: 1.85rem !important;
                height: 1.85rem !important;
                padding: 0 !important;
                border: 0 !important;
                border-radius: 0 !important;
                background: transparent !important;
                font-size: 0 !important;
                box-shadow: none !important;
                width: 100% !important;
                overflow: hidden !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar button p {
                display: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar [data-testid="stIconMaterial"] {
                font-size: 1.05rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar
            [data-testid="stPopoverButton"] [aria-hidden="true"] {
                display: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_mobile_toolbar
            [data-testid="stPopoverButton"] > div {
                width: 100% !important;
                justify-content: center !important;
                gap: 0 !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-mobile-home-popover-marker),
            [data-testid="stPopoverBody"]:has(.pudu-mobile-navigation-popover-marker) {
                width: min(13rem, calc(100vw - 1rem)) !important;
                max-width: calc(100vw - 1rem) !important;
                border-radius: 12px !important;
                background: #ffffff !important;
                box-shadow: 0 12px 34px rgba(12, 38, 58, 0.22) !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-mobile-home-popover-marker) > div,
            [data-testid="stPopoverBody"]:has(.pudu-mobile-navigation-popover-marker) > div {
                gap: 0.35rem !important;
                padding: 0.55rem !important;
                background: #ffffff !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-mobile-home-popover-marker) p,
            [data-testid="stPopoverBody"]:has(.pudu-mobile-navigation-popover-marker) p,
            [data-testid="stPopoverBody"]:has(.pudu-mobile-home-popover-marker) label {
                font-size: 0.7rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-page-title {
                font-size: 1.02rem !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [data-testid="stLayoutWrapper"]:has(.pudu-section-heading) > [data-testid="stVerticalBlock"] {
                gap: 0.28rem !important;
                padding: 0.42rem !important;
                border-radius: 9px !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-section-heading {
                margin-bottom: 0.18rem !important;
                gap: 0.34rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-section-index {
                width: 1.45rem !important;
                height: 1.45rem !important;
                font-size: 0.58rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-section-title {
                font-size: 0.82rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-field-label {
                position: static !important;
                z-index: auto !important;
                display: block !important;
                width: auto !important;
                margin: 0 0 0.24rem !important;
                padding: 0 !important;
                background: transparent !important;
                font-size: 0.68rem !important;
                line-height: 1.3 !important;
                text-shadow: none !important;
                box-shadow: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section
            [data-testid="stElementContainer"]:has(.pudu-section-heading) {
                min-height: 2rem !important;
                height: auto !important;
                margin-bottom: 0.28rem !important;
                overflow: visible !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section
            [data-testid="stElementContainer"]:has(.pudu-field-label) {
                min-height: 1.05rem !important;
                height: auto !important;
                margin-bottom: 0.24rem !important;
                overflow: visible !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-inline-required-hint {
                display: none !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section [data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                column-gap: 0.38rem !important;
                row-gap: 0.62rem !important;
                align-items: start !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section [data-testid="column"] {
                width: auto !important;
                min-width: 0 !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section [data-testid="stVerticalBlock"] {
                gap: 0.24rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section [data-testid="column"] > [data-testid="stVerticalBlock"] {
                padding-top: 0.08rem !important;
                padding-bottom: 0.2rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section div[data-baseweb="input"],
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section div[data-baseweb="select"] > div {
                min-height: 28px !important;
                height: 28px !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section input {
                min-height: 26px !important;
                height: 26px !important;
                padding-top: 0.12rem !important;
                padding-bottom: 0.12rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section textarea {
                min-height: 36px !important;
                height: 36px !important;
                padding: 0.24rem 0.36rem !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section div[data-baseweb="input"],
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section div[data-baseweb="select"] > div,
            .stApp:has(.pudu-request-page-marker) .st-key-request_business_section textarea {
                box-shadow: none !important;
                text-shadow: none !important;
                filter: none !important;
            }
            .stApp:has(.pudu-request-page-marker) div[data-baseweb="input"],
            .stApp:has(.pudu-request-page-marker) div[data-baseweb="select"] > div,
            .stApp:has(.pudu-request-page-marker) .stButton > button,
            .stApp:has(.pudu-request-page-marker) [data-testid="stPopover"] > button {
                min-height: 34px !important;
                font-size: 0.68rem !important;
            }
            .stApp:has(.pudu-request-page-marker) input,
            .stApp:has(.pudu-request-page-marker) [data-baseweb="select"] * {
                font-size: 0.68rem !important;
            }
            .stApp:has(.pudu-request-page-marker) textarea {
                min-height: 52px !important;
                height: 52px !important;
                padding: 0.4rem !important;
                font-size: 0.66rem !important;
            }
            .stApp:has(.pudu-request-page-marker)
            .st-key-request_catalog_grid {
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                gap: 0.38rem !important;
                align-items: start !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] > [data-testid="stVerticalBlock"] {
                gap: 0.2rem !important;
                padding: 0.34rem !important;
                border-radius: 9px !important;
            }
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] [data-testid="stImage"] img,
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] .pudu-product-image-placeholder {
                height: 82px !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-product-card-kicker {
                margin: 0.12rem 0 0 !important;
                font-size: 0.54rem !important;
                line-height: 1.1 !important;
            }
            .stApp:has(.pudu-request-page-marker) .pudu-product-card-title {
                min-height: 1.9rem !important;
                margin: 0 !important;
                padding: 0 !important;
                font-size: 0.72rem !important;
                line-height: 1.25 !important;
                overflow-wrap: anywhere;
            }
            .stApp:has(.pudu-request-page-marker)
            [class*="st-key-request_product_card_"] [data-testid="stPopover"] > button {
                min-height: 32px !important;
                height: 32px !important;
                padding: 0.2rem 0.35rem !important;
                font-size: 0.68rem !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) {
                inset: 50% auto auto 50% !important;
                width: min(20rem, calc(100vw - 1.5rem)) !important;
                min-width: 0 !important;
                max-width: calc(100vw - 1.1rem) !important;
                height: min(84dvh, 42rem) !important;
                max-height: 84dvh !important;
                border-radius: 14px !important;
                overflow: hidden !important;
                transform: translate(-50%, -50%) !important;
                box-shadow: 0 18px 48px rgba(12, 38, 58, 0.28) !important;
                background: #ffffff !important;
                z-index: 1000005 !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-mobile-specification-popover-compact) {
                height: auto !important;
                max-height: 84dvh !important;
                overflow: visible !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) > div {
                display: flex !important;
                flex-direction: column !important;
                gap: 0.25rem !important;
                height: 100% !important;
                min-height: 0 !important;
                padding: 0.42rem !important;
                overflow: hidden !important;
                overscroll-behavior: contain !important;
                scrollbar-width: thin;
                background: #ffffff !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-mobile-specification-popover-compact) > div {
                height: auto !important;
                min-height: 0 !important;
                padding: 0.32rem 0.42rem 0.38rem !important;
                overflow: visible !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) [data-testid="stAlert"] {
                margin: 0.08rem 0 !important;
                padding: 0.22rem 0.34rem !important;
                min-height: 0 !important;
                border-radius: 6px !important;
                font-size: 0.56rem !important;
                line-height: 1.2 !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) [data-testid="stAlert"] p,
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) [data-testid="stAlert"] span {
                font-size: 0.56rem !important;
                line-height: 1.2 !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) h4 {
                margin: 0 0 0.2rem !important;
                font-size: 0.94rem !important;
                line-height: 1.2 !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) p,
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) label,
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker) span {
                font-size: 0.64rem !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
            [data-testid="stButtonGroup"] > div:last-child,
            [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] > div:last-child {
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                gap: 0.22rem !important;
            }
            [class*="st-key-request_model_line_grid_"] {
                grid-template-columns: minmax(0, 1fr) !important;
                gap: 0.22rem !important;
            }
            [class*="st-key-request_model_line_grid_"] [data-testid="stVerticalBlockBorderWrapper"] {
                padding: 0.2rem !important;
            }
            [class*="st-key-request_model_line_grid_"] [data-testid="stVerticalBlock"] {
                gap: 0.08rem !important;
            }
            [class*="st-key-request_model_line_grid_"] [data-testid="stCaptionContainer"] {
                margin: 0 !important;
                line-height: 1 !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_cart_models_v2_"]
            [data-testid="stButtonGroup"] > div:last-child {
                display: grid !important;
                grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
                gap: 0.16rem !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_cart_models_v2_"]
            [data-testid="stButtonGroup"] button {
                width: 100% !important;
                min-width: 0 !important;
                white-space: normal !important;
                overflow-wrap: anywhere !important;
                margin: 0 !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-specification-popover-marker)
            [data-testid="stButtonGroup"] button {
                min-height: 18px !important;
                height: auto !important;
                padding: 0.1rem 0.18rem !important;
                font-size: 0.54rem !important;
                line-height: 1.15 !important;
            }
            [class*="st-key-request_spec_model_scroll_"] {
                min-height: 8.5rem !important;
                height: auto !important;
                max-height: 34dvh !important;
                flex: 1 1 0 !important;
                overflow-y: auto !important;
                overscroll-behavior: contain !important;
                scrollbar-width: thin;
                padding: 0.28rem 0.24rem 0.34rem !important;
                border: 1px solid rgba(55, 91, 128, 0.13) !important;
                border-radius: 9px !important;
                background: #F3F6FA !important;
            }
            [class*="st-key-request_spec_model_scroll_"] .pudu-spec-model-heading {
                display: none !important;
                position: sticky;
                top: -0.28rem;
                z-index: 5;
                margin: 0 !important;
                padding: 0.34rem 0.36rem 0.24rem;
                color: #173B56;
                background: #F3F6FA;
                font-size: 0.66rem !important;
                font-weight: 750;
                line-height: 1.2;
            }
            [class*="st-key-request_spec_model_scroll_"] .pudu-product-model-label {
                margin: 0 !important;
                font-size: 0.6rem !important;
                line-height: 1.15 !important;
                font-weight: 650 !important;
            }
            [class*="st-key-request_spec_model_scroll_"]
            [data-testid="stElementContainer"]:has(.pudu-product-model-label) {
                min-height: 0.8rem !important;
                margin-bottom: 0.2rem !important;
                overflow: visible !important;
            }
            [class*="st-key-request_quantity_presets_"] [data-testid="stWidgetLabel"] {
                min-height: 1.05rem !important;
                margin-bottom: 0.08rem !important;
            }
            [class*="st-key-request_quantity_presets_"] [data-testid="stButtonGroup"] > div:last-child {
                gap: 0.14rem !important;
            }
            [class*="st-key-request_quantity_presets_"] [data-testid="stButtonGroup"] button {
                min-height: 18px !important;
                height: 18px !important;
                padding: 0.04rem 0.12rem !important;
                font-size: 0.5rem !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-mobile-specification-popover-compact)
            [class*="st-key-request_spec_model_scroll_"] {
                min-height: 0 !important;
                height: auto !important;
                max-height: none !important;
                flex: 0 0 auto !important;
                overflow: visible !important;
                padding-right: 0 !important;
                border: 0 !important;
                background: transparent !important;
            }
            [class*="st-key-request_spec_fixed_"] {
                position: relative !important;
                bottom: auto !important;
                z-index: 4 !important;
                flex: 0 0 auto !important;
                gap: 0.18rem !important;
                margin-top: 0.18rem !important;
                padding: 0.34rem 0.08rem 0.05rem !important;
                border-top: 1px solid rgba(20, 79, 113, 0.16) !important;
                background: #ffffff !important;
                box-shadow: 0 -8px 18px rgba(255, 255, 255, 0.96) !important;
            }
            [class*="st-key-request_language_pills_"] {
                padding: 0.18rem 0.2rem 0.2rem !important;
                border: 1px solid rgba(29, 111, 107, 0.13) !important;
                border-radius: 9px !important;
                background: #EEF8F6 !important;
            }
            [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] > div:last-child {
                gap: 0.1rem !important;
            }
            [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] button {
                min-height: 16px !important;
                padding: 0.04rem 0.08rem !important;
                font-size: 0.48rem !important;
                line-height: 1.02 !important;
            }
            [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] button p,
            [class*="st-key-request_language_pills_"] [data-testid="stButtonGroup"] button span {
                font-size: 0.48rem !important;
                line-height: 1.02 !important;
            }
            [data-testid="stPopoverBody"] [class*="st-key-request_spec_fixed_"]
            [data-testid="stButtonGroup"] > div:last-child {
                display: grid !important;
                grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
                gap: 0.16rem !important;
            }
            [class*="st-key-request_spec_fixed_"] div[data-baseweb="input"],
            [class*="st-key-request_spec_fixed_"] input,
            [class*="st-key-request_spec_fixed_"] button {
                min-height: 22px !important;
                font-size: 0.54rem !important;
            }
            [class*="st-key-request_cart_quantity_"] div[data-baseweb="input"],
            [class*="st-key-request_cart_remark_"] div[data-baseweb="input"],
            [class*="st-key-request_cart_quantity_"] input,
            [class*="st-key-request_cart_remark_"] input {
                min-height: 24px !important;
                height: 24px !important;
                padding-block: 0 !important;
            }
            [class*="st-key-request_spec_fixed_"] [data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: minmax(0, 0.72fr) minmax(0, 1.5fr) minmax(0, 0.92fr) !important;
                gap: 0.16rem !important;
                align-items: end !important;
                padding: 0.18rem 0.2rem 0.2rem !important;
                border: 1px solid rgba(173, 103, 37, 0.13) !important;
                border-radius: 9px !important;
                background: #FFF7ED !important;
            }
            [class*="st-key-request_spec_fixed_"] [class*="st-key-request_add_to_cart_"] {
                position: static !important;
                z-index: 8 !important;
                margin-top: 0.08rem !important;
                padding-top: 0.06rem !important;
                background: #ffffff !important;
            }
            [class*="st-key-request_spec_fixed_"] [class*="st-key-request_add_to_cart_"] button {
                min-height: 24px !important;
            }
            @media (max-height: 760px) {
                [class*="st-key-request_spec_model_scroll_"] {
                    min-height: 6.75rem !important;
                }
                [class*="st-key-request_spec_fixed_"] {
                    gap: 0.1rem !important;
                    margin-top: 0.08rem !important;
                    padding-top: 0.18rem !important;
                }
            }
            [class*="st-key-request_spec_fixed_"] [data-testid="column"] {
                width: auto !important;
                min-width: 0 !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_compact_cart {
                z-index: 1000003 !important;
                pointer-events: auto !important;
            }
            [data-testid="stPopoverBody"]:has(.pudu-full-cart-popover-marker) {
                z-index: 1000004 !important;
                pointer-events: auto !important;
            }
            .stApp:has(.pudu-request-page-marker) .st-key-request_compact_cart button,
            .stApp:has(.pudu-request-page-marker) .st-key-request_preview button {
                min-height: 44px !important;
                border-radius: 10px !important;
                font-size: 0.76rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(
    title: str,
    kicker: str,
    subtitle: str,
    *,
    page_key: str = "",
) -> None:
    title = ui_text(title)
    header_html = (
        f"""
        <div class="pudu-page-header">
            <div>
                <div class="pudu-page-title">{escape(title)}</div>
            </div>
        </div>
        """
    )
    if page_key:
        title_col, button_col = st.columns([8, 1.45], vertical_alignment="center")
        title_col.markdown(header_html, unsafe_allow_html=True)
        render_page_cache_refresh_button(page_key, button_col)
        return
    st.markdown(header_html, unsafe_allow_html=True)


def fullscreen_sync_overlay_html(message: str) -> str:
    return f"""
        <div class="pudu-sync-overlay" role="status" aria-live="assertive" aria-busy="true">
            <div class="pudu-sync-overlay__panel" data-sync-operation="{escape(message)}">
                <div class="pudu-sync-overlay__spinner" aria-hidden="true"></div>
                <div class="pudu-sync-overlay__copy">
                    <strong>{escape(message)}</strong>
                </div>
            </div>
        </div>
    """


def fullscreen_submission_success_html(message: str, close_label: str = "返回申请页面") -> str:
    return f"""
        <div class="pudu-sync-overlay pudu-sync-overlay--success" role="alertdialog" aria-live="assertive">
            <div class="pudu-sync-overlay__panel">
                <a class="pudu-sync-overlay__close" href="./" target="_self"
                   aria-label="{escape(close_label)}" title="{escape(close_label)}">&times;</a>
                <div class="pudu-sync-overlay__copy">
                    <strong>{escape(message)}</strong>
                </div>
            </div>
        </div>
    """


def render_request_submission_success() -> None:
    is_english = get_ui_language() == LANGUAGE_EN
    message = "Request submitted. You may close this page." if is_english else "申请已提交，您可以关闭此页面。"
    close_label = "Return to request page" if is_english else "返回申请页面"
    st.markdown(fullscreen_submission_success_html(message, close_label), unsafe_allow_html=True)


def render_inventory_plan_submission_success() -> None:
    is_english = get_ui_language() == LANGUAGE_EN
    message = (
        "The fulfillment plan for this request has been submitted. You may close this page."
        if is_english
        else "该申请单已提交配货方案，您可以关闭当前页面。"
    )
    close_label = "Return to request page" if is_english else "返回申请页面"
    st.markdown(fullscreen_submission_success_html(message, close_label), unsafe_allow_html=True)


def close_application_window() -> None:
    st.html(
        """
        <script>
        window.close();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def install_button_click_guard(delay_ms: int = 700) -> None:
    """Ignore accidental rapid repeat clicks without delaying widget edits."""
    st.components.v1.html(
        f"""
        <script>
        (() => {{
          const doc = window.parent.document;
          if (doc.body.dataset.puduClickGuard === "true") return;
          doc.body.dataset.puduClickGuard = "true";
          doc.addEventListener("click", (event) => {{
            const button = event.target.closest("button");
            if (!button || button.closest('[data-testid="stSidebarCollapseButton"]')) return;
            const lockedUntil = Number(button.dataset.puduLockedUntil || 0);
            const now = Date.now();
            if (lockedUntil > now) {{
              event.preventDefault();
              event.stopImmediatePropagation();
              return;
            }}
            button.dataset.puduLockedUntil = String(now + {int(delay_ms)});
          }}, true);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def fullscreen_sync_in_progress() -> bool:
    return bool(st.session_state.get(FULLSCREEN_SYNC_IN_PROGRESS_KEY))


@contextmanager
def fullscreen_data_sync(message: str = "正在同步数据，请稍候..."):
    st.session_state[FULLSCREEN_SYNC_IN_PROGRESS_KEY] = True
    overlay = st.empty()
    overlay.markdown(fullscreen_sync_overlay_html(message), unsafe_allow_html=True)
    try:
        yield
    finally:
        overlay.empty()
        st.session_state[FULLSCREEN_SYNC_IN_PROGRESS_KEY] = False


def render_section_header(index: str, title: str, description: str = "") -> None:
    title = ui_text(title)
    description = ui_text(description)
    tone = {
        "01": "navy",
        "02": "teal",
        "03": "coral",
        "04": "gold",
    }.get(index, "navy")
    description_html = (
        f'<div class="pudu-section-description">{escape(description)}</div>' if description else ""
    )
    st.markdown(
        f"""
        <div class="pudu-section-heading pudu-section-tone-{tone}">
            <div class="pudu-section-index">{escape(index)}</div>
            <div>
                <div class="pudu-section-title">{escape(title)}</div>
                {description_html}
            </div>
        </div>
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
        return str(st.secrets.get("APPROVAL_VIEW_PASSWORD", DEFAULT_APPROVAL_PASSWORD))
    except (FileNotFoundError, KeyError, AttributeError):
        return DEFAULT_APPROVAL_PASSWORD


def get_secret_value(name: str, default: str = "") -> str:
    try:
        secret_value = st.secrets.get(name)
    except (FileNotFoundError, KeyError, AttributeError):
        secret_value = None
    if secret_value not in (None, ""):
        return str(secret_value).strip()
    return str(os.getenv(name, default)).strip()


def github_cache_refresh_token() -> str:
    return get_secret_value("GITHUB_CACHE_REFRESH_TOKEN")


def trigger_github_cache_refresh() -> None:
    token = github_cache_refresh_token()
    if not token:
        raise RuntimeError("Streamlit Secrets 尚未配置 GITHUB_CACHE_REFRESH_TOKEN。")
    payload = json.dumps({"event_type": "refresh-static-cache"}).encode("utf-8")
    api_request = url_request.Request(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/dispatches",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "pudu-material-operations",
        },
    )
    try:
        with url_request.urlopen(api_request, timeout=20) as response:
            if response.status != 204:
                raise RuntimeError(f"GitHub 返回了异常状态码：{response.status}")
    except url_error.HTTPError as exc:
        raise RuntimeError(f"GitHub 缓存发布任务触发失败（HTTP {exc.code}）。") from exc
    except url_error.URLError as exc:
        raise RuntimeError("无法连接 GitHub，请稍后重试。") from exc


def feishu_app_id() -> str:
    return get_secret_value("FEISHU_APP_ID")


def feishu_app_secret() -> str:
    return get_secret_value("FEISHU_APP_SECRET")


def feishu_approval_writeback_app_id() -> str:
    """Return the dedicated app ID for approval callbacks and writeback APIs."""
    return get_secret_value("FEISHU_APPROVAL_WRITEBACK_APP_ID")


def feishu_approval_writeback_app_secret() -> str:
    """Return the dedicated app secret for approval callbacks and writeback APIs."""
    return get_secret_value("FEISHU_APPROVAL_WRITEBACK_APP_SECRET")


def feishu_approval_writeback_config_args() -> tuple[str, str]:
    return (
        feishu_approval_writeback_app_id(),
        feishu_approval_writeback_app_secret(),
    )


def feishu_bitable_app_token() -> str:
    return get_secret_value("FEISHU_BITABLE_APP_TOKEN")


def corporate_apparel_source_app_token() -> str:
    """Return the writable administrative Base token behind the synced table."""
    return get_secret_value("FEISHU_CORPORATE_APPAREL_SOURCE_APP_TOKEN")


def corporate_apparel_source_client() -> FeishuBitableClient:
    app_token = corporate_apparel_source_app_token()
    if not app_token:
        raise RuntimeError(
            "企业文化衫行政源表尚未完成应用授权：请将‘营销物料管理’应用添加为源表协作者，"
            "并配置 FEISHU_CORPORATE_APPAREL_SOURCE_APP_TOKEN。"
        )
    return get_feishu_bitable_client(feishu_app_id(), feishu_app_secret(), app_token)


def feishu_bitable_web_url(table_name: str) -> str:
    table_id = feishu_table_id(table_name)
    configured_url = get_secret_value("FEISHU_BITABLE_WEB_URL")
    base_url = configured_url or (
        f"https://pudutech.feishu.cn/base/{url_parse.quote(feishu_bitable_app_token())}"
    )
    parsed = url_parse.urlparse(base_url)
    query = dict(url_parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["table"] = table_id
    query.pop("view", None)
    return url_parse.urlunparse(parsed._replace(query=url_parse.urlencode(query)))


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
            numeric = float(value)  # type: ignore[arg-type]
            return int(numeric) if numeric.is_integer() else numeric
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


def set_yes_no_field(
    table_name: str,
    fields: dict[str, object],
    field_name: str,
    enabled: bool,
) -> None:
    if not feishu_has_field(table_name, field_name):
        return
    fields[field_name] = bool(enabled) if feishu_field_type(table_name, field_name) == 7 else (
        "是" if enabled else "否"
    )


def set_feishu_unit_price(
    table_name: str,
    fields: dict[str, object],
    value: object,
) -> None:
    set_first_plain_field(table_name, fields, list(UNIT_PRICE_FIELD_CANDIDATES), value)


def request_material_unit_price_rmb(
    material_fields: dict[str, object],
    category_price_rmb: float = 0.0,
) -> float:
    """Return the current RMB category price used to freeze a request line."""
    price = feishu_float(material_fields, UNIT_PRICE_RMB_FIELD)
    return round(price if price else float(category_price_rmb or 0), 4)


def request_line_subtotal_rmb(unit_price_rmb: object, quantity: object) -> float:
    return round(float(unit_price_rmb or 0) * int(quantity or 0), 2)


def request_lines_total_rmb(lines: list[dict[str, object]]) -> float:
    total = 0.0
    for line in lines:
        subtotal = float(line.get("subtotal_rmb") or 0)
        if not subtotal:
            subtotal = request_line_subtotal_rmb(
                line.get("unit_price_rmb"), line.get("quantity")
            )
        total += subtotal
    return round(total, 2)


def format_rmb(value: object) -> str:
    return f"¥{float(value or 0):,.2f}"


def material_price_sync_updates(
    material_rows: list[dict], category_rows: list[dict]
) -> list[dict[str, object]]:
    """Build USD source-price updates so material RMB formulas mirror categories."""
    category_price_by_id = {
        feishu_record_id(row): feishu_float_any(
            feishu_fields(row), list(UNIT_PRICE_FIELD_CANDIDATES)
        )
        for row in category_rows
        if feishu_record_id(row)
    }
    updates: list[dict[str, object]] = []
    for row in material_rows:
        fields = feishu_fields(row)
        category_ids = feishu_link_ids(fields, "品类关联")
        if not category_ids or category_ids[0] not in category_price_by_id:
            continue
        expected = float(category_price_by_id[category_ids[0]])
        current = feishu_float_any(fields, list(UNIT_PRICE_FIELD_CANDIDATES))
        if abs(current - expected) < 0.000001:
            continue
        update_fields: dict[str, object] = {}
        set_feishu_unit_price(MATERIAL_TABLE_NAME, update_fields, expected)
        if update_fields:
            updates.append(
                {"record_id": feishu_record_id(row), "fields": update_fields}
            )
    return updates


def sync_material_unit_prices_from_categories() -> int:
    updates = material_price_sync_updates(
        fresh_feishu_rows(MATERIAL_TABLE_NAME), fresh_feishu_rows(CATEGORY_TABLE_NAME)
    )
    return feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, updates)


def set_feishu_customs_code(
    table_name: str,
    fields: dict[str, object],
    value: object,
) -> None:
    field_name = "海关编码"
    if not feishu_has_field(table_name, field_name):
        return
    text = str(value or "").strip()
    if not text:
        return
    if feishu_field_type(table_name, field_name) == 2:
        if re.fullmatch(r"[+-]?\d+", text):
            fields[field_name] = int(text)
            return
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError("飞书中的海关编码为数字字段，请只填写数字。") from exc
        if not pd.notna(number) or number in (float("inf"), float("-inf")):
            raise ValueError("海关编码必须是有效数字。")
        fields[field_name] = number
        return
    if feishu_accepts_plain_value(table_name, field_name):
        fields[field_name] = text


def set_shipping_category_fields(
    fields: dict[str, object],
    commercial_invoice_name: object,
    packing_list_product_type: object,
) -> None:
    invoice_name = str(commercial_invoice_name or "").strip()
    packing_type = str(packing_list_product_type or "").strip()
    if feishu_has_field(CATEGORY_TABLE_NAME, COMMERCIAL_INVOICE_NAME_FIELD):
        fields[COMMERCIAL_INVOICE_NAME_FIELD] = invoice_name
    if feishu_has_field(CATEGORY_TABLE_NAME, PACKING_LIST_PRODUCT_TYPE_FIELD):
        fields[PACKING_LIST_PRODUCT_TYPE_FIELD] = packing_type


def set_first_person_or_plain_field(
    table_name: str,
    fields: dict[str, object],
    candidates: list[str],
    display_value: object,
    open_id: object,
) -> None:
    normalized_open_id = str(open_id or "").strip()
    for field_name in candidates:
        if not feishu_has_field(table_name, field_name):
            continue
        if feishu_field_type(table_name, field_name) == 11 and normalized_open_id:
            fields[field_name] = [{"id": normalized_open_id}]
            return
        if display_value not in (None, "") and feishu_accepts_plain_value(table_name, field_name):
            fields[field_name] = display_value
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


def feishu_batch_update_record_fields(table_name: str, records: list[dict]) -> int:
    client = feishu_client()
    if client is None:
        return 0
    writable_records = [
        {
            "record_id": str(record.get("record_id") or ""),
            "fields": filter_feishu_fields(table_name, dict(record.get("fields") or {})),
        }
        for record in records
    ]
    writable_records = [
        record for record in writable_records if record["record_id"] and record["fields"]
    ]
    updated = 0
    for start in range(0, len(writable_records), 1000):
        batch = writable_records[start : start + 1000]
        updated += len(client.batch_update_records(feishu_table_id(table_name), batch))
    return updated


def feishu_batch_delete_record_ids(table_name: str, record_ids: list[str]) -> int:
    client = feishu_client()
    if client is None:
        return 0
    normalized_ids = unique_preserve([str(record_id) for record_id in record_ids if record_id])
    for start in range(0, len(normalized_ids), 500):
        client.batch_delete_records(feishu_table_id(table_name), normalized_ids[start : start + 500])
    return len(normalized_ids)


def material_model_link_field_name() -> str:
    fields = feishu_table_fields(MATERIAL_TABLE_NAME)
    for field_name in MODEL_LINK_FIELD_CANDIDATES:
        if field_name in fields and fields[field_name].get("type") in {18, 21}:
            return field_name
    return ""


def material_language_link_field_name() -> str:
    fields = feishu_table_fields(MATERIAL_TABLE_NAME)
    for field_name in LANGUAGE_LINK_FIELD_CANDIDATES:
        if field_name in fields and fields[field_name].get("type") in {18, 21}:
            return field_name
    return ""


def ensure_feishu_model_records(models: list[str]) -> tuple[str, dict[str, str]]:
    normalized_models = unique_preserve(
        [str(model).strip() or NO_MODEL_TEXT for model in models if str(model).strip()]
    )
    link_field = material_model_link_field_name()
    if normalized_models and not link_field:
        refresh_feishu_schema_cache()
        link_field = material_model_link_field_name()
    if not normalized_models or not link_field:
        return link_field, {}
    if MODEL_TABLE_NAME not in feishu_schema().get("tables", {}):
        refresh_feishu_schema_cache()
    if MODEL_TABLE_NAME not in feishu_schema().get("tables", {}):
        return link_field, {}

    rows = fresh_feishu_rows(MODEL_TABLE_NAME)
    model_ids: dict[str, str] = {}
    max_code = 0
    for row in rows:
        fields = feishu_fields(row)
        model = feishu_text(fields, "产品型号").strip()
        record_id = feishu_record_id(row)
        if model and record_id and model not in model_ids:
            model_ids[model] = record_id
        code = feishu_text(fields, "产品型号编码").strip()
        if code.isdigit():
            max_code = max(max_code, int(code))

    missing_models = [model for model in normalized_models if model not in model_ids]
    if missing_models:
        records = [
            {
                "产品型号编码": str(max_code + index),
                "产品型号": model,
                "启用状态": STATUS_ACTIVE,
            }
            for index, model in enumerate(missing_models, start=1)
        ]
        created = feishu_batch_create_records(MODEL_TABLE_NAME, records)
        for model, row in zip(missing_models, created):
            record_id = feishu_record_id(row)
            if record_id:
                model_ids[model] = record_id
    return link_field, {model: model_ids[model] for model in normalized_models if model in model_ids}


def add_material_model_link(
    fields: dict[str, object],
    model: str,
    link_field: str,
    model_ids: dict[str, str],
) -> None:
    model_record_id = model_ids.get(model.strip() or NO_MODEL_TEXT, "")
    if link_field and model_record_id:
        fields[link_field] = [model_record_id]


def feishu_language_name(fields: dict) -> str:
    return feishu_text(fields, "语言种类").strip() or feishu_text(fields, "语种").strip()


def ensure_feishu_language_records(languages: list[str]) -> tuple[str, dict[str, str]]:
    normalized_languages = unique_preserve(
        [str(language).strip() or NO_LANGUAGE_TEXT for language in languages if str(language).strip()]
    )
    link_field = material_language_link_field_name()
    if normalized_languages and not link_field:
        refresh_feishu_schema_cache()
        link_field = material_language_link_field_name()
    if not normalized_languages or not link_field:
        return link_field, {}
    if LANGUAGE_TABLE_NAME not in feishu_schema().get("tables", {}):
        refresh_feishu_schema_cache()
    if LANGUAGE_TABLE_NAME not in feishu_schema().get("tables", {}):
        return link_field, {}

    try:
        rows = fresh_feishu_rows(LANGUAGE_TABLE_NAME)
    except FeishuBitableError:
        return link_field, {}

    language_ids: dict[str, str] = {}
    for row in rows:
        language = feishu_language_name(feishu_fields(row))
        record_id = feishu_record_id(row)
        if language and record_id and language not in language_ids:
            language_ids[language] = record_id

    missing_languages = [language for language in normalized_languages if language not in language_ids]
    if missing_languages:
        records = [
            {
                "语言种类": language,
                "启用状态": STATUS_ACTIVE,
            }
            for language in missing_languages
        ]
        created = feishu_batch_create_records(LANGUAGE_TABLE_NAME, records)
        for language, row in zip(missing_languages, created):
            record_id = feishu_record_id(row)
            if record_id:
                language_ids[language] = record_id
    return link_field, {
        language: language_ids[language]
        for language in normalized_languages
        if language in language_ids
    }


def add_material_language_link(
    fields: dict[str, object],
    language: str,
    link_field: str,
    language_ids: dict[str, str],
) -> None:
    language_record_id = language_ids.get(language.strip() or NO_LANGUAGE_TEXT, "")
    if link_field and language_record_id:
        fields[link_field] = [language_record_id]


def dimension_management_config(kind: str) -> dict[str, object]:
    if kind == "model":
        return {
            "table": MODEL_TABLE_NAME,
            "name_field": "产品型号",
            "code_field": "产品型号编码",
            "material_name_field": "产品型号",
            "link_fields": MODEL_LINK_FIELD_CANDIDATES,
            "label": "型号",
        }
    if kind == "language":
        return {
            "table": LANGUAGE_TABLE_NAME,
            "name_field": "语言种类",
            "code_field": "",
            "material_name_field": "语种",
            "link_fields": LANGUAGE_LINK_FIELD_CANDIDATES,
            "label": "语种",
        }
    if kind == "region":
        return {
            "table": REGION_TABLE_NAME,
            "name_field": "战区名称",
            "code_field": "",
            "material_name_field": "战区管理",
            "link_fields": (),
            "label": "战区",
        }
    raise ValueError("不支持的基础维度类型。")


def dimension_management_records(kind: str, rows: list[dict] | None = None) -> list[dict[str, str]]:
    config = dimension_management_config(kind)
    table_name = str(config["table"])
    name_field = str(config["name_field"])
    code_field = str(config["code_field"])
    records: list[dict[str, str]] = []
    for row in list(rows if rows is not None else safe_feishu_rows(table_name)):
        fields = feishu_fields(row)
        name = (
            feishu_language_name(fields)
            if kind == "language"
            else feishu_text(fields, name_field).strip()
        )
        record_id = feishu_record_id(row)
        if name and record_id:
            records.append(
                {
                    "record_id": record_id,
                    "name": name,
                    "code": feishu_text(fields, code_field).strip() if code_field else "",
                    "status": normalize_enabled_status(feishu_text(fields, "启用状态")),
                    "zh_page_name": (
                        feishu_text(fields, "中文页面名称").strip() or name
                        if kind == "model" else name
                    ),
                    "en_page_name": (
                        feishu_text(fields, "英文页面名称").strip() or name
                        if kind == "model" else name
                    ),
                    "product_line": (
                        feishu_text(fields, "产品线").strip()
                        if kind == "model" else ""
                    ),
                    "model_type": (
                        feishu_text(fields, MODEL_TYPE_FIELD).strip() or MODEL_TYPE_REGULAR
                        if kind == "model" else ""
                    ),
                }
            )
    records.sort(key=lambda item: item["name"].casefold())
    return records


def filter_dimension_association_dataframe(
    association_df: pd.DataFrame,
    query: object,
    counterpart_column: str,
) -> pd.DataFrame:
    keyword = str(query or "").strip().casefold()
    if not keyword or association_df.empty:
        return association_df.copy()
    searchable = (
        association_df["物料品类"].fillna("").astype(str)
        + " "
        + association_df[counterpart_column].fillna("").astype(str)
    ).str.casefold()
    return association_df[searchable.str.contains(keyword, regex=False)].reset_index(drop=True)


def dimension_association_category_names(
    kind: str,
    categories: list[dict],
    dimension_name: object,
) -> list[str]:
    normalized_dimension = normalize_option_label(dimension_name).casefold()
    if kind == "region":
        return [
            str(item.get("category") or "")
            for item in categories
            if str(item.get("category") or "")
            and str(item.get("category_definition") or "") == CATEGORY_DEFINITION_CULTURAL
        ]
    no_dimension_value = NO_MODEL_TEXT if kind == "model" else NO_LANGUAGE_TEXT
    editing_no_dimension = normalized_dimension == normalize_option_label(no_dimension_value).casefold()
    return [
        str(item.get("category") or "")
        for item in categories
        if str(item.get("category") or "")
        and (
            bool(item.get("no_model" if kind == "model" else "no_language"))
            == editing_no_dimension
        )
    ]


def persist_dimension_association_edits(
    selection_state_key: str,
    editor_state_key: str,
    row_keys: list[list[str]],
) -> None:
    selected = {
        (str(item[0]), str(item[1]))
        for item in list(st.session_state.get(selection_state_key) or [])
        if isinstance(item, (list, tuple)) and len(item) >= 2
    }
    editor_state = st.session_state.get(editor_state_key) or {}
    edited_rows = dict(editor_state.get("edited_rows") or {}) if isinstance(editor_state, dict) else {}
    for row_index, changes in edited_rows.items():
        try:
            category, counterpart = row_keys[int(row_index)]
        except (IndexError, TypeError, ValueError):
            continue
        key = (str(category), str(counterpart))
        if bool(dict(changes).get("关联")):
            selected.add(key)
        elif "关联" in dict(changes):
            selected.discard(key)
    st.session_state[selection_state_key] = [list(item) for item in sorted(selected)]


def dimension_material_references(kind: str, record_id: str, name: str) -> list[str]:
    config = dimension_management_config(kind)
    target_name = normalize_option_label(name).casefold()
    referenced_ids: list[str] = []
    source_table = CULTURAL_MATERIAL_TABLE_NAME if kind == "region" else MATERIAL_TABLE_NAME
    for row in fresh_feishu_rows(source_table):
        fields = feishu_fields(row)
        linked_ids = feishu_link_ids_any(fields, list(config["link_fields"]))  # type: ignore[arg-type]
        material_name = feishu_text(fields, str(config["material_name_field"]))
        if record_id in linked_ids or normalize_option_label(material_name).casefold() == target_name:
            referenced_ids.append(feishu_record_id(row))
    return unique_preserve([value for value in referenced_ids if value])


def dimension_association_plan(
    kind: str,
    operation: str,
    current_name: str,
    target_name: str,
    selected_keys: list[list[str]] | list[tuple[str, str]],
    material_records: list[dict],
    category_records: list[dict],
) -> list[dict[str, object]]:
    """Build the exact material-row changes shown in review and executed by Worker."""
    selected = {
        (str(key[0]).strip(), str(key[1]).strip())
        for key in selected_keys
        if len(key) >= 2 and str(key[0]).strip() and str(key[1]).strip()
    }
    category_ids = {
        str(item.get("category") or ""): str(item.get("record_id") or "")
        for item in category_records
    }
    if kind == "region":
        existing_by_key = {
            (str(row.get("category") or ""), str(row.get("model") or "")): row
            for row in material_records
            if normalize_option_label(str(row.get("region") or "")).casefold()
            == normalize_option_label(current_name).casefold()
        }
    else:
        existing_by_key = {
        (
            str(row.get("category") or ""),
            str(row.get("language") if kind == "model" else row.get("model") or ""),
        ): row
        for row in material_records
        if normalize_option_label(
            str(row.get("model") if kind == "model" else row.get("language") or "")
        ).casefold()
        == normalize_option_label(current_name).casefold()
        }
    changes: list[dict[str, object]] = []
    if operation == "delete":
        selected = set(existing_by_key)
    for key in sorted(set(existing_by_key) | selected):
        existing = existing_by_key.get(key)
        if operation == "delete":
            if existing is not None:
                changes.append({
                    "action": "delete", "record_id": str(existing.get("record_id") or ""),
                    "material_code": str(existing.get("material_code") or ""), "category": key[0],
                    "model": str(existing.get("model") or NO_MODEL_TEXT),
                    "language": str(existing.get("language") or NO_LANGUAGE_TEXT),
                    "region": str(existing.get("region") or ""),
                    "quantity": int(existing.get("quantity") or 0),
                    "status": normalize_enabled_status(existing.get("status")),
                    "request_visible": normalize_request_page_visibility(existing.get("request_visible")),
                })
        elif key in selected:
            if existing is None:
                changes.append({
                    "action": "create", "category": key[0], "category_record_id": category_ids.get(key[0], ""),
                    "model": target_name if kind == "model" else key[1],
                    "language": key[1] if kind == "model" else (target_name if kind == "language" else ""),
                    "region": target_name if kind == "region" else "",
                    "quantity": 0, "unit_price": 0.0, "customs_code": "", "status": STATUS_ACTIVE,
                    "request_visible": REQUEST_PAGE_VISIBLE_VALUE,
                })
            elif operation == "edit" and target_name != current_name:
                changes.append({
                    "action": "update", "record_id": str(existing.get("record_id") or ""),
                    "material_code": str(existing.get("material_code") or ""),
                    "category": key[0], "category_record_id": category_ids.get(key[0], ""),
                    "model": target_name if kind == "model" else str(existing.get("model") or NO_MODEL_TEXT),
                    "language": str(existing.get("language") or NO_LANGUAGE_TEXT) if kind in {"model", "region"} else target_name,
                    "region": target_name if kind == "region" else str(existing.get("region") or ""),
                    "quantity": int(existing.get("quantity") or 0),
                    "unit_price": float(existing.get("unit_price") or 0),
                    "customs_code": str(existing.get("customs_code") or ""),
                    "status": normalize_enabled_status(existing.get("status")),
                    "request_visible": normalize_request_page_visibility(existing.get("request_visible")),
                })
        elif existing is not None:
            changes.append({
                "action": "delete", "record_id": str(existing.get("record_id") or ""),
                "material_code": str(existing.get("material_code") or ""), "category": key[0],
                "model": str(existing.get("model") or NO_MODEL_TEXT),
                "language": str(existing.get("language") or NO_LANGUAGE_TEXT),
                "region": str(existing.get("region") or ""),
                "quantity": int(existing.get("quantity") or 0),
                "status": normalize_enabled_status(existing.get("status")),
                "request_visible": normalize_request_page_visibility(existing.get("request_visible")),
            })
    return changes


def dimension_change_dataframe(changes: list[dict[str, object]]) -> pd.DataFrame:
    labels = {"create": "新增", "update": "修改", "delete": "删除"}
    return pd.DataFrame([{
        "操作": labels.get(str(item.get("action") or ""), ""),
        "物料编码": str(item.get("material_code") or "待生成"),
        "物料品类": str(item.get("category") or ""),
        "产品型号": str(item.get("model") or NO_MODEL_TEXT),
        "语种": str(item.get("language") or NO_LANGUAGE_TEXT),
        "战区": str(item.get("region") or ""),
        "库存数量": int(item.get("quantity") or 0),
        "启用状态": normalize_enabled_status(item.get("status")),
        "申领页显示": normalize_request_page_visibility(item.get("request_visible")),
    } for item in changes])


def material_model_name_updates(
    material_rows: list[dict],
    model_rows: list[dict],
) -> list[dict[str, object]]:
    model_name_by_id = {
        feishu_record_id(row): feishu_text(feishu_fields(row), "产品型号").strip()
        for row in model_rows
        if feishu_record_id(row)
        and feishu_text(feishu_fields(row), "产品型号").strip()
    }
    updates: list[dict[str, object]] = []
    for row in material_rows:
        fields = feishu_fields(row)
        linked_name = next(
            (
                model_name_by_id.get(model_id, "")
                for model_id in feishu_link_ids_any(
                    fields,
                    list(MODEL_LINK_FIELD_CANDIDATES),
                )
                if model_name_by_id.get(model_id, "")
            ),
            "",
        )
        if not linked_name or feishu_text(fields, "产品型号").strip() == linked_name:
            continue
        record_id = feishu_record_id(row)
        if record_id:
            updates.append(
                {"record_id": record_id, "fields": {"产品型号": linked_name}}
            )
    return updates


def material_rows_with_dimension_model_names(
    material_rows: list[dict],
    model_rows: list[dict],
) -> list[dict]:
    updates_by_id = {
        str(update["record_id"]): str(dict(update["fields"])["产品型号"])
        for update in material_model_name_updates(material_rows, model_rows)
    }
    normalized_rows: list[dict] = []
    for row in material_rows:
        normalized = dict(row)
        record_id = feishu_record_id(row)
        if record_id in updates_by_id:
            fields = feishu_fields(row)
            fields["产品型号"] = updates_by_id[record_id]
            normalized["fields"] = fields
        normalized_rows.append(normalized)
    return normalized_rows


def sync_material_model_names_from_dimension(
    material_rows: list[dict] | None = None,
    model_rows: list[dict] | None = None,
) -> int:
    resolved_material_rows = list(
        material_rows if material_rows is not None else fresh_feishu_rows(MATERIAL_TABLE_NAME)
    )


    resolved_model_rows = list(
        model_rows if model_rows is not None else fresh_feishu_rows(MODEL_TABLE_NAME)
    )
    updates = material_model_name_updates(resolved_material_rows, resolved_model_rows)
    return feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, updates) if updates else 0


def sync_new_request_model_material_rows() -> dict[str, object]:
    """Attach newly added models and create their flyer/roll-up request rows once."""
    model_rows = fresh_feishu_rows(MODEL_TABLE_NAME)
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    language_rows = fresh_feishu_rows(LANGUAGE_TABLE_NAME)
    parsed_materials = [
        parsed for row in material_rows
        if (parsed := parse_feishu_inventory_record(row)) is not None
    ]
    linked_model_ids = {
        model_id
        for row in material_rows
        for model_id in feishu_link_ids_any(feishu_fields(row), list(MODEL_LINK_FIELD_CANDIDATES))
    }
    new_models = [
        row for row in model_rows
        if feishu_record_id(row) not in linked_model_ids
        and feishu_text(feishu_fields(row), MODEL_TYPE_FIELD).strip() == MODEL_TYPE_REGULAR
        and feishu_text(feishu_fields(row), "产品型号").strip() not in {"", NO_MODEL_TEXT}
    ]
    if not new_models:
        return {"model_count": 0, "created_count": 0, "linked_count": 0}
    category_ids = {
        feishu_text(feishu_fields(row), "物料品类"): feishu_record_id(row)
        for row in category_rows
    }
    language_ids = {
        feishu_language_name(feishu_fields(row)): feishu_record_id(row)
        for row in language_rows
        if feishu_language_name(feishu_fields(row)) and feishu_record_id(row)
    }
    material_by_key = {
        (str(item.get("category") or ""), str(item.get("model") or NO_MODEL_TEXT), str(item.get("language") or NO_LANGUAGE_TEXT)): item
        for item in parsed_materials
    }
    category_languages = {
        category: sort_languages(unique_preserve([
            str(item.get("language") or NO_LANGUAGE_TEXT)
            for item in parsed_materials if str(item.get("category") or "") == category
        ]))
        for category in AUTO_REQUEST_MODEL_CATEGORIES
    }
    next_codes = iter(next_material_codes_from_records(
        parsed_materials,
        len(new_models) * sum(len(values) for values in category_languages.values()),
    ))
    updates: list[dict[str, object]] = []
    creates: list[dict[str, object]] = []
    linked_at = feishu_datetime_value(
        MATERIAL_TABLE_NAME,
        INVENTORY_ZERO_SINCE_FIELD,
        datetime.now(),
    )
    for model_row in new_models:
        model_id = feishu_record_id(model_row)
        model = feishu_text(feishu_fields(model_row), "产品型号").strip()
        for category in AUTO_REQUEST_MODEL_CATEGORIES:
            category_id = category_ids.get(category, "")
            if not category_id:
                continue
            for language in category_languages.get(category, []):
                existing = material_by_key.get((category, model, language))
                if existing:
                    updates.append({
                        "record_id": str(existing.get("record_id") or ""),
                        "fields": {
                            "型号关联": [model_id],
                            "启用状态": STATUS_ACTIVE,
                            REQUEST_PAGE_VISIBILITY_FIELD: REQUEST_PAGE_VISIBLE_VALUE,
                            INVENTORY_ZERO_SINCE_FIELD: linked_at,
                        },
                    })
                    continue
                fields: dict[str, object] = {
                    "物料编码": next(next_codes),
                    "物料品类": category,
                    "产品型号": model,
                    "语种": language,
                    "当前库存": 0,
                    "备注": "",
                    "启用状态": STATUS_ACTIVE,
                    REQUEST_PAGE_VISIBILITY_FIELD: REQUEST_PAGE_VISIBLE_VALUE,
                    "品类关联": [category_id],
                    "型号关联": [model_id],
                }
                language_id = language_ids.get(language, "")
                if language_id:
                    fields[material_language_link_field_name() or "语种关联"] = [language_id]
                category_row = next(
                    (row for row in category_rows if feishu_record_id(row) == category_id),
                    {},
                )
                set_feishu_unit_price(
                    MATERIAL_TABLE_NAME,
                    fields,
                    feishu_float_any(
                        feishu_fields(category_row), list(UNIT_PRICE_FIELD_CANDIDATES)
                    ),
                )
                creates.append(fields)
    updated_count = feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, updates)
    created_rows = feishu_batch_create_records(MATERIAL_TABLE_NAME, creates) if creates else []
    return {
        "model_count": len(new_models),
        "created_count": len(created_rows),
        "linked_count": updated_count,
        "models": [feishu_text(feishu_fields(row), "产品型号") for row in new_models],
    }


def execute_dimension_management(draft: dict[str, object]) -> dict[str, object]:
    kind = str(draft.get("kind") or "")
    if kind == "region":
        return execute_region_dimension_management(draft)
    operation = str(draft.get("operation") or "")
    config = dimension_management_config(kind)
    table_name = str(config["table"])
    name_field = str(config["name_field"])
    code_field = str(config["code_field"])
    label = str(config["label"])
    records = dimension_management_records(kind, fresh_feishu_rows(table_name))
    by_id = {item["record_id"]: item for item in records}
    normalized_names = {
        normalize_option_label(item["name"]).casefold(): item for item in records
    }
    record_id = str(draft.get("record_id") or "")
    name = str(draft.get("name") or "").strip()
    zh_page_name = str(draft.get("zh_page_name") or name).strip()
    en_page_name = str(draft.get("en_page_name") or name).strip()
    product_line = str(draft.get("product_line") or "").strip()
    model_type = str(draft.get("model_type") or MODEL_TYPE_REGULAR).strip()
    if model_type not in MODEL_TYPE_OPTIONS:
        model_type = MODEL_TYPE_REGULAR
    status = normalize_enabled_status(draft.get("status"))
    dimension_created_count = 0
    if operation == "create":
        if not name:
            raise ValueError(f"请填写{label}名称。")
        if normalize_option_label(name).casefold() in normalized_names:
            raise ValueError(f"该{label}已经存在。")
        fields: dict[str, object] = {name_field: name, "启用状态": status}
        if kind == "model":
            fields.update({
                "中文页面名称": zh_page_name,
                "英文页面名称": en_page_name,
                "产品线": product_line,
                MODEL_TYPE_FIELD: model_type,
            })
        if code_field:
            numeric_codes = [int(item["code"]) for item in records if item["code"].isdigit()]
            fields[code_field] = str(max(numeric_codes, default=0) + 1)
        created = feishu_batch_create_records(table_name, [fields])
        record_id = feishu_record_id(created[0] if created else {})
        if not record_id:
            raise RuntimeError(f"新增{label}后未返回记录 ID。")
        dimension_created_count = len(created)
    if operation != "create" and record_id not in by_id:
        raise ValueError(f"所选{label}不存在，请刷新页面后重试。")
    current = by_id.get(record_id, {"name": name})
    if operation == "edit":
        if not name:
            raise ValueError(f"请填写{label}名称。")
        duplicate = normalized_names.get(normalize_option_label(name).casefold())
        if duplicate and duplicate["record_id"] != record_id:
            raise ValueError(f"该{label}名称已经存在。")
        dimension_fields: dict[str, object] = {name_field: name, "启用状态": status}
        if kind == "model":
            dimension_fields.update({
                "中文页面名称": zh_page_name,
                "英文页面名称": en_page_name,
                "产品线": product_line,
                MODEL_TYPE_FIELD: model_type,
            })
        feishu_update_record_fields(table_name, record_id, dimension_fields)
    elif operation not in {"create", "delete"}:
        raise ValueError("不支持的基础维度管理操作。")

    changes = [dict(item) for item in list(draft.get("changes") or []) if isinstance(item, dict)]
    if "changes" not in draft:
        if operation == "create":
            return {"operation": operation, "created_count": dimension_created_count}
        if operation == "edit":
            material_updates = [
                {"record_id": material_id, "fields": {str(config["material_name_field"]): name}}
                for material_id in dimension_material_references(kind, record_id, str(current["name"]))
            ]
            updated_material_count = feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, material_updates)
            return {"operation": operation, "updated_count": 1, "updated_material_count": updated_material_count}
        references = dimension_material_references(kind, record_id, str(current["name"]))
        deleted_material_count = feishu_batch_delete_record_ids(MATERIAL_TABLE_NAME, references)
        deleted_count = feishu_batch_delete_record_ids(table_name, [record_id])
        return {"operation": operation, "deleted_count": deleted_count, "deleted_material_count": deleted_material_count}
    all_inventory = [
        parsed for row in fresh_feishu_rows(MATERIAL_TABLE_NAME)
        if (parsed := parse_feishu_inventory_record(row)) is not None
    ]
    current_by_id = {str(item.get("record_id") or ""): item for item in all_inventory}
    delete_ids: list[str] = []
    update_rows: list[dict[str, object]] = []
    create_changes: list[dict[str, object]] = []
    model_link_field, model_ids = ensure_feishu_model_records(
        unique_preserve([str(item.get("model") or NO_MODEL_TEXT) for item in changes])
    )
    language_link_field, language_ids = ensure_feishu_language_records(
        unique_preserve([str(item.get("language") or NO_LANGUAGE_TEXT) for item in changes])
    )
    for item in changes:
        action = str(item.get("action") or "")
        item_id = str(item.get("record_id") or "")
        if action in {"update", "delete"} and item_id not in current_by_id:
            raise RuntimeError("预览后关联物料已变化，请返回刷新后重新提交。")
        if action == "delete":
            delete_ids.append(item_id)
        elif action == "create":
            create_changes.append(item)
        elif action == "update":
            fields: dict[str, object] = {
                "产品型号": item.get("model"), "语种": item.get("language"),
                "启用状态": normalize_enabled_status(item.get("status")),
                REQUEST_PAGE_VISIBILITY_FIELD: normalize_request_page_visibility(item.get("request_visible")),
            }
            add_material_model_link(fields, str(item.get("model") or NO_MODEL_TEXT), model_link_field, model_ids)
            add_material_language_link(fields, str(item.get("language") or NO_LANGUAGE_TEXT), language_link_field, language_ids)
            update_rows.append({"record_id": item_id, "fields": fields})
    new_codes = next_material_codes_from_records(all_inventory, len(create_changes))
    create_rows: list[dict[str, object]] = []
    for item, material_code in zip(create_changes, new_codes):
        fields = {
            "物料编码": material_code, "物料品类": item.get("category"),
            "产品型号": item.get("model"), "语种": item.get("language"),
            "当前库存": 0, "备注": "", "启用状态": normalize_enabled_status(item.get("status")),
            REQUEST_PAGE_VISIBILITY_FIELD: normalize_request_page_visibility(item.get("request_visible")),
            "品类关联": [str(item.get("category_record_id") or "")],
        }
        set_feishu_unit_price(MATERIAL_TABLE_NAME, fields, float(item.get("unit_price") or 0))
        set_feishu_customs_code(MATERIAL_TABLE_NAME, fields, str(item.get("customs_code") or ""))
        add_material_model_link(fields, str(item.get("model") or NO_MODEL_TEXT), model_link_field, model_ids)
        add_material_language_link(fields, str(item.get("language") or NO_LANGUAGE_TEXT), language_link_field, language_ids)
        create_rows.append(fields)
    created_materials = feishu_batch_create_records(MATERIAL_TABLE_NAME, create_rows) if create_rows else []
    updated_material_count = feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, update_rows)
    deleted_material_count = feishu_batch_delete_record_ids(MATERIAL_TABLE_NAME, delete_ids)
    deleted_count = feishu_batch_delete_record_ids(table_name, [record_id]) if operation == "delete" else 0
    affected_categories = unique_preserve([str(item.get("category") or "") for item in changes])
    if affected_categories:
        refreshed_inventory = [
            parsed for row in fresh_feishu_rows(MATERIAL_TABLE_NAME)
            if (parsed := parse_feishu_inventory_record(row)) is not None
        ]
        for category in feishu_category_records_from_rows(fresh_feishu_rows(CATEGORY_TABLE_NAME)):
            category_name = str(category.get("category") or "")
            if category_name in affected_categories:
                update_category_inventory_counts(
                    category,
                    [item for item in refreshed_inventory if str(item.get("category") or "") == category_name],
                )
    return {
        "operation": operation, "created_count": dimension_created_count,
        "created_material_count": len(created_materials), "updated_material_count": updated_material_count,
        "deleted_material_count": deleted_material_count, "deleted_count": deleted_count,
    }


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


def render_storage_diagnostics(parent: object | None = None) -> None:
    is_unlocked = bool(st.session_state.get("admin_unlocked"))
    expander_parent = parent if parent is not None else st.sidebar
    with expander_parent.expander(
        "系统连接",
        expanded=False,
        icon=":material/settings:" if is_unlocked else ":material/lock:",
    ):
        if not sidebar_admin_auth_gate("storage_diagnostics"):
            return
        st.write(f"当前存储：**{storage_mode_label()}**")
        st.write(f"FEISHU_APP_ID：{'已读取' if bool(feishu_app_id()) else '未读取'}")
        st.write(f"FEISHU_APP_SECRET：{'已读取' if bool(feishu_app_secret()) else '未读取'}")
        st.write(f"FEISHU_BITABLE_APP_TOKEN：{'已读取' if bool(feishu_bitable_app_token()) else '未读取'}")

        st.caption("为加快页面打开速度，行数统计改为手动检查。")
        if st.button(
            "检查连接并刷新数据",
            key="refresh_storage_status",
            icon=":material/cloud_sync:",
            width="stretch",
        ):
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


def normalize_enabled_status(value: object) -> str:
    return STATUS_INACTIVE if str(value or "").strip() == STATUS_INACTIVE else STATUS_ACTIVE


def normalize_request_page_visibility(value: object) -> str:
    return (
        REQUEST_PAGE_VISIBLE_VALUE
        if str(value or "").strip() == REQUEST_PAGE_VISIBLE_VALUE
        else REQUEST_PAGE_HIDDEN_VALUE
    )


def material_record_is_active(record: dict) -> bool:
    return normalize_enabled_status(record.get("status")) == STATUS_ACTIVE


def enforce_category_inventory_status(plan: dict, category_status: object) -> dict:
    return plan


def normalize_option_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_category_match_key(value: object) -> str:
    """Match category labels even when bilingual suffix formatting differs."""
    normalized = unicodedata.normalize("NFKC", normalize_option_label(value))
    base_label = normalized.split("(", 1)[0].strip()
    return re.sub(r"\s+", "", base_label or normalized).casefold()


def request_category_image_path(product: object) -> Path | None:
    product_key = normalize_category_match_key(product)
    for row in safe_feishu_rows(CATEGORY_TABLE_NAME):
        fields = feishu_fields(row)
        if normalize_category_match_key(feishu_text(fields, "物料品类")) != product_key:
            continue
        attachments = fields.get(REQUEST_CATEGORY_IMAGE_FIELD)
        if not isinstance(attachments, list):
            return None
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            cached_path = str(attachment.get("cached_path") or "").strip()
            if not cached_path:
                file_token = str(attachment.get("file_token") or "").strip()
                if file_token:
                    digest = hashlib.sha256(file_token.encode("utf-8")).hexdigest()[:20]
                    cached_path = f"assets/request_categories/{digest}.webp"
            if not cached_path:
                continue
            candidate = application_cache_path(cached_path)
            root = Path(__file__).resolve().parent
            if root == candidate or root in candidate.parents:
                return candidate if candidate.is_file() else None
        return None
    return None


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def request_category_image_paths(cache_generated_at: str) -> dict[str, str]:
    """Build the request-card image index once per published cache snapshot."""
    del cache_generated_at
    result: dict[str, str] = {}
    root = Path(__file__).resolve().parent
    for row in safe_feishu_rows(CATEGORY_TABLE_NAME):
        fields = feishu_fields(row)
        product_key = normalize_category_match_key(feishu_text(fields, "物料品类"))
        if not product_key or product_key in result:
            continue
        attachments = fields.get(REQUEST_CATEGORY_IMAGE_FIELD)
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            cached_path = str(attachment.get("cached_path") or "").strip()
            if not cached_path:
                file_token = str(attachment.get("file_token") or "").strip()
                if file_token:
                    digest = hashlib.sha256(file_token.encode("utf-8")).hexdigest()[:20]
                    cached_path = f"assets/request_categories/{digest}.webp"
            if not cached_path:
                continue
            candidate = application_cache_path(cached_path)
            if candidate != root and root in candidate.parents and candidate.is_file():
                result[product_key] = str(candidate)
                break
    return result


def default_no_language_product_keys() -> set[str]:
    return {normalize_option_label(product) for product in DEFAULT_NO_LANGUAGE_PRODUCTS}


def is_default_no_language_product(product: str) -> bool:
    return normalize_option_label(product) in default_no_language_product_keys()


def parse_custom_values(raw_text: str) -> list[str]:
    parts = re.split(r"[\n,，;；、]+", raw_text)
    return unique_preserve(parts)


def parse_optional_unit_price(raw_value: object) -> float | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("单价（美元）必须填写有效数字。") from exc
    if value < 0:
        raise ValueError("单价（美元）不能小于 0。")
    return value


def sort_languages(languages: list[str]) -> list[str]:
    unique_languages = unique_preserve(languages)

    def priority(language: str) -> int:
        if language == NO_LANGUAGE_TEXT:
            return -1
        if "English" in language or "英语" in language:
            return 0
        if "Simplified Chinese" in language or "简中" in language:
            return 1
        return 2

    return sorted(
        unique_languages,
        key=lambda language: (priority(language), unique_languages.index(language)),
    )


def sort_models(models: list[str]) -> list[str]:
    """Keep related model families together while sorting numeric suffixes naturally."""
    unique_models = unique_preserve(
        [model for model in models if str(model).strip() and str(model).strip() != NO_MODEL_TEXT]
    )

    def model_key(model: str) -> tuple[object, ...]:
        normalized = re.sub(r"^PUDU\s+", "", model.strip(), flags=re.IGNORECASE)
        parts = re.split(r"(\d+)", normalized.casefold())
        natural_parts = tuple(
            (1, int(part)) if part.isdigit() else (0, part)
            for part in parts
        )
        return natural_parts + ((2, model.casefold()),)

    return sorted(unique_models, key=model_key)


def sort_model_options(models: list[str]) -> list[str]:
    normalized_models = [str(model).strip() or NO_MODEL_TEXT for model in models]
    sorted_models = sort_models(normalized_models)
    if NO_MODEL_TEXT in normalized_models:
        return [NO_MODEL_TEXT] + sorted_models
    return sorted_models


def sort_request_products(products: list[str]) -> list[str]:
    """Keep the four product-line manuals together without reordering other categories."""
    unique_products = unique_preserve(products)
    grouped_products: list[str] = []
    grouped_indices: list[int] = []
    for prefix in REQUEST_MANUAL_PRODUCT_ORDER:
        for index, product in enumerate(unique_products):
            if product.startswith(prefix):
                grouped_products.append(product)
                grouped_indices.append(index)
                break
    if not grouped_products:
        return unique_products

    grouped_set = set(grouped_products)
    remaining = [product for product in unique_products if product not in grouped_set]
    insert_at = min(grouped_indices)
    return remaining[:insert_at] + grouped_products + remaining[insert_at:]


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
            language_name = str(item[2]).strip() or NO_LANGUAGE_TEXT
            inventory_product_keys.add(product_key)
            product_models.setdefault(product_key, []).append(model_name)
            product_languages.setdefault(product_key, []).append(language_name)
            product_model_languages.setdefault((product_key, model_key), []).append(language_name)

    configured_language_product_keys = {
        normalize_option_label(product) for product in options.get("configured_language_products", [])
    }
    no_language_product_keys = {
        normalize_option_label(product) for product in options.get("no_language_products", [])
    } | (default_no_language_product_keys() - configured_language_product_keys)
    no_language_product_keys.update(
        product_key
        for product_key, product_language_values in product_languages.items()
        if product_language_values and set(product_language_values) == {NO_LANGUAGE_TEXT}
    )

    return {
        "products": options["products"],
        "models": sort_models(options["models"]),
        "languages": sort_languages(options["languages"]),
        "no_model_product_keys": {normalize_option_label(product) for product in options["no_model_products"]},
        "no_language_product_keys": no_language_product_keys,
        "inventory_product_keys": inventory_product_keys,
        "product_models": {key: sort_model_options(values) for key, values in product_models.items()},
        "product_languages": {key: sort_languages(values) for key, values in product_languages.items()},
        "product_model_languages": {
            key: sort_languages(values) for key, values in product_model_languages.items()
        },
        "inventory_df": inventory_df,
    }


def product_model_state(product: str, selection_context: dict[str, object]) -> tuple[bool, list[str]]:
    product_key = normalize_option_label(product)
    scoped_models = sort_model_options(
        list(dict(selection_context.get("product_models") or {}).get(product_key, []))
    )
    is_no_model_product = scoped_models == [NO_MODEL_TEXT]
    return is_no_model_product, scoped_models


def product_model_line_groups(
    product: str,
    selection_context: dict[str, object],
) -> tuple[bool, list[tuple[str, list[str]]]]:
    _, scoped_models = product_model_state(product, selection_context)
    product_lines = {
        str(model).strip(): str(product_line).strip()
        for model, product_line in dict(
            selection_context.get("model_product_lines") or {}
        ).items()
    }
    grouped: dict[str, list[str]] = {
        product_line: [] for product_line in PRIMARY_MODEL_PRODUCT_LINES
    }
    other_groups: dict[str, list[str]] = {}
    for model in scoped_models:
        product_line = product_lines.get(model, "")
        if product_line in grouped:
            grouped[product_line].append(model)
        else:
            other_groups.setdefault(product_line or "未分组", []).append(model)
    primary_group_count = sum(bool(grouped[product_line]) for product_line in PRIMARY_MODEL_PRODUCT_LINES)
    groups = [
        (product_line, grouped[product_line])
        for product_line in PRIMARY_MODEL_PRODUCT_LINES
        if grouped[product_line]
    ]
    groups.extend(
        (product_line, models)
        for product_line, models in other_groups.items()
        if models
    )
    return primary_group_count >= 2, groups


def selection_context_has_inventory_combination(
    selection_context: dict[str, object],
    product: str,
    model: str,
    language: str,
) -> bool:
    product_key = normalize_option_label(product)
    model_key = normalize_option_label(model or NO_MODEL_TEXT)
    scoped_languages = dict(selection_context.get("product_model_languages") or {}).get(
        (product_key, model_key),
        [],
    )
    return str(language).strip() in {str(value).strip() for value in scoped_languages}


def product_language_options(
    product: str,
    model: str,
    selection_context: dict[str, object],
    fallback_languages: list[str] | None = None,
) -> list[str]:
    product_key = normalize_option_label(product)
    model_key = normalize_option_label(model or NO_MODEL_TEXT)
    scoped_languages = dict(selection_context.get("product_model_languages") or {}).get(
        (product_key, model_key),
        [],
    )
    return sort_languages(list(scoped_languages))


def product_language_state(
    product: str,
    model: str,
    selection_context: dict[str, object],
    fallback_languages: list[str] | None = None,
) -> tuple[bool, list[str]]:
    scoped_languages = product_language_options(
        product,
        model,
        selection_context,
        fallback_languages,
    )
    return scoped_languages == [NO_LANGUAGE_TEXT], scoped_languages


def request_form_active_combinations(
    rows: list[dict[str, object]],
    model_product_lines: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    normalized_product_lines = {
        str(model).strip(): str(product_line).strip()
        for model, product_line in dict(model_product_lines or {}).items()
        if str(model).strip() and str(product_line).strip()
    }
    product_models: dict[str, dict[str, list[str]]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        product = str(item.get("product") or "").strip()
        if not product:
            continue
        model = str(item.get("model") or "").strip() or NO_MODEL_TEXT
        language = str(item.get("language") or "").strip() or NO_LANGUAGE_TEXT
        product_models.setdefault(product, {}).setdefault(model, []).append(language)

    combinations: list[dict[str, object]] = []
    for product, model_languages in product_models.items():
        combinations.append(
            {
                "product": product,
                "models": [
                    {
                        "model": model,
                        "languages": sort_languages(model_languages[model]),
                        **(
                            {"product_line": normalized_product_lines[model]}
                            if model in normalized_product_lines
                            else {}
                        ),
                    }
                    for model in sort_model_options(list(model_languages))
                ],
            }
        )
    return combinations


def request_form_combination_count(combinations: list[dict[str, object]]) -> int:
    return sum(
        len(list(model_config.get("languages") or []))
        for product_config in combinations
        if isinstance(product_config, dict)
        for model_config in list(product_config.get("models") or [])
        if isinstance(model_config, dict)
    )


def validate_request_form_cache(
    cache_data: dict[str, object],
    *,
    require_data: bool = False,
) -> dict[str, int]:
    schema_version = int(cache_data.get("schema_version") or 1)
    if schema_version > REQUEST_FORM_CACHE_SCHEMA_VERSION:
        raise ValueError(f"不支持的申请页面缓存版本：{schema_version}。")

    rows = [item for item in list(cache_data.get("inventory_rows") or []) if isinstance(item, dict)]
    row_count = int(cache_data.get("row_count") or 0)
    if row_count != len(rows):
        raise ValueError(
            f"申请页面缓存行数不一致：配置 {row_count}，实际 {len(rows)}。"
        )

    model_product_lines = {
        str(model).strip(): str(product_line).strip()
        for model, product_line in dict(cache_data.get("model_product_lines") or {}).items()
        if str(model).strip() and str(product_line).strip()
    }
    expected_combinations = request_form_active_combinations(rows, model_product_lines)
    expected_count = request_form_combination_count(expected_combinations)
    if schema_version >= 2:
        cached_combinations = list(cache_data.get("active_combinations") or [])
        if cached_combinations != expected_combinations:
            raise ValueError("申请页面缓存中的启用组合配置与物料行不一致。")
        configured_count = int(cache_data.get("combination_count") or 0)
        if configured_count != expected_count:
            raise ValueError(
                f"申请页面缓存组合数不一致：配置 {configured_count}，实际 {expected_count}。"
            )

    products = [str(value).strip() for value in list(cache_data.get("products") or []) if str(value).strip()]
    combination_product_keys = {
        normalize_option_label(str(item.get("product") or ""))
        for item in expected_combinations
        if isinstance(item, dict)
    }
    product_keys = {normalize_option_label(product) for product in products}
    if product_keys != combination_product_keys:
        raise ValueError("申请页面缓存品类配置与启用物料组合不一致。")
    if require_data and (not rows or not products or expected_count <= 0):
        raise ValueError("申请页面缓存没有可用的启用物料组合。")

    return {
        "row_count": len(rows),
        "product_count": len(products),
        "combination_count": expected_count,
    }


def request_form_cache_from_inventory(
    options: dict,
    inventory_df: pd.DataFrame,
    *,
    source: str,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    enabled_product_by_key = {
        normalize_category_match_key(product): str(product)
        for product in list(options.get("products") or [])
    }
    enabled_inventory_df = inventory_df
    if not inventory_df.empty:
        enabled_inventory_df = inventory_df[
            inventory_df[PRODUCT_COL]
            .map(normalize_category_match_key)
            .isin(enabled_product_by_key)
        ]
    if not enabled_inventory_df.empty:
        for item in enabled_inventory_df.fillna("").itertuples(index=False):
            canonical_product = enabled_product_by_key.get(
                normalize_category_match_key(item[1]),
                str(item[1]),
            )
            rows.append(
                {
                    "material_code": str(item[0]),
                    "product": canonical_product,
                    "model": str(item[2]).strip() or NO_MODEL_TEXT,
                    "language": str(item[3]).strip() or NO_LANGUAGE_TEXT,
                    "quantity": int(item[4] or 0),
                    # Keep the same RMB conversion used by backend snapshots so
                    # the cache-only request page can estimate a cart total.
                    "unit_price_rmb": round(float(item[5] or 0) * 6.77, 4),
                }
            )
    model_product_lines = {
        str(model).strip(): str(product_line).strip()
        for model, product_line in dict(options.get("model_product_lines") or {}).items()
        if str(model).strip() and str(product_line).strip()
    }
    model_display_names = normalize_model_display_names(options.get("model_display_names", {}))
    category_display_names = normalize_category_display_names(
        options.get("category_display_names", {})
    )
    active_combinations = request_form_active_combinations(rows, model_product_lines)
    active_product_keys = {
        normalize_option_label(str(item.get("product") or ""))
        for item in active_combinations
    }
    products = [
        str(product)
        for product in sort_request_products(list(options.get("products") or []))
        if normalize_option_label(product) in active_product_keys
    ]
    cache = {
        "schema_version": REQUEST_FORM_CACHE_SCHEMA_VERSION,
        "source": source,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "products": products,
        "no_model_products": unique_preserve(list(options.get("no_model_products") or [])),
        "no_language_products": unique_preserve(list(options.get("no_language_products") or [])),
        "configured_language_products": unique_preserve(
            list(options.get("configured_language_products") or [])
        ),
        "models": sort_models(list(options.get("models") or [])),
        "model_product_lines": model_product_lines,
        "model_display_names": model_display_names,
        "category_display_names": category_display_names,
        "languages": sort_languages(list(options.get("languages") or [])),
        "active_combinations": active_combinations,
        "combination_count": request_form_combination_count(active_combinations),
        "inventory_rows": rows,
        "row_count": len(rows),
    }
    validate_request_form_cache(cache)
    return cache


def build_live_request_form_cache() -> dict[str, object]:
    inventory_df = load_feishu_request_inventory_snapshot(*feishu_config_args())
    options = load_feishu_options_snapshot(*feishu_config_args())
    return request_form_cache_from_inventory(options, inventory_df, source="live_feishu")


@st.cache_data(show_spinner=False)
def load_static_json_file(
    path_value: str,
    modified_ns: int,
    file_size: int,
) -> object:
    del modified_ns, file_size
    return json.loads(Path(path_value).read_text(encoding="utf-8"))


def static_cache_file_signature(path: Path) -> tuple[str, int, int]:
    root = Path(__file__).resolve().parent
    if root in path.resolve().parents:
        path = application_cache_path(path.resolve().relative_to(root).as_posix())
    if not path.exists():
        return str(path), 0, 0
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


def application_cache_path(relative: str) -> Path:
    # A full page render keeps one publication, including its image files.
    return resolve_cache_path(
        Path(__file__).resolve().parent, relative,
        st.session_state.get("_live_cache_manifest"),
    )


def prepare_live_cache_view() -> None:
    manifest = read_manifest(Path(__file__).resolve().parent)
    previous = st.session_state.get("_live_cache_manifest", {})
    if previous.get("revision") != manifest.get("revision"):
        request_category_image_paths.clear()
    st.session_state["_live_cache_manifest"] = manifest


@st.fragment(run_every=5)
def render_live_cache_notice() -> None:
    current = read_manifest(Path(__file__).resolve().parent)
    applied = st.session_state.get("_live_cache_manifest", {})
    if current.get("revision") and current.get("revision") != applied.get("revision"):
        st.info(ui_text("本地缓存已更新。可继续填写；切换页面或点击下方按钮加载新数据。"))
        if st.button(ui_text("加载最新缓存"), key="load_published_cache"):
            st.rerun(scope="app")


def load_static_request_form_cache() -> dict[str, object]:
    if not REQUEST_FORM_STATIC_CACHE_PATH.exists():
        return {
            "schema_version": REQUEST_FORM_CACHE_SCHEMA_VERSION,
            "source": "empty",
            "generated_at": "",
            "products": [],
            "no_model_products": [],
            "no_language_products": [],
            "configured_language_products": [],
            "models": [],
            "model_product_lines": {},
            "model_display_names": {},
            "category_display_names": {},
            "languages": [],
            "active_combinations": [],
            "combination_count": 0,
            "inventory_rows": [],
            "row_count": 0,
        }
    data = load_static_json_file(*static_cache_file_signature(REQUEST_FORM_STATIC_CACHE_PATH))
    if not isinstance(data, dict):
        raise ValueError("申请页面静态缓存文件格式不正确。")
    validate_request_form_cache(data)
    return data


load_static_request_form_cache.clear = load_static_json_file.clear  # type: ignore[attr-defined]


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


def refresh_request_form_cache_from_page_data() -> dict[str, object]:
    data = request_form_cache_from_inventory(
        load_feishu_options(),
        load_feishu_request_inventory(),
        source="session_page_refresh",
    )
    set_request_form_cache_state(
        data=data,
        refreshing=False,
        error="",
        updated_at=str(data.get("generated_at") or ""),
    )
    st.session_state["request_form_cache_data"] = data
    st.session_state["request_form_cache_locked"] = False
    return data


def request_form_cache_to_selection_context(cache_data: dict[str, object]) -> dict[str, object]:
    product_models: dict[str, list[str]] = {}
    product_languages: dict[str, list[str]] = {}
    product_model_languages: dict[tuple[str, str], list[str]] = {}
    inventory_product_keys: set[str] = set()
    unit_price_rmb_by_combination: dict[tuple[str, str, str], float] = {}
    rows = list(cache_data.get("inventory_rows") or [])
    has_active_combination_config = "active_combinations" in cache_data
    for item in rows:
        if not isinstance(item, dict):
            continue
        product = str(item.get("product") or "").strip()
        model = str(item.get("model") or "").strip() or NO_MODEL_TEXT
        language = str(item.get("language") or "").strip() or NO_LANGUAGE_TEXT
        if not product:
            continue
        product_key = normalize_option_label(product)
        model_key = normalize_option_label(model)
        inventory_product_keys.add(product_key)
        unit_price_rmb_by_combination[(product_key, model_key, language)] = float(
            item.get("unit_price_rmb") or 0
        )
        if not has_active_combination_config:
            product_models.setdefault(product_key, []).append(model)
            product_languages.setdefault(product_key, []).append(language)
            product_model_languages.setdefault((product_key, model_key), []).append(language)

    if has_active_combination_config:
        for product_config in list(cache_data.get("active_combinations") or []):
            if not isinstance(product_config, dict):
                continue
            product = str(product_config.get("product") or "").strip()
            if not product:
                continue
            product_key = normalize_option_label(product)
            inventory_product_keys.add(product_key)
            for model_config in list(product_config.get("models") or []):
                if not isinstance(model_config, dict):
                    continue
                model = str(model_config.get("model") or "").strip() or NO_MODEL_TEXT
                languages = [
                    str(language).strip() or NO_LANGUAGE_TEXT
                    for language in list(model_config.get("languages") or [])
                ]
                model_key = normalize_option_label(model)
                product_models.setdefault(product_key, []).append(model)
                product_languages.setdefault(product_key, []).extend(languages)
                product_model_languages.setdefault((product_key, model_key), []).extend(languages)

    product_candidates = sort_request_products(
        list(cache_data.get("products") or [])
        + [str(item.get("product") or "") for item in rows if isinstance(item, dict)]
    )
    products = [
        product
        for product in product_candidates
        if normalize_option_label(product) in inventory_product_keys
    ]
    models = sort_models(
        list(cache_data.get("models") or [])
        + [str(item.get("model") or "") for item in rows if isinstance(item, dict)]
    )
    languages = sort_languages(unique_preserve(list(cache_data.get("languages") or []) + [str(item.get("language") or "") for item in rows if isinstance(item, dict)]))
    configured_language_product_keys = {
        normalize_option_label(product)
        for product in list(cache_data.get("configured_language_products") or [])
    }
    no_language_product_keys = {
        normalize_option_label(product) for product in list(cache_data.get("no_language_products") or [])
    } | (default_no_language_product_keys() - configured_language_product_keys)
    no_language_product_keys.update(
        product_key
        for product_key, product_language_values in product_languages.items()
        if product_language_values and set(product_language_values) == {NO_LANGUAGE_TEXT}
    )

    return {
        "products": products,
        "models": models,
        "category_display_names": normalize_category_display_names(
            cache_data.get("category_display_names", {})
        ),
        "model_product_lines": {
            str(model).strip(): str(product_line).strip()
            for model, product_line in dict(
                cache_data.get("model_product_lines") or {}
            ).items()
            if str(model).strip() and str(product_line).strip()
        },
        "model_display_names": normalize_model_display_names(
            cache_data.get("model_display_names", {})
        ),
        "languages": languages,
        "no_model_product_keys": {
            normalize_option_label(product) for product in list(cache_data.get("no_model_products") or [])
        },
        "no_language_product_keys": no_language_product_keys,
        "inventory_product_keys": inventory_product_keys,
        "product_models": {key: sort_model_options(values) for key, values in product_models.items()},
        "product_languages": {key: sort_languages(values) for key, values in product_languages.items()},
        "product_model_languages": {
            key: sort_languages(values) for key, values in product_model_languages.items()
        },
        "unit_price_rmb_by_combination": unit_price_rmb_by_combination,
        "inventory_df": pd.DataFrame(rows),
        "cache_source": cache_data.get("source", ""),
        "cache_generated_at": cache_data.get("generated_at", ""),
        "cache_row_count": int(cache_data.get("row_count") or len(rows)),
    }


def mark_request_form_dirty() -> None:
    st.session_state["request_form_cache_locked"] = True


def enforce_request_cart_exclusive_multi_select(
    active_key: str,
    other_key: str,
) -> None:
    mark_request_form_dirty()
    if st.session_state.get(active_key):
        st.session_state[other_key] = False


def sync_request_department_from_selected_applicant() -> None:
    mark_request_form_dirty()
    open_id = str(st.session_state.get("request_requester_open_id") or "")
    user_lookup = st.session_state.get(REQUEST_CONTACT_USER_LOOKUP_KEY)
    if not open_id or not isinstance(user_lookup, dict):
        st.session_state["request_department_id"] = None
        return
    user = user_lookup.get(open_id)
    if not isinstance(user, dict):
        st.session_state["request_department_id"] = None
        return
    department_ids = [
        str(value)
        for value in list(user.get("department_ids") or [])
        if str(value).strip()
    ]
    current_department_id = str(st.session_state.get("request_department_id") or "")
    if current_department_id not in department_ids:
        st.session_state["request_department_id"] = department_ids[0] if department_ids else None


def get_request_form_selection_context() -> dict[str, object]:
    state = request_form_cache_state()
    live_data = state.get("data") if isinstance(state.get("data"), dict) else None
    runtime_data = request_form_cache_from_runtime_page_data()
    static_data = load_static_request_form_cache()
    current_data = st.session_state.get("request_form_cache_data")
    candidates = [
        data
        for data in (static_data, live_data, runtime_data, current_data)
        if isinstance(data, dict)
    ]
    if candidates:
        next_data = max(
            enumerate(candidates),
            key=lambda item: (str(item[1].get("generated_at") or ""), item[0]),
        )[1]
        if next_data is not current_data:
            st.session_state["request_form_cache_data"] = next_data
            st.session_state["request_form_cache_locked"] = False
    return request_form_cache_to_selection_context(dict(st.session_state["request_form_cache_data"]))


def get_restock_selection_context() -> dict[str, object]:
    category_rows = safe_feishu_rows(CATEGORY_TABLE_NAME)
    category_records = feishu_category_records_from_rows(category_rows)
    inventory_records = feishu_inventory_records_from_rows(
        safe_feishu_rows(MATERIAL_TABLE_NAME),
        category_rows,
        active_only=False,
    )
    inventory_rows = [
        {
            "material_code": str(item.get("material_code") or ""),
            "product": str(item.get("category") or ""),
            "model": str(item.get("model") or NO_MODEL_TEXT),
            "language": str(item.get("language") or NO_LANGUAGE_TEXT),
            "quantity": int(item.get("quantity") or 0),
            "status": str(item.get("status") or ""),
        }
        for item in inventory_records
    ]
    inventory_category_keys = {
        normalize_category_match_key(item.get("category"))
        for item in inventory_records
        if str(item.get("category") or "").strip()
    }
    inventory_rows.extend(
        {
            "material_code": "",
            "product": str(category.get("category") or ""),
            "model": NO_MODEL_TEXT,
            "language": NO_LANGUAGE_TEXT,
            "quantity": 0,
            "status": str(category.get("status") or STATUS_INACTIVE),
            "synthetic": True,
        }
        for category in category_records
        if category.get("no_model")
        and category.get("no_language")
        and normalize_category_match_key(category.get("category"))
        not in inventory_category_keys
    )
    context = request_form_cache_to_selection_context(
        {
            "source": "page_data_cache",
            "generated_at": page_cache_status(PAGE_CACHE_TABLES["restock"])[1],
            "inventory_rows": inventory_rows,
            "row_count": len(inventory_rows),
            "products": [str(item.get("category") or "") for item in category_records],
            "models": [str(item.get("model") or "") for item in inventory_records],
            "languages": [str(item.get("language") or "") for item in inventory_records],
            "no_model_products": [
                str(item.get("category") or "")
                for item in category_records
                if item.get("no_model")
            ],
            "no_language_products": [
                str(item.get("category") or "")
                for item in category_records
                if item.get("no_language")
            ],
            "configured_language_products": [
                str(item.get("category") or "") for item in category_records
            ],
        }
    )
    category_definition_by_product = {
        str(item.get("category") or ""): str(
            item.get("category_definition") or UNDEFINED_CATEGORY_DEFINITION
        )
        for item in category_records
        if str(item.get("category") or "").strip()
    }
    context["category_definition_by_product"] = category_definition_by_product
    context["category_definitions"] = unique_preserve(
        [
            category_definition_by_product.get(product, UNDEFINED_CATEGORY_DEFINITION)
            for product in list(context.get("products") or [])
        ]
    )
    return context


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


def material_dashboard_dataframe(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "记录ID": str(row.get("record_id") or ""),
                "物料编码": str(row.get("material_code") or ""),
                "物料品类": str(row.get("category") or ""),
                "产品型号": str(row.get("model") or NO_MODEL_TEXT),
                "语种": str(row.get("language") or ""),
                "库存数量": int(row.get("quantity") or 0),
                "单价": float(row.get("unit_price") or 0),
                "总价值": float(row.get("total_value") or 0),
            }
            for row in records
        ],
        columns=["记录ID", "物料编码", "物料品类", "产品型号", "语种", "库存数量", "单价", "总价值"],
    )


def material_stock_status(quantity: object, low_stock_threshold: int) -> str:
    normalized_quantity = int(quantity or 0)
    if normalized_quantity < 0:
        return "负库存"
    if normalized_quantity == 0:
        return "零库存"
    if normalized_quantity <= max(int(low_stock_threshold), 0):
        return "低库存"
    return "正常库存"


def apply_material_dashboard_filters(
    df: pd.DataFrame,
    *,
    categories: list[str],
    models: list[str],
    languages: list[str],
    stock_statuses: list[str],
    low_stock_threshold: int,
) -> pd.DataFrame:
    filtered = df.copy()
    filtered["库存状态"] = filtered["库存数量"].map(
        lambda quantity: material_stock_status(quantity, low_stock_threshold)
    )
    if categories:
        filtered = filtered[filtered["物料品类"].isin(categories)]
    if models:
        filtered = filtered[filtered["产品型号"].isin(models)]
    if languages:
        filtered = filtered[filtered["语种"].isin(languages)]
    if stock_statuses:
        filtered = filtered[filtered["库存状态"].isin(stock_statuses)]
    return filtered.reset_index(drop=True)


def material_dashboard_summary(df: pd.DataFrame) -> dict[str, float | int]:
    if df.empty:
        return {
            "combination_count": 0,
            "quantity_sum": 0,
            "total_value": 0.0,
            "negative_count": 0,
            "zero_count": 0,
        }
    return {
        "combination_count": len(df),
        "quantity_sum": int(df["库存数量"].sum()),
        "total_value": float(df["总价值"].sum()),
        "negative_count": int((df["库存数量"] < 0).sum()),
        "zero_count": int((df["库存数量"] == 0).sum()),
    }


def material_dashboard_grouped_data(
    df: pd.DataFrame,
    group_column: str,
    value_column: str,
    *,
    limit: int = 12,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[group_column, value_column])
    grouped = df.groupby(group_column, as_index=False, dropna=False)[value_column].sum()
    grouped["_sort"] = grouped[value_column].abs()
    grouped = grouped.sort_values(["_sort", group_column], ascending=[False, True]).head(limit)
    return grouped.drop(columns=["_sort"]).reset_index(drop=True)


def navigate_to_inventory(key: str, label: str = "查看实时库存表") -> None:
    if st.button(label, key=key, icon=":material/inventory_2:", width="stretch"):
        st.query_params["view"] = "inventory"
        st.rerun()


def navigate_to_warehouse_locations(
    key: str, label: str = "物料仓库位置查询"
) -> None:
    current_view = str(st.query_params.get("view", ""))
    if st.button(
        label,
        key=key,
        icon=":material/location_on:",
        disabled=current_view == "warehouse",
        width="stretch",
    ):
        st.query_params["view"] = "warehouse"
        st.rerun()


def render_inventory_query_link() -> None:
    with st.container(key="sidebar_inventory_query"):
        st.link_button(
            ui_text("查询库存"),
            INVENTORY_QUERY_URL,
            icon=":material/search:",
            width="stretch",
        )


def navigate_to_management(key: str, label: str = "返回库存管理") -> None:
    if st.button(label, key=key, type="tertiary", icon=":material/arrow_back:", width="stretch"):
        st.query_params.clear()
        st.rerun()


def navigate_to_management_section(key: str, section: str, label: str, icon: str) -> None:
    current_view = str(st.query_params.get("view", ""))
    active = (
        not current_view
        and str(st.session_state.get(MANAGEMENT_NAVIGATION_KEY, "库存登记")) == section
    )
    if st.button(label, key=key, icon=icon, disabled=active, width="stretch"):
        set_management_section(section)
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


def load_static_page_data_cache() -> dict[str, object]:
    if not PAGE_DATA_STATIC_CACHE_PATH.exists():
        return {"schema_version": 1, "generated_at": "", "tables": {}}
    data = load_static_json_file(*static_cache_file_signature(PAGE_DATA_STATIC_CACHE_PATH))
    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        raise RuntimeError("页面静态缓存文件格式不正确。")
    return data


load_static_page_data_cache.clear = load_static_json_file.clear  # type: ignore[attr-defined]


@st.cache_resource(show_spinner=False)
def page_data_runtime_cache() -> dict[str, object]:
    return {
        "lock": threading.Lock(),
        "tables": {},
        "updated_at": {},
    }


def page_data_cache_rows(table_name: str) -> list[dict]:
    static_cache = load_static_page_data_cache()
    static_generated_at = str(static_cache.get("generated_at") or "")
    static_tables = dict(static_cache.get("tables") or {})
    runtime_cache = page_data_runtime_cache()
    runtime_lock = runtime_cache["lock"]
    with runtime_lock:  # type: ignore[union-attr]
        runtime_tables = dict(runtime_cache.get("tables") or {})
        runtime_updated_at = str(dict(runtime_cache.get("updated_at") or {}).get(table_name) or "")
        if table_name in runtime_tables and runtime_updated_at >= static_generated_at:
            rows = list(runtime_tables[table_name])
            if table_name == MATERIAL_TABLE_NAME:
                model_rows = list(
                    runtime_tables.get(MODEL_TABLE_NAME)
                    or static_tables.get(MODEL_TABLE_NAME)
                    or []
                )
                return material_rows_with_dimension_model_names(rows, model_rows)
            return rows
    table_data = static_tables.get(table_name, [])
    if isinstance(table_data, dict):
        table_data = table_data.get("rows", [])
    rows = list(table_data) if isinstance(table_data, list) else []
    if table_name == MATERIAL_TABLE_NAME:
        model_data = static_tables.get(MODEL_TABLE_NAME, [])
        if isinstance(model_data, dict):
            model_data = model_data.get("rows", [])
        return material_rows_with_dimension_model_names(
            rows,
            list(model_data) if isinstance(model_data, list) else [],
        )
    return rows


def feishu_rows(table_name: str) -> list[dict]:
    cached_rows = page_data_cache_rows(table_name)
    if cached_rows or table_name in dict(load_static_page_data_cache().get("tables") or {}):
        return cached_rows
    return load_feishu_rows_snapshot(table_name, *feishu_config_args())


def fresh_feishu_rows(table_name: str) -> list[dict]:
    client = feishu_client()
    if client is None:
        return []
    return client.list_records(feishu_table_id(table_name))


def safe_fresh_feishu_rows(table_name: str) -> list[dict]:
    try:
        return fresh_feishu_rows(table_name)
    except FeishuBitableError:
        if table_name in OPTIONAL_PAGE_CACHE_TABLES:
            return []
        raise


def safe_feishu_rows(table_name: str) -> list[dict]:
    try:
        return feishu_rows(table_name)
    except FeishuBitableError:
        if table_name in OPTIONAL_PAGE_CACHE_TABLES:
            return []
        raise


def stable_feishu_rows_signature(rows: list[dict]) -> str:
    ignored_keys = {"cached_path", "tmp_url", "url"}

    def stable_value(value: object) -> object:
        if isinstance(value, dict):
            return {
                str(key): stable_value(item)
                for key, item in value.items()
                if str(key) not in ignored_keys
            }
        if isinstance(value, list):
            return [stable_value(item) for item in value]
        return value

    normalized = sorted(
        (stable_value(dict(row)) for row in rows),
        key=lambda row: (
            str(dict(row).get("record_id") or dict(row).get("id") or ""),
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
        ),
    )
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def page_data_signature(page_key: str, table_rows: dict[str, list[dict]]) -> str:
    signatures = {
        table_name: stable_feishu_rows_signature(list(table_rows.get(table_name) or []))
        for table_name in PAGE_CACHE_TABLES[page_key]
    }
    payload = json.dumps(signatures, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def mark_page_snapshot_seen(
    page_key: str,
    table_rows: dict[str, list[dict]] | None = None,
) -> str:
    current_rows = table_rows or {
        table_name: page_data_cache_rows(table_name)
        for table_name in PAGE_CACHE_TABLES[page_key]
    }
    signature = page_data_signature(page_key, current_rows)
    st.session_state[page_update_session_key(page_key, "seen_signature")] = signature
    st.session_state[page_update_session_key(page_key, "latest_signature")] = signature
    st.session_state[page_update_session_key(page_key, "update_available")] = False
    return signature


def refresh_page_cache_tables(table_names: list[str] | tuple[str, ...]) -> dict[str, object]:
    normalized_names = unique_preserve([str(table_name) for table_name in table_names])
    refreshed_tables = {table_name: safe_fresh_feishu_rows(table_name) for table_name in normalized_names}
    if MATERIAL_TABLE_NAME in refreshed_tables:
        model_rows = refreshed_tables.get(MODEL_TABLE_NAME) or page_data_cache_rows(MODEL_TABLE_NAME)
        refreshed_tables[MATERIAL_TABLE_NAME] = material_rows_with_dimension_model_names(
            refreshed_tables[MATERIAL_TABLE_NAME],
            list(model_rows),
        )
    refreshed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    runtime_cache = page_data_runtime_cache()
    runtime_lock = runtime_cache["lock"]
    with runtime_lock:  # type: ignore[union-attr]
        runtime_tables = dict(runtime_cache.get("tables") or {})
        runtime_updated_at = dict(runtime_cache.get("updated_at") or {})
        runtime_tables.update(refreshed_tables)
        runtime_updated_at.update({table_name: refreshed_at for table_name in normalized_names})
        runtime_cache["tables"] = runtime_tables
        runtime_cache["updated_at"] = runtime_updated_at
    st.cache_data.clear()
    return {
        "tables": normalized_names,
        "updated_at": refreshed_at,
        "row_count": sum(len(rows) for rows in refreshed_tables.values()),
    }


def page_cache_status(table_names: list[str] | tuple[str, ...]) -> tuple[str, str]:
    normalized_names = unique_preserve([str(table_name) for table_name in table_names])
    runtime_cache = page_data_runtime_cache()
    runtime_lock = runtime_cache["lock"]
    with runtime_lock:  # type: ignore[union-attr]
        runtime_tables = dict(runtime_cache.get("tables") or {})
        runtime_updated_at = dict(runtime_cache.get("updated_at") or {})
    static_cache = load_static_page_data_cache()
    static_generated_at = str(static_cache.get("generated_at") or "")
    if normalized_names and all(
        table_name in runtime_tables
        and str(runtime_updated_at.get(table_name) or "") >= static_generated_at
        for table_name in normalized_names
    ):
        timestamps = [str(runtime_updated_at.get(table_name) or "") for table_name in normalized_names]
        return "服务缓存已刷新", max(timestamps) if timestamps else ""
    return "部署静态缓存", static_generated_at


def build_page_data_static_snapshot() -> dict[str, object]:
    tables = {table_name: safe_fresh_feishu_rows(table_name) for table_name in ALL_PAGE_CACHE_TABLES}
    tables[MATERIAL_TABLE_NAME] = material_rows_with_dimension_model_names(
        tables[MATERIAL_TABLE_NAME],
        tables[MODEL_TABLE_NAME],
    )
    return {
        "schema_version": 1,
        "source": "live_feishu",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tables": tables,
        "row_counts": {table_name: len(rows) for table_name, rows in tables.items()},
    }


def contact_department_cache_from_rows(
    rows: list[dict[str, object]],
    *,
    source: str,
    department_users: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    departments_by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        department_id = str(
            row.get("open_department_id") or row.get("department_id") or ""
        ).strip()
        name = str(row.get("name") or "").strip()
        if not department_id or not name:
            continue
        departments_by_id[department_id] = {
            "department_id": department_id,
            "name": name,
            "parent_department_id": str(row.get("parent_department_id") or "").strip(),
        }

    def department_path(department_id: str, visited: set[str] | None = None) -> str:
        department = departments_by_id.get(department_id)
        if department is None:
            return ""
        current_visited = set(visited or set())
        if department_id in current_visited:
            return department["name"]
        current_visited.add(department_id)
        parent_id = department["parent_department_id"]
        parent_path = (
            department_path(parent_id, current_visited)
            if parent_id and parent_id != "0" and parent_id in departments_by_id
            else ""
        )
        return f"{parent_path} / {department['name']}" if parent_path else department["name"]

    departments = [
        {
            "department_id": department_id,
            "name": department["name"],
            "path": department_path(department_id),
            "parent_department_id": department["parent_department_id"],
        }
        for department_id, department in departments_by_id.items()
    ]
    departments.sort(key=lambda item: str(item["path"]).casefold())
    department_path_by_id = {
        str(item["department_id"]): str(item["path"])
        for item in departments
    }
    users_by_open_id: dict[str, dict[str, object]] = {}
    for department in departments:
        department_id = str(department["department_id"])
        user_rows = dict(department_users or {}).get(department_id, [])
        department_path_value = department_path_by_id.get(department_id, "")
        for row in user_rows:
            open_id = str(row.get("open_id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not open_id or not name:
                continue
            user = users_by_open_id.setdefault(
                open_id,
                {
                    "open_id": open_id,
                    "name": name,
                    "department_ids": [],
                    "department_paths": [],
                },
            )
            department_ids = user["department_ids"]
            department_paths = user["department_paths"]
            if isinstance(department_ids, list) and department_id not in department_ids:
                department_ids.append(department_id)
            if (
                isinstance(department_paths, list)
                and department_path_value
                and department_path_value not in department_paths
            ):
                department_paths.append(department_path_value)

    users = sorted(
        users_by_open_id.values(),
        key=lambda item: (
            str(item.get("name") or "").casefold(),
            " / ".join(str(value) for value in item.get("department_paths", [])),
            str(item.get("open_id") or ""),
        ),
    )
    return {
        "schema_version": 1,
        "source": source,
        "consumers": ["material_request", "inventory_restock"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "departments": departments,
        "row_count": len(departments),
        "users": users,
        "user_count": len(users),
    }


def build_live_contact_department_cache() -> dict[str, object]:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法读取通讯录部门。")
    department_rows = client.list_contact_departments()
    department_ids = unique_preserve(
        [
            str(row.get("open_department_id") or row.get("department_id") or "").strip()
            for row in department_rows
        ]
    )
    department_ids = [department_id for department_id in department_ids if department_id]
    department_users: dict[str, list[dict[str, object]]] = {}
    if department_ids:
        client.tenant_access_token()

        def load_department_users_with_retry(department_id: str) -> list[dict[str, object]]:
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    return list(client.list_department_users(department_id))
                except (FeishuBitableError, OSError) as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
            raise RuntimeError(f"读取部门成员失败：{department_id}") from last_error

        max_workers = min(8, len(department_ids))
        failed_department_ids: list[str] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_department = {
                executor.submit(load_department_users_with_retry, department_id): department_id
                for department_id in department_ids
            }
            for future in as_completed(future_to_department):
                department_id = future_to_department[future]
                try:
                    department_users[department_id] = list(future.result())
                except RuntimeError:
                    failed_department_ids.append(department_id)
        if failed_department_ids:
            raise RuntimeError(
                f"{len(failed_department_ids)} 个部门成员读取失败，已保留原通讯录缓存，请稍后重试。"
            )
    return contact_department_cache_from_rows(
        department_rows,
        source="live_feishu",
        department_users=department_users,
    )


def load_static_contact_department_cache() -> dict[str, object]:
    if not CONTACT_DEPARTMENT_STATIC_CACHE_PATH.exists():
        return {
            "schema_version": 1,
            "source": "empty",
            "consumers": ["material_request", "inventory_restock"],
            "generated_at": "",
            "departments": [],
            "row_count": 0,
            "users": [],
            "user_count": 0,
        }
    data = load_static_json_file(
        *static_cache_file_signature(CONTACT_DEPARTMENT_STATIC_CACHE_PATH)
    )
    if not isinstance(data, dict):
        raise RuntimeError("通讯录静态缓存文件格式不正确。")
    return data


load_static_contact_department_cache.clear = load_static_json_file.clear  # type: ignore[attr-defined]


def get_contact_directory_cache() -> dict[str, object]:
    static_cache = load_static_contact_department_cache()
    cached = st.session_state.get("contact_department_cache_data")
    if (
        not isinstance(cached, dict)
        or str(static_cache.get("generated_at") or "")
        > str(cached.get("generated_at") or "")
    ):
        cached = static_cache
        if not list(cached.get("departments") or []):
            cached = build_live_contact_department_cache()
        st.session_state["contact_department_cache_data"] = cached
    return cached


def get_contact_departments() -> list[dict[str, str]]:
    cached = get_contact_directory_cache()
    return [
        {
            "department_id": str(item.get("department_id") or ""),
            "name": str(item.get("name") or ""),
            "path": str(item.get("path") or item.get("name") or ""),
        }
        for item in list(cached.get("departments") or [])
        if isinstance(item, dict) and str(item.get("department_id") or "").strip()
    ]


def get_contact_users() -> list[dict[str, object]]:
    cached = get_contact_directory_cache()
    return [
        {
            "open_id": str(item.get("open_id") or ""),
            "name": str(item.get("name") or ""),
            "department_ids": [
                str(value)
                for value in list(item.get("department_ids") or [])
                if str(value).strip()
            ],
            "department_paths": [
                str(value)
                for value in list(item.get("department_paths") or [])
                if str(value).strip()
            ],
        }
        for item in list(cached.get("users") or [])
        if isinstance(item, dict) and str(item.get("open_id") or "").strip()
    ]


def refresh_contact_departments_from_feishu() -> dict[str, object]:
    data = build_live_contact_department_cache()
    st.session_state["contact_department_cache_data"] = data
    return data


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_contact_department_users_snapshot(
    department_id: str,
    app_id: str,
    app_secret: str,
    app_token: str,
) -> list[dict[str, str]]:
    client = FeishuBitableClient(
        FeishuBitableConfig(
            app_id=app_id,
            app_secret=app_secret,
            app_token=app_token,
        )
    )
    users_by_open_id: dict[str, dict[str, str]] = {}
    for item in client.list_department_users(department_id):
        open_id = str(item.get("open_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not open_id or not name:
            continue
        users_by_open_id[open_id] = {"open_id": open_id, "name": name}
    return sorted(users_by_open_id.values(), key=lambda item: item["name"].casefold())


def load_contact_department_users(department_id: str) -> list[dict[str, str]]:
    return load_contact_department_users_snapshot(department_id, *feishu_config_args())


def request_form_cache_from_runtime_page_data() -> dict[str, object] | None:
    runtime_cache = page_data_runtime_cache()
    runtime_lock = runtime_cache["lock"]
    with runtime_lock:  # type: ignore[union-attr]
        runtime_tables = dict(runtime_cache.get("tables") or {})
        runtime_updated_at = dict(runtime_cache.get("updated_at") or {})
    if not all(table_name in runtime_tables for table_name in REQUEST_FORM_CACHE_TABLES):
        return None
    runtime_signature = (
        str(runtime_updated_at.get(MATERIAL_TABLE_NAME) or ""),
        str(runtime_updated_at.get(CATEGORY_TABLE_NAME) or ""),
        str(runtime_updated_at.get(MODEL_TABLE_NAME) or ""),
        str(runtime_updated_at.get(LANGUAGE_TABLE_NAME) or ""),
    )
    cached_signature = st.session_state.get("request_runtime_cache_signature")
    cached_data = st.session_state.get("request_runtime_cache_data")
    if cached_signature == runtime_signature and isinstance(cached_data, dict):
        return cached_data
    data = request_form_cache_from_inventory(
        load_feishu_options(),
        load_feishu_request_inventory(),
        source="shared_runtime_page_cache",
    )
    timestamps = [
        str(runtime_updated_at.get(table_name) or "")
        for table_name in REQUEST_FORM_CACHE_TABLES
    ]
    if all(timestamps):
        data["generated_at"] = min(timestamps)
    st.session_state["request_runtime_cache_signature"] = runtime_signature
    st.session_state["request_runtime_cache_data"] = data
    return data


def render_page_cache_toolbar(page_key: str) -> None:
    message_key = f"page_cache_message_{page_key}"
    message = st.session_state.pop(message_key, "")
    if message:
        st.success(message)
    warning = st.session_state.pop("post_write_cache_warning", "")
    if warning:
        st.warning(warning)



def render_page_cache_refresh_button(page_key: str, container: object = st) -> None:
    table_names = PAGE_CACHE_TABLES[page_key]
    message_key = f"page_cache_message_{page_key}"
    if container.button(
        "刷新本页数据",
        key=f"refresh_page_cache_{page_key}",
        icon=":material/refresh:",
        width="stretch",
    ):
        if page_key == "order_scheduling":
            from order_scheduling_page import start_refresh
            start_refresh(APP_RUNTIME)
            st.rerun()
        with fullscreen_data_sync("正在同步本页数据"):
            try:
                result = refresh_page_cache_tables(table_names)
                if page_key == "request":
                    refresh_request_form_cache_from_page_data()
                mark_page_snapshot_seen(page_key)
            except Exception as exc:
                st.error("本页数据刷新失败，请检查飞书连接和数据表权限。")
                st.exception(exc)
                return
        st.session_state[message_key] = (
            f"本页数据已刷新，共同步 {result['row_count']} 条记录。"
        )
        st.rerun()


def refresh_page_cache_after_write(page_key: str, *, update_request_form: bool = False) -> None:
    # Writes are handled by Feishu or the background queue. Do not immediately
    # download the related tables again after every create/edit/delete action.
    # The deployed snapshot changes only through manual refresh or the local
    # scheduled material-cache task.
    del page_key, update_request_form


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


def feishu_link_texts(fields: dict, name: str) -> list[str]:
    value = fields.get(name)
    if value in (None, ""):
        return []

    raw_items = value if isinstance(value, list) else [value]
    texts: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            text_arr = item.get("text_arr") or []
            if isinstance(text_arr, list):
                texts.extend(str(text) for text in text_arr if text not in (None, ""))
            text = item.get("text")
            if text not in (None, ""):
                texts.append(str(text))
    return unique_preserve(texts)


def feishu_attachment_items(fields: dict, name: str) -> list[dict[str, str]]:
    value = fields.get(name)
    if not isinstance(value, list):
        return []
    attachments: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        file_token = str(item.get("file_token") or "").strip()
        if not file_token:
            continue
        attachments.append(
            {
                "file_token": file_token,
                "name": str(item.get("name") or "").strip(),
                "type": str(item.get("type") or "").strip(),
                "url": str(item.get("tmp_url") or item.get("url") or "").strip(),
                "cached_path": str(item.get("cached_path") or "").strip(),
            }
        )
    return attachments


@st.cache_data(show_spinner=False, ttl=60 * 60)
def load_feishu_attachment_snapshot(
    file_token: str,
    app_id: str,
    app_secret: str,
    app_token: str,
    attachment_url: str = "",
) -> bytes:
    return get_feishu_bitable_client(
        app_id,
        app_secret,
        app_token,
    ).download_bitable_attachment(
        file_token,
        attachment_url,
    )


def load_feishu_attachment(file_token: str, attachment_url: str = "") -> bytes:
    return load_feishu_attachment_snapshot(
        file_token,
        *feishu_config_args(),
        attachment_url=attachment_url,
    )


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


def feishu_float_any(fields: dict, names: list[str], default: float = 0.0) -> float:
    for name in names:
        if name in fields:
            return feishu_float(fields, name, default)
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


def inventory_maintenance_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("text") or value.get("value") or ""
    if value in (None, ""):
        return None
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = 0.0
    if numeric_value:
        try:
            divisor = 1000 if abs(numeric_value) >= 10_000_000_000 else 1
            return datetime.fromtimestamp(numeric_value / divisor).replace(microsecond=0)
        except (OSError, OverflowError, ValueError):
            return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def inventory_maintenance_datetime_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def inventory_material_key(fields: dict) -> tuple[str, str, str]:
    return (
        feishu_text(fields, "物料品类").strip(),
        (feishu_text(fields, "产品型号").strip() or NO_MODEL_TEXT),
        (feishu_text(fields, "语种").strip() or NO_LANGUAGE_TEXT),
    )


def latest_inventory_change_times(
    material_rows: list[dict],
    ledger_rows: list[dict],
) -> dict[str, datetime]:
    material_ids_by_key: dict[tuple[str, str, str], list[str]] = {}
    for row in material_rows:
        record_id = feishu_record_id(row)
        if not record_id:
            continue
        material_ids_by_key.setdefault(
            inventory_material_key(feishu_fields(row)), []
        ).append(record_id)

    latest_by_material_id: dict[str, datetime] = {}
    for row in ledger_rows:
        fields = feishu_fields(row)
        if (
            is_blank_feishu_transaction(fields)
            or feishu_transaction_status(fields) != "有效"
            or feishu_transaction_delta(fields) == 0
        ):
            continue
        occurred_at = inventory_maintenance_datetime(fields.get("发生时间"))
        if occurred_at is None:
            continue
        material_ids = feishu_link_ids_any(fields, ["物料编码", "物料"])
        if not material_ids:
            fallback_ids = material_ids_by_key.get(inventory_material_key(fields), [])
            material_ids = fallback_ids if len(fallback_ids) == 1 else []
        for material_id in material_ids:
            previous = latest_by_material_id.get(material_id)
            if previous is None or occurred_at > previous:
                latest_by_material_id[material_id] = occurred_at
    return latest_by_material_id


def inventory_status_row_summary(
    row: dict,
    *,
    zero_since: datetime | None = None,
) -> dict[str, object]:
    fields = feishu_fields(row)
    return {
        "record_id": feishu_record_id(row),
        "material_code": feishu_text(fields, "物料编码") or "-",
        "product": feishu_text(fields, "物料品类") or "-",
        "model": feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
        "language": feishu_text(fields, "语种") or NO_LANGUAGE_TEXT,
        "quantity": feishu_int(fields, "当前库存"),
        "zero_since": inventory_maintenance_datetime_text(zero_since) if zero_since else "",
    }


def plan_inventory_status_maintenance(
    material_rows: list[dict],
    ledger_rows: list[dict],
    *,
    now: datetime | None = None,
    inactivity_days: int = INVENTORY_AUTO_DISABLE_DAYS,
) -> dict[str, object]:
    checked_at = (now or datetime.now()).replace(microsecond=0)
    cutoff = checked_at - timedelta(days=max(1, int(inactivity_days)))
    latest_changes = latest_inventory_change_times(material_rows, ledger_rows)
    updates: list[dict[str, object]] = []
    enabled_rows: list[dict[str, object]] = []
    disabled_rows: list[dict[str, object]] = []
    initialized_zero_rows = 0

    for row in material_rows:
        record_id = feishu_record_id(row)
        if not record_id:
            continue
        fields = feishu_fields(row)
        quantity = feishu_int(fields, "当前库存")
        zero_since_raw = feishu_text(fields, INVENTORY_ZERO_SINCE_FIELD).strip()
        zero_since = inventory_maintenance_datetime(zero_since_raw)
        latest_change = latest_changes.get(record_id)
        update_fields: dict[str, object] = {}

        if quantity != 0:
            if zero_since_raw:
                update_fields[INVENTORY_ZERO_SINCE_FIELD] = ""
        else:
            anchor = zero_since
            if latest_change is not None and (anchor is None or latest_change > anchor):
                anchor = latest_change
                update_fields[INVENTORY_ZERO_SINCE_FIELD] = inventory_maintenance_datetime_text(anchor)
            elif anchor is None:
                anchor = checked_at
                update_fields[INVENTORY_ZERO_SINCE_FIELD] = inventory_maintenance_datetime_text(anchor)
                initialized_zero_rows += 1

        if update_fields:
            updates.append({"record_id": record_id, "fields": update_fields})

    return {
        "checked_at": inventory_maintenance_datetime_text(checked_at),
        "cutoff": inventory_maintenance_datetime_text(cutoff),
        "updates": updates,
        "enabled_rows": enabled_rows,
        "disabled_rows": disabled_rows,
        "initialized_zero_rows": initialized_zero_rows,
        "material_count": len(material_rows),
        "ledger_count": len(ledger_rows),
    }


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


def feishu_request_page_visible(fields: dict) -> bool:
    return (
        normalize_request_page_visibility(
            feishu_text(fields, REQUEST_PAGE_VISIBILITY_FIELD)
        )
        == REQUEST_PAGE_VISIBLE_VALUE
    )


def feishu_inventory_dataframe_from_rows(
    rows: list[dict],
    *,
    request_visible_only: bool = False,
) -> pd.DataFrame:
    data: list[list[object]] = []
    for row in rows:
        fields = feishu_fields(row)
        material_code = feishu_text(fields, "物料编码")
        category = feishu_text(fields, "物料品类")
        if not material_code or not category:
            continue
        if request_visible_only:
            if not feishu_request_page_visible(fields):
                continue
        quantity = feishu_int(fields, "当前库存")
        unit_price = feishu_float_any(fields, list(UNIT_PRICE_FIELD_CANDIDATES))
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


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_inventory_snapshot(app_id: str, app_secret: str, app_token: str) -> pd.DataFrame:
    return feishu_inventory_dataframe_from_rows(
        load_feishu_rows_snapshot(MATERIAL_TABLE_NAME, app_id, app_secret, app_token)
    )


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_request_inventory_snapshot(
    app_id: str,
    app_secret: str,
    app_token: str,
) -> pd.DataFrame:
    return feishu_inventory_dataframe_from_rows(
        load_feishu_rows_snapshot(MATERIAL_TABLE_NAME, app_id, app_secret, app_token),
        request_visible_only=True,
    )


def load_feishu_inventory() -> pd.DataFrame:
    return feishu_inventory_dataframe_from_rows(feishu_rows(MATERIAL_TABLE_NAME))


def load_feishu_request_inventory() -> pd.DataFrame:
    return feishu_inventory_dataframe_from_rows(
        feishu_rows(MATERIAL_TABLE_NAME),
        request_visible_only=True,
    )


def feishu_options_from_rows(
    categories: list[dict],
    inventory_df: pd.DataFrame,
    model_rows: list[dict] | None = None,
    language_rows: list[dict] | None = None,
    material_rows: list[dict] | None = None,
    *,
    request_visible_only: bool = False,
) -> dict:
    category_products: list[str] = []
    category_display_names: dict[str, dict[str, str]] = {}
    no_model_products: list[str] = []
    no_language_products: list[str] = []
    configured_language_products: list[str] = []
    for row in categories:
        fields = feishu_fields(row)
        product = feishu_text(fields, "物料品类")
        if request_visible_only:
            if not feishu_request_page_visible(fields):
                continue
        if product:
            category_products.append(product)
            category_display_names[product] = {
                LANGUAGE_ZH: feishu_text(fields, "中文页面名称").strip(),
                LANGUAGE_EN: feishu_text(fields, "英文页面名称").strip(),
            }
        if feishu_text(fields, "是否无需型号") == "是":
            no_model_products.append(product)
        no_language_value = feishu_text(fields, "是否无需语种")
        if no_language_value:
            configured_language_products.append(product)
        if no_language_value == "是" or (not no_language_value and is_default_no_language_product(product)):
            no_language_products.append(product)
    inventory_products = (
        unique_preserve(list(inventory_df[PRODUCT_COL].astype(str)))
        if not inventory_df.empty
        else []
    )
    inventory_product_keys = {
        normalize_category_match_key(product) for product in inventory_products
    }
    products = sort_request_products(
        [
            product
            for product in category_products
            if normalize_category_match_key(product) in inventory_product_keys
        ]
    )
    inventory_no_model_products = (
        unique_preserve(list(inventory_df.loc[inventory_df[MODEL_COL] == NO_MODEL_TEXT, PRODUCT_COL].astype(str)))
        if not inventory_df.empty
        else []
    )
    inventory_models = (
        [value for value in inventory_df[MODEL_COL].astype(str) if value and value != NO_MODEL_TEXT]
        if not inventory_df.empty
        else []
    )
    request_model_rows = list(model_rows or [])
    dimension_models = [
        feishu_text(feishu_fields(row), "产品型号")
        for row in request_model_rows
    ]
    model_product_lines = {
        feishu_text(feishu_fields(row), "产品型号").strip(): feishu_text(
            feishu_fields(row), "产品线"
        ).strip()
        for row in request_model_rows
        if feishu_text(feishu_fields(row), "产品型号").strip()
    }
    model_display_names = {
        feishu_text(feishu_fields(row), "产品型号").strip(): {
            LANGUAGE_ZH: feishu_text(feishu_fields(row), "中文页面名称").strip()
            or feishu_text(feishu_fields(row), "产品型号").strip(),
            LANGUAGE_EN: feishu_text(feishu_fields(row), "英文页面名称").strip()
            or feishu_text(feishu_fields(row), "产品型号").strip(),
        }
        for row in request_model_rows
        if feishu_text(feishu_fields(row), "产品型号").strip()
    }
    product_line_by_model_id = {
        feishu_record_id(row): feishu_text(feishu_fields(row), "产品线").strip()
        for row in request_model_rows
        if feishu_record_id(row)
    }
    for material_row in list(material_rows or []):
        material_fields = feishu_fields(material_row)
        model = feishu_text(material_fields, "产品型号").strip()
        linked_product_lines = [
            product_line_by_model_id.get(model_id, "")
            for model_id in feishu_link_ids_any(
                material_fields,
                list(MODEL_LINK_FIELD_CANDIDATES),
            )
        ]
        linked_product_line = next(
            (product_line for product_line in linked_product_lines if product_line),
            "",
        )
        if model and linked_product_line:
            model_product_lines[model] = linked_product_line
    models = sort_models(dimension_models or inventory_models)
    inventory_languages = (
        unique_preserve(list(inventory_df[LANGUAGE_COL].astype(str)))
        if not inventory_df.empty
        else []
    )
    dimension_languages = [
        feishu_language_name(feishu_fields(row))
        for row in list(language_rows or [])
    ]
    languages = sort_languages(dimension_languages or inventory_languages)
    if not inventory_df.empty:
        for product, product_df in inventory_df.groupby(PRODUCT_COL):
            product_languages = {str(value).strip() for value in product_df[LANGUAGE_COL] if str(value).strip()}
            if product_languages == {NO_LANGUAGE_TEXT}:
                no_language_products.append(str(product))
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "products": sort_request_products(products),
        "no_model_products": unique_preserve(no_model_products + inventory_no_model_products),
        "no_language_products": unique_preserve(no_language_products),
        "configured_language_products": unique_preserve(configured_language_products),
        "models": models,
        "model_product_lines": model_product_lines,
        "model_display_names": model_display_names,
        "category_display_names": category_display_names,
        "languages": languages,
        "no_model_text": NO_MODEL_TEXT,
        "no_language_text": NO_LANGUAGE_TEXT,
        "row_count": len(inventory_df),
    }


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_options_snapshot(app_id: str, app_secret: str, app_token: str) -> dict:
    return feishu_options_from_rows(
        load_feishu_rows_snapshot(CATEGORY_TABLE_NAME, app_id, app_secret, app_token),
        load_feishu_request_inventory_snapshot(app_id, app_secret, app_token),
        load_feishu_rows_snapshot(MODEL_TABLE_NAME, app_id, app_secret, app_token),
        page_data_cache_rows(LANGUAGE_TABLE_NAME),
        load_feishu_rows_snapshot(MATERIAL_TABLE_NAME, app_id, app_secret, app_token),
        request_visible_only=True,
    )


def load_feishu_options() -> dict:
    material_rows = safe_feishu_rows(MATERIAL_TABLE_NAME)
    return feishu_options_from_rows(
        safe_feishu_rows(CATEGORY_TABLE_NAME),
        feishu_inventory_dataframe_from_rows(
            material_rows,
            request_visible_only=True,
        ),
        safe_feishu_rows(MODEL_TABLE_NAME),
        safe_feishu_rows(LANGUAGE_TABLE_NAME),
        material_rows,
        request_visible_only=True,
    )


def feishu_transactions_dataframe_from_rows(rows: list[dict]) -> pd.DataFrame:
    data: list[list[object]] = []
    for row in rows:
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


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_transactions_dataframe_snapshot(app_id: str, app_secret: str, app_token: str) -> pd.DataFrame:
    return feishu_transactions_dataframe_from_rows(
        load_feishu_rows_snapshot(LEDGER_TABLE_NAME, app_id, app_secret, app_token)
    )


def load_feishu_transactions_dataframe() -> pd.DataFrame:
    return feishu_transactions_dataframe_from_rows(feishu_rows(LEDGER_TABLE_NAME))


def feishu_ledger_type(action: str) -> str:
    return action


def build_feishu_ledger_fields(
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
) -> dict[str, object]:
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
    return fields


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
    fields = build_feishu_ledger_fields(
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
        status=status,
        original_ledger_id=original_ledger_id,
        source_request_id=source_request_id,
        source_line_id=source_line_id,
        source_request_no=source_request_no,
        idempotency_key=idempotency_key,
    )

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
            source_request_id=str(item.get("source_request_id") or ""),
            source_line_id=str(item.get("source_line_id") or ""),
            source_request_no=str(item.get("source_request_no") or ""),
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


def build_restock_no(submission_token: object, occurred_at: datetime | None = None) -> str:
    timestamp = occurred_at or datetime.now()
    token = re.sub(r"[^A-Za-z0-9]", "", str(submission_token or "")).upper()
    suffix = token[:6] or uuid.uuid4().hex[:6].upper()
    return f"{RESTOCK_NO_PREFIX}-{timestamp.strftime('%Y%m%d')}-{suffix}"


def validate_restock_draft(draft: dict[str, object]) -> list[str]:
    errors: list[str] = []
    mode = str(draft.get("mode") or "restock")
    if mode not in {"restock", "reduce"}:
        errors.append("请选择补库或减库模式")
    if not str(draft.get("operator") or "").strip():
        errors.append("请填写操作人")
    lines = [line for line in list(draft.get("lines") or []) if isinstance(line, dict)]
    if not lines:
        errors.append("请至少加入一种操作物料")
        return errors
    if len(lines) > MAX_RESTOCK_LINE_COUNT:
        errors.append(f"一次补库最多可添加 {MAX_RESTOCK_LINE_COUNT} 种物料")
    seen: set[tuple[str, str, str]] = set()
    for index, line in enumerate(lines, start=1):
        key = request_material_key(line)
        if not all(key):
            errors.append(f"第 {index} 条操作明细缺少品类、型号或语种")
        if int(line.get("quantity") or 0) <= 0:
            errors.append(f"第 {index} 条{'减库' if mode == 'reduce' else '补库'}数量必须大于 0")
        if key in seen:
            errors.append(f"第 {index} 条操作物料重复，请合并数量")
        seen.add(key)
    return errors


def create_missing_restock_material_records(
    lines: list[dict[str, object]],
    restock_records: list[dict],
    restock_by_key: dict[tuple[str, str, str], dict],
    raw_material_by_id: dict[str, dict],
    category_records: list[dict],
) -> int:
    category_by_product = {
        normalize_category_match_key(item.get("category")): item
        for item in category_records
        if str(item.get("category") or "").strip()
    }
    missing_keys: list[tuple[str, str, str]] = []
    for line in lines:
        key = request_material_key(line)
        if key in restock_by_key or key in missing_keys:
            continue
        category = category_by_product.get(normalize_category_match_key(key[0]))
        if (
            category is None
            or not category.get("no_model")
            or not category.get("no_language")
            or key[1] != NO_MODEL_TEXT
            or key[2] != NO_LANGUAGE_TEXT
        ):
            raise RuntimeError(f"补库物料不存在：{key[0]} / {key[1]} / {key[2]}")
        missing_keys.append(key)

    if not missing_keys:
        return 0

    new_codes = next_material_codes_from_records(restock_records, len(missing_keys))
    model_link_field, model_record_ids = ensure_feishu_model_records([NO_MODEL_TEXT])
    language_link_field, language_record_ids = ensure_feishu_language_records(
        [NO_LANGUAGE_TEXT]
    )
    create_fields: list[dict[str, object]] = []
    for key, material_code in zip(missing_keys, new_codes):
        category = category_by_product[normalize_category_match_key(key[0])]
        fields: dict[str, object] = {
            "物料编码": material_code,
            "物料品类": str(category.get("category") or key[0]),
            "产品型号": NO_MODEL_TEXT,
            "语种": NO_LANGUAGE_TEXT,
            "当前库存": 0,
            "启用状态": STATUS_INACTIVE,
            "备注": "",
            "品类关联": [str(category.get("record_id") or "")],
        }
        set_feishu_unit_price(
            MATERIAL_TABLE_NAME,
            fields,
            float(category.get("unit_price") or 0),
        )
        set_feishu_customs_code(
            MATERIAL_TABLE_NAME,
            fields,
            str(category.get("customs_code") or ""),
        )
        add_material_model_link(
            fields,
            NO_MODEL_TEXT,
            model_link_field,
            model_record_ids,
        )
        add_material_language_link(
            fields,
            NO_LANGUAGE_TEXT,
            language_link_field,
            language_record_ids,
        )
        create_fields.append(fields)

    created_rows = feishu_batch_create_records(MATERIAL_TABLE_NAME, create_fields)
    if len(created_rows) != len(create_fields):
        raise RuntimeError("缺失的补库物料主数据未完整创建。")

    category_updates: dict[str, dict[str, object]] = {}
    for key, material_code, fields, created_row in zip(
        missing_keys,
        new_codes,
        create_fields,
        created_rows,
    ):
        record_id = feishu_record_id(created_row)
        if not record_id:
            raise RuntimeError("创建补库物料主数据后未返回记录 ID。")
        restock_by_key[key] = {
            "record_id": record_id,
            "material_code": material_code,
            "category": key[0],
            "model": key[1],
            "language": key[2],
            "quantity": 0,
            "unit_price": feishu_float_any(fields, list(UNIT_PRICE_FIELD_CANDIDATES)),
            "status": STATUS_INACTIVE,
        }
        raw_material_by_id[record_id] = {"record_id": record_id, "fields": fields}
        category = category_by_product[normalize_category_match_key(key[0])]
        category_id = str(category.get("record_id") or "")
        category_updates[category_id] = {
            "record_id": category_id,
            "fields": {
                "库存行数": 1,
                "产品型号数量": 1,
                "语种数量": 1,
            },
        }
    feishu_batch_update_record_fields(
        CATEGORY_TABLE_NAME,
        list(category_updates.values()),
    )
    return len(created_rows)


def submit_inventory_restock(draft: dict[str, object]) -> list[dict[str, object]]:
    errors = validate_restock_draft(draft)
    if errors:
        raise RuntimeError("；".join(errors))
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法保存采购补库。")

    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    raw_material_by_id = {feishu_record_id(row): row for row in material_rows}
    restock_records = feishu_inventory_records_from_rows(
        material_rows,
        category_rows,
        active_only=False,
    )
    restock_by_key = {
        (
            str(record.get("category") or ""),
            str(record.get("model") or NO_MODEL_TEXT),
            str(record.get("language") or NO_LANGUAGE_TEXT),
        ): record
        for record in restock_records
    }
    category_records = feishu_category_records_from_rows(category_rows)
    draft_lines = [
        line
        for line in list(draft.get("lines") or [])
        if isinstance(line, dict)
    ]
    create_missing_restock_material_records(
        draft_lines,
        restock_records,
        restock_by_key,
        raw_material_by_id,
        category_records,
    )
    category_definition_by_product = {
        str(item.get("category") or ""): str(
            item.get("category_definition") or UNDEFINED_CATEGORY_DEFINITION
        )
        for item in category_records
    }
    restock_no = str(draft.get("restock_no") or "").strip()
    operator = str(draft.get("operator") or "").strip()
    purchase_order_no = str(draft.get("purchase_order_no") or "").strip()
    overall_note = str(draft.get("note") or "").strip()
    mode = str(draft.get("mode") or "restock")
    operation_label = "减库" if mode == "reduce" else "补库"
    ledger_action = ACTION_RECEIVE if mode == "reduce" else ACTION_PURCHASE
    submission_token = str(draft.get("submission_token") or "").strip() or uuid.uuid4().hex
    occurred_at = datetime.now()
    prepared: list[dict[str, object]] = []
    for index, line in enumerate(draft_lines, start=1):
        product, model, language = request_material_key(line)
        record = restock_by_key.get((product, model, language))
        if record is None:
            raise RuntimeError(f"补库物料不存在：{product} / {model} / {language}")
        record_id = str(record.get("record_id") or "")
        raw_row = raw_material_by_id.get(record_id, {})
        before_quantity = feishu_int(feishu_fields(raw_row), "当前库存")
        quantity = int(line.get("quantity") or 0)
        after_quantity = before_quantity - quantity if mode == "reduce" else before_quantity + quantity
        line_note = str(line.get("remark") or "").strip()
        note_parts = [f"{operation_label}单 {restock_no}", f"操作人：{operator}"]
        if purchase_order_no:
            note_parts.append(f"采购单号：{purchase_order_no}")
        if overall_note:
            note_parts.append(f"{operation_label}说明：{overall_note}")
        if line_note:
            note_parts.append(f"明细备注：{line_note}")
        prepared.append(
            {
                "record_id": record_id,
                "material_code": str(record.get("material_code") or ""),
                "product": product,
                "category_definition": category_definition_by_product.get(
                    product,
                    str(line.get("category_definition") or UNDEFINED_CATEGORY_DEFINITION),
                ),
                "model": model,
                "language": language,
                "quantity": quantity,
                "before_quantity": before_quantity,
                "before_status": normalize_enabled_status(
                    feishu_text(feishu_fields(raw_row), "启用状态")
                ),
                "after_quantity": after_quantity,
                "remark": line_note,
                "ledger_note": "；".join(note_parts),
                "idempotency_key": f"restock:{submission_token}:{index}",
            }
        )

    inventory_updates = [
        {
            "record_id": str(item["record_id"]),
            "fields": {
                "当前库存": int(item["after_quantity"]),
                "启用状态": (
                    str(item.get("before_status") or STATUS_ACTIVE)
                    if mode == "reduce"
                    else STATUS_ACTIVE
                ),
            },
        }
        for item in prepared
    ]
    rollback_updates = [
        {
            "record_id": str(item["record_id"]),
            "fields": {
                "当前库存": int(item["before_quantity"]),
                "启用状态": str(item.get("before_status") or STATUS_ACTIVE),
            },
        }
        for item in prepared
    ]
    ledger_fields = [
        build_feishu_ledger_fields(
            str(item["record_id"]),
            ledger_action,
            str(item["product"]),
            str(item["model"]),
            str(item["language"]),
            int(item["quantity"]),
            int(item["before_quantity"]),
            int(item["after_quantity"]),
            str(item["ledger_note"]),
            occurred_at,
            idempotency_key=str(item["idempotency_key"]),
        )
        for item in prepared
    ]
    try:
        updated_count = feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, inventory_updates)
        if updated_count != len(prepared):
            raise RuntimeError("物料主数据未完整更新。")
        created_ledgers = feishu_batch_create_records(LEDGER_TABLE_NAME, ledger_fields)
        if len(created_ledgers) != len(prepared):
            raise RuntimeError("库存流水未完整写入。")
    except Exception:
        try:
            feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, rollback_updates)
        except Exception:
            pass
        raise
    return prepared


def next_request_no() -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"{REQUEST_NO_PREFIX}-{today}-"
    max_number = 0
    for row in fresh_feishu_rows(REQUEST_TABLE_NAME):
        request_no = feishu_text(feishu_fields(row), "申请单号")
        if request_no.startswith(prefix):
            suffix = request_no.removeprefix(prefix)
            if suffix.isdigit():
                max_number = max(max_number, int(suffix))
    return f"{prefix}{max_number + 1:03d}"


def request_row_sort_key(row: dict) -> tuple[int, str]:
    submitted_value = feishu_fields(row).get("提交时间", 0)
    try:
        submitted_at = int(submitted_value)
    except (TypeError, ValueError):
        submitted_at = 0
    return submitted_at, feishu_record_id(row)


def submission_token_rows(submission_token: str) -> list[dict]:
    if not submission_token or not feishu_has_field(REQUEST_TABLE_NAME, "提交幂等键"):
        return []
    rows = [
        row
        for row in fresh_feishu_rows(REQUEST_TABLE_NAME)
        if feishu_text(feishu_fields(row), "提交幂等键") == submission_token
    ]
    return sorted(rows, key=request_row_sort_key)


def request_line_rows_by_request_id() -> tuple[list[dict], dict[str, list[dict]]]:
    rows = fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
    result: dict[str, list[dict]] = {}
    for row in rows:
        request_ids = feishu_link_ids_any(feishu_fields(row), ["所属申请单", "申请单"])
        for request_id in request_ids:
            result.setdefault(str(request_id), []).append(row)
    return rows, result


def find_completed_submission(submission_token: str) -> tuple[dict, int] | None:
    request_rows = submission_token_rows(submission_token)
    if not request_rows:
        return None
    _, lines_by_request_id = request_line_rows_by_request_id()
    for row in request_rows:
        line_count = len(lines_by_request_id.get(feishu_record_id(row), []))
        if line_count > 0:
            return row, line_count
    return None


def cleanup_incomplete_submission_rows(submission_token: str) -> int:
    client = feishu_client()
    if client is None or not submission_token:
        return 0
    request_rows = submission_token_rows(submission_token)
    if not request_rows:
        return 0
    _, lines_by_request_id = request_line_rows_by_request_id()
    removed = 0
    for row in request_rows:
        record_id = feishu_record_id(row)
        if record_id and not lines_by_request_id.get(record_id):
            client.delete_record(feishu_table_id(REQUEST_TABLE_NAME), record_id)
            removed += 1
    return removed


def ensure_unique_request_no(request_record_id: str, request_no: str, submission_token: str) -> str:
    client = feishu_client()
    if client is None:
        return request_no
    current_request_no = request_no
    for _ in range(5):
        matching_rows = [
            row
            for row in fresh_feishu_rows(REQUEST_TABLE_NAME)
            if feishu_text(feishu_fields(row), "申请单号") == current_request_no
        ]
        if len(matching_rows) <= 1:
            return current_request_no
        matching_rows.sort(key=request_row_sort_key)
        canonical_row = matching_rows[0]
        if feishu_record_id(canonical_row) == request_record_id:
            return current_request_no
        canonical_token = feishu_text(feishu_fields(canonical_row), "提交幂等键")
        if submission_token and canonical_token == submission_token:
            return current_request_no
        current_request_no = next_request_no()
        client.update_record(
            feishu_table_id(REQUEST_TABLE_NAME),
            request_record_id,
            {"申请单号": current_request_no},
        )
    raise RuntimeError("申请单号并发冲突，请重新提交。")


def reconcile_submission_duplicates(submission_token: str, current_request_id: str) -> tuple[dict | None, int]:
    client = feishu_client()
    if client is None or not submission_token:
        return None, 0
    request_rows = submission_token_rows(submission_token)
    if len(request_rows) <= 1:
        return (request_rows[0], 0) if request_rows else (None, 0)

    _, lines_by_request_id = request_line_rows_by_request_id()
    completed_rows = [row for row in request_rows if lines_by_request_id.get(feishu_record_id(row))]
    if len(completed_rows) <= 1:
        current_row = next((row for row in request_rows if feishu_record_id(row) == current_request_id), None)
        return current_row, 0

    completed_rows.sort(key=request_row_sort_key)
    canonical_row = completed_rows[0]
    canonical_id = feishu_record_id(canonical_row)
    removed_count = 0
    for duplicate_row in completed_rows[1:]:
        duplicate_id = feishu_record_id(duplicate_row)
        for line_row in lines_by_request_id.get(duplicate_id, []):
            client.delete_record(feishu_table_id(REQUEST_LINE_TABLE_NAME), feishu_record_id(line_row))
        client.delete_record(feishu_table_id(REQUEST_TABLE_NAME), duplicate_id)
        removed_count += 1
    return canonical_row if canonical_id else None, removed_count


def material_lookup_by_key() -> dict[tuple[str, str, str], dict]:
    return feishu_inventory_index()


def request_customer_display_label(request_payload: dict[str, object]) -> str:
    return (
        "代理商名称"
        if str(request_payload.get("request_reason") or "").strip()
        in {"代理商支持", "代理活动"}
        else "客户名称"
    )


def request_note_text(request_payload: dict[str, object]) -> str:
    parts = [
        (request_customer_display_label(request_payload), request_payload.get("customer_name")),
        ("国家", request_payload.get("country")),
        ("收件人信息", request_payload.get("recipient_info")),
        ("运费承担者", request_payload.get("freight_payer")),
        ("物料用途", request_payload.get("material_usage")),
        ("申请人", request_payload.get("requester")),
    ]
    return "\n".join(f"{label}：{str(value).strip()}" for label, value in parts if str(value or "").strip())


def feishu_person_open_ids(fields: dict, names: list[str]) -> list[str]:
    open_ids: list[str] = []
    for name in names:
        value = fields.get(name)
        items = value if isinstance(value, list) else ([value] if value else [])
        for item in items:
            if not isinstance(item, dict):
                continue
            open_id = str(item.get("open_id") or item.get("id") or "").strip()
            if open_id.startswith("ou_") and open_id not in open_ids:
                open_ids.append(open_id)
    return open_ids


def feishu_choice_values(fields: dict, name: str) -> list[str]:
    value = fields.get(name)
    items = value if isinstance(value, list) else ([value] if value not in (None, "") else [])
    choices: list[str] = []
    for item in items:
        if isinstance(item, dict):
            text_arr = item.get("text_arr") or []
            choice = str(
                item.get("name")
                or item.get("value")
                or item.get("text")
                or (text_arr[0] if text_arr else "")
            ).strip()
        else:
            choice = str(item).strip()
        if choice and choice not in choices:
            choices.append(choice)
    return choices


def feishu_permission_enabled(fields: dict) -> bool:
    enabled_values = {
        value.casefold() for value in feishu_choice_values(fields, "是否启用")
    }
    return bool(enabled_values & {"是", "启用", "true", "1", "yes"})


def enabled_role_open_ids(role_name: str) -> list[str]:
    open_ids: list[str] = []
    for row in fresh_feishu_rows(USER_PERMISSION_TABLE_NAME):
        fields = feishu_fields(row)
        roles = set(feishu_choice_values(fields, "角色"))
        if role_name not in roles or not feishu_permission_enabled(fields):
            continue
        for open_id in feishu_person_open_ids(fields, ["用户账号", "用户", "成员"]):
            if open_id not in open_ids:
                open_ids.append(open_id)
    return open_ids


def requester_has_enabled_role(requester_open_id: object, role_name: str) -> bool:
    """Read the enabled permission row for a requester without name matching."""
    target = str(requester_open_id or "").strip()
    if not target:
        return False
    for row in fresh_feishu_rows(USER_PERMISSION_TABLE_NAME):
        fields = feishu_fields(row)
        if not feishu_permission_enabled(fields):
            continue
        if target in feishu_person_open_ids(fields, ["用户账号", "用户", "成员"]):
            return role_name in feishu_choice_values(fields, "角色")
    return False


def ensure_order_scheduling_fields() -> None:
    """Create the explicit fulfillment columns required by order scheduling."""
    from order_scheduling import (
        ARRIVAL_DATE,
        BATCH_TABLE,
        DETAIL_TABLE,
        FULFILLMENT_STATUS,
        ORDER_DATE,
        SHIP_DATE,
        USAGE_DATE,
    )
    refresh_feishu_schema_cache()
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建下单排期履约字段。")
    options = [{"name": value} for value in ("待安排", "已下单", "制作中", "已发货", "已到货", "已完成", "无需下单", "已取消")]
    required = {
        REQUEST_TABLE_NAME: ((USAGE_DATE, 5, None), (ORDER_DATE, 5, None), (ARRIVAL_DATE, 5, None),
                             (SHIP_DATE, 5, None), (FULFILLMENT_STATUS, 3, {"options": options})),
        REQUEST_LINE_TABLE_NAME: ((USAGE_DATE, 5, None), (ORDER_DATE, 5, None), (ARRIVAL_DATE, 5, None),
                                  (SHIP_DATE, 5, None), ("计划到仓日期", 5, None),
                                  (FULFILLMENT_STATUS, 3, {"options": options})),
        BATCH_TABLE: ((USAGE_DATE, 5, None), (ORDER_DATE, 5, None), (ARRIVAL_DATE, 5, None),
                      (SHIP_DATE, 5, None)),
        DETAIL_TABLE: ((USAGE_DATE, 5, None), (ORDER_DATE, 5, None), (ARRIVAL_DATE, 5, None),
                       (SHIP_DATE, 5, None)),
    }
    request_reason_options = [{"name": value} for value in ("代理商支持", "展会需求", "客户来访", "其他")]
    for table, fields in required.items():
        table_id = feishu_table_id(table)
        live_field_rows = client.list_fields(table_id)
        live_fields = {str(field.get("field_name") or ""): field for field in live_field_rows}
        for field_name, field_type, prop in fields:
            if field_name not in live_fields:
                client.create_field(table_id, field_name, field_type, prop)
                live_fields[field_name] = {"field_name": field_name, "type": field_type}
        if table == REQUEST_TABLE_NAME and "申请原因" in live_fields:
            reason_field = live_fields["申请原因"]
            if int(reason_field.get("type") or 0) == 3:
                current_options = {
                    str(option.get("name") or "")
                    for option in dict(reason_field.get("property") or {}).get("options", [])
                }
                if "代理商支持" not in current_options:
                    retained_legacy_options = [
                        {"name": option}
                        for option in sorted(current_options - {item["name"] for item in request_reason_options})
                        if option
                    ]
                    client.update_field(
                        table_id,
                        str(reason_field.get("field_id") or ""),
                        "申请原因",
                        3,
                        {"options": request_reason_options + retained_legacy_options},
                    )
    refresh_feishu_schema_cache()


def enabled_admin_open_ids() -> list[str]:
    return enabled_role_open_ids("管理员")


@st.cache_data(show_spinner=False, ttl=120)
def cached_enabled_admin_open_ids(
    app_id: str,
    app_secret: str,
    app_token: str,
) -> list[str]:
    del app_id, app_secret, app_token
    return enabled_admin_open_ids()


def enabled_sales_open_ids() -> list[str]:
    return enabled_role_open_ids("销售")


def next_user_permission_number(rows: list[dict]) -> str:
    numbers: list[int] = []
    for row in rows:
        raw_number = feishu_text(feishu_fields(row), "用户编号").strip()
        if raw_number.isdigit():
            numbers.append(int(raw_number))
    return str(max(numbers, default=0) + 1)


def ensure_requester_sales_permission(request_payload: dict[str, object]) -> str:
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    if not requester_open_id.startswith("ou_"):
        raise RuntimeError("申请人未关联有效的飞书账号，无法自动加入销售权限。")

    rows = fresh_feishu_rows(USER_PERMISSION_TABLE_NAME)
    for row in rows:
        fields = feishu_fields(row)
        if requester_open_id not in feishu_person_open_ids(
            fields, ["用户账号", "用户", "成员"]
        ):
            continue
        roles = feishu_choice_values(fields, "角色")
        if "销售" in roles:
            return "existing"
        record_id = feishu_record_id(row)
        if not record_id:
            raise RuntimeError("申请人的权限记录缺少记录 ID，无法补充销售身份。")
        feishu_update_record_fields(
            USER_PERMISSION_TABLE_NAME,
            record_id,
            {"角色": [*roles, "销售"]},
        )
        return "updated"

    new_fields: dict[str, object] = {
        "用户编号": next_user_permission_number(rows),
        "用户账号": [{"id": requester_open_id}],
        "角色": ["销售"],
        "是否启用": "是",
    }
    created = feishu_create_record(USER_PERMISSION_TABLE_NAME, new_fields)
    if not created:
        raise RuntimeError("写入用户权限表失败。")
    return "created"


def material_request_notification_text(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> str:
    valid_lines = [line for line in lines if int(line.get("quantity") or 0) > 0]
    total_rmb = request_lines_total_rmb(valid_lines)
    details = [
        (
            f"{index}. {str(line.get('product') or '-')} / "
            f"{request_model_display_label(line.get('model'), language=LANGUAGE_ZH)} / "
            f"{str(line.get('language') or NO_LANGUAGE_TEXT)} × {int(line.get('quantity') or 0)}"
        )
        for index, line in enumerate(valid_lines, start=1)
    ]
    parts = [
        (
            f"【来自{str(request_payload.get('department') or '-')}的"
            f"{str(request_payload.get('requester') or '-')}的营销物料即将进入审批流程，"
            f"本批物料的用途为{str(request_payload.get('material_usage') or '-')}，"
            "请关注飞书审批进度。】"
        ),
        f"申请单号：{request_no}",
        f"申请人：{str(request_payload.get('requester') or '-')}",
        f"申请部门：{str(request_payload.get('department') or '-')}",
        f"{request_customer_display_label(request_payload)}/国家：{str(request_payload.get('customer_name') or '-')} / {str(request_payload.get('country') or '-')}",
        f"物料用途：{str(request_payload.get('material_usage') or '-')}",
        f"申请原因：{str(request_payload.get('request_reason') or '-')}",
        f"申请总金额：{format_rmb(total_rmb)}",
        "",
        *details,
    ]
    return "\n".join(parts)


def _feishu_card_plain_text(value: object, *, max_length: int = 1600) -> str:
    text = str(value or "-").strip() or "-"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[:max_length]


def _feishu_card_text_element(
    value: object,
    *,
    max_length: int = 1600,
    text_size: str = "normal",
    text_color: str = "default",
    lines: int = 4,
) -> dict[str, object]:
    return {
        "tag": "div",
        "text": {
            "tag": "plain_text",
            "content": _feishu_card_plain_text(value, max_length=max_length),
            "text_size": text_size,
            "text_color": text_color,
            "lines": lines,
        },
    }


def _feishu_notification_field(label: str, value: object) -> dict[str, object]:
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_spacing": "2px",
                "elements": [
                    _feishu_card_text_element(
                        label,
                        max_length=80,
                        text_size="notation",
                        text_color="grey-500",
                        lines=1,
                    ),
                    _feishu_card_text_element(value, max_length=500, lines=4),
                ],
            }
        ],
    }


def _feishu_notification_field_grid(
    fields: list[tuple[str, object]],
) -> dict[str, object]:
    left_fields = fields[::2]
    right_fields = fields[1::2]
    columns: list[dict[str, object]] = []
    for column_fields in (left_fields, right_fields):
        if not column_fields:
            continue
        columns.append(
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_spacing": "16px",
                "elements": [
                    _feishu_notification_field(label, value)
                    for label, value in column_fields
                ],
            }
        )
    return {
        "tag": "column_set",
        "flex_mode": "bisect" if len(columns) == 2 else "none",
        "horizontal_spacing": "16px",
        "columns": columns,
    }


def _feishu_notification_section(
    title: str,
    elements: list[dict[str, object]],
    *,
    color: str,
    focus: bool = False,
    last: bool = False,
) -> dict[str, object]:
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "margin": "0px" if last else "0px 0px 12px 0px",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "background_style": f"{color}-50",
                "padding": "12px",
                "vertical_spacing": "12px",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"**<font color='{color}'>{title}</font>**",
                        "text_size": "heading-4" if focus else "normal",
                    },
                    *elements,
                ],
            }
        ],
    }


def _feishu_inventory_review_table(
    lines: list[dict[str, object]],
) -> dict[str, object]:
    """Build one paginated table so large requests stay below card element limits."""
    rows: list[dict[str, object]] = []
    for index, line in enumerate(lines, start=1):
        requested = int(line.get("quantity") or 0)
        current_stock = int(line.get("current_stock") or line.get("stock_snapshot") or 0)
        status = (
            INVENTORY_RESULT_SUFFICIENT
            if current_stock > 0 and current_stock >= requested
            else "库存不足，需要制作"
        )
        specification = (
            f"{line.get('product') or '-'} / "
            f"{request_model_display_label(line.get('model'), language=LANGUAGE_ZH)} / "
            f"{line.get('language') or NO_LANGUAGE_TEXT}"
        )
        remark = str(line.get("remark") or "").strip()
        if remark:
            specification += f"\n备注：{_feishu_card_plain_text(remark, max_length=300)}"
        rows.append(
            {
                "sequence": index,
                "specification": specification,
                "requested": requested,
                "stock": current_stock,
                "result": status,
            }
        )
    return {
        "tag": "table",
        "page_size": 10,
        "row_height": "auto",
        "row_max_height": "96px",
        "freeze_first_column": True,
        "header_style": {
            "background_style": "grey",
            "bold": True,
            "lines": 1,
        },
        "columns": [
            {
                "name": "sequence",
                "display_name": "序号",
                "data_type": "number",
                "width": "80px",
                "horizontal_align": "center",
            },
            {
                "name": "specification",
                "display_name": "物料规格（品类 / 型号 / 语种）",
                "data_type": "text",
            },
            {
                "name": "requested",
                "display_name": "申请数",
                "data_type": "number",
                "width": "80px",
                "horizontal_align": "right",
            },
            {
                "name": "stock",
                "display_name": "实时库存",
                "data_type": "number",
                "width": "90px",
                "horizontal_align": "right",
            },
            {
                "name": "result",
                "display_name": "库存结果",
                "data_type": "text",
                "width": "140px",
            },
        ],
        "rows": rows,
    }


def _feishu_requester_material_table(
    lines: list[dict[str, object]], *, english: bool = False
) -> dict[str, object]:
    """Render compact request details as one paginated element.

    Keeping every line inside a single table avoids the card element-count
    failures caused by one markdown block per requested material.
    """
    rows: list[dict[str, object]] = []
    for index, line in enumerate(lines, start=1):
        product = str(line.get("product") or "-")
        model = request_model_display_label(
            line.get("model"), language=LANGUAGE_EN if english else LANGUAGE_ZH
        )
        dimension = str(
            line.get("language") or line.get("region") or NO_LANGUAGE_TEXT
        )
        if english:
            product = english_material_notification_label(product)
            dimension = english_material_notification_label(dimension)
        specification = f"{product} / {model} / {dimension}"
        remark = str(line.get("remark") or "").strip()
        if remark:
            specification += (
                f"\n{'Remark' if english else '备注'}："
                f"{_feishu_card_plain_text(remark, max_length=300)}"
            )
        row: dict[str, object] = {
            "sequence": index,
            "specification": specification,
            "quantity": int(line.get("quantity") or 0),
        }
        if line.get("remaining_stock") is not None:
            row["remaining_stock"] = int(line.get("remaining_stock"))
        rows.append(row)
    has_remaining_stock = any(
        row.get("remaining_stock") is not None for row in rows
    )
    return {
        "tag": "table",
        "page_size": 10,
        "row_height": "auto",
        "row_max_height": "96px",
        "freeze_first_column": True,
        "header_style": {
            "background_style": "grey",
            "bold": True,
            "lines": 1,
        },
        "columns": [
            {
                "name": "sequence",
                "display_name": "No." if english else "序号",
                "data_type": "number",
                "width": "80px",
                "horizontal_align": "center",
            },
            {
                "name": "specification",
                "display_name": (
                    "Material / Model / Language or Region"
                    if english
                    else "物料 / 型号 / 语种或战区"
                ),
                "data_type": "text",
            },
            {
                "name": "quantity",
                "display_name": "Qty" if english else "数量",
                "data_type": "number",
                "width": "80px",
                "horizontal_align": "right",
            },
            *(
                [
                    {
                        "name": "remaining_stock",
                        "display_name": "Remaining" if english else "领取后库存",
                        "data_type": "number",
                        "width": "100px",
                        "horizontal_align": "right",
                    }
                ]
                if has_remaining_stock
                else []
            ),
        ],
        "rows": rows,
    }


def _feishu_notification_table(
    columns: list[dict[str, object]],
    rows: list[dict[str, object]],
    *,
    page_size: int = 10,
    freeze_first_column: bool = True,
) -> dict[str, object]:
    """Build the shared paginated table used by material-detail notifications."""
    return {
        "tag": "table",
        "page_size": page_size,
        "row_height": "auto",
        "row_max_height": "96px",
        "freeze_first_column": freeze_first_column,
        "header_style": {
            "background_style": "grey",
            "bold": True,
            "lines": 1,
        },
        "columns": columns,
        "rows": rows,
    }


def _feishu_normalize_card_tables(value: object) -> object:
    """Normalize table columns to Feishu Card JSON 2.0 constraints."""
    if isinstance(value, list):
        return [_feishu_normalize_card_tables(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {
        key: _feishu_normalize_card_tables(item)
        for key, item in value.items()
    }
    if normalized.get("tag") != "table":
        return normalized
    columns = [
        dict(column)
        for column in list(normalized.get("columns") or [])
        if isinstance(column, dict)
    ]
    key_map: dict[str, str] = {}
    for index, column in enumerate(columns):
        original_name = str(column.get("name") or "")
        safe_name = f"c{index}"
        if original_name:
            key_map[original_name] = safe_name
        column["name"] = safe_name
        width = str(column.get("width") or "").strip().lower()
        if width.endswith("px") and width[:-2].isdigit():
            column["width"] = f"{min(600, max(80, int(width[:-2])))}px"
    normalized["columns"] = columns
    normalized["rows"] = [
        {
            key_map.get(str(key), str(key)): item
            for key, item in row.items()
        }
        for row in list(normalized.get("rows") or [])
        if isinstance(row, dict)
    ]
    return normalized


def _feishu_notification_card_v2(
    title: str,
    template: str,
    elements: list[dict[str, object]],
) -> dict[str, object]:
    """Wrap notification elements in the card 2.0 schema required by tables."""
    safe_elements = _feishu_normalize_card_tables(elements)
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "fill",
            "summary": {"content": title},
        },
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "10px",
            "elements": safe_elements,
        },
    }


def material_request_notification_card(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
    *,
    review_context: dict[str, object] | None = None,
    operator_open_id: str = "",
) -> dict[str, object]:
    context = dict(review_context or {})
    review_request = dict(context.get("request") or {})
    review_lines = [dict(line) for line in list(context.get("lines") or []) if isinstance(line, dict)]
    valid_lines = review_lines or [line for line in lines if int(line.get("quantity") or 0) > 0]
    total_quantity = sum(int(line.get("quantity") or 0) for line in valid_lines)
    total_rmb = request_lines_total_rmb(valid_lines)
    application_fields: list[tuple[str, object]] = [
        ("申请单号", request_no),
        ("申请人", request_payload.get("requester")),
        ("申请部门", request_payload.get("department")),
        ("标题", request_payload.get("title")),
        (
            "物料使用时间",
            review_request.get("material_usage_time")
            or request_payload.get("material_usage_time")
            or "-",
        ),
        (request_customer_display_label(request_payload), request_payload.get("customer_name")),
        ("国家", request_payload.get("country")),
        ("运费承担者", request_payload.get("freight_payer")),
        ("申请原因", request_payload.get("request_reason") or review_request.get("request_reason")),
        ("申请总金额", format_rmb(total_rmb)),
        ("申请合计", f"{len(valid_lines)} 种，共 {total_quantity} 件"),
    ]
    header_title = "营销物料申请库存确认"
    review_result = str(context.get("result") or "")
    review_status = str(review_request.get("inventory_review_status") or INVENTORY_REVIEW_PENDING)
    review_status_display = review_status
    snapshot_at = str(context.get("snapshot_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    elements = [
        _feishu_notification_section(
            "库存审查",
            [
                _feishu_notification_field_grid(
                    [
                        ("审查状态", review_status_display),
                        ("库存结论", review_result or "待计算"),
                        ("库存快照时间", snapshot_at),
                        ("申请变更次数", review_request.get("inventory_review_version", 0)),
                        (
                            "计划核实时间",
                            review_request.get("inventory_review_reminder_at") or "未设置",
                        ),
                    ]
                )
            ],
            color="blue",
            focus=True,
        ),
        _feishu_notification_section(
            "申请信息",
            [_feishu_notification_field_grid(application_fields)],
            color="orange",
            focus=True,
        ),
        _feishu_notification_section(
            "收件人信息",
            [_feishu_card_text_element(request_payload.get("recipient_info"), lines=6)],
            color="orange",
        ),
        _feishu_notification_section(
            "物料用途",
            [_feishu_card_text_element(request_payload.get("material_usage"), lines=6)],
            color="orange",
        ),
        {
            "tag": "markdown",
            "content": "**物料明细与实时库存**",
            "text_size": "heading-4",
            "margin": "0px 0px 8px 0px",
        },
        _feishu_inventory_review_table(valid_lines),
    ]
    request_id = str(review_request.get("record_id") or "")
    if request_id and review_status != INVENTORY_REVIEW_CONFIRMED:
        base_url = get_secret_value(
            "LOCAL_APP_URL",
            DEFAULT_LOCAL_APP_URL,
        ).rstrip("/") + "/"
        edit_args = {
            "allocation": "request",
            "request_id": request_id,
        }
        if operator_open_id:
            edit_args.update(
                {
                    "operator": operator_open_id,
                    "review_token": request_review_access_token(request_id, operator_open_id),
                }
            )
        edit_url = f"{base_url}?{url_parse.urlencode(edit_args)}"
        elements.extend(
            [
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
                                "text": {"tag": "plain_text", "content": "调整配货方案"},
                                "type": "default",
                                "behaviors": [
                                    {
                                        "type": "open_url",
                                        "default_url": edit_url,
                                        "pc_url": edit_url,
                                        "ios_url": edit_url,
                                        "android_url": edit_url,
                                    }
                                ],
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
                                "text": {"tag": "plain_text", "content": "驳回申请"},
                                "type": "danger_filled",
                                "behaviors": [
                                    {
                                        "type": "callback",
                                        "value": {
                                            "action": "reject_request_inventory",
                                            "request_id": request_id,
                                            "request_no": request_no,
                                            "version": int(review_request.get("inventory_review_version") or 0),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
            {
                "tag": "form",
                "name": "request_inventory_confirm_form",
                "vertical_spacing": "8px",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": "**申请单发货日期 ***",
                    },
                    {
                        "tag": "date_picker",
                        "name": "ship_date",
                        "required": True,
                        "width": "fill",
                        "placeholder": {"tag": "plain_text", "content": "请选择发货日期"},
                    },
                    {
                        "tag": "button",
                        "name": (
                            f"confirm_request_inventory__{request_id}__"
                            f"{int(review_request.get('inventory_review_version') or 0)}"
                        ),
                        "text": {"tag": "plain_text", "content": "按原申请确认"},
                        "type": "primary_filled",
                        "form_action_type": "submit",
                        "value": {
                            "action": "confirm_request_inventory",
                            "request_id": request_id,
                            "request_no": request_no,
                            "version": int(review_request.get("inventory_review_version") or 0),
                        },
                    },
                ],
            },
            {
                "tag": "form",
                "name": f"inventory_review_reminder_form__{request_id}",
                "vertical_spacing": "8px",
                "elements": [
                    {
                        "tag": "select_static",
                        "name": "reminder_schedule",
                        "required": True,
                        "width": "fill",
                        "placeholder": {"tag": "plain_text", "content": "选择再次核实库存的时间"},
                        "options": [
                            {
                                "text": {"tag": "plain_text", "content": label},
                                "value": value,
                            }
                            for value, label, _scheduled_at in inventory_review_reminder_schedule_options()
                        ],
                    },
                    {
                        "tag": "button",
                        "name": f"save_inventory_reminder__{request_id}",
                        "text": {"tag": "plain_text", "content": "保存核实时间"},
                        "type": "default",
                        "width": "fill",
                        "form_action_type": "submit",
                    },
                ],
            },
            ]
        )
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "fill",
            "summary": {"content": header_title},
        },
        "header": {
            "template": "green" if review_status == INVENTORY_REVIEW_CONFIRMED else "orange",
            "title": {"tag": "plain_text", "content": header_title},
            "icon": {"tag": "standard_icon", "token": "approve_colorful"},
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {
                        "tag": "plain_text",
                        "content": (
                            INVENTORY_REVIEW_CONFIRMED
                            if review_status == INVENTORY_REVIEW_CONFIRMED
                            else "待确认库存"
                        ),
                    },
                    "color": "green" if review_status == INVENTORY_REVIEW_CONFIRMED else "orange",
                }
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": elements,
        },
    }


def material_request_rejection_card(
    request_no: str,
    requester: str = "申请人",
) -> dict[str, object]:
    title = "营销物料申请已驳回"
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": title},
        },
        "header": {
            "template": "red",
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": request_no or "-"},
            "icon": {"tag": "standard_icon", "token": "close_colorful"},
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": "已驳回"},
                    "color": "red",
                }
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"{requester or '申请人'}，您的营销物料申请已被管理员驳回。"
                        "申请单及申请明细已删除，如有需要请重新提交。"
                    ),
                }
            ],
        },
    }


def request_inventory_card_edit_form(
    request_id: str,
    *,
    error_message: str = "",
) -> dict[str, object]:
    context = request_inventory_review_context(request_id=request_id)
    request = dict(context["request"])
    if str(request.get("inventory_review_status") or "") == INVENTORY_REVIEW_CONFIRMED:
        raise RuntimeError("该申请已经完成库存核实，不能继续修改。")
    material_rows = list(context.get("material_rows") or [])
    active_materials: list[dict[str, str]] = []
    for row in material_rows:
        fields = feishu_fields(row)
        active_materials.append(
            {
                "record_id": feishu_record_id(row),
                "product": feishu_text(fields, "物料品类"),
                "model": feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
                "language": feishu_text(fields, "语种") or NO_LANGUAGE_TEXT,
            }
        )

    form_elements: list[dict[str, object]] = []
    for index, line in enumerate(list(context["lines"])):
        product = str(line.get("product") or "")
        candidates = [item for item in active_materials if item["product"] == product]
        current_material_id = str(line.get("material_record_id") or "")
        if current_material_id and all(item["record_id"] != current_material_id for item in candidates):
            candidates.insert(
                0,
                {
                    "record_id": current_material_id,
                    "product": product,
                    "model": str(line.get("model") or NO_MODEL_TEXT),
                    "language": str(line.get("language") or NO_LANGUAGE_TEXT),
                },
            )
        unique_candidates = list(
            {
                item["record_id"]: item
                for item in candidates
                if str(item.get("record_id") or "")
            }.values()
        )
        form_elements.extend(
            [
                {
                    "tag": "markdown",
                    "content": (
                        f"**{index + 1:02d}. {product}**\n"
                        f"申请数量 {int(line.get('quantity') or 0)}｜品类保持不变"
                    ),
                },
                {
                    "tag": "select_static",
                    "name": f"material_{index}",
                    "required": True,
                    "width": "fill",
                    "placeholder": {"tag": "plain_text", "content": "选择型号 / 语种"},
                    "initial_option": current_material_id,
                    "options": [
                        {
                            "text": {
                                "tag": "plain_text",
                                "content": f"{item['model']} / {item['language']}",
                            },
                            "value": item["record_id"],
                        }
                        for item in unique_candidates
                    ],
                },
            ]
        )
    form_elements.extend(
        [
            {
                "tag": "date_picker",
                "name": "ship_date",
                "required": True,
                "width": "fill",
                "label": {"tag": "plain_text", "content": "申请单发货日期 *"},
                "placeholder": {"tag": "plain_text", "content": "请选择发货日期"},
            },
            {
                "tag": "input",
                "name": "change_note",
                "required": True,
                "input_type": "multiline_text",
                "rows": 2,
                "max_length": 500,
                "width": "fill",
                "label": {"tag": "plain_text", "content": "申请物料更改信息说明"},
                "placeholder": {"tag": "plain_text", "content": "请说明本次修改原因"},
            },
            {
                "tag": "button",
                "name": (
                    f"save_inventory_edit__{request_id}__"
                    f"{int(request.get('inventory_review_version') or 0)}"
                ),
                "text": {"tag": "plain_text", "content": "保存修改"},
                "type": "primary_filled",
                "width": "fill",
                "form_action_type": "submit",
                "confirm": {
                    "title": {"tag": "plain_text", "content": "确认保存修改"},
                    "text": {"tag": "plain_text", "content": "修改将写入后台队列并通知申请人。"},
                },
            },
        ]
    )
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": "营销物料申请库存确认｜编辑"},
        },
        "header": {
            "template": "wathet",
            "title": {"tag": "plain_text", "content": "营销物料申请库存确认"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{request.get('request_no') or '-'}｜仅修改型号和语种",
            },
            "icon": {"tag": "standard_icon", "token": "approve_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "12px",
            "elements": [
                *(
                    [
                        {
                            "tag": "markdown",
                            "content": f"**<font color='red'>保存失败</font>**\n{_feishu_card_plain_text(error_message, max_length=500)}",
                        }
                    ]
                    if error_message
                    else []
                ),
                {
                    "tag": "markdown",
                    "content": "**卡片内编辑**\n品类和申请数量保持不变，只调整型号与语种。",
                },
                {
                    "tag": "form",
                    "name": "request_inventory_edit_form",
                    "vertical_spacing": "12px",
                    "elements": form_elements,
                },
            ],
        },
    }


def request_inventory_card_edit_draft(
    request_id: str,
    expected_version: int,
    operator_open_id: str,
    form_value: dict[str, object],
) -> dict[str, object]:
    context = request_inventory_review_context(request_id=request_id)
    request = dict(context["request"])
    if int(request.get("inventory_review_version") or 0) != expected_version:
        raise RuntimeError("申请已发生修改，请打开最新卡片后重新编辑。")
    material_rows = list(context.get("material_rows") or [])
    desired: list[dict[str, object]] = []
    for index, line in enumerate(list(context["lines"])):
        product = str(line.get("product") or "")
        material_id = str(form_value.get(f"material_{index}") or "").strip()
        model = str(form_value.get(f"model_{index}") or "").strip()
        language = str(form_value.get(f"language_{index}") or "").strip()
        matched = next(
            (
                row
                for row in material_rows
                if feishu_text(feishu_fields(row), "物料品类") == product
                and (
                    (material_id and feishu_record_id(row) == material_id)
                    or (
                        not material_id
                        and (feishu_text(feishu_fields(row), "产品型号") or NO_MODEL_TEXT) == model
                        and (feishu_text(feishu_fields(row), "语种") or NO_LANGUAGE_TEXT) == language
                    )
                )
            ),
            None,
        )
        if matched is None:
            selected_label = f"{model} / {language}" if not material_id else "所选型号 / 语种"
            raise RuntimeError(f"{product} 不存在“{selected_label}”这一可用物料组合，请重新选择。")
        desired.append(
            {
                "line_record_id": str(line.get("record_id") or ""),
                "material_record_id": feishu_record_id(matched),
                "quantity": int(line.get("quantity") or 0),
                "remark": str(line.get("remark") or ""),
            }
        )
    change_note = str(form_value.get("change_note") or "").strip()
    ship_date = str(form_value.get("ship_date") or "").strip()
    if not change_note:
        raise RuntimeError("请填写申请物料更改信息说明。")
    return {
        "request_id": request_id,
        "expected_version": expected_version,
        "operator_open_id": operator_open_id,
        "change_note": change_note,
        "ship_date": ship_date,
        "before_lines": _request_review_line_summary(list(context["lines"])),
        "lines": desired,
    }


def inventory_review_reminder_schedule_options(
    now: datetime | None = None,
) -> list[tuple[str, str, datetime]]:
    base = now or datetime.now()
    offsets = (
        ("tomorrow", "明天上午10:00", 1),
        ("3days", "3天后上午10:00", 3),
        ("1week", "1周后上午10:00", 7),
        ("2weeks", "2周后上午10:00", 14),
        ("1month", "1个月后上午10:00", 30),
        ("2months", "2个月后上午10:00", 60),
    )
    return [
        (
            value,
            label,
            (base + timedelta(days=days)).replace(
                hour=10, minute=0, second=0, microsecond=0
            ),
        )
        for value, label, days in offsets
    ]


def execute_inventory_review_reminder_schedule(
    request_id: str,
    operator_open_id: str,
    schedule_value: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if operator_open_id not in enabled_admin_open_ids():
        raise PermissionError("只有已启用管理员可以调整库存核实时间。")
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法保存库存核实时间。")
    request_row = client.get_record(feishu_table_id(REQUEST_TABLE_NAME), request_id)
    if not request_row:
        raise RuntimeError("申请单不存在或已被删除。")
    request = load_feishu_request_records([request_row])[0]
    if str(request.get("status") or "") != REQUEST_STATUS_PENDING:
        raise RuntimeError("只有待审批申请可以设置库存核实提醒。")
    if str(request.get("inventory_review_status") or "") == INVENTORY_REVIEW_CONFIRMED:
        raise RuntimeError("该申请已经完成库存核实，无需设置提醒。")
    choices = {
        value: scheduled_at
        for value, _label, scheduled_at in inventory_review_reminder_schedule_options(now)
    }
    scheduled_at = choices.get(str(schedule_value or ""))
    if scheduled_at is None:
        raise RuntimeError("请选择有效的库存核实时间。")
    feishu_update_record_fields(
        REQUEST_TABLE_NAME,
        request_id,
        {
            INVENTORY_REVIEW_REMINDER_AT_FIELD: feishu_datetime_value(
                REQUEST_TABLE_NAME, INVENTORY_REVIEW_REMINDER_AT_FIELD, scheduled_at
            ),
            INVENTORY_REVIEW_REMINDER_STATUS_FIELD: INVENTORY_REVIEW_REMINDER_PENDING,
        },
    )
    return {
        "request_id": request_id,
        "request_no": str(request.get("request_no") or ""),
        "scheduled_at": scheduled_at,
    }


def pending_inventory_review_contexts() -> list[dict[str, object]]:
    contexts: list[dict[str, object]] = []
    request_rows = fresh_feishu_rows(REQUEST_TABLE_NAME)
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    all_lines = load_feishu_request_line_records(
        fresh_feishu_rows(REQUEST_LINE_TABLE_NAME),
        material_rows,
        category_rows,
    )
    snapshot_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in request_rows:
        fields = feishu_fields(row)
        if feishu_text(fields, "申请类型") != "普通物料申请":
            continue
        if feishu_text(fields, "审批状态") != REQUEST_STATUS_PENDING:
            continue
        if feishu_text(fields, "库存审查状态") == INVENTORY_REVIEW_CONFIRMED:
            continue
        request_id = feishu_record_id(row)
        if not request_id:
            continue
        request = load_feishu_request_records([row])[0]
        lines = request_lines_for_request(request, all_lines)
        contexts.append(
            {
                "request": request,
                "request_row": row,
                "lines": lines,
                "result": request_inventory_review_result(lines),
                "snapshot_at": snapshot_at,
                "material_rows": material_rows,
                "category_rows": category_rows,
            }
        )
    return contexts


def notify_enabled_admins_of_inventory_review_reminder(
    request_id: str,
    *,
    reason: str = "计划核实时间已到",
    mark_scheduled_reminder: bool = True,
) -> int:
    context = request_inventory_review_context(request_id=request_id)
    request = dict(context["request"])
    if str(request.get("status") or "") != REQUEST_STATUS_PENDING:
        return 0
    if str(request.get("inventory_review_status") or "") == INVENTORY_REVIEW_CONFIRMED:
        return 0
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送库存核实提醒。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    # Keep every live card id for this request.  A reminder is an additional
    # entry point, not a replacement for the original inventory-review card;
    # otherwise the final confirmation can only refresh the latest reminder
    # while earlier administrator cards remain actionable and stale.
    existing_message_ids = [
        str(value)
        for value in list(request.get("inventory_message_ids") or [])
        if str(value).strip()
    ]
    message_ids: list[str] = []
    for open_id in recipients:
        card = material_request_notification_card(
            str(request.get("request_no") or ""),
            request,
            list(context.get("lines") or []),
            review_context=context,
            operator_open_id=open_id,
        )
        card["header"]["title"]["content"] = "营销物料申请库存核实提醒"
        card["header"]["subtitle"] = {
            "tag": "plain_text",
            "content": reason,
        }
        message_ids.append(send_feishu_interactive_message(client, open_id, card))
    updates: dict[str, object] = {
        "库存确认消息ID": json.dumps(
            unique_preserve([*existing_message_ids, *message_ids]),
            ensure_ascii=False,
        ),
        "管理员通知状态": "已发送",
        "管理员通知时间": feishu_datetime_value(
            REQUEST_TABLE_NAME, "管理员通知时间", datetime.now()
        ),
    }
    if mark_scheduled_reminder:
        updates[INVENTORY_REVIEW_REMINDER_STATUS_FIELD] = INVENTORY_REVIEW_REMINDER_SENT
        last_field = first_feishu_field(
            REQUEST_TABLE_NAME,
            list(INVENTORY_REVIEW_LAST_REMINDER_FIELD_CANDIDATES),
        )
        if feishu_has_field(REQUEST_TABLE_NAME, last_field):
            updates[last_field] = feishu_datetime_value(
                REQUEST_TABLE_NAME, last_field, datetime.now()
            )
    feishu_update_record_fields(REQUEST_TABLE_NAME, request_id, updates)
    return len(recipients)


def weekly_inventory_review_digest_card(
    contexts: list[dict[str, object]],
    operator_open_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now()
    sorted_contexts = sorted(
        contexts,
        key=lambda item: str(dict(item.get("request") or {}).get("submitted_at") or ""),
    )
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": f"截至 {current:%Y-%m-%d %H:%M}，共有 **{len(sorted_contexts)}** 条普通物料申请尚未核实库存。",
        }
    ]
    base_url = get_secret_value("LOCAL_APP_URL", DEFAULT_LOCAL_APP_URL).rstrip("/") + "/"
    for context in sorted_contexts[:20]:
        request = dict(context.get("request") or {})
        request_id = str(request.get("record_id") or "")
        planned = str(request.get("inventory_review_reminder_at") or "未设置")
        edit_args = {
            "allocation": "request",
            "request_id": request_id,
            "operator": operator_open_id,
            "review_token": request_review_access_token(request_id, operator_open_id),
        }
        edit_url = f"{base_url}?{url_parse.urlencode(edit_args)}"
        elements.extend(
            [
                {
                    "tag": "markdown",
                    "content": (
                        f"**{request.get('request_no') or '-'}**｜{request.get('requester') or '-'}｜"
                        f"提交 {request.get('submitted_at') or '-'}｜计划核实 {planned}"
                    ),
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看并调整配货方案"},
                    "type": "default",
                    "behaviors": [
                        {
                            "type": "open_url",
                            "default_url": edit_url,
                            "pc_url": edit_url,
                            "ios_url": edit_url,
                            "android_url": edit_url,
                        }
                    ],
                },
            ]
        )
    if len(sorted_contexts) > 20:
        elements.append(
            {
                "tag": "markdown",
                "content": f"另有 {len(sorted_contexts) - 20} 条未展示，请进入系统查看。",
            }
        )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text", "content": "营销物料申请待核实库存提醒"},
            "icon": {"tag": "standard_icon", "token": "approve_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "10px",
            "elements": elements,
        },
    }


def notify_weekly_pending_inventory_reviews(*, now: datetime | None = None) -> int:
    contexts = pending_inventory_review_contexts()
    if not contexts:
        return 0
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送每周库存核实汇总。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    for open_id in recipients:
        send_feishu_interactive_message(
            client,
            open_id,
            weekly_inventory_review_digest_card(contexts, open_id, now=now),
        )
    return len(recipients)


def enqueue_inventory_review_scheduled_tasks(now: datetime | None = None) -> int:
    current = now or datetime.now()
    created = 0
    request_rows = fresh_feishu_rows(REQUEST_TABLE_NAME)
    for row in request_rows:
        fields = feishu_fields(row)
        if feishu_text(fields, "申请类型") != "普通物料申请":
            continue
        if feishu_text(fields, "审批状态") != REQUEST_STATUS_PENDING:
            continue
        if feishu_text(fields, "库存审查状态") == INVENTORY_REVIEW_CONFIRMED:
            continue
        if feishu_text(fields, INVENTORY_REVIEW_REMINDER_STATUS_FIELD) != INVENTORY_REVIEW_REMINDER_PENDING:
            continue
        scheduled_ms = feishu_int(fields, INVENTORY_REVIEW_REMINDER_AT_FIELD)
        if scheduled_ms <= 0 or scheduled_ms > int(current.timestamp() * 1000):
            continue
        request_id = feishu_record_id(row)
        _task, is_new = enqueue_feishu_background_write(
            QUEUE_TASK_TYPE_INVENTORY_REVIEW_REMINDER,
            {"request_id": request_id, "scheduled_at_ms": scheduled_ms},
            idempotency_key=f"inventory-review-reminder:{request_id}:{scheduled_ms}",
        )
        created += int(is_new)
    monday = (current - timedelta(days=current.weekday())).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    if current.weekday() == 0 and current >= monday:
        iso_year, iso_week, _ = current.isocalendar()
        _task, is_new = enqueue_feishu_background_write(
            QUEUE_TASK_TYPE_WEEKLY_INVENTORY_REVIEW,
            {"iso_year": iso_year, "iso_week": iso_week},
            idempotency_key=f"weekly-inventory-review:{iso_year}-W{iso_week:02d}",
        )
        created += int(is_new)
    return created


def _send_feishu_message_compat(
    client: object,
    receive_id: str,
    message_type: str,
    content: dict[str, object],
    *,
    receive_id_type: str = "open_id",
) -> str:
    normalized_receive_id = str(receive_id or "").strip()
    if not normalized_receive_id:
        raise FeishuBitableError("Feishu message receive_id cannot be empty.")

    method_name = (
        "send_interactive_message"
        if message_type == "interactive"
        else "send_text_message"
    )
    sender = getattr(client, method_name, None)
    if callable(sender):
        payload = content if message_type == "interactive" else str(content.get("text") or "")
        if receive_id_type == "open_id":
            return sender(normalized_receive_id, payload)
        return sender(normalized_receive_id, payload, receive_id_type=receive_id_type)

    request_method = getattr(client, "_request", None)
    if not callable(request_method):
        raise FeishuBitableError(f"Feishu client cannot send {message_type} messages.")
    response = request_method(
        "POST",
        "/im/v1/messages",
        params={"receive_id_type": receive_id_type},
        payload={
            "receive_id": normalized_receive_id,
            "msg_type": message_type,
            "content": json.dumps(content, ensure_ascii=False),
        },
    )
    message_id = str(response.get("data", {}).get("message_id", "")).strip()
    if not message_id:
        raise FeishuBitableError("Feishu did not return a message_id.")
    return message_id


def send_feishu_interactive_message(
    client: object,
    receive_id: str,
    card: dict[str, object],
) -> str:
    if not card:
        raise FeishuBitableError("Feishu interactive card cannot be empty.")
    safe_card = _feishu_normalize_card_tables(card)
    return _send_feishu_message_compat(
        client,
        receive_id,
        "interactive",
        safe_card,
    )


def send_feishu_text_message(client: object, receive_id: str, text: str) -> str:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        raise FeishuBitableError("Feishu message text cannot be empty.")
    return _send_feishu_message_compat(
        client,
        receive_id,
        "text",
        {"text": normalized_text},
    )


def notify_requester_of_inventory_edit(
    request: dict[str, object],
    before_lines: list[dict[str, object]],
    after_lines: list[dict[str, object]],
    change_note: str,
) -> int:
    requester_open_id = str(request.get("requester_open_id") or "").strip()
    if not requester_open_id:
        raise RuntimeError("申请单未记录申请人 OpenID，无法发送物料变更通知。")
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送申请变更通知。")

    english = requester_prefers_english(request)
    admin_open_ids = enabled_admin_open_ids()
    admin_mentions = " ".join(
        f"<at id={open_id}></at>" for open_id in admin_open_ids
    )
    contact_text = (
        "If you have any questions or other requests, please contact "
        if english
        else "如有疑问或其他需求，请联系"
    )
    if admin_mentions:
        contact_text += admin_mentions
    else:
        contact_text += "the material administrator." if english else "物料管理员。"

    title = (
        "Marketing material request updated"
        if english
        else "营销物料申请已调整"
    )
    card = {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": title},
        },
        "header": {
            "template": "green",
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {
                "tag": "plain_text",
                "content": str(request.get("request_no") or "-"),
            },
            "icon": {"tag": "standard_icon", "token": "notice_colorful"},
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {
                        "tag": "plain_text",
                        "content": "Inventory verified" if english else INVENTORY_REVIEW_CONFIRMED,
                    },
                    "color": "green",
                }
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "12px",
            "elements": [
                # Feishu Card JSON 2.0 does not allow a table to be nested in
                # a column/column_set.  Keep material tables as direct body
                # children so requester/admin notifications remain valid.
                {
                    "tag": "markdown",
                    "content": (
                        "**<font color='grey'>Before change</font>**"
                        if english
                        else "**<font color='grey'>修改前</font>**"
                    ),
                },
                _feishu_requester_material_table(before_lines, english=english),
                {
                    "tag": "markdown",
                    "content": (
                        "**<font color='green'>After change</font>**"
                        if english
                        else "**<font color='green'>修改后</font>**"
                    ),
                    "text_size": "heading-4",
                },
                _feishu_requester_material_table(after_lines, english=english),
                _feishu_notification_section(
                    "Change explanation" if english else "申请物料更改信息说明",
                    [_feishu_card_text_element(change_note, lines=6)],
                    color="orange",
                ),
                {
                    "tag": "markdown",
                    "content": contact_text,
                },
            ],
        },
    }
    recipients = unique_preserve([requester_open_id, *admin_open_ids])
    for open_id in recipients:
        send_feishu_interactive_message(client, open_id, card)
    return len(recipients)


def notify_enabled_admins_of_material_request(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> int:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送机器人提醒。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    try:
        review_context = request_inventory_review_context(request_no=request_no)
    except Exception:
        review_context = None
    existing_message_ids = (
        [str(value) for value in list(dict(review_context.get("request") or {}).get("inventory_message_ids") or [])]
        if review_context
        else []
    )
    message_ids: list[str] = []
    update_message = getattr(client, "update_interactive_message", None)
    if existing_message_ids and callable(update_message):
        # A request can have an original card plus one or more reminder cards.
        # Refresh every stored message instead of only the first card for each
        # current administrator.  Notification batches are written in the same
        # recipient order, so modulo restores the recipient-specific signed
        # action link for historical batches as well.
        recipients_with_live_card: set[str] = set()
        for index, message_id in enumerate(existing_message_ids):
            operator_open_id = recipients[index % len(recipients)]
            card = material_request_notification_card(
                request_no,
                request_payload,
                lines,
                review_context=review_context,
                operator_open_id=operator_open_id,
            )
            try:
                if not message_id:
                    raise LookupError("missing historical message id")
                update_message(message_id, card)
                message_ids.append(message_id)
                recipients_with_live_card.add(operator_open_id)
            except Exception as exc:
                # Feishu only allows interactive messages to be updated for 14
                # days.  Drop an expired historical card here and create at
                # most one replacement per current recipient below.  Preserve
                # fail-closed behavior for every other update error so the
                # background task can retry the card refresh independently of
                # the already committed business write.
                if "230031" not in str(exc) and not isinstance(exc, LookupError):
                    raise
        for operator_open_id in recipients:
            if operator_open_id in recipients_with_live_card:
                continue
            card = material_request_notification_card(
                request_no,
                request_payload,
                lines,
                review_context=review_context,
                operator_open_id=operator_open_id,
            )
            message_ids.append(
                send_feishu_interactive_message(client, operator_open_id, card)
            )
    else:
        for open_id in recipients:
            card = material_request_notification_card(
                request_no,
                request_payload,
                lines,
                review_context=review_context,
                operator_open_id=open_id,
            )
            message_ids.append(send_feishu_interactive_message(client, open_id, card))
    if review_context:
        request = dict(review_context.get("request") or {})
        request_id = str(request.get("record_id") or "")
        if request_id:
            feishu_update_record_fields(
                REQUEST_TABLE_NAME,
                request_id,
                {
                    "库存确认消息ID": json.dumps(message_ids, ensure_ascii=False),
                    "管理员通知状态": "已发送",
                    "管理员通知时间": feishu_datetime_value(
                        REQUEST_TABLE_NAME, "管理员通知时间", datetime.now()
                    ),
                },
            )
    return len(recipients)


def material_restock_notification_card(
    draft: dict[str, object],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    total_quantity = sum(int(line.get("quantity") or 0) for line in lines)
    operation_label = "减库" if str(draft.get("mode") or "restock") == "reduce" else "补库"

    def short_field(label: str, value: object) -> dict[str, object]:
        return {
            "is_short": True,
            "text": {
                "tag": "plain_text",
                "content": f"{label}\n{_feishu_card_plain_text(value, max_length=500)}",
            },
        }

    elements: list[dict[str, object]] = [
        {"tag": "markdown", "content": f"**{operation_label}信息**"},
        {
            "tag": "div",
            "fields": [
                short_field(f"{operation_label}单号", draft.get("restock_no")),
                short_field("操作人", draft.get("operator")),
                short_field("采购/业务单号", draft.get("purchase_order_no") or "-"),
                short_field(f"{operation_label}合计", f"{len(lines)} 种，共 {total_quantity} 件"),
            ],
        },
    ]
    note = str(draft.get("note") or "").strip()
    if note:
        elements.extend(
            [
                {"tag": "markdown", "content": f"**{operation_label}说明**"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": _feishu_card_plain_text(note),
                    },
                },
            ]
        )
    elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": f"**{operation_label}明细**"}])
    rows: list[dict[str, object]] = []
    for index, line in enumerate(lines, start=1):
        specification = (
            f"{_feishu_card_plain_text(line.get('product'), max_length=300)} / "
            f"{_feishu_card_plain_text(request_model_display_label(line.get('model'), language=LANGUAGE_ZH), max_length=200)} / "
            f"{_feishu_card_plain_text(line.get('language') or NO_LANGUAGE_TEXT, max_length=200)}"
        )
        remark = str(line.get("remark") or "").strip()
        rows.append(
            {
                "sequence": index,
                "specification": specification,
                "quantity": int(line.get("quantity") or 0),
                "inventory_change": (
                    f"{int(line.get('before_quantity') or 0)} → "
                    f"{int(line.get('after_quantity') or 0)}"
                ),
                "remark": _feishu_card_plain_text(remark, max_length=500) or "-",
            }
        )
    elements.append(
        _feishu_notification_table(
            [
                {"name": "sequence", "display_name": "序号", "data_type": "number", "width": "80px", "horizontal_align": "center"},
                {"name": "specification", "display_name": "物料 / 型号 / 语种", "data_type": "text"},
                {"name": "quantity", "display_name": operation_label + "数", "data_type": "number", "width": "86px", "horizontal_align": "right"},
                {"name": "inventory_change", "display_name": "库存变化", "data_type": "text", "width": "120px"},
                {"name": "remark", "display_name": "备注", "data_type": "text", "width": "160px"},
            ],
            rows,
        )
    )
    title = f"物料编辑通知｜{operation_label}已完成"
    return _feishu_notification_card_v2(
        title,
        "red" if operation_label == "减库" else "green",
        elements,
    )


def notify_enabled_admins_of_restock(
    draft: dict[str, object],
    lines: list[dict[str, object]],
) -> int:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送补库通知。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    card = material_restock_notification_card(draft, lines)
    return send_category_notification_to_available_admins(client, recipients, card)


def approval_writeback_notification_card(
    request_no: str,
    instance_code: str,
    lines: list[dict[str, object]],
    *,
    succeeded: bool,
) -> dict[str, object]:
    issued_lines = [
        line for line in lines if str(line.get("status") or "") == "已发放"
    ]
    pending_lines = [line for line in lines if line not in issued_lines]
    total_quantity = sum(int(line.get("actual_issue_qty") or 0) for line in issued_lines)
    outcome_text = "已完成" if succeeded else "发生异常，需要检查"
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": (
                f"**申请单号：** {request_no}\n"
                f"**审批回写：** {outcome_text}\n"
                f"**库存变更：** 已完成 {len(issued_lines)} 条、待处理 {len(pending_lines)} 条；"
                f"当前已发放 {total_quantity} 件"
            ),
        },
        {"tag": "hr"},
        {"tag": "markdown", "content": "**物料及库存变更结果**"},
    ]
    displayed_lines = issued_lines if succeeded else lines
    rows: list[dict[str, object]] = []
    for index, line in enumerate(displayed_lines[:40], start=1):
        rows.append(
            {
                "sequence": index,
                "specification": (
                    f"{line.get('actual_product') or line.get('product') or '-'} / "
                    f"{line.get('actual_model') or line.get('model') or NO_MODEL_TEXT} / "
                    f"{line.get('actual_language') or line.get('language') or NO_LANGUAGE_TEXT}"
                ),
                "issued_quantity": int(line.get("actual_issue_qty") or 0),
                "status": str(line.get("status") or "-"),
                "current_stock": int(line.get("current_stock") or 0),
            }
        )
    elements.append(
        _feishu_notification_table(
            [
                {"name": "sequence", "display_name": "序号", "data_type": "number", "width": "80px", "horizontal_align": "center"},
                {"name": "specification", "display_name": "物料 / 型号 / 语种", "data_type": "text"},
                {"name": "issued_quantity", "display_name": "实际发放", "data_type": "number", "width": "96px", "horizontal_align": "right"},
                {"name": "status", "display_name": "状态", "data_type": "text", "width": "100px"},
                {"name": "current_stock", "display_name": "当前库存", "data_type": "number", "width": "96px", "horizontal_align": "right"},
            ],
            rows,
        )
    )
    if len(displayed_lines) > 40:
        elements.append(
            {"tag": "markdown", "content": f"另有 **{len(displayed_lines) - 40}** 条，请在物料系统中查看。"}
        )
    if not succeeded:
        elements.append(
            {
                "tag": "markdown",
                "content": "**请勿直接整单重跑。** 部分库存可能已经扣减，请先核对库存流水和未发放明细。",
            }
        )
    elements.append(
        {"tag": "div", "text": {"tag": "plain_text", "content": f"审批实例：{instance_code}"}}
    )
    title = "营销物料申请回写完成" if succeeded else "营销物料申请回写异常"
    return _feishu_notification_card_v2(
        title,
        "green" if succeeded else "red",
        elements,
    )


def notify_enabled_admins_of_approval_writeback(
    request_no: str,
    instance_code: str,
    *,
    succeeded: bool,
) -> int:
    if not request_no or not instance_code:
        raise RuntimeError("审批回写通知缺少申请单号或审批实例编号。")
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送审批回写通知。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    context = request_inventory_review_context(request_no=request_no)
    request = dict(context["request"])
    lines = [dict(line) for line in list(context["lines"])]
    is_complete = str(request.get("status") or "") == "已发放" and bool(lines) and all(
        str(line.get("status") or "") == "已发放" for line in lines
    )
    if succeeded != is_complete:
        raise RuntimeError(f"申请单 {request_no} 的回写完成状态已变化，请重新检查后发送通知。")
    card = approval_writeback_notification_card(
        request_no,
        instance_code,
        lines,
        succeeded=succeeded,
    )
    return send_category_notification_to_available_admins(client, recipients, card)


def approval_writeback_is_complete(request_no: str) -> bool:
    context = request_inventory_review_context(request_no=request_no)
    request = dict(context["request"])
    lines = [dict(line) for line in list(context["lines"])]
    return str(request.get("status") or "") == "已发放" and bool(lines) and all(
        str(line.get("status") or "") == "已发放" for line in lines
    )


def cleanup_custom_materials_for_request(request_no: str) -> int:
    """Delete request-scoped custom master rows after a complete writeback."""
    context = request_inventory_review_context(request_no=request_no)
    request = dict(context["request"])
    lines = [dict(line) for line in list(context["lines"])]
    if str(request.get("status") or "") != "已发放" or not lines or any(
        str(line.get("status") or "") != "已发放" for line in lines
    ):
        raise RuntimeError(f"申请单 {request_no} 尚未完整发放，不能清理自定义物料。")
    request_row = dict(context["request_row"])
    request_fields = feishu_fields(request_row)
    if feishu_text(request_fields, "临时物料清理状态") == "已清理":
        return 0
    linked_material_ids = {
        str(line.get("material_record_id") or "") for line in lines
        if str(line.get("material_record_id") or "")
    }
    delete_ids: list[str] = []
    for row in list(context["material_rows"]):
        record_id = feishu_record_id(row)
        if record_id not in linked_material_ids:
            continue
        fields = feishu_fields(row)
        temporary_value = fields.get("是否临时物料")
        is_temporary = temporary_value is True or str(temporary_value or "").strip().lower() in {
            "true", "1", "是", "yes",
        }
        if is_temporary and feishu_text(fields, "备注").startswith("自定义物料申请:"):
            delete_ids.append(record_id)
    deleted = feishu_batch_delete_record_ids(MATERIAL_TABLE_NAME, delete_ids)
    feishu_update_record_fields(
        REQUEST_TABLE_NAME,
        feishu_record_id(request_row),
        {"临时物料清理状态": "已清理"},
    )
    return deleted


def dimension_management_notification_card(
    draft: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    kind = str(draft.get("kind") or "")
    label = {"model": "型号", "language": "语种", "region": "战区"}.get(kind, "基础维度")
    operation = str(draft.get("operation") or "")
    operation_label = {"create": "新增", "edit": "编辑", "delete": "删除"}.get(operation, operation)
    changes = [dict(item) for item in list(draft.get("changes") or []) if isinstance(item, dict)]
    elements: list[dict[str, object]] = [{
        "tag": "markdown",
        "content": (
            f"**操作：** {operation_label}{label}\n"
            f"**{label}名称：** {_feishu_card_plain_text(draft.get('old_name')) or '-'}"
            f" → {_feishu_card_plain_text(draft.get('name'))}\n"
            f"**启用状态：** {_feishu_card_plain_text(draft.get('old_status')) or '-'}"
            f" → {_feishu_card_plain_text(draft.get('status'))}\n"
            f"**执行结果：** 新增物料 {int(result.get('created_material_count') or 0)} 条，"
            f"修改物料 {int(result.get('updated_material_count') or 0)} 条，"
            f"删除物料 {int(result.get('deleted_material_count') or 0)} 条"
        ),
    }]
    if kind == "model" and operation != "delete":
        elements.append({"tag": "markdown", "content": (
            f"**产品线：** {_feishu_card_plain_text(draft.get('old_product_line')) or '-'}"
            f" → {_feishu_card_plain_text(draft.get('product_line')) or '-'}\n"
            f"**中文页面名称：** {_feishu_card_plain_text(draft.get('old_zh_page_name')) or '-'}"
            f" → {_feishu_card_plain_text(draft.get('zh_page_name'))}\n"
            f"**英文页面名称：** {_feishu_card_plain_text(draft.get('old_en_page_name')) or '-'}"
            f" → {_feishu_card_plain_text(draft.get('en_page_name'))}"
        )})
    elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": "**关联物料变更明细**"}])
    rows = dimension_change_dataframe(changes).to_dict("records") if changes else []
    table_rows = [
        {
            "sequence": index,
            "operation": str(row.get("操作") or "-"),
            "material_code": str(row.get("物料编码") or "-"),
            "specification": (
                f"{row.get('物料品类') or '-'} / {row.get('产品型号') or '-'} / "
                f"{row.get('战区') if kind == 'region' else row.get('语种')}"
            ),
            "quantity": int(row.get("库存数量") or 0),
            "status": str(row.get("启用状态") or "-"),
            "request_visible": str(row.get("申领页显示") or "-"),
        }
        for index, row in enumerate(rows[:40], start=1)
    ]
    elements.append(
        _feishu_notification_table(
            [
                {"name": "sequence", "display_name": "序号", "data_type": "number", "width": "80px", "horizontal_align": "center"},
                {"name": "operation", "display_name": "操作", "data_type": "text", "width": "84px"},
                {"name": "material_code", "display_name": "物料编码", "data_type": "text", "width": "130px"},
                {"name": "specification", "display_name": "品类 / 型号 / 语种或战区", "data_type": "text"},
                {"name": "quantity", "display_name": "库存", "data_type": "number", "width": "80px", "horizontal_align": "right"},
                {"name": "status", "display_name": "状态", "data_type": "text", "width": "80px"},
                {"name": "request_visible", "display_name": "申领页", "data_type": "text", "width": "90px"},
            ],
            table_rows,
        )
    )
    if len(rows) > 40:
        elements.append({"tag": "markdown", "content": f"另有 **{len(rows) - 40}** 条变更，请在物料管理中查看。"})
    return _feishu_notification_card_v2(
        f"物料编辑通知｜{label}管理已完成",
        "blue",
        elements,
    )


def notify_enabled_admins_of_dimension_management(
    draft: dict[str, object], result: dict[str, object]
) -> int:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送基础维度管理通知。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    return send_category_notification_to_available_admins(
        client,
        recipients,
        dimension_management_notification_card(draft, result),
    )


def category_edit_change_rows(draft: dict[str, object]) -> list[dict[str, object]]:
    """Return human-readable before/after rows for category edit review and cards."""
    current_by_key = {
        (str(row.get("model") or NO_MODEL_TEXT), str(row.get("language") or NO_LANGUAGE_TEXT)): row
        for row in list(draft.get("current_records") or [])
        if isinstance(row, dict)
    }
    rows: list[dict[str, object]] = []
    for target in list(draft.get("targets") or []):
        if not isinstance(target, dict):
            continue
        key = (str(target.get("model") or NO_MODEL_TEXT), str(target.get("language") or NO_LANGUAGE_TEXT))
        before = current_by_key.get(key)
        before_quantity = int(before.get("quantity") or 0) if before else 0
        after_quantity = int(target.get("quantity") or 0)
        before_unit_price = float(before.get("unit_price") or 0) if before else 0.0
        after_unit_price = float(target.get("unit_price") or 0)
        before_customs_code = str(before.get("customs_code") or "") if before else ""
        after_customs_code = str(target.get("customs_code") or "")
        before_status = normalize_enabled_status(before.get("status")) if before else "-"
        after_status = normalize_enabled_status(target.get("status"))
        before_request_visible = (
            normalize_request_page_visibility(before.get("request_visible"))
            if before
            else "-"
        )
        after_request_visible = normalize_request_page_visibility(
            target.get("request_visible")
        )
        action = "新增" if before is None else ("修改" if (
            before_quantity != after_quantity
            or before_unit_price != after_unit_price
            or before_customs_code != after_customs_code
            or before_status != after_status
            or before_request_visible != after_request_visible
        ) else "保留")
        rows.append({
            "操作": action,
            "产品型号": key[0],
            "语种": key[1],
            "库存变化": (
                f"新增 {after_quantity}" if before is None
                else f"{before_quantity} → {after_quantity}" if before_quantity != after_quantity
                else "—"
            ),
            "单价变化": (
                f"新增 {after_unit_price:g}" if before is None
                else f"{before_unit_price:g} → {after_unit_price:g}" if before_unit_price != after_unit_price
                else "—"
            ),
            "状态变化": (
                f"新增 {after_status}" if before is None
                else f"{before_status} → {after_status}" if before_status != after_status
                else "—"
            ),
            "申领页显示变化": (
                f"新增 {after_request_visible}" if before is None
                else f"{before_request_visible} → {after_request_visible}"
                if before_request_visible != after_request_visible else "—"
            ),
            "海关编码变化": (
                f"新增 {after_customs_code or '-'}" if before is None
                else f"{before_customs_code or '-'} → {after_customs_code or '-'}"
                if before_customs_code != after_customs_code else "—"
            ),
        })
    target_keys = {
        (str(target.get("model") or NO_MODEL_TEXT), str(target.get("language") or NO_LANGUAGE_TEXT))
        for target in list(draft.get("targets") or []) if isinstance(target, dict)
    }
    for key, before in current_by_key.items():
        if key not in target_keys:
            rows.append({
                "操作": "移除/迁移", "产品型号": key[0], "语种": key[1],
                "库存变化": f"{int(before.get('quantity') or 0)} → 0", "单价变化": "-",
                "状态变化": f"{normalize_enabled_status(before.get('status'))} → 移除",
                "申领页显示变化": (
                    f"{normalize_request_page_visibility(before.get('request_visible'))} → 移除"
                ),
                "海关编码变化": "-",
            })
    return rows


def category_edit_notification_card(
    draft: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    rows = category_edit_change_rows(draft)
    changed_rows = [row for row in rows if row["操作"] != "保留"]
    base_changes = [
        ("物料品类名称", draft.get("old_product"), draft.get("product")),
        ("中文页面名称", draft.get("old_category_zh_page_name"), draft.get("category_zh_page_name")),
        ("英文页面名称", draft.get("old_category_en_page_name"), draft.get("category_en_page_name")),
        ("品类定义", draft.get("old_category_definition"), draft.get("category_definition")),
        ("品类启用状态", draft.get("old_category_status"), draft.get("category_status")),
        ("品类在申领页显示", draft.get("old_category_request_visible"), draft.get("category_request_visible")),
        ("商业发票产品名称", draft.get("old_commercial_invoice_name"), draft.get("commercial_invoice_name")),
        ("装箱单产品类型", draft.get("old_packing_list_product_type"), draft.get("packing_list_product_type")),
        ("单价（美元）", draft.get("old_category_unit_price"), draft.get("category_unit_price")),
        ("海关编码", draft.get("old_category_customs_code"), draft.get("category_customs_code")),
    ]
    changed_base_fields = [
        (label, before, after)
        for label, before, after in base_changes
        if str(before or "").strip() != str(after or "").strip()
    ]
    elements: list[dict[str, object]] = [{
        "tag": "markdown",
        "content": (
            f"**品类：** {_feishu_card_plain_text(draft.get('old_product'))} → "
            f"{_feishu_card_plain_text(draft.get('product'))}\n"
            f"**修改时间：** {_feishu_card_plain_text(draft.get('edited_at'))}\n"
            f"**品类启用状态：** {_feishu_card_plain_text(draft.get('category_status'))}\n"
            f"**品类在申领页显示：** {_feishu_card_plain_text(draft.get('category_request_visible'))}\n"
            f"**商业发票产品名称：** {_feishu_card_plain_text(draft.get('commercial_invoice_name'))}\n"
            f"**装箱单产品类型：** {_feishu_card_plain_text(draft.get('packing_list_product_type'))}\n"
            f"**结果：** 目标组合 {int(result.get('target_count') or 0)} 条，"
            f"新增 {int(result.get('created_count') or 0)} 条，移除 {int(result.get('deleted_count') or 0)} 条，"
            f"库存差额 {int(result.get('quantity_difference') or 0):+,}"
        ),
    }, {"tag": "hr"}, {"tag": "markdown", "content": "**品类基础信息变更**"}]
    for label, before, after in changed_base_fields:
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": (
            f"{label}：{_feishu_card_plain_text(before) or '-'} → "
            f"{_feishu_card_plain_text(after) or '-'}"
        )}})
    if not changed_base_fields:
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": "品类基础信息无变化。"}})
    elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": "**物料主数据变更明细**"}])
    table_rows = [
        {
            "sequence": index,
            "operation": str(row["操作"]),
            "specification": f"{row['产品型号']} / {row['语种']}",
            "inventory_change": str(row["库存变化"]),
            "unit_price_change": str(row["单价变化"]),
            "status_change": str(row["状态变化"]),
            "visibility_change": str(row["申领页显示变化"]),
            "customs_change": str(row["海关编码变化"]),
        }
        for index, row in enumerate(changed_rows[:40], start=1)
    ]
    elements.append(
        _feishu_notification_table(
            [
                {"name": "sequence", "display_name": "序号", "data_type": "number", "width": "80px", "horizontal_align": "center"},
                {"name": "operation", "display_name": "操作", "data_type": "text", "width": "90px"},
                {"name": "specification", "display_name": "型号 / 语种", "data_type": "text"},
                {"name": "inventory_change", "display_name": "库存变化", "data_type": "text", "width": "120px"},
                {"name": "unit_price_change", "display_name": "单价变化", "data_type": "text", "width": "120px"},
                {"name": "status_change", "display_name": "状态变化", "data_type": "text", "width": "120px"},
                {"name": "visibility_change", "display_name": "申领页显示", "data_type": "text", "width": "130px"},
                {"name": "customs_change", "display_name": "海关编码", "data_type": "text", "width": "150px"},
            ],
            table_rows,
        )
    )
    if len(changed_rows) > 40:
        elements.append({"tag": "markdown", "content": f"另有 **{len(changed_rows) - 40}** 条修改，请在品类管理中查看。"})
    return _feishu_notification_card_v2(
        "物料编辑通知｜品类修改已完成",
        "blue",
        elements,
    )


def is_feishu_recipient_unavailable_error(exc: Exception) -> bool:
    compact_message = re.sub(r"\s+", "", str(exc))
    return (
        '"code":230013' in compact_message
        or "FeishuAPI230013:" in compact_message
    )


def send_category_notification_to_available_admins(
    client: object,
    recipients: list[str],
    card: dict[str, object],
) -> int:
    sent_count = 0
    for open_id in recipients:
        try:
            send_feishu_interactive_message(client, open_id, card)
        except FeishuBitableError as exc:
            if is_feishu_recipient_unavailable_error(exc):
                continue
            raise
        sent_count += 1
    return sent_count


def notify_enabled_admins_of_category_edit(
    draft: dict[str, object], result: dict[str, object]
) -> int:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送品类编辑通知。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    card = category_edit_notification_card(draft, result)
    return send_category_notification_to_available_admins(client, recipients, card)


def category_create_notification_card(
    draft: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    targets = [
        target
        for target in list(result.get("targets") or draft.get("targets") or [])
        if isinstance(target, dict)
    ]
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": (
                f"**物料品类：** {_feishu_card_plain_text(draft.get('product'))}\n"
                f"**中文页面名称：** {_feishu_card_plain_text(draft.get('category_zh_page_name'))}\n"
                f"**英文页面名称：** {_feishu_card_plain_text(draft.get('category_en_page_name'))}\n"
                f"**品类定义：** {_feishu_card_plain_text(draft.get('category_definition'))}\n"
                f"**创建时间：** {_feishu_card_plain_text(draft.get('created_at'))}\n"
                f"**品类状态：** {_feishu_card_plain_text(draft.get('category_status'))}\n"
                f"**品类在申领页显示：** {_feishu_card_plain_text(draft.get('category_request_visible'))}\n"
                f"**商业发票产品名称：** {_feishu_card_plain_text(draft.get('commercial_invoice_name'))}\n"
                f"**装箱单产品类型：** {_feishu_card_plain_text(draft.get('packing_list_product_type'))}\n"
                f"**创建结果：** 库存组合 {int(result.get('target_count') or 0)} 条，"
                f"型号 {len(list(result.get('models') or []))} 个，"
                f"语种 {len(list(result.get('languages') or []))} 个，"
                f"初始库存 {int(result.get('target_quantity') or 0):,} 件"
            ),
        },
        {"tag": "hr"},
        {"tag": "markdown", "content": "**新增库存组合明细**"},
    ]
    table_rows = [
        {
            "sequence": index,
            "specification": (
                f"{_feishu_card_plain_text(target.get('model') or NO_MODEL_TEXT)} / "
                f"{_feishu_card_plain_text(target.get('language') or NO_LANGUAGE_TEXT)}"
            ),
            "quantity": int(target.get("quantity") or 0),
            "unit_price": float(target.get("unit_price") or 0),
            "status": _feishu_card_plain_text(target.get("status")),
            "request_visible": _feishu_card_plain_text(
                normalize_request_page_visibility(target.get("request_visible"))
            ),
            "customs_code": _feishu_card_plain_text(target.get("customs_code")) or "-",
        }
        for index, target in enumerate(targets[:40], start=1)
    ]
    elements.append(
        _feishu_notification_table(
            [
                {"name": "sequence", "display_name": "序号", "data_type": "number", "width": "80px", "horizontal_align": "center"},
                {"name": "specification", "display_name": "型号 / 语种", "data_type": "text"},
                {"name": "quantity", "display_name": "初始库存", "data_type": "number", "width": "100px", "horizontal_align": "right"},
                {"name": "unit_price", "display_name": "单价", "data_type": "number", "width": "84px", "horizontal_align": "right"},
                {"name": "status", "display_name": "状态", "data_type": "text", "width": "84px"},
                {"name": "request_visible", "display_name": "申领页", "data_type": "text", "width": "90px"},
                {"name": "customs_code", "display_name": "海关编码", "data_type": "text", "width": "150px"},
            ],
            table_rows,
        )
    )
    if len(targets) > 40:
        elements.append({
            "tag": "markdown",
            "content": f"另有 **{len(targets) - 40}** 条新增组合，请在品类管理中查看。",
        })
    return _feishu_notification_card_v2(
        "物料编辑通知｜新物料品类已创建",
        "green",
        elements,
    )


def notify_enabled_admins_of_category_create(
    draft: dict[str, object], result: dict[str, object]
) -> int:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送新增品类通知。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    card = category_create_notification_card(draft, result)
    return send_category_notification_to_available_admins(client, recipients, card)


def category_delete_notification_card(draft: dict[str, object]) -> dict[str, object]:
    rows = [
        dict(row)
        for row in list(draft.get("records") or [])
        if isinstance(row, dict)
    ]
    category_names = unique_preserve(
        [str(value) for value in list(draft.get("category_names") or []) if str(value)]
    )
    delete_kind = str(draft.get("delete_kind") or "material_rows")
    action_label = "删除整品类" if delete_kind == "categories" else "删除物料行"
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": (
                f"**操作：** {action_label}\n"
                f"**删除时间：** {_feishu_card_plain_text(draft.get('deleted_at'))}\n"
                f"**涉及品类：** {_feishu_card_plain_text('、'.join(category_names) or '-')}\n"
                f"**删除结果：** 品类 {len(category_names) if delete_kind == 'categories' else 0} 个，"
                f"物料行 {len(rows)} 条"
            ),
        },
        {"tag": "hr"},
        {"tag": "markdown", "content": "**删除明细**"},
    ]
    table_rows = [
        {
            "sequence": index,
            "material_code": _feishu_card_plain_text(row.get("material_code") or "-"),
            "specification": (
                f"{_feishu_card_plain_text(row.get('category'))} / "
                f"{_feishu_card_plain_text(row.get('model') or NO_MODEL_TEXT)} / "
                f"{_feishu_card_plain_text(row.get('language') or NO_LANGUAGE_TEXT)}"
            ),
            "quantity": int(row.get("quantity") or 0),
            "status": _feishu_card_plain_text(normalize_enabled_status(row.get("status"))),
            "request_visible": _feishu_card_plain_text(
                normalize_request_page_visibility(row.get("request_visible"))
            ),
        }
        for index, row in enumerate(rows[:40], start=1)
    ]
    elements.append(
        _feishu_notification_table(
            [
                {"name": "sequence", "display_name": "序号", "data_type": "number", "width": "80px", "horizontal_align": "center"},
                {"name": "material_code", "display_name": "物料编码", "data_type": "text", "width": "130px"},
                {"name": "specification", "display_name": "品类 / 型号 / 语种", "data_type": "text"},
                {"name": "quantity", "display_name": "库存", "data_type": "number", "width": "80px", "horizontal_align": "right"},
                {"name": "status", "display_name": "状态", "data_type": "text", "width": "84px"},
                {"name": "request_visible", "display_name": "申领页", "data_type": "text", "width": "90px"},
            ],
            table_rows,
        )
    )
    if len(rows) > 40:
        elements.append(
            {"tag": "markdown", "content": f"另有 **{len(rows) - 40}** 条删除明细。"}
        )
    return _feishu_notification_card_v2(
        "物料编辑通知｜物料删除已完成",
        "red",
        elements,
    )


def notify_enabled_admins_of_category_delete(draft: dict[str, object]) -> int:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送删除通知。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    return send_category_notification_to_available_admins(
        client,
        recipients,
        category_delete_notification_card(draft),
    )


def ensure_inventory_zero_since_field() -> bool:
    refresh_feishu_schema_cache()
    if feishu_has_field(MATERIAL_TABLE_NAME, INVENTORY_ZERO_SINCE_FIELD):
        return False
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建库存归零时间字段。")
    client.create_field(
        feishu_table_id(MATERIAL_TABLE_NAME),
        INVENTORY_ZERO_SINCE_FIELD,
        1,
    )
    refresh_feishu_schema_cache()
    if not feishu_has_field(MATERIAL_TABLE_NAME, INVENTORY_ZERO_SINCE_FIELD):
        raise RuntimeError("物料主数据的库存归零时间字段创建失败。")
    return True


def inventory_auto_disable_notification_card(
    rows: list[dict[str, object]],
    checked_at: str,
) -> dict[str, object]:
    visible_rows = rows[:40]
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": (
                f"**自动停用 {len(rows)} 条库存行**\n"
                f"检查时间：{_feishu_card_plain_text(checked_at, max_length=100)}\n"
                f"规则：当前库存为 0，且超过 {INVENTORY_AUTO_DISABLE_DAYS} 天没有有效库存数量变化。"
            ),
        },
        {"tag": "hr"},
        {"tag": "markdown", "content": "**停用明细**"},
    ]
    table_rows: list[dict[str, object]] = []
    for index, row in enumerate(visible_rows, start=1):
        table_rows.append(
            {
                "sequence": index,
                "material_code": _feishu_card_plain_text(row.get("material_code"), max_length=100),
                "specification": (
                    f"{_feishu_card_plain_text(row.get('product'), max_length=250)} / "
                    f"{_feishu_card_plain_text(row.get('model') or NO_MODEL_TEXT, max_length=160)} / "
                    f"{_feishu_card_plain_text(row.get('language') or NO_LANGUAGE_TEXT, max_length=160)}"
                ),
                "quantity": 0,
                "zero_since": _feishu_card_plain_text(row.get("zero_since"), max_length=100),
            }
        )
    elements.append(
        _feishu_notification_table(
            [
                {"name": "sequence", "display_name": "序号", "data_type": "number", "width": "80px", "horizontal_align": "center"},
                {"name": "material_code", "display_name": "物料编码", "data_type": "text", "width": "130px"},
                {"name": "specification", "display_name": "品类 / 型号 / 语种", "data_type": "text"},
                {"name": "quantity", "display_name": "库存", "data_type": "number", "width": "80px", "horizontal_align": "right"},
                {"name": "zero_since", "display_name": "归零计时", "data_type": "text", "width": "160px"},
            ],
            table_rows,
        )
    )
    if len(rows) > len(visible_rows):
        elements.append(
            {
                "tag": "markdown",
                "content": f"另有 **{len(rows) - len(visible_rows)}** 条，请在物料主数据中查看。",
            }
        )
    return _feishu_notification_card_v2(
        "零库存行已自动停用",
        "red",
        elements,
    )


def notify_enabled_admins_of_inventory_auto_disable(
    rows: list[dict[str, object]],
    checked_at: str,
) -> int:
    if not rows:
        return 0
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送库存停用通知。")
    recipients = enabled_admin_open_ids()
    if not recipients:
        raise RuntimeError("用户权限表中没有启用的管理员账号。")
    card = inventory_auto_disable_notification_card(rows, checked_at)
    for open_id in recipients:
        send_feishu_interactive_message(client, open_id, card)
    return len(recipients)


def maintain_inventory_status(
    *,
    now: datetime | None = None,
    inactivity_days: int = INVENTORY_AUTO_DISABLE_DAYS,
) -> dict[str, object]:
    field_created = ensure_inventory_zero_since_field()
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    if not material_rows:
        raise RuntimeError("物料主数据没有返回任何记录，已停止库存状态维护。")
    model_rows = fresh_feishu_rows(MODEL_TABLE_NAME)
    model_name_updated_count = sync_material_model_names_from_dimension(
        material_rows,
        model_rows,
    )
    material_rows = material_rows_with_dimension_model_names(material_rows, model_rows)
    ledger_rows = fresh_feishu_rows(LEDGER_TABLE_NAME)
    plan = plan_inventory_status_maintenance(
        material_rows,
        ledger_rows,
        now=now,
        inactivity_days=inactivity_days,
    )
    updates = list(plan["updates"])
    updated_count = (
        feishu_batch_update_record_fields(MATERIAL_TABLE_NAME, updates)
        if updates
        else 0
    )
    if updated_count != len(updates):
        raise RuntimeError(
            f"库存状态维护只更新了 {updated_count}/{len(updates)} 条记录，已停止后续操作。"
        )

    disabled_rows = list(plan["disabled_rows"])
    notification_count = 0
    if disabled_rows:
        try:
            notification_count = notify_enabled_admins_of_inventory_auto_disable(
                disabled_rows,
                str(plan["checked_at"]),
            )
        except Exception as exc:
            rollback_records = [
                {
                    "record_id": str(row.get("record_id") or ""),
                    "fields": {"启用状态": STATUS_ACTIVE},
                }
                for row in disabled_rows
                if str(row.get("record_id") or "")
            ]
            rolled_back = feishu_batch_update_record_fields(
                MATERIAL_TABLE_NAME,
                rollback_records,
            )
            st.cache_data.clear()
            raise RuntimeError(
                f"库存行停用通知发送失败，已恢复 {rolled_back}/{len(rollback_records)} 条记录：{exc}"
            ) from exc

    st.cache_data.clear()
    return {
        "checked_at": plan["checked_at"],
        "field_created": field_created,
        "model_name_updated_count": model_name_updated_count,
        "material_count": plan["material_count"],
        "ledger_count": plan["ledger_count"],
        "updated_count": updated_count,
        "enabled_count": len(plan["enabled_rows"]),
        "disabled_count": len(disabled_rows),
        "initialized_zero_count": plan["initialized_zero_rows"],
        "notification_count": notification_count,
        "enabled_rows": plan["enabled_rows"],
        "disabled_rows": disabled_rows,
    }


def requester_prefers_english(request_data: dict[str, object]) -> bool:
    requester = str(request_data.get("requester") or "").strip()
    return bool(requester) and re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", requester) is None


def english_material_notification_label(value: object) -> str:
    text = str(value or "-").strip() or "-"
    english_parts = re.findall(r"[（(]([^()（）]*[A-Za-z][^()（）]*)[）)]", text)
    if english_parts:
        return english_parts[-1].strip()
    return str(translate_ui_text(text, LANGUAGE_EN))


def sales_request_received_notification_text(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
    *,
    english: bool = False,
) -> str:
    valid_lines = [line for line in lines if int(line.get("quantity") or 0) > 0]
    details = [
        (
            f"{index:02d}. "
            f"{english_material_notification_label(line.get('product'))} / "
            f"{request_model_display_label(line.get('model'), language=LANGUAGE_EN)} / "
            f"{english_material_notification_label(line.get('language') or NO_LANGUAGE_TEXT)} "
            f"× {int(line.get('quantity') or 0)}"
        )
        for index, line in enumerate(valid_lines, start=1)
    ]
    if english:
        return "\n".join(
            [
                "Your marketing material request is being reviewed for inventory availability and will enter the approval process after confirmation.",
                "",
                "Material details",
                *details,
                "",
                f"Request No.: {request_no}",
                f"Applicant: {str(request_payload.get('requester') or '-')}",
                f"Purpose: {str(request_payload.get('material_usage') or '-')}",
            ]
        )
    details = [
        (
            f"{index:02d}. {str(line.get('product') or '-')} / "
            f"{request_model_display_label(line.get('model'), language=LANGUAGE_ZH)} / "
            f"{str(line.get('language') or NO_LANGUAGE_TEXT)} "
            f"× {int(line.get('quantity') or 0)}"
        )
        for index, line in enumerate(valid_lines, start=1)
    ]
    return "\n".join(
        [
            "【您提交的营销物料申请正在进行库存确认，确认后将进入审批流程】",
            "",
            "物料明细",
            *details,
            "",
            f"申请单号：{request_no}",
            f"申请人：{str(request_payload.get('requester') or '-')}",
            f"物料用途：{str(request_payload.get('material_usage') or '-')}",
        ]
    )


def sales_request_received_notification_card(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    english = requester_prefers_english(request_payload)
    header_title = (
        "Your marketing material request is being reviewed for inventory availability and will enter the approval process after confirmation"
        if english
        else "您提交的营销物料申请正在进行库存确认，确认后将进入审批流程"
    )
    detail_title = "Material details" if english else "物料明细"
    info_title = "Request information" if english else "申请信息"
    info_fields = [
        ("Request No." if english else "申请单号", request_no),
        ("Applicant" if english else "申请人", request_payload.get("requester")),
        ("Purpose" if english else "物料用途", request_payload.get("material_usage")),
    ]
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": header_title},
        },
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": header_title},
            "icon": {"tag": "standard_icon", "token": "approve_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": [
                _feishu_notification_section(
                    detail_title,
                    [_feishu_requester_material_table(lines, english=english)],
                    color="blue",
                    focus=True,
                ),
                _feishu_notification_section(
                    info_title,
                    [_feishu_notification_field_grid(info_fields)],
                    color="blue",
                    last=True,
                ),
            ],
        },
    }


def notify_sales_request_received(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> int:
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    eligible_requesters = set(enabled_sales_open_ids()) | set(enabled_admin_open_ids())
    if not requester_open_id or requester_open_id not in eligible_requesters:
        return 0
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送销售申请回执。")
    send_feishu_interactive_message(
        client,
        requester_open_id,
        sales_request_received_notification_card(request_no, request_payload, lines),
    )
    return 1


def request_material_match_key(
    product: object,
    model: object,
    language: object,
) -> tuple[str, str, str]:
    return (
        normalize_category_match_key(product),
        normalize_option_label(model or NO_MODEL_TEXT),
        normalize_option_label(language),
    )


def build_request_material_index(
    material_rows: list[dict],
    category_rows: list[dict],
    *,
    include_all_for_admin: bool = False,
) -> dict[tuple[str, str, str], dict]:
    raw_material_by_id = {feishu_record_id(row): row for row in material_rows}
    allowed_category_keys = {
        normalize_category_match_key(feishu_text(feishu_fields(row), "物料品类"))
        for row in category_rows
        if feishu_text(feishu_fields(row), "物料品类")
        and (
            feishu_request_page_visible(feishu_fields(row))
            or include_all_for_admin
        )
    }
    return {
        request_material_match_key(
            record["category"],
            record["model"],
            record["language"],
        ): raw_material_by_id[str(record["record_id"])]
        for record in feishu_inventory_records_from_rows(
            material_rows,
            active_only=False,
        )
        if (
            include_all_for_admin
            or feishu_request_page_visible(
                feishu_fields(raw_material_by_id[str(record["record_id"])])
            )
        )
        and normalize_category_match_key(record["category"]) in allowed_category_keys
    }


def ensure_custom_request_material(
    material_rows: list[dict],
    item: dict[str, object],
    submission_token: str,
) -> dict:
    """Create or recover the request-scoped master row for one custom material."""
    product = str(item.get("product") or "").strip()
    model = str(item.get("model") or product).strip()
    language = str(item.get("language") or product).strip()
    marker_seed = "|".join(request_material_key(item))
    marker_hash = hashlib.sha256(marker_seed.encode("utf-8")).hexdigest()[:12]
    marker = f"自定义物料申请:{submission_token}:{marker_hash}"
    for row in material_rows:
        if feishu_text(feishu_fields(row), "备注") == marker:
            return row

    parsed_inventory = [
        parsed for row in material_rows
        if (parsed := parse_feishu_inventory_record(row)) is not None
    ]
    fields: dict[str, object] = {
        "物料编码": next_material_codes_from_records(parsed_inventory, 1)[0],
        "物料品类": product,
        "产品型号": model,
        "语种": language,
        "当前库存": 0,
        "备注": marker,
        "启用状态": STATUS_INACTIVE,
        REQUEST_PAGE_VISIBILITY_FIELD: REQUEST_PAGE_HIDDEN_VALUE,
    }
    set_yes_no_field(MATERIAL_TABLE_NAME, fields, "是否临时物料", True)
    set_feishu_unit_price(MATERIAL_TABLE_NAME, fields, 0)
    created = feishu_create_record(MATERIAL_TABLE_NAME, fields)
    if not feishu_record_id(created):
        raise RuntimeError(f"自定义物料主数据创建成功但未返回记录 ID：{product}")
    if not feishu_fields(created):
        created = {**created, "fields": dict(fields)}
    material_rows.append(created)
    return created


def submit_feishu_material_request(
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> tuple[str, int, bool]:
    refresh_feishu_schema_cache()
    valid_lines = [item for item in lines if int(item.get("quantity") or 0) > 0]
    if not valid_lines:
        raise RuntimeError("请至少填写一条数量大于 0 的物料明细。")
    submission_token = str(request_payload.get("submission_token") or "").strip()
    existing_submission = find_completed_submission(submission_token)
    if existing_submission is not None:
        existing_row, existing_line_count = existing_submission
        return feishu_text(feishu_fields(existing_row), "申请单号"), existing_line_count, False

    scheduling_fields = {}
    if request_payload.get("scheduling_version") == 1:
        import order_scheduling as scheduling_rules
        from order_scheduling_service import SchedulingService
        SchedulingService(APP_RUNTIME).validate_schema()
        scheduling_fields = scheduling_rules.calculate_dates(
            request_payload.get("arrival_start"), request_payload.get("arrival_end"),
            str(request_payload.get("request_reason") or ""),
            list(request_payload.get("accepted_roles") or ["销售"]),
            submitted=request_payload.get("accepted_date") or scheduling_rules.today(),
        )
        request_payload = {
            **request_payload,
            "request_reason": scheduling_fields["申请原因"],
        }

    # The queue may run immediately after a category/inventory task. Always
    # validate submissions against live Feishu rows instead of the static page
    # cache, which can legitimately lag behind the preceding background write.
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    raw_material_by_id = {feishu_record_id(row): row for row in material_rows}
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    material_index = build_request_material_index(
        material_rows,
        category_rows,
        include_all_for_admin=(
            "管理员" in set(request_payload.get("accepted_roles") or [])
        ),
    )
    category_price_rmb = {
        normalize_category_match_key(feishu_text(feishu_fields(row), "物料品类")): feishu_float(
            feishu_fields(row), UNIT_PRICE_RMB_FIELD
        )
        for row in category_rows
    }
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
        key = request_material_match_key(product, model, language)
        if key in seen_keys:
            raise RuntimeError(f"同一申请单内物料重复，请合并数量：{product} / {model} / {language}")
        seen_keys.add(key)
        is_custom_material = bool(item.get("is_custom_material"))
        material_row = (
            ensure_custom_request_material(material_rows, item, submission_token)
            if is_custom_material
            else material_index.get(key)
        )
        if material_row is None:
            raise RuntimeError(f"未找到物料组合：{product} / {model} / {language}")
        raw_material_by_id[feishu_record_id(material_row)] = material_row
        material_fields = feishu_fields(material_row)
        unit_price_rmb = 0.0 if is_custom_material else request_material_unit_price_rmb(
            material_fields, category_price_rmb.get(normalize_category_match_key(product), 0.0)
        )
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
                "unit_price_rmb": unit_price_rmb,
                "subtotal_rmb": request_line_subtotal_rmb(unit_price_rmb, quantity),
                "is_custom_material": is_custom_material,
            }
        )

    now = datetime.now()
    material_usage = str(request_payload.get("material_usage") or "").strip()
    request_no = next_request_no()
    request_fields: dict[str, object] = {
        "申请单号": request_no,
        "申请类型": "普通物料申请",
        "标题": request_payload.get("title") or REQUEST_FORM_TITLE,
        "申请部门/区域": request_payload.get("department"),
        "申请部门": request_payload.get("department"),
        "申请部门|区域": request_payload.get("department"),
        "客户名称": request_payload.get("customer_name"),
        "国家": request_payload.get("country"),
        "收件人信息": request_payload.get("recipient_info"),
        "运费的承担者": DEFAULT_FREIGHT_PAYER,
        "运费承担者": DEFAULT_FREIGHT_PAYER,
        "业务类型": "物料领取",
        "用途/活动": material_usage,
        "用途|活动": material_usage,
        "物料用途": material_usage,
        "审批状态": REQUEST_STATUS_PENDING,
        "库存审查状态": INVENTORY_REVIEW_PENDING,
        "库存审查结论": request_inventory_review_result(
            [
                {
                    "quantity": int(item["quantity"]),
                    "current_stock": int(item["stock_snapshot"]),
                }
                for item in prepared_lines
            ]
        ),
        "申请变更次数": "0",
        "库存快照时间": feishu_datetime_value(REQUEST_TABLE_NAME, "库存快照时间", now),
        "管理员通知状态": "待发送",
        REQUEST_TOTAL_RMB_FIELD: round(
            sum(float(item["subtotal_rmb"]) for item in prepared_lines), 2
        ),
        "提交时间": feishu_datetime_value(REQUEST_TABLE_NAME, "提交时间", now),
        "备注": request_note_text(request_payload),
    }
    if scheduling_fields:
        request_fields.update(scheduling_fields)
        request_fields["排期编辑版本"] = 0
        # The accepted calendar day must not move forward because a Worker was delayed.
        request_fields["提交时间"] = int(request_payload["accepted_at_ms"])
    if any(bool(item.get("is_custom_material")) for item in prepared_lines):
        set_first_plain_field(
            REQUEST_TABLE_NAME,
            request_fields,
            ["临时物料清理状态"],
            "待清理",
        )
    set_first_plain_field(REQUEST_TABLE_NAME, request_fields, ["提交幂等键"], submission_token)
    set_first_person_or_plain_field(
        REQUEST_TABLE_NAME,
        request_fields,
        ["申请人", "申请人姓名"],
        request_payload.get("requester"),
        request_payload.get("requester_open_id"),
    )
    set_first_plain_field(
        REQUEST_TABLE_NAME,
        request_fields,
        ["申请人OpenID", "申请人 open_id"],
        request_payload.get("requester_open_id"),
    )
    set_first_plain_field(
        REQUEST_TABLE_NAME,
        request_fields,
        ["申请部门ID", "申请部门 open_department_id"],
        request_payload.get("department_id"),
    )
    request_record = feishu_create_record(REQUEST_TABLE_NAME, request_fields)
    request_record_id = feishu_record_id(request_record)
    if not request_record_id:
        raise RuntimeError("申请单创建成功但未返回记录 ID。")
    request_no = ensure_unique_request_no(request_record_id, request_no, submission_token)

    line_records: list[dict[str, object]] = []
    for index, item in enumerate(prepared_lines, start=1):
        line_fields: dict[str, object] = {
            "明细编号": f"{request_no}-{index:02d}",
            "申请数量": int(item["quantity"]),
            "提交时库存快照": int(item["stock_snapshot"]),
            "原申请数量": str(int(item["quantity"])),
            "库存审查时库存": str(int(item["stock_snapshot"])),
            "库存满足状态": (
                INVENTORY_RESULT_SUFFICIENT
                if int(item["stock_snapshot"]) > 0
                and int(item["stock_snapshot"]) >= int(item["quantity"])
                else "库存不足，需要制作"
            ),
            "审批通过数量": int(item["quantity"]),
            "实际发放数量": 0,
            "明细状态": REQUEST_LINE_STATUS_PENDING,
            "备注": item["remark"],
            REQUEST_PRICE_SNAPSHOT_FIELD: float(item["unit_price_rmb"]),
            REQUEST_LINE_SUBTOTAL_FIELD: float(item["subtotal_rmb"]),
        }
        if scheduling_fields:
            for field_name in (
                "物料使用时间",
                "物料下单时间",
                "物料到货时间",
                "物料发货时间",
            ):
                if field_name in scheduling_fields:
                    line_fields[field_name] = scheduling_fields[field_name]
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["申请单号"], request_no)
        set_request_line_material_fields(
            line_fields,
            raw_material_by_id[str(item["material_record_id"])],
            str(item["product"]),
            str(item["model"]),
            str(item["language"]),
        )
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["物料数量"], int(item["quantity"]))
        for request_field in ["所属申请单", "申请单"]:
            if feishu_has_field(REQUEST_LINE_TABLE_NAME, request_field):
                line_fields[request_field] = request_no if feishu_accepts_plain_value(REQUEST_LINE_TABLE_NAME, request_field) else [request_record_id]
                break
        line_records.append(line_fields)

    client = feishu_client()
    if client is None:
        return request_no, 0, True
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
    canonical_row, _ = reconcile_submission_duplicates(submission_token, request_record_id)
    created_new_request = True
    if canonical_row is not None:
        request_no = feishu_text(feishu_fields(canonical_row), "申请单号") or request_no
        created_new_request = feishu_record_id(canonical_row) == request_record_id
    return request_no, len(line_records), created_new_request


def queued_material_request_payload(
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    if request_payload.get("scheduling_version") == 1:
        import order_scheduling as scheduling_rules

        request_payload = {
            **request_payload,
            "request_reason": scheduling_rules.normalize_reason(
                request_payload.get("request_reason")
            ),
        }
    queued_request = {
        key: request_payload.get(key)
        for key in (
            "title",
            "department",
            "department_id",
            "requester",
            "requester_open_id",
            "customer_name",
            "country",
            "recipient_info",
            "freight_payer",
            "material_usage",
            "submission_token",
            "scheduling_version",
            "request_reason",
            "arrival_start",
            "arrival_end",
            "accepted_date",
            "accepted_at_ms",
            "accepted_roles",
        )
    }
    queued_request["freight_payer"] = DEFAULT_FREIGHT_PAYER
    queued_lines = [
        {
            "product": str(line.get("product") or ""),
            "model": str(line.get("model") or ""),
            "language": str(line.get("language") or ""),
            "quantity": int(line.get("quantity") or 0),
            "remark": str(line.get("remark") or ""),
            "current_stock": int(line.get("current_stock") or 0),
            "inventory_status": str(line.get("inventory_status") or ""),
            "is_custom_material": bool(line.get("is_custom_material")),
        }
        for line in lines
        if isinstance(line, dict)
    ]
    return {
        "version": 1,
        "request_payload": queued_request,
        "lines": queued_lines,
    }


def enqueue_feishu_material_request(
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> tuple[SubmissionTask, bool]:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建后台申请任务。")
    submission_token = str(request_payload.get("submission_token") or "").strip()
    if not submission_token:
        raise RuntimeError("申请提交幂等键不能为空。")
    table_id = ensure_submission_queue_table(client)
    existing = find_task_by_idempotency_key(client, submission_token, table_id)
    if existing is not None:
        if existing.status == QUEUE_STATUS_FAILED:
            return enqueue_submission_task(
                client,
                QUEUE_TASK_TYPE_MATERIAL_REQUEST,
                submission_token,
                existing.payload,
            )
        return existing, False
    if request_payload.get("scheduling_version") == 1:
        import order_scheduling as scheduling_rules
        from order_scheduling_service import SchedulingService
        service = SchedulingService(APP_RUNTIME)
        service.validate_schema()
        accepted_now = datetime.now(scheduling_rules.CHINA_TZ)
        roles = service.roles(request_payload.get("requester_open_id"))
        scheduling_fields = scheduling_rules.calculate_dates(request_payload.get("arrival_start"), request_payload.get("arrival_end"),
            str(request_payload.get("request_reason") or ""), roles, submitted=accepted_now.date())
        request_payload = {**request_payload, "request_reason": scheduling_fields["申请原因"],
                           "accepted_roles": roles,
                           "accepted_date": accepted_now.date().isoformat(),
                           "accepted_at_ms": int(accepted_now.timestamp() * 1000)}
    payload = queued_material_request_payload(request_payload, lines)
    return enqueue_submission_task(
        client,
        QUEUE_TASK_TYPE_MATERIAL_REQUEST,
        submission_token,
        payload,
    )


def enqueue_feishu_background_write(
    task_type: str,
    payload: dict[str, object],
    idempotency_key: str | None = None,
) -> tuple[SubmissionTask, bool]:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建后台写入任务。")
    return enqueue_submission_task(
        client,
        task_type,
        str(idempotency_key or uuid.uuid4().hex),
        payload,
    )


def serialize_category_sync_args(args: dict[str, object]) -> dict[str, object]:
    queued = dict(args)
    target_values = dict(queued.pop("target_values", {}) or {})
    queued["target_values_rows"] = [
        {"model": str(key[0]), "language": str(key[1]), "values": dict(value)}
        for key, value in target_values.items()
    ]
    return queued


def deserialize_category_sync_args(args: dict[str, object]) -> dict[str, object]:
    restored = dict(args)
    rows = list(restored.pop("target_values_rows", []) or [])
    restored["target_values"] = {
        (str(row.get("model") or ""), str(row.get("language") or "")): dict(row.get("values") or {})
        for row in rows if isinstance(row, dict)
    }
    return restored


def feishu_person_text(fields: dict, names: list[str]) -> str:
    for name in names:
        value = fields.get(name)
        if value in (None, ""):
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, dict):
                for key in ("name", "en_name", "text", "email"):
                    if item.get(key):
                        return str(item[key]).strip()
            elif str(item).strip():
                return str(item).strip()
    return ""


REQUEST_NOTE_LABELS = (
    "客户名称",
    "国家",
    "收件人信息",
    "运费承担者",
    "物料用途",
    "申请人",
    "相关附件",
)


def request_note_values(fields: dict) -> dict[str, str]:
    note = feishu_text(fields, "备注")
    if not note:
        return {}
    labels_pattern = "|".join(re.escape(label) for label in REQUEST_NOTE_LABELS)
    pattern = re.compile(
        rf"^(?P<label>{labels_pattern})[：:][ \t]*(?P<value>.*?)"
        rf"(?=^(?:{labels_pattern})[：:]|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    return {
        match.group("label"): match.group("value").strip()
        for match in pattern.finditer(note)
        if match.group("value").strip()
    }


def request_applicant_text(fields: dict) -> str:
    requester = feishu_person_text(fields, ["申请人", "申请人姓名"])
    if requester:
        return requester
    return request_note_values(fields).get("申请人", "")


def set_request_line_material_fields(
    fields: dict[str, object],
    material_row: dict,
    product: str,
    model: str,
    language: str,
) -> None:
    material_record_id = feishu_record_id(material_row)
    material_fields = feishu_fields(material_row)
    material_code = feishu_text(material_fields, "物料编码")
    # Keep immutable text snapshots alongside relation/lookup fields. Custom
    # materials intentionally do not create category/model/language dimension
    # rows, so approval integrations can fall back to these display values.
    for snapshot_field, display_value in (
        ("品类名称", product),
        ("产品型号名称", model or NO_MODEL_TEXT),
        ("语种名称", language),
        ("实际发放物料品类", product),
        ("实际发放产品型号", model or NO_MODEL_TEXT),
        ("实际发放语种", language),
    ):
        if (
            feishu_has_field(REQUEST_LINE_TABLE_NAME, snapshot_field)
            and feishu_accepts_plain_value(REQUEST_LINE_TABLE_NAME, snapshot_field)
        ):
            fields[snapshot_field] = display_value
    dimension_fields = (
        (["品类", "物料品类"], ["品类关联"], product),
        (["产品型号"], list(MODEL_LINK_FIELD_CANDIDATES), model or NO_MODEL_TEXT),
        (["语种"], list(LANGUAGE_LINK_FIELD_CANDIDATES), language),
    )
    for line_field_candidates, material_link_candidates, display_value in dimension_fields:
        line_field = first_feishu_field(REQUEST_LINE_TABLE_NAME, line_field_candidates)
        if not feishu_has_field(REQUEST_LINE_TABLE_NAME, line_field):
            continue
        if feishu_accepts_plain_value(REQUEST_LINE_TABLE_NAME, line_field):
            fields[line_field] = display_value
            continue
        linked_record_ids = feishu_link_ids_any(material_fields, material_link_candidates)
        if linked_record_ids:
            fields[line_field] = linked_record_ids
    for material_field in ["物料", "物料编码"]:
        if not feishu_has_field(REQUEST_LINE_TABLE_NAME, material_field):
            continue
        fields[material_field] = (
            material_code
            if feishu_accepts_plain_value(REQUEST_LINE_TABLE_NAME, material_field)
            else [material_record_id]
        )


def load_feishu_request_records(rows: list[dict] | None = None) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    source_rows = rows if rows is not None else feishu_rows(REQUEST_TABLE_NAME)
    for row in source_rows:
        fields = feishu_fields(row)
        request_no = feishu_text(fields, "申请单号")
        if not request_no:
            continue
        requester_open_ids = feishu_person_open_ids(fields, ["申请人", "申请人姓名"])
        note_values = request_note_values(fields)
        records.append(
            {
                "record_id": feishu_record_id(row),
                "request_no": request_no,
                "title": feishu_text(fields, "标题"),
                "request_type": feishu_text(fields, "申请类型"),
                "requester": request_applicant_text(fields),
                "requester_open_id": requester_open_ids[0] if requester_open_ids else "",
                "department": feishu_text_any(fields, ["申请部门/区域", "申请部门|区域", "申请部门"]),
                "position": feishu_text_any(fields, ["岗位", "职位"]),
                "customer_name": feishu_text(fields, "客户名称")
                or note_values.get("客户名称", ""),
                "country": feishu_text(fields, "国家") or note_values.get("国家", ""),
                "recipient_info": feishu_text(fields, "收件人信息")
                or note_values.get("收件人信息", ""),
                "freight_payer": feishu_text_any(fields, ["运费的承担者", "运费承担者"])
                or note_values.get("运费承担者", ""),
                "material_usage": feishu_text_any(fields, ["物料用途", "用途/活动", "用途|活动"])
                or note_values.get("物料用途", ""),
                "material_usage_time": feishu_datetime_text(
                    fields.get("物料使用时间", "")
                ),
                "request_reason": feishu_text(fields, "申请原因")
                or note_values.get("申请原因", ""),
                "request_total_rmb": feishu_float(fields, REQUEST_TOTAL_RMB_FIELD),
                "status": feishu_text(fields, "审批状态"),
                "submitted_at": feishu_datetime_text(fields.get("提交时间", "")),
                "approved_at": feishu_datetime_text(fields.get("审批时间", "")),
                "approval_comment": feishu_text(fields, "审批意见"),
                "inventory_review_status": feishu_text(fields, "库存审查状态")
                or INVENTORY_REVIEW_PENDING,
                "inventory_review_reminder_at": feishu_datetime_text(
                    fields.get(INVENTORY_REVIEW_REMINDER_AT_FIELD, "")
                ),
                "inventory_review_reminder_at_ms": feishu_int(
                    fields, INVENTORY_REVIEW_REMINDER_AT_FIELD
                ),
                "inventory_review_reminder_status": feishu_text(
                    fields, INVENTORY_REVIEW_REMINDER_STATUS_FIELD
                ),
            }
        )
    records.sort(key=lambda item: str(item["request_no"]), reverse=True)
    return records


def load_feishu_request_line_records(
    rows: list[dict] | None = None,
    material_rows: list[dict] | None = None,
    category_rows: list[dict] | None = None,
) -> list[dict[str, object]]:
    source_material_rows = material_rows if material_rows is not None else feishu_material_rows()
    material_by_id = {feishu_record_id(row): row for row in source_material_rows}
    source_category_rows = category_rows if category_rows is not None else feishu_category_rows()
    category_definition_by_key = {
        normalize_category_match_key(feishu_text(feishu_fields(row), "物料品类")):
            feishu_text(feishu_fields(row), "品类定义") or UNDEFINED_CATEGORY_DEFINITION
        for row in source_category_rows
        if feishu_text(feishu_fields(row), "物料品类").strip()
    }
    records: list[dict[str, object]] = []
    source_rows = rows if rows is not None else feishu_rows(REQUEST_LINE_TABLE_NAME)
    for row in source_rows:
        fields = feishu_fields(row)
        request_ids = feishu_link_ids_any(fields, ["所属申请单", "申请单"])
        material_ids = feishu_link_ids_any(fields, ["物料", "物料编码"])
        material_row = material_by_id.get(material_ids[0], {}) if material_ids else {}
        material_fields = feishu_fields(material_row)
        product = (
            feishu_text(material_fields, "物料品类")
            or feishu_text_any(fields, ["品类名称", "物料品类", "品类"])
        )
        model = (
            feishu_text(material_fields, "产品型号")
            or feishu_text_any(fields, ["产品型号名称", "产品型号"])
            or NO_MODEL_TEXT
        )
        language = (
            feishu_text(material_fields, "语种")
            or feishu_text_any(fields, ["语种名称", "语种"])
        )
        actual_product = feishu_text(fields, "实际发放物料品类") or product
        actual_model = feishu_text(fields, "实际发放产品型号") or model
        actual_language = feishu_text(fields, "实际发放语种") or language
        quantity = feishu_int_any(fields, ["申请数量", "物料数量"])
        if not product or not language or quantity <= 0:
            continue
        approved_qty = feishu_int(fields, "审批通过数量", quantity)
        actual_qty = feishu_int(fields, "实际发放数量")
        records.append(
            {
                "record_id": feishu_record_id(row),
                "line_no": feishu_text(fields, "明细编号"),
                "request_ids": request_ids,
                "request_no": feishu_text_any(fields, ["申请单号", "所属申请单", "申请单"]),
                "material_record_id": material_ids[0] if material_ids else "",
                "product": product,
                "category_definition": category_definition_by_key.get(
                    normalize_category_match_key(product),
                    UNDEFINED_CATEGORY_DEFINITION,
                ),
                "model": model,
                "language": language,
                "actual_product": actual_product,
                "actual_model": actual_model,
                "actual_language": actual_language,
                "actual_material_code": feishu_text(fields, "实际发放物料编码"),
                "quantity": quantity,
                "usage": feishu_text(fields, "物料用途"),
                "remark": feishu_text(fields, "备注"),
                "stock_snapshot": feishu_int(fields, "提交时库存快照"),
                "unit_price_rmb": feishu_float(fields, REQUEST_PRICE_SNAPSHOT_FIELD),
                "subtotal_rmb": feishu_float(fields, REQUEST_LINE_SUBTOTAL_FIELD),
                "current_stock": feishu_int(material_fields, "当前库存"),
                "in_transit_stock": feishu_int(material_fields, "在途库存"),
                "approved_qty": approved_qty,
                "actual_issue_qty": actual_qty,
                "status": feishu_text(fields, "明细状态") or REQUEST_LINE_STATUS_PENDING,
            }
        )
    return records


def request_inventory_review_result(lines: list[dict[str, object]]) -> str:
    sufficient = [
        int(line.get("current_stock") or 0) >= int(line.get("quantity") or 0)
        and int(line.get("current_stock") or 0) > 0
        for line in lines
    ]
    if sufficient and all(sufficient):
        return INVENTORY_RESULT_SUFFICIENT
    if any(sufficient):
        return INVENTORY_RESULT_PARTIAL
    return INVENTORY_RESULT_INSUFFICIENT


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed if str(item)] if isinstance(parsed, list) else []


def request_review_access_token(request_id: str, operator_open_id: str) -> str:
    message = f"{request_id}:{operator_open_id}".encode("utf-8")
    return hmac.new(feishu_app_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()


def valid_request_review_access_token(
    request_id: str,
    operator_open_id: str,
    token: str,
) -> bool:
    if not request_id or not operator_open_id or not token:
        return False
    return hmac.compare_digest(
        request_review_access_token(request_id, operator_open_id),
        token,
    )


REQUEST_INVENTORY_PAGE_LINE_FIELDS = [
    "所属申请单",
    "申请单",
    "申请单号",
    "物料",
    "物料编码",
    "品类名称",
    "物料品类",
    "品类",
    "产品型号名称",
    "产品型号",
    "语种名称",
    "语种",
    "申请数量",
    "物料数量",
    "备注",
    REQUEST_PRICE_SNAPSHOT_FIELD,
    REQUEST_LINE_SUBTOTAL_FIELD,
]


@st.cache_data(show_spinner=False, ttl=120)
def load_request_inventory_page_rows(
    request_id: str,
    request_table_id: str,
    request_line_table_id: str,
    request_line_field_names: tuple[str, ...],
    app_id: str,
    app_secret: str,
    app_token: str,
) -> tuple[dict, list[dict]]:
    client = FeishuBitableClient(
        FeishuBitableConfig(app_id, app_secret, app_token)
    )
    request_row = client.get_record(request_table_id, request_id)
    line_ids = feishu_link_ids_any(
        feishu_fields(request_row), ["申请明细", "关联申请明细"]
    )
    if line_ids:
        related_lines = [
            client.get_record(request_line_table_id, line_id) for line_id in line_ids
        ]
    else:
        line_rows = client.list_records(
            request_line_table_id,
            field_names=list(request_line_field_names),
        )
        related_lines = [
            row
            for row in line_rows
            if request_id
            in feishu_link_ids_any(feishu_fields(row), ["所属申请单", "申请单"])
        ]
    return request_row, related_lines


def request_inventory_review_page_context(request_id: str) -> dict[str, object]:
    if not request_id:
        raise RuntimeError("缺少申请单标识。")
    request_row, line_rows = load_request_inventory_page_rows(
        request_id,
        feishu_table_id(REQUEST_TABLE_NAME),
        feishu_table_id(REQUEST_LINE_TABLE_NAME),
        tuple(
            field_name
            for field_name in REQUEST_INVENTORY_PAGE_LINE_FIELDS
            if feishu_has_field(REQUEST_LINE_TABLE_NAME, field_name)
        ),
        *feishu_config_args(),
    )
    if not request_row:
        raise RuntimeError("申请单不存在或已被删除。")
    request = load_feishu_request_records([request_row])[0]
    request_fields = feishu_fields(request_row)
    request.update(
        {
            "inventory_review_status": feishu_text(request_fields, "库存审查状态")
            or INVENTORY_REVIEW_PENDING,
            "inventory_review_result": feishu_text(request_fields, "库存审查结论"),
            "inventory_change_note": feishu_text(
                request_fields, "申请物料更改信息说明"
            ),
            "inventory_review_version": int(
                feishu_text(request_fields, "申请变更次数") or 0
            ),
        }
    )
    material_rows = feishu_rows(MATERIAL_TABLE_NAME)
    category_rows = feishu_rows(CATEGORY_TABLE_NAME)
    lines = load_feishu_request_line_records(line_rows, material_rows, category_rows)
    for line in lines:
        stock = int(line.get("current_stock") or 0)
        quantity = int(line.get("quantity") or 0)
        line["inventory_status"] = (
            INVENTORY_RESULT_SUFFICIENT
            if stock > 0 and stock >= quantity
            else "库存不足，需要制作"
        )
    return {
        "request": request,
        "request_row": request_row,
        "lines": lines,
        "result": request_inventory_review_result(lines),
        "snapshot_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "material_rows": material_rows,
        "category_rows": category_rows,
    }


def request_inventory_review_context(
    *,
    request_id: str = "",
    request_no: str = "",
) -> dict[str, object]:
    request_rows = fresh_feishu_rows(REQUEST_TABLE_NAME)
    request_row = next(
        (
            row
            for row in request_rows
            if (request_id and feishu_record_id(row) == request_id)
            or (request_no and feishu_text(feishu_fields(row), "申请单号") == request_no)
        ),
        None,
    )
    if request_row is None:
        raise RuntimeError("申请单不存在或已被删除。")
    request = load_feishu_request_records([request_row])[0]
    request_fields = feishu_fields(request_row)
    request.update(
        {
            "inventory_review_status": feishu_text(request_fields, "库存审查状态") or INVENTORY_REVIEW_PENDING,
            "inventory_review_result": feishu_text(request_fields, "库存审查结论"),
            "inventory_change_note": feishu_text(request_fields, "申请物料更改信息说明"),
            "inventory_review_version": int(feishu_text(request_fields, "申请变更次数") or 0),
            "inventory_message_ids": _json_list(feishu_text(request_fields, "库存确认消息ID")),
        }
    )
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    all_lines = load_feishu_request_line_records(
        fresh_feishu_rows(REQUEST_LINE_TABLE_NAME),
        material_rows,
        category_rows,
    )
    lines = request_lines_for_request(request, all_lines)
    for line in lines:
        stock = int(line.get("current_stock") or 0)
        quantity = int(line.get("quantity") or 0)
        line["inventory_status"] = (
            INVENTORY_RESULT_SUFFICIENT
            if stock > 0 and stock >= quantity
            else "库存不足，需要制作"
        )
    return {
        "request": request,
        "request_row": request_row,
        "lines": lines,
        "result": request_inventory_review_result(lines),
        "snapshot_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "material_rows": material_rows,
        "category_rows": category_rows,
    }


def cached_allocation_material_records(
    cache_data: dict[str, object],
    material_rows: list[dict],
    *,
    current_material_ids: set[str] | None = None,
    category_rows: list[dict] | None = None,
) -> list[dict[str, object]]:
    cached_codes = {
        str(item.get("material_code") or "").strip()
        for item in list(cache_data.get("inventory_rows") or [])
        if isinstance(item, dict) and str(item.get("material_code") or "").strip()
    }
    current_ids = set(current_material_ids or set())
    category_definition_by_key = {
        normalize_category_match_key(feishu_text(feishu_fields(row), "物料品类")):
            feishu_text(feishu_fields(row), "品类定义") or UNDEFINED_CATEGORY_DEFINITION
        for row in list(category_rows if category_rows is not None else feishu_category_rows())
        if feishu_text(feishu_fields(row), "物料品类").strip()
    }
    records: list[dict[str, object]] = []
    for row in material_rows:
        record_id = feishu_record_id(row)
        fields = feishu_fields(row)
        material_code = feishu_text(fields, "物料编码")
        if material_code not in cached_codes and record_id not in current_ids:
            continue
        records.append(
            {
                "record_id": record_id,
                "material_code": material_code,
                "category": feishu_text(fields, "物料品类"),
                "category_definition": category_definition_by_key.get(
                    normalize_category_match_key(feishu_text(fields, "物料品类")),
                    UNDEFINED_CATEGORY_DEFINITION,
                ),
                "model": feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
                "language": feishu_text(fields, "语种") or NO_LANGUAGE_TEXT,
                "quantity": feishu_int(fields, "当前库存"),
                "in_transit_quantity": feishu_int(fields, "在途库存"),
                "unit_price_rmb": request_material_unit_price_rmb(fields),
            }
        )
    return records


def _request_review_person_value(open_id: str) -> list[dict[str, str]] | None:
    return [{"id": open_id}] if str(open_id).startswith("ou_") else None


def ensure_request_change_record_fields() -> None:
    refresh_feishu_schema_cache()
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置。")
    required = {
        "申请单号": 1,
        "操作人OpenID": 1,
        "操作时间": 5,
        "变更说明": 1,
        "变更前JSON": 1,
        "变更后JSON": 1,
        "变更版本": 2,
    }
    table_id = feishu_table_id(REQUEST_CHANGE_TABLE_NAME)
    for field_name, field_type in required.items():
        if not feishu_has_field(REQUEST_CHANGE_TABLE_NAME, field_name):
            client.create_field(table_id, field_name, field_type)
    refresh_feishu_schema_cache()


def _request_review_line_summary(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "record_id": str(line.get("record_id") or ""),
            "material_record_id": str(line.get("material_record_id") or ""),
            "product": str(line.get("product") or ""),
            "model": str(line.get("model") or ""),
            "language": str(line.get("language") or ""),
            "quantity": int(line.get("quantity") or 0),
            "remark": str(line.get("remark") or ""),
            "unit_price_rmb": float(line.get("unit_price_rmb") or 0),
            "subtotal_rmb": float(line.get("subtotal_rmb") or 0),
        }
        for line in lines
    ]


def request_material_detail_text(lines: list[dict[str, object]]) -> str:
    valid_lines = [line for line in lines if int(line.get("quantity") or 0) > 0]
    return "\n".join(
        (
            f"{index:02d}. {str(line.get('product') or '-')} / "
            f"{request_model_display_label(line.get('model'), language=LANGUAGE_ZH)} / "
            f"{str(line.get('language') or NO_LANGUAGE_TEXT)} "
            f"× {int(line.get('quantity') or 0)}"
        )
        for index, line in enumerate(valid_lines, start=1)
    )


def sync_request_ship_date_to_schedule(request_id: str, ship_date: object) -> int:
    """Propagate one request's ship date to every existing schedule record."""
    from order_scheduling import BATCH_TABLE, DETAIL_TABLE, SHIP_DATE, date_ms

    request_key = str(request_id or "").strip()
    if not request_key:
        raise RuntimeError("申请单标识不能为空，无法写入发货日期。")
    ship_date_value = date_ms(ship_date)
    line_rows = fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
    detail_rows = fresh_feishu_rows(DETAIL_TABLE)
    batch_rows = fresh_feishu_rows(BATCH_TABLE)
    line_ids = {
        feishu_record_id(row)
        for row in line_rows
        if request_key in feishu_link_ids_any(feishu_fields(row), ["所属申请单", "申请单"])
    }
    detail_ids = {
        feishu_record_id(row)
        for row in detail_rows
        if request_key in feishu_link_ids(feishu_fields(row), "来源申请单")
    }
    batch_ids = {
        batch_id
        for row in detail_rows
        if feishu_record_id(row) in detail_ids
        for batch_id in feishu_link_ids(feishu_fields(row), "所属下单批次")
    }
    updates = 0
    for table_name, rows, record_ids in (
        (REQUEST_LINE_TABLE_NAME, line_rows, line_ids),
        (DETAIL_TABLE, detail_rows, detail_ids),
        (BATCH_TABLE, batch_rows, batch_ids),
    ):
        if SHIP_DATE not in feishu_table_fields(table_name):
            raise RuntimeError(f"{table_name}缺少字段：{SHIP_DATE}。")
        payload = [
            {"record_id": feishu_record_id(row), "fields": {SHIP_DATE: ship_date_value}}
            for row in rows
            if feishu_record_id(row) in record_ids
        ]
        if payload:
            written = feishu_batch_update_record_fields(table_name, payload)
            if written != len(payload):
                raise RuntimeError(
                    f"{table_name}发货日期写入不完整：应更新{len(payload)}条，实际{written}条。"
                )
            updates += written
    return updates


def allocation_line_requires_order(
    category_definition: object,
    requested: object,
) -> bool:
    """Only printed materials may enter ordering and five-day auto-restock."""
    return (
        str(category_definition or "").strip() == CATEGORY_DEFINITION_PRINT
        and requested is True
    )


def apply_inventory_allocation_schedule(
    request_id: str,
    line_plans: list[dict[str, object]],
    operator_open_id: str,
    generation_key: str,
    *,
    validated_line_ids: set[str] | None = None,
) -> dict[str, object]:
    """Persist per-line order decisions made in the inventory workbench."""
    from order_scheduling import ARRIVAL_DATE, FULFILLMENT_STATUS, GENERATED, date_ms, today
    from order_scheduling_service import SchedulingService

    request_key = str(request_id or "").strip()
    operator = str(operator_open_id or "").strip()
    if not request_key or not generation_key:
        raise RuntimeError("申请单或下单批次标识不能为空。")
    current_day = today()
    planned_day = current_day + timedelta(days=5)
    line_ids = {str(item.get("line_id") or "") for item in line_plans}
    if validated_line_ids is None:
        line_rows = fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
        line_by_id = {
            feishu_record_id(row)
            for row in line_rows
            if feishu_record_id(row) in line_ids
            and request_key in feishu_link_ids_any(feishu_fields(row), ["所属申请单", "申请单"])
        }
        if line_by_id != line_ids:
            raise RuntimeError("配货明细已发生变化，请刷新申请单后重新提交。")
    elif not line_ids <= {str(value) for value in validated_line_ids}:
        raise RuntimeError("配货明细校验不完整，请刷新申请单后重新提交。")
    normalized_plans = [
        {
            **item,
            "order_required": allocation_line_requires_order(
                item.get("category_definition"),
                item.get("order_required"),
            ),
        }
        for item in line_plans
    ]
    order_plans = [item for item in normalized_plans if item["order_required"]]
    no_order_plans = [item for item in normalized_plans if not item["order_required"]]
    line_updates: list[dict[str, object]] = []
    for item in no_order_plans:
        fields: dict[str, object] = {}
        if feishu_has_field(REQUEST_LINE_TABLE_NAME, FULFILLMENT_STATUS):
            fields[FULFILLMENT_STATUS] = "已到货"
        if feishu_has_field(REQUEST_LINE_TABLE_NAME, ARRIVAL_DATE):
            fields[ARRIVAL_DATE] = date_ms(current_day)
        if fields:
            line_updates.append({"record_id": str(item["line_id"]), "fields": fields})
    for item in order_plans:
        fields = {}
        if feishu_has_field(REQUEST_LINE_TABLE_NAME, FULFILLMENT_STATUS):
            fields[FULFILLMENT_STATUS] = "已下单"
        if feishu_has_field(REQUEST_LINE_TABLE_NAME, ARRIVAL_DATE):
            fields[ARRIVAL_DATE] = date_ms(planned_day)
        if fields:
            line_updates.append({"record_id": str(item["line_id"]), "fields": fields})
    if line_updates:
        written = 0
        for update in line_updates:
            result = feishu_update_record_fields(
                REQUEST_LINE_TABLE_NAME,
                str(update["record_id"]),
                dict(update["fields"]),
            )
            if result is not False:
                written += 1
        if written != len(line_updates):
            raise RuntimeError(f"配货下单状态写入不完整：应更新{len(line_updates)}条，实际{written}条。")

    generated = 0
    if order_plans and feishu_client() is not None:
        service = SchedulingService(APP_RUNTIME)
        live_snapshot = service.snapshot(live=True)
        live_groups = service.grouped_requests(live_snapshot)
        if request_key in live_groups:
            already_generated_line_ids = {
                str(item.get("id") or "")
                for item in list(live_groups[request_key].get("lines") or [])
                if feishu_text(dict(item.get("fields") or {}), GENERATED) == "已生成"
            }
            pending_order_plans = [
                item
                for item in order_plans
                if str(item.get("line_id") or "") not in already_generated_line_ids
            ]
            # A retry may arrive after the allocation edit was persisted while
            # every requested order line already belongs to an earlier committed
            # batch.  Treat those lines as satisfied instead of trying to create
            # a duplicate batch; genuinely new order lines still use the normal
            # fail-closed scheduling path below.
            if pending_order_plans:
                selections = [
                    {
                        "request_id": request_key,
                        "line_id": str(item["line_id"]),
                        "planned_date": planned_day.isoformat(),
                        "confirmed_arrived": False,
                    }
                    for item in pending_order_plans
                ]
                payload = {
                    "operator_open_id": operator,
                    "generation_key": generation_key,
                    "selections": selections,
                    "fingerprints": {request_key: live_groups[request_key]["fingerprint"]},
                    "note": "配货工作台自动生成下单批次",
                }
                service.record_schedule(payload, {}, lambda _progress: None)
                generated = len(pending_order_plans)

    request_status = "全部已到货" if no_order_plans and not order_plans else "部分已到货" if no_order_plans else "待下单"
    request_updates: dict[str, object] = {}
    if feishu_has_field(REQUEST_TABLE_NAME, FULFILLMENT_STATUS):
        request_updates[FULFILLMENT_STATUS] = request_status
    if request_updates:
        feishu_update_record_fields(REQUEST_TABLE_NAME, request_key, request_updates)
    return {
        "planned_arrival_date": planned_day.isoformat(),
        "generated_order_lines": generated,
        "arrived_without_order_lines": len(no_order_plans),
    }


def execute_request_inventory_edit(draft: dict[str, object]) -> dict[str, object]:
    request_id = str(draft.get("request_id") or "")
    expected_version = int(draft.get("expected_version") or 0)
    change_note = str(draft.get("change_note") or "").strip()
    ship_date = draft.get("ship_date")
    operator_open_id = str(draft.get("operator_open_id") or "").strip()
    if not change_note:
        raise RuntimeError("申请物料更改信息说明不能为空。")
    context = request_inventory_review_context(request_id=request_id)
    request = dict(context["request"])
    current_version = int(request.get("inventory_review_version") or 0)
    recovering_notifications = (
        current_version == expected_version + 1
        and str(request.get("inventory_change_note") or "") == change_note
    )
    if recovering_notifications:
        generation_key = str(draft.get("generation_key") or f"allocation:{request_id}:{expected_version}")
        category_definition_by_line_id = {
            str(item.get("record_id") or ""): item.get("category_definition")
            for item in list(context.get("lines") or [])
        }
        allocation_plans = [
            {
                "line_id": str(item.get("line_record_id") or ""),
                "category_definition": category_definition_by_line_id.get(
                    str(item.get("line_record_id") or ""),
                    UNDEFINED_CATEGORY_DEFINITION,
                ),
                "order_required": item.get("order_required") is True,
            }
            for item in list(draft.get("lines") or [])
            if str(item.get("line_record_id") or "")
        ]
        if allocation_plans:
            apply_inventory_allocation_schedule(
                request_id,
                allocation_plans,
                operator_open_id,
                generation_key,
                validated_line_ids={item["line_id"] for item in allocation_plans},
            )
        if ship_date not in (None, ""):
            from order_scheduling import SHIP_DATE, date_ms
            feishu_update_record_fields(
                REQUEST_TABLE_NAME,
                request_id,
                {SHIP_DATE: date_ms(ship_date)},
            )
            sync_request_ship_date_to_schedule(request_id, ship_date)
        before_lines = [
            dict(item) for item in list(draft.get("before_lines") or []) if isinstance(item, dict)
        ]
        after_lines = _request_review_line_summary(list(context["lines"]))
        notify_requester_of_inventory_edit(request, before_lines, after_lines, change_note)
        notify_enabled_admins_of_material_request(
            str(request.get("request_no") or ""), request, after_lines
        )
        return {
            "request_no": request.get("request_no"),
            "version": current_version,
            "result": context["result"],
            "recovered_notifications": True,
        }
    desired = [dict(item) for item in list(draft.get("lines") or []) if isinstance(item, dict)]
    if not desired:
        raise RuntimeError("申请必须至少保留 1 条物料明细。")
    material_by_id = {
        feishu_record_id(row): row for row in list(context.get("material_rows") or [])
    }
    category_definition_by_key = {
        normalize_category_match_key(feishu_text(feishu_fields(row), "物料品类")):
            feishu_text(feishu_fields(row), "品类定义") or UNDEFINED_CATEGORY_DEFINITION
        for row in list(context.get("category_rows") or [])
        if feishu_text(feishu_fields(row), "物料品类").strip()
    }
    seen: set[str] = set()
    seen_line_ids: set[str] = set()
    valid_line_ids = {
        str(line.get("record_id") or "")
        for line in list(context["lines"])
        if str(line.get("record_id") or "")
    }
    prepared: list[dict[str, object]] = []
    for item in desired:
        material_id = str(item.get("material_record_id") or "")
        line_record_id = str(item.get("line_record_id") or "")
        quantity = int(item.get("quantity") or 0)
        if material_id in seen:
            raise RuntimeError("同一物料不能在申请中重复出现。")
        if material_id not in material_by_id or quantity <= 0:
            raise RuntimeError("申请明细包含无效物料或数量。")
        # A queued task is the authoritative target state. Administrators may
        # edit or delete a line in Base while the task is waiting; an obsolete
        # source id must therefore fall back to matching/creating the desired
        # material instead of making the task fail.
        if line_record_id not in valid_line_ids or line_record_id in seen_line_ids:
            line_record_id = ""
        seen.add(material_id)
        if line_record_id:
            seen_line_ids.add(line_record_id)
        material_fields = feishu_fields(material_by_id[material_id])
        product = feishu_text(material_fields, "物料品类")
        category_definition = category_definition_by_key.get(
            normalize_category_match_key(product),
            UNDEFINED_CATEGORY_DEFINITION,
        )
        existing_line = next(
            (
                line
                for line in list(context["lines"])
                if str(line.get("material_record_id") or "") == material_id
            ),
            None,
        )
        unit_price_rmb = (
            float(existing_line.get("unit_price_rmb") or 0)
            if existing_line
            else request_material_unit_price_rmb(material_fields)
        )
        prepared.append(
            {
                "line_record_id": line_record_id,
                "material_record_id": material_id,
                "product": product,
                "category_definition": category_definition,
                "model": feishu_text(material_fields, "产品型号") or NO_MODEL_TEXT,
                "language": feishu_text(material_fields, "语种"),
                "quantity": quantity,
                "remark": str(item.get("remark") or "").strip(),
                "current_stock": feishu_int(material_fields, "当前库存"),
                "order_required": allocation_line_requires_order(
                    category_definition,
                    item.get("order_required") is True
                    if "order_required" in item
                    else feishu_int(material_fields, "当前库存") < quantity,
                ),
                "unit_price_rmb": unit_price_rmb,
                "subtotal_rmb": request_line_subtotal_rmb(unit_price_rmb, quantity),
            }
        )

    before_lines = [
        dict(item) for item in list(draft.get("before_lines") or []) if isinstance(item, dict)
    ] or _request_review_line_summary(list(context["lines"]))
    current_by_material = {
        str(line.get("material_record_id") or ""): line for line in list(context["lines"])
    }
    current_by_record_id = {
        str(line.get("record_id") or ""): line
        for line in list(context["lines"])
        if str(line.get("record_id") or "")
    }
    request_no = str(request.get("request_no") or "")
    used_line_numbers = {
        str(line.get("line_no") or "").strip()
        for line in list(context["lines"])
        if str(line.get("line_no") or "").strip()
    }
    suffix_pattern = re.compile(rf"^{re.escape(request_no)}-(\d+)$")
    next_line_suffix = max(
        (
            int(match.group(1))
            for line_no in used_line_numbers
            if (match := suffix_pattern.fullmatch(line_no))
        ),
        default=0,
    )
    line_updates: list[dict[str, object]] = []
    line_creates: list[dict[str, object]] = []
    kept_line_ids: set[str] = set()
    for index, item in enumerate(prepared, start=1):
        source_line_id = str(item.get("line_record_id") or "")
        existing = (
            current_by_record_id.get(source_line_id)
            if source_line_id
            else current_by_material.get(str(item["material_record_id"]))
        )
        fields: dict[str, object] = {
            "申请数量": int(item["quantity"]),
            "审批通过数量": int(item["quantity"]),
            "实际发放数量": int(item["quantity"]),
            "库存审查时库存": str(int(item["current_stock"])),
            "库存满足状态": (
                INVENTORY_RESULT_SUFFICIENT
                if int(item["current_stock"]) > 0 and int(item["current_stock"]) >= int(item["quantity"])
                else "库存不足，需要制作"
            ),
            "明细变更说明": change_note,
            "备注": item["remark"],
            REQUEST_PRICE_SNAPSHOT_FIELD: float(item["unit_price_rmb"]),
            REQUEST_LINE_SUBTOTAL_FIELD: float(item["subtotal_rmb"]),
        }
        if existing:
            line_id = str(existing.get("record_id") or "")
            kept_line_ids.add(line_id)
            set_request_line_material_fields(
                fields,
                material_by_id[str(item["material_record_id"])],
                str(item["product"]),
                str(item["model"]),
                str(item["language"]),
            )
            if feishu_has_field(REQUEST_LINE_TABLE_NAME, "原申请数量"):
                fields["原申请数量"] = str(int(existing.get("quantity") or item["quantity"]))
            line_updates.append({"record_id": line_id, "fields": fields})
        else:
            next_line_suffix += 1
            next_line_no = f"{request_no}-{next_line_suffix:02d}"
            while next_line_no in used_line_numbers:
                next_line_suffix += 1
                next_line_no = f"{request_no}-{next_line_suffix:02d}"
            used_line_numbers.add(next_line_no)
            fields.update(
                {
                    # A request line number is a stable identity, not its current
                    # display position. Allocation edits may delete or reorder
                    # rows, so newly created lines must never reuse a suffix.
                    "明细编号": next_line_no,
                    "原申请数量": str(int(item["quantity"])),
                    "提交时库存快照": int(item["current_stock"]),
                    "明细状态": REQUEST_LINE_STATUS_PENDING,
                    "所属申请单": [request_id],
                }
            )
            set_request_line_material_fields(
                fields,
                material_by_id[str(item["material_record_id"])],
                str(item["product"]),
                str(item["model"]),
                str(item["language"]),
            )
            line_creates.append(fields)

    removed_ids = [
        str(line.get("record_id") or "")
        for line in list(context["lines"])
        if str(line.get("record_id") or "") not in kept_line_ids
        and str(line.get("material_record_id") or "") not in seen
    ]
    if line_updates:
        feishu_batch_update_record_fields(REQUEST_LINE_TABLE_NAME, line_updates)
    created_line_rows = []
    if line_creates:
        created_line_rows = feishu_batch_create_records(REQUEST_LINE_TABLE_NAME, line_creates)
    if removed_ids:
        feishu_batch_delete_record_ids(REQUEST_LINE_TABLE_NAME, removed_ids)

    # Preserve monotonic audit versions without treating a manual Base edit as
    # an optimistic-lock failure. The queued draft still overwrites the live
    # business fields below.
    new_version = max(current_version, expected_version) + 1
    result = request_inventory_review_result(prepared)
    now = datetime.now()
    request_updates: dict[str, object] = {
        "库存审查状态": INVENTORY_REVIEW_CONFIRMED,
        "库存审查结论": result,
        "物料明细文字信息": request_material_detail_text(prepared),
        "申请物料更改信息说明": change_note,
        "申请物料最后修改时间": feishu_datetime_value(REQUEST_TABLE_NAME, "申请物料最后修改时间", now),
        "申请变更次数": str(new_version),
        REQUEST_TOTAL_RMB_FIELD: round(
            sum(float(item["subtotal_rmb"]) for item in prepared), 2
        ),
        "库存快照时间": feishu_datetime_value(REQUEST_TABLE_NAME, "库存快照时间", now),
        INVENTORY_REVIEW_REMINDER_STATUS_FIELD: INVENTORY_REVIEW_REMINDER_NONE,
    }
    if ship_date not in (None, ""):
        from order_scheduling import SHIP_DATE, date_ms
        request_updates[SHIP_DATE] = date_ms(ship_date)
    person_value = _request_review_person_value(operator_open_id)
    if person_value:
        request_updates["申请物料最后修改人"] = person_value
        request_updates["库存审查人"] = person_value
    request_updates["库存审查时间"] = feishu_datetime_value(
        REQUEST_TABLE_NAME,
        "库存审查时间",
        now,
    )
    feishu_update_record_fields(REQUEST_TABLE_NAME, request_id, request_updates)
    if ship_date not in (None, ""):
        sync_request_ship_date_to_schedule(request_id, ship_date)

    current_line_rows = list(created_line_rows or [])
    unresolved_material_ids = {
        str(item.get("material_record_id") or "")
        for item in prepared
        if not str(item.get("line_record_id") or "")
    }
    if unresolved_material_ids:
        current_line_rows.extend(fresh_feishu_rows(REQUEST_LINE_TABLE_NAME))
    allocation_plans = []
    for item in prepared:
        line_id = str(item.get("line_record_id") or "")
        if not line_id:
            line_id = next(
                (
                    feishu_record_id(row)
                    for row in current_line_rows
                    if request_id in feishu_link_ids_any(feishu_fields(row), ["所属申请单", "申请单"])
                    and str(item.get("material_record_id") or "") in feishu_link_ids_any(
                        feishu_fields(row), ["物料编码", "物料"]
                    )
                ),
                "",
            )
        if line_id:
            allocation_plans.append({
                "line_id": line_id,
                "category_definition": item.get("category_definition"),
                "order_required": item.get("order_required") is True,
            })
    allocation_result = apply_inventory_allocation_schedule(
        request_id,
        allocation_plans,
        operator_open_id,
        str(draft.get("generation_key") or f"allocation:{request_id}:{expected_version}"),
        validated_line_ids={item["line_id"] for item in allocation_plans},
    ) if allocation_plans else {}

    ensure_request_change_record_fields()
    after_lines = _request_review_line_summary(prepared)
    feishu_batch_create_records(
        REQUEST_CHANGE_TABLE_NAME,
        [
            {
                "文本": f"{request_no}-V{new_version}",
                "申请单号": request_no,
                "操作人OpenID": operator_open_id or "应用管理员",
                "操作时间": feishu_datetime_value(REQUEST_CHANGE_TABLE_NAME, "操作时间", now),
                "变更说明": change_note,
                "变更前JSON": json.dumps(before_lines, ensure_ascii=False, separators=(",", ":")),
                "变更后JSON": json.dumps(after_lines, ensure_ascii=False, separators=(",", ":")),
                "变更版本": new_version,
            }
        ],
    )
    notify_requester_of_inventory_edit(request, before_lines, after_lines, change_note)
    notify_enabled_admins_of_material_request(request_no, request, after_lines)
    return {"request_no": request_no, "version": new_version, "result": result, **allocation_result}


def execute_request_inventory_confirm(draft: dict[str, object]) -> dict[str, object]:
    from order_scheduling import SHIP_DATE, date_ms
    request_id = str(draft.get("request_id") or "")
    expected_version = int(draft.get("expected_version") or 0)
    operator_open_id = str(draft.get("operator_open_id") or "").strip()
    ship_date = draft.get("ship_date")
    if operator_open_id not in enabled_admin_open_ids():
        raise PermissionError("只有已启用管理员可以确认库存。")
    context = request_inventory_review_context(request_id=request_id)
    request = dict(context["request"])
    already_confirmed = (
        str(request.get("inventory_review_status") or "") == INVENTORY_REVIEW_CONFIRMED
    )
    # The queued confirmation is authoritative. Manual edits made after enqueue
    # must not turn a valid background write into an optimistic-lock failure.
    line_updates = [
        {
            "record_id": str(line.get("record_id") or ""),
            "fields": {
                "审批通过数量": int(line.get("quantity") or 0),
                "实际发放数量": int(line.get("quantity") or 0),
                "库存审查时库存": str(int(line.get("current_stock") or 0)),
                "库存满足状态": str(line.get("inventory_status") or ""),
            },
        }
        for line in list(context["lines"])
        if str(line.get("record_id") or "")
        and (
            not already_confirmed
            or int(line.get("approved_qty") or 0) != int(line.get("quantity") or 0)
            or int(line.get("actual_issue_qty") or 0) != int(line.get("quantity") or 0)
        )
    ]
    if line_updates:
        updated_line_count = feishu_batch_update_record_fields(
            REQUEST_LINE_TABLE_NAME, line_updates
        )
        if updated_line_count != len(line_updates):
            raise RuntimeError(
                f"库存确认应更新 {len(line_updates)} 条申请明细，实际仅更新 {updated_line_count} 条。"
            )
    else:
        updated_line_count = 0
    allocation_plans = [
        {
            "line_id": str(line.get("record_id") or ""),
            "category_definition": line.get("category_definition"),
            "order_required": allocation_line_requires_order(
                line.get("category_definition"),
                int(line.get("current_stock") or 0) < int(line.get("quantity") or 0),
            ),
        }
        for line in list(context["lines"])
        if str(line.get("record_id") or "")
    ]
    allocation_result = (
        apply_inventory_allocation_schedule(
            request_id,
            allocation_plans,
            operator_open_id,
            str(draft.get("generation_key") or f"allocation:{request_id}:{expected_version}"),
            validated_line_ids={str(line.get("record_id") or "") for line in list(context["lines"])},
        )
        if allocation_plans and not already_confirmed
        else {}
    )
    if already_confirmed:
        if ship_date not in (None, ""):
            feishu_update_record_fields(
                REQUEST_TABLE_NAME,
                request_id,
                {SHIP_DATE: date_ms(ship_date)},
            )
            sync_request_ship_date_to_schedule(request_id, ship_date)
        notification_count = notify_enabled_admins_of_material_request(
            str(request.get("request_no") or ""),
            request,
            list(context.get("lines") or []),
        )
        return {
            "request_no": request.get("request_no"),
            "already_confirmed": True,
            "repaired_line_count": updated_line_count,
            "recovered_notifications": True,
            "notification_count": notification_count,
        }
    now = datetime.now()
    request_updates: dict[str, object] = {
        "库存审查状态": INVENTORY_REVIEW_CONFIRMED,
        "库存审查结论": str(context["result"]),
        "物料明细文字信息": request_material_detail_text(list(context["lines"])),
        "库存审查时间": feishu_datetime_value(REQUEST_TABLE_NAME, "库存审查时间", now),
        "申请物料最后修改时间": feishu_datetime_value(
            REQUEST_TABLE_NAME,
            "申请物料最后修改时间",
            now,
        ),
        "库存快照时间": feishu_datetime_value(REQUEST_TABLE_NAME, "库存快照时间", now),
        INVENTORY_REVIEW_REMINDER_STATUS_FIELD: INVENTORY_REVIEW_REMINDER_NONE,
    }
    if ship_date not in (None, ""):
        request_updates[SHIP_DATE] = date_ms(ship_date)
    person_value = _request_review_person_value(operator_open_id)
    if person_value:
        request_updates["库存审查人"] = person_value
        request_updates["申请物料最后修改人"] = person_value
    feishu_update_record_fields(REQUEST_TABLE_NAME, request_id, request_updates)
    if ship_date not in (None, ""):
        sync_request_ship_date_to_schedule(request_id, ship_date)
    notify_enabled_admins_of_material_request(
        str(request.get("request_no") or ""), request, list(context["lines"])
    )
    return {
        "request_no": request.get("request_no"),
        "result": context["result"],
        "confirmed": True,
        **allocation_result,
    }


def notify_requester_of_inventory_rejection(request: dict[str, object]) -> int:
    requester_open_id = str(request.get("requester_open_id") or "").strip()
    if not requester_open_id:
        raise RuntimeError("申请单未记录申请人 OpenID，无法发送驳回通知。")
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送申请驳回通知。")
    send_feishu_interactive_message(
        client,
        requester_open_id,
        material_request_rejection_card(
            str(request.get("request_no") or ""),
            str(request.get("requester") or "申请人"),
        ),
    )
    return 1


def execute_request_inventory_reject(draft: dict[str, object]) -> dict[str, object]:
    request_id = str(draft.get("request_id") or "").strip()
    expected_version = int(draft.get("expected_version") or 0)
    operator_open_id = str(draft.get("operator_open_id") or "").strip()
    if operator_open_id not in enabled_admin_open_ids():
        raise PermissionError("只有已启用管理员可以驳回库存核实申请。")
    context = request_inventory_review_context(request_id=request_id)
    request = dict(context["request"])
    if str(request.get("status") or "") != REQUEST_STATUS_PENDING:
        raise RuntimeError("只有待审批申请可以驳回。")
    if str(request.get("inventory_review_status") or "") == INVENTORY_REVIEW_CONFIRMED:
        raise RuntimeError("该申请已经完成库存核实，不能驳回。")
    if int(request.get("inventory_review_version") or 0) != expected_version:
        raise RuntimeError("申请已发生修改，请查看最新卡片后再驳回。")
    line_ids = [
        str(line.get("record_id") or "")
        for line in list(context.get("lines") or [])
        if str(line.get("record_id") or "")
    ]
    deleted_lines = feishu_batch_delete_record_ids(REQUEST_LINE_TABLE_NAME, line_ids)
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法删除申请单。")
    client.delete_record(feishu_table_id(REQUEST_TABLE_NAME), request_id)
    notify_requester_of_inventory_rejection(request)
    return {
        "request_no": request.get("request_no"),
        "requester": request.get("requester"),
        "deleted_request_id": request_id,
        "deleted_line_count": deleted_lines,
        "rejected": True,
    }


def transaction_request_context_indexes() -> tuple[
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    request_by_id: dict[str, dict[str, str]] = {}
    request_by_no: dict[str, dict[str, str]] = {}
    for request_record in load_feishu_request_records():
        context = {
            "request_no": str(request_record.get("request_no") or ""),
            "requester": str(request_record.get("requester") or ""),
        }
        request_id = str(request_record.get("record_id") or "")
        if request_id:
            request_by_id[request_id] = context
        if context["request_no"]:
            request_by_no[context["request_no"]] = context

    line_context_by_id: dict[str, dict[str, str]] = {}
    for line_record in load_feishu_request_line_records():
        context: dict[str, str] | None = None
        for request_id in line_record.get("request_ids", []):
            context = request_by_id.get(str(request_id))
            if context:
                break
        if context is None:
            context = request_by_no.get(str(line_record.get("request_no") or ""))
        line_id = str(line_record.get("record_id") or "")
        if line_id and context:
            line_context_by_id[line_id] = context
    return request_by_id, request_by_no, line_context_by_id


def transaction_source_context(
    fields: dict,
    request_by_id: dict[str, dict[str, str]],
    request_by_no: dict[str, dict[str, str]],
    line_context_by_id: dict[str, dict[str, str]],
) -> dict[str, str]:
    for request_id in feishu_link_ids_any(fields, ["关联申请单"]):
        if str(request_id) in request_by_id:
            return request_by_id[str(request_id)]
    for line_id in feishu_link_ids_any(fields, ["关联申请明细", "关联明细"]):
        if str(line_id) in line_context_by_id:
            return line_context_by_id[str(line_id)]
    request_no = feishu_text_any(fields, ["关联申请单号", "关联申请单"])
    return request_by_no.get(request_no, {})


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
    request_by_id, request_by_no, line_context_by_id = transaction_request_context_indexes()
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
        request_context = transaction_source_context(
            fields,
            request_by_id,
            request_by_no,
            line_context_by_id,
        )
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
                "request_no": request_context.get("request_no", ""),
                "requester": request_context.get("requester", ""),
            }
        )
    record_by_id = {str(item["record_id"]): item for item in records}
    for item in records:
        original = record_by_id.get(str(item.get("reversal_of") or ""))
        if original and not item["request_no"]:
            item["request_no"] = original.get("request_no", "")
            item["requester"] = original.get("requester", "")
        if item["request_no"] and not item["requester"]:
            item["requester"] = "未填写申请人"
        elif not item["request_no"]:
            item["requester"] = "非申请记录"
    records.sort(key=lambda item: item["created_sort"], reverse=True)
    return records[:limit]


def parse_feishu_inventory_record(
    row: dict,
    *,
    category_override: str = "",
) -> dict | None:
    fields = feishu_fields(row)
    if not fields:
        return None
    material_code = feishu_text(fields, "物料编码")
    category = category_override.strip() or feishu_text(fields, "物料品类")
    if not material_code or not category:
        return None
    quantity = feishu_int(fields, "当前库存")
    in_transit_quantity = feishu_int(fields, "在途库存")
    unit_price = feishu_float_any(fields, list(UNIT_PRICE_FIELD_CANDIDATES))
    return {
        "record_id": feishu_record_id(row),
        "material_code": material_code,
        "category": category,
        "model": feishu_text(fields, "产品型号") or NO_MODEL_TEXT,
        "language": feishu_text(fields, "语种"),
        "quantity": quantity,
        "in_transit_quantity": in_transit_quantity,
        "unit_price": unit_price,
        "total_value": quantity * unit_price,
        "remark": feishu_text(fields, "备注"),
        "customs_code": feishu_text(fields, "海关编码"),
        "status": normalize_enabled_status(feishu_text(fields, "启用状态")),
        "request_visible": normalize_request_page_visibility(
            feishu_text(fields, REQUEST_PAGE_VISIBILITY_FIELD)
        ),
    }


def feishu_inventory_records_from_rows(
    material_rows: list[dict],
    category_rows: list[dict] | None = None,
    *,
    active_only: bool = False,
) -> list[dict]:
    category_records = feishu_category_records_from_rows(list(category_rows or []))
    category_by_id = {
        str(category.get("record_id") or ""): str(category.get("category") or "")
        for category in category_records
        if str(category.get("record_id") or "")
    }
    records: list[dict] = []
    for row in material_rows:
        linked_category = next(
            (
                category_by_id[record_id]
                for record_id in feishu_link_ids(feishu_fields(row), "品类关联")
                if record_id in category_by_id
            ),
            "",
        )
        parsed = parse_feishu_inventory_record(
            row,
            category_override=linked_category,
        )
        if parsed is not None:
            records.append(parsed)
    records.sort(key=lambda item: (item["category"], item["model"], item["language"], item["material_code"]))
    return records


def load_feishu_inventory_records(*, active_only: bool = False) -> list[dict]:
    return feishu_inventory_records_from_rows(
        feishu_material_rows(),
        feishu_category_rows(),
        active_only=active_only,
    )


def feishu_category_records_from_rows(rows: list[dict]) -> list[dict]:
    records: list[dict] = []
    for row in rows:
        fields = feishu_fields(row)
        product = feishu_text(fields, "物料品类")
        if not product:
            continue
        unit_price_text = feishu_text_any(fields, list(UNIT_PRICE_FIELD_CANDIDATES))
        records.append(
            {
                "record_id": feishu_record_id(row),
                "category": product,
                "zh_page_name": feishu_text(fields, "中文页面名称").strip() or product,
                "en_page_name": feishu_text(fields, "英文页面名称").strip() or product,
                "category_definition": feishu_text(fields, "品类定义"),
                "commercial_invoice_name": feishu_text(
                    fields, COMMERCIAL_INVOICE_NAME_FIELD
                ),
                "packing_list_product_type": feishu_text(
                    fields, PACKING_LIST_PRODUCT_TYPE_FIELD
                ),
                "no_model": feishu_text(fields, "是否无需型号") == "是",
                "no_language": feishu_text(fields, "是否无需语种") == "是"
                or (
                    not feishu_text(fields, "是否无需语种")
                    and is_default_no_language_product(product)
                ),
                "status": normalize_enabled_status(feishu_text(fields, "启用状态")),
                "request_visible": normalize_request_page_visibility(
                    feishu_text(fields, REQUEST_PAGE_VISIBILITY_FIELD)
                ),
                "unit_price": parse_optional_unit_price(unit_price_text),
                "unit_price_rmb": feishu_float(fields, UNIT_PRICE_RMB_FIELD),
                "customs_code": feishu_text(fields, "海关编码"),
                "created_at": feishu_text(fields, "创建时间"),
                "remark": feishu_text(fields, "备注"),
            }
        )
    records.sort(key=lambda item: item["category"])
    return records


def load_feishu_category_records() -> list[dict]:
    return feishu_category_records_from_rows(feishu_category_rows())


def category_pool_summary(
    categories: list[dict],
    inventory_records: list[dict],
) -> list[dict[str, object]]:
    inventory_by_category: dict[str, list[dict]] = {}
    for record in inventory_records:
        inventory_by_category.setdefault(str(record.get("category") or ""), []).append(record)
    return [
        {
            "value": str(category.get("category") or ""),
            "label": str(category.get("category") or ""),
            "group": (
                CATEGORY_DEFINITION_GIFT
                if str(category.get("category_definition") or "").strip()
                == CATEGORY_DEFINITION_GIFT
                else CATEGORY_DEFINITION_PRINT
            ),
            "meta": (
                f"{len(inventory_by_category.get(str(category.get('category') or ''), []))} {ui_text('行')}"
                f" · {ui_text('库存')} {sum(int(record.get('quantity') or 0) for record in inventory_by_category.get(str(category.get('category') or ''), []))}"
                f" · {ui_text(normalize_enabled_status(category.get('status')))}"
            ),
        }
        for category in categories
        if str(category.get("category") or "")
    ]


def category_model_pool_summary(records: list[dict]) -> list[dict[str, object]]:
    records_by_model: dict[str, list[dict]] = {}
    for record in records:
        model = str(record.get("model") or NO_MODEL_TEXT)
        records_by_model.setdefault(model, []).append(record)
    return [
        {
            "value": model,
            "label": model,
            "meta": (
                f"{len(model_records)} {ui_text('个语种')}"
                f" · {ui_text('库存')} {sum(int(record.get('quantity') or 0) for record in model_records)}"
            ),
        }
        for model, model_records in records_by_model.items()
    ]


def category_material_pool_summary(records: list[dict]) -> list[dict[str, object]]:
    return [
        {
            "value": str(record.get("record_id") or ""),
            "label": str(record.get("language") or NO_LANGUAGE_TEXT),
            "meta": (
                f"{str(record.get('material_code') or '未编码')}"
                f" · {ui_text('库存')} {int(record.get('quantity') or 0)}"
                f" · {ui_text(normalize_enabled_status(record.get('status')))}"
            ),
        }
        for record in records
        if str(record.get("record_id") or "")
    ]


def category_language_pool_summary(records: list[dict]) -> list[dict[str, object]]:
    records_by_language: dict[str, list[dict]] = {}
    for record in records:
        language = str(record.get("language") or NO_LANGUAGE_TEXT)
        records_by_language.setdefault(language, []).append(record)
    return [
        {
            "value": language,
            "label": language,
            "meta": (
                f"{len(unique_preserve([str(record.get('model') or NO_MODEL_TEXT) for record in language_records]))} {ui_text('个型号')}"
                f" · {ui_text('库存')} {sum(int(record.get('quantity') or 0) for record in language_records)}"
            ),
        }
        for language, language_records in records_by_language.items()
    ]


def render_category_option_pool(
    options: list[dict[str, object]],
    *,
    selected: str | list[str] | None,
    key: str,
    multi: bool = False,
    editable: bool = False,
    danger: bool = False,
    compact: bool = False,
    grouped: bool = False,
) -> tuple[str | list[str] | None, str]:
    selection_state_key = f"{key}_selection"
    current_selected = st.session_state.get(selection_state_key, selected)
    result = CATEGORY_OPTION_POOL(
        key=key,
        data={
            "options": [
                {
                    "value": str(option.get("value") or ""),
                    "label": escape(str(option.get("label") or "")),
                    "meta": escape(str(option.get("meta") or "")),
                    "group": escape(str(option.get("group") or "")),
                }
                for option in options
            ],
            "selected": current_selected,
            "multi": multi,
            "editable": editable,
            "danger": danger,
            "compact": compact,
            "grouped": grouped,
            "group_order": list(CATEGORY_DEFINITION_OPTIONS) if grouped else [],
        },
        on_selected_change=lambda: None,
        on_edit_change=lambda: None,
    )
    next_selected = getattr(result, "selected", None)
    valid_values = {str(option.get("value") or "") for option in options}
    if multi:
        normalized_selected: str | list[str] | None = [
            str(value)
            for value in list(next_selected or [])
            if str(value) in valid_values
        ]
    else:
        candidate = str(next_selected or current_selected or "")
        normalized_selected = candidate if candidate in valid_values else None
    st.session_state[selection_state_key] = normalized_selected
    return normalized_selected, str(getattr(result, "edit", "") or "")


def parse_gift_project_record(row: dict) -> dict | None:
    fields = feishu_fields(row)
    project_name = feishu_text(fields, "项目名称").strip()
    material_name = feishu_text(fields, "物料名称").strip()
    if not project_name and not material_name:
        return None
    return {
        "record_id": feishu_record_id(row),
        "project_name": project_name,
        "material_name": material_name,
        "status": feishu_text(fields, "物料状态").strip(),
        "category_ids": feishu_link_ids(fields, GIFT_PROJECT_CATEGORY_LINK_FIELD),
        "category_link_texts": feishu_link_texts(fields, GIFT_PROJECT_CATEGORY_LINK_FIELD),
        "attachments": feishu_attachment_items(fields, "物料图片"),
        "supplier_contact": feishu_text(fields, "供应商联系方式").strip(),
        "remark": feishu_text(fields, "备注").strip(),
    }


def gift_project_records_from_rows(rows: list[dict]) -> list[dict]:
    return [
        parsed
        for row in rows
        if (parsed := parse_gift_project_record(row)) is not None
    ]


def gift_category_candidates_from_material_rows(
    material_rows: list[dict],
    categories_by_id: dict[str, dict],
    category_by_name: dict[str, dict],
) -> dict[str, list[dict]]:
    candidates_by_material_name: dict[str, list[dict]] = {}
    for row in material_rows:
        fields = feishu_fields(row)
        material_name = feishu_text(fields, "物料品类").strip()
        if not material_name:
            continue
        candidates: list[dict] = []
        for category_id in feishu_link_ids(fields, "品类关联"):
            category = categories_by_id.get(category_id)
            if category is not None:
                candidates.append(category)
        name_match = category_by_name.get(normalize_category_match_key(material_name))
        if name_match is not None:
            candidates.append(name_match)
        if not candidates:
            continue
        material_key = normalize_category_match_key(material_name)
        candidates_by_material_name.setdefault(material_key, [])
        candidates_by_material_name[material_key] = unique_gift_categories(
            [*candidates_by_material_name[material_key], *candidates]
        )
    return candidates_by_material_name


def unique_gift_categories(categories: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for category in categories:
        category_id = str(category.get("record_id") or "")
        if not category_id or category_id in seen:
            continue
        result.append(category)
        seen.add(category_id)
    return result


def gift_project_related_categories(
    project: dict,
    categories_by_id: dict[str, dict],
    category_by_name: dict[str, dict],
    categories_by_material_name: dict[str, list[dict]],
) -> list[dict]:
    candidates: list[dict] = []
    for category_id in list(project.get("category_ids") or []):
        category = categories_by_id.get(str(category_id))
        if category is not None:
            candidates.append(category)
    for link_text in list(project.get("category_link_texts") or []):
        category = category_by_name.get(normalize_category_match_key(link_text))
        if category is not None:
            candidates.append(category)

    material_key = normalize_category_match_key(project.get("material_name"))
    candidates.extend(categories_by_material_name.get(material_key, []))
    category = category_by_name.get(material_key)
    if category is not None:
        candidates.append(category)
    return unique_gift_categories(candidates)


def normalize_gift_category_fuzzy_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", normalize_option_label(value))
    normalized = re.sub(r"[A-Za-z0-9]+", "", normalized)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized).casefold()


def ranked_gift_category_fuzzy_matches(
    project_name: object,
    categories: list[dict],
) -> list[tuple[float, dict]]:
    project_key = normalize_gift_category_fuzzy_key(project_name)
    if len(project_key) < 4:
        return []
    scored: list[tuple[float, dict]] = []
    project_chars = set(project_key)
    for category in categories:
        category_key = normalize_gift_category_fuzzy_key(category.get("category"))
        if len(category_key) < 4:
            continue
        if project_key == category_key:
            score = 1.0
        elif project_key in category_key or category_key in project_key:
            score = min(len(project_key), len(category_key)) / max(len(project_key), len(category_key))
        else:
            category_chars = set(category_key)
            shared_chars = project_chars & category_chars
            if not shared_chars:
                continue
            coverage = len(shared_chars) / max(len(category_chars), 1)
            jaccard = len(shared_chars) / max(len(project_chars | category_chars), 1)
            sequence_ratio = SequenceMatcher(None, project_key, category_key).ratio()
            score = 0.55 * coverage + 0.25 * jaccard + 0.2 * sequence_ratio
        if score >= 0.74:
            scored.append((score, category))
    scored.sort(
        key=lambda item: (
            item[0],
            len(normalize_category_match_key(item[1].get("category"))),
        ),
        reverse=True,
    )
    return scored


def best_gift_category_fuzzy_match(project_name: object, categories: list[dict]) -> dict | None:
    scored = ranked_gift_category_fuzzy_matches(project_name, categories)
    if not scored:
        return None
    best_score, best_category = scored[0]
    if len(scored) > 1 and best_score - scored[1][0] < 0.12:
        return None
    return best_category


def gift_project_catalog_context(
    category_rows: list[dict],
    material_rows: list[dict] | None = None,
) -> dict[str, object]:
    categories = [
        category
        for category in feishu_category_records_from_rows(category_rows)
        if category["category_definition"] == CATEGORY_DEFINITION_GIFT
    ]
    categories_by_id = {
        str(category.get("record_id") or ""): category
        for category in categories
        if str(category.get("record_id") or "")
    }
    category_by_name = {
        normalize_category_match_key(category.get("category")): category
        for category in categories
        if normalize_category_match_key(category.get("category"))
    }
    categories_by_material_name = gift_category_candidates_from_material_rows(
        list(material_rows or []),
        categories_by_id,
        category_by_name,
    )
    return {
        "categories": categories,
        "categories_by_id": categories_by_id,
        "category_by_name": category_by_name,
        "categories_by_material_name": categories_by_material_name,
    }


def gift_project_inferred_categories(
    project: dict,
    context: dict[str, object],
    *,
    allow_fuzzy: bool = True,
) -> list[dict]:
    related_categories = gift_project_related_categories(
        project,
        dict(context["categories_by_id"]),  # type: ignore[arg-type]
        dict(context["category_by_name"]),  # type: ignore[arg-type]
        dict(context["categories_by_material_name"]),  # type: ignore[arg-type]
    )
    if related_categories or not allow_fuzzy:
        return related_categories
    fuzzy_category = best_gift_category_fuzzy_match(
        project.get("material_name"),
        list(context["categories"]),  # type: ignore[arg-type]
    )
    return [fuzzy_category] if fuzzy_category is not None else []


def build_gift_project_category_link_updates(
    category_rows: list[dict],
    material_rows: list[dict],
    project_rows: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    context = gift_project_catalog_context(category_rows, material_rows)
    stats = {
        "project_count": 0,
        "already_linked_count": 0,
        "update_count": 0,
        "unmatched_count": 0,
        "ambiguous_count": 0,
    }
    updates: list[dict] = []
    for project in gift_project_records_from_rows(project_rows):
        stats["project_count"] += 1
        if project.get("category_ids"):
            stats["already_linked_count"] += 1
            continue
        related_categories = gift_project_inferred_categories(project, context)
        if not related_categories:
            fuzzy_matches = ranked_gift_category_fuzzy_matches(
                project.get("material_name"),
                list(context["categories"]),  # type: ignore[arg-type]
            )
            if len(fuzzy_matches) > 1 and fuzzy_matches[0][0] - fuzzy_matches[1][0] < 0.12:
                stats["ambiguous_count"] += 1
            else:
                stats["unmatched_count"] += 1
            continue
        if len(related_categories) > 1:
            stats["ambiguous_count"] += 1
            continue
        category_id = str(related_categories[0].get("record_id") or "")
        project_id = str(project.get("record_id") or "")
        if not category_id or not project_id:
            stats["unmatched_count"] += 1
            continue
        updates.append(
            {
                "record_id": project_id,
                "fields": {GIFT_PROJECT_CATEGORY_LINK_FIELD: [category_id]},
            }
        )
        stats["update_count"] += 1
    return updates, stats


def sync_feishu_gift_project_category_links() -> dict[str, int]:
    if not feishu_has_field(GIFT_PROJECT_TABLE_NAME, GIFT_PROJECT_CATEGORY_LINK_FIELD):
        raise RuntimeError(f"飞书项目周边礼品表缺少字段：{GIFT_PROJECT_CATEGORY_LINK_FIELD}")
    if feishu_field_type(GIFT_PROJECT_TABLE_NAME, GIFT_PROJECT_CATEGORY_LINK_FIELD) not in {18, 21}:
        raise RuntimeError(f"飞书字段不是关联字段：{GIFT_PROJECT_CATEGORY_LINK_FIELD}")

    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    project_rows = fresh_feishu_rows(GIFT_PROJECT_TABLE_NAME)
    updates, stats = build_gift_project_category_link_updates(
        category_rows,
        material_rows,
        project_rows,
    )
    stats["written_count"] = feishu_batch_update_record_fields(
        GIFT_PROJECT_TABLE_NAME,
        updates,
    )
    return stats


GIFT_PROJECT_PROGRESS_STAGES = (
    "已提需",
    "寻源中",
    "待确认下单",
    "设计制作中",
    "到货",
    "已发货",
)

GIFT_PROJECT_STAGE_CLASSES = {
    "已提需": "requested",
    "寻源中": "sourcing",
    "待确认下单": "confirm",
    "设计制作中": "design",
    "到货": "arrived",
    "已发货": "shipped",
}


def gift_project_progress_stage(status: object) -> str:
    value = str(status or "").strip()
    if "发货" in value:
        return "已发货"
    if any(token in value for token in ("到货", "库存")):
        return "到货"
    if any(token in value for token in ("设计", "制作", "生产")):
        return "设计制作中"
    if any(token in value for token in ("确认", "下单")):
        return "待确认下单"
    if any(token in value for token in ("寻源", "询价")):
        return "寻源中"
    return "已提需"


def gift_gallery_records_from_rows(
    category_rows: list[dict],
    project_rows: list[dict],
    material_rows: list[dict] | None = None,
) -> list[dict]:
    context = gift_project_catalog_context(category_rows, material_rows)
    categories = list(context["categories"])  # type: ignore[arg-type]
    projects = gift_project_records_from_rows(project_rows)
    gallery: list[dict] = []
    for category in categories:
        category_id = str(category.get("record_id") or "")
        related_projects = [
            project
            for project in projects
            if category_id
            in {
                str(item.get("record_id") or "")
                for item in gift_project_inferred_categories(project, context)
            }
        ]
        attachments: list[dict[str, str]] = []
        attachment_tokens: set[str] = set()
        for project in related_projects:
            for attachment in list(project.get("attachments") or []):
                file_token = str(attachment.get("file_token") or "")
                if file_token and file_token not in attachment_tokens:
                    attachments.append(dict(attachment))
                    attachment_tokens.add(file_token)
        gallery.append(
            {
                **category,
                "projects": related_projects,
                "attachments": attachments,
                "search_text": " ".join(
                    [
                        str(category.get("category") or ""),
                        str(category.get("remark") or ""),
                        *[
                            " ".join(
                                [
                                    str(project.get("project_name") or ""),
                                    str(project.get("status") or ""),
                                    str(project.get("remark") or ""),
                                ]
                            )
                            for project in related_projects
                        ],
                    ]
                ).casefold(),
            }
        )
    return gallery


def filter_gift_gallery_records(records: list[dict], query: object) -> list[dict]:
    keywords = [
        keyword.casefold()
        for keyword in re.split(r"\s+", str(query or "").strip())
        if keyword.strip()
    ]
    if not keywords:
        return list(records)
    return [
        record
        for record in records
        if all(keyword in str(record.get("search_text") or "") for keyword in keywords)
    ]


def gift_project_management_records(
    category_rows: list[dict],
    project_rows: list[dict],
    material_rows: list[dict] | None = None,
) -> list[dict]:
    context = gift_project_catalog_context(category_rows, material_rows)
    records: list[dict] = []
    for project in gift_project_records_from_rows(project_rows):
        related_categories = gift_project_inferred_categories(project, context)
        category = related_categories[0] if related_categories else None
        unit_price = float((category or {}).get("unit_price") or 0)
        unit_price_rmb = float((category or {}).get("unit_price_rmb") or 0)
        records.append(
            {
                **project,
                "matched_category_id": str((category or {}).get("record_id") or ""),
                "category": str((category or {}).get("category") or project.get("material_name") or ""),
                "unit_price": unit_price,
                "unit_price_rmb": unit_price_rmb or unit_price * 6.77,
                "category_status": str((category or {}).get("status") or ""),
            }
        )
    records.sort(
        key=lambda item: (
            str(item.get("project_name") or "未命名项目"),
            str(item.get("material_name") or ""),
        )
    )
    return records


def build_gift_project_fields(
    project_name: object,
    material_name: object,
    category_record_id: object,
    *,
    owner: object = "",
    owner_open_id: object = "",
    remark: object = "",
    attachment_token: object = "",
) -> dict[str, object]:
    project = str(project_name or "").strip()
    material = str(material_name or "").strip()
    category_id = str(category_record_id or "").strip()
    if not project:
        raise ValueError("请填写项目名称。")
    if not material or not category_id:
        raise ValueError("请选择有效的周边礼品。")
    fields: dict[str, object] = {
        "项目名称": project,
        "物料名称": material,
        "物料状态": GIFT_PROJECT_STATUS_REQUESTED,
        "物料品类关联": [category_id],
        "备注": str(remark or "").strip(),
    }
    responsible = str(owner or "").strip()
    responsible_open_id = str(owner_open_id or "").strip()
    if responsible_open_id:
        if not responsible_open_id.startswith("ou_"):
            raise ValueError("负责人通讯录 ID 无效，请重新选择负责人。")
        fields["负责人"] = [{"id": responsible_open_id}]
    elif responsible:
        if feishu_field_type(GIFT_PROJECT_TABLE_NAME, "负责人") == 11:
            raise ValueError("负责人必须从飞书通讯录中选择，不能直接填写姓名。")
        fields["负责人"] = responsible
    file_token = str(attachment_token or "").strip()
    if file_token:
        fields["物料图片"] = [{"file_token": file_token}]
    return fields


def upload_gift_project_attachment(uploaded_file: object | None) -> str:
    if uploaded_file is None:
        return ""
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法上传物料图片。")
    file_name = str(getattr(uploaded_file, "name", "") or "").strip()
    content = bytes(uploaded_file.getvalue())  # type: ignore[attr-defined]
    content_type = str(
        getattr(uploaded_file, "type", "") or "application/octet-stream"
    )
    return client.upload_media(file_name, content, content_type)


def create_gift_project_request(
    project_name: object,
    category_record_id: object,
    *,
    owner: object = "",
    owner_open_id: object = "",
    remark: object = "",
    attachment_token: object = "",
) -> dict:
    created = create_gift_project_requests_batch(
        project_name,
        [category_record_id],
        owner=owner,
        owner_open_id=owner_open_id,
        remark=remark,
        attachment_token=attachment_token,
    )
    return created[0]


def create_gift_project_requests_batch(
    project_name: object,
    category_record_ids: list[object],
    *,
    owner: object = "",
    owner_open_id: object = "",
    remark: object = "",
    attachment_token: object = "",
) -> list[dict]:
    category_ids = unique_preserve(
        [
            str(value or "").strip()
            for value in category_record_ids
            if str(value or "").strip()
        ]
    )
    if not category_ids:
        raise ValueError("请至少选择一个有效的周边礼品。")
    categories = {
        str(item.get("record_id") or ""): item
        for item in feishu_category_records_from_rows(
            fresh_feishu_rows(CATEGORY_TABLE_NAME)
        )
    }
    missing_ids = [
        category_id for category_id in category_ids if category_id not in categories
    ]
    if missing_ids:
        raise ValueError("部分周边礼品不存在，请刷新页面后重新选择。")
    invalid_categories = [
        str(categories[category_id].get("category") or category_id)
        for category_id in category_ids
        if categories[category_id].get("category_definition") != CATEGORY_DEFINITION_GIFT
    ]
    if invalid_categories:
        raise ValueError(
            "以下品类不是周边礼品，不能写入项目礼品申请："
            + "、".join(invalid_categories)
        )
    records = [
        build_gift_project_fields(
            project_name,
            categories[category_id].get("category"),
            category_id,
            owner=owner,
            owner_open_id=owner_open_id,
            remark=remark,
            attachment_token=attachment_token,
        )
        for category_id in category_ids
    ]
    created = feishu_batch_create_records(GIFT_PROJECT_TABLE_NAME, records)
    if len(created) != len(records):
        raise RuntimeError(
            f"项目周边礼品需求应写入 {len(records)} 条，飞书仅返回 {len(created)} 条。"
        )
    return created


def build_category_inventory_plan(
    records: list[dict],
    target_product: str,
    target_models: list[str],
    target_languages: list[str],
    *,
    model_renames: dict[str, str] | None = None,
    language_renames: dict[str, str] | None = None,
    carry_model: str = "",
    carry_language: str = "",
    initial_quantities: dict[tuple[str, str], int] | None = None,
    target_values: dict[tuple[str, str], dict[str, object]] | None = None,
    default_request_visible: str = REQUEST_PAGE_VISIBLE_VALUE,
    referenced_ids: set[str] | None = None,
) -> dict:
    product = target_product.strip()
    models = unique_preserve([str(value).strip() for value in target_models if str(value).strip()])
    languages = unique_preserve([str(value).strip() for value in target_languages if str(value).strip()])
    if not product:
        raise ValueError("物料品类名称不能为空。")
    if not models:
        raise ValueError("目标产品型号不能为空。")
    if not languages:
        raise ValueError("目标语种不能为空。")

    model_renames = {
        str(source).strip(): str(target).strip()
        for source, target in (model_renames or {}).items()
        if str(source).strip() and str(target).strip() and str(source).strip() != str(target).strip()
    }
    language_renames = {
        str(source).strip(): str(target).strip()
        for source, target in (language_renames or {}).items()
        if str(source).strip()
        and str(target).strip()
        and str(source).strip() != str(target).strip()
    }
    carry_model = carry_model.strip() or models[0]
    carry_language = carry_language.strip() or languages[0]
    if carry_model not in models:
        raise ValueError("承接库存的产品型号必须包含在目标型号中。")
    if carry_language not in languages:
        raise ValueError("承接库存的语种必须包含在目标语种中。")

    grouped: dict[tuple[str, str], list[dict]] = {}
    for source in records:
        source_model = str(source.get("model") or NO_MODEL_TEXT).strip() or NO_MODEL_TEXT
        source_language = str(source.get("language") or "").strip()
        renamed_source_model = model_renames.get(source_model, source_model)
        renamed_source_language = language_renames.get(source_language, source_language)
        target_model = renamed_source_model if renamed_source_model in models else carry_model
        target_language = (
            renamed_source_language
            if renamed_source_language in languages
            else carry_language
        )
        grouped.setdefault((target_model, target_language), []).append(dict(source))

    initial_quantities = initial_quantities or {}
    target_values = target_values or {}
    referenced_ids = referenced_ids or set()
    targets: list[dict] = []
    source_to_target_key: dict[str, tuple[str, str]] = {}
    delete_ids: list[str] = []
    merge_count = 0

    for model in models:
        for language in languages:
            key = (model, language)
            sources = grouped.get(key, [])
            keeper: dict | None = None
            if sources:
                keeper = min(
                    sources,
                    key=lambda item: (
                        0 if str(item.get("record_id") or "") in referenced_ids else 1,
                        0 if int(item.get("quantity") or 0) != 0 else 1,
                        str(item.get("material_code") or ""),
                    ),
                )
                if len(sources) > 1:
                    merge_count += len(sources) - 1

            quantity = (
                sum(int(item.get("quantity") or 0) for item in sources)
                if sources
                else int(initial_quantities.get(key, 0) or 0)
            )
            total_value = sum(
                int(item.get("quantity") or 0) * float(item.get("unit_price") or 0)
                for item in sources
            )
            if sources and quantity:
                unit_price = total_value / quantity
            elif keeper is not None:
                unit_price = float(keeper.get("unit_price") or 0)
            else:
                unit_price = 0.0

            remarks = unique_preserve(
                [str(item.get("remark") or "").strip() for item in sources if str(item.get("remark") or "").strip()]
            )
            customs_values = unique_preserve(
                [
                    str(item.get("customs_code") or "").strip()
                    for item in sources
                    if str(item.get("customs_code") or "").strip()
                ]
            )
            customs_code = (
                str((keeper or {}).get("customs_code") or "").strip()
                or (customs_values[0] if customs_values else "")
            )
            status = (
                STATUS_ACTIVE
                if not sources or any(material_record_is_active(source) for source in sources)
                else STATUS_INACTIVE
            )
            request_visible = (
                normalize_request_page_visibility((keeper or {}).get("request_visible"))
                if keeper is not None
                else normalize_request_page_visibility(default_request_visible)
            )
            override = dict(target_values.get(key) or {})
            override_quantity = override.get("quantity")
            if override_quantity is not None and not pd.isna(override_quantity):
                quantity = int(override_quantity)
            override_unit_price = override.get("unit_price")
            if override_unit_price is not None and not pd.isna(override_unit_price):
                unit_price = float(override_unit_price)
            if "customs_code" in override:
                customs_code = str(override.get("customs_code") or "").strip()
            if "status" in override:
                status = normalize_enabled_status(override.get("status"))
            if "request_visible" in override:
                request_visible = normalize_request_page_visibility(
                    override.get("request_visible")
                )
            keeper_id = str((keeper or {}).get("record_id") or "")
            source_ids = [str(item.get("record_id") or "") for item in sources if item.get("record_id")]
            for source_id in source_ids:
                source_to_target_key[source_id] = key
                if source_id != keeper_id:
                    delete_ids.append(source_id)

            targets.append(
                {
                    "key": key,
                    "product": product,
                    "model": model,
                    "language": language,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "remark": "\n".join(remarks),
                    "customs_code": customs_code,
                    "status": status,
                    "request_visible": request_visible,
                    "material_code": str((keeper or {}).get("material_code") or ""),
                    "keeper_id": keeper_id,
                    "source_ids": source_ids,
                    "is_new": not sources,
                    "action": "新增" if not sources else ("重组" if len(sources) > 1 else "保留"),
                }
            )

    current_quantity = sum(int(record.get("quantity") or 0) for record in records)
    target_quantity = sum(int(target["quantity"] or 0) for target in targets)
    return {
        "product": product,
        "models": models,
        "languages": languages,
        "model_renames": model_renames,
        "language_renames": language_renames,
        "targets": targets,
        "source_to_target_key": source_to_target_key,
        "delete_ids": unique_preserve(delete_ids),
        "current_count": len(records),
        "target_count": len(targets),
        "create_count": sum(1 for target in targets if target["is_new"]),
        "delete_count": len(unique_preserve(delete_ids)),
        "merge_count": merge_count,
        "current_quantity": current_quantity,
        "target_quantity": target_quantity,
        "quantity_difference": target_quantity - current_quantity,
        "discarded_quantity": max(current_quantity - target_quantity, 0),
    }


def category_model_rename_values(editor_df: pd.DataFrame) -> dict[str, str]:
    model_renames: dict[str, str] = {}
    final_names: list[str] = []
    for row in editor_df.to_dict("records"):
        current_model = str(row.get("当前型号") or "").strip()
        updated_model = str(row.get("修改后型号") or "").strip()
        if not current_model:
            continue
        if not updated_model:
            raise ValueError(f"请填写“{current_model}”修改后的型号名称。")
        if updated_model == NO_MODEL_TEXT:
            raise ValueError("如需取消产品型号，请使用“该品类无需产品型号”选项。")
        final_names.append(updated_model)
        if current_model != updated_model:
            model_renames[current_model] = updated_model
    if len(final_names) != len(set(final_names)):
        raise ValueError("修改后的产品型号不能与其他已有型号重名。")
    return model_renames


def category_language_rename_values(editor_df: pd.DataFrame) -> dict[str, str]:
    language_renames: dict[str, str] = {}
    final_names: list[str] = []
    for row in editor_df.to_dict("records"):
        current_language = str(row.get("当前语种") or "").strip()
        updated_language = str(row.get("修改后语种") or "").strip()
        if not current_language:
            continue
        if not updated_language:
            raise ValueError(f"请填写“{current_language}”修改后的语种名称。")
        if updated_language == NO_LANGUAGE_TEXT:
            raise ValueError("如需取消语种，请使用“该品类无需语种”选项。")
        final_names.append(updated_language)
        if current_language != updated_language:
            language_renames[current_language] = updated_language
    if len(final_names) != len(set(final_names)):
        raise ValueError("修改后的语种不能与其他已有语种重名。")
    return language_renames


def category_inventory_target_values(editor_df: pd.DataFrame) -> dict[tuple[str, str], dict[str, object]]:
    values: dict[tuple[str, str], dict[str, object]] = {}
    for row in editor_df.to_dict("records"):
        model = str(row.get("产品型号") or "").strip()
        language = str(row.get("语种") or "").strip()
        quantity = row.get("库存数量")
        if not model or not language:
            raise ValueError("产品型号和语种不能为空。")
        if quantity is None or pd.isna(quantity):
            raise ValueError(f"请填写 {model} / {language} 的库存数量。")
        unit_price = row.get("单价")
        normalized_unit_price = (
            0.0 if unit_price is None or pd.isna(unit_price) else float(unit_price)
        )
        if normalized_unit_price < 0:
            raise ValueError(f"{model} / {language} 的单价不能小于 0。")
        status = normalize_enabled_status(row.get("启用状态"))
        values[(model, language)] = {
            "quantity": int(quantity),
            "unit_price": normalized_unit_price,
            "customs_code": str(row.get("海关编码") or "").strip(),
            "status": status,
        }
        if "申领页显示" in row:
            values[(model, language)]["request_visible"] = (
                normalize_request_page_visibility(row.get("申领页显示"))
            )
    return values


def category_inventory_preview_dataframe(targets: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "操作": "新增",
                "序号": index,
                "产品型号": str(target.get("model") or NO_MODEL_TEXT),
                "语种": str(target.get("language") or NO_LANGUAGE_TEXT),
                "库存数量": int(target.get("quantity") or 0),
                "单价": float(target.get("unit_price") or 0),
                "海关编码": str(target.get("customs_code") or ""),
                "启用状态": normalize_enabled_status(target.get("status")),
                "申领页显示": normalize_request_page_visibility(
                    target.get("request_visible")
                ),
            }
            for index, target in enumerate(targets, start=1)
        ],
        columns=[
            "操作",
            "序号",
            "产品型号",
            "语种",
            "库存数量",
            "单价",
            "海关编码",
            "启用状态",
            "申领页显示",
        ],
    )


def category_inventory_preview_values(
    editor_df: pd.DataFrame,
    expected_keys: list[tuple[str, str]],
    category_status: object,
) -> dict[tuple[str, str], dict[str, object]]:
    values = category_inventory_target_values(editor_df)
    normalized_expected_keys = [
        (str(model).strip(), str(language).strip())
        for model, language in expected_keys
    ]
    if len(values) != len(editor_df) or set(values) != set(normalized_expected_keys):
        raise ValueError("预览库存行与目标型号、语种组合不一致，请返回修改后重新预览。")
    if normalize_enabled_status(category_status) == STATUS_INACTIVE:
        for item in values.values():
            item["status"] = STATUS_INACTIVE
    return values


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


def count_feishu_item_request_lines(
    material_record_id: str,
    product: str,
    model: str,
    language: str,
) -> int:
    count = 0
    for row in feishu_rows(REQUEST_LINE_TABLE_NAME):
        fields = feishu_fields(row)
        linked_ids = feishu_link_ids_any(fields, ["物料", "物料编码"])
        if material_record_id and material_record_id in linked_ids:
            count += 1
            continue
        if (
            not linked_ids
            and feishu_text(fields, "物料品类") == product
            and (feishu_text(fields, "产品型号") or NO_MODEL_TEXT)
            == (model or NO_MODEL_TEXT)
            and (feishu_text(fields, "语种") or NO_LANGUAGE_TEXT)
            == (language or NO_LANGUAGE_TEXT)
        ):
            count += 1
    return count


def count_feishu_category_transactions(product: str) -> int:
    material_ids = {
        feishu_record_id(row)
        for row in feishu_material_rows()
        if feishu_text(feishu_fields(row), "物料品类") == product
    }
    count = 0
    for row in feishu_rows("库存流水"):
        fields = feishu_fields(row)
        if not fields or is_blank_feishu_transaction(fields):
            continue
        if feishu_text(fields, "物料品类") == product or material_ids.intersection(
            feishu_link_ids_any(fields, ["物料编码", "物料"])
        ):
            count += 1
    return count


def count_feishu_category_business_references(
    product: str,
    category_record_id: str,
) -> int:
    material_ids = {
        feishu_record_id(row)
        for row in feishu_material_rows()
        if feishu_text(feishu_fields(row), "物料品类") == product
    }
    count = 0
    for row in feishu_rows(REQUEST_LINE_TABLE_NAME):
        fields = feishu_fields(row)
        if feishu_text(fields, "物料品类") == product or material_ids.intersection(
            feishu_link_ids_any(fields, ["物料", "物料编码"])
        ):
            count += 1
    for row in feishu_rows(GIFT_PROJECT_TABLE_NAME):
        fields = feishu_fields(row)
        if category_record_id in feishu_link_ids(
            fields, GIFT_PROJECT_CATEGORY_LINK_FIELD
        ) or product in feishu_link_texts(fields, GIFT_PROJECT_CATEGORY_LINK_FIELD):
            count += 1
    return count


def get_or_create_feishu_category_record(
    product: str,
    no_model: bool,
    no_language: bool = False,
    category_definition: str = "",
    category_zh_page_name: str = "",
    category_en_page_name: str = "",
) -> dict:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书客户端未初始化。")
    existing = find_feishu_category_record(product)
    category_zh_page_name = category_zh_page_name.strip() or product
    category_en_page_name = category_en_page_name.strip() or product
    if existing is not None:
        updates: dict[str, object] = {
            "中文页面名称": category_zh_page_name,
            "英文页面名称": category_en_page_name,
        }
        if no_model:
            updates["是否无需型号"] = "是"
        if no_language:
            updates["是否无需语种"] = "是"
        if category_definition:
            updates["品类定义"] = category_definition
        if updates:
            feishu_update_record_fields(
                "物料品类",
                feishu_record_id(existing),
                updates,
            )
        return existing
    category_fields: dict[str, object] = {
        "物料品类": product,
        "中文页面名称": category_zh_page_name,
        "英文页面名称": category_en_page_name,
        "是否无需型号": "是" if no_model else "否",
        "是否无需语种": "是" if no_language else "否",
        "启用状态": "启用",
        "库存行数": 0,
        "产品型号数量": 0,
        "语种数量": 0,
        "备注": "",
    }
    if category_definition:
        category_fields["品类定义"] = category_definition
    created = feishu_batch_create_records(
        "物料品类",
        [category_fields],
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
    source_request_id = (feishu_link_ids_any(transaction_fields, ["关联申请单"]) or [""])[0]
    source_line_id = (
        feishu_link_ids_any(transaction_fields, ["关联申请明细", "关联明细"]) or [""]
    )[0]
    source_request_no = feishu_text_any(transaction_fields, ["关联申请单号", "关联申请单"])
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
        source_request_id=source_request_id,
        source_line_id=source_line_id,
        source_request_no=source_request_no,
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
    original_row = find_feishu_transaction_by_id(transaction_record_id)
    original_fields = feishu_fields(original_row or {})
    source_request_id = (feishu_link_ids_any(original_fields, ["关联申请单"]) or [""])[0]
    source_line_id = (
        feishu_link_ids_any(original_fields, ["关联申请明细", "关联明细"]) or [""]
    )[0]
    source_request_no = feishu_text_any(original_fields, ["关联申请单号", "关联申请单"])
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
                    "source_request_id": source_request_id,
                    "source_line_id": source_line_id,
                    "source_request_no": source_request_no,
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
    category_record = get_or_create_feishu_category_record(
        product.strip(),
        model == NO_MODEL_TEXT,
        language.strip() == NO_LANGUAGE_TEXT,
    )
    category_record_id = feishu_record_id(category_record)
    link_field, model_ids = ensure_feishu_model_records([model])
    language_link_field, language_ids = ensure_feishu_language_records([language])
    update_fields: dict[str, object] = {
        "物料编码": material_code.strip(),
        "物料品类": product.strip(),
        "产品型号": model,
        "语种": language.strip(),
        "备注": remark.strip(),
        "品类关联": [category_record_id] if category_record_id else [],
    }
    set_feishu_unit_price(MATERIAL_TABLE_NAME, update_fields, float(unit_price or 0))
    set_feishu_customs_code(MATERIAL_TABLE_NAME, update_fields, customs_code)
    add_material_model_link(update_fields, model, link_field, model_ids)
    add_material_language_link(update_fields, language, language_link_field, language_ids)
    feishu_update_record_fields(MATERIAL_TABLE_NAME, record_id, update_fields)


def delete_feishu_category(product: str, category_record_id: str) -> None:
    client = feishu_client()
    if client is None:
        return
    for row in feishu_material_rows():
        if feishu_text(feishu_fields(row), "物料品类") == product:
            client.delete_record(feishu_table_id("物料主数据"), feishu_record_id(row))
    client.delete_record(feishu_table_id("物料品类"), category_record_id)


def update_feishu_category(
    old_product: str,
    new_product: str,
    no_model: bool,
    no_language: bool,
    category_record_id: str,
) -> None:
    client = feishu_client()
    if client is None:
        return
    new_product = new_product.strip()
    feishu_update_record_fields(
        "物料品类",
        category_record_id,
        {
            "物料品类": new_product,
            "是否无需型号": "是" if no_model else "否",
            "是否无需语种": "是" if no_language else "否",
        },
    )
    category_material_rows = [
        row
        for row in feishu_material_rows()
        if feishu_text(feishu_fields(row), "物料品类") == old_product
    ]
    target_models = [
        NO_MODEL_TEXT if no_model else (feishu_text(feishu_fields(row), "产品型号") or NO_MODEL_TEXT)
        for row in category_material_rows
    ]
    link_field, model_ids = ensure_feishu_model_records(target_models)
    target_languages = [
        NO_LANGUAGE_TEXT if no_language else (feishu_text(feishu_fields(row), "语种") or NO_LANGUAGE_TEXT)
        for row in category_material_rows
    ]
    language_link_field, language_ids = ensure_feishu_language_records(target_languages)
    for row, target_model, target_language in zip(category_material_rows, target_models, target_languages):
        update_fields: dict[str, object] = {
            "物料品类": new_product,
            "品类关联": [category_record_id],
        }
        if no_model:
            update_fields["产品型号"] = NO_MODEL_TEXT
        add_material_model_link(update_fields, target_model, link_field, model_ids)
        if no_language:
            update_fields["语种"] = NO_LANGUAGE_TEXT
        add_material_language_link(update_fields, target_language, language_link_field, language_ids)
        feishu_update_record_fields(MATERIAL_TABLE_NAME, feishu_record_id(row), update_fields)


def next_material_codes_from_records(records: list[dict], count: int) -> list[str]:
    max_number = 0
    for record in records:
        value = str(record.get("material_code") or "")
        match = re.search(r"(\d+)$", value)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return [f"MAT-{number:04d}" for number in range(max_number + 1, max_number + count + 1)]


def build_material_relation_updates(
    rows: list[dict],
    source_to_target_id: dict[str, str],
    relation_fields: list[str],
) -> list[dict]:
    updates: list[dict] = []
    for row in rows:
        fields = feishu_fields(row)
        changed_fields: dict[str, object] = {}
        for field_name in relation_fields:
            old_ids = feishu_link_ids(fields, field_name)
            if not old_ids:
                continue
            new_ids = unique_preserve([source_to_target_id.get(record_id, record_id) for record_id in old_ids])
            if new_ids != old_ids:
                changed_fields[field_name] = new_ids
        if changed_fields:
            updates.append({"record_id": feishu_record_id(row), "fields": changed_fields})
    return updates


def sync_feishu_cultural_category_inventory(
    *, old_product: str, new_product: str, models: list[str], regions: list[str],
    category_record_id: str, category_zh_page_name: str, category_en_page_name: str,
    category_status: str, category_request_visible: str,
    commercial_invoice_name: str, packing_list_product_type: str,
    target_values: dict[tuple[str, str], dict[str, object]],
) -> dict[str, object]:
    """Create or edit a culture category as model x region combinations."""
    if not models or not regions:
        raise ValueError("文化周边品类必须至少选择一个型号和一个战区。")
    category_fields: dict[str, object] = {
        "物料品类": new_product, "中文页面名称": category_zh_page_name,
        "英文页面名称": category_en_page_name, "品类定义": CATEGORY_DEFINITION_CULTURAL,
        "是否无需型号": "否", "是否无需语种": "否", "启用状态": category_status,
        REQUEST_PAGE_VISIBILITY_FIELD: category_request_visible,
    }
    set_shipping_category_fields(category_fields, commercial_invoice_name, packing_list_product_type)
    created_category = False
    if category_record_id:
        feishu_update_record_fields(CATEGORY_TABLE_NAME, category_record_id, category_fields)
    else:
        created = feishu_batch_create_records(CATEGORY_TABLE_NAME, [category_fields])
        category_record_id = feishu_record_id(created[0] if created else {})
        created_category = True
    if not category_record_id:
        raise RuntimeError("创建文化周边品类后未返回记录 ID。")

    current = [item for item in load_cultural_dimension_inventory_records(fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME)) if str(item.get("category") or "") == old_product]
    current_by_key = {(str(item.get("model") or ""), str(item.get("region") or "")): item for item in current}
    target_keys = {(str(model), str(region)) for model in models for region in regions}
    model_ids = {model: _cultural_dimension_record_id(MODEL_TABLE_NAME, "产品型号", model) for model in models}
    missing_models = [model for model, value in model_ids.items() if not value]
    if missing_models:
        raise RuntimeError("以下型号不存在：" + "、".join(missing_models))
    deletes = [str(item.get("record_id") or "") for key, item in current_by_key.items() if key not in target_keys]
    updates: list[dict[str, object]] = []
    creates: list[dict[str, object]] = []
    for key in sorted(target_keys):
        model, region = key
        values = dict(target_values.get(key) or {})
        fields: dict[str, object] = {
            "物料品类": new_product, "产品型号": model, "战区管理": region,
            "物料品类关联": [category_record_id], "产品型号关联": [model_ids[model]],
        }
        existing = current_by_key.get(key)
        if existing:
            fields.update({
                **cultural_stock_fields(values.get("quantity", existing.get("quantity", 0))),
                "单价（人民币）": float(values.get("unit_price", existing.get("unit_price", 0)) or 0),
                "备注": str(existing.get("remark") or ""),
            })
            updates.append({"record_id": str(existing.get("record_id") or ""), "fields": fields})
        else:
            fields.update({"文化周边编码": f"CUL-{uuid.uuid4().hex[:8].upper()}", **cultural_stock_fields(values.get("quantity"), initialize=True), "单价（人民币）": float(values.get("unit_price") or 0), "备注": ""})
            creates.append(fields)
    created_rows = feishu_batch_create_records(CULTURAL_MATERIAL_TABLE_NAME, creates) if creates else []
    updated_count = feishu_batch_update_record_fields(CULTURAL_MATERIAL_TABLE_NAME, updates)
    deleted_count = feishu_batch_delete_record_ids(CULTURAL_MATERIAL_TABLE_NAME, deletes)
    return {"created_category": created_category, "category_record_id": category_record_id, "created_material_count": len(created_rows), "updated_material_count": updated_count, "deleted_material_count": deleted_count, "plan": {"targets": [{"model": model, "language": region, "region": region} for model, region in sorted(target_keys)]}}


def sync_feishu_category_inventory(
    *,
    old_product: str,
    new_product: str,
    no_model: bool,
    no_language: bool,
    target_models: list[str],
    target_languages: list[str],
    category_definition: str = "",
    category_zh_page_name: str = "",
    category_en_page_name: str = "",
    category_status: str = STATUS_ACTIVE,
    category_request_visible: str = REQUEST_PAGE_VISIBLE_VALUE,
    category_unit_price: float | None = None,
    category_customs_code: str = "",
    commercial_invoice_name: str = "",
    packing_list_product_type: str = "",
    category_record_id: str = "",
    model_renames: dict[str, str] | None = None,
    language_renames: dict[str, str] | None = None,
    carry_model: str = "",
    carry_language: str = "",
    initial_quantities: dict[tuple[str, str], int] | None = None,
    target_values: dict[tuple[str, str], dict[str, object]] | None = None,
) -> dict:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书客户端未初始化。")

    old_product = old_product.strip()
    new_product = new_product.strip()
    category_status = normalize_enabled_status(category_status)
    category_request_visible = normalize_request_page_visibility(
        category_request_visible
    )
    category_unit_price = None if category_unit_price is None else float(category_unit_price)
    category_customs_code = category_customs_code.strip()
    commercial_invoice_name = commercial_invoice_name.strip()
    packing_list_product_type = packing_list_product_type.strip()
    if not commercial_invoice_name:
        raise ValueError("商业发票产品名称不能为空。")
    category_definition = category_definition.strip()
    category_zh_page_name = category_zh_page_name.strip() or new_product
    category_en_page_name = category_en_page_name.strip() or new_product
    models = [NO_MODEL_TEXT] if no_model else target_models
    languages = [NO_LANGUAGE_TEXT] if no_language else target_languages

    if category_definition == CATEGORY_DEFINITION_CULTURAL:
        return sync_feishu_cultural_category_inventory(
            old_product=old_product, new_product=new_product,
            models=models, regions=languages,
            category_record_id=category_record_id,
            category_zh_page_name=category_zh_page_name,
            category_en_page_name=category_en_page_name,
            category_status=category_status,
            category_request_visible=category_request_visible,
            commercial_invoice_name=commercial_invoice_name,
            packing_list_product_type=packing_list_product_type,
            target_values=target_values or {},
        )

    category_rows = fresh_feishu_rows("物料品类")
    if category_record_id and not category_definition:
        category_definition = next(
            (
                feishu_text(feishu_fields(row), "品类定义")
                for row in category_rows
                if feishu_record_id(row) == category_record_id
            ),
            "",
        )
    for row in category_rows:
        row_id = feishu_record_id(row)
        row_product = feishu_text(feishu_fields(row), "物料品类")
        if (
            row_product == new_product
            and row_id != category_record_id
            and new_product != old_product
        ):
            raise ValueError("新的物料品类名称已经存在。")

    raw_inventory_rows = fresh_feishu_rows("物料主数据")
    all_inventory = [
        parsed
        for row in raw_inventory_rows
        if (parsed := parse_feishu_inventory_record(row)) is not None
    ]
    source_records = [record for record in all_inventory if record["category"] == old_product] if old_product else []

    relation_sources: list[tuple[str, list[str], list[dict]]] = []
    referenced_ids: set[str] = set()
    for table_name, candidates in (
        ("库存流水", ["物料编码", "物料"]),
        (REQUEST_LINE_TABLE_NAME, ["物料", "物料编码"]),
    ):
        relation_fields = [
            field_name
            for field_name in candidates
            if feishu_has_field(table_name, field_name) and feishu_field_type(table_name, field_name) in {18, 21}
        ]
        rows = fresh_feishu_rows(table_name) if relation_fields else []
        relation_sources.append((table_name, relation_fields, rows))
        for row in rows:
            fields = feishu_fields(row)
            for field_name in relation_fields:
                referenced_ids.update(feishu_link_ids(fields, field_name))

    plan = build_category_inventory_plan(
        source_records,
        new_product,
        models,
        languages,
        model_renames=model_renames,
        language_renames=language_renames,
        carry_model=carry_model,
        carry_language=carry_language,
        initial_quantities=initial_quantities,
        target_values=target_values,
        default_request_visible=category_request_visible,
        referenced_ids=referenced_ids,
    )
    plan = enforce_category_inventory_status(plan, category_status)

    created_category = False
    if not category_record_id:
        category_fields: dict[str, object] = {
            "物料品类": new_product,
            "中文页面名称": category_zh_page_name,
            "英文页面名称": category_en_page_name,
            "是否无需型号": "是" if no_model else "否",
            "是否无需语种": "是" if no_language else "否",
            "启用状态": category_status,
            REQUEST_PAGE_VISIBILITY_FIELD: category_request_visible,
            "库存行数": plan["target_count"],
            "产品型号数量": len(plan["models"]),
            "语种数量": len(plan["languages"]),
            "备注": "",
        }
        if category_definition:
            category_fields["品类定义"] = category_definition
        set_feishu_unit_price(CATEGORY_TABLE_NAME, category_fields, category_unit_price)
        set_feishu_customs_code(CATEGORY_TABLE_NAME, category_fields, category_customs_code)
        set_shipping_category_fields(
            category_fields,
            commercial_invoice_name,
            packing_list_product_type,
        )
        created = feishu_batch_create_records(
            CATEGORY_TABLE_NAME,
            [category_fields],
        )
        category_record_id = feishu_record_id(created[0] if created else {})
        if not category_record_id:
            raise RuntimeError("创建物料品类后未返回记录 ID。")
        created_category = True

    model_link_field, model_record_ids = ensure_feishu_model_records(plan["models"])
    language_link_field, language_record_ids = ensure_feishu_language_records(plan["languages"])
    new_targets = [target for target in plan["targets"] if target["is_new"]]
    new_codes = next_material_codes_from_records(all_inventory, len(new_targets))
    create_fields: list[dict[str, object]] = []
    for target, material_code in zip(new_targets, new_codes):
        target["material_code"] = material_code
        fields: dict[str, object] = {
            "物料编码": material_code,
            "物料品类": new_product,
            "产品型号": target["model"],
            "语种": target["language"],
            "当前库存": int(target["quantity"]),
            "备注": target["remark"],
            "启用状态": target["status"],
            REQUEST_PAGE_VISIBILITY_FIELD: normalize_request_page_visibility(
                target.get("request_visible")
            ),
            "品类关联": [category_record_id],
        }
        set_feishu_unit_price(MATERIAL_TABLE_NAME, fields, float(target["unit_price"]))
        set_feishu_customs_code(MATERIAL_TABLE_NAME, fields, target["customs_code"])
        add_material_model_link(fields, target["model"], model_link_field, model_record_ids)
        add_material_language_link(fields, target["language"], language_link_field, language_record_ids)
        create_fields.append(fields)

    created_material_rows: list[dict] = []
    for start in range(0, len(create_fields), 500):
        created_material_rows.extend(feishu_batch_create_records("物料主数据", create_fields[start : start + 500]))
    if len(created_material_rows) != len(new_targets):
        raise RuntimeError("新增库存组合数量与飞书返回数量不一致，请刷新后重试。")
    for target, created_row in zip(new_targets, created_material_rows):
        target["keeper_id"] = feishu_record_id(created_row)

    keeper_updates: list[dict] = []
    for target in plan["targets"]:
        if target["is_new"]:
            continue
        fields = {
            "物料品类": new_product,
            "产品型号": target["model"],
            "语种": target["language"],
            "当前库存": int(target["quantity"]),
            "备注": target["remark"],
            "启用状态": target["status"],
            REQUEST_PAGE_VISIBILITY_FIELD: normalize_request_page_visibility(
                target.get("request_visible")
            ),
            "品类关联": [category_record_id],
        }
        set_feishu_unit_price(MATERIAL_TABLE_NAME, fields, float(target["unit_price"]))
        set_feishu_customs_code(MATERIAL_TABLE_NAME, fields, target["customs_code"])
        add_material_model_link(fields, target["model"], model_link_field, model_record_ids)
        add_material_language_link(fields, target["language"], language_link_field, language_record_ids)
        keeper_updates.append({"record_id": target["keeper_id"], "fields": fields})
    feishu_batch_update_record_fields("物料主数据", keeper_updates)

    target_id_by_key = {target["key"]: str(target["keeper_id"]) for target in plan["targets"]}
    source_to_target_id = {
        source_id: target_id_by_key[target_key]
        for source_id, target_key in plan["source_to_target_key"].items()
    }
    relation_update_count = 0
    for table_name, relation_fields, rows in relation_sources:
        updates = build_material_relation_updates(rows, source_to_target_id, relation_fields)
        relation_update_count += feishu_batch_update_record_fields(table_name, updates)

    deleted_count = feishu_batch_delete_record_ids("物料主数据", plan["delete_ids"])
    category_update_fields: dict[str, object] = {
        "物料品类": new_product,
        "中文页面名称": category_zh_page_name,
        "英文页面名称": category_en_page_name,
        "是否无需型号": "是" if no_model else "否",
        "是否无需语种": "是" if no_language else "否",
        "启用状态": category_status,
        REQUEST_PAGE_VISIBILITY_FIELD: category_request_visible,
        "库存行数": plan["target_count"],
        "产品型号数量": len(plan["models"]),
        "语种数量": len(plan["languages"]),
    }
    if category_definition:
        category_update_fields["品类定义"] = category_definition
    set_feishu_unit_price(CATEGORY_TABLE_NAME, category_update_fields, category_unit_price)
    set_feishu_customs_code(CATEGORY_TABLE_NAME, category_update_fields, category_customs_code)
    set_shipping_category_fields(
        category_update_fields,
        commercial_invoice_name,
        packing_list_product_type,
    )
    feishu_update_record_fields(CATEGORY_TABLE_NAME, category_record_id, category_update_fields)

    return {
        **plan,
        "category_record_id": category_record_id,
        "created_category": created_category,
        "created_count": len(created_material_rows),
        "updated_count": len(keeper_updates),
        "deleted_count": deleted_count,
        "relation_update_count": relation_update_count,
        "category_definition": category_definition,
        "category_zh_page_name": category_zh_page_name,
        "category_en_page_name": category_en_page_name,
        "category_request_visible": category_request_visible,
        "commercial_invoice_name": commercial_invoice_name,
        "packing_list_product_type": packing_list_product_type,
    }


def create_new_gift_project_request(
    project_name: object,
    material_name: object,
    *,
    owner: object = "",
    owner_open_id: object = "",
    unit_price: float = 0.0,
    remark: object = "",
    attachment_token: object = "",
) -> dict[str, object]:
    product = str(material_name or "").strip()
    if not product:
        raise ValueError("请填写新的周边礼品名称。")
    if float(unit_price) < 0:
        raise ValueError("单价（美元）不能小于 0。")
    existing_names = {
        normalize_category_match_key(item.get("category"))
        for item in feishu_category_records_from_rows(
            fresh_feishu_rows(CATEGORY_TABLE_NAME)
        )
    }
    if normalize_category_match_key(product) in existing_names:
        raise ValueError("该物料品类已经存在，请返回卡片列表选择现有周边礼品。")

    category_result = sync_feishu_category_inventory(
        old_product="",
        new_product=product,
        no_model=True,
        no_language=True,
        target_models=[NO_MODEL_TEXT],
        target_languages=[NO_LANGUAGE_TEXT],
        category_definition=CATEGORY_DEFINITION_GIFT,
        category_status=STATUS_INACTIVE,
        category_request_visible=REQUEST_PAGE_HIDDEN_VALUE,
        category_unit_price=float(unit_price),
        commercial_invoice_name=product,
        packing_list_product_type="Give aways",
        target_values={
            (NO_MODEL_TEXT, NO_LANGUAGE_TEXT): {
                "quantity": 0,
                "unit_price": float(unit_price),
                "status": STATUS_INACTIVE,
                "request_visible": REQUEST_PAGE_HIDDEN_VALUE,
            }
        },
    )
    project_record = create_gift_project_request(
        project_name,
        category_result["category_record_id"],
        owner=owner,
        owner_open_id=owner_open_id,
        remark=remark,
        attachment_token=attachment_token,
    )
    return {
        "category": category_result,
        "project_record": project_record,
    }


def process_gift_project_batch(args: dict[str, object]) -> dict[str, int]:
    existing_ids = list(args.get("category_record_ids") or [])
    created_count = 0
    if existing_ids:
        created_count += len(create_gift_project_requests_batch(
            args.get("project_name"), existing_ids,
            owner=args.get("owner", ""), owner_open_id=args.get("owner_open_id", ""),
        ))
    new_line = args.get("new_line")
    if isinstance(new_line, dict):
        create_new_gift_project_request(
            args.get("project_name"), new_line.get("name"),
            owner=args.get("owner", ""), owner_open_id=args.get("owner_open_id", ""),
            remark=f"数量：{int(new_line.get('quantity') or 1)}\n{str(new_line.get('remark') or '')}",
        )
        created_count += 1
    return {"created_count": created_count}


def find_feishu_category_record(product: str) -> dict | None:
    for row in feishu_rows("物料品类"):
        if feishu_text(feishu_fields(row), "物料品类") == product:
            return row
    return None


def add_feishu_material_category_payload(
    product: str,
    no_model: bool,
    no_language: bool,
    df: pd.DataFrame,
) -> int:
    client = feishu_client()
    if client is None:
        return 0

    models = unique_preserve(list(df[MODEL_COL].astype(str)))
    languages = unique_preserve(list(df[LANGUAGE_COL].astype(str)))
    category_record = find_feishu_category_record(product)
    if category_record is None:
        created = feishu_batch_create_records(
            "物料品类",
            [
                {
                    "物料品类": product,
                    "是否无需型号": "是" if no_model else "否",
                    "是否无需语种": "是" if no_language else "否",
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
        feishu_update_record_fields(
            "物料品类",
            category_record_id,
            {
                "是否无需型号": "是" if no_model else "否",
                "是否无需语种": "是" if no_language else "否",
                "启用状态": "启用",
                "库存行数": len(df),
                "产品型号数量": len(models),
                "语种数量": len(languages),
            },
        )

    records: list[dict[str, object]] = []
    model_link_field, model_record_ids = ensure_feishu_model_records(models)
    language_link_field, language_record_ids = ensure_feishu_language_records(languages)
    for row in df[INVENTORY_HEADERS].itertuples(index=False):
        fields: dict[str, object] = {
            "物料编码": str(row[0]),
            "物料品类": str(row[1]),
            "产品型号": str(row[2]) or NO_MODEL_TEXT,
            "语种": str(row[3]),
            "当前库存": int(row[4]),
            "备注": "",
            "启用状态": STATUS_ACTIVE,
            "品类关联": [category_record_id] if category_record_id else [],
        }
        set_feishu_unit_price(MATERIAL_TABLE_NAME, fields, float(row[5] or 0))
        add_material_model_link(fields, str(row[2]) or NO_MODEL_TEXT, model_link_field, model_record_ids)
        add_material_language_link(fields, str(row[3]) or NO_LANGUAGE_TEXT, language_link_field, language_record_ids)
        records.append(fields)

    inserted = 0
    for start in range(0, len(records), 500):
        created = feishu_batch_create_records(MATERIAL_TABLE_NAME, records[start : start + 500])
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


def management_section_requires_admin(section: object) -> bool:
    return str(section or "") in ADMIN_MANAGEMENT_SECTIONS


def set_management_section(section: object, *, sync_workbench_control: bool = True) -> str:
    """Keep navigation state independent from the request-page radio widget."""
    normalized = str(section or "库存登记")
    st.session_state[MANAGEMENT_NAVIGATION_KEY] = normalized
    if sync_workbench_control and normalized in MANAGEMENT_WORKBENCH_SECTIONS:
        st.session_state[MANAGEMENT_WORKBENCH_CONTROL_KEY] = normalized
    return normalized


def apply_management_section_from_query() -> str:
    """Open a public workbench directly from a stable shareable URL."""
    route = str(st.query_params.get("section", "")).strip().casefold()
    section = {
        "request": "库存登记",
        "cultural_request": "文化周边申领",
    }.get(route, "")
    if section:
        set_management_section(section)
    return section


def sync_management_section_from_workbench_control() -> None:
    selected = st.session_state.get(MANAGEMENT_WORKBENCH_CONTROL_KEY, "库存登记")
    if selected in MANAGEMENT_WORKBENCH_SECTIONS:
        set_management_section(selected, sync_workbench_control=False)


def request_material_management_navigation_loading() -> None:
    st.session_state.pop(MANAGEMENT_NAVIGATION_LOADING_KEY, None)


def management_navigation_uses_loading_overlay(section: object) -> bool:
    return False


def admin_auth_gate() -> bool:
    if st.session_state.get("admin_unlocked"):
        return True
    password = st.text_input("请输入管理员密码", type="password", key="admin_password")
    if password == get_approval_password():
        st.session_state["admin_unlocked"] = True
        st.rerun()
    if password:
        st.error("密码不正确")
    return False


def sidebar_admin_auth_gate(key_prefix: str) -> bool:
    if st.session_state.get("admin_unlocked"):
        return True
    password = st.text_input(
        "请输入管理员密码",
        type="password",
        key=f"{key_prefix}_admin_password",
    )
    if st.button(
        "解锁",
        key=f"{key_prefix}_admin_unlock",
        icon=":material/lock_open:",
        width="stretch",
    ):
        if password == get_approval_password():
            st.session_state["admin_unlocked"] = True
            st.rerun()
        st.error("密码不正确")
    return False


def render_github_cache_publish() -> None:
    if not st.session_state.get("admin_unlocked"):
        with st.expander(
            "手动发布静态缓存",
            expanded=False,
            icon=":material/lock:",
        ):
            sidebar_admin_auth_gate("github_cache_publish")
        return
    if github_cache_refresh_token():
        if st.button(
            "发布 GitHub 静态缓存",
            key="sidebar_publish_github_cache",
            icon=":material/cloud_upload:",
            width="stretch",
        ):
            with fullscreen_data_sync("正在提交 GitHub 缓存发布任务"):
                try:
                    trigger_github_cache_refresh()
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.session_state["github_cache_refresh_message"] = (
                        "GitHub 静态缓存更新任务已提交，完成后应用将自动重新部署。"
                    )
                    st.rerun()
        return
    st.link_button(
        "手动发布静态缓存",
        GITHUB_CACHE_WORKFLOW_URL,
        icon=":material/open_in_new:",
        width="stretch",
    )


def render_sidebar_link() -> None:
    with st.sidebar:
        current_view = str(st.query_params.get("view", ""))
        if PUDU_BLUE_LOGO_PATH.exists():
            with st.container(key="sidebar_corporate_logo"):
                st.image(str(PUDU_BLUE_LOGO_PATH), width="stretch")
        with st.container(key="sidebar_brand"):
            brand_icon_col, brand_text_col = st.columns(
                [0.3, 0.7],
                gap="small",
                vertical_alignment="center",
            )
            brand_icon_col.image(str(APP_ICON_PATH), width=64)
            brand_text_col.markdown(
                f"""
                    <div class="pudu-brand-name">{escape(ui_text("营销物料管理系统"))}</div>
                    <div class="pudu-brand-subtitle">PUDU Material Operations</div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown(
            '<div class="pudu-sidebar-label">语言设置 / Language</div>',
            unsafe_allow_html=True,
        )
        st.radio(
            "界面语言 / Interface Language",
            SUPPORTED_UI_LANGUAGES,
            key=UI_LANGUAGE_SESSION_KEY,
            format_func=lambda language: "中文 / Chinese" if language == LANGUAGE_ZH else "English / 英文",
            horizontal=True,
            label_visibility="collapsed",
        )
        st.divider()
        st.markdown(
            f'<div class="pudu-sidebar-label">{escape(ui_text("工作台导航"))}</div>',
            unsafe_allow_html=True,
        )
        navigate_to_management_section(
            "sidebar_open_request",
            "库存登记",
            "库存登记",
            ":material/edit_note:",
        )
        navigate_to_management_section(
            "sidebar_open_cultural_request",
            "文化周边申领",
            "文化周边申领",
            ":material/checkroom:",
        )
        render_inventory_query_link()
        navigate_to_management_section(
            "sidebar_open_material_management",
            "物料管理",
            "物料管理",
            ":material/inventory_2:",
        )
        st.divider()
        with st.container(key="sidebar_data_system_group"):
            st.markdown(
                '<div class="pudu-sidebar-system-heading">'
                f'<div class="pudu-sidebar-label">{escape(ui_text("数据与系统"))}</div>'
                f'<div class="pudu-app-version">{escape(ui_text("当前应用版本"))} {escape(APP_VERSION)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            if not st.session_state.get("admin_unlocked"):
                with st.expander("数据与系统工具", expanded=False, icon=":material/lock:"):
                    sidebar_admin_auth_gate("data_system_tools")
            else:
                if st.button(
                    "更新物料数据缓存",
                    key="sidebar_refresh_data",
                    icon=":material/refresh:",
                    width="stretch",
                ):
                    with fullscreen_data_sync("正在更新物料页面数据缓存"):
                        try:
                            maintenance = maintain_inventory_status()
                            result = refresh_page_cache_tables(ALL_PAGE_CACHE_TABLES)
                            refresh_request_form_cache_from_page_data()
                        except Exception as exc:
                            st.error("数据库同步失败。")
                            st.exception(exc)
                        else:
                            st.success(
                                f"全部页面数据已同步，共 {result['row_count']} 条记录；"
                                f"自动启用 {maintenance['enabled_count']} 条，"
                                f"自动停用 {maintenance['disabled_count']} 条。"
                            )
                github_message = st.session_state.pop("github_cache_refresh_message", "")
                if github_message:
                    st.success(github_message)
                with st.container(key="sidebar_cache_publish"):
                    render_github_cache_publish()
                render_storage_diagnostics(st)
        st.divider()


def sync_mobile_request_language() -> None:
    selected = normalize_ui_language(
        st.session_state.get("request_mobile_ui_language", get_ui_language())
    )
    st.session_state[UI_LANGUAGE_SESSION_KEY] = selected


def render_mobile_request_toolbar() -> None:
    current_language = get_ui_language()
    if "request_mobile_ui_language" not in st.session_state or normalize_ui_language(
        st.session_state.get("request_mobile_ui_language", current_language)
    ) != current_language:
        st.session_state["request_mobile_ui_language"] = current_language

    with st.container(key="request_mobile_toolbar"):
        pudu_col, app_col, language_col, menu_col = st.columns(
            [1.6, 0.8, 0.8, 0.8],
            gap="small",
            vertical_alignment="center",
        )
        if PUDU_BLUE_LOGO_PATH.exists():
            pudu_col.image(str(PUDU_BLUE_LOGO_PATH), width="stretch")
        if APP_ICON_PATH.exists():
            app_col.image(str(APP_ICON_PATH), width="stretch")
        with language_col.popover(
            ui_text("语言设置"),
            key="request_mobile_language",
            icon=":material/translate:",
            width="stretch",
        ):
            st.markdown(
                '<span class="pudu-mobile-home-popover-marker"></span>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**{escape(ui_text('语言设置'))} / Language**")
            st.radio(
                "界面语言 / Interface Language",
                SUPPORTED_UI_LANGUAGES,
                key="request_mobile_ui_language",
                format_func=lambda language: (
                    "中文 / Chinese" if language == LANGUAGE_ZH else "English / 英文"
                ),
                on_change=sync_mobile_request_language,
                label_visibility="collapsed",
            )
        with menu_col.popover(
            ui_text("导航"),
            key="request_mobile_navigation",
            icon=":material/menu:",
            width="stretch",
        ):
            st.markdown(
                '<span class="pudu-mobile-navigation-popover-marker"></span>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**{escape(ui_text('工作台导航'))}**")
            navigate_to_management_section(
                "mobile_open_request",
                "库存登记",
                ui_text("物料申领"),
                ":material/edit_note:",
            )
            navigate_to_management_section(
                "mobile_open_cultural_request",
                "文化周边申领",
                ui_text("文化周边申领"),
                ":material/checkroom:",
            )


def build_request_title(material_usage: object, requester: object) -> str:
    usage_text = str(material_usage or "").strip() or "物料用途"
    requester_text = str(requester or "").strip() or "申请人"
    return f"{usage_text}-{requester_text}-营销物料领取"


def required_field_label(container: object, label: str, hint: str = "") -> None:
    hint_html = (
        f'<span class="pudu-inline-required-hint">{escape(hint)}</span>'
        if hint.strip()
        else ""
    )
    container.markdown(
        (
            f'<div class="pudu-field-label"><span>{escape(ui_text(label))} '
            f'<span class="pudu-required-star">*</span></span>{hint_html}'
            '<span class="pudu-required-control-marker" aria-hidden="true"></span></div>'
        ),
        unsafe_allow_html=True,
    )


def render_readonly_request_department(container: object, department: str) -> None:
    value = str(department or "").strip()
    display_value = value or ui_text("选择申请人后自动显示")
    value_class = " has-value" if value else ""
    container.markdown(
        (
            f'<div class="pudu-readonly-required-control{value_class}" '
            f'role="textbox" aria-readonly="true">{escape(display_value)}</div>'
        ),
        unsafe_allow_html=True,
    )


def initialize_request_form_state() -> None:
    defaults = {
        "request_department": get_secret_value("DEFAULT_REQUEST_DEPARTMENT", ""),
        "request_requester": get_secret_value("DEFAULT_REQUESTER", ""),
        "request_department_id": None,
        "request_requester_open_id": None,
        "request_department_manual": get_secret_value("DEFAULT_REQUEST_DEPARTMENT", ""),
        "request_requester_manual": get_secret_value("DEFAULT_REQUESTER", ""),
        "request_customer_name": "",
        "request_country": "",
        "request_recipient_info": "",
        "request_freight_payer": DEFAULT_FREIGHT_PAYER,
        "request_material_usage": "",
        "request_material_lines": [],
        "request_form_stage": "edit",
        "request_material_table_version": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "request_submission_token" not in st.session_state:
        st.session_state["request_submission_token"] = uuid.uuid4().hex


def render_request_contact_fields(requester_col: object) -> tuple[str, str, str, str]:
    requester_hint = "Enter the English name" if get_ui_language() == LANGUAGE_EN else "填写中文名称"
    required_field_label(requester_col, "申请人", requester_hint)
    try:
        departments = get_contact_departments()
        directory_users = get_contact_users()
    except Exception as exc:
        st.warning(f"飞书通讯录暂时不可用，无法自动识别申请部门：{exc}")
        department = ""
        requester = requester_col.text_input(
            "申请人",
            placeholder=requester_hint,
            key="request_requester_manual",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        st.session_state["request_department"] = department
        st.session_state["request_requester"] = requester
        st.session_state["request_department_id"] = None
        st.session_state["request_requester_open_id"] = None
        return department, "", requester, ""

    department_by_id = {
        str(item["department_id"]): item
        for item in departments
        if str(item.get("department_id") or "").strip()
    }
    users: list[dict[str, object]] = list(directory_users)
    user_by_id = {
        str(item["open_id"]): item
        for item in users
        if str(item.get("open_id") or "").strip()
    }
    name_counts: dict[str, int] = {}
    for item in users:
        name = str(item.get("name") or "")
        name_counts[name] = name_counts.get(name, 0) + 1

    def user_label(open_id: object) -> str:
        item = user_by_id.get(str(open_id), {})
        name = str(item.get("name") or open_id)
        department_paths = unique_preserve(
            [str(value) for value in list(item.get("department_paths") or [])]
        )
        label = f"{name} · {'、'.join(department_paths)}" if department_paths else name
        return f"{label} · {str(open_id)[-6:]}" if name_counts.get(name, 0) > 1 else label

    user_options = list(user_by_id)
    st.session_state[REQUEST_CONTACT_USER_LOOKUP_KEY] = user_by_id
    current_open_id = st.session_state.get("request_requester_open_id")
    if current_open_id not in user_options:
        st.session_state["request_requester_open_id"] = None
    requester_open_id = requester_col.selectbox(
        "申请人",
        user_options,
        index=None,
        key="request_requester_open_id",
        format_func=user_label,
        placeholder=(
            "Enter the English name"
            if get_ui_language() == LANGUAGE_EN
            else "填写中文名称"
        ) if directory_users else "通讯录中暂无可选成员",
        disabled=not user_options,
        label_visibility="collapsed",
        on_change=sync_request_department_from_selected_applicant,
    )
    requester = (
        str(user_by_id.get(str(requester_open_id), {}).get("name") or "")
        if requester_open_id
        else ""
    )
    selected_user = user_by_id.get(str(requester_open_id), {})
    selected_department_ids = [
        str(value)
        for value in list(selected_user.get("department_ids") or [])
        if str(value).strip() and str(value) in department_by_id
    ]
    current_department_id = str(st.session_state.get("request_department_id") or "")
    department_id = (
        current_department_id
        if current_department_id in selected_department_ids
        else (selected_department_ids[0] if selected_department_ids else "")
    )
    department = (
        str(department_by_id.get(department_id, {}).get("path") or "")
        if department_id
        else ""
    )
    st.session_state["request_department"] = department
    st.session_state["request_department_id"] = department_id or None
    st.session_state["request_requester"] = requester
    if not users:
        requester_col.caption("通讯录中暂无可选成员，请刷新本页数据后重试。")
    elif requester_open_id and not department:
        requester_col.caption("该申请人未关联有效部门，请联系管理员维护通讯录。")
    return department, str(department_id or ""), requester, str(requester_open_id or "")


def get_request_material_lines() -> list[dict[str, object]]:
    raw_lines = st.session_state.get("request_material_lines")
    if not isinstance(raw_lines, list):
        raw_lines = []
    lines = [
        {
            "product": str(item.get("product", "")).strip(),
            "model": str(item.get("model", "")).strip() or NO_MODEL_TEXT,
            "language": str(item.get("language", "")).strip() or NO_LANGUAGE_TEXT,
            "quantity": int(item.get("quantity") or 0),
            "remark": str(item.get("remark", "")).strip(),
            "is_custom_material": bool(item.get("is_custom_material")),
        }
        for item in raw_lines
        if isinstance(item, dict)
    ]
    st.session_state["request_material_lines"] = lines
    return lines


def request_material_key(item: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(item.get("product", "")).strip(),
        str(item.get("model", "")).strip() or NO_MODEL_TEXT,
        str(item.get("language", "")).strip() or NO_LANGUAGE_TEXT,
    )


def filter_request_catalog_products(products: list[str], query: str) -> list[str]:
    keyword = normalize_option_label(query).casefold()
    if not keyword:
        return list(products)
    return [
        product
        for product in products
        if keyword in normalize_option_label(product).casefold()
        or keyword in normalize_option_label(request_option_display_label(product)).casefold()
    ]


def add_request_material_to_cart(
    lines: list[dict[str, object]],
    next_line: dict[str, object],
) -> tuple[list[dict[str, object]], bool]:
    updated_lines = [dict(line) for line in lines]
    next_key = request_material_key(next_line)
    for line in updated_lines:
        if request_material_key(line) != next_key:
            continue
        line["quantity"] = min(
            1_000_000,
            max(1, int(line.get("quantity") or 0)) + max(1, int(next_line.get("quantity") or 0)),
        )
        next_remark = str(next_line.get("remark", "")).strip()
        if next_remark:
            line["remark"] = next_remark
        return updated_lines, True
    updated_lines.append(dict(next_line))
    return updated_lines, False


def build_request_cart_selection_lines(
    selection_context: dict[str, object],
    product: str,
    selected_models: list[str],
    selected_languages: list[str],
    quantity: int,
    remark: str,
) -> list[dict[str, object]]:
    return [
        {
            "product": product,
            "model": model or NO_MODEL_TEXT,
            "language": language or NO_LANGUAGE_TEXT,
            "quantity": max(1, int(quantity)),
            "remark": str(remark or "").strip(),
        }
        for model in selected_models
        for language in selected_languages
        if selection_context_has_inventory_combination(
            selection_context,
            product,
            model or NO_MODEL_TEXT,
            language or NO_LANGUAGE_TEXT,
        )
    ]


def build_custom_request_material_line(
    description: object,
    quantity: int,
    remark: object,
) -> dict[str, object]:
    """Build one free-text material line without expanding dimensions."""
    custom_text = str(description or "").strip()
    return {
        "product": custom_text,
        "model": custom_text,
        "language": custom_text,
        "quantity": max(1, int(quantity)),
        "remark": str(remark or "").strip(),
        "is_custom_material": True,
    }


def clear_request_normal_dimension_state(
    model_widget_key: str,
    language_widget_key: str,
) -> None:
    """Make normal dimensions mutually exclusive with custom-material mode."""
    st.session_state[model_widget_key] = []
    st.session_state[language_widget_key] = None
    for key in list(st.session_state):
        if str(key).startswith(f"{model_widget_key}_"):
            st.session_state[key] = []
    mark_request_form_dirty()


def request_language_options_for_models(
    selection_context: dict[str, object],
    product: str,
    selected_models: list[str],
) -> list[str]:
    scoped_options = [
        product_language_options(product, model, selection_context)
        for model in selected_models
    ]
    if not scoped_options:
        return []
    common_languages = set(scoped_options[0])
    for languages in scoped_options[1:]:
        common_languages.intersection_update(languages)
    return sort_languages(
        [language for language in scoped_options[0] if language in common_languages]
    )


def normalize_request_option_state(
    state_key: str,
    options: list[str],
    *,
    multiple: bool,
) -> None:
    current_value = st.session_state.get(state_key)
    if multiple:
        selected_values = (
            [value for value in current_value if value in options]
            if isinstance(current_value, list)
            else []
        )
        st.session_state[state_key] = selected_values
        return
    if not isinstance(current_value, str) or current_value not in options:
        st.session_state[state_key] = None


def ensure_request_language_default(state_key: str, options: list[str]) -> str | None:
    """Keep a deliberate language choice valid without preselecting one."""
    normalize_request_option_state(state_key, options, multiple=False)
    selected = st.session_state.get(state_key)
    return str(selected) if isinstance(selected, str) and selected in options else None


def apply_request_quantity_preset(preset_key: str, quantity_key: str) -> None:
    selected = st.session_state.get(preset_key)
    if selected is not None:
        st.session_state[quantity_key] = int(selected)
    mark_request_form_dirty()


def clear_request_quantity_preset(preset_key: str) -> None:
    st.session_state[preset_key] = None
    mark_request_form_dirty()


def request_estimated_total_rmb(
    lines: list[dict[str, object]],
    selection_context: dict[str, object],
) -> float:
    """Estimate cart cost from cached prices; backend snapshots stay authoritative."""
    price_index = dict(selection_context.get("unit_price_rmb_by_combination") or {})
    total = 0.0
    for line in lines:
        if bool(line.get("is_custom_material")):
            continue
        key = (
            normalize_option_label(line.get("product")),
            normalize_option_label(line.get("model") or NO_MODEL_TEXT),
            str(line.get("language") or NO_LANGUAGE_TEXT).strip(),
        )
        total += float(price_index.get(key) or 0) * max(0, int(line.get("quantity") or 0))
    return round(total, 2)


def sync_request_model_line_selection(
    state_key: str,
    group_keys: list[str],
    changed_key: str,
    multiple: bool,
) -> None:
    selected_values: list[str] = []
    for group_key in group_keys:
        value = st.session_state.get(group_key)
        if multiple:
            if isinstance(value, list):
                selected_values.extend(str(item) for item in value if str(item).strip())
        elif group_key == changed_key and isinstance(value, str) and value:
            selected_values = [value]
    selected_values = unique_preserve(selected_values)
    st.session_state[state_key] = selected_values if multiple else (selected_values[0] if selected_values else None)
    if not multiple:
        for group_key in group_keys:
            if group_key != changed_key:
                st.session_state[group_key] = None
    mark_request_form_dirty()


def render_request_model_selector(
    product: str,
    selection_context: dict[str, object],
    model_options: list[str],
    *,
    multiple: bool,
    state_key: str,
) -> list[str]:
    model_display_names = selection_context.get("model_display_names", {})
    display_model = lambda value: request_model_display_label(
        value, model_display_names
    )
    use_product_line_layout, groups = product_model_line_groups(
        product,
        selection_context,
    )
    normalize_request_option_state(state_key, model_options, multiple=multiple)
    if not use_product_line_layout:
        selected = st.pills(
            "产品型号",
            model_options,
            selection_mode="multi" if multiple else "single",
            required=not multiple,
            format_func=display_model,
            key=state_key,
            on_change=mark_request_form_dirty,
            width="stretch",
        )
        return list(selected or []) if multiple else [selected] if selected else []

    current = st.session_state.get(state_key)
    selected_values = list(current or []) if multiple else [current] if current else []
    group_options = {name: options for name, options in groups}
    primary_groups = [
        (name, list(group_options.get(name, [])))
        for name in PRIMARY_MODEL_PRODUCT_LINES
    ]
    other_groups = [
        (name, options)
        for name, options in groups
        if name not in PRIMARY_MODEL_PRODUCT_LINES and options
    ]
    selectable_groups = [item for item in primary_groups + other_groups if item[1]]
    group_keys = [f"{state_key}_{name}" for name, _ in selectable_groups]
    for group_key, (_, options) in zip(group_keys, selectable_groups):
        scoped_selected = [value for value in selected_values if value in options]
        st.session_state[group_key] = scoped_selected if multiple else (
            scoped_selected[0] if scoped_selected else None
        )

    st.markdown('<span class="pudu-model-line-grid-marker"></span>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="pudu-product-model-label">{escape(ui_text("产品型号"))}</div>',
        unsafe_allow_html=True,
    )
    visible_groups = [item for item in primary_groups + other_groups if item[1]]
    with st.container(key=f"request_model_line_grid_{normalize_option_label(product)}"):
        for name, options in visible_groups:
            group_key = f"{state_key}_{name}"
            with st.container(border=True):
                st.markdown(
                    '<span class="pudu-model-line-group-marker"></span>',
                    unsafe_allow_html=True,
                )
                st.caption(name)
                st.pills(
                    f"{name} 产品型号",
                    options,
                    selection_mode="multi" if multiple else "single",
                    format_func=display_model,
                    key=group_key,
                    on_change=sync_request_model_line_selection,
                    args=(state_key, group_keys, group_key, multiple),
                    label_visibility="collapsed",
                    width="stretch",
                )
    current = st.session_state.get(state_key)
    return list(current or []) if multiple else [current] if current else []


def prepare_request_line_editor_state() -> None:
    load_data = st.session_state.pop("request_line_editor_load", None)
    if isinstance(load_data, dict):
        st.session_state["request_material_edit_index"] = int(load_data.get("index", -1))
        st.session_state["request_line_product"] = str(load_data.get("product", ""))
        st.session_state["request_line_model"] = str(load_data.get("model", "")) or NO_MODEL_TEXT
        st.session_state["request_line_language"] = (
            str(load_data.get("language", "")) or NO_LANGUAGE_TEXT
        )
        st.session_state["request_line_quantity"] = max(1, int(load_data.get("quantity") or 1))
        st.session_state["request_line_remark"] = str(load_data.get("remark", ""))
        for field in ("product", "model", "language"):
            for language_code in SUPPORTED_UI_LANGUAGES:
                st.session_state.pop(f"request_line_{field}_{language_code}", None)
        return
    if st.session_state.pop("request_line_editor_reset", False):
        for key in (
            "request_line_product",
            "request_line_model",
            "request_line_language",
            "request_line_quantity",
            "request_line_remark",
        ):
            st.session_state.pop(key, None)
        for field in ("product", "model", "language"):
            for language_code in SUPPORTED_UI_LANGUAGES:
                st.session_state.pop(f"request_line_{field}_{language_code}", None)
        st.session_state["request_material_edit_index"] = None


def request_material_table_dataframe(lines: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "选择": False,
                "序号": index + 1,
                "物料品类": request_category_display_label(line["product"]),
                "产品型号": request_model_display_label(line["model"]),
                "语种": line["language"],
                "数量": int(line["quantity"]),
                "备注": line.get("remark", ""),
            }
            for index, line in enumerate(lines)
        ]
    )


def apply_request_material_table_edits(
    lines: list[dict[str, object]],
    edited_df: pd.DataFrame,
) -> tuple[list[dict[str, object]], list[int]]:
    updated_lines = [dict(line) for line in lines]
    selected_indices: list[int] = []
    for row in edited_df.to_dict("records"):
        try:
            line_index = int(row.get("序号") or 0) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= line_index < len(updated_lines):
            continue
        if bool(row.get("选择")):
            selected_indices.append(line_index)
        try:
            quantity = int(row.get("数量") or updated_lines[line_index].get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = int(updated_lines[line_index].get("quantity") or 1)
        remark_value = row.get("备注", "")
        remark = "" if pd.isna(remark_value) else str(remark_value).strip()
        updated_lines[line_index]["quantity"] = max(1, min(1_000_000, quantity))
        updated_lines[line_index]["remark"] = remark
    return updated_lines, list(dict.fromkeys(selected_indices))


def validate_request_draft(
    draft: dict[str, object],
    *,
    include_live_schedule_validation: bool = True,
) -> list[str]:
    errors: list[str] = []
    customer_label = request_customer_display_label(draft)
    if include_live_schedule_validation and draft.get("scheduling_version") == 1:
        from order_scheduling_service import SchedulingService
        try:
            SchedulingService(APP_RUNTIME).request_dates(draft)
        except Exception as exc:
            errors.append(str(exc))
    missing = [
        label
        for label, value in [
            ("申请部门", draft.get("department")),
            ("申请人", draft.get("requester")),
            (customer_label, draft.get("customer_name")),
            ("国家", draft.get("country")),
            ("收件人信息", draft.get("recipient_info")),
            ("运费的承担者", draft.get("freight_payer")),
            ("物料用途", draft.get("material_usage")),
        ]
        if not str(value or "").strip()
    ]
    if missing:
        errors.append("请补充必填信息：" + "、".join(missing))

    lines = list(draft.get("lines") or [])
    if not lines:
        errors.append("请至少加入一种申请物料")
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            errors.append(f"第 {index + 1} 条物料明细无效")
            continue
        if not all(str(line.get(field, "")).strip() for field in ("product", "model", "language")):
            errors.append(f"第 {index + 1} 条物料缺少品类、型号或语种")
        if int(line.get("quantity") or 0) <= 0:
            errors.append(f"第 {index + 1} 条物料数量必须大于 0")
    return errors


def show_request_validation_toast(errors: list[str]) -> None:
    """Display request validation failures prominently without moving page content."""
    if errors:
        st.toast("；".join(errors), icon="⚠️", duration="long")


def restore_request_form_from_draft(draft: dict[str, object]) -> None:
    field_map = {
        "request_department": "department",
        "request_requester": "requester",
        "request_customer_name": "customer_name",
        "request_country": "country",
        "request_recipient_info": "recipient_info",
        "request_freight_payer": "freight_payer",
        "request_material_usage": "material_usage",
    }
    for state_key, draft_key in field_map.items():
        st.session_state[state_key] = draft.get(draft_key, "")
    st.session_state["request_department_id"] = draft.get("department_id") or None
    st.session_state["request_requester_open_id"] = draft.get("requester_open_id") or None
    st.session_state["request_department_manual"] = draft.get("department", "")
    st.session_state["request_requester_manual"] = draft.get("requester", "")
    if draft.get("scheduling_version") == 1:
        import order_scheduling as scheduling_rules
        st.session_state["request_schedule_reason"] = scheduling_rules.normalize_reason(
            draft.get("request_reason")
        ) or None
        st.session_state["request_schedule_dates"] = tuple(
            scheduling_rules.as_date(draft.get(k)) for k in ("arrival_start", "arrival_end")
            if draft.get(k)
        )
    st.session_state["request_material_lines"] = [
        dict(line) for line in list(draft.get("lines") or []) if isinstance(line, dict)
    ]
    st.session_state["request_material_table_version"] = (
        int(st.session_state.get("request_material_table_version", 0)) + 1
    )
    st.session_state["request_line_editor_reset"] = True
    st.session_state["request_form_stage"] = "edit"
    st.session_state.pop("request_draft_payload", None)


def clear_request_application_state() -> None:
    for key in list(st.session_state):
        if str(key).startswith("request_"):
            st.session_state.pop(key, None)


def scroll_request_page_to_top_if_needed() -> None:
    if not st.session_state.pop("request_scroll_to_top", False):
        return
    st.html(
        """
        <script>
        const main = document.querySelector('[data-testid="stMain"]');
        if (main) main.scrollTo({ top: 0, left: 0, behavior: 'instant' });
        window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_request_cart_added_toast() -> None:
    if not st.session_state.pop("request_cart_added_toast", False):
        return
    message = (
        "Added to cart"
        if get_ui_language() == LANGUAGE_EN
        else "已加入购物车"
    )
    st.toast(message, icon="🛒", duration="long")


def render_request_review_field(container: object, label: str, value: object) -> None:
    display_value = escape(str(value or "-")).replace("\n", "<br>")
    container.markdown(
        f"""
        <div class="pudu-review-field">
            <span>{escape(ui_text(label))}</span>
            <strong>{display_value}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_request_review() -> None:
    scroll_request_page_to_top_if_needed()
    draft = st.session_state.get("request_draft_payload")
    if not isinstance(draft, dict):
        st.session_state["request_form_stage"] = "edit"
        st.rerun()

    lines = [dict(line) for line in list(draft.get("lines") or []) if isinstance(line, dict)]
    total_quantity = sum(int(line.get("quantity") or 0) for line in lines)
    estimated_total_rmb = request_estimated_total_rmb(
        lines,
        get_request_form_selection_context(),
    )
    material_types_label = escape(ui_text("物料种类"))
    total_quantity_label = escape(ui_text("申请总数量"))
    estimated_total_label = escape(ui_text("预计总花费"))
    estimated_total_hint = escape(ui_text("按当前单价估算，以最终审核为准"))
    st.markdown(
        f"""
        <div class="pudu-review-metrics">
            <div class="pudu-review-metric"><span>{material_types_label}</span><strong>{len(lines)}</strong></div>
            <div class="pudu-review-metric"><span>{total_quantity_label}</span><strong>{total_quantity}</strong></div>
            <div class="pudu-review-metric pudu-review-metric-cost"><span>{estimated_total_label}</span><strong>¥{estimated_total_rmb:,.2f}</strong><small>{estimated_total_hint}</small></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        render_section_header("01", "申请信息确认", "请核对完整申请内容后再提交")
        st.markdown(
            f"""
            <div class="pudu-generated-title">
                <span>{escape(ui_text("申请标题"))}</span>
                <strong>{escape(str(draft.get("title") or ""))}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
        overview_cols = st.columns(4)
        render_request_review_field(overview_cols[0], "申请人", draft.get("requester"))
        render_request_review_field(overview_cols[1], "申请部门", draft.get("department"))
        customer_label = (
            "代理商名称"
            if draft.get("request_reason") == "代理商支持"
            else "客户名称"
        )
        render_request_review_field(overview_cols[2], customer_label, draft.get("customer_name"))
        render_request_review_field(overview_cols[3], "国家", draft.get("country"))
        detail_cols = st.columns([1.2, 1, 1.4])
        render_request_review_field(detail_cols[0], "物料用途", draft.get("material_usage"))
        render_request_review_field(detail_cols[1], "收件人信息", draft.get("recipient_info"))
        if draft.get("scheduling_version") == 1:
            schedule_cols = st.columns(3)
            render_request_review_field(schedule_cols[0], "申请原因", draft.get("request_reason"))
            render_request_review_field(schedule_cols[1], "要求到达开始日期", draft.get("arrival_start"))
            render_request_review_field(schedule_cols[2], "要求到达结束日期", draft.get("arrival_end"))

    with st.container(border=True):
        render_section_header("02", "申请物料清单", f"共 {len(lines)} 种物料")
        review_df = pd.DataFrame(
            [
                {
                    "序号": index + 1,
                    "物料品类": line.get("product", ""),
                    "产品型号": request_model_display_label(line.get("model", "")),
                    "语种": line.get("language", ""),
                    "申请数量": int(line.get("quantity") or 0),
                    "备注": line.get("remark", ""),
                }
                for index, line in enumerate(lines)
            ]
        )
        edited_review_df = st.data_editor(
            review_df,
            width="stretch",
            hide_index=True,
            height=min(820, max(150, 38 * (len(review_df) + 1) + 18)),
            row_height=34,
            num_rows="fixed",
            disabled=["序号", "物料品类", "产品型号", "语种", "备注"],
            column_config={
                "申请数量": st.column_config.NumberColumn(
                    "申请数量", min_value=1, max_value=1_000_000, step=1, format="%d"
                )
            },
            key="request_review_quantity_editor",
        )
        edited_quantities = [
            max(1, int(row.get("申请数量") or 1))
            for row in edited_review_df.to_dict("records")
        ]
        if edited_quantities != [int(line.get("quantity") or 0) for line in lines]:
            for line, quantity in zip(lines, edited_quantities):
                line["quantity"] = quantity
            draft["lines"] = [dict(line) for line in lines]
            st.session_state["request_draft_payload"] = draft

    back_col, _, confirm_col = st.columns([1.1, 2.2, 1.4])
    if back_col.button(
        "返回修改",
        key="request_review_back",
        icon=":material/arrow_back:",
        width="stretch",
    ):
        restore_request_form_from_draft(draft)
        st.session_state["request_scroll_to_top"] = True
        st.rerun()
    if confirm_col.button(
        "确认提交",
        key="request_review_confirm",
        type="primary",
        icon=":material/check_circle:",
        width="stretch",
    ):
        errors = validate_request_draft(draft)
        if errors:
            show_request_validation_toast(errors)
            return
        with fullscreen_data_sync("正在提交数据，请稍后......"):
            with DATA_LOCK:
                try:
                    task, created_new_task = enqueue_feishu_material_request(
                        draft,
                        lines,
                    )
                except Exception as exc:
                    st.error("申请未能进入后台队列，请检查飞书写入权限后重试。")
                    st.exception(exc)
                    return
        clear_request_application_state()
        render_request_submission_success()
        st.stop()


def toggle_request_compact_cart() -> None:
    st.session_state["request_compact_cart_open"] = not bool(
        st.session_state.get("request_compact_cart_open", False)
    )


def render_compact_request_cart_button(container: object, lines: list[dict[str, object]]) -> None:
    container.button(
        f"🛒 {len(lines)}",
        key="request_compact_cart",
        width="stretch",
        on_click=toggle_request_compact_cart,
    )


def render_compact_request_cart_panel(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    if not st.session_state.get("request_compact_cart_open", False):
        return lines
    total_quantity = sum(int(line.get("quantity") or 0) for line in lines)
    with st.container(border=True, key="request_compact_cart_panel"):
        st.markdown(
            '<span class="pudu-full-cart-popover-marker"></span>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"{len(lines)} {ui_text('种物料')} · {total_quantity} {ui_text('件')}"
        )
        if not lines:
            st.info("采购车为空，请先选择物料。")
            return lines

        table_version = int(st.session_state.get("request_material_table_version", 0))
        edited_df = st.data_editor(
            request_material_table_dataframe(lines),
            width="stretch",
            hide_index=True,
            height=min(720, max(140, 38 * (len(lines) + 1) + 22)),
            row_height=34,
            disabled=["序号", "物料品类", "产品型号", "语种"],
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", width="small"),
                "序号": st.column_config.NumberColumn("序号", width="small", format="%d"),
                "物料品类": st.column_config.TextColumn("物料品类", width="medium"),
                "产品型号": st.column_config.TextColumn("产品型号", width="medium"),
                "语种": st.column_config.TextColumn("语种", width="medium"),
                "数量": st.column_config.NumberColumn(
                    "数量",
                    min_value=1,
                    max_value=1_000_000,
                    step=1,
                    format="%d",
                    width="small",
                ),
                "备注": st.column_config.TextColumn("备注", width="medium"),
            },
            key=f"request_material_table_{table_version}",
            on_change=mark_request_form_dirty,
        )
        updated_lines, selected_indices = apply_request_material_table_edits(lines, edited_df)
        if updated_lines != lines:
            st.session_state["request_material_lines"] = updated_lines
            lines = updated_lines
        if st.button(
            "删除选中",
            key="request_delete_selected_material",
            icon=":material/delete:",
            disabled=not selected_indices,
            width="stretch",
        ):
            selected_set = set(selected_indices)
            st.session_state["request_material_lines"] = [
                line for index, line in enumerate(lines) if index not in selected_set
            ]
            st.session_state["request_material_table_version"] = table_version + 1
            mark_request_form_dirty()
            st.rerun(scope="fragment")
    return lines


def request_preview_full_rerun() -> None:
    """Record a preview request; callbacks must not call ``st.rerun`` directly."""
    st.session_state["request_preview_requested"] = True


@st.fragment
def render_request_material_builder(
    selection_context: dict[str, object],
    products: list[str],
) -> tuple[list[dict[str, object]], bool]:
    lines = get_request_material_lines()
    render_request_cart_added_toast()

    with st.container(border=True, key="request_material_section"):
        render_section_header(
            "02",
            "选择申请物料",
            "选择对应物料的规格并加入采购车，可按实际需求添加多种物料。",
        )
        if not products:
            st.error("当前没有可申请的物料品类，请先刷新数据或联系管理员。")
            return lines, False

        request_cache_generated_at = str(
            load_static_request_form_cache().get("generated_at") or ""
        )
        category_image_paths = request_category_image_paths(request_cache_generated_at)

        search_col, cart_col, preview_col = st.columns(
            [5.6, 0.72, 1.75],
            gap="small",
            vertical_alignment="bottom",
        )
        search_query = search_col.text_input(
            "搜索物料",
            key="request_catalog_search",
            placeholder="输入品类名称搜索",
            icon=":material/search:",
            label_visibility="collapsed",
        )
        render_compact_request_cart_button(cart_col, lines)
        estimated_total_rmb = request_estimated_total_rmb(lines, selection_context)
        preview_clicked = bool(st.session_state.pop("request_preview_validation_pending", False))
        preview_col.button(
            "提交物料申请",
            key="request_preview",
            type="primary",
            icon=":material/preview:",
            width="stretch",
            on_click=request_preview_full_rerun,
        )
        if st.session_state.pop("request_preview_requested", False):
            st.session_state["request_preview_validation_pending"] = True
            st.rerun(scope="app")
        st.markdown(
            f"""
            <div class="pudu-request-cost-summary">
                <span>{escape(ui_text("预计总花费"))}</span>
                <strong>¥{estimated_total_rmb:,.2f}</strong>
                <small>{escape(ui_text("按当前缓存单价估算，自定义物料不计价，以最终审核为准"))}</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
        lines = render_compact_request_cart_panel(lines)
        filtered_products = filter_request_catalog_products(products, search_query)
        if not filtered_products:
            st.info("没有找到匹配的物料，请更换关键词。")
        else:
            catalog_grid = st.container(key="request_catalog_grid")
            card_columns = [catalog_grid] * 6
            for index, catalog_product in enumerate(filtered_products):
                product_state_key = normalize_option_label(catalog_product)
                _, scoped_models = product_model_state(
                    catalog_product,
                    selection_context,
                )
                model_options = unique_preserve(scoped_models)
                if not model_options:
                    continue
                with card_columns[index % 6].container(
                    border=True,
                    key=f"request_product_card_{index}",
                ):
                    st.markdown('<span class="pudu-product-card-marker"></span>', unsafe_allow_html=True)
                    category_image_path = category_image_paths.get(
                        normalize_category_match_key(catalog_product)
                    )
                    if category_image_path:
                        st.image(
                            category_image_path,
                            width="stretch",
                        )
                    else:
                        st.markdown(
                            f"""
                            <div class="pudu-product-image-placeholder">
                                {escape(
                                    "No image available"
                                    if get_ui_language() == LANGUAGE_EN
                                    else "暂无图片"
                                )}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f"""
                        <div class="pudu-product-card-kicker">{escape(ui_text("物料品类"))}</div>
                        <div class="pudu-product-card-title">
                            {escape(request_category_display_label(catalog_product))}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    with st.popover(
                        "选择规格",
                        key=f"request_catalog_select_{index}_{normalize_option_label(catalog_product)}",
                        icon=":material/shopping_cart:",
                        width="stretch",
                    ):
                        all_language_options = request_language_options_for_models(
                            selection_context,
                            catalog_product,
                            model_options,
                        )
                        # Preserve the desktop popover widths, which also account for
                        # shared language choices. Phone height is evaluated separately
                        # from the model count below.
                        option_complexity = max(len(model_options), len(all_language_options))
                        popover_size = (
                            "compact" if option_complexity <= 4
                            else "medium" if option_complexity <= 8
                            else "wide"
                        )
                        mobile_model_complexity = len(model_options)
                        mobile_popover_size = (
                            "compact" if mobile_model_complexity <= 4
                            else "medium" if mobile_model_complexity <= 8
                            else "wide"
                        )
                        st.markdown(
                            f'<span class="pudu-specification-popover-marker '
                            f'pudu-specification-popover-{popover_size} '
                            f'pudu-mobile-specification-popover-{mobile_popover_size}"></span>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f"#### {escape(request_category_display_label(catalog_product))}",
                            unsafe_allow_html=True,
                        )
                        model_multi_key = f"request_cart_model_multi_{product_state_key}"
                        language_multi_key = f"request_cart_language_multi_{product_state_key}"
                        st.session_state[model_multi_key] = True
                        st.session_state[language_multi_key] = False
                        model_multi = True
                        language_multi = False

                        model_widget_key = (
                            f"request_cart_models_v2_{'multi' if model_multi else 'single'}_"
                            f"{get_ui_language()}_{product_state_key}"
                        )
                        language_widget_key = (
                            f"request_cart_languages_v2_{'multi' if language_multi else 'single'}_"
                            f"{get_ui_language()}_{product_state_key}"
                        )
                        custom_mode = st.checkbox(
                            (
                                "Can't find the material you need? Check the box on the right"
                                if get_ui_language() == LANGUAGE_EN
                                else "没找到想要的物料？请点击左侧方框"
                            ),
                            key=f"request_custom_material_{product_state_key}",
                            on_change=clear_request_normal_dimension_state,
                            args=(model_widget_key, language_widget_key),
                        )
                        st.markdown('<span class="pudu-custom-material-hint"></span>', unsafe_allow_html=True)
                        selected_models: list[str] = []
                        selected_languages: list[str] = []
                        custom_description = ""
                        if custom_mode:
                            with st.container(border=True, key=f"request_custom_material_panel_{product_state_key}"):
                                st.markdown(
                                    "**Custom material**"
                                    if get_ui_language() == LANGUAGE_EN
                                    else "**自定义物料**"
                                )
                                custom_description = st.text_area(
                                    (
                                        "Please enter the required material and quantity."
                                        if get_ui_language() == LANGUAGE_EN
                                        else "请填写需要的物料和数量。"
                                    ),
                                    key=f"request_custom_material_description_{product_state_key}",
                                    placeholder=(
                                        "Please enter the required material and quantity."
                                        if get_ui_language() == LANGUAGE_EN
                                        else "请填写需要的物料和数量。"
                                    ),
                                    height=80,
                                    on_change=mark_request_form_dirty,
                                )
                        else:
                            with st.container(key=f"request_spec_model_scroll_{product_state_key}"):
                                st.markdown(
                                    f'<div class="pudu-spec-model-heading">{escape(ui_text("型号选择"))}</div>',
                                    unsafe_allow_html=True,
                                )
                                selected_models = render_request_model_selector(
                                    catalog_product,
                                    selection_context,
                                    model_options,
                                    multiple=model_multi,
                                    state_key=model_widget_key,
                                )
                            language_options = request_language_options_for_models(
                                selection_context,
                                catalog_product,
                                selected_models,
                            )
                            ensure_request_language_default(language_widget_key, language_options)
                        with st.container(key=f"request_spec_fixed_{product_state_key}"):
                            if not custom_mode:
                                selected_language_values: object = []
                                if language_options:
                                    language_columns = min(4, max(2, len(language_options)))
                                    with st.container(key=f"request_language_pills_{product_state_key}"):
                                        st.markdown(
                                            f'<span class="pudu-language-pills-marker '
                                            f'pudu-language-columns-{language_columns}"></span>',
                                            unsafe_allow_html=True,
                                        )
                                        selected_language_values = st.pills(
                                            ui_text("语种"),
                                            language_options,
                                            selection_mode="multi" if language_multi else "single",
                                            required=not language_multi,
                                            format_func=request_option_display_label,
                                            key=language_widget_key,
                                            on_change=mark_request_form_dirty,
                                            width="stretch",
                                        )
                                selected_languages = (
                                    list(selected_language_values or [])
                                    if language_multi
                                    else [selected_language_values] if selected_language_values else []
                                )

                            quantity_key = f"request_cart_quantity_{product_state_key}"
                            quantity_preset_key = f"request_quantity_presets_{product_state_key}"
                            option_cols = st.columns([0.65, 1.35, 0.9], gap="small")
                            quantity = option_cols[0].number_input(
                                "自定义数量",
                                min_value=1,
                                max_value=1_000_000,
                                step=1,
                                key=quantity_key,
                                on_change=clear_request_quantity_preset,
                                args=(quantity_preset_key,),
                            )
                            option_cols[1].pills(
                                "快捷数量",
                                [20, 50],
                                selection_mode="single",
                                format_func=lambda value: str(value),
                                key=quantity_preset_key,
                                on_change=apply_request_quantity_preset,
                                args=(quantity_preset_key, quantity_key),
                                label_visibility="hidden",
                                width="stretch",
                            )
                            remark = option_cols[2].text_input(
                                "备注",
                                key=f"request_cart_remark_{product_state_key}",
                                placeholder="可选",
                                on_change=mark_request_form_dirty,
                            )
                            action_clicked = st.button(
                                "加入采购车",
                                key=f"request_add_to_cart_{product_state_key}",
                                type="primary",
                                icon=":material/add_shopping_cart:",
                                disabled=(not str(custom_description).strip()) if custom_mode else (
                                    not selected_models or not selected_languages
                                ),
                                width="stretch",
                            )
                        if action_clicked:
                            selected_lines = (
                                [build_custom_request_material_line(custom_description, int(quantity), remark)]
                                if custom_mode
                                else build_request_cart_selection_lines(
                                    selection_context,
                                    catalog_product,
                                    selected_models,
                                    selected_languages,
                                    int(quantity),
                                    str(remark or ""),
                                )
                            )
                            if not selected_lines:
                                st.warning("所选型号和语种之间没有有效的物料组合。")
                            else:
                                next_lines = [dict(line) for line in lines]
                                for selected_line in selected_lines:
                                    next_lines, _ = add_request_material_to_cart(
                                        next_lines,
                                        selected_line,
                                    )
                                st.session_state["request_material_lines"] = next_lines
                                st.session_state["request_material_table_version"] = (
                                    int(
                                        st.session_state.get(
                                            "request_material_table_version",
                                            0,
                                        )
                                    )
                                    + 1
                                )
                                mark_request_form_dirty()
                                st.session_state["request_cart_added_toast"] = True
                                st.rerun(scope="fragment")

        lines = get_request_material_lines()
    return lines, preview_clicked


def render_change_form(show_title: bool = True) -> None:
    initialize_request_form_state()
    scroll_request_page_to_top_if_needed()
    st.markdown(
        '<span class="pudu-request-page-marker" aria-hidden="true"></span>',
        unsafe_allow_html=True,
    )
    render_mobile_request_toolbar()
    if st.session_state.get("request_form_stage") == "review":
        render_request_review()
        return

    # The request catalog is already backed by the deployed static snapshot.
    # Reading it on every Streamlit rerun is local and must not trigger the
    # fullscreen loading layer while users edit fields or material selections.
    selection_context = get_request_form_selection_context()
    products = list(selection_context["products"])

    if show_title:
        render_page_header(
            "营销物料领取登记",
            "申请工作台",
            "登记客户、收件信息和领取明细，提交后进入审批发放流程。",
            page_key="request",
        )
    message = st.session_state.pop("request_submit_message", "")
    if message:
        st.success(message)
    warning = st.session_state.pop("request_submit_warning", "")
    if warning:
        st.warning(warning)

    with st.container(border=True, key="request_business_section"):
        render_section_header("01", "申请与业务信息", "填写领取申请的基础信息")
        top_cols = st.columns([1.35, 1, 1])
        department, department_id, requester, requester_open_id = render_request_contact_fields(
            top_cols[0]
        )
        customer_label = (
            "代理商名称"
            if st.session_state.get("request_schedule_reason") == "代理商支持"
            else "客户名称"
        )
        required_field_label(top_cols[1], customer_label)
        customer_name = top_cols[1].text_input(
            customer_label,
            key="request_customer_name",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        required_field_label(top_cols[2], "国家")
        country = top_cols[2].text_input(
            "国家",
            key="request_country",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        generated_title = build_request_title(
            st.session_state.get("request_material_usage", ""),
            requester,
        )
        st.markdown(
            f"""
            <div class="pudu-generated-title">
                <span>{escape(ui_text("申请标题"))}</span>
                <strong>{escape(generated_title)}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )

        middle_cols = st.columns(2)
        recipient_hint = (
            "Include the full delivery address and postal code, recipient company, recipient name, and contact details."
            if get_ui_language() == LANGUAGE_EN
            else "包含具体收货地址及邮编，收件公司，收件人及其联系方式"
        )
        required_field_label(middle_cols[0], "收件人信息", recipient_hint)
        recipient_info = middle_cols[0].text_area(
            "收件人信息",
            placeholder="",
            height=64,
            key="request_recipient_info",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        required_field_label(middle_cols[1], "物料用途", (
            "For promotional materials, please specify the exact name of the event."
            if get_ui_language() == LANGUAGE_EN
            else "活动物料请注明具体活动名称"
        ))
        material_usage = middle_cols[1].text_area(
            "物料用途",
            placeholder="",
            height=64,
            key="request_material_usage",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )

        freight_payer = DEFAULT_FREIGHT_PAYER
        from order_scheduling_page import request_schedule_inputs
        scheduling_inputs = request_schedule_inputs(APP_RUNTIME)

    lines, preview_clicked = render_request_material_builder(
        selection_context,
        products,
    )
    if preview_clicked:
        generated_title = build_request_title(material_usage, requester)
        draft = {
            "title": generated_title,
            "department": department,
            "department_id": department_id,
            "requester": requester,
            "requester_open_id": requester_open_id,
            "customer_name": customer_name,
            "country": country,
            "recipient_info": recipient_info,
            "freight_payer": freight_payer,
            "material_usage": material_usage,
            "submission_token": st.session_state["request_submission_token"],
            "lines": [dict(line) for line in lines],
            **scheduling_inputs,
        }
        errors = validate_request_draft(
            draft,
            include_live_schedule_validation=False,
        )
        if errors:
            show_request_validation_toast(errors)
            return
        st.session_state["request_draft_payload"] = draft
        st.session_state["request_form_stage"] = "review"
        st.session_state["request_scroll_to_top"] = True
        mark_request_form_dirty()
        st.rerun()


def initialize_restock_form_state() -> None:
    defaults: dict[str, object] = {
        "restock_operator": "",
        "restock_purchase_order_no": "",
        "restock_note": "",
        "restock_lines": [],
        "restock_form_stage": "edit",
        "restock_material_table_version": 0,
        "restock_material_edit_index": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "restock_submission_token" not in st.session_state:
        st.session_state["restock_submission_token"] = uuid.uuid4().hex


def clear_restock_form_state() -> None:
    for key in list(st.session_state):
        if str(key).startswith("restock_"):
            st.session_state.pop(key, None)


def get_restock_material_lines() -> list[dict[str, object]]:
    raw_lines = st.session_state.get("restock_lines")
    if not isinstance(raw_lines, list):
        raw_lines = []
    lines = [
        {
            "category_definition": str(item.get("category_definition") or "").strip(),
            "product": str(item.get("product") or "").strip(),
            "model": str(item.get("model") or "").strip() or NO_MODEL_TEXT,
            "language": str(item.get("language") or "").strip() or NO_LANGUAGE_TEXT,
            "quantity": int(item.get("quantity") or 0),
                "remark": str(item.get("remark") or "").strip(),
                "order_required": item.get("order_required") is True,
            }
        for item in raw_lines
        if isinstance(item, dict)
    ]
    st.session_state["restock_lines"] = lines
    return lines


def prepare_restock_line_editor_state() -> None:
    load_data = st.session_state.pop("restock_line_editor_load", None)
    if isinstance(load_data, dict):
        st.session_state["restock_material_edit_index"] = int(load_data.get("index", -1))
        st.session_state["restock_line_category_definition"] = str(
            load_data.get("category_definition") or ""
        )
        st.session_state["restock_line_product"] = str(load_data.get("product") or "")
        st.session_state["restock_line_model"] = str(load_data.get("model") or NO_MODEL_TEXT)
        st.session_state["restock_line_language"] = str(
            load_data.get("language") or NO_LANGUAGE_TEXT
        )
        st.session_state["restock_line_quantity"] = max(1, int(load_data.get("quantity") or 1))
        st.session_state["restock_line_remark"] = str(load_data.get("remark") or "")
        return
    if st.session_state.pop("restock_line_editor_reset", False):
        for key in (
            "restock_line_product",
            "restock_line_category_definition",
            "restock_line_model",
            "restock_line_language",
            "restock_line_quantity",
            "restock_line_remark",
        ):
            st.session_state.pop(key, None)
        st.session_state["restock_material_edit_index"] = None


def finish_restock_line_entry(
    session_state: MutableMapping[str, object],
) -> None:
    session_state["restock_material_edit_index"] = None
    session_state.pop("restock_line_editor_reset", None)


def restock_scoped_models(
    selection_context: dict[str, object],
    product: str,
) -> tuple[bool, list[str]]:
    product_key = normalize_option_label(product)
    scoped_models = list(
        dict(selection_context.get("product_models") or {}).get(product_key, [])
    )
    model_options = sort_model_options(scoped_models)
    is_no_model = product_key in set(selection_context.get("no_model_product_keys") or set())
    if is_no_model or not model_options or model_options == [NO_MODEL_TEXT]:
        return True, [NO_MODEL_TEXT]
    return False, model_options


def restock_scoped_languages(
    selection_context: dict[str, object],
    product: str,
    model: str,
) -> tuple[bool, list[str]]:
    product_key = normalize_option_label(product)
    model_key = normalize_option_label(model or NO_MODEL_TEXT)
    is_no_language = product_key in set(
        selection_context.get("no_language_product_keys") or set()
    )
    if is_no_language:
        return True, [NO_LANGUAGE_TEXT]
    scoped_languages = list(
        dict(selection_context.get("product_model_languages") or {}).get(
            (product_key, model_key),
            [],
        )
    )
    language_options = sort_languages(scoped_languages)
    if not language_options:
        return True, [NO_LANGUAGE_TEXT]
    return language_options == [NO_LANGUAGE_TEXT], language_options


def restock_inventory_snapshot(
    selection_context: dict[str, object],
) -> dict[tuple[str, str, str], int]:
    snapshot: dict[tuple[str, str, str], int] = {}
    inventory_df = selection_context.get("inventory_df")
    if not isinstance(inventory_df, pd.DataFrame) or inventory_df.empty:
        return snapshot
    for row in inventory_df.to_dict("records"):
        key = (
            str(row.get("product") or row.get(PRODUCT_COL) or "").strip(),
            str(row.get("model") or row.get(MODEL_COL) or NO_MODEL_TEXT).strip()
            or NO_MODEL_TEXT,
            str(row.get("language") or row.get(LANGUAGE_COL) or NO_LANGUAGE_TEXT).strip()
            or NO_LANGUAGE_TEXT,
        )
        quantity = row.get("quantity", row.get(QTY_COL, 0))
        snapshot[key] = int(quantity or 0)
    return snapshot


def render_restock_material_builder(
    selection_context: dict[str, object],
) -> list[dict[str, object]]:
    prepare_restock_line_editor_state()
    lines = get_restock_material_lines()
    products = list(selection_context.get("products") or [])
    category_definition_by_product = dict(
        selection_context.get("category_definition_by_product") or {}
    )
    category_definitions = list(selection_context.get("category_definitions") or [])
    with st.container(border=True):
        render_section_header(
            "02",
            "采购补库清单",
            f"按品类定义逐条添加现有物料，最多 {MAX_RESTOCK_LINE_COUNT} 种",
        )
        if not products:
            st.error("当前没有可补库的物料，请先刷新数据或在品类管理中创建库存行。")
            return lines

        editor_index_value = st.session_state.get("restock_material_edit_index")
        editor_index = (
            int(editor_index_value)
            if isinstance(editor_index_value, int) and 0 <= editor_index_value < len(lines)
            else None
        )
        editor_cols = st.columns(
            [1.25, 2.05, 1.55, 1.4, 0.8, 1.35, 1.1],
            gap="small",
            vertical_alignment="bottom",
        )
        (
            definition_col,
            product_col,
            model_col,
            language_col,
            quantity_col,
            remark_col,
            action_col,
        ) = editor_cols
        required_field_label(definition_col, "品类定义")
        if not category_definitions:
            category_definitions = [UNDEFINED_CATEGORY_DEFINITION]
        if st.session_state.get("restock_line_category_definition") not in category_definitions:
            st.session_state["restock_line_category_definition"] = category_definitions[0]
        category_definition = definition_col.selectbox(
            "品类定义",
            category_definitions,
            key="restock_line_category_definition",
            label_visibility="collapsed",
        )
        scoped_products = [
            product
            for product in products
            if category_definition_by_product.get(
                product,
                UNDEFINED_CATEGORY_DEFINITION,
            )
            == category_definition
        ]
        if not scoped_products:
            st.error("该品类定义下没有可补库的启用物料。")
            return lines
        required_field_label(product_col, "物料品类")
        if st.session_state.get("restock_line_product") not in scoped_products:
            st.session_state["restock_line_product"] = scoped_products[0]
        product = product_col.selectbox(
            "物料品类",
            scoped_products,
            key="restock_line_product",
            label_visibility="collapsed",
        )
        no_model, model_options = restock_scoped_models(selection_context, product)
        if st.session_state.get("restock_line_model") not in model_options:
            st.session_state["restock_line_model"] = model_options[0]
        required_field_label(model_col, "产品型号")
        model = model_col.selectbox(
            "产品型号",
            model_options,
            key="restock_line_model",
            disabled=no_model,
            label_visibility="collapsed",
        )
        no_language, language_options = restock_scoped_languages(
            selection_context,
            product,
            model,
        )
        if not language_options:
            language_options = [NO_LANGUAGE_TEXT]
        if st.session_state.get("restock_line_language") not in language_options:
            st.session_state["restock_line_language"] = language_options[0]
        required_field_label(language_col, "语种")
        language = language_col.selectbox(
            "语种",
            language_options,
            key="restock_line_language",
            disabled=no_language,
            label_visibility="collapsed",
        )
        required_field_label(quantity_col, "补库数量")
        quantity = quantity_col.number_input(
            "补库数量",
            min_value=1,
            max_value=1_000_000,
            value=1,
            step=1,
            key="restock_line_quantity",
            label_visibility="collapsed",
        )
        remark = remark_col.text_input(
            "明细备注",
            key="restock_line_remark",
            placeholder="可选",
        )
        action_clicked = action_col.button(
            "保存修改" if editor_index is not None else "加入清单",
            key="restock_add_material",
            type="primary",
            icon=":material/save:" if editor_index is not None else ":material/add:",
            disabled=editor_index is None and len(lines) >= MAX_RESTOCK_LINE_COUNT,
            width="stretch",
        )
        if editor_index is not None and action_col.button(
            "取消编辑",
            key="restock_cancel_material_edit",
            type="tertiary",
            icon=":material/close:",
            width="stretch",
        ):
            st.session_state["restock_line_editor_reset"] = True
            st.rerun()

        if action_clicked:
            next_line = {
                "category_definition": category_definition,
                "product": product,
                "model": model or NO_MODEL_TEXT,
                "language": language or NO_LANGUAGE_TEXT,
                "quantity": int(quantity),
                "remark": str(remark or "").strip(),
            }
            duplicate_index = next(
                (
                    index
                    for index, line in enumerate(lines)
                    if request_material_key(line) == request_material_key(next_line)
                    and index != editor_index
                ),
                None,
            )
            if not selection_context_has_inventory_combination(
                selection_context,
                product,
                model,
                language,
            ):
                st.warning("该品类、型号和语种的库存组合不存在，请重新选择。")
            elif duplicate_index is not None:
                st.warning(f"该物料组合已在清单第 {duplicate_index + 1} 行，请直接修改原行。")
            else:
                next_lines = [dict(line) for line in lines]
                if editor_index is None:
                    next_lines.append(next_line)
                else:
                    next_lines[editor_index] = next_line
                st.session_state["restock_lines"] = next_lines
                st.session_state["restock_material_table_version"] = (
                    int(st.session_state.get("restock_material_table_version", 0)) + 1
                )
                finish_restock_line_entry(st.session_state)
                st.rerun()

        lines = get_restock_material_lines()
        st.markdown(
            f"""
            <div class="pudu-material-list-status">
                <span>{escape(ui_text("采购补库清单"))}</span>
                <strong>{len(lines)} / {MAX_RESTOCK_LINE_COUNT}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not lines:
            st.info("尚未添加补库物料。")
            return lines

        table_version = int(st.session_state.get("restock_material_table_version", 0))
        restock_table_df = request_material_table_dataframe(lines).rename(
            columns={"数量": "补库数量"}
        )
        restock_table_df.insert(
            2,
            "品类定义",
            [str(line.get("category_definition") or "") for line in lines],
        )
        edited_df = st.data_editor(
            restock_table_df,
            width="stretch",
            hide_index=True,
            height=min(520, max(140, 38 * (len(lines) + 1) + 22)),
            row_height=34,
            disabled=["序号", "品类定义", "物料品类", "产品型号", "语种"],
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", width="small"),
                "序号": st.column_config.NumberColumn("序号", width="small", format="%d"),
                "品类定义": st.column_config.TextColumn("品类定义", width="small"),
                "物料品类": st.column_config.TextColumn("物料品类", width="large"),
                "产品型号": st.column_config.TextColumn("产品型号", width="medium"),
                "语种": st.column_config.TextColumn("语种", width="medium"),
                "补库数量": st.column_config.NumberColumn(
                    "补库数量",
                    min_value=1,
                    max_value=1_000_000,
                    step=1,
                    format="%d",
                    width="small",
                ),
                "备注": st.column_config.TextColumn("备注", width="medium"),
            },
            key=f"restock_material_table_{table_version}",
        )
        normalized_df = edited_df.rename(columns={"补库数量": "数量"})
        updated_lines, selected_indices = apply_request_material_table_edits(lines, normalized_df)
        if updated_lines != lines:
            st.session_state["restock_lines"] = updated_lines
            lines = updated_lines

        edit_col, delete_col, _ = st.columns([1.1, 1.1, 3])
        if edit_col.button(
            "编辑选中",
            key="restock_edit_selected_material",
            icon=":material/edit:",
            disabled=len(selected_indices) != 1,
            width="stretch",
        ):
            selected_index = selected_indices[0]
            st.session_state["restock_line_editor_load"] = {
                "index": selected_index,
                **lines[selected_index],
            }
            st.session_state["restock_material_table_version"] = table_version + 1
            st.rerun()
        if delete_col.button(
            "删除选中",
            key="restock_delete_selected_material",
            icon=":material/delete:",
            disabled=not selected_indices,
            width="stretch",
        ):
            selected_set = set(selected_indices)
            st.session_state["restock_lines"] = [
                line for index, line in enumerate(lines) if index not in selected_set
            ]
            st.session_state["restock_material_table_version"] = table_version + 1
            if editor_index in selected_set:
                st.session_state["restock_line_editor_reset"] = True
            st.rerun()
    return lines


def restore_restock_form_from_draft(draft: dict[str, object]) -> None:
    st.session_state["restock_operator"] = str(draft.get("operator") or "")
    st.session_state["restock_purchase_order_no"] = str(
        draft.get("purchase_order_no") or ""
    )
    st.session_state["restock_note"] = str(draft.get("note") or "")
    st.session_state["restock_lines"] = [
        dict(line) for line in list(draft.get("lines") or []) if isinstance(line, dict)
    ]
    st.session_state["restock_form_stage"] = "edit"
    st.session_state["restock_material_table_version"] = (
        int(st.session_state.get("restock_material_table_version", 0)) + 1
    )
    st.session_state["restock_line_editor_reset"] = True
    st.session_state.pop("restock_draft_payload", None)


def render_restock_review() -> None:
    draft = st.session_state.get("restock_draft_payload")
    if not isinstance(draft, dict):
        st.session_state["restock_form_stage"] = "edit"
        st.rerun()
    lines = [dict(line) for line in list(draft.get("lines") or []) if isinstance(line, dict)]
    total_quantity = sum(int(line.get("quantity") or 0) for line in lines)
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("补库单号", str(draft.get("restock_no") or "-"))
    metric_b.metric("补库物料种类", f"{len(lines):,}")
    metric_c.metric("补库总数量", f"{total_quantity:,}")
    with st.container(border=True):
        render_section_header("01", "补库信息确认", "请核对补库信息和全部明细后再确认")
        info_cols = st.columns(3)
        render_request_review_field(info_cols[0], "补库人", draft.get("operator"))
        render_request_review_field(info_cols[1], "采购单号", draft.get("purchase_order_no") or "-")
        render_request_review_field(info_cols[2], "补库说明", draft.get("note") or "-")
    with st.container(border=True):
        render_section_header("02", "补库明细预览", f"共 {len(lines)} 种物料")
        preview_df = pd.DataFrame(
            [
                {
                    "序号": index + 1,
                    "品类定义": line.get("category_definition") or UNDEFINED_CATEGORY_DEFINITION,
                    "物料品类": line.get("product") or "",
                    "产品型号": line.get("model") or NO_MODEL_TEXT,
                    "语种": line.get("language") or NO_LANGUAGE_TEXT,
                    "缓存库存": int(line.get("snapshot_quantity") or 0),
                    "补库数量": int(line.get("quantity") or 0),
                    "预计补库后库存": int(line.get("snapshot_quantity") or 0)
                    + int(line.get("quantity") or 0),
                    "备注": line.get("remark") or "",
                }
                for index, line in enumerate(lines)
            ]
        )
        st.dataframe(
            preview_df,
            width="stretch",
            hide_index=True,
            height=min(820, max(150, 38 * (len(preview_df) + 1) + 18)),
            row_height=34,
        )
        st.caption("预览使用当前页面缓存；确认补库时会重新读取飞书实时库存并计算最终数量。")

    back_col, _, confirm_col = st.columns([1.1, 2.2, 1.4])
    if back_col.button(
        "返回修改",
        key="restock_review_back",
        icon=":material/arrow_back:",
        width="stretch",
    ):
        restore_restock_form_from_draft(draft)
        st.rerun()
    if confirm_col.button(
        "确认补库",
        key="restock_review_confirm",
        type="primary",
        icon=":material/add_box:",
        width="stretch",
    ):
        errors = validate_restock_draft(draft)
        if errors:
            st.warning("；".join(errors))
            return
        with fullscreen_data_sync("正在提交数据，请稍后......"):
            try:
                task, _ = enqueue_feishu_background_write(
                    QUEUE_TASK_TYPE_RESTOCK,
                    {"draft": dict(draft)},
                    str(draft.get("restock_no") or ""),
                )
            except Exception as exc:
                st.error("采购补库任务未能进入后台队列，请重试。")
                st.exception(exc)
                return
        restock_no = str(draft.get("restock_no") or "")
        clear_restock_form_state()
        st.session_state["restock_submit_message"] = data_submission_success_message()
        st.rerun()


def render_restock_form() -> None:
    initialize_restock_form_state()
    message = st.session_state.pop("restock_submit_message", "")
    warning = st.session_state.pop("restock_submit_warning", "")
    if message:
        st.success(message)
    if warning:
        st.warning(warning)
    if st.session_state.get("restock_form_stage") == "review":
        render_restock_review()
        return
    with st.spinner("物料数据加载中，请稍后......"):
        selection_context = get_restock_selection_context()
    with st.container(border=True):
        render_section_header("01", "采购补库信息", "填写补库基础信息并逐条添加采购物料")
        info_cols = st.columns([1.2, 1.2, 2.2])
        required_field_label(info_cols[0], "补库人")
        operator = info_cols[0].text_input(
            "补库人",
            key="restock_operator",
            label_visibility="collapsed",
        )
        info_cols[1].markdown(
            f'<div class="pudu-field-label">{escape(ui_text("采购单号"))}</div>',
            unsafe_allow_html=True,
        )
        purchase_order_no = info_cols[1].text_input(
            "采购单号",
            key="restock_purchase_order_no",
            placeholder="可选",
            label_visibility="collapsed",
        )
        info_cols[2].markdown(
            f'<div class="pudu-field-label">{escape(ui_text("补库说明"))}</div>',
            unsafe_allow_html=True,
        )
        note = info_cols[2].text_input(
            "补库说明",
            key="restock_note",
            placeholder="可选",
            label_visibility="collapsed",
        )
        restock_no = build_restock_no(st.session_state["restock_submission_token"])
        st.caption(f"补库单号：{restock_no}")

    lines = render_restock_material_builder(selection_context)
    _, preview_col = st.columns([3, 1.25])
    if preview_col.button(
        "预览并核对补库",
        key="restock_preview",
        type="primary",
        icon=":material/preview:",
        width="stretch",
    ):
        snapshot = restock_inventory_snapshot(selection_context)
        preview_lines = [
            {
                **dict(line),
                "snapshot_quantity": snapshot.get(request_material_key(line), 0),
            }
            for line in lines
        ]
        draft = {
            "restock_no": restock_no,
            "operator": operator,
            "purchase_order_no": purchase_order_no,
            "note": note,
            "submission_token": st.session_state["restock_submission_token"],
            "lines": preview_lines,
        }
        errors = validate_restock_draft(draft)
        if errors:
            st.warning("；".join(errors))
            return
        st.session_state["restock_draft_payload"] = draft
        st.session_state["restock_form_stage"] = "review"
        st.rerun()


def clear_new_category_creation_state() -> None:
    prefixes = (
        "category_name_new",
        "category_zh_page_name_new",
        "category_en_page_name_new",
        "category_status_new",
        "category_request_visible_new",
        "category_definition_new",
        "category_unit_price_new",
        "category_customs_code_new",
        "category_commercial_invoice_name_new",
        "category_packing_list_product_type_new",
        "category_no_model_new",
        "category_no_language_new",
        "category_models_new",
        "category_custom_models_new",
        "category_languages_new",
        "category_custom_languages_new",
        "category_target_values_new_",
        "category_target_revision_new_",
        "category_target_defaults_new_",
        "category_combo_new_",
        "category_batch_targets_new_",
        "category_batch_status_new_",
        "category_apply_batch_status_new_",
        "category_discard_confirm_new_",
        "category_confirm_new",
        "category_submit_new",
        "category_create_preview_",
    )
    for key in list(st.session_state):
        if str(key).startswith(prefixes):
            st.session_state.pop(key, None)
    st.session_state.pop(CATEGORY_CREATE_STAGE_KEY, None)
    st.session_state.pop(CATEGORY_CREATE_DRAFT_KEY, None)


def restore_new_category_creation_state(
    draft: dict,
    target_values: dict[tuple[str, str], dict[str, object]],
) -> None:
    allowed_form_keys = {
        "category_name_new",
        "category_zh_page_name_new",
        "category_en_page_name_new",
        "category_status_new",
        "category_request_visible_new",
        "category_definition_new",
        "category_unit_price_new",
        "category_customs_code_new",
        "category_commercial_invoice_name_new",
        "category_packing_list_product_type_new",
        "category_no_model_new",
        "category_no_language_new",
        "category_models_new",
        "category_custom_models_new",
        "category_languages_new",
        "category_custom_languages_new",
    }
    form_state = draft.get("form_state")
    if isinstance(form_state, dict):
        for key, value in form_state.items():
            normalized_key = str(key)
            if normalized_key in allowed_form_keys:
                st.session_state[normalized_key] = value

    target_state_key = str(draft.get("target_state_key") or "")
    revision_key = str(draft.get("revision_key") or "")
    if target_state_key:
        st.session_state[target_state_key] = target_values
    if revision_key:
        st.session_state[revision_key] = int(st.session_state.get(revision_key, 0) or 0) + 1


def render_category_edit_review() -> None:
    draft = st.session_state.get(CATEGORY_EDIT_DRAFT_KEY)
    if not isinstance(draft, dict):
        st.session_state[CATEGORY_EDIT_STAGE_KEY] = "edit"
        st.rerun()
    rows = category_edit_change_rows(draft)
    changed_rows = [row for row in rows if row["操作"] != "保留"]
    changed_count = len(changed_rows)
    render_section_header("01", "品类修改明细确认", "确认后才会保存至飞书，并向全部启用管理员发送修改卡片")
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("修改明细", f"{changed_count:,}")
    metric_b.metric("目标组合", f"{len(list(draft.get('targets') or [])):,}")
    metric_c.metric("库存差额", f"{int(draft.get('quantity_difference') or 0):+,}")
    with st.container(border=True):
        st.markdown("**品类基础信息变更清单**")
        info_cols = st.columns(4)
        render_request_review_field(info_cols[0], "原品类名称", draft.get("old_product"))
        render_request_review_field(info_cols[1], "修改后名称", draft.get("product"))
        render_request_review_field(info_cols[2], "中文页面名称", draft.get("category_zh_page_name"))
        render_request_review_field(info_cols[3], "英文页面名称", draft.get("category_en_page_name"))
        secondary_cols = st.columns(4)
        render_request_review_field(secondary_cols[0], "品类定义", draft.get("category_definition"))
        render_request_review_field(
            secondary_cols[1],
            "品类状态 / 申领页显示",
            f"{draft.get('category_status')} / {draft.get('category_request_visible')}",
        )
        render_request_review_field(
            secondary_cols[2], "商业发票产品名称", draft.get("commercial_invoice_name")
        )
        render_request_review_field(
            secondary_cols[3], "装箱单产品类型", draft.get("packing_list_product_type")
        )
        st.markdown("**物料主数据变更清单**")
        if changed_rows:
            st.dataframe(
                pd.DataFrame(changed_rows),
                width="stretch",
                hide_index=True,
                height=min(720, max(180, 38 * (len(changed_rows) + 1))),
            )
        else:
            st.info("库存组合没有发生变化；请返回检查是否只修改了品类名称或基础配置。")
    st.info("点击“确认保存修改”后任务将进入后台队列；页面可直接关闭，Worker 完成后会通知管理员。")
    back_col, _, confirm_col = st.columns([1.1, 2.2, 1.5])
    if back_col.button("返回修改", icon=":material/arrow_back:", width="stretch", key="category_edit_review_back"):
        st.session_state[CATEGORY_EDIT_STAGE_KEY] = "edit"
        st.session_state.pop(CATEGORY_EDIT_DRAFT_KEY, None)
        st.rerun()
    if confirm_col.button("确认保存修改", type="primary", icon=":material/check_circle:", width="stretch", key="category_edit_review_confirm"):
        with fullscreen_data_sync("正在提交数据，请稍后......"):
            try:
                task, _ = enqueue_feishu_background_write(
                    QUEUE_TASK_TYPE_CATEGORY_SYNC,
                    {
                        "sync_args": serialize_category_sync_args(dict(draft["sync_args"])),
                        "draft": {key: value for key, value in dict(draft).items() if key != "sync_args"},
                        "notification_kind": "edit",
                    },
                )
            except Exception as exc:
                st.error("品类修改任务未能进入后台队列，请重试。")
                st.exception(exc)
                return
        st.session_state.pop(CATEGORY_EDIT_DRAFT_KEY, None)
        st.session_state[CATEGORY_EDIT_STAGE_KEY] = "edit"
        st.session_state["category_added_message"] = data_submission_success_message()
        st.rerun()


def render_new_category_review() -> None:
    draft = st.session_state.get(CATEGORY_CREATE_DRAFT_KEY)
    if not isinstance(draft, dict):
        st.session_state[CATEGORY_CREATE_STAGE_KEY] = "edit"
        st.rerun()

    targets = [
        dict(target)
        for target in list(draft.get("targets") or [])
        if isinstance(target, dict)
    ]
    expected_keys = [
        (str(target.get("model") or ""), str(target.get("language") or ""))
        for target in targets
    ]
    if not targets or any(not model or not language for model, language in expected_keys):
        st.session_state[CATEGORY_CREATE_STAGE_KEY] = "edit"
        st.session_state.pop(CATEGORY_CREATE_DRAFT_KEY, None)
        st.rerun()

    product = str(draft.get("product") or "")
    category_status = normalize_enabled_status(draft.get("category_status"))
    preview_df = category_inventory_preview_dataframe(targets)

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("目标库存行", f"{len(preview_df):,}")
    metric_b.metric("产品型号数量", f"{len(list(draft.get('models') or [])):,}")
    metric_c.metric("语种数量", f"{len(list(draft.get('languages') or [])):,}")

    with st.container(border=True):
        render_section_header("01", "品类信息确认", "确认基础信息后编辑每一条新增库存行")
        info_cols = st.columns(5)
        render_request_review_field(info_cols[0], "物料品类", product)
        render_request_review_field(info_cols[1], "中文页面名称", draft.get("category_zh_page_name"))
        render_request_review_field(info_cols[2], "英文页面名称", draft.get("category_en_page_name"))
        render_request_review_field(info_cols[3], "品类定义", draft.get("category_definition"))
        render_request_review_field(info_cols[4], "品类启用状态", category_status)
        detail_cols = st.columns(5)
        render_request_review_field(
            detail_cols[0],
            "品类在申领页显示",
            draft.get("category_request_visible"),
        )
        render_request_review_field(
            detail_cols[1],
            "产品型号规则",
            NO_MODEL_TEXT if draft.get("no_model") else f"{len(list(draft.get('models') or []))} 个型号",
        )
        render_request_review_field(
            detail_cols[2],
            "语种规则",
            NO_LANGUAGE_TEXT
            if draft.get("no_language")
            else f"{len(list(draft.get('languages') or []))} 个语种",
        )
        render_request_review_field(
            detail_cols[3], "商业发票产品名称", draft.get("commercial_invoice_name")
        )
        render_request_review_field(
            detail_cols[4], "装箱单产品类型", draft.get("packing_list_product_type")
        )

    with st.container(border=True):
        render_section_header(
            "02",
            "新增库存行预览",
            "逐行填写初始库存数量；确认创建前不会写入飞书",
        )
        disabled_columns = ["操作", "序号", "产品型号", "语种"]
        if category_status == STATUS_INACTIVE:
            disabled_columns.append("启用状态")
        edited_df = st.data_editor(
            preview_df,
            width="stretch",
            hide_index=True,
            num_rows="fixed",
            disabled=disabled_columns,
            height=min(860, max(185, 38 * (len(preview_df) + 1) + 20)),
            row_height=34,
            column_config={
                "序号": st.column_config.NumberColumn("序号", width="small"),
                "产品型号": st.column_config.TextColumn("产品型号", width="medium"),
                "语种": st.column_config.TextColumn("语种", width="medium"),
                "库存数量": st.column_config.NumberColumn(
                    "库存数量",
                    required=True,
                    step=1,
                    format="%d",
                    width="small",
                ),
                "单价": st.column_config.NumberColumn(
                    "单价",
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                    width="small",
                ),
                "海关编码": st.column_config.TextColumn("海关编码", width="medium"),
                "启用状态": st.column_config.SelectboxColumn(
                    "启用状态",
                    options=list(MATERIAL_STATUS_OPTIONS),
                    required=True,
                    width="small",
                ),
                "申领页显示": st.column_config.SelectboxColumn(
                    "申领页显示",
                    options=list(REQUEST_PAGE_VISIBILITY_OPTIONS),
                    required=True,
                    width="small",
                ),
            },
            key=f"category_create_preview_editor_{draft.get('preview_token')}",
        )
        current_total = int(pd.to_numeric(edited_df["库存数量"], errors="coerce").fillna(0).sum())
        st.caption(f"当前共 {len(edited_df):,} 条库存行，初始库存合计 {current_total:,}。")

    try:
        edited_values = category_inventory_preview_values(
            edited_df,
            expected_keys,
            category_status,
        )
        preview_error = ""
    except ValueError as exc:
        edited_values = {}
        preview_error = str(exc)
        st.error(preview_error)

    back_col, _, confirm_col = st.columns([1.1, 2.2, 1.5])
    if back_col.button(
        "返回修改",
        key="category_create_preview_back",
        icon=":material/arrow_back:",
        width="stretch",
    ):
        if preview_error:
            st.warning("请先修正库存行数据后再返回。")
            return
        restore_new_category_creation_state(draft, edited_values)
        st.session_state[CATEGORY_CREATE_STAGE_KEY] = "edit"
        st.session_state.pop(CATEGORY_CREATE_DRAFT_KEY, None)
        st.rerun()

    if confirm_col.button(
        "确认创建品类",
        key="category_create_preview_confirm",
        type="primary",
        icon=":material/check_circle:",
        width="stretch",
    ):
        if preview_error:
            st.warning("请先修正全部库存行后再确认创建。")
            return
        sync_args = dict(
                        old_product="",
                        new_product=product,
                        no_model=bool(draft.get("no_model")),
                        no_language=bool(draft.get("no_language")),
                        target_models=list(draft.get("models") or []),
                        target_languages=list(draft.get("languages") or []),
                        category_definition=str(draft.get("category_definition") or ""),
                        category_zh_page_name=str(draft.get("category_zh_page_name") or product),
                        category_en_page_name=str(draft.get("category_en_page_name") or product),
                        category_status=category_status,
                        category_request_visible=normalize_request_page_visibility(
                            draft.get("category_request_visible")
                        ),
                        category_unit_price=draft.get("category_unit_price"),
                        category_customs_code=str(draft.get("category_customs_code") or ""),
                        commercial_invoice_name=str(
                            draft.get("commercial_invoice_name") or ""
                        ),
                        packing_list_product_type=str(
                            draft.get("packing_list_product_type") or ""
                        ),
                        target_values=edited_values,
                    )
        notification_draft = {
                **dict(draft),
                "product": product,
                "category_status": category_status,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        with fullscreen_data_sync("正在提交数据，请稍后......"):
            try:
                task, _ = enqueue_feishu_background_write(
                    QUEUE_TASK_TYPE_CATEGORY_SYNC,
                    {"sync_args": serialize_category_sync_args(sync_args), "draft": notification_draft, "notification_kind": "create"},
                )
            except Exception as exc:
                st.error("品类创建任务未能进入后台队列，请重试。")
                st.exception(exc)
                return
        clear_new_category_creation_state()
        st.session_state["category_added_message"] = data_submission_success_message()
        st.rerun()


def category_delete_blockers(records: list[dict]) -> list[str]:
    return []


def update_category_inventory_counts(category: dict, remaining_records: list[dict]) -> None:
    models = unique_preserve(
        [str(record.get("model") or NO_MODEL_TEXT) for record in remaining_records]
    )
    languages = unique_preserve(
        [str(record.get("language") or NO_LANGUAGE_TEXT) for record in remaining_records]
    )
    feishu_update_record_fields(
        CATEGORY_TABLE_NAME,
        str(category.get("record_id") or ""),
        {
            "库存行数": len(remaining_records),
            "产品型号数量": len(models),
            "语种数量": len(languages),
        },
    )


def category_delete_preview_dataframe(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "操作": "删除",
                "物料编码": str(record.get("material_code") or "-"),
                "物料品类": str(record.get("category") or ""),
                "产品型号": str(record.get("model") or NO_MODEL_TEXT),
                "语种": str(record.get("language") or NO_LANGUAGE_TEXT),
                "库存数量": int(record.get("quantity") or 0),
                "单价": float(record.get("unit_price") or 0),
                "启用状态": normalize_enabled_status(record.get("status")),
                "申领页显示": normalize_request_page_visibility(
                    record.get("request_visible")
                ),
            }
            for record in records
        ],
        columns=[
            "操作",
            "物料编码",
            "物料品类",
            "产品型号",
            "语种",
            "库存数量",
            "单价",
            "启用状态",
            "申领页显示",
        ],
    )


def category_delete_record_signature(record: dict) -> tuple[object, ...]:
    return (
        str(record.get("record_id") or ""),
        str(record.get("material_code") or ""),
        str(record.get("category") or ""),
        str(record.get("model") or NO_MODEL_TEXT),
        str(record.get("language") or NO_LANGUAGE_TEXT),
        int(record.get("quantity") or 0),
        float(record.get("unit_price") or 0),
        normalize_enabled_status(record.get("status")),
        normalize_request_page_visibility(record.get("request_visible")),
    )


def category_delete_changed_records(
    preview_records: list[dict],
    current_records: list[dict],
) -> list[str]:
    preview_by_id = {
        str(record.get("record_id") or ""): category_delete_record_signature(record)
        for record in preview_records
        if str(record.get("record_id") or "")
    }
    current_by_id = {
        str(record.get("record_id") or ""): category_delete_record_signature(record)
        for record in current_records
        if str(record.get("record_id") or "")
    }
    changed: list[str] = []
    for record_id, preview_signature in preview_by_id.items():
        current_signature = current_by_id.get(record_id)
        if current_signature != preview_signature:
            changed.append(str(preview_signature[1] or record_id))
    return changed


def category_delete_category_blockers(
    category_names: list[str],
    category_by_name: dict[str, dict],
    inventory_records: list[dict],
) -> list[str]:
    return [
        f"{category_name}（品类已不存在）"
        for category_name in category_names
        if category_name not in category_by_name
    ]


def category_delete_material_scope(
    records: list[dict],
    selected_models: list[str],
    selected_languages: list[str],
) -> list[dict]:
    model_set = set(selected_models)
    language_set = set(selected_languages)
    if not model_set and not language_set:
        return []
    return [
        record
        for record in records
        if (
            not model_set
            or str(record.get("model") or NO_MODEL_TEXT) in model_set
        )
        and (
            not language_set
            or str(record.get("language") or NO_LANGUAGE_TEXT) in language_set
        )
    ]


def start_category_delete_review(
    *,
    delete_kind: str,
    category_names: list[str],
    records: list[dict],
) -> None:
    st.session_state[CATEGORY_DELETE_DRAFT_KEY] = {
        "delete_kind": delete_kind,
        "category_names": unique_preserve(category_names),
        "record_ids": unique_preserve(
            [str(record.get("record_id") or "") for record in records if str(record.get("record_id") or "")]
        ),
        "records": [dict(record) for record in records],
        "previewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    st.session_state[CATEGORY_DELETE_STAGE_KEY] = "review"


def clear_category_delete_state() -> None:
    st.session_state.pop(CATEGORY_DELETE_DRAFT_KEY, None)
    st.session_state[CATEGORY_DELETE_STAGE_KEY] = "edit"
    for key in list(st.session_state):
        if str(key).startswith("category_delete_") and str(key) not in {
            CATEGORY_DELETE_STAGE_KEY,
            CATEGORY_DELETE_DRAFT_KEY,
        }:
            st.session_state.pop(key, None)


def execute_category_delete(
    draft: dict[str, object],
    *,
    notify_admins: bool = True,
) -> dict[str, int]:
    delete_kind = str(draft.get("delete_kind") or "")
    category_names = [str(value) for value in list(draft.get("category_names") or [])]
    preview_records = [dict(row) for row in list(draft.get("records") or []) if isinstance(row, dict)]
    refresh_page_cache_tables((CATEGORY_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME, REQUEST_LINE_TABLE_NAME, GIFT_PROJECT_TABLE_NAME))
    categories = load_feishu_category_records()
    inventory_records = load_feishu_inventory_records()
    category_by_name = {str(item.get("category") or ""): item for item in categories}
    if delete_kind == "categories":
        blockers = category_delete_category_blockers(category_names, category_by_name, inventory_records)
        current_records = [row for row in inventory_records if str(row.get("category") or "") in set(category_names)]
        if {str(row.get("record_id") or "") for row in preview_records} != {str(row.get("record_id") or "") for row in current_records}:
            blockers.append("预览后品类下的物料行范围已变化")
    else:
        record_ids = {str(value) for value in list(draft.get("record_ids") or [])}
        current_records = [row for row in inventory_records if str(row.get("record_id") or "") in record_ids]
        blockers = category_delete_blockers(current_records)
        if len(record_ids) != len(current_records):
            blockers.append("部分物料行已被其他操作修改或删除")
    changed = category_delete_changed_records(preview_records, current_records)
    if changed:
        blockers.append("预览后数据已变化：" + "、".join(changed[:8]))
    if blockers:
        raise RuntimeError("删除前检查未通过：" + "；".join(blockers[:8]))
    if delete_kind == "categories":
        for name in category_names:
            delete_feishu_category(name, str(category_by_name[name].get("record_id") or ""))
    else:
        deleted_ids = {str(row.get("record_id") or "") for row in current_records}
        for row in current_records:
            delete_feishu_inventory_item(str(row.get("record_id") or ""))
        for name in category_names:
            category = category_by_name.get(name)
            if category:
                update_category_inventory_counts(category, [row for row in inventory_records if str(row.get("category") or "") == name and str(row.get("record_id") or "") not in deleted_ids])
    notified = 0
    if notify_admins:
        notice = {
            **draft,
            "records": current_records,
            "deleted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        notified = notify_enabled_admins_of_category_delete(notice)
    return {"deleted_count": len(current_records), "notification_count": notified}


def render_category_delete_review() -> None:
    draft = st.session_state.get(CATEGORY_DELETE_DRAFT_KEY)
    if not isinstance(draft, dict):
        st.session_state[CATEGORY_DELETE_STAGE_KEY] = "edit"
        st.rerun()
    delete_kind = str(draft.get("delete_kind") or "material_rows")
    category_names = [str(value) for value in list(draft.get("category_names") or [])]
    records = [dict(record) for record in list(draft.get("records") or []) if isinstance(record, dict)]
    preview_df = category_delete_preview_dataframe(records)

    render_section_header(
        "01",
        "删除内容确认",
        "核对全部删除明细；最终确认时会重新读取飞书并检查删除范围是否发生变化",
    )
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("删除类型", "整品类" if delete_kind == "categories" else "物料行")
    metric_b.metric("涉及品类", f"{len(category_names):,}")
    metric_c.metric("物料行", f"{len(records):,}")
    with st.container(border=True):
        st.markdown("**涉及品类**")
        st.write("、".join(category_names) or "-")
        if preview_df.empty:
            st.info("所选品类没有物料行，确认后只删除品类记录。")
        else:
            st.dataframe(
                preview_df,
                width="stretch",
                hide_index=True,
                height=min(720, max(180, 38 * (len(preview_df) + 1))),
            )
    st.error(
        "删除操作不可撤销。库存数量、库存流水、申请明细和项目关联不会阻止删除；"
        "关联历史记录不会被联动删除。"
    )
    confirmed = st.checkbox(
        "我已核对以上全部删除明细，并确认执行不可撤销的删除操作",
        key="category_delete_review_confirmed",
    )
    back_col, _, confirm_col = st.columns([1.1, 2.2, 1.6])
    if back_col.button(
        "返回修改",
        icon=":material/arrow_back:",
        width="stretch",
        key="category_delete_review_back",
    ):
        st.session_state[CATEGORY_DELETE_STAGE_KEY] = "edit"
        st.session_state.pop(CATEGORY_DELETE_DRAFT_KEY, None)
        st.rerun()
    if confirm_col.button(
        "确认删除",
        type="primary",
        icon=":material/delete_forever:",
        width="stretch",
        disabled=not confirmed,
        key="category_delete_review_submit",
    ):
        with fullscreen_data_sync("正在提交数据，请稍后......"):
            try:
                task, _ = enqueue_feishu_background_write(
                    QUEUE_TASK_TYPE_CATEGORY_DELETE,
                    {"draft": dict(draft)},
                )
            except Exception as exc:
                st.error("删除任务未能进入后台队列，请重试。")
                st.exception(exc)
                return
        clear_category_delete_state()
        deleted_label = (
            f"{len(category_names)} 个物料品类"
            if delete_kind == "categories"
            else f"{len(records)} 条物料行"
        )
        st.session_state["category_added_message"] = data_submission_success_message()
        st.rerun()


def render_category_delete_workspace(
    categories: list[dict],
    inventory_records: list[dict],
) -> None:
    st.warning("当前为删除模式。选择内容后会先进入删除预览，确认前不会写入飞书。")
    selected_category, _ = render_category_option_pool(
        category_pool_summary(categories, inventory_records),
        selected=None,
        key="category_delete_category_pool",
        multi=False,
        danger=True,
        compact=True,
        grouped=True,
    )
    selected_category_name = str(selected_category or "")
    selected_category_names = [selected_category_name] if selected_category_name else []
    st.caption(
        f"已选择品类：{selected_category_name}"
        if selected_category_name
        else "请选择 1 个品类。"
    )
    category_by_name = {str(category.get("category") or ""): category for category in categories}

    if selected_category_name:
        selected_name = selected_category_name
        selected_category = category_by_name[selected_name]
        category_records = [
            record
            for record in inventory_records
            if str(record.get("category") or "") == selected_name
        ]
        st.markdown("**选择要删除的型号和语种**")
        model_column, language_column = st.columns(2, gap="small")
        with model_column:
            st.caption("产品型号（可多选）")
            selected_models, _ = render_category_option_pool(
                category_model_pool_summary(category_records),
                selected=[],
                key=f"category_delete_model_pool_{selected_category['record_id']}",
                multi=True,
                danger=True,
                compact=True,
            )
        with language_column:
            st.caption("语种（可多选）")
            selected_languages, _ = render_category_option_pool(
                category_language_pool_summary(category_records),
                selected=[],
                key=f"category_delete_language_pool_{selected_category['record_id']}",
                multi=True,
                danger=True,
                compact=True,
            )
        selected_model_names = [str(value) for value in list(selected_models or [])]
        selected_language_names = [str(value) for value in list(selected_languages or [])]
        delete_scope = category_delete_material_scope(
            category_records,
            selected_model_names,
            selected_language_names,
        )
        st.caption(
            f"已选择 {len(selected_model_names)} 个型号、{len(selected_language_names)} 个语种，"
            f"对应 {len(delete_scope)} 条物料行。"
        )
        if delete_scope:
            st.caption(
                f"准备删除 {len(delete_scope)} 条物料行；点击后先进入明细预览。"
            )
            if st.button(
                "预览删除所选型号和语种对应物料行",
                icon=":material/preview:",
                type="primary",
                width="stretch",
                key=f"category_delete_rows_{selected_category['record_id']}",
            ):
                blockers = category_delete_blockers(delete_scope)
                if blockers:
                    st.error("以下物料行不能删除：" + "；".join(blockers[:8]))
                else:
                    start_category_delete_review(
                        delete_kind="material_rows",
                        category_names=[selected_name],
                        records=delete_scope,
                    )
                    st.rerun()
        elif selected_model_names or selected_language_names:
            st.warning("当前选择的型号与语种组合没有对应物料行。")

    if selected_category_names:
        st.divider()
        st.caption("删除整个品类时，会同时删除其全部物料行；点击后先进入完整预览。")
        if st.button(
            f"预览删除所选品类（{len(selected_category_names)}）",
            icon=":material/preview:",
            width="stretch",
            key="category_delete_categories",
        ):
            blocked = category_delete_category_blockers(
                selected_category_names,
                category_by_name,
                inventory_records,
            )
            if blocked:
                st.error("以下品类不能删除：" + "；".join(blocked[:8]))
            else:
                start_category_delete_review(
                    delete_kind="categories",
                    category_names=selected_category_names,
                    records=[
                        record
                        for record in inventory_records
                        if str(record.get("category") or "") in set(selected_category_names)
                    ],
                )
                st.rerun()


def render_dimension_management_page(kind: str) -> None:
    config = dimension_management_config(kind)
    label = str(config["label"])
    table_name = str(config["table"])
    state_prefix = f"dimension_management_{kind}"
    draft_key = f"{state_prefix}_draft"
    message_key = f"{state_prefix}_message"
    message = st.session_state.pop(message_key, "")
    if message:
        st.success(message)
    draft = st.session_state.get(draft_key)
    if isinstance(draft, dict):
        operation_labels = {"create": "新增", "edit": "编辑", "delete": "删除"}
        operation = str(draft.get("operation") or "")
        render_section_header(
            "02",
            f"确认{operation_labels.get(operation, '')}{label}",
            "确认后任务将进入后台队列，页面可直接关闭。",
        )
        with st.container(border=True):
            preview_cols = st.columns(3)
            render_request_review_field(preview_cols[0], "操作", operation_labels.get(operation, operation))
            render_request_review_field(preview_cols[1], f"{label}名称", draft.get("name"))
            render_request_review_field(preview_cols[2], "启用状态", draft.get("status"))
            if kind == "model" and operation != "delete":
                model_detail_cols = st.columns(4)
                render_request_review_field(model_detail_cols[0], "产品线", draft.get("product_line") or "-")
                render_request_review_field(model_detail_cols[1], MODEL_TYPE_FIELD, draft.get("model_type"))
                render_request_review_field(model_detail_cols[2], "中文页面名称", draft.get("zh_page_name"))
                render_request_review_field(model_detail_cols[3], "英文页面名称", draft.get("en_page_name"))
            if operation == "delete":
                st.warning(f"删除{label}时，会同时删除所有引用该{label}的物料主数据。此操作不可撤销。")
            changes = [dict(item) for item in list(draft.get("changes") or []) if isinstance(item, dict)]
            st.markdown("**物料主数据变更清单**")
            if changes:
                st.dataframe(
                    dimension_change_dataframe(changes),
                    width="stretch", hide_index=True,
                    height=min(720, max(180, 38 * (len(changes) + 1))),
                )
            else:
                st.info("关联物料组合没有变化，本次只保存基础信息。")
        back_col, _, confirm_col = st.columns([1.1, 2.2, 1.45])
        if back_col.button("返回修改", key=f"{state_prefix}_back", icon=":material/arrow_back:", width="stretch"):
            st.session_state.pop(draft_key, None)
            st.rerun()
        if confirm_col.button(
            f"确认{operation_labels.get(operation, '')}",
            key=f"{state_prefix}_confirm",
            type="primary",
            icon=":material/send:",
            width="stretch",
        ):
            with fullscreen_data_sync("正在提交数据，请稍后......"):
                try:
                    task, _ = enqueue_feishu_background_write(
                        QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT,
                        {"draft": dict(draft)},
                    )
                except Exception as exc:
                    st.error(f"{label}管理任务未能进入后台队列，请重试。")
                    st.exception(exc)
                    return
            st.session_state.pop(draft_key, None)
            for key in list(st.session_state):
                if str(key).startswith(f"{state_prefix}_{operation}_association"):
                    st.session_state.pop(key, None)
            st.session_state[message_key] = data_submission_success_message()
            st.rerun()
        return

    with st.spinner(f"{label}数据加载中，请稍后......"):
        records = dimension_management_records(kind, safe_feishu_rows(table_name))
        counterpart_kind = "language" if kind == "model" else "model"
        counterpart_config = dimension_management_config(counterpart_kind)
        counterpart_records = dimension_management_records(
            counterpart_kind,
            safe_feishu_rows(str(counterpart_config["table"])),
        )
        categories = load_feishu_category_records()
        inventory_records = (
            load_cultural_dimension_inventory_records()
            if kind == "region"
            else load_feishu_inventory_records()
        )
    render_section_header("01", f"{label}管理", f"新增、编辑或删除{label}，提交前需核对变更。")
    mode = st.segmented_control(
        "操作类型",
        ["＋ 新增", "✎ 编辑", "－ 删除"],
        key=f"{state_prefix}_mode",
        label_visibility="collapsed",
        width="stretch",
        default="✎ 编辑",
    ) or "✎ 编辑"
    operation = {"＋ 新增": "create", "✎ 编辑": "edit", "－ 删除": "delete"}[mode]
    selected: dict[str, str] | None = None
    if operation != "create":
        if not records:
            st.info(f"暂无可{('编辑' if operation == 'edit' else '删除')}的{label}。")
            return
        selected_id = st.selectbox(
            f"选择{label}",
            [item["record_id"] for item in records],
            format_func=lambda value: next(
                (f"{item['name']} · {item['status']}" for item in records if item["record_id"] == value),
                str(value),
            ),
            key=f"{state_prefix}_selected_id",
        )
        selected = next(item for item in records if item["record_id"] == selected_id)
    default_name = str((selected or {}).get("name") or "")
    default_status = str((selected or {}).get("status") or STATUS_ACTIVE)
    default_zh_page_name = str((selected or {}).get("zh_page_name") or default_name)
    default_en_page_name = str((selected or {}).get("en_page_name") or default_name)
    default_product_line = str((selected or {}).get("product_line") or "")
    default_model_type = str((selected or {}).get("model_type") or MODEL_TYPE_REGULAR)
    if operation == "delete":
        st.error(f"删除该{label}会同时删除引用它的物料主数据，请在预览后仔细确认。")
        name = default_name
        status = default_status
        zh_page_name = default_zh_page_name
        en_page_name = default_en_page_name
        product_line = default_product_line
        model_type = default_model_type
    else:
        form_cols = st.columns([2.2, 1])
        name = form_cols[0].text_input(
            f"{label}名称",
            value=default_name,
            key=f"{state_prefix}_{operation}_name_{(selected or {}).get('record_id', 'new')}",
        )
        status = form_cols[1].selectbox(
            "启用状态",
            MATERIAL_STATUS_OPTIONS,
            index=list(MATERIAL_STATUS_OPTIONS).index(default_status),
            key=f"{state_prefix}_{operation}_status_{(selected or {}).get('record_id', 'new')}",
        )
        if kind == "model":
            model_detail_cols = st.columns(4)
            product_line = model_detail_cols[0].text_input(
                "产品线",
                value=default_product_line,
                placeholder="例如：IR、CR、SR、GR",
                key=f"{state_prefix}_{operation}_product_line_{(selected or {}).get('record_id', 'new')}",
            )
            model_type = model_detail_cols[1].selectbox(
                MODEL_TYPE_FIELD,
                MODEL_TYPE_OPTIONS,
                index=MODEL_TYPE_OPTIONS.index(default_model_type),
                key=f"{state_prefix}_{operation}_model_type_{(selected or {}).get('record_id', 'new')}",
            )
            zh_page_name = model_detail_cols[2].text_input(
                "中文页面名称",
                value=default_zh_page_name,
                key=f"{state_prefix}_{operation}_zh_page_name_{(selected or {}).get('record_id', 'new')}",
            )
            en_page_name = model_detail_cols[3].text_input(
                "英文页面名称",
                value=default_en_page_name,
                key=f"{state_prefix}_{operation}_en_page_name_{(selected or {}).get('record_id', 'new')}",
            )
        else:
            zh_page_name = name
            en_page_name = name
            product_line = ""
            model_type = ""
    current_name = default_name if operation != "create" else str(name or "").strip()
    if operation == "delete":
        selected_keys = [
            [str(row.get("category") or ""), str(row.get("language") if kind == "model" else row.get("model") or "")]
            for row in inventory_records
            if normalize_option_label(str(row.get("model") if kind == "model" else (row.get("region") if kind == "region" else row.get("language")) or "")).casefold()
            == normalize_option_label(current_name).casefold()
        ]
    else:
        category_names = dimension_association_category_names(kind, categories, current_name)
        counterpart_names = unique_preserve(
            [str(item.get("name") or "") for item in counterpart_records]
            + [
            str(row.get("language") if kind == "model" else row.get("model") or "")
            for row in inventory_records
            if str(row.get("language") if kind == "model" else row.get("model") or "").strip()
            ]
        )
        existing_keys = {
            (str(row.get("category") or ""), str(row.get("language") if kind == "model" else row.get("model") or ""))
            for row in inventory_records
            if normalize_option_label(str(row.get("model") if kind == "model" else (row.get("region") if kind == "region" else row.get("language")) or "")).casefold()
            == normalize_option_label(default_name).casefold()
        }
        counterpart_column = "语种" if kind == "model" else "产品型号"
        selection_state_key = (
            f"{state_prefix}_{operation}_association_selection_"
            f"{(selected or {}).get('record_id', 'new')}"
        )
        if selection_state_key not in st.session_state:
            st.session_state[selection_state_key] = [list(item) for item in sorted(existing_keys)]
        selected_association_keys = {
            (str(item[0]), str(item[1]))
            for item in list(st.session_state.get(selection_state_key) or [])
            if isinstance(item, (list, tuple)) and len(item) >= 2
        }
        association_df = pd.DataFrame([
            {"关联": (category, counterpart) in selected_association_keys, "物料品类": category,
             counterpart_column: counterpart}
            for category in category_names for counterpart in counterpart_names
        ])
        with st.container(border=True):
            st.markdown(f"**选择该{label}需要关联的物料组合**")
            st.caption("勾选后会新增缺失的物料主数据行；取消勾选会在确认后删除已有关联行。")
            association_query = st.text_input(
                "搜索关联物料组合",
                placeholder=f"输入物料品类或{counterpart_column}名称",
                key=f"{state_prefix}_{operation}_association_search_{(selected or {}).get('record_id', 'new')}",
            )
            filtered_association_df = filter_dimension_association_dataframe(
                association_df,
                association_query,
                counterpart_column,
            )
            st.caption(f"当前显示 {len(filtered_association_df)} / {len(association_df)} 条组合；搜索不会清除已勾选内容。")
            if filtered_association_df.empty:
                st.info("没有找到匹配的物料组合，请更换关键词。")
            else:
                query_token = hashlib.sha256(
                    str(association_query or "").strip().casefold().encode("utf-8")
                ).hexdigest()[:12]
                editor_state_key = (
                    f"{state_prefix}_{operation}_associations_"
                    f"{(selected or {}).get('record_id', 'new')}_{query_token}"
                )
                row_keys = [
                    [str(row["物料品类"]), str(row[counterpart_column])]
                    for row in filtered_association_df.to_dict("records")
                ]
                st.data_editor(
                    filtered_association_df, width="stretch", hide_index=True, num_rows="fixed",
                    disabled=["物料品类", counterpart_column],
                    height=min(720, max(180, 35 * (len(filtered_association_df) + 1))),
                    key=editor_state_key,
                    on_change=persist_dimension_association_edits,
                    args=(selection_state_key, editor_state_key, row_keys),
                )
        selected_keys = [list(item) for item in sorted(selected_association_keys)]
    _, preview_col = st.columns([3, 1.25])
    if preview_col.button(
        f"预览{ {'create': '新增', 'edit': '修改', 'delete': '删除'}[operation] }",
        key=f"{state_prefix}_{operation}_preview",
        type="primary",
        icon=":material/preview:",
        width="stretch",
    ):
        normalized_name = str(name or "").strip()
        if not normalized_name:
            st.warning(f"请填写{label}名称。")
            return
        duplicate = next(
            (
                item for item in records
                if normalize_option_label(item["name"]).casefold()
                == normalize_option_label(normalized_name).casefold()
                and item["record_id"] != str((selected or {}).get("record_id") or "")
            ),
            None,
        )
        if operation != "delete" and duplicate:
            st.warning(f"该{label}名称已经存在。")
            return
        st.session_state[draft_key] = {
            "kind": kind,
            "operation": operation,
            "record_id": str((selected or {}).get("record_id") or ""),
            "old_name": default_name,
            "old_status": default_status,
            "old_zh_page_name": default_zh_page_name,
            "old_en_page_name": default_en_page_name,
            "old_product_line": default_product_line,
            "old_model_type": default_model_type,
            "name": normalized_name,
            "status": status,
            "zh_page_name": str(zh_page_name or normalized_name).strip(),
            "en_page_name": str(en_page_name or normalized_name).strip(),
            "product_line": str(product_line or "").strip(),
            "model_type": str(model_type or "").strip(),
            "selected_keys": selected_keys,
            "changes": dimension_association_plan(
                kind, operation, default_name or normalized_name, normalized_name,
                selected_keys, inventory_records, categories,
            ),
        }
        st.rerun()


def render_add_category_form() -> None:
    if st.session_state.get(CATEGORY_DELETE_STAGE_KEY) == "review":
        render_category_delete_review()
        return
    if st.session_state.get(CATEGORY_EDIT_STAGE_KEY) == "review":
        render_category_edit_review()
        return
    if st.session_state.get(CATEGORY_CREATE_STAGE_KEY) == "review":
        render_new_category_review()
        return
    with st.spinner("物料数据加载中，请稍后......"):
        options = load_options()
        categories = load_feishu_category_records()
        inventory_records = load_feishu_inventory_records()
        cultural_inventory_records = load_cultural_dimension_inventory_records()

    message = st.session_state.pop("category_added_message", "") or st.session_state.pop(
        "category_admin_message", ""
    )
    if message:
        st.success(message)
    warning = st.session_state.pop("category_admin_warning", "")
    if warning:
        st.warning(warning)

    render_section_header("01", "物料品类管理", "新增、编辑或删除品类，并在提交前核对全部变更")
    if st.session_state.get("category_management_mode") not in {
        "＋ 新增",
        "✎ 编辑",
        "－ 删除",
    }:
        st.session_state["category_management_mode"] = "✎ 编辑"
    mode = st.segmented_control(
        "操作类型",
        ["＋ 新增", "✎ 编辑", "－ 删除"],
        key="category_management_mode",
        label_visibility="collapsed",
        width="stretch",
    ) or "✎ 编辑"
    is_edit = mode == "✎ 编辑"
    category_by_name = {str(item["category"]): item for item in categories}

    selected_category: dict | None = None
    if mode == "－ 删除":
        render_category_delete_workspace(categories, inventory_records)
        return
    if is_edit:
        if not category_by_name:
            st.info("暂无可编辑的物料品类，请先新增品类。")
            return
        default_category = str(
            st.session_state.get("category_management_selected_name")
            or next(iter(category_by_name))
        )
        category_names = list(category_by_name)
        if default_category not in category_by_name:
            default_category = category_names[0]
            st.session_state["category_management_selected_name"] = default_category
        selected_name = st.selectbox(
            "选择物料品类",
            category_names,
            index=category_names.index(default_category),
            key="category_management_selected_name",
        )
        selected_category = category_by_name[selected_name]
        selected_pool = (
            cultural_inventory_records
            if str(selected_category.get("category_definition") or "") == CATEGORY_DEFINITION_CULTURAL
            else inventory_records
        )
        selected_record_count = sum(1 for record in selected_pool if record["category"] == selected_name)
        st.caption(f"当前品类共有 {selected_record_count} 条库存组合，修改后将先进入明细确认页。")

    category_id = str((selected_category or {}).get("record_id") or "")
    old_product = str((selected_category or {}).get("category") or "")
    selected_is_cultural = str((selected_category or {}).get("category_definition") or "") == CATEGORY_DEFINITION_CULTURAL
    current_records = [record for record in (cultural_inventory_records if selected_is_cultural else inventory_records) if record["category"] == old_product] if is_edit else []
    current_models = unique_preserve([str(record["model"] or NO_MODEL_TEXT) for record in current_records])
    current_languages = unique_preserve([
        str(record.get("region") if selected_is_cultural else record.get("language") or "")
        for record in current_records
        if str(record.get("region") if selected_is_cultural else record.get("language") or "").strip()
    ])
    current_no_model = bool((selected_category or {}).get("no_model")) or (
        bool(current_models) and set(current_models) == {NO_MODEL_TEXT}
    )
    current_no_language = bool((selected_category or {}).get("no_language")) or (
        bool(current_languages) and set(current_languages) == {NO_LANGUAGE_TEXT}
    )
    current_category_status = normalize_enabled_status((selected_category or {}).get("status"))
    current_category_request_visible = normalize_request_page_visibility(
        (selected_category or {}).get("request_visible")
        if selected_category is not None
        else REQUEST_PAGE_VISIBLE_VALUE
    )
    current_category_definition = str(
        (selected_category or {}).get("category_definition")
        or CATEGORY_DEFINITION_PRINT
    )
    current_category_zh_page_name = str(
        (selected_category or {}).get("zh_page_name") or old_product
    )
    current_category_en_page_name = str(
        (selected_category or {}).get("en_page_name") or old_product
    )
    current_category_unit_price = (selected_category or {}).get("unit_price")
    current_category_customs_code = str((selected_category or {}).get("customs_code") or "")
    current_commercial_invoice_name = str(
        (selected_category or {}).get("commercial_invoice_name") or ""
    )
    current_packing_list_product_type = str(
        (selected_category or {}).get("packing_list_product_type") or ""
    )
    editor_key = category_id or "new"
    pool_edit_dimension = ""
    pool_focus_model = ""
    pool_focus_language = ""

    with st.container(border=True):
        product_key = f"category_name_{editor_key}"
        product = st.text_input(
            "物料品类名称 *",
            placeholder="例如：新版宣传册(New Brochure)",
            key=product_key,
            **({} if product_key in st.session_state else {"value": old_product}),
        ).strip()
        page_name_zh_col, page_name_en_col = st.columns(2)
        category_zh_page_name_key = f"category_zh_page_name_{editor_key}"
        category_zh_page_name = page_name_zh_col.text_input(
            "中文页面名称 *",
            placeholder="例如：产品单页",
            key=category_zh_page_name_key,
            **(
                {}
                if category_zh_page_name_key in st.session_state
                else {"value": current_category_zh_page_name}
            ),
        ).strip()
        category_en_page_name_key = f"category_en_page_name_{editor_key}"
        category_en_page_name = page_name_en_col.text_input(
            "英文页面名称 *",
            placeholder="例如：Product Flyer",
            key=category_en_page_name_key,
            **(
                {}
                if category_en_page_name_key in st.session_state
                else {"value": current_category_en_page_name}
            ),
        ).strip()
        metadata_definition_col, metadata_status_col, metadata_visibility_col = st.columns(
            3,
            vertical_alignment="bottom",
        )
        shipping_name_col, shipping_type_col = st.columns([2, 1])
        commercial_invoice_name_key = f"category_commercial_invoice_name_{editor_key}"
        commercial_invoice_name = shipping_name_col.text_input(
            "商业发票产品名称 *",
            placeholder="例如：Product Flyer",
            key=commercial_invoice_name_key,
            **(
                {}
                if commercial_invoice_name_key in st.session_state
                else {"value": current_commercial_invoice_name}
            ),
        ).strip()
        packing_type_options = unique_preserve(
            list(PACKING_LIST_PRODUCT_TYPE_OPTIONS)
            + ([current_packing_list_product_type] if current_packing_list_product_type else [])
        )
        packing_list_product_type_key = f"category_packing_list_product_type_{editor_key}"
        packing_list_product_type = shipping_type_col.selectbox(
            "装箱单产品类型",
            packing_type_options,
            key=packing_list_product_type_key,
            **(
                {}
                if packing_list_product_type_key in st.session_state
                else {
                    "index": packing_type_options.index(current_packing_list_product_type)
                    if current_packing_list_product_type in packing_type_options
                    else 0
                }
            ),
        )
        st.caption("商业发票产品名称为发货模板下拉选项；选择后会同步带出装箱单类型、单价和海关编码。")
        metadata_price_col, metadata_customs_col = st.columns(2)
        category_definition_options = unique_preserve(
            list(CATEGORY_DEFINITION_OPTIONS)
            + [
                str(item.get("category_definition") or "").strip()
                for item in categories
                if str(item.get("category_definition") or "").strip()
            ]
        )
        category_definition_key = f"category_definition_{editor_key}"
        category_definition = metadata_definition_col.selectbox(
            "品类定义 *",
            category_definition_options,
            key=category_definition_key,
            **(
                {}
                if category_definition_key in st.session_state
                else {
                    "index": category_definition_options.index(
                        current_category_definition
                        if current_category_definition in category_definition_options
                        else category_definition_options[0]
                    )
                }
            ),
        )
        is_cultural_category = category_definition == CATEGORY_DEFINITION_CULTURAL
        category_status_key = f"category_status_{editor_key}"
        category_status = metadata_status_col.radio(
            "品类启用状态 *",
            list(MATERIAL_STATUS_OPTIONS),
            horizontal=True,
            help="该字段控制品类管理状态；申领页是否显示只由“是否在申领页显示”字段决定。",
            key=category_status_key,
            **(
                {}
                if category_status_key in st.session_state
                else {"index": list(MATERIAL_STATUS_OPTIONS).index(current_category_status)}
            ),
        )
        category_unit_price_key = f"category_unit_price_{editor_key}"
        category_unit_price_text = metadata_price_col.text_input(
            "单价（美元）",
            placeholder="可选，例如：0.06",
            key=category_unit_price_key,
            **(
                {}
                if category_unit_price_key in st.session_state
                else {
                    "value": ""
                    if current_category_unit_price is None
                    else f"{float(current_category_unit_price):g}"
                }
            ),
        )
        category_customs_key = f"category_customs_code_{editor_key}"
        category_customs_code = metadata_customs_col.text_input(
            "海关编码",
            placeholder="可选，例如：4911101000",
            key=category_customs_key,
            **(
                {}
                if category_customs_key in st.session_state
                else {"value": current_category_customs_code}
            ),
        ).strip()
        category_metadata_error = ""
        try:
            category_unit_price = parse_optional_unit_price(category_unit_price_text)
        except ValueError as exc:
            category_unit_price = None
            category_metadata_error = str(exc)
            st.error(category_metadata_error)
        st.caption("单价和海关编码可留空；新增库存组合默认继承这里的值，也可在下方单独调整。")
        rule_col_a, rule_col_b = st.columns(2)
        no_model_key = f"category_no_model_{editor_key}"
        no_model = rule_col_a.checkbox(
            "该品类无需产品型号",
            help="勾选后产品型号统一为“无需型号”，库存数量可在下方库存组合编辑区重新分配。",
            key=no_model_key,
            **({} if no_model_key in st.session_state else {"value": current_no_model}),
        )
        no_language_key = f"category_no_language_{editor_key}"
        if is_cultural_category:
            rule_col_b.info("文化周边品类按“产品型号＋战区”生成库存组合。")
            no_language = False
        else:
            no_language = rule_col_b.checkbox(
                "该品类无需语种",
                help="勾选后语种统一为“无需语种”，库存数量可在下方库存组合编辑区重新分配。",
                key=no_language_key,
                **(
                    {}
                    if no_language_key in st.session_state
                    else {"value": current_no_language}
                ),
            )

        available_models = unique_preserve(
            [model for model in current_models + list(options["models"]) if model and model != NO_MODEL_TEXT]
        )
        available_languages = unique_preserve(
            current_languages
            + (
                [feishu_text(feishu_fields(row), "战区名称") for row in safe_feishu_rows(REGION_TABLE_NAME)]
                if is_cultural_category
                else sort_languages(list(options["languages"]))
            )
        )
        available_languages = [value for value in available_languages if value and value != NO_LANGUAGE_TEXT]
        default_models = [model for model in current_models if model != NO_MODEL_TEXT]
        default_languages = [language for language in current_languages if language != NO_LANGUAGE_TEXT]

        model_col, language_col = st.columns(2)
        selected_models_key = f"category_models_{editor_key}"
        selected_models = model_col.multiselect(
            "产品型号 *",
            available_models,
            disabled=no_model,
            help="编辑时会自动勾选当前型号；取消勾选即可移除该型号。",
            key=selected_models_key,
            **(
                {}
                if selected_models_key in st.session_state
                else {"default": default_models}
            ),
        )
        custom_models_text = model_col.text_area(
            "新增型号",
            placeholder="可用逗号、分号、顿号或换行分隔",
            disabled=no_model,
            height=86,
            key=f"category_custom_models_{editor_key}",
        )
        selected_languages_key = f"category_languages_{editor_key}"
        selected_languages = language_col.multiselect(
            "战区 *" if is_cultural_category else "语种 *",
            available_languages,
            disabled=no_language,
            help="编辑时会自动勾选当前语种；取消勾选即可移除该语种。",
            key=selected_languages_key,
            **(
                {}
                if selected_languages_key in st.session_state
                else {"default": default_languages}
            ),
        )
        custom_languages_text = language_col.text_area(
            "新增战区请前往“战区管理”" if is_cultural_category else "新增自定义语种",
            placeholder="可用逗号、分号、顿号或换行分隔",
            disabled=no_language or is_cultural_category,
            height=86,
            key=f"category_custom_languages_{editor_key}",
        )

        model_renames: dict[str, str] = {}
        model_rename_error = ""
        editable_current_models = [model for model in current_models if model != NO_MODEL_TEXT]
        rename_state_key = f"category_model_rename_state_{editor_key}"
        rename_state = {
            str(source): str(target)
            for source, target in dict(st.session_state.get(rename_state_key, {}) or {}).items()
            if str(source) in editable_current_models and str(target).strip()
        }
        if is_edit and editable_current_models and not no_model:
            with st.expander(
                "修改已有型号",
                expanded=pool_edit_dimension == "model",
            ):
                st.caption("一次选择一个型号进行修改；应用后可继续选择其他型号，库存和历史关联保持不变。")
                rename_select_col, rename_input_col, rename_button_col = st.columns(
                    [1.1, 1.5, 0.7],
                    vertical_alignment="bottom",
                )
                rename_source_key = f"category_model_rename_source_{editor_key}"
                if pool_edit_dimension == "model" and pool_focus_model in editable_current_models:
                    st.session_state[rename_source_key] = pool_focus_model
                rename_source = rename_select_col.selectbox(
                    "选择要修改的型号",
                    editable_current_models,
                    key=rename_source_key,
                )
                rename_token = uuid.uuid5(uuid.NAMESPACE_URL, rename_source).hex[:10]
                rename_target = rename_input_col.text_input(
                    "新的型号名称 *",
                    value=rename_state.get(rename_source, rename_source),
                    key=f"category_model_rename_target_{editor_key}_{rename_token}",
                ).strip()
                if rename_button_col.button(
                    "应用改名",
                    icon=":material/edit:",
                    width="stretch",
                    key=f"category_apply_model_rename_{editor_key}",
                ):
                    candidate_state = dict(rename_state)
                    if rename_target == rename_source:
                        candidate_state.pop(rename_source, None)
                    else:
                        candidate_state[rename_source] = rename_target
                    try:
                        category_model_rename_values(
                            pd.DataFrame(
                                [
                                    {
                                        "当前型号": model,
                                        "修改后型号": candidate_state.get(model, model),
                                    }
                                    for model in editable_current_models
                                ]
                            )
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state[rename_state_key] = candidate_state
                        st.rerun()
                if rename_state:
                    st.info(
                        f"{ui_text('已设置')}："
                        + "；".join(f"{source} → {target}" for source, target in rename_state.items())
                    )
                    st.caption("需要取消某项改名时，将新的型号名称改回原型号并再次应用。")
            try:
                all_model_renames = category_model_rename_values(
                    pd.DataFrame(
                        [
                            {
                                "当前型号": model,
                                "修改后型号": rename_state.get(model, model),
                            }
                            for model in editable_current_models
                        ]
                    )
                )
                model_renames = {
                    source: target
                    for source, target in all_model_renames.items()
                    if source in selected_models
                }
            except ValueError as exc:
                model_rename_error = str(exc)
                st.error(model_rename_error)

        language_renames: dict[str, str] = {}
        language_rename_error = ""
        editable_current_languages = [
            language for language in current_languages if language != NO_LANGUAGE_TEXT
        ]
        language_rename_state_key = f"category_language_rename_state_{editor_key}"
        language_rename_state = {
            str(source): str(target)
            for source, target in dict(
                st.session_state.get(language_rename_state_key, {}) or {}
            ).items()
            if str(source) in editable_current_languages and str(target).strip()
        }
        if is_edit and editable_current_languages and not no_language and not is_cultural_category:
            with st.expander(
                "修改已有语种",
                expanded=pool_edit_dimension == "material",
            ):
                st.caption("一次选择一个语种进行修改；应用后库存和历史关联保持不变。")
                rename_language_col, rename_language_input_col, rename_language_button_col = st.columns(
                    [1.1, 1.5, 0.7],
                    vertical_alignment="bottom",
                )
                language_rename_source_key = f"category_language_rename_source_{editor_key}"
                if (
                    pool_edit_dimension == "material"
                    and pool_focus_language in editable_current_languages
                ):
                    st.session_state[language_rename_source_key] = pool_focus_language
                language_rename_source = rename_language_col.selectbox(
                    "选择要修改的语种",
                    editable_current_languages,
                    key=language_rename_source_key,
                )
                language_rename_token = uuid.uuid5(
                    uuid.NAMESPACE_URL, language_rename_source
                ).hex[:10]
                language_rename_target = rename_language_input_col.text_input(
                    "新的语种名称 *",
                    value=language_rename_state.get(
                        language_rename_source, language_rename_source
                    ),
                    key=f"category_language_rename_target_{editor_key}_{language_rename_token}",
                ).strip()
                if rename_language_button_col.button(
                    "应用改名",
                    icon=":material/edit:",
                    width="stretch",
                    key=f"category_apply_language_rename_{editor_key}",
                ):
                    candidate_state = dict(language_rename_state)
                    if language_rename_target == language_rename_source:
                        candidate_state.pop(language_rename_source, None)
                    else:
                        candidate_state[language_rename_source] = language_rename_target
                    try:
                        category_language_rename_values(
                            pd.DataFrame(
                                [
                                    {
                                        "当前语种": language,
                                        "修改后语种": candidate_state.get(language, language),
                                    }
                                    for language in editable_current_languages
                                ]
                            )
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state[language_rename_state_key] = candidate_state
                        st.rerun()
                if language_rename_state:
                    st.info(
                        f"{ui_text('已设置')}："
                        + "；".join(
                            f"{source} → {target}"
                            for source, target in language_rename_state.items()
                        )
                    )
            try:
                all_language_renames = category_language_rename_values(
                    pd.DataFrame(
                        [
                            {
                                "当前语种": language,
                                "修改后语种": language_rename_state.get(language, language),
                            }
                            for language in editable_current_languages
                        ]
                    )
                )
                language_renames = {
                    source: target
                    for source, target in all_language_renames.items()
                    if source in selected_languages
                }
            except ValueError as exc:
                language_rename_error = str(exc)
                st.error(language_rename_error)

        renamed_selected_models = [model_renames.get(model, model) for model in selected_models]
        renamed_selected_languages = [
            language_renames.get(language, language) for language in selected_languages
        ]
        models = (
            [NO_MODEL_TEXT]
            if no_model
            else unique_preserve(renamed_selected_models + parse_custom_values(custom_models_text))
        )
        languages = (
            [NO_LANGUAGE_TEXT]
            if no_language
            else unique_preserve(
                renamed_selected_languages
                + ([] if is_cultural_category else parse_custom_values(custom_languages_text))
            )
        )
        category_request_visible_key = f"category_request_visible_{editor_key}"
        category_request_visible = metadata_visibility_col.radio(
            "品类在申领页显示 *",
            list(REQUEST_PAGE_VISIBILITY_OPTIONS),
            horizontal=True,
            help="申领页只读取此字段；该设置与品类启用状态互相独立。",
            key=category_request_visible_key,
            **(
                {}
                if category_request_visible_key in st.session_state
                else {
                    "index": list(REQUEST_PAGE_VISIBILITY_OPTIONS).index(
                        current_category_request_visible
                    )
                }
            ),
        )

        carry_model = models[0] if models else ""
        carry_language = languages[0] if languages else ""
        renamed_source_models = set(model_renames)
        renamed_source_languages = set(language_renames)
        removed_models = [
            model
            for model in current_models
            if model not in models and model not in renamed_source_models
        ]
        removed_languages = [
            language
            for language in current_languages
            if language not in languages and language not in renamed_source_languages
        ]
        if current_records and models and removed_models:
            carry_model = st.selectbox(
                "被取消型号的历史关联迁移到 *",
                models,
                help="这里只决定申请明细和流水的关联去向；库存数量请在下方库存组合编辑区填写。",
                key=f"category_carry_model_{editor_key}",
            )
        if current_records and languages and removed_languages:
            carry_language = st.selectbox(
                "被取消战区的库存迁移到 *" if is_cultural_category else "被取消语种的历史关联迁移到 *",
                languages,
                help="这里只决定申请明细和流水的关联去向；库存数量请在下方库存组合编辑区填写。",
                key=f"category_carry_language_{editor_key}",
            )

        plan: dict | None = None
        if (
            product
            and models
            and languages
            and not model_rename_error
            and not language_rename_error
            and not category_metadata_error
        ):
            try:
                plan = build_category_inventory_plan(
                    current_records,
                    product,
                    models,
                    languages,
                    model_renames=model_renames,
                    language_renames=language_renames,
                    carry_model=carry_model,
                    carry_language=carry_language,
                )
            except ValueError as exc:
                st.error(str(exc))

        target_values: dict[tuple[str, str], dict[str, object]] = {}
        target_state_key = ""
        revision_key = ""
        discard_confirmed = True
        if plan is not None:
            st.markdown(f"**{ui_text('库存组合编辑')}**")
            st.caption(
                "选择一个型号和战区后编辑对应库存组合；切换组合时，已填写内容会自动保留。"
                if is_cultural_category
                else "选择一个型号和语种后编辑对应库存组合；切换到其他组合时，已经填写的内容会自动保留。"
            )
            signature = uuid.uuid5(
                uuid.NAMESPACE_URL,
                "|".join(f"{target['model']}::{target['language']}" for target in plan["targets"]),
            ).hex[:12]
            target_state_key = f"category_target_values_{editor_key}_{signature}"
            revision_key = f"category_target_revision_{editor_key}_{signature}"
            defaults_state_key = f"category_target_defaults_{editor_key}_{signature}"
            category_defaults = {
                "unit_price": float(category_unit_price or 0),
                "customs_code": category_customs_code,
                "status": category_status,
                "request_visible": category_request_visible,
            }
            previous_category_defaults = st.session_state.get(defaults_state_key)
            saved_target_values = st.session_state.get(target_state_key, {})
            revision = int(st.session_state.get(revision_key, 0) or 0)
            valid_target_keys = {target["key"] for target in plan["targets"]}
            saved_target_values = (
                {
                    key: dict(value)
                    for key, value in saved_target_values.items()
                    if key in valid_target_keys and isinstance(value, dict)
                }
                if isinstance(saved_target_values, dict)
                else {}
            )
            base_target_values = {
                target["key"]: {
                    "quantity": int(target["quantity"]),
                    "unit_price": float(
                        category_defaults["unit_price"]
                        if target["is_new"]
                        else target["unit_price"] or 0
                    ),
                    "customs_code": str(
                        category_defaults["customs_code"]
                        if target["is_new"]
                        else target["customs_code"] or ""
                    ),
                    "status": normalize_enabled_status(
                        category_defaults["status"]
                        if target["is_new"]
                        else target["status"]
                    ),
                    "request_visible": normalize_request_page_visibility(
                        category_defaults["request_visible"]
                        if target["is_new"]
                        else target.get("request_visible")
                    ),
                }
                for target in plan["targets"]
            }
            target_values = {
                key: {**value, **dict(saved_target_values.get(key) or {})}
                for key, value in base_target_values.items()
            }

            for target_key, values in target_values.items():
                target_token = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{target_key[0]}::{target_key[1]}",
                ).hex[:10]
                widget_prefix = f"category_combo_{editor_key}_{signature}_{revision}_{target_token}"
                quantity_key = f"{widget_prefix}_quantity"
                unit_price_key = f"{widget_prefix}_unit_price"
                customs_key = f"{widget_prefix}_customs"
                status_key = f"{widget_prefix}_status"
                request_visible_key = f"{widget_prefix}_request_visible"
                if quantity_key in st.session_state:
                    values["quantity"] = int(st.session_state[quantity_key])
                if unit_price_key in st.session_state:
                    values["unit_price"] = float(st.session_state[unit_price_key] or 0)
                if customs_key in st.session_state:
                    values["customs_code"] = str(st.session_state[customs_key] or "").strip()
                if status_key in st.session_state:
                    values["status"] = normalize_enabled_status(st.session_state[status_key])
                if request_visible_key in st.session_state:
                    values["request_visible"] = normalize_request_page_visibility(
                        st.session_state[request_visible_key]
                    )
                if category_status == STATUS_INACTIVE:
                    values["status"] = STATUS_INACTIVE

            if (
                not is_edit
                and isinstance(previous_category_defaults, dict)
                and previous_category_defaults != category_defaults
            ):
                previous_price = float(previous_category_defaults.get("unit_price") or 0)
                previous_customs = str(previous_category_defaults.get("customs_code") or "")
                previous_status = normalize_enabled_status(previous_category_defaults.get("status"))
                previous_request_visible = normalize_request_page_visibility(
                    previous_category_defaults.get("request_visible")
                )
                for values in target_values.values():
                    if float(values.get("unit_price") or 0) == previous_price:
                        values["unit_price"] = category_defaults["unit_price"]
                    if str(values.get("customs_code") or "") == previous_customs:
                        values["customs_code"] = category_defaults["customs_code"]
                    if normalize_enabled_status(values.get("status")) == previous_status:
                        values["status"] = category_defaults["status"]
                    if (
                        normalize_request_page_visibility(values.get("request_visible"))
                        == previous_request_visible
                    ):
                        values["request_visible"] = category_defaults["request_visible"]
                st.session_state[target_state_key] = target_values
                st.session_state[defaults_state_key] = category_defaults
                st.session_state[revision_key] = revision + 1
                st.rerun()
            st.session_state[defaults_state_key] = category_defaults

            plan = build_category_inventory_plan(
                current_records,
                product,
                models,
                languages,
                model_renames=model_renames,
                language_renames=language_renames,
                carry_model=carry_model,
                carry_language=carry_language,
                target_values=target_values,
                default_request_visible=category_request_visible,
            )
            plan = enforce_category_inventory_status(plan, category_status)

            selector_model_col, selector_language_col = st.columns(2)
            selected_target_model_key = f"category_combo_model_{editor_key}_{signature}"
            if pool_focus_model in models:
                st.session_state[selected_target_model_key] = pool_focus_model
            selected_target_model = selector_model_col.selectbox(
                "选择要编辑的产品型号",
                models,
                key=selected_target_model_key,
            )
            selected_target_language_key = f"category_combo_language_{editor_key}_{signature}"
            if pool_focus_language in languages:
                st.session_state[selected_target_language_key] = pool_focus_language
            selected_target_language = selector_language_col.selectbox(
                "选择要编辑的战区" if is_cultural_category else "选择要编辑的语种",
                languages,
                key=selected_target_language_key,
            )
            st.session_state.pop("category_pool_focus_model", None)
            st.session_state.pop("category_pool_focus_language", None)
            st.session_state.pop("category_pool_edit_dimension", None)
            selected_target_key = (selected_target_model, selected_target_language)
            selected_target = next(
                target for target in plan["targets"] if target["key"] == selected_target_key
            )
            selected_values = target_values[selected_target_key]
            selected_token = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{selected_target_model}::{selected_target_language}",
            ).hex[:10]
            selected_widget_prefix = (
                f"category_combo_{editor_key}_{signature}_{revision}_{selected_token}"
            )
            st.caption(
                f"{ui_text('当前组合处理方式')}：{ui_text(str(selected_target['action']))}"
            )
            quantity_col, price_col, customs_col, status_col, visibility_col = st.columns(
                [1, 1, 1.4, 1.2, 1.2],
                vertical_alignment="bottom",
            )
            selected_quantity = quantity_col.number_input(
                "库存数量 *",
                value=int(selected_values["quantity"]),
                step=1,
                key=f"{selected_widget_prefix}_quantity",
            )
            selected_unit_price = price_col.number_input(
                "单价",
                min_value=0.0,
                value=float(selected_values["unit_price"] or 0),
                step=0.01,
                format="%.2f",
                key=f"{selected_widget_prefix}_unit_price",
            )
            selected_customs_code = customs_col.text_input(
                "海关编码",
                value=str(selected_values["customs_code"] or ""),
                key=f"{selected_widget_prefix}_customs",
            )
            selected_status = status_col.radio(
                "启用状态 *",
                list(MATERIAL_STATUS_OPTIONS),
                index=list(MATERIAL_STATUS_OPTIONS).index(
                    STATUS_INACTIVE
                    if category_status == STATUS_INACTIVE
                    else normalize_enabled_status(selected_values["status"])
                ),
                horizontal=True,
                disabled=category_status == STATUS_INACTIVE,
                key=f"{selected_widget_prefix}_status",
            )
            selected_request_visible = visibility_col.radio(
                "申领页显示 *",
                list(REQUEST_PAGE_VISIBILITY_OPTIONS),
                index=list(REQUEST_PAGE_VISIBILITY_OPTIONS).index(
                    normalize_request_page_visibility(
                        selected_values.get("request_visible")
                    )
                ),
                horizontal=True,
                key=f"{selected_widget_prefix}_request_visible",
            )
            target_values[selected_target_key] = {
                "quantity": int(selected_quantity),
                "unit_price": float(selected_unit_price),
                "customs_code": selected_customs_code.strip(),
                "status": STATUS_INACTIVE
                if category_status == STATUS_INACTIVE
                else normalize_enabled_status(selected_status),
                "request_visible": normalize_request_page_visibility(
                    selected_request_visible
                ),
            }
            st.session_state[target_state_key] = target_values
            plan = build_category_inventory_plan(
                current_records,
                product,
                models,
                languages,
                model_renames=model_renames,
                language_renames=language_renames,
                carry_model=carry_model,
                carry_language=carry_language,
                target_values=target_values,
                default_request_visible=category_request_visible,
            )
            plan = enforce_category_inventory_status(plan, category_status)

            if plan is not None:
                if category_status == STATUS_INACTIVE:
                    st.info("品类停用时，旗下所有库存组合会同步停用；重新启用品类后可再选择需要启用的库存行。")
                else:
                    with st.expander("批量调整库存状态", expanded=False):
                        target_key_by_label = {
                            f"{target['model']} · {target['language']}": target["key"]
                            for target in plan["targets"]
                        }
                        batch_target_labels = st.multiselect(
                            "选择库存组合",
                            list(target_key_by_label),
                            key=f"category_batch_targets_{editor_key}_{signature}_{revision}",
                        )
                        batch_status_col, batch_button_col = st.columns(
                            [1, 1],
                            vertical_alignment="bottom",
                        )
                        batch_status = batch_status_col.selectbox(
                            "批量设置启用状态",
                            list(MATERIAL_STATUS_OPTIONS),
                            key=f"category_batch_status_{editor_key}_{signature}",
                        )
                        if batch_button_col.button(
                            "应用到所选库存组合",
                            icon=":material/checklist:",
                            width="stretch",
                            key=f"category_apply_batch_status_{editor_key}_{signature}",
                        ):
                            if not batch_target_labels:
                                st.warning("请先选择至少一个库存组合。")
                            else:
                                for label in batch_target_labels:
                                    target_values[target_key_by_label[label]]["status"] = batch_status
                                st.session_state[target_state_key] = target_values
                                st.session_state[revision_key] = revision + 1
                                st.rerun()
                        st.caption("批量设置只更新当前页面状态，保存品类配置后才会同步至飞书。")

                metric_a, metric_b, metric_c, metric_d = st.columns(4)
                metric_a.metric("当前组合", plan["current_count"])
                metric_b.metric("目标组合", plan["target_count"])
                metric_c.metric("新增组合", plan["create_count"])
                metric_d.metric("移除旧行", plan["delete_count"])
                quantity_a, quantity_b, quantity_c = st.columns(3)
                quantity_a.metric("当前库存合计", f"{plan['current_quantity']:,}")
                quantity_b.metric("目标库存合计", f"{plan['target_quantity']:,}")
                quantity_c.metric("库存数量差额", f"{plan['quantity_difference']:+,}")
                enabled_count = sum(1 for target in plan["targets"] if target["status"] == STATUS_ACTIVE)
                st.caption(
                    f"启用库存组合 {enabled_count:,} 条；停用库存组合 {plan['target_count'] - enabled_count:,} 条。"
                )
                if plan["discarded_quantity"] > 0:
                    st.warning(f"将直接舍弃 {plan['discarded_quantity']:,} 件未分配库存，此操作保存后不可自动恢复。")
                    discard_confirmed = st.checkbox(
                        "确认直接舍弃未分配库存",
                        key=f"category_discard_confirm_{editor_key}_{signature}",
                    )
                elif plan["quantity_difference"] > 0 and current_records:
                    st.info(f"目标库存将比当前库存增加 {plan['quantity_difference']:,} 件。")

        if is_edit:
            confirmed = st.checkbox(
                "我已确认以上品类配置和库存组合",
                key=f"category_confirm_{editor_key}",
            )
        else:
            confirmed = True
            st.caption("点击创建物料品类后，将先进入全部新增库存行预览页；最终确认前不会写入飞书。")
        submitted = st.button(
            "保存品类配置" if is_edit else "创建物料品类",
            type="primary",
            icon=":material/save:" if is_edit else ":material/add_circle:",
            width="stretch",
            key=f"category_submit_{editor_key}",
        )

    if submitted:
        existing_names = {str(item["category"]) for item in categories if item["record_id"] != category_id}
        if not product:
            st.error("请填写物料品类名称。")
        elif not category_zh_page_name:
            st.error("请填写中文页面名称。")
        elif not category_en_page_name:
            st.error("请填写英文页面名称。")
        elif product != old_product and product in existing_names:
            st.error("该物料品类名称已经存在。")
        elif not commercial_invoice_name:
            st.error("请填写商业发票产品名称。")
        elif not models:
            st.error("请至少保留或新增一个产品型号，或勾选“无需产品型号”。")
        elif not languages:
            st.error("请至少选择一个战区。" if is_cultural_category else "请至少保留或新增一个语种，或勾选“无需语种”。")
        elif category_metadata_error:
            st.error(category_metadata_error)
        elif plan is None:
            st.error("请检查库存组合中的数量、单价、海关编码、启用状态和申领页显示。")
        elif plan["discarded_quantity"] > 0 and not discard_confirmed:
            st.warning("请确认直接舍弃未分配库存。")
        elif is_edit and not confirmed:
            st.warning("请先确认品类配置和库存组合。")
        elif not is_edit:
            st.session_state[CATEGORY_CREATE_DRAFT_KEY] = {
                "product": product,
                "category_zh_page_name": category_zh_page_name,
                "category_en_page_name": category_en_page_name,
                "no_model": no_model,
                "no_language": no_language,
                "models": list(models),
                "languages": list(languages),
                "category_status": category_status,
                "category_request_visible": category_request_visible,
                "category_definition": category_definition,
                "category_unit_price": category_unit_price,
                "category_customs_code": category_customs_code,
                "commercial_invoice_name": commercial_invoice_name,
                "packing_list_product_type": packing_list_product_type,
                "targets": [dict(target) for target in plan["targets"]],
                "target_state_key": target_state_key,
                "revision_key": revision_key,
                "form_state": {
                    "category_name_new": product,
                    "category_zh_page_name_new": category_zh_page_name,
                    "category_en_page_name_new": category_en_page_name,
                    "category_status_new": category_status,
                    "category_request_visible_new": category_request_visible,
                    "category_definition_new": category_definition,
                    "category_unit_price_new": category_unit_price_text,
                    "category_customs_code_new": category_customs_code,
                    "category_commercial_invoice_name_new": commercial_invoice_name,
                    "category_packing_list_product_type_new": packing_list_product_type,
                    "category_no_model_new": no_model,
                    "category_no_language_new": no_language,
                    "category_models_new": list(selected_models),
                    "category_custom_models_new": custom_models_text,
                    "category_languages_new": list(selected_languages),
                    "category_custom_languages_new": custom_languages_text,
                },
                "preview_token": uuid.uuid4().hex,
            }
            st.session_state[CATEGORY_CREATE_STAGE_KEY] = "review"
            st.rerun()
        else:
            sync_args = {
                "old_product": old_product, "new_product": product, "no_model": no_model,
                "category_zh_page_name": category_zh_page_name,
                "category_en_page_name": category_en_page_name,
                "no_language": no_language, "target_models": list(models),
                "target_languages": list(languages), "category_status": category_status,
                "category_request_visible": category_request_visible,
                "category_definition": category_definition,
                "category_unit_price": category_unit_price, "category_customs_code": category_customs_code,
                "commercial_invoice_name": commercial_invoice_name,
                "packing_list_product_type": packing_list_product_type,
                "category_record_id": category_id, "model_renames": dict(model_renames),
                "language_renames": dict(language_renames),
                "carry_model": carry_model, "carry_language": carry_language,
                "target_values": {key: dict(value) for key, value in target_values.items()},
            }
            st.session_state[CATEGORY_EDIT_DRAFT_KEY] = {
                "old_product": old_product, "product": product, "category_status": category_status,
                "category_zh_page_name": category_zh_page_name,
                "category_en_page_name": category_en_page_name,
                "old_category_zh_page_name": current_category_zh_page_name,
                "old_category_en_page_name": current_category_en_page_name,
                "old_category_definition": current_category_definition,
                "old_category_status": current_category_status,
                "old_category_request_visible": current_category_request_visible,
                "old_commercial_invoice_name": current_commercial_invoice_name,
                "old_packing_list_product_type": current_packing_list_product_type,
                "old_category_unit_price": current_category_unit_price,
                "old_category_customs_code": current_category_customs_code,
                "category_request_visible": category_request_visible,
                "category_definition": category_definition,
                "category_unit_price": category_unit_price,
                "category_customs_code": category_customs_code,
                "commercial_invoice_name": commercial_invoice_name,
                "packing_list_product_type": packing_list_product_type,
                "edited_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "current_records": [dict(row) for row in current_records],
                "targets": [dict(target) for target in plan["targets"]],
                "quantity_difference": plan["quantity_difference"], "sync_args": sync_args,
            }
            st.session_state[CATEGORY_EDIT_STAGE_KEY] = "review"
            st.rerun()

def add_material_category(
    product: str,
    models: list[str],
    languages: list[str],
    no_model: bool,
    no_language: bool,
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
                inserted_count = add_feishu_material_category_payload(
                    product,
                    no_model,
                    no_language,
                    new_df,
                )
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
    refresh_page_cache_after_write("category", update_request_form=True)
    st.rerun()


def render_download_center(full_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    render_section_header("03", "下载库存数据", "按需生成完整库存、筛选结果和库存流水文件")

    if st.button(
        "生成或刷新下载文件",
        key="prepare_inventory_downloads",
        icon=":material/file_export:",
        width="stretch",
    ):
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
        icon=":material/download:",
        width="stretch",
    )
    full_col_b.download_button(
        "下载完整库存 CSV",
        data=bundle["full_csv"],
        file_name=f"完整物料库存表_{timestamp}.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
    )
    log_col.download_button(
        "下载库存变更流水",
        data=bundle["transaction_csv"],
        file_name=f"库存变更流水_{timestamp}.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
    )

    filtered_col_a, filtered_col_b = st.columns(2)
    filtered_col_a.download_button(
        "下载当前筛选 Excel",
        data=bundle["filtered_xlsx"],
        file_name=f"当前筛选物料库存表_{timestamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        width="stretch",
    )
    filtered_col_b.download_button(
        "下载当前筛选 CSV",
        data=bundle["filtered_csv"],
        file_name=f"当前筛选物料库存表_{timestamp}.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
    )


def render_transaction_admin() -> None:
    render_section_header("01", "库存提交记录", "筛选、修正或撤回库存变更流水")
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

    with st.spinner("物料数据加载中，请稍后......"):
        records = load_feishu_transaction_records(start_date=start_date, end_date=end_date, limit=limit)
    if status_filter != "全部":
        records = [row for row in records if row["status"] == status_filter]
    applicant_options = sorted({str(row["requester"]) for row in records if row.get("requester")})
    selected_applicants = st.multiselect(
        "按申请人筛选",
        applicant_options,
        key="tx_applicant_filter",
        placeholder="全部申请人",
    )
    if selected_applicants:
        records = [row for row in records if row["requester"] in selected_applicants]
    if not records:
        st.info("当前日期、状态和申请人筛选条件下暂无库存提交记录。")
        return

    record_map = {row["record_id"]: row for row in records}
    table_df = pd.DataFrame(
        [
            {
                "选择": False,
                "记录ID": row["record_id"],
                "时间": row["created_at"],
                "状态": row["status"],
                "申请人": row["requester"],
                "申请单号": row["request_no"],
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
    metric_col_d.metric("关联申请单", f"{table_df['申请单号'].replace('', pd.NA).nunique():,}")

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
    if action_col_c.button(
        "批量撤回选中提交",
        icon=":material/undo:",
        width="stretch",
        key="tx_batch_revert_button",
    ):
        if not active_selected_ids:
            st.warning("请先勾选至少一条有效提交记录。")
        elif inactive_count:
            st.warning("选中记录包含已撤回或冲销记录，请取消这些记录后再操作。")
        elif not revert_confirmed:
            st.warning("请先勾选确认批量撤回。")
        else:
            try:
                with fullscreen_data_sync("正在提交数据，请稍后......"):
                    task, _ = enqueue_feishu_background_write(
                        QUEUE_TASK_TYPE_TRANSACTION_REVERT,
                        {"transaction_ids": active_selected_ids, "note": revert_note},
                    )
            except Exception as exc:
                st.error("批量撤回失败。请检查飞书应用是否有物料主数据和库存流水编辑权限。")
                st.exception(exc)
                return
            st.session_state["transaction_admin_message"] = data_submission_success_message()
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
            is_no_language_product, scoped_languages = product_language_state(
                replace_product,
                replace_model,
                selection_context,
            )
            languages = (
                [NO_LANGUAGE_TEXT]
                if is_no_language_product
                else unique_preserve([str(selected["language"])] + scoped_languages)
            )
            replace_language = edit_col_c.selectbox(
                "语种",
                languages,
                index=languages.index(str(selected["language"])) if str(selected["language"]) in languages else 0,
                key=f"replace_language_{selected_id}",
                disabled=is_no_language_product,
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
            if st.button(
                "保存选中记录的编辑",
                type="primary",
                icon=":material/save:",
                width="stretch",
                key=f"replace_transaction_button_{selected_id}",
            ):
                if not replace_confirmed:
                    st.warning("请先勾选确认修正。")
                else:
                    with fullscreen_data_sync("正在提交数据，请稍后......"):
                        try:
                            task, _ = enqueue_feishu_background_write(
                                QUEUE_TASK_TYPE_TRANSACTION_REPLACE,
                                {"args": {"transaction_record_id": selected_id, "action": replace_action, "product": replace_product, "model": replace_model, "language": replace_language, "quantity": int(replace_quantity), "note": replace_note}},
                            )
                        except Exception as exc:
                            st.error("修正任务未能进入后台队列，请重试。")
                            st.exception(exc)
                            return
                    st.session_state["transaction_admin_message"] = data_submission_success_message()
                    st.rerun()
    elif len(selected_ids) > 1:
        st.info("已选择多条记录，可批量撤回；如需编辑，请只勾选一条有效记录。")
    else:
        st.caption("勾选一条有效记录可编辑；勾选多条有效记录可批量撤回。")


def normalize_multiselect_state(key: str, options: list[str]) -> None:
    current = st.session_state.get(key)
    if not isinstance(current, (list, tuple, set)):
        return
    normalized = [str(value) for value in current if str(value) in options]
    if list(current) != normalized:
        st.session_state[key] = normalized


def render_material_dashboard(records: list[dict]) -> list[dict]:
    render_section_header("01", "库存数据看板", "仅统计启用库存行，并自定义查看库存规模、价值分布和预警状态")
    dashboard_df = material_dashboard_dataframe(records)
    if dashboard_df.empty:
        st.info("暂无物料数据可供分析。")
        return []

    with st.expander("看板设置", expanded=False, icon=":material/tune:"):
        enabled_modules = st.multiselect(
            "显示内容",
            list(MATERIAL_DASHBOARD_MODULES),
            default=list(MATERIAL_DASHBOARD_MODULES),
            key="material_dashboard_modules",
        )
        low_stock_threshold = int(
            st.number_input(
                "低库存阈值",
                min_value=0,
                value=DEFAULT_LOW_STOCK_THRESHOLD,
                step=10,
                key="material_dashboard_low_stock_threshold",
            )
        )

    filter_columns = st.columns([2.1, 1.55, 1.55, 1.4])
    category_options = sorted(dashboard_df["物料品类"].dropna().astype(str).unique().tolist())
    normalize_multiselect_state("material_dashboard_categories", category_options)
    selected_categories = filter_columns[0].multiselect(
        "物料品类",
        category_options,
        key="material_dashboard_categories",
        placeholder="全部品类",
    )

    model_scope = (
        dashboard_df[dashboard_df["物料品类"].isin(selected_categories)]
        if selected_categories
        else dashboard_df
    )
    model_options = sorted(model_scope["产品型号"].dropna().astype(str).unique().tolist())
    normalize_multiselect_state("material_dashboard_models", model_options)
    selected_models = filter_columns[1].multiselect(
        "产品型号",
        model_options,
        key="material_dashboard_models",
        placeholder="全部型号",
    )

    language_scope = model_scope[model_scope["产品型号"].isin(selected_models)] if selected_models else model_scope
    language_options = sort_languages(language_scope["语种"].dropna().astype(str).unique().tolist())
    normalize_multiselect_state("material_dashboard_languages", language_options)
    selected_languages = filter_columns[2].multiselect(
        "语种",
        language_options,
        key="material_dashboard_languages",
        placeholder="全部语种",
    )
    selected_statuses = filter_columns[3].multiselect(
        "库存状态",
        list(MATERIAL_STOCK_STATUSES),
        key="material_dashboard_stock_statuses",
        placeholder="全部状态",
    )

    filtered_df = apply_material_dashboard_filters(
        dashboard_df,
        categories=selected_categories,
        models=selected_models,
        languages=selected_languages,
        stock_statuses=selected_statuses,
        low_stock_threshold=low_stock_threshold,
    )
    st.caption(f"当前看板与下方明细联动，共显示 {len(filtered_df):,} 条库存组合。")

    if "库存预警" in enabled_modules:
        alert_df = filtered_df[filtered_df["库存状态"] != "正常库存"].copy()
        with st.container(border=True):
            st.markdown(f"### {ui_text('库存预警')}")
            if alert_df.empty:
                st.success("当前筛选下没有库存预警。")
            else:
                status_order = {"负库存": 0, "零库存": 1, "低库存": 2}
                alert_df["_status_order"] = alert_df["库存状态"].map(status_order).fillna(9)
                alert_df = alert_df.sort_values(["_status_order", "库存数量", "物料品类"]).drop(
                    columns=["_status_order"]
                )
                negative_count = int((alert_df["库存状态"] == "负库存").sum())
                zero_count = int((alert_df["库存状态"] == "零库存").sum())
                low_count = int((alert_df["库存状态"] == "低库存").sum())
                alert_message = (
                    f"发现 {len(alert_df):,} 条启用库存预警：负库存 {negative_count:,} 条，"
                    f"零库存 {zero_count:,} 条，低库存 {low_count:,} 条。"
                )
                if negative_count or zero_count:
                    st.error(alert_message)
                else:
                    st.warning(alert_message)
                st.dataframe(
                    alert_df[["库存状态", "物料编码", "物料品类", "产品型号", "语种", "库存数量"]],
                    width="stretch",
                    hide_index=True,
                    height=min(320, 38 + 35 * max(min(len(alert_df), 8), 1)),
                )

    if "概览指标" in enabled_modules:
        summary = material_dashboard_summary(filtered_df)
        metric_columns = st.columns(5)
        metric_columns[0].metric("库存组合数", f"{summary['combination_count']:,}", border=True)
        metric_columns[1].metric("库存总数量", f"{summary['quantity_sum']:,}", border=True)
        metric_columns[2].metric("库存总价值", f"{summary['total_value']:,.2f}", border=True)
        metric_columns[3].metric("负库存行", f"{summary['negative_count']:,}", border=True)
        metric_columns[4].metric("零库存行", f"{summary['zero_count']:,}", border=True)

    chart_specs: list[tuple[str, pd.DataFrame, str, str, str]] = []
    if "品类库存数量" in enabled_modules:
        chart_specs.append(
            (
                "品类库存数量",
                material_dashboard_grouped_data(filtered_df, "物料品类", "库存数量"),
                "物料品类",
                "库存数量",
                "#176B87",
            )
        )
    if "品类库存价值" in enabled_modules:
        chart_specs.append(
            (
                "品类库存价值",
                material_dashboard_grouped_data(filtered_df, "物料品类", "总价值"),
                "物料品类",
                "总价值",
                "#138A8A",
            )
        )
    if "语种分布" in enabled_modules:
        chart_specs.append(
            (
                "语种库存分布",
                material_dashboard_grouped_data(filtered_df, "语种", "库存数量"),
                "语种",
                "库存数量",
                "#E06B4F",
            )
        )

    for start in range(0, len(chart_specs), 2):
        batch = chart_specs[start : start + 2]
        chart_columns = st.columns(len(batch))
        for chart_column, (title, chart_df, x_column, y_column, color) in zip(chart_columns, batch):
            with chart_column:
                st.markdown(f"**{ui_text(title)}**")
                if chart_df.empty:
                    st.info("当前筛选无可展示数据。")
                    continue
                localized_x = ui_text(x_column)
                localized_y = ui_text(y_column)
                localized_chart_df = chart_df.rename(columns={x_column: localized_x, y_column: localized_y})
                st.bar_chart(
                    localized_chart_df,
                    x=localized_x,
                    y=localized_y,
                    color=color,
                    height=290,
                    width="stretch",
                )

    selected_ids = set(filtered_df["记录ID"].astype(str).tolist())
    return [row for row in records if str(row.get("record_id") or "") in selected_ids]


def render_material_data_admin(records: list[dict] | None = None) -> None:
    render_section_header("02", "库存行维护", "仅展示启用库存行；搜索、编辑或删除物料主数据记录")
    message = st.session_state.pop("material_admin_message", "")
    if message:
        st.success(message)

    search_text = st.text_input("搜索库存行", key="item_search_text", placeholder="物料编码 / 品类 / 型号 / 语种")
    if records is None:
        with st.spinner("物料数据加载中，请稍后......"):
            records = load_feishu_inventory_records(active_only=True)
    if not records:
        st.info("当前看板筛选下暂无物料行。")
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
    delete_col_a.caption("库存数量和流水记录不会阻止删除；历史记录不会被联动删除。")
    delete_confirmed = delete_col_b.checkbox("确认批量删除", key="item_batch_delete_confirmed")
    if delete_col_c.button(
        "批量删除选中库存行",
        icon=":material/delete:",
        width="stretch",
        key="item_batch_delete_button",
    ):
        if not selected_records:
            st.warning("请先勾选至少一条库存行。")
        elif not delete_confirmed:
            st.warning("请先勾选确认批量删除。")
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
            refresh_page_cache_after_write("material_database", update_request_form=True)
            st.rerun()

    if len(selected_records) == 1:
        item = selected_records[0]
        selected_item_id = item["record_id"]
        current_product = str(item["category"])
        current_model = str(item["model"] or NO_MODEL_TEXT)
        current_language = str(item["language"])
        no_language = current_language == NO_LANGUAGE_TEXT
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
            language = st.text_input(
                "语种",
                value=NO_LANGUAGE_TEXT if no_language else current_language,
                disabled=no_language,
                key=f"edit_material_language_{selected_item_id}",
            )
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
            if st.button(
                "保存选中库存行修改",
                type="primary",
                icon=":material/save:",
                width="stretch",
                key=f"save_inventory_item_edit_{selected_item_id}",
            ):
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
                    refresh_page_cache_after_write("material_database", update_request_form=True)
                    st.rerun()
    elif len(selected_records) > 1:
        st.info("已选择多条库存行，可批量删除；如需编辑，请只勾选一条。")
    else:
        st.caption("勾选一条库存行可编辑；勾选多条可批量删除。")


def render_category_admin() -> None:
    render_section_header("01", "物料品类维护", "编辑品类规则或撤回未使用的品类")
    message = st.session_state.pop("category_admin_message", "")
    if message:
        st.success(message)

    with st.spinner("物料数据加载中，请稍后......"):
        categories = load_feishu_category_records()
        inventory_records = load_feishu_inventory_records()
    if not categories:
        st.info("暂无物料品类。")
        return

    summary: dict[str, dict[str, int]] = {}
    category_models: dict[str, set[str]] = {}
    for item in inventory_records:
        product = str(item["category"])
        category_models.setdefault(product, set()).add(str(item["model"] or NO_MODEL_TEXT))
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
                "品类定义": row["category_definition"] or UNDEFINED_CATEGORY_DEFINITION,
                "无需型号": bool(row["no_model"]),
                "无需语种": bool(row["no_language"]),
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
    delete_col_a.caption("库存数量和流水记录不会阻止撤回；历史记录不会被联动删除。")
    delete_confirmed = delete_col_b.checkbox("确认批量撤回", key="category_batch_delete_confirmed")
    if delete_col_c.button(
        "批量撤回选中品类",
        icon=":material/undo:",
        width="stretch",
        key="category_batch_delete_button",
    ):
        if not selected_records:
            st.warning("请先勾选至少一个物料品类。")
        elif not delete_confirmed:
            st.warning("请先勾选确认批量撤回。")
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
            refresh_page_cache_after_write("category", update_request_form=True)
            st.rerun()

    if len(selected_records) == 1:
        category = selected_records[0]
        category_id = str(category["record_id"])
        old_product = str(category["category"])
        stats = summary.get(old_product, {"real_model_count": 0})
        existing_category_names = {str(row["category"]) for row in categories if row["record_id"] != category_id}
        inventory_category_names = {str(row["category"]) for row in inventory_records if str(row["category"]) != old_product}
        with st.expander("编辑选中物料品类", expanded=True):
            edit_col_a, edit_col_b, edit_col_c = st.columns([2, 1, 1])
            new_product = edit_col_a.text_input("物料品类名称", value=old_product, key=f"edit_category_name_{category_id}")
            no_model = edit_col_b.checkbox("无需型号", value=bool(category["no_model"]), key=f"edit_category_no_model_{category_id}")
            no_language = edit_col_c.checkbox(
                "无需语种",
                value=bool(category["no_language"]),
                key=f"edit_category_no_language_{category_id}",
            )
            if st.button(
                "保存选中品类修改",
                type="primary",
                icon=":material/save:",
                width="stretch",
                key=f"save_category_edit_{category_id}",
            ):
                if not new_product.strip():
                    st.error("物料品类名称不能为空。")
                elif no_model and int(stats.get("real_model_count", 0)) > 0:
                    st.error("该品类已有具体产品型号，不能直接改为无需型号。")
                elif no_language and int(stats.get("row_count", 0)) > len(category_models.get(old_product, set())):
                    st.error("该品类仍有按语种拆分的重复库存行，请先合并后再改为无需语种。")
                elif new_product.strip() != old_product and (
                    new_product.strip() in existing_category_names or new_product.strip() in inventory_category_names
                ):
                    st.error("新的物料品类名称已经存在。")
                elif count_feishu_category_transactions(old_product) > 0:
                    st.error("该品类已有流水记录。为保证历史可追溯，请先撤回相关库存提交后再修改品类。")
                else:
                    with DATA_LOCK:
                        try:
                            update_feishu_category(
                                old_product,
                                new_product,
                                no_model,
                                no_language,
                                category_id,
                            )
                        except Exception as exc:
                            st.error("修改物料品类失败。请检查飞书单选字段是否已有对应选项，或改为文本字段。")
                            st.exception(exc)
                            return
                    st.session_state["category_admin_message"] = "物料品类已修改。"
                    refresh_page_cache_after_write("category", update_request_form=True)
                    st.rerun()
    elif len(selected_records) > 1:
        st.info("已选择多个品类，可批量撤回；如需编辑，请只勾选一个。")
    else:
        st.caption("勾选一个品类可编辑；勾选多个可批量撤回。")

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
    refresh_page_cache_after_write("maintenance", update_request_form=True)


def request_lines_for_request(
    request: dict[str, object],
    lines: list[dict[str, object]],
) -> list[dict[str, object]]:
    request_id = str(request["record_id"])
    request_no = str(request["request_no"])
    result: list[dict[str, object]] = []
    for line in lines:
        request_ids = [str(item) for item in line.get("request_ids", [])]
        if request_ids:
            matches_request = request_id in request_ids
        else:
            matches_request = str(line.get("request_no", "")) == request_no
        if matches_request:
            result.append(line)
    return result


def render_inventory_view() -> None:
    render_page_header(
        "实时物料库存表",
        "库存视图",
        "按物料品类、产品型号和语种查看当前库存与价值。",
        page_key="inventory",
    )
    if not auth_gate():
        return
    render_page_cache_toolbar("inventory")

    with st.spinner("物料数据加载中，请稍后......"):
        df = load_inventory()
    with st.container(border=True):
        render_section_header("01", "库存筛选", f"当前存储：{storage_mode_label()}")
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
        if st.button(
            "显示全部库存组合",
            key="show_all_inventory_rows",
            icon=":material/view_list:",
            width="stretch",
        ):
            st.session_state["inventory_only_stocked"] = False
            st.rerun()

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("组合总数", f"{len(filtered):,}")
    metric_b.metric("非零库存组合", f"{int((filtered[QTY_COL] != 0).sum()):,}")
    metric_c.metric("库存总数量", f"{int(filtered[QTY_COL].sum()):,}")
    metric_d.metric("库存总价值", f"{float(filtered[VALUE_COL].sum()):,.2f}")

    render_section_header("02", "库存明细", f"当前筛选显示 {len(filtered):,} 条物料组合")
    st.dataframe(filtered, width="stretch", hide_index=True, height=560)
    render_download_center(df, filtered)


def load_warehouse_location_cache() -> dict[str, object]:
    if not WAREHOUSE_LOCATION_CACHE_PATH.exists():
        return {"schema_version": 1, "generated_at": "", "shelves": []}
    data = load_static_json_file(*static_cache_file_signature(WAREHOUSE_LOCATION_CACHE_PATH))
    if not isinstance(data, dict) or not isinstance(data.get("shelves"), list):
        raise RuntimeError("仓库位置静态缓存文件格式不正确。")
    return data


load_warehouse_location_cache.clear = load_static_json_file.clear  # type: ignore[attr-defined]


def warehouse_material_search_text(material: dict[str, object]) -> str:
    return " ".join(
        str(material.get(key) or "")
        for key in ("material_code", "category", "model", "language")
    ).casefold()


def warehouse_shelf_material_count(shelf: dict[str, object]) -> int:
    direct_count = len(list(shelf.get("materials") or []))
    row_count = sum(
        len(list(row.get("materials") or []))
        for row in list(shelf.get("rows") or [])
        if isinstance(row, dict)
    )
    return direct_count + row_count


def sort_warehouse_location_shelves(shelves: list[dict]) -> list[dict]:
    return sorted(
        shelves,
        key=lambda shelf: (
            warehouse_shelf_material_count(shelf) == 0,
            -warehouse_shelf_material_count(shelf),
            str(shelf.get("shelf_code") or ""),
        ),
    )


def filter_warehouse_location_shelves(
    shelves: list[dict],
    *,
    query: str = "",
    shelf_code: str = "",
) -> list[dict]:
    normalized_query = str(query or "").strip().casefold()
    normalized_shelf = str(shelf_code or "").strip()
    results: list[dict] = []
    for source in shelves:
        shelf = dict(source)
        if normalized_shelf and str(shelf.get("shelf_code") or "") != normalized_shelf:
            continue
        shelf_text = " ".join(
            str(shelf.get(key) or "")
            for key in ("shelf_code", "ground_location", "description")
        ).casefold()
        direct_materials = [dict(item) for item in list(shelf.get("materials") or [])]
        rows = [dict(item) for item in list(shelf.get("rows") or [])]
        if not normalized_query or normalized_query in shelf_text:
            shelf["visible_materials"] = direct_materials
            shelf["visible_rows"] = rows
            results.append(shelf)
            continue
        visible_materials = [
            material
            for material in direct_materials
            if normalized_query in warehouse_material_search_text(material)
        ]
        visible_rows: list[dict] = []
        for row in rows:
            row_text = " ".join(
                str(row.get(key) or "") for key in ("row_code", "description")
            ).casefold()
            materials = [dict(item) for item in list(row.get("materials") or [])]
            matching_materials = [
                material
                for material in materials
                if normalized_query in warehouse_material_search_text(material)
            ]
            if normalized_query in row_text:
                row["visible_materials"] = materials
                visible_rows.append(row)
            elif matching_materials:
                row["visible_materials"] = matching_materials
                visible_rows.append(row)
        if visible_materials or visible_rows:
            shelf["visible_materials"] = visible_materials
            shelf["visible_rows"] = visible_rows
            results.append(shelf)
    return results


WAREHOUSE_MAP_POINTS = {
    "H001": (235, 470, 160, 470),
    "H002": (325, 470, 345, 405),
    "H003": (450, 620, 390, 660),
    "H004": (575, 470, 740, 455),
    "H005": (450, 735, 450, 835),
    "H006": (600, 175, 740, 135),
    "G001": (235, 650, 160, 650),
    "G002": (665, 640, 740, 650),
    "G003": (665, 300, 740, 285),
    "G004": (235, 270, 160, 270),
    "G005": (520, 170, 520, 70),
}

WAREHOUSE_ENGLISH_TEXT = {
    "进门左侧": "Left side after entering",
    "进门右侧（左列）": "Right side after entering (left column)",
    "进门右侧（前列）": "Right side after entering (front row)",
    "进门右侧（右列）": "Right side after entering (right column)",
    "进门后侧": "Rear area after entering",
    "靠窗后侧": "Rear area by the windows",
    "（地面）进门左下": "Floor area, lower left by entrance",
    "（地面）右侧靠墙（前半）": "Floor area, right wall (front half)",
    "（地面）右侧靠墙（后半）": "Floor area, right wall (rear half)",
    "（地面）左侧货架后方": "Floor area, behind the left shelves",
    "（地面）靠窗后侧": "Floor area, rear by the windows",
    "中文货架，从上到下依次为产品单页、品牌手册、易拉宝": "Chinese materials shelf: product flyers, brand brochures, and roll-up banners from top to bottom.",
    "小语种货架，二层德语法语、三层西语意大利、四层韩语和备货箱": "Language shelf: German and French on Level 2, Spanish and Italian on Level 3, and Korean plus reserve boxes on Level 4.",
    "英文货架": "English materials shelf",
    "背靠背，每面从上到下分类。": "Back-to-back shelving, categorized from top to bottom on each side.",
    "英文品牌手册+四条工业线手册": "English brand brochures and brochures for four industrial product lines.",
    "左侧靠墙两列为小语种折页物料； 地面为英文单页备货。": "The two columns by the left wall store multilingual leaflets; reserve English flyers are stored on the floor.",
    "左侧靠墙两列为小语种折页物料; 地面为英文单页备货。": "The two columns by the left wall store multilingual leaflets; reserve English flyers are stored on the floor.",
    "笔记本礼盒、公仔和无纺布袋": "Notebook gift boxes, plush toys, and non-woven bags.",
}


def warehouse_display_text(value: object) -> str:
    text = str(value or "").strip()
    compact_text = " ".join(text.split())
    if get_ui_language() == LANGUAGE_EN:
        return WAREHOUSE_ENGLISH_TEXT.get(
            text,
            WAREHOUSE_ENGLISH_TEXT.get(
                compact_text,
                str(translate_ui_text(compact_text, LANGUAGE_EN)),
            ),
        )
    return text


def warehouse_row_level_label(row_code: str) -> str:
    match = re.search(r"(?:^|[-_])0?([1-9]\d*)$", str(row_code or "").strip())
    if not match:
        return ""
    level = int(match.group(1))
    if get_ui_language() == LANGUAGE_EN:
        return "Top Level" if level == 1 else f"Level {level}"
    return "最上层" if level == 1 else f"第 {level} 层"


def warehouse_anchor_slug(shelf_code: object) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(shelf_code or "").strip().casefold()).strip("-")


def render_warehouse_floor_map(
    shelves: list[dict], *, highlight_matches: bool = False
) -> None:
    english = get_ui_language() == LANGUAGE_EN
    labels = {
        "aria": "Warehouse shelf location diagram showing shelves in the current filter" if english else "仓库货架位置示意图，标出当前筛选结果中的货架位置",
        "title": "Warehouse Shelf Location Diagram" if english else "仓库货架位置示意图",
        "caveat": "Based on location descriptions; not to scale" if english else "按位置描述绘制，非精确比例",
        "center": "Central Shelving Area" if english else "中央货架区",
        "ring": "Ring-shaped aisles on all four sides" if english else "四周为环形过道",
        "north": "North Aisle" if english else "北侧过道",
        "south": "South Aisle" if english else "南侧过道",
        "west": "West Aisle" if english else "西侧过道",
        "east": "East Aisle" if english else "东侧过道",
        "windows": "Full-width windows along the north wall" if english else "北侧整面窗户",
        "entrance": "Warehouse Entrance (11F Northwest Corner)" if english else "仓库入口（11F 西北角）",
        "view_images": "View Images" if english else "查看图片",
        "expand": "Expand shelf details" if english else "展开货架详情",
    }
    markers: list[str] = []
    for shelf in shelves:
        shelf_code = str(shelf.get("shelf_code") or "").strip()
        if shelf_code not in WAREHOUSE_MAP_POINTS:
            continue
        pin_x, pin_y, _, _ = WAREHOUSE_MAP_POINTS[shelf_code]
        location = warehouse_display_text(shelf.get("ground_location") or "位置待补充")
        safe_code = escape(shelf_code)
        safe_location = escape(location)
        anchor_slug = warehouse_anchor_slug(shelf_code)
        marker_class = "warehouse-marker is-filter-match" if highlight_matches else "warehouse-marker"
        card_x = pin_x - 34
        card_y = pin_y - 18
        markers.append(
            f'<g id="map-{anchor_slug}" class="{marker_class}">'
            f'<foreignObject x="{card_x}" y="{card_y}" width="190" height="125" overflow="visible">'
            f'<div xmlns="http://www.w3.org/1999/xhtml" class="shelf-map-card-shell">'
            f'<details class="shelf-map-card">'
            f'<summary aria-label="{escape(labels["expand"])} {safe_code}"><span>{safe_code}</span><b aria-hidden="true">⌄</b></summary>'
            f'<div class="shelf-map-card-body"><p>{safe_location}</p>'
            f'<a href="#gallery-{anchor_slug}">{escape(labels["view_images"])} ↓</a></div>'
            f'</details></div></foreignObject></g>'
        )
    map_html = f"""
    <div class="warehouse-map-wrap" role="group" aria-label="{escape(labels['aria'])}">
      <div class="warehouse-map-title"><strong>{escape(labels['title'])}</strong><span>{escape(labels['caveat'])}</span></div>
      <div class="warehouse-map-scroll">
        <svg class="warehouse-map" viewBox="0 0 900 900" xmlns="http://www.w3.org/2000/svg">
          <style>
            .warehouse-map {{ font-family: Inter, "Microsoft YaHei", sans-serif; }}
            .warehouse-outline {{ fill: #e5e7eb; stroke: #94a3b8; stroke-width: 2; }}
            .zone {{ fill: #e8f4f5; stroke: #b8dfe2; stroke-width: 1.5; }}
            .zone-text {{ fill: #64748b; font-size: 13px; font-weight: 600; }}
          </style>
          <rect x="200" y="120" width="500" height="650" rx="18" class="warehouse-outline" />
          <rect x="340" y="290" width="220" height="310" rx="12" class="zone" />
          <text x="450" y="435" text-anchor="middle" class="zone-text">{escape(labels['center'])}</text>
          <text x="450" y="458" text-anchor="middle" class="zone-text">{escape(labels['ring'])}</text>
          <text x="450" y="265" text-anchor="middle" class="zone-text">{escape(labels['north'])}</text>
          <text x="520" y="690" text-anchor="middle" class="zone-text">{escape(labels['south'])}</text>
          <text x="315" y="445" text-anchor="middle" class="zone-text" transform="rotate(-90 315 445)">{escape(labels['west'])}</text>
          <text x="585" y="445" text-anchor="middle" class="zone-text" transform="rotate(90 585 445)">{escape(labels['east'])}</text>
          <line x1="215" y1="120" x2="685" y2="120" stroke="#4aa9b2" stroke-width="9" />
          <path d="M 250 110 L 250 130 M 300 110 L 300 130 M 350 110 L 350 130 M 400 110 L 400 130 M 450 110 L 450 130 M 500 110 L 500 130 M 550 110 L 550 130 M 600 110 L 600 130 M 650 110 L 650 130" stroke="#ffffff" stroke-width="2" />
          <text x="450" y="95" text-anchor="middle" class="zone-text">{escape(labels['windows'])}</text>
          <path d="M 235 770 L 235 810 L 285 810" fill="none" stroke="#087f8c" stroke-width="5" />
          <path d="M 285 795 L 307 810 L 285 825" fill="none" stroke="#087f8c" stroke-width="3" />
          <text x="195" y="858" text-anchor="start" class="zone-text">{escape(labels['entrance'])}</text>
          {''.join(markers)}
        </svg>
      </div>
    </div>
    <style>
      .warehouse-map-wrap {{ margin: .5rem 0 1.25rem; padding: 1rem; border: 1px solid #d9e2ec; border-radius: 14px; background: white; }}
      .warehouse-map-title {{ display:flex; justify-content:space-between; gap:1rem; color:#0f172a; }}
      .warehouse-map-title span {{ color:#64748b; font-size:.82rem; }}
      .warehouse-map-scroll {{ overflow-x:auto; margin-top:.5rem; }}
      .warehouse-map {{ display:block; min-width:620px; width:100%; max-height:820px; height:auto; }}
      .shelf-map-card-shell {{ position:relative; width:max-content; font-family:Inter,"Microsoft YaHei",sans-serif; }}
      .shelf-map-card {{ width:68px; border:2px solid #087f8c; border-radius:9px; background:#fff; box-shadow:0 2px 7px rgba(15,23,42,.15); color:#0f172a; transition:width .16s ease, box-shadow .16s ease; }}
      .shelf-map-card[open] {{ position:relative; z-index:20; width:170px; box-shadow:0 8px 20px rgba(15,23,42,.22); }}
      .shelf-map-card summary {{ display:flex; align-items:center; justify-content:space-between; gap:.35rem; padding:7px 9px; cursor:pointer; list-style:none; font-size:13px; font-weight:800; line-height:1.15; }}
      .shelf-map-card summary::-webkit-details-marker {{ display:none; }}
      .shelf-map-card summary b {{ color:#087f8c; font-size:14px; transition:transform .16s ease; }}
      .shelf-map-card[open] summary b {{ transform:rotate(180deg); }}
      .shelf-map-card-body {{ padding:0 9px 9px; border-top:1px solid #dbe5e8; }}
      .shelf-map-card-body p {{ margin:7px 0; color:#475569; font-size:11px; line-height:1.35; }}
      .shelf-map-card-body a {{ color:#087f8c !important; font-size:11px; font-weight:800; text-decoration:none !important; }}
      .shelf-map-card-body a:hover {{ text-decoration:underline !important; }}
      .warehouse-marker.is-filter-match .shelf-map-card {{ border-color:#f59e0b; box-shadow:0 0 0 3px rgba(245,158,11,.25); }}
      .warehouse-marker:target .shelf-map-card {{ border-color:#f97316; box-shadow:0 0 0 5px rgba(249,115,22,.28),0 8px 20px rgba(15,23,42,.2); }}
      .warehouse-gallery-anchor {{ scroll-margin-top: 5rem; height: 0; overflow: hidden; }}
      .warehouse-gallery-anchor:target {{ height: auto; margin-bottom: .55rem; padding: .55rem .75rem; border-left: 4px solid #f97316; border-radius: 6px; background: #fff7ed; color: #9a3412; font-weight: 700; }}
      .warehouse-gallery-anchor:target::after {{ content: attr(data-highlight-label); }}
      .warehouse-map-return {{ display:inline-block; margin-bottom:.45rem; color:#087f8c !important; font-size:.84rem; font-weight:700; text-decoration:none !important; }}
      .warehouse-map-return:hover {{ text-decoration:underline !important; }}
      @media (max-width: 720px) {{ .warehouse-map-title {{ flex-direction:column; gap:.2rem; }} }}
      @media (prefers-reduced-motion: reduce) {{ .shelf-map-card, .shelf-map-card summary b {{ transition:none; }} }}
    </style>
    """
    st.markdown(map_html, unsafe_allow_html=True)


def render_warehouse_materials(materials: list[dict]) -> None:
    if not materials:
        st.caption(
            "No linked material details"
            if get_ui_language() == LANGUAGE_EN
            else "暂无关联物料明细"
        )
        return
    for material in materials:
        st.markdown(
            " · ".join(
                value
                for value in [
                    str(material.get("category") or ""),
                    str(material.get("model") or ""),
                    str(material.get("language") or ""),
                    str(material.get("material_code") or ""),
                ]
                if value
            )
        )


def render_cached_warehouse_images(images: list[dict], caption: str) -> None:
    valid_images = [
        image
        for image in images
        if isinstance(image, dict)
        and application_cache_path(str(image.get("path") or "")).is_file()
    ]
    if not valid_images:
        st.caption(
            "No location images"
            if get_ui_language() == LANGUAGE_EN
            else "暂无位置图片"
        )
        return
    image_columns = st.columns(min(3, len(valid_images)))
    for index, image in enumerate(valid_images):
        image_path = application_cache_path(str(image.get("path") or ""))
        image_columns[index % len(image_columns)].image(
            str(image_path),
            caption=f"{caption} · {index + 1}",
            width="stretch",
        )


def render_warehouse_location_view(*, show_header: bool = True) -> None:
    english = get_ui_language() == LANGUAGE_EN
    if show_header:
        render_page_header(
            "物料仓库位置查询",
            "仓库位置图集",
            "按物料、型号、语种、货架编号或位置说明查询存放位置。",
        )
    cache = load_warehouse_location_cache()
    shelves = [dict(item) for item in list(cache.get("shelves") or []) if isinstance(item, dict)]
    st.info("本页面仅用于查询物料存放位置。如需拿取物料，请先提交物料申请。")
    with st.container(border=True):
        search_col, shelf_col = st.columns([2.4, 1])
        query = search_col.text_input(
            "搜索物料或位置",
            placeholder=(
                "Enter material category, model, language, code, shelf, or location"
                if english
                else "输入物料品类、型号、语种、物料编码、货架编号或位置"
            ),
            key="warehouse_location_query",
            icon=":material/search:",
        )
        shelf_options = ["全部货架"] + sorted(
            str(shelf.get("shelf_code") or "") for shelf in shelves if shelf.get("shelf_code")
        )
        selected_shelf = shelf_col.selectbox(
            "筛选货架",
            shelf_options,
            key=f"warehouse_location_shelf_filter_{get_ui_language()}",
            format_func=lambda option: (
                "All Shelves" if english and option == "全部货架" else option
            ),
        )
    filtered = sort_warehouse_location_shelves(
        filter_warehouse_location_shelves(
            shelves,
            query=query,
            shelf_code="" if selected_shelf == "全部货架" else selected_shelf,
        )
    )
    render_warehouse_floor_map(
        filtered,
        highlight_matches=bool(str(query or "").strip() or selected_shelf != "全部货架"),
    )
    render_section_header(
        "01",
        "Location Gallery" if english else "位置图片集锦",
        f"{len(filtered)} shelf locations found" if english else f"共找到 {len(filtered)} 个货架位置",
    )
    if not filtered:
        st.warning(
            "No matching locations found. Try a material name, model, language, or shelf code."
            if english
            else "没有找到匹配的位置，请尝试物料名称、型号、语种或货架编号。"
        )
        return
    gallery_columns = st.columns(3)
    for index, shelf in enumerate(filtered):
        with gallery_columns[index % 3].container(border=True):
            shelf_code = str(shelf.get("shelf_code") or "未编号")
            anchor_slug = warehouse_anchor_slug(shelf_code)
            located_label = (
                f"Located shelf {shelf_code}"
                if english
                else f"已定位到货架 {shelf_code}"
            )
            return_label = "Locate on map" if english else "在地图中定位"
            st.markdown(
                f'<div id="gallery-{anchor_slug}" class="warehouse-gallery-anchor" data-highlight-label="{escape(located_label)}"></div>'
                f'<a class="warehouse-map-return" href="#map-{anchor_slug}">↥ {escape(return_label)}</a>',
                unsafe_allow_html=True,
            )
            st.subheader(shelf_code)
            location = warehouse_display_text(shelf.get("ground_location") or "位置待补充")
            st.caption(f":material/location_on: {location}")
            render_cached_warehouse_images(list(shelf.get("images") or []), shelf_code)
            description = warehouse_display_text(shelf.get("description") or "")
            if description:
                st.write(description)
            direct_materials = list(shelf.get("visible_materials", shelf.get("materials") or []))
            if direct_materials:
                direct_label = (
                    f"Shelf Materials ({len(direct_materials)})"
                    if get_ui_language() == LANGUAGE_EN
                    else f"货架关联物料（{len(direct_materials)}）"
                )
                with st.expander(direct_label):
                    render_warehouse_materials(direct_materials)
            visible_rows = list(shelf.get("visible_rows", shelf.get("rows") or []))
            for row in visible_rows:
                row_code = str(row.get("row_code") or "未编号货架行")
                row_materials = list(row.get("visible_materials", row.get("materials") or []))
                level_label = warehouse_row_level_label(row_code)
                row_label_parts = [row_code]
                if level_label:
                    row_label_parts.append(level_label)
                row_label_parts.append(
                    f"{len(row_materials)} material types"
                    if get_ui_language() == LANGUAGE_EN
                    else f"{len(row_materials)} 项物料"
                )
                with st.expander(" · ".join(row_label_parts)):
                    row_description = warehouse_display_text(row.get("description") or "")
                    if row_description:
                        st.write(row_description)
                    render_cached_warehouse_images(list(row.get("images") or []), row_code)
                    render_warehouse_materials(row_materials)


def render_gift_image(attachments: list[dict], product: object) -> None:
    attachment = attachments[0] if attachments else None
    if isinstance(attachment, dict):
        cached_path = str(attachment.get("cached_path") or "").strip()
        if cached_path:
            app_root = Path(__file__).resolve().parent
            image_path = application_cache_path(cached_path)
            if app_root in image_path.parents and image_path.is_file():
                st.image(str(image_path), width="stretch")
                return
        file_token = str(attachment.get("file_token") or "")
        if file_token:
            try:
                st.image(
                    load_feishu_attachment(
                        file_token,
                        str(attachment.get("url") or ""),
                    ),
                    width="stretch",
                )
                return
            except Exception:
                pass
    category_image_path = request_category_image_path(product)
    if category_image_path:
        st.image(str(category_image_path), width="stretch")
        return
    st.markdown(
        '<div class="pudu-product-image-placeholder">暂无图片</div>',
        unsafe_allow_html=True,
    )


def render_gift_fixed_rules() -> None:
    st.markdown(
        f"""
        <div class="pudu-fixed-rule-row">
            <div><span>{escape(ui_text("品类定义"))}</span>{escape(ui_text(CATEGORY_DEFINITION_GIFT))}</div>
            <div><span>{escape(ui_text("产品型号"))}</span>{escape(ui_text(NO_MODEL_TEXT))}</div>
            <div><span>{escape(ui_text("语种"))}</span>{escape(ui_text(NO_LANGUAGE_TEXT))}</div>
            <div><span>{escape(ui_text("物料状态"))}</span>{escape(ui_text(GIFT_PROJECT_STATUS_REQUESTED))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_existing_gift_project_form(category: dict) -> None:
    category_id = str(category.get("record_id") or "")
    product = str(category.get("category") or "")
    with st.container(border=True):
        render_section_header("02", "新建项目需求", product)
        render_gift_fixed_rules()
        project_col, note_col, image_col = st.columns([1.2, 2, 1.2])
        required_field_label(project_col, "项目名称")
        project_name = project_col.text_input(
            "项目名称",
            placeholder="填写新的或已有项目名称",
            label_visibility="collapsed",
            key=f"gift_existing_project_{category_id}",
        )
        note_col.markdown(
            '<div class="pudu-field-label">备注</div>',
            unsafe_allow_html=True,
        )
        remark = note_col.text_input(
            "备注",
            placeholder="可选",
            label_visibility="collapsed",
            key=f"gift_existing_remark_{category_id}",
        )
        image_col.markdown(
            '<div class="pudu-field-label">物料图片</div>',
            unsafe_allow_html=True,
        )
        uploaded_file = image_col.file_uploader(
            "物料图片",
            type=["png", "jpg", "jpeg", "webp"],
            label_visibility="collapsed",
            key=f"gift_existing_image_{category_id}",
        )
        _, submit_col = st.columns([3, 1.15])
        submitted = submit_col.button(
            "提交项目需求",
            type="primary",
            icon=":material/send:",
            width="stretch",
            key=f"gift_existing_submit_{category_id}",
        )
    if not submitted:
        return
    if not str(project_name or "").strip():
        st.warning("请填写项目名称。")
        return
    with fullscreen_data_sync("正在提交数据，请稍后......"):
        try:
            attachment_token = upload_gift_project_attachment(uploaded_file)
            task, _ = enqueue_feishu_background_write(
                QUEUE_TASK_TYPE_GIFT_PROJECT,
                {"operation": "existing", "args": {"project_name": project_name, "category_record_id": category_id, "remark": remark, "attachment_token": attachment_token}},
            )
        except Exception as exc:
            st.error("项目周边礼品需求提交失败，请检查飞书字段和应用写入权限。")
            st.exception(exc)
            return
    st.session_state.pop("gift_selected_category_id", None)
    st.session_state["gift_project_submit_message"] = data_submission_success_message()
    st.rerun()


def render_new_gift_project_form() -> None:
    with st.container(border=True):
        render_section_header("03", "新增周边礼品", "创建默认停用且不在申领页显示的品类、零库存行和项目需求")
        render_gift_fixed_rules()
        project_col, product_col, price_col = st.columns([1.2, 1.6, 0.8])
        required_field_label(project_col, "项目名称")
        project_name = project_col.text_input(
            "项目名称",
            placeholder="填写新的或已有项目名称",
            label_visibility="collapsed",
            key="gift_new_project_name",
        )
        required_field_label(product_col, "新的物料名称")
        material_name = product_col.text_input(
            "新的物料名称",
            placeholder="例如：活动定制徽章",
            label_visibility="collapsed",
            key="gift_new_material_name",
        )
        price_col.markdown(
            '<div class="pudu-field-label">单价（美元）</div>',
            unsafe_allow_html=True,
        )
        unit_price = price_col.number_input(
            "单价（美元）",
            min_value=0.0,
            step=0.01,
            format="%.2f",
            label_visibility="collapsed",
            key="gift_new_unit_price",
        )
        note_col, image_col = st.columns([2, 1.2])
        note_col.markdown(
            '<div class="pudu-field-label">备注</div>',
            unsafe_allow_html=True,
        )
        remark = note_col.text_input(
            "备注",
            placeholder="可选",
            label_visibility="collapsed",
            key="gift_new_remark",
        )
        image_col.markdown(
            '<div class="pudu-field-label">物料图片</div>',
            unsafe_allow_html=True,
        )
        uploaded_file = image_col.file_uploader(
            "物料图片",
            type=["png", "jpg", "jpeg", "webp"],
            label_visibility="collapsed",
            key="gift_new_image",
        )
        confirmed = st.checkbox(
            "我确认现有周边礼品中没有所需物料，并创建新的周边礼品品类",
            key="gift_new_final_confirmed",
        )
        _, submit_col = st.columns([3, 1.15])
        submitted = submit_col.button(
            "确认新增并提交",
            type="primary",
            icon=":material/add_circle:",
            width="stretch",
            key="gift_new_submit",
        )
    if not submitted:
        return
    if not confirmed:
        st.warning("请先确认新增周边礼品。")
        return
    if not str(project_name or "").strip() or not str(material_name or "").strip():
        st.warning("请填写项目名称和新的物料名称。")
        return
    with fullscreen_data_sync("正在提交数据，请稍后......"):
        try:
            attachment_token = upload_gift_project_attachment(uploaded_file)
            task, _ = enqueue_feishu_background_write(
                QUEUE_TASK_TYPE_GIFT_PROJECT,
                {"operation": "new", "args": {"project_name": project_name, "material_name": material_name, "unit_price": float(unit_price), "remark": remark, "attachment_token": attachment_token}},
            )
        except Exception as exc:
            st.error("新增周边礼品失败，请检查品类名称、飞书字段和应用写入权限。")
            st.exception(exc)
            return
    for key in list(st.session_state):
        if str(key).startswith("gift_new_"):
            st.session_state.pop(key, None)
    st.session_state["gift_create_mode"] = False
    st.session_state["gift_project_submit_message"] = data_submission_success_message()
    st.rerun()


@st.dialog("周边礼品完整信息", width="large")
def render_gift_project_detail_drawer(item: dict) -> None:
    st.markdown(
        '<span class="pudu-gift-detail-drawer-marker"></span>',
        unsafe_allow_html=True,
    )
    product = str(item.get("material_name") or item.get("category") or "未命名物料")
    render_gift_image(list(item.get("attachments") or []), product)
    st.markdown(f"## {escape(product)}")
    status = str(item.get("status") or "未填写")
    project_name = str(item.get("project_name") or "未命名项目")
    usd_price = float(item.get("unit_price") or 0)
    rmb_price = float(item.get("unit_price_rmb") or 0)
    st.markdown(
        f"**{escape(ui_text('物料状态'))}**　{escape(ui_text(status))}\n\n"
        f"**{escape(ui_text('项目'))}**　{escape(project_name)}\n\n"
        f"**{escape(ui_text('单价'))}**　USD {usd_price:g} · RMB {rmb_price:.2f}"
    )
    st.divider()
    st.markdown("**备注**")
    st.write(str(item.get("remark") or "暂无备注"))
    supplier = str(item.get("supplier_contact") or "").strip()
    if supplier:
        st.markdown(f"**{escape(ui_text('供应商联系方式'))}**　{escape(supplier)}")


def remove_gift_batch_selected_item(
    session_state: MutableMapping[str, object],
    category_id: object,
) -> list[str]:
    target_id = str(category_id or "").strip()
    selected_ids = session_state.get("gift_batch_selected_ids", [])
    if not isinstance(selected_ids, (list, tuple, set)):
        selected_ids = []
    remaining_ids = sorted(
        {
            str(value or "").strip()
            for value in selected_ids
            if str(value or "").strip()
            and str(value or "").strip() != target_id
        }
    )
    session_state["gift_batch_selected_ids"] = remaining_ids
    return remaining_ids


def remove_gift_batch_new_item(
    session_state: MutableMapping[str, object],
) -> None:
    session_state.pop("gift_batch_new_line", None)


def render_gift_projects_page() -> None:
    message = st.session_state.pop("gift_project_submit_message", "")
    if message:
        st.success(message)
    with st.spinner("周边礼品数据加载中，请稍后......"):
        category_rows = safe_feishu_rows(CATEGORY_TABLE_NAME)
        material_rows = safe_feishu_rows(MATERIAL_TABLE_NAME)
        project_rows = safe_feishu_rows(GIFT_PROJECT_TABLE_NAME)
        gallery = gift_gallery_records_from_rows(
            category_rows,
            project_rows,
            material_rows,
        )
    project_records = gift_project_management_records(
        category_rows,
        project_rows,
        material_rows,
    )
    project_names = sorted(
        {
            str(project.get("project_name") or "")
            for project in project_records
            if str(project.get("project_name") or "").strip()
        }
    )
    page_mode = st.radio(
        "项目礼品管理功能",
        ["项目进度", "新增项目物料"],
        horizontal=True,
        index=0,
        key="gift_project_page_mode",
        label_visibility="collapsed",
    )
    if page_mode == "新增项目物料":
        directory_users = get_contact_users()
        owner_by_id = {
            str(item.get("open_id") or ""): item
            for item in directory_users
            if str(item.get("open_id") or "").strip()
        }
        owner_name_counts: dict[str, int] = {}
        for item in directory_users:
            owner_name = str(item.get("name") or "")
            owner_name_counts[owner_name] = owner_name_counts.get(owner_name, 0) + 1

        def gift_owner_label(open_id: object) -> str:
            item = owner_by_id.get(str(open_id), {})
            name = str(item.get("name") or open_id)
            department_paths = unique_preserve(
                [str(value) for value in list(item.get("department_paths") or [])]
            )
            label = f"{name} · {'、'.join(department_paths)}" if department_paths else name
            return (
                f"{label} · {str(open_id)[-6:]}"
                if owner_name_counts.get(name, 0) > 1
                else label
            )

        project_col, owner_col = st.columns(2)
        required_field_label(project_col, "项目名称")
        project_name = project_col.text_input("项目名称", key="gift_batch_project_name", label_visibility="collapsed")
        required_field_label(owner_col, "负责人")
        owner_open_id = owner_col.selectbox(
            "负责人",
            list(owner_by_id),
            index=None,
            format_func=gift_owner_label,
            placeholder="输入姓名搜索负责人",
            disabled=not owner_by_id,
            key="gift_batch_owner_open_id",
            label_visibility="collapsed",
        )
        owner = str(owner_by_id.get(str(owner_open_id), {}).get("name") or "")
        if not owner_by_id:
            owner_col.caption("通讯录中暂无可选成员，请刷新本页数据后重试。")
        st.caption("可从下方卡片多选已有周边礼品；也可用第一张卡片新建周边礼品并加入同一清单。")
        filtered_gallery = filter_gift_gallery_records(gallery, "")
        selected_ids = set(st.session_state.get("gift_batch_selected_ids", []))
        gift_lines = [item for item in filtered_gallery if str(item.get("record_id") or "") in selected_ids]
        new_line = st.session_state.get("gift_batch_new_line")
        with st.container(border=True):
            st.markdown('<span class="pudu-gift-batch-cart-marker"></span>', unsafe_allow_html=True)
            st.markdown(
                f"**{escape(ui_text('购物清单'))}：** "
                f"{len(gift_lines) + (1 if new_line else 0)} {escape(ui_text('项'))}"
            )
            if gift_lines or new_line:
                for item in gift_lines:
                    category_id = str(item.get("record_id") or "")
                    product = str(item.get("category") or "未命名周边礼品")
                    name_col, type_col, remove_col = st.columns([4.5, 2.2, 0.9])
                    name_col.markdown(
                        '<span class="pudu-gift-batch-item-marker"></span>'
                        f'<div class="pudu-gift-batch-item-name">{escape(product)}</div>',
                        unsafe_allow_html=True,
                    )
                    type_col.markdown(
                        '<div class="pudu-gift-batch-item-meta">已有品类</div>',
                        unsafe_allow_html=True,
                    )
                    if remove_col.button(
                        "移除",
                        icon=":material/delete:",
                        key=f"gift_cart_remove_{category_id}",
                        help=f"从购物清单移除：{product}",
                        width="stretch",
                    ):
                        remove_gift_batch_selected_item(st.session_state, category_id)
                        st.rerun()
                if new_line:
                    new_name = str(new_line.get("name") or "未命名周边礼品")
                    new_quantity = int(new_line.get("quantity") or 1)
                    name_col, type_col, remove_col = st.columns([4.5, 2.2, 0.9])
                    name_col.markdown(
                        '<span class="pudu-gift-batch-item-marker"></span>'
                        f'<div class="pudu-gift-batch-item-name">{escape(new_name)}</div>',
                        unsafe_allow_html=True,
                    )
                    type_col.markdown(
                        '<div class="pudu-gift-batch-item-meta">'
                        f"{escape(ui_text('待新建品类'))} · {escape(ui_text('数量'))} {new_quantity}"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    if remove_col.button(
                        "移除",
                        icon=":material/delete:",
                        key="gift_cart_remove_new",
                        help=f"从购物清单移除：{new_name}",
                        width="stretch",
                    ):
                        remove_gift_batch_new_item(st.session_state)
                        st.rerun()
            if st.button("批量提交", type="primary", key="gift_batch_submit"):
                if not str(project_name).strip() or not str(owner_open_id or "").strip():
                    st.error("项目名称和负责人均为必填项。")
                elif not gift_lines and not new_line:
                    st.error("请至少选择一个已有物料或加入一个新物料。")
                else:
                    with fullscreen_data_sync("正在提交数据，请稍后......"):
                        try:
                            task, _ = enqueue_feishu_background_write(
                                QUEUE_TASK_TYPE_GIFT_PROJECT,
                                {"operation": "batch", "args": {"project_name": project_name, "category_record_ids": [item.get("record_id") for item in gift_lines], "owner": owner, "owner_open_id": owner_open_id, "new_line": new_line}},
                            )
                        except Exception as exc:
                            st.error(f"批量任务未能进入后台队列：{exc}")
                            return
                    st.session_state["gift_batch_selected_ids"] = []
                    st.session_state.pop("gift_batch_new_line", None)
                    st.session_state["gift_project_submit_message"] = data_submission_success_message()
                    st.rerun()
        catalog_items = [*filtered_gallery]
        for row_start in range(0, len(catalog_items), 6):
            row_items = catalog_items[row_start : row_start + 6]
            card_columns = (
                st.columns([2, 1, 1, 1, 1, 1, 1], gap="small")
                if row_start == 0
                else st.columns(8, gap="small")
            )
            if row_start == 0:
                with card_columns[0].container(border=True):
                    st.markdown('<span class="pudu-gift-new-category-card-marker"></span>', unsafe_allow_html=True)
                    st.markdown('<div class="pudu-gift-new-category-card"><h3>需要新的周边品类，点击这里</h3><p>填写名称、数量和备注后加入清单</p></div>', unsafe_allow_html=True)
                    new_name = st.text_input("名称", key="gift_batch_new_name", label_visibility="collapsed", placeholder="新周边品类名称")
                    quantity_col, remark_col = st.columns([0.75, 1.25], gap="small")
                    new_quantity = quantity_col.number_input("数量", min_value=1, step=1, key="gift_batch_new_quantity")
                    new_remark = remark_col.text_input("备注", key="gift_batch_new_remark", placeholder="可选")
                    if st.button("加入清单", width="stretch", key="gift_batch_add_new"):
                        if not str(new_name).strip():
                            st.warning("请填写新周边品类名称。")
                        else:
                            st.session_state["gift_batch_new_line"] = {
                                "name": str(new_name).strip(),
                                "quantity": int(new_quantity),
                                "remark": str(new_remark or "").strip(),
                            }
                            st.rerun()
            offset = 1 if row_start == 0 else 0
            for column_index, item in enumerate(row_items):
                category_id = str(item.get("record_id") or "")
                product = str(item.get("category") or "")
                with card_columns[column_index + offset].container(border=True):
                    st.markdown('<span class="pudu-gift-catalog-card-marker"></span>', unsafe_allow_html=True)
                    render_gift_image(list(item.get("attachments") or []), product)
                    st.markdown(f'<div class="pudu-gift-catalog-title">{escape(product)}</div>', unsafe_allow_html=True)
                    is_selected = category_id in selected_ids
                    if st.button("移出清单" if is_selected else "加入清单", width="stretch", key=f"gift_select_{category_id}"):
                        if is_selected:
                            selected_ids.remove(category_id)
                        else:
                            selected_ids.add(category_id)
                        st.session_state["gift_batch_selected_ids"] = sorted(selected_ids)
                        st.rerun()
        return

    if not project_names:
        st.info("当前还没有可选择的项目礼品。")
        selected_project = ""
        selected_records = []
    else:
        selected_project = st.pills(
            "选择项目",
            project_names,
            selection_mode="single",
            default=project_names[0],
            key="gift_project_filter",
            width="stretch",
        )
        selected_records = [
            item for item in project_records if item.get("project_name") == selected_project
        ]
    if project_names and not selected_records:
        st.info("当前项目没有匹配的周边礼品记录。")
    elif selected_records:
        for stage in GIFT_PROJECT_PROGRESS_STAGES:
            stage_records = sorted(
                (item for item in selected_records if gift_project_progress_stage(item.get("status")) == stage),
                key=lambda item: str(item.get("material_name") or item.get("category") or ""),
            )
            expander_label = f"{stage} · {len(stage_records)}" if stage_records else stage
            with st.expander(expander_label, expanded=bool(stage_records)):
                stage_class = GIFT_PROJECT_STAGE_CLASSES[stage]
                st.markdown(
                    f'<span class="pudu-project-progress-stage-marker pudu-project-stage-{stage_class}"></span>',
                    unsafe_allow_html=True,
                )
                if not stage_records:
                    st.markdown(
                        '<div class="pudu-project-empty-stage">当前流程阶段暂无物料</div>',
                        unsafe_allow_html=True,
                    )
                    continue
                stage_columns = st.columns(4, gap="small")
                for item_index, item in enumerate(stage_records):
                    product = str(item.get("material_name") or item.get("category") or "")
                    usd_price = float(item.get("unit_price") or 0)
                    rmb_price = float(item.get("unit_price_rmb") or 0)
                    status = str(item.get("status") or "未填写")
                    status_class = "pudu-project-progress-status"
                    if stage in ("已提需", "待确认下单"):
                        status_class += " pudu-project-progress-status--requested"
                    elif stage in ("寻源中", "设计制作中"):
                        status_class += " pudu-project-progress-status--design"
                    elif stage == "到货":
                        status_class += " pudu-project-progress-status--arrived"
                    elif stage == "已发货":
                        status_class += " pudu-project-progress-status--stock"
                    with stage_columns[item_index % len(stage_columns)].container(border=True):
                        st.markdown('<span class="pudu-project-progress-card-marker"></span>', unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="{status_class}">{escape(ui_text("物料状态"))}：{escape(ui_text(status))}</div>',
                            unsafe_allow_html=True,
                        )
                        render_gift_image(list(item.get("attachments") or []), product)
                        st.markdown(f'<div class="pudu-project-progress-title" title="{escape(product)}">{escape(product)}</div>', unsafe_allow_html=True)
                        st.markdown(
                            f'<div class="pudu-project-progress-meta"><strong>{escape(ui_text("项目"))}：</strong>{escape(str(item.get("project_name") or ui_text("未命名项目")))}<br><strong>{escape(ui_text("单价"))}：</strong>USD {usd_price:g} · RMB {rmb_price:.2f}</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown('<div class="pudu-project-progress-note-label">备注</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="pudu-project-progress-note">{escape(str(item.get("remark") or "暂无备注"))}</div>', unsafe_allow_html=True)
                        supplier = str(item.get("supplier_contact") or "").strip()
                        if supplier:
                            st.caption(f"{ui_text('供应商联系方式')}：{supplier}")
                        if st.button(
                            "查看完整信息",
                            icon=":material/arrow_forward:",
                            width="stretch",
                            key=f"gift_detail_{item.get('record_id') or item_index}",
                        ):
                            render_gift_project_detail_drawer(item)



def cultural_claimability(stock: object) -> str:
    return CULTURAL_CLAIMABLE_YES if int(stock or 0) > 0 else CULTURAL_CLAIMABLE_NO


def cultural_stock_fields(stock: object, *, initialize: bool = False) -> dict[str, object]:
    quantity = int(stock or 0)
    fields: dict[str, object] = {"当前库存": quantity}
    if quantity <= 0 or initialize:
        fields[CULTURAL_CLAIMABLE_FIELD] = cultural_claimability(quantity)
    return fields


def sync_cultural_material_claimability(
    rows: list[dict] | None = None,
) -> dict[str, int]:
    """Keep claimability aligned with stock before Worker/cache publication."""
    if rows is None:
        # Cache jobs are long-lived processes; refresh schema so newly-added
        # control fields are writable immediately instead of being filtered out.
        refresh_feishu_schema_cache()
    resolved_rows = list(
        rows if rows is not None else fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME)
    )
    updates: list[dict[str, object]] = []
    for row in resolved_rows:
        fields = feishu_fields(row)
        stock = feishu_int(fields, "当前库存")
        current = feishu_text(fields, CULTURAL_CLAIMABLE_FIELD).strip()
        # Initialize the newly-added selector for historical positive-stock rows,
        # while preserving an administrator's explicit manual "否" choice.
        expected = CULTURAL_CLAIMABLE_NO if stock <= 0 else CULTURAL_CLAIMABLE_YES
        if stock > 0 and current:
            continue
        if current == expected:
            continue
        record_id = feishu_record_id(row)
        if record_id:
            updates.append({"record_id": record_id, "fields": {CULTURAL_CLAIMABLE_FIELD: expected}})
    written = (
        feishu_batch_update_record_fields(CULTURAL_MATERIAL_TABLE_NAME, updates)
        if updates else 0
    )
    if updates and rows is None:
        verified_rows = fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME)
        verified_by_id = {feishu_record_id(row): row for row in verified_rows}
        failed = [
            item["record_id"]
            for item in updates
            if feishu_text(
                feishu_fields(verified_by_id.get(item["record_id"], {})),
                CULTURAL_CLAIMABLE_FIELD,
            ).strip()
            != str(item["fields"][CULTURAL_CLAIMABLE_FIELD])
        ]
        if failed:
            raise RuntimeError(
                f"文化周边是否可以申领字段写入后校验失败：{len(failed)} 条"
            )
    return {"checked_count": len(resolved_rows), "updated_count": written}


def cultural_request_catalog(
    cultural_rows: list[dict] | None = None,
    category_rows: list[dict] | None = None,
    model_rows: list[dict] | None = None,
    *,
    include_all_categories_for_admin: bool = False,
    include_unclaimable_combinations: bool = False,
) -> dict[str, object]:
    """Build the culture-only category/model/region catalog from page cache."""
    culture = list(cultural_rows if cultural_rows is not None else feishu_rows(CULTURAL_MATERIAL_TABLE_NAME))
    categories = list(category_rows if category_rows is not None else feishu_rows(CATEGORY_TABLE_NAME))
    models = list(model_rows if model_rows is not None else feishu_rows(MODEL_TABLE_NAME))
    category_labels: dict[str, dict[str, str]] = {}
    category_ids: dict[str, str] = {}
    for row in categories:
        fields = feishu_fields(row)
        if feishu_text(fields, "品类定义") != CATEGORY_DEFINITION_CULTURAL:
            continue
        if not include_all_categories_for_admin and not feishu_request_page_visible(fields):
            continue
        name = feishu_text(fields, "物料品类").strip()
        if not name:
            continue
        category_ids[name] = feishu_record_id(row)
        category_labels[name] = {
            LANGUAGE_ZH: feishu_text(fields, "中文页面名称") or name,
            LANGUAGE_EN: feishu_text(fields, "英文页面名称") or name,
        }
    model_ids = {
        feishu_text(feishu_fields(row), "产品型号").strip(): feishu_record_id(row)
        for row in models
        if feishu_text(feishu_fields(row), "产品型号").strip()
    }
    combinations: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in culture:
        fields = feishu_fields(row)
        if (
            not include_unclaimable_combinations
            and feishu_text(fields, CULTURAL_CLAIMABLE_FIELD).strip()
            != CULTURAL_CLAIMABLE_YES
        ):
            continue
        product = feishu_text(fields, "物料品类").strip()
        model = feishu_text(fields, "产品型号").strip()
        region = feishu_text(fields, "战区管理").strip()
        if not product or product not in category_ids or not model or not region:
            continue
        combinations[(product, model, region)] = {
            "record_id": feishu_record_id(row),
            "product": product,
            "model": model,
            "region": region,
            "stock": feishu_int(fields, "当前库存"),
            "unit_price_rmb": feishu_float(fields, "单价（人民币）"),
        }
    products = unique_preserve(key[0] for key in combinations)
    return {
        "products": products,
        "category_labels": category_labels,
        "category_ids": category_ids,
        "model_ids": model_ids,
        "combinations": combinations,
    }


def execute_region_dimension_management(draft: dict[str, object]) -> dict[str, object]:
    """Apply region CRUD and its culture-inventory association plan."""
    refresh_feishu_schema_cache()
    operation = str(draft.get("operation") or "")
    record_id = str(draft.get("record_id") or "")
    name = str(draft.get("name") or "").strip()
    status = normalize_enabled_status(draft.get("status"))
    records = dimension_management_records("region", fresh_feishu_rows(REGION_TABLE_NAME))
    by_id = {item["record_id"]: item for item in records}
    if operation != "create" and record_id not in by_id:
        raise ValueError("所选战区不存在，请刷新页面后重试。")
    if not name:
        raise ValueError("请填写战区名称。")
    duplicate = next((item for item in records if normalize_option_label(item["name"]).casefold() == normalize_option_label(name).casefold() and item["record_id"] != record_id), None)
    if duplicate:
        raise ValueError("该战区名称已经存在。")
    created_count = 0
    if operation == "create":
        created = feishu_batch_create_records(REGION_TABLE_NAME, [{"战区名称": name, "启用状态": status}])
        record_id = feishu_record_id(created[0] if created else {})
        created_count = len(created)
    elif operation == "edit":
        feishu_update_record_fields(REGION_TABLE_NAME, record_id, {"战区名称": name, "启用状态": status})
    elif operation != "delete":
        raise ValueError("不支持的战区管理操作。")

    changes = [dict(item) for item in list(draft.get("changes") or []) if isinstance(item, dict)]
    current_rows = {str(item.get("record_id") or ""): item for item in load_cultural_dimension_inventory_records(fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME))}
    delete_ids: list[str] = []
    updates: list[dict[str, object]] = []
    creates: list[dict[str, object]] = []
    for item in changes:
        action = str(item.get("action") or "")
        item_id = str(item.get("record_id") or "")
        if action in {"update", "delete"} and item_id not in current_rows:
            raise RuntimeError("预览后关联文化周边已变化，请返回刷新后重新提交。")
        if action == "delete":
            delete_ids.append(item_id)
        elif action == "update":
            updates.append({"record_id": item_id, "fields": {"战区管理": name}})
        elif action == "create":
            category = str(item.get("category") or "")
            model = str(item.get("model") or "")
            category_id = _cultural_dimension_record_id(CATEGORY_TABLE_NAME, "物料品类", category)
            model_id = _cultural_dimension_record_id(MODEL_TABLE_NAME, "产品型号", model)
            if not category_id or not model_id:
                raise RuntimeError("战区关联的文化周边品类或型号不存在。")
            creates.append({
                "文化周边编码": f"CUL-{uuid.uuid4().hex[:8].upper()}",
                "物料品类": category, "产品型号": model, "战区管理": name,
                **cultural_stock_fields(0), "单价（人民币）": 0.0, "备注": "",
                "物料品类关联": [category_id], "产品型号关联": [model_id],
            })
    created_rows = feishu_batch_create_records(CULTURAL_MATERIAL_TABLE_NAME, creates) if creates else []
    updated_count = feishu_batch_update_record_fields(CULTURAL_MATERIAL_TABLE_NAME, updates)
    deleted_material_count = feishu_batch_delete_record_ids(CULTURAL_MATERIAL_TABLE_NAME, delete_ids)
    deleted_count = feishu_batch_delete_record_ids(REGION_TABLE_NAME, [record_id]) if operation == "delete" else 0
    return {"operation": operation, "created_count": created_count, "created_material_count": len(created_rows), "updated_material_count": updated_count, "deleted_material_count": deleted_material_count, "deleted_count": deleted_count}


def load_cultural_dimension_inventory_records(
    rows: list[dict] | None = None,
) -> list[dict[str, object]]:
    """Normalize culture inventory rows for the shared dimension editor."""
    return [
        {
            "record_id": feishu_record_id(row),
            "material_code": feishu_text(feishu_fields(row), "文化周边编码"),
            "category": feishu_text(feishu_fields(row), "物料品类"),
            "model": feishu_text(feishu_fields(row), "产品型号"),
            # The shared category-plan engine uses its second dimension slot;
            # for culture inventory that slot represents region, not language.
            "language": feishu_text(feishu_fields(row), "战区管理"),
            "region": feishu_text(feishu_fields(row), "战区管理"),
            "quantity": feishu_int(feishu_fields(row), "当前库存"),
            "unit_price": feishu_float(feishu_fields(row), "单价（人民币）"),
            "remark": feishu_text(feishu_fields(row), "备注"),
            "status": STATUS_ACTIVE,
            "request_visible": REQUEST_PAGE_VISIBLE_VALUE,
        }
        for row in list(rows if rows is not None else safe_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME))
        if feishu_record_id(row)
    ]


def cultural_request_display_category(product: object, catalog: dict[str, object]) -> str:
    labels = dict(dict(catalog.get("category_labels") or {}).get(str(product), {}) or {})
    return str(labels.get(get_ui_language()) or product)


CULTURAL_SIZE_ORDER = (
    "2XS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL", "6XL", "7XL", "8XL"
)
CULTURAL_REQUEST_MAX_TOTAL_QUANTITY = 2
CULTURAL_REQUEST_CUMULATIVE_FIELD = "POLO申领数量累计"
CULTURAL_JACKET_CATEGORY = "文化夹克"
CULTURAL_JACKET_MAX_TOTAL_QUANTITY = 1
CULTURAL_JACKET_CUMULATIVE_FIELD = "文化夹克申领数量累计"
CULTURAL_REQUEST_MESSAGE_IDS_FIELD = "文化周边消息ID"
CULTURAL_REQUEST_STATUS_ISSUED = "已发放"
CULTURAL_REQUEST_STATUS_REJECTING = "驳回处理中"
CULTURAL_REQUEST_STATUS_REJECTED = "已驳回"

CORPORATE_APPAREL_REQUEST_TYPE = "企业文化衫领取"
CORPORATE_APPAREL_LINE_TYPE = "企业文化衫"
CORPORATE_APPAREL_STYLE_MAP = {
    "T恤-黑色（短袖）": "文化衫-休闲T恤-黑色（短袖）",
    "休闲商务POLO-黑色（短袖）": "文化衫-休闲商务POLO-黑色（短袖）",
    "休闲商务夹克-黑色（长袖）": "文化衫-休闲商务夹克-黑色（长袖）",
    "商务衬衫-黑色（长袖）": "文化衫-商务衬衫-黑色（长袖）",
    "冲锋衣-黑色": "文化衫-休闲冲锋衣-黑色",
}
CORPORATE_APPAREL_QUOTA_FIELDS = {
    "T恤-黑色（短袖）": (("T恤-黑色（短袖）申领数量累计",), 1),
    "休闲商务POLO-黑色（短袖）": ((CULTURAL_REQUEST_CUMULATIVE_FIELD,), CULTURAL_REQUEST_MAX_TOTAL_QUANTITY),
    "休闲商务夹克-黑色（长袖）": ((CULTURAL_JACKET_CUMULATIVE_FIELD,), CULTURAL_JACKET_MAX_TOTAL_QUANTITY),
    "商务衬衫-黑色（长袖）": (("商务衬衫-黑色（长袖）申领数量累计", "商务衬衫-黑色（长袖）神灵数量累计"), 1),
    "冲锋衣-黑色": (("冲锋衣-黑色申领数量累计",), 1),
}
CORPORATE_APPAREL_LINE_MARKER = "企业文化衫库存记录ID"


def corporate_apparel_source_record_id(source_id: object) -> str:
    """Extract the writable source record id from a connector-sync SourceID."""
    encoded = str(source_id or "").strip()
    if not encoded:
        return ""
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""
    return next((part for part in decoded.split(":") if part.startswith("rec")), "")


def corporate_apparel_source_record_id_for_sync_record(sync_record_id: str) -> str:
    normalized = str(sync_record_id or "").strip()
    if not normalized:
        return ""
    source_row = next(
        (
            row for row in fresh_feishu_rows(CORPORATE_APPAREL_TABLE_NAME)
            if feishu_record_id(row) == normalized
        ),
        None,
    )
    return corporate_apparel_source_record_id(feishu_fields(source_row or {}).get("SourceID"))


def update_corporate_apparel_source_redeemed(item: dict[str, object], target: int) -> None:
    source_record_id = str(item.get("source_record_id") or "").strip()
    if not source_record_id:
        source_record_id = corporate_apparel_source_record_id_for_sync_record(
            str(item.get("record_id") or "")
        )
    if not source_record_id:
        raise RuntimeError("企业文化衫同步记录缺少可写入的行政源记录 ID。")
    corporate_apparel_source_client().update_record(
        CORPORATE_APPAREL_SOURCE_TABLE_ID,
        source_record_id,
        {"系统兑换数量": int(target)},
    )


def corporate_apparel_catalog(
    rows: list[dict] | None = None,
    *,
    source_rows: list[dict] | None = None,
) -> dict[str, object]:
    """Return the five claimable corporate-apparel styles from the shared source."""
    synced_rows = list(
        rows if rows is not None else safe_feishu_rows(CORPORATE_APPAREL_TABLE_NAME)
    )
    display_by_source = {value: key for key, value in CORPORATE_APPAREL_STYLE_MAP.items()}
    source_by_id = (
        {feishu_record_id(row): row for row in source_rows}
        if source_rows is not None else None
    )
    items: list[dict[str, object]] = []
    for row in synced_rows:
        synced_fields = feishu_fields(row)
        source_record_id = corporate_apparel_source_record_id(synced_fields.get("SourceID"))
        if source_by_id is not None:
            source_row = source_by_id.get(source_record_id)
            if source_row is None:
                raise RuntimeError("企业文化衫同步记录未匹配到行政源表，库存数据无法核实。")
            fields = feishu_fields(source_row)
        else:
            fields = synced_fields
        source_style = feishu_text(fields, "款式").strip()
        product = display_by_source.get(source_style)
        record_id = feishu_record_id(row)
        if not product or not record_id:
            continue
        latest_inventory = feishu_int(fields, "最新库存")
        redeemed = feishu_int(fields, "系统兑换数量")
        size = feishu_text(fields, "码数").strip() or "均码"
        attachments = synced_fields.get("图片") if isinstance(synced_fields.get("图片"), list) else []
        images = [
            str(item.get("cached_path") or "").strip()
            for item in attachments
            if isinstance(item, dict) and str(item.get("cached_path") or "").strip()
        ]
        items.append(
            {
                "record_id": record_id,
                "source_record_id": source_record_id,
                "product": product,
                "source_style": source_style,
                "size": size,
                "code": feishu_text(fields, "编码").strip(),
                "latest_inventory": latest_inventory,
                "system_redeemed": redeemed,
                "available": latest_inventory - redeemed,
                "images": images,
            }
        )
    order = {name: index for index, name in enumerate(CORPORATE_APPAREL_STYLE_MAP)}
    items.sort(key=lambda item: (order.get(str(item["product"]), 99), cultural_size_sort_key(item["size"])))
    return {"products": list(CORPORATE_APPAREL_STYLE_MAP), "items": items}


def _corporate_apparel_quota_field(product: str) -> tuple[str, int]:
    aliases, limit = CORPORATE_APPAREL_QUOTA_FIELDS[product]
    for field_name in aliases:
        if feishu_has_field(USER_PERMISSION_TABLE_NAME, field_name):
            return field_name, limit
    return aliases[0], limit


def validate_corporate_apparel_cached_quota(
    requester_open_id: str,
    lines: list[dict[str, object]],
    permission_rows: list[dict],
) -> list[dict[str, object]]:
    """Validate per-person apparel limits from the currently published permission cache.

    The worker repeats this check against fresh Feishu data before writing.  This
    cache-backed pass exists so the web page can reject an over-limit request
    immediately instead of accepting a queue task that is guaranteed to fail.
    """
    open_id = str(requester_open_id or "").strip()
    permission_row = next(
        (
            row for row in permission_rows
            if open_id in feishu_person_open_ids(
                feishu_fields(row), ["用户账号", "用户", "成员"]
            )
        ),
        None,
    )
    permission_fields = feishu_fields(permission_row or {})
    requested_by_product: dict[str, int] = {}
    for raw in lines:
        product = str(raw.get("product") or "").strip()
        quantity = int(raw.get("quantity") or 0)
        if product not in CORPORATE_APPAREL_QUOTA_FIELDS or quantity <= 0:
            raise RuntimeError("企业文化衫领取明细无效。")
        requested_by_product[product] = requested_by_product.get(product, 0) + quantity

    snapshots: list[dict[str, object]] = []
    for product, requested in requested_by_product.items():
        aliases, limit = CORPORATE_APPAREL_QUOTA_FIELDS[product]
        field_name = next((name for name in aliases if name in permission_fields), aliases[0])
        current = feishu_int(permission_fields, field_name)
        target = current + requested
        if target > limit:
            remaining = max(0, limit - current)
            raise RuntimeError(
                f"{product} 每人累计最多领取 {limit} 件，当前已领取 {current} 件，"
                f"本次最多还能领取 {remaining} 件。"
            )
        snapshots.append(
            {
                "product": product,
                "field": field_name,
                "current": current,
                "requested": requested,
                "target": target,
                "limit": limit,
            }
        )
    return snapshots


def ensure_corporate_apparel_quota_fields() -> None:
    refresh_feishu_schema_cache()
    missing: list[str] = []
    for product in CORPORATE_APPAREL_STYLE_MAP:
        aliases, _ = CORPORATE_APPAREL_QUOTA_FIELDS[product]
        if not any(feishu_has_field(USER_PERMISSION_TABLE_NAME, name) for name in aliases):
            missing.append(aliases[0])
    if not missing:
        return
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建企业文化衫领取额度字段。")
    table_id = feishu_table_id(USER_PERMISSION_TABLE_NAME)
    for field_name in missing:
        client.create_field(table_id, field_name, 2)
    refresh_feishu_schema_cache()


def corporate_apparel_request_plan(
    request_payload: dict[str, object], lines: list[dict[str, object]]
) -> dict[str, object]:
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    if not requester_open_id.startswith("ou_"):
        raise RuntimeError("请选择已关联飞书账号的申请人。")
    ensure_requester_sales_permission(request_payload)
    ensure_corporate_apparel_quota_fields()
    permission_row = next(
        (
            row for row in fresh_feishu_rows(USER_PERMISSION_TABLE_NAME)
            if requester_open_id in feishu_person_open_ids(
                feishu_fields(row), ["用户账号", "用户", "成员"]
            )
        ),
        None,
    )
    permission_record_id = feishu_record_id(permission_row or {})
    if not permission_record_id:
        raise RuntimeError("申请人权限记录创建失败，请稍后重试。")
    authoritative_source_rows = corporate_apparel_source_client().list_records(
        CORPORATE_APPAREL_SOURCE_TABLE_ID
    )
    catalog_items = {
        (str(item["product"]), str(item["size"])): item
        for item in corporate_apparel_catalog(
            fresh_feishu_rows(CORPORATE_APPAREL_TABLE_NAME),
            source_rows=authoritative_source_rows,
        )["items"]
    }
    prepared: list[dict[str, object]] = []
    requested_by_product: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for raw in lines:
        product = str(raw.get("product") or "").strip()
        size = str(raw.get("size") or raw.get("model") or "").strip()
        quantity = int(raw.get("quantity") or 0)
        if product not in CORPORATE_APPAREL_STYLE_MAP or quantity <= 0:
            raise RuntimeError("企业文化衫领取明细无效。")
        key = (product, size)
        if key in seen:
            raise RuntimeError("同一品类和尺码不能重复提交。")
        seen.add(key)
        item = catalog_items.get(key)
        if not item:
            raise RuntimeError(f"未找到企业文化衫库存组合：{product} / {size}")
        if int(item["available"]) < quantity:
            raise RuntimeError(f"{product} / {size} 可领取库存不足。")
        requested_by_product[product] = requested_by_product.get(product, 0) + quantity
        prepared.append(
            {
                **item,
                "quantity": quantity,
                "target_system_redeemed": int(item["system_redeemed"]) + quantity,
            }
        )
    if not prepared:
        raise RuntimeError("请至少选择一件企业文化衫。")
    quota_targets: list[dict[str, object]] = []
    permission_fields = feishu_fields(permission_row or {})
    for product, requested in requested_by_product.items():
        field_name, limit = _corporate_apparel_quota_field(product)
        current = feishu_int(permission_fields, field_name)
        target = current + requested
        if target > limit:
            raise RuntimeError(f"{product} 每人累计最多领取 {limit} 件，当前已领取 {current} 件。")
        quota_targets.append(
            {"product": product, "field": field_name, "current": current, "target": target, "limit": limit}
        )
    return {
        "permission_record_id": permission_record_id,
        "items": prepared,
        "quota_targets": quota_targets,
    }


def queued_corporate_apparel_request_payload(
    request_payload: dict[str, object], lines: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "version": 1,
        "request_payload": {
            key: request_payload.get(key)
            for key in ("requester", "requester_open_id", "department", "department_id", "material_usage", "submission_token")
        },
        "lines": [
            {
                "product": str(line.get("product") or ""),
                "size": str(line.get("size") or line.get("model") or ""),
                "quantity": int(line.get("quantity") or 0),
            }
            for line in lines if isinstance(line, dict) and int(line.get("quantity") or 0) > 0
        ],
    }


def submit_feishu_corporate_apparel_request(
    request_payload: dict[str, object], plan: dict[str, object]
) -> tuple[str, int, bool]:
    refresh_feishu_schema_cache()
    ensure_cultural_request_workflow_fields()
    token = str(request_payload.get("submission_token") or "").strip()
    items = [dict(item) for item in list(plan.get("items") or [])]
    source_client = corporate_apparel_source_client()
    source_fields = {
        str(field.get("field_name") or "")
        for field in source_client.list_fields(CORPORATE_APPAREL_SOURCE_TABLE_ID)
    }
    if "系统兑换数量" not in source_fields:
        raise RuntimeError("行政源表缺少‘系统兑换数量’字段，无法登记企业文化衫领取。")
    for item in items:
        if not (
            str(item.get("source_record_id") or "").strip()
            or corporate_apparel_source_record_id_for_sync_record(str(item.get("record_id") or ""))
        ):
            raise RuntimeError("企业文化衫同步记录缺少可写入的行政源记录 ID。")
    detail_text = "\n".join(
        f"{index:02d}. {item['product']} / {item['size']} × {int(item['quantity'])}"
        for index, item in enumerate(items, start=1)
    )
    existing_rows = submission_token_rows(token)
    if existing_rows:
        request_row = existing_rows[0]
        request_record_id = feishu_record_id(request_row)
        request_no = feishu_text(feishu_fields(request_row), "申请单号")
        created_new = False
    else:
        request_no = next_request_no()
        request_fields: dict[str, object] = {
            "申请单号": request_no,
            "标题": f"{request_payload.get('requester') or '申请人'}-企业文化衫领取",
            "申请部门/区域": request_payload.get("department"),
            "申请部门": request_payload.get("department"),
            "业务类型": CORPORATE_APPAREL_REQUEST_TYPE,
            "申请类型": CORPORATE_APPAREL_REQUEST_TYPE,
            "审批状态": "无需审批",
            "文化周边处理状态": CULTURAL_REQUEST_STATUS_ISSUED,
            "文化周边通知状态": "待发送",
            "物料用途": str(request_payload.get("material_usage") or "").strip(),
            "物料明细文字信息": detail_text,
            "提交时间": feishu_datetime_value(REQUEST_TABLE_NAME, "提交时间", datetime.now()),
            "提交幂等键": token,
        }
        set_first_person_or_plain_field(
            REQUEST_TABLE_NAME, request_fields, ["申请人", "申请人姓名"],
            request_payload.get("requester"), request_payload.get("requester_open_id"),
        )
        set_first_plain_field(REQUEST_TABLE_NAME, request_fields, ["申请人OpenID"], request_payload.get("requester_open_id"))
        created = feishu_create_record(REQUEST_TABLE_NAME, request_fields)
        request_record_id = feishu_record_id(created)
        created_new = True
    existing_lines = {
        feishu_text(feishu_fields(row), "明细编号"): row
        for row in fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
    }
    for index, item in enumerate(items, start=1):
        line_no = f"{request_no}-{index:02d}"
        if line_no not in existing_lines:
            feishu_create_record(
                REQUEST_LINE_TABLE_NAME,
                {
                    "明细编号": line_no,
                    "申请单号": request_no,
                    "申请数量": int(item["quantity"]),
                    "审批通过数量": int(item["quantity"]),
                    "实际发放数量": int(item["quantity"]),
                    "物料数量": int(item["quantity"]),
                    "品类名称": item["product"],
                    "产品型号名称": item["size"],
                    "明细业务类型": CORPORATE_APPAREL_LINE_TYPE,
                    "明细状态": "已发放",
                    "备注": f"{CORPORATE_APPAREL_LINE_MARKER}:{item['record_id']}",
                    "所属申请单": [request_record_id],
                },
            )
        update_corporate_apparel_source_redeemed(
            item, int(item["target_system_redeemed"])
        )
    quota_fields = {
        str(item["field"]): int(item["target"])
        for item in list(plan.get("quota_targets") or [])
    }
    feishu_update_record_fields(
        USER_PERMISSION_TABLE_NAME,
        str(plan.get("permission_record_id") or ""),
        quota_fields,
    )
    return request_no, len(items), created_new


def _corporate_apparel_card(
    request_no: str, requester: str, lines: list[dict[str, object]], *, applicant: bool,
    material_usage: str = "",
) -> dict[str, object]:
    title = "企业文化衫领取已提交" if applicant else "企业文化衫领取通知"
    table_lines = [
        {"product": line.get("product"), "model": line.get("size") or line.get("model"), "quantity": line.get("quantity")}
        for line in lines
    ]
    elements: list[dict[str, object]] = [
        {"tag": "markdown", "content": "您的领取申请已登记。" if applicant else f"{requester} 提交了企业文化衫领取申请。"},
        {"tag": "markdown", "content": f"**申请单号**：{request_no}\n\n**申请事由**：{material_usage or '未填写'}\n\n**领取明细**"},
        _feishu_requester_material_table(table_lines),
    ]
    if not applicant:
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "驳回申领"},
                "type": "danger_filled",
                "width": "fill",
                "value": {"action": "reject_corporate_apparel_request", "request_no": request_no},
                "confirm": {
                    "title": {"tag": "plain_text", "content": "确认驳回企业文化衫领取"},
                    "text": {"tag": "plain_text", "content": "驳回后将恢复系统兑换数量和个人领取额度。"},
                },
            }
        )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default", "summary": {"content": title}},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
        "body": {"direction": "vertical", "padding": "12px 12px 16px 12px", "elements": elements},
    }


def corporate_apparel_notification_targets(
    request_no: str, request_payload: dict[str, object], lines: list[dict[str, object]]
) -> list[dict[str, object]]:
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    requester = str(request_payload.get("requester") or "申请人")
    material_usage = str(request_payload.get("material_usage") or "").strip()
    targets: list[dict[str, object]] = []
    if requester_open_id:
        targets.append({
            "key": f"applicant:{requester_open_id}", "audience": "applicant",
            "recipient_id": requester_open_id,
            "card": _corporate_apparel_card(request_no, requester, lines, applicant=True, material_usage=material_usage),
        })
    for open_id in enabled_role_open_ids("HR"):
        targets.append({
            "key": f"hr:{open_id}", "audience": "hr", "recipient_id": open_id,
            "card": _corporate_apparel_card(request_no, requester, lines, applicant=False, material_usage=material_usage),
        })
    return targets


def corporate_apparel_request_context(request_no: str) -> dict[str, object]:
    normalized_no = str(request_no or "").strip()
    request_row = next(
        (
            row for row in fresh_feishu_rows(REQUEST_TABLE_NAME)
            if feishu_text(feishu_fields(row), "申请单号").strip() == normalized_no
        ),
        None,
    )
    if request_row is None:
        raise RuntimeError("未找到企业文化衫领取申请单。")
    request_fields = feishu_fields(request_row)
    if (
        feishu_text(request_fields, "业务类型").strip() != CORPORATE_APPAREL_REQUEST_TYPE
        and feishu_text(request_fields, "申请类型").strip() != CORPORATE_APPAREL_REQUEST_TYPE
    ):
        raise RuntimeError("该申请单不是企业文化衫领取申请。")
    request_id = feishu_record_id(request_row)
    requester_ids = feishu_person_open_ids(request_fields, ["申请人", "申请人姓名"])
    lines: list[dict[str, object]] = []
    for row in fresh_feishu_rows(REQUEST_LINE_TABLE_NAME):
        fields = feishu_fields(row)
        if feishu_text(fields, "明细业务类型").strip() != CORPORATE_APPAREL_LINE_TYPE:
            continue
        linked = feishu_link_ids_any(fields, ["所属申请单", "申请单"])
        if request_id not in linked and feishu_text(fields, "申请单号").strip() != normalized_no:
            continue
        marker = feishu_text(fields, "备注").strip()
        record_id = marker.split(":", 1)[1].strip() if marker.startswith(f"{CORPORATE_APPAREL_LINE_MARKER}:") else ""
        lines.append(
            {
                "line_record_id": feishu_record_id(row),
                "record_id": record_id,
                "product": feishu_text(fields, "品类名称").strip(),
                "size": feishu_text(fields, "产品型号名称").strip(),
                "quantity": feishu_int(fields, "申请数量"),
            }
        )
    if not lines:
        raise RuntimeError("企业文化衫领取申请没有可驳回的明细。")
    return {
        "request": {
            "record_id": request_id,
            "request_no": normalized_no,
            "requester": request_applicant_text(request_fields) or "申请人",
            "requester_open_id": requester_ids[0] if requester_ids else "",
            "status": feishu_text(request_fields, "文化周边处理状态"),
            "message_ids": _cultural_request_message_ids(request_fields),
        },
        "lines": lines,
    }


def corporate_apparel_rejection_plan(request_no: str, operator_open_id: str) -> dict[str, object]:
    if str(operator_open_id or "").strip() not in enabled_role_open_ids("HR"):
        raise PermissionError("只有已启用的 HR 可以驳回企业文化衫领取申请。")
    context = corporate_apparel_request_context(request_no)
    request = dict(context["request"])
    if str(request.get("status") or "") == CULTURAL_REQUEST_STATUS_REJECTED:
        return {"already_rejected": True, "context": context, "stock_targets": [], "quota_targets": []}
    source_by_id = {
        feishu_record_id(row): row for row in fresh_feishu_rows(CORPORATE_APPAREL_TABLE_NAME)
    }
    authoritative_source_by_id = {
        feishu_record_id(row): row
        for row in corporate_apparel_source_client().list_records(
            CORPORATE_APPAREL_SOURCE_TABLE_ID
        )
    }
    requested_by_product: dict[str, int] = {}
    stock_targets: list[dict[str, object]] = []
    for line in list(context["lines"]):
        item = dict(line)
        source = source_by_id.get(str(item.get("record_id") or ""))
        if source is None:
            raise RuntimeError("企业文化衫领取明细缺少有效的源库存记录。")
        source_record_id = corporate_apparel_source_record_id(
            feishu_fields(source).get("SourceID")
        )
        authoritative_source = authoritative_source_by_id.get(source_record_id)
        if authoritative_source is None:
            raise RuntimeError("企业文化衫领取明细未匹配到行政源库存记录。")
        quantity = max(0, int(item.get("quantity") or 0))
        product = str(item.get("product") or "")
        requested_by_product[product] = requested_by_product.get(product, 0) + quantity
        current = feishu_int(feishu_fields(authoritative_source), "系统兑换数量")
        stock_targets.append({
            **item,
            "source_record_id": source_record_id,
            "target_system_redeemed": max(0, current - quantity),
        })
    requester_open_id = str(request.get("requester_open_id") or "")
    permission_row = next(
        (
            row for row in fresh_feishu_rows(USER_PERMISSION_TABLE_NAME)
            if requester_open_id in feishu_person_open_ids(feishu_fields(row), ["用户账号", "用户", "成员"])
        ),
        None,
    )
    permission_record_id = feishu_record_id(permission_row or {})
    if not permission_record_id:
        raise RuntimeError("未找到申请人的用户权限记录，无法恢复领取额度。")
    quota_targets: list[dict[str, object]] = []
    for product, quantity in requested_by_product.items():
        field_name, _ = _corporate_apparel_quota_field(product)
        current = feishu_int(feishu_fields(permission_row or {}), field_name)
        quota_targets.append({"field": field_name, "target": max(0, current - quantity)})
    return {
        "already_rejected": False,
        "context": context,
        "permission_record_id": permission_record_id,
        "stock_targets": stock_targets,
        "quota_targets": quota_targets,
    }


def execute_corporate_apparel_rejection(plan: dict[str, object]) -> dict[str, object]:
    context = dict(plan.get("context") or {})
    request = dict(context.get("request") or {})
    request_no = str(request.get("request_no") or "")
    if plan.get("already_rejected"):
        return {"request_no": request_no, "already_rejected": True, "rejected": True}
    request_record_id = str(request.get("record_id") or "")
    feishu_update_record_fields(
        REQUEST_TABLE_NAME, request_record_id,
        {"文化周边处理状态": CULTURAL_REQUEST_STATUS_REJECTING},
    )
    for item in list(plan.get("stock_targets") or []):
        line = dict(item)
        update_corporate_apparel_source_redeemed(
            line, int(line.get("target_system_redeemed") or 0)
        )
        feishu_update_record_fields(
            REQUEST_LINE_TABLE_NAME,
            str(line.get("line_record_id") or ""),
            {"审批通过数量": 0, "实际发放数量": 0, "明细状态": CULTURAL_REQUEST_STATUS_REJECTED},
        )
    quota_fields = {
        str(item["field"]): int(item["target"])
        for item in list(plan.get("quota_targets") or [])
    }
    feishu_update_record_fields(
        USER_PERMISSION_TABLE_NAME,
        str(plan.get("permission_record_id") or ""),
        quota_fields,
    )
    feishu_update_record_fields(
        REQUEST_TABLE_NAME, request_record_id,
        {"文化周边处理状态": CULTURAL_REQUEST_STATUS_REJECTED, "文化周边通知状态": "驳回待通知"},
    )
    return {"request_no": request_no, "rejected": True, "restored_quantity": sum(int(item.get("quantity") or 0) for item in list(plan.get("stock_targets") or []))}


def corporate_apparel_rejection_targets(request_no: str) -> list[dict[str, object]]:
    context = corporate_apparel_request_context(request_no)
    request = dict(context["request"])
    lines = [dict(item) for item in list(context["lines"])]
    message_ids = dict(request.get("message_ids") or {})
    requester = str(request.get("requester") or "申请人")
    targets: list[dict[str, object]] = []
    requester_open_id = str(request.get("requester_open_id") or "")
    if requester_open_id:
        key = f"applicant:{requester_open_id}"
        card = _corporate_apparel_card(request_no, requester, lines, applicant=True)
        card["header"]["template"] = "red"
        card["header"]["title"]["content"] = "企业文化衫领取已驳回"
        card["body"]["elements"][0]["content"] = "您的企业文化衫领取申请已被 HR 驳回，领取额度已恢复。"
        targets.append({"key": key, "recipient_id": requester_open_id, "message_id": message_ids.get(key, ""), "card": card})
    for open_id in enabled_role_open_ids("HR"):
        key = f"hr:{open_id}"
        card = _corporate_apparel_card(request_no, requester, lines, applicant=True)
        card["header"]["template"] = "red"
        card["header"]["title"]["content"] = "企业文化衫领取已驳回"
        card["body"]["elements"][0]["content"] = f"{requester} 的企业文化衫领取申请已驳回。"
        targets.append({"key": key, "recipient_id": open_id, "message_id": message_ids.get(key, ""), "card": card})
    return targets


def cultural_size_sort_key(value: object) -> tuple[int, str]:
    size = str(value or "").strip()
    try:
        return CULTURAL_SIZE_ORDER.index(size), ""
    except ValueError:
        return len(CULTURAL_SIZE_ORDER), size.casefold()


def validate_cultural_request_quantity(lines: list[dict[str, object]]) -> int:
    jacket_quantity = sum(
        max(0, int(line.get("quantity") or 0))
        for line in lines
        if isinstance(line, dict)
        and str(line.get("product") or "").strip() == CULTURAL_JACKET_CATEGORY
    )
    cultural_shirt_quantity = sum(
        max(0, int(line.get("quantity") or 0))
        for line in lines
        if isinstance(line, dict)
        and str(line.get("product") or "").strip() != CULTURAL_JACKET_CATEGORY
    )
    if jacket_quantity > CULTURAL_JACKET_MAX_TOTAL_QUANTITY:
        raise RuntimeError("每位申请人累计最多申领 1 件文化夹克。")
    if cultural_shirt_quantity > CULTURAL_REQUEST_MAX_TOTAL_QUANTITY:
        raise RuntimeError(
            f"每位申请人累计最多申领 {CULTURAL_REQUEST_MAX_TOTAL_QUANTITY} 件文化衫。"
        )
    return cultural_shirt_quantity + jacket_quantity


def ensure_cultural_request_quota_fields() -> None:
    """Ensure independent cumulative counters exist for shirts and jackets."""
    refresh_feishu_schema_cache()
    required = (
        CULTURAL_REQUEST_CUMULATIVE_FIELD,
        CULTURAL_JACKET_CUMULATIVE_FIELD,
    )
    missing = [
        field_name
        for field_name in required
        if not feishu_has_field(USER_PERMISSION_TABLE_NAME, field_name)
    ]
    if not missing:
        return
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建文化周边申领额度字段。")
    table_id = feishu_table_id(USER_PERMISSION_TABLE_NAME)
    for field_name in missing:
        client.create_field(table_id, field_name, 2)
    refresh_feishu_schema_cache()
    still_missing = [
        field_name
        for field_name in required
        if not feishu_has_field(USER_PERMISSION_TABLE_NAME, field_name)
    ]
    if still_missing:
        raise RuntimeError(f"用户权限表申领额度字段创建失败：{'、'.join(still_missing)}")


def ensure_cultural_request_workflow_fields() -> None:
    """Ensure request-card tracking needed by the manual reject workflow."""
    refresh_feishu_schema_cache()
    if feishu_has_field(REQUEST_TABLE_NAME, CULTURAL_REQUEST_MESSAGE_IDS_FIELD):
        return
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建文化周边卡片追踪字段。")
    client.create_field(
        feishu_table_id(REQUEST_TABLE_NAME),
        CULTURAL_REQUEST_MESSAGE_IDS_FIELD,
        1,
    )
    refresh_feishu_schema_cache()
    if not feishu_has_field(REQUEST_TABLE_NAME, CULTURAL_REQUEST_MESSAGE_IDS_FIELD):
        raise RuntimeError("文化周边卡片追踪字段创建失败。")


def cultural_request_quota_snapshot(
    request_payload: dict[str, object], lines: list[dict[str, object]]
) -> dict[str, object]:
    validate_cultural_request_quantity(lines)
    requested_jacket_quantity = sum(
        max(0, int(line.get("quantity") or 0))
        for line in lines
        if isinstance(line, dict)
        and str(line.get("product") or "").strip() == CULTURAL_JACKET_CATEGORY
    )
    requested_quantity = sum(
        max(0, int(line.get("quantity") or 0))
        for line in lines
        if isinstance(line, dict)
        and str(line.get("product") or "").strip() != CULTURAL_JACKET_CATEGORY
    )
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    if not requester_open_id.startswith("ou_"):
        raise RuntimeError("申请人未关联有效的飞书账号，无法核对文化周边申领额度。")
    ensure_requester_sales_permission(request_payload)
    ensure_cultural_request_quota_fields()
    permission_row = next(
        (
            row
            for row in fresh_feishu_rows(USER_PERMISSION_TABLE_NAME)
            if requester_open_id
            in feishu_person_open_ids(feishu_fields(row), ["用户账号", "用户", "成员"])
        ),
        None,
    )
    if permission_row is None or not feishu_record_id(permission_row):
        raise RuntimeError("未找到申请人的用户权限记录，无法核对文化周边申领额度。")
    current_quantity = feishu_int(
        feishu_fields(permission_row), CULTURAL_REQUEST_CUMULATIVE_FIELD
    )
    current_jacket_quantity = feishu_int(
        feishu_fields(permission_row), CULTURAL_JACKET_CUMULATIVE_FIELD
    )
    target_quantity = current_quantity + requested_quantity
    target_jacket_quantity = current_jacket_quantity + requested_jacket_quantity
    shirt_allowed = target_quantity <= CULTURAL_REQUEST_MAX_TOTAL_QUANTITY
    jacket_allowed = target_jacket_quantity <= CULTURAL_JACKET_MAX_TOTAL_QUANTITY
    return {
        "permission_record_id": feishu_record_id(permission_row),
        "current_quantity": current_quantity,
        "requested_quantity": requested_quantity,
        "target_quantity": target_quantity,
        "current_jacket_quantity": current_jacket_quantity,
        "requested_jacket_quantity": requested_jacket_quantity,
        "target_jacket_quantity": target_jacket_quantity,
        "allowed": shirt_allowed and jacket_allowed,
        "quota_label": "文化夹克" if not jacket_allowed else "文化衫",
        "quota_limit": (
            CULTURAL_JACKET_MAX_TOTAL_QUANTITY
            if not jacket_allowed
            else CULTURAL_REQUEST_MAX_TOTAL_QUANTITY
        ),
    }


def update_cultural_request_cumulative_quantity(
    permission_record_id: str,
    target_quantity: int,
    target_jacket_quantity: int | None = None,
) -> None:
    if not str(permission_record_id or "").strip():
        raise RuntimeError("用户权限记录缺少记录 ID，无法更新文化周边累计数量。")
    fields = {CULTURAL_REQUEST_CUMULATIVE_FIELD: int(target_quantity)}
    if target_jacket_quantity is not None:
        fields[CULTURAL_JACKET_CUMULATIVE_FIELD] = int(target_jacket_quantity)
    feishu_update_record_fields(
        USER_PERMISSION_TABLE_NAME,
        str(permission_record_id),
        fields,
    )


def initialize_cultural_request_state() -> None:
    defaults: dict[str, object] = {
        "cultural_request_lines": [],
        "cultural_request_material_usage": "",
        "cultural_request_stage": "edit",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "cultural_request_submission_token" not in st.session_state:
        st.session_state["cultural_request_submission_token"] = uuid.uuid4().hex


def clear_cultural_request_state() -> None:
    for key in list(st.session_state):
        if str(key).startswith("cultural_request_"):
            st.session_state.pop(key, None)


def queued_cultural_request_payload(
    request_payload: dict[str, object], lines: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "version": 1,
        "request_payload": {
            key: request_payload.get(key)
            for key in (
                "requester", "requester_open_id", "department", "department_id",
                "material_usage", "submission_token", "administrator_override",
            )
        },
        "lines": [
            {
                "product": str(line.get("product") or ""),
                "model": str(line.get("model") or ""),
                "region": str(line.get("region") or ""),
                "quantity": int(line.get("quantity") or 0),
                "remark": str(line.get("remark") or ""),
            }
            for line in lines
            if isinstance(line, dict) and int(line.get("quantity") or 0) > 0
        ],
    }


def enqueue_feishu_cultural_request(
    request_payload: dict[str, object], lines: list[dict[str, object]]
) -> tuple[SubmissionTask, bool]:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法创建文化周边后台任务。")
    token = str(request_payload.get("submission_token") or "").strip()
    if not token:
        raise RuntimeError("文化周边申请提交幂等键不能为空。")
    validate_cultural_request_quantity(lines)
    table_id = ensure_submission_queue_table(client)
    existing = find_task_by_idempotency_key(client, token, table_id)
    if existing is not None and existing.status != QUEUE_STATUS_FAILED:
        return existing, False
    payload = queued_cultural_request_payload(request_payload, lines)
    return enqueue_submission_task(client, QUEUE_TASK_TYPE_CULTURAL_REQUEST, token, payload)


def _cultural_request_card(
    request_no: str,
    requester: str,
    lines: list[dict[str, object]],
    *,
    applicant: bool,
    admin_open_ids: list[str] | None = None,
    material_usage: str = "",
) -> dict[str, object]:
    title = "文化周边需求已提交" if applicant else "文化周边申领通知"
    admin_mentions = " ".join(
        f"<at id={open_id}></at>" for open_id in list(admin_open_ids or []) if open_id
    )
    lead = (
        f"您的（文化周边）需求已提交，请找{admin_mentions or '已启用的管理员'}进行申领。"
        if applicant else f"{requester} 提交了文化周边申领，请安排发放。"
    )
    elements: list[dict[str, object]] = [
        {"tag": "markdown", "content": lead},
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": (
                f"**申请单号**：{request_no}\n\n"
                f"**文化衫用途**：{material_usage or '-'}\n\n"
                "**申请明细**"
            ),
        },
        _feishu_requester_material_table(lines),
    ]
    if not applicant:
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "驳回申领"},
                "type": "danger_filled",
                "width": "fill",
                "value": {
                    "action": "reject_cultural_request",
                    "request_no": request_no,
                },
                "confirm": {
                    "title": {"tag": "plain_text", "content": "确认驳回文化周边申领"},
                    "text": {
                        "tag": "plain_text",
                        "content": "驳回后将恢复库存和申请额度，并通知申请人。",
                    },
                },
            }
        )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default", "summary": {"content": title}},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "elements": elements,
        },
    }


def cultural_request_notification_targets(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> list[dict[str, object]]:
    admins = enabled_admin_open_ids()
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    requester = str(request_payload.get("requester") or "申请人")
    targets: list[dict[str, object]] = []
    if requester_open_id:
        targets.append({
            "key": f"applicant:{requester_open_id}",
            "audience": "applicant",
            "recipient_id": requester_open_id,
            "card": _cultural_request_card(
                request_no,
                requester,
                lines,
                applicant=True,
                admin_open_ids=admins,
                material_usage=str(request_payload.get("material_usage") or "").strip(),
            ),
        })
    catalog = cultural_request_catalog(
        fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME),
        include_all_categories_for_admin=bool(
            request_payload.get("administrator_override")
        ),
    )
    combinations = dict(catalog.get("combinations") or {})
    admin_lines: list[dict[str, object]] = []
    for line in lines:
        normalized = dict(line)
        item = combinations.get((
            str(line.get("product") or "").strip(),
            str(line.get("model") or "").strip(),
            str(line.get("region") or "").strip(),
        ))
        if item:
            normalized["remaining_stock"] = int(item.get("stock") or 0)
        admin_lines.append(normalized)
    for open_id in admins:
        targets.append({
            "key": f"admin:{open_id}",
            "audience": "admins",
            "recipient_id": open_id,
            "card": _cultural_request_card(
                request_no,
                requester,
                admin_lines,
                applicant=False,
                material_usage=str(request_payload.get("material_usage") or "").strip(),
            ),
        })
    return targets


def notify_cultural_request(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> dict[str, int]:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送文化周边通知。")
    counts = {"applicant": 0, "admins": 0}
    for target in cultural_request_notification_targets(request_no, request_payload, lines):
        send_feishu_interactive_message(
            client,
            str(target["recipient_id"]),
            dict(target["card"]),
        )
        counts[str(target["audience"])] += 1
    return counts


def _cultural_request_rejection_card(
    requester: str,
    current_quantity: int,
    requested_quantity: int,
    *,
    applicant: bool,
    admin_open_ids: list[str] | None = None,
    quota_label: str = "文化衫",
    quota_limit: int = CULTURAL_REQUEST_MAX_TOTAL_QUANTITY,
) -> dict[str, object]:
    admins = [str(value) for value in list(admin_open_ids or []) if str(value).strip()]
    admin_mentions = " ".join(f"<at id={open_id}></at>" for open_id in admins)
    reason = (
        f"本次申请 {requested_quantity} 件，历史累计已申领 {current_quantity} 件，"
        f"提交后将超过每人累计最多 {quota_limit} 件{quota_label}的限制。"
    )
    if applicant:
        lead = (
            "您的文化周边申领已驳回，申请单、申请明细、库存流水和库存均未写入。"
            f"如有疑问，请联系{admin_mentions or '已启用的管理员'}。"
        )
        title = "文化周边申领已驳回"
    else:
        lead = f"{requester} 的文化周边申领因累计数量超限已自动驳回，未写入业务数据。"
        title = "文化周边申领超限通知"
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default", "summary": {"content": title}},
        "header": {"template": "red", "title": {"tag": "plain_text", "content": title}},
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "elements": [
                {"tag": "markdown", "content": lead},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**驳回原因**\n{reason}"},
            ],
        },
    }


def notify_cultural_request_rejected(
    request_payload: dict[str, object],
    current_quantity: int,
    requested_quantity: int,
    *,
    quota_label: str = "文化衫",
    quota_limit: int = CULTURAL_REQUEST_MAX_TOTAL_QUANTITY,
) -> dict[str, int]:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送文化周边驳回通知。")
    admins = enabled_admin_open_ids()
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    requester = str(request_payload.get("requester") or "申请人")
    if requester_open_id:
        send_feishu_interactive_message(
            client,
            requester_open_id,
            _cultural_request_rejection_card(
                requester,
                current_quantity,
                requested_quantity,
                applicant=True,
                admin_open_ids=admins,
                quota_label=quota_label,
                quota_limit=quota_limit,
            ),
        )
    for open_id in admins:
        send_feishu_interactive_message(
            client,
            open_id,
            _cultural_request_rejection_card(
                requester,
                current_quantity,
                requested_quantity,
                applicant=False,
                quota_label=quota_label,
                quota_limit=quota_limit,
            ),
        )
    return {"applicant": 1 if requester_open_id else 0, "admins": len(admins)}


def _cultural_request_message_ids(fields: dict[str, object]) -> dict[str, str]:
    raw = feishu_text(fields, CULTURAL_REQUEST_MESSAGE_IDS_FIELD).strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if str(key).strip() and str(value).strip()
    }


def cultural_request_context(request_no: str) -> dict[str, object]:
    normalized_no = str(request_no or "").strip()
    request_rows = fresh_feishu_rows(REQUEST_TABLE_NAME)
    request_row = next(
        (
            row
            for row in request_rows
            if feishu_text(feishu_fields(row), "申请单号").strip() == normalized_no
        ),
        None,
    )
    if request_row is None:
        raise RuntimeError("未找到文化周边申请单，请刷新卡片后重试。")
    request_fields = feishu_fields(request_row)
    if (
        feishu_text(request_fields, "业务类型").strip() != "文化周边申领"
        and feishu_text(request_fields, "申请类型").strip() != "文化周边申请"
    ):
        raise RuntimeError("该申请单不是文化周边申领，不能执行驳回。")
    request_id = feishu_record_id(request_row)
    requester_open_ids = feishu_person_open_ids(
        request_fields, ["申请人", "申请人姓名"]
    )
    line_rows: list[dict[str, object]] = []
    for row in fresh_feishu_rows(REQUEST_LINE_TABLE_NAME):
        fields = feishu_fields(row)
        linked_requests = feishu_link_ids_any(fields, ["所属申请单", "申请单"])
        if (
            request_id not in linked_requests
            and feishu_text(fields, "申请单号").strip() != normalized_no
        ):
            continue
        if feishu_text(fields, "明细业务类型").strip() != "文化周边":
            continue
        line_rows.append(
            {
                "record_id": feishu_record_id(row),
                "product": feishu_text(fields, "品类名称"),
                "model": feishu_text(fields, "产品型号名称"),
                "region": feishu_text(fields, "文化周边战区"),
                "quantity": feishu_int(fields, "申请数量"),
                "culture_record_ids": feishu_link_ids_any(
                    fields, ["文化周边物料"]
                ),
            }
        )
    if not line_rows:
        raise RuntimeError("文化周边申请单没有可驳回的申请明细。")
    return {
        "request": {
            "record_id": request_id,
            "request_no": normalized_no,
            "requester": request_applicant_text(request_fields) or "申请人",
            "requester_open_id": requester_open_ids[0] if requester_open_ids else "",
            "status": feishu_text(request_fields, "文化周边处理状态"),
            "message_ids": _cultural_request_message_ids(request_fields),
        },
        "lines": line_rows,
    }


def recalculate_cultural_request_quota(requester_open_id: str) -> dict[str, int]:
    """Rebuild quota counters from non-rejected cultural requests."""
    normalized_open_id = str(requester_open_id or "").strip()
    if not normalized_open_id.startswith("ou_"):
        raise RuntimeError("申请人未关联有效的飞书账号，无法恢复文化周边额度。")
    ensure_cultural_request_quota_fields()
    active_request_ids: set[str] = set()
    active_request_nos: set[str] = set()
    for row in fresh_feishu_rows(REQUEST_TABLE_NAME):
        fields = feishu_fields(row)
        business_type = feishu_text(fields, "业务类型").strip()
        request_type = feishu_text(fields, "申请类型").strip()
        if not (
            business_type in {"文化周边申领", CORPORATE_APPAREL_REQUEST_TYPE}
            or request_type in {"文化周边申请", CORPORATE_APPAREL_REQUEST_TYPE}
        ):
            continue
        if feishu_text(fields, "文化周边处理状态").strip() != CULTURAL_REQUEST_STATUS_ISSUED:
            continue
        if normalized_open_id not in feishu_person_open_ids(
            fields, ["申请人", "申请人姓名"]
        ):
            continue
        record_id = feishu_record_id(row)
        request_no = feishu_text(fields, "申请单号").strip()
        if record_id:
            active_request_ids.add(record_id)
        if request_no:
            active_request_nos.add(request_no)
    shirt_quantity = 0
    jacket_quantity = 0
    for row in fresh_feishu_rows(REQUEST_LINE_TABLE_NAME):
        fields = feishu_fields(row)
        line_type = feishu_text(fields, "明细业务类型").strip()
        if line_type not in {"文化周边", CORPORATE_APPAREL_LINE_TYPE}:
            continue
        request_ids = set(feishu_link_ids_any(fields, ["所属申请单", "申请单"]))
        request_no = feishu_text(fields, "申请单号").strip()
        if not (request_ids & active_request_ids or request_no in active_request_nos):
            continue
        quantity = max(0, feishu_int(fields, "申请数量"))
        product = feishu_text(fields, "品类名称").strip()
        if line_type == CORPORATE_APPAREL_LINE_TYPE and product not in {
            "休闲商务POLO-黑色（短袖）",
            "休闲商务夹克-黑色（长袖）",
        }:
            continue
        if product in {CULTURAL_JACKET_CATEGORY, "休闲商务夹克-黑色（长袖）"}:
            jacket_quantity += quantity
        else:
            shirt_quantity += quantity
    permission_row = next(
        (
            row
            for row in fresh_feishu_rows(USER_PERMISSION_TABLE_NAME)
            if normalized_open_id
            in feishu_person_open_ids(feishu_fields(row), ["用户账号", "用户", "成员"])
        ),
        None,
    )
    permission_record_id = feishu_record_id(permission_row or {})
    if not permission_record_id:
        raise RuntimeError("未找到申请人的用户权限记录，无法恢复文化周边额度。")
    update_cultural_request_cumulative_quantity(
        permission_record_id,
        shirt_quantity,
        jacket_quantity,
    )
    return {"shirt_quantity": shirt_quantity, "jacket_quantity": jacket_quantity}


def execute_cultural_request_rejection(draft: dict[str, object]) -> dict[str, object]:
    request_no = str(draft.get("request_no") or "").strip()
    operator_open_id = str(draft.get("operator_open_id") or "").strip()
    if operator_open_id not in enabled_admin_open_ids():
        raise PermissionError("只有已启用管理员可以驳回文化周边申领。")
    ensure_cultural_request_workflow_fields()
    context = cultural_request_context(request_no)
    request = dict(context["request"])
    status = str(request.get("status") or "").strip()
    if status == CULTURAL_REQUEST_STATUS_REJECTED:
        return {
            "request_no": request_no,
            "requester": request.get("requester"),
            "already_rejected": True,
            "rejected": True,
        }
    if status not in {
        CULTURAL_REQUEST_STATUS_ISSUED,
        CULTURAL_REQUEST_STATUS_REJECTING,
    }:
        raise RuntimeError("只有已发放的文化周边申请可以驳回。")
    request_id = str(request.get("record_id") or "")
    if status == CULTURAL_REQUEST_STATUS_ISSUED:
        feishu_update_record_fields(
            REQUEST_TABLE_NAME,
            request_id,
            {"文化周边处理状态": CULTURAL_REQUEST_STATUS_REJECTING},
        )

    culture_rows = fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME)
    culture_by_id = {feishu_record_id(row): row for row in culture_rows}
    ledger_rows = fresh_feishu_rows(LEDGER_TABLE_NAME)
    ledger_by_key = {
        feishu_text(feishu_fields(row), "幂等键"): row for row in ledger_rows
    }
    restored_quantity = 0
    for line in list(context.get("lines") or []):
        line_record_id = str(line.get("record_id") or "")
        culture_ids = [
            str(value) for value in list(line.get("culture_record_ids") or []) if str(value)
        ]
        if not line_record_id or not culture_ids:
            raise RuntimeError("文化周边申请明细缺少库存关联，无法驳回。")
        culture_id = culture_ids[0]
        culture_row = culture_by_id.get(culture_id)
        if culture_row is None:
            raise RuntimeError("文化周边库存记录不存在，无法驳回。")
        quantity = max(0, int(line.get("quantity") or 0))
        ledger_key = f"cultural-reject:{request_no}:{line_record_id}"
        existing_ledger = ledger_by_key.get(ledger_key)
        if existing_ledger is not None:
            before_reversal_stock = feishu_int(
                feishu_fields(existing_ledger),
                "变更前数量",
                feishu_int(feishu_fields(culture_row), "当前库存"),
            )
            after_stock = feishu_int(
                feishu_fields(existing_ledger),
                "变更后数量",
                feishu_int(feishu_fields(culture_row), "当前库存") + quantity,
            )
        else:
            current_stock = feishu_int(feishu_fields(culture_row), "当前库存")
            before_reversal_stock = current_stock
            after_stock = current_stock + quantity
            created_ledger = feishu_create_record(
                LEDGER_TABLE_NAME,
                {
                    "操作": ACTION_PURCHASE,
                    "数量": quantity,
                    "库存变化": quantity,
                    "变更前数量": current_stock,
                    "变更后数量": after_stock,
                    "幂等键": ledger_key,
                    "流水业务类型": "文化周边申领驳回",
                    "文化周边战区快照": str(line.get("region") or ""),
                    "文化周边物料": [culture_id],
                    "关联明细": [line_record_id],
                    "备注": (
                        f"文化周边申领驳回 {request_no}：{line.get('product')} / "
                        f"{line.get('model')} / {line.get('region')}"
                    ),
                    "时间": feishu_datetime_value(LEDGER_TABLE_NAME, "时间", datetime.now()),
                },
            )
            ledger_by_key[ledger_key] = created_ledger
        restored_stock_fields = cultural_stock_fields(after_stock)
        if before_reversal_stock <= 0 < after_stock:
            restored_stock_fields[CULTURAL_CLAIMABLE_FIELD] = CULTURAL_CLAIMABLE_YES
        feishu_update_record_fields(
            CULTURAL_MATERIAL_TABLE_NAME,
            culture_id,
            restored_stock_fields,
        )
        feishu_update_record_fields(
            REQUEST_LINE_TABLE_NAME,
            line_record_id,
            {
                "审批通过数量": 0,
                "实际发放数量": 0,
                "明细状态": CULTURAL_REQUEST_STATUS_REJECTED,
            },
        )
        restored_quantity += quantity

    quota = recalculate_cultural_request_quota(str(request.get("requester_open_id") or ""))
    feishu_update_record_fields(
        REQUEST_TABLE_NAME,
        request_id,
        {
            "文化周边处理状态": CULTURAL_REQUEST_STATUS_REJECTED,
            "文化周边通知状态": "驳回待通知",
        },
    )
    return {
        "request_no": request_no,
        "requester": request.get("requester"),
        "restored_quantity": restored_quantity,
        "quota": quota,
        "rejected": True,
    }


def _cultural_manual_rejection_card(
    request_no: str,
    requester: str,
    lines: list[dict[str, object]],
    *,
    applicant: bool,
) -> dict[str, object]:
    title = "文化周边申领已驳回"
    lead = (
        "您的文化周边申领已被管理员驳回，相关库存和申领额度已经恢复。"
        if applicant
        else f"{requester or '申请人'} 的文化周边申领已驳回，相关库存和申领额度已经恢复。"
    )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default", "summary": {"content": title}},
        "header": {
            "template": "red",
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": request_no or "-"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "elements": [
                {"tag": "markdown", "content": lead},
                {"tag": "hr"},
                {"tag": "markdown", "content": "**已驳回明细**"},
                _feishu_requester_material_table(lines),
            ],
        },
    }


def cultural_request_rejection_targets(request_no: str) -> list[dict[str, object]]:
    context = cultural_request_context(request_no)
    request = dict(context["request"])
    lines = [dict(line) for line in list(context.get("lines") or [])]
    message_ids = dict(request.get("message_ids") or {})
    targets: list[dict[str, object]] = []
    requester_open_id = str(request.get("requester_open_id") or "")
    requester = str(request.get("requester") or "申请人")
    if requester_open_id:
        key = f"applicant:{requester_open_id}"
        targets.append({
            "key": key,
            "audience": "applicant",
            "recipient_id": requester_open_id,
            "message_id": str(message_ids.get(key) or ""),
            "card": _cultural_manual_rejection_card(
                request_no, requester, lines, applicant=True
            ),
        })
    for open_id in enabled_admin_open_ids():
        key = f"admin:{open_id}"
        targets.append({
            "key": key,
            "audience": "admins",
            "recipient_id": open_id,
            "message_id": str(message_ids.get(key) or ""),
            "card": _cultural_manual_rejection_card(
                request_no, requester, lines, applicant=False
            ),
        })
    return targets


def _cultural_dimension_record_id(table_name: str, field_name: str, value: str) -> str:
    for row in fresh_feishu_rows(table_name):
        if feishu_text(feishu_fields(row), field_name).strip() == value.strip():
            return feishu_record_id(row)
    return ""


def cultural_management_notification_card(
    action: str,
    product: str,
    model: str,
    region: str,
) -> dict[str, object]:
    return _feishu_notification_card_v2(
        "文化周边数据变更通知",
        "blue",
        [
            {"tag": "markdown", "content": "**变更明细**"},
            _feishu_notification_table(
                [
                    {"name": "operation", "display_name": "操作", "data_type": "text", "width": "90px"},
                    {"name": "product", "display_name": "品类", "data_type": "text"},
                    {"name": "model", "display_name": "型号", "data_type": "text", "width": "140px"},
                    {"name": "region", "display_name": "战区", "data_type": "text", "width": "150px"},
                ],
                [{
                    "operation": action,
                    "product": product or "-",
                    "model": model or "-",
                    "region": region or "-",
                }],
                freeze_first_column=False,
            ),
        ],
    )


def execute_cultural_material_management(draft: dict[str, object]) -> dict[str, object]:
    """Create, edit, or delete one culture inventory combination from the Worker."""
    refresh_feishu_schema_cache()
    action = str(draft.get("action") or "create").strip()
    record_id = str(draft.get("record_id") or "").strip()
    product = str(draft.get("product") or "").strip()
    model = str(draft.get("model") or "").strip()
    region = str(draft.get("region") or "").strip()
    if action == "delete":
        if not record_id:
            raise RuntimeError("删除文化周边时缺少记录 ID。")
        client = feishu_client()
        if client is None:
            raise RuntimeError("飞书未配置，无法删除文化周边。")
        client.delete_record(feishu_table_id(CULTURAL_MATERIAL_TABLE_NAME), record_id)
        result = {"action": action, "record_id": record_id, "deleted": True}
    else:
        if not product or not model or not region:
            raise RuntimeError("文化周边的品类、型号和战区均不能为空。")
        category_id = _cultural_dimension_record_id(CATEGORY_TABLE_NAME, "物料品类", product)
        model_id = _cultural_dimension_record_id(MODEL_TABLE_NAME, "产品型号", model)
        if not category_id or not model_id:
            raise RuntimeError("文化周边关联的品类或型号不存在。")
        fields: dict[str, object] = {
            "物料品类": product,
            "产品型号": model,
            "战区管理": region,
            **cultural_stock_fields(draft.get("stock"), initialize=action == "create"),
            "单价（人民币）": float(draft.get("unit_price_rmb") or 0),
            "备注": str(draft.get("remark") or ""),
            "物料品类关联": [category_id],
            "产品型号关联": [model_id],
        }
        if action == "create":
            duplicate = next(
                (
                    row for row in fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME)
                    if (
                        feishu_text(feishu_fields(row), "物料品类").strip(),
                        feishu_text(feishu_fields(row), "产品型号").strip(),
                        feishu_text(feishu_fields(row), "战区管理").strip(),
                    ) == (product, model, region)
                ),
                None,
            )
            if duplicate:
                raise RuntimeError("该品类、型号和战区组合已经存在。")
            fields["文化周边编码"] = f"CUL-{uuid.uuid4().hex[:8].upper()}"
            created = feishu_create_record(CULTURAL_MATERIAL_TABLE_NAME, fields)
            record_id = feishu_record_id(created)
            result = {"action": action, "record_id": record_id, "created": True}
        elif action == "edit":
            if not record_id:
                raise RuntimeError("编辑文化周边时缺少记录 ID。")
            feishu_update_record_fields(CULTURAL_MATERIAL_TABLE_NAME, record_id, fields)
            result = {"action": action, "record_id": record_id, "updated": True}
        else:
            raise RuntimeError(f"不支持的文化周边管理操作：{action}")
    client = feishu_client()
    if client is not None:
        card = cultural_management_notification_card(action, product, model, region)
        for open_id in enabled_admin_open_ids():
            send_feishu_interactive_message(client, open_id, card)
    return result


def render_cultural_material_management() -> None:
    rows = feishu_rows(CULTURAL_MATERIAL_TABLE_NAME)
    catalog = cultural_request_catalog(rows)
    st.caption("新增、编辑和删除均通过后台任务队列执行；允许负库存。")
    operation = st.segmented_control(
        "操作",
        ["新增", "编辑", "删除"],
        default="新增",
        key="cultural_management_operation",
    ) or "新增"
    selected_row: dict | None = None
    if operation != "新增":
        options = [feishu_record_id(row) for row in rows]
        row_by_id = {feishu_record_id(row): row for row in rows}
        selected_id = st.selectbox(
            "选择文化周边记录",
            options,
            format_func=lambda value: " / ".join(
                [
                    feishu_text(feishu_fields(row_by_id[value]), "物料品类"),
                    feishu_text(feishu_fields(row_by_id[value]), "产品型号"),
                    feishu_text(feishu_fields(row_by_id[value]), "战区管理"),
                ]
            ),
            key="cultural_management_record",
        )
        selected_row = row_by_id.get(selected_id)
    selected_fields = feishu_fields(selected_row or {})
    if operation == "删除":
        st.warning("确认后将删除所选文化周边库存组合；已生成的申请明细和库存流水不会删除。")
        if st.button("确认删除", type="primary", key="cultural_management_delete", width="stretch"):
            enqueue_feishu_background_write(
                QUEUE_TASK_TYPE_CULTURAL_MANAGEMENT,
                {"draft": {"action": "delete", "record_id": feishu_record_id(selected_row or {})}},
            )
            st.success("删除任务已进入后台队列。")
        return
    category_rows = [
        row for row in feishu_rows(CATEGORY_TABLE_NAME)
        if feishu_text(feishu_fields(row), "品类定义") == CATEGORY_DEFINITION_CULTURAL
    ]
    products = [feishu_text(feishu_fields(row), "物料品类") for row in category_rows]
    models = [feishu_text(feishu_fields(row), "产品型号") for row in feishu_rows(MODEL_TABLE_NAME)]
    regions = [feishu_text(feishu_fields(row), "战区名称") for row in feishu_rows(REGION_TABLE_NAME)]
    cols = st.columns(3)
    product = cols[0].selectbox("文化周边品类", products, index=products.index(feishu_text(selected_fields, "物料品类")) if feishu_text(selected_fields, "物料品类") in products else 0)
    model = cols[1].selectbox("产品型号 / 尺码", models, index=models.index(feishu_text(selected_fields, "产品型号")) if feishu_text(selected_fields, "产品型号") in models else 0)
    region = cols[2].selectbox("战区", regions, index=regions.index(feishu_text(selected_fields, "战区管理")) if feishu_text(selected_fields, "战区管理") in regions else 0)
    value_cols = st.columns(2)
    stock = value_cols[0].number_input("库存数量", value=feishu_int(selected_fields, "当前库存"), step=1)
    price = value_cols[1].number_input("单价（人民币）", value=feishu_float(selected_fields, "单价（人民币）"), min_value=0.0, step=1.0)
    remark = st.text_input("备注", value=feishu_text(selected_fields, "备注"))
    action = "edit" if operation == "编辑" else "create"
    if st.button("确认提交", type="primary", key="cultural_management_submit", width="stretch"):
        draft = {
            "action": action,
            "record_id": feishu_record_id(selected_row or {}),
            "product": product,
            "model": model,
            "region": region,
            "stock": int(stock),
            "unit_price_rmb": float(price),
            "remark": remark,
        }
        enqueue_feishu_background_write(
            QUEUE_TASK_TYPE_CULTURAL_MANAGEMENT,
            {"draft": draft},
            idempotency_key=f"cultural-management:{hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()}",
        )
        st.success("文化周边管理任务已进入后台队列。")


def submit_feishu_cultural_request(
    request_payload: dict[str, object], lines: list[dict[str, object]]
) -> tuple[str, int, bool]:
    """Persist a culture request and idempotently apply its stock movements."""
    refresh_feishu_schema_cache()
    ensure_cultural_request_workflow_fields()
    token = str(request_payload.get("submission_token") or "").strip()
    material_usage = str(request_payload.get("material_usage") or "").strip()
    valid_lines = [dict(line) for line in lines if int(line.get("quantity") or 0) > 0]
    if not valid_lines:
        raise RuntimeError("请至少选择一条文化周边。")
    if len(valid_lines) > MAX_CULTURAL_REQUEST_LINE_COUNT:
        raise RuntimeError(f"一次最多提交 {MAX_CULTURAL_REQUEST_LINE_COUNT} 条文化周边明细。")
    validate_cultural_request_quantity(valid_lines)
    culture_rows = fresh_feishu_rows(CULTURAL_MATERIAL_TABLE_NAME)
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    model_rows = fresh_feishu_rows(MODEL_TABLE_NAME)
    catalog = cultural_request_catalog(
        culture_rows,
        category_rows,
        model_rows,
        # Page validation decides which combinations can be selected.  Once a
        # queue task has been accepted, persist that exact snapshot even if a
        # concurrent request drives stock to zero and the live claimability
        # flag flips to "否" before the Worker reaches it.
        include_all_categories_for_admin=True,
        include_unclaimable_combinations=True,
    )
    combinations = dict(catalog["combinations"])
    prepared: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in valid_lines:
        key = (
            str(line.get("product") or "").strip(),
            str(line.get("model") or "").strip(),
            str(line.get("region") or "").strip(),
        )
        if key in seen:
            raise RuntimeError("同一文化周边组合不能重复提交，请合并数量。")
        seen.add(key)
        culture_item = combinations.get(key)
        if not culture_item:
            raise RuntimeError(f"未找到文化周边库存组合：{' / '.join(key)}")
        quantity = int(line.get("quantity") or 0)
        prepared.append({**culture_item, "quantity": quantity, "remark": str(line.get("remark") or "")})

    detail_text = "\n".join(
        f"{index:02d}. {item['product']} / {item['model']} / {item['region']} × {int(item['quantity'])}"
        for index, item in enumerate(prepared, start=1)
    )
    request_regions = "、".join(unique_preserve([
        str(item.get("region") or "").strip() for item in prepared
        if str(item.get("region") or "").strip()
    ]))

    existing_rows = submission_token_rows(token)
    if existing_rows:
        request_row = existing_rows[0]
        request_record_id = feishu_record_id(request_row)
        request_no = feishu_text(feishu_fields(request_row), "申请单号")
        created_new = False
    else:
        request_no = next_request_no()
        request_fields: dict[str, object] = {
            "申请单号": request_no,
            "标题": f"{request_payload.get('requester') or '申请人'}-文化周边申领",
            "申请部门/区域": request_payload.get("department"),
            "申请部门": request_payload.get("department"),
            "业务类型": "文化周边申领",
            "申请类型": "文化周边申请",
            "物料用途": material_usage,
            "审批状态": "无需审批",
            "文化周边处理状态": CULTURAL_REQUEST_STATUS_ISSUED,
            "文化周边通知状态": "待发送",
            "物料明细文字信息": detail_text,
            "所属战区": request_regions,
            "提交时间": feishu_datetime_value(REQUEST_TABLE_NAME, "提交时间", datetime.now()),
            "提交幂等键": token,
            REQUEST_TOTAL_RMB_FIELD: round(
                sum(float(item["unit_price_rmb"]) * int(item["quantity"]) for item in prepared), 2
            ),
        }
        set_first_person_or_plain_field(
            REQUEST_TABLE_NAME,
            request_fields,
            ["申请人", "申请人姓名"],
            request_payload.get("requester"),
            request_payload.get("requester_open_id"),
        )
        set_first_plain_field(REQUEST_TABLE_NAME, request_fields, ["申请人OpenID"], request_payload.get("requester_open_id"))
        created_request = feishu_create_record(REQUEST_TABLE_NAME, request_fields)
        request_record_id = feishu_record_id(created_request)
        if not request_record_id:
            raise RuntimeError("文化周边申请单创建成功但未返回记录 ID。")
        created_new = True

    all_line_rows = fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
    lines_by_number = {
        feishu_text(feishu_fields(row), "明细编号"): row for row in all_line_rows
    }
    ledger_rows = fresh_feishu_rows(LEDGER_TABLE_NAME)
    ledger_keys = {feishu_text(feishu_fields(row), "幂等键") for row in ledger_rows}
    category_ids = dict(catalog.get("category_ids") or {})
    model_ids = dict(catalog.get("model_ids") or {})
    for index, item in enumerate(prepared, start=1):
        line_no = f"{request_no}-{index:02d}"
        line_row = lines_by_number.get(line_no)
        if line_row is None:
            line_fields: dict[str, object] = {
                "明细编号": line_no,
                "申请单号": request_no,
                "申请数量": int(item["quantity"]),
                "审批通过数量": int(item["quantity"]),
                "实际发放数量": int(item["quantity"]),
                "物料数量": int(item["quantity"]),
                "品类名称": item["product"],
                "产品型号名称": item["model"],
                "明细业务类型": "文化周边",
                "文化周边战区": item["region"],
                "明细状态": "已发放",
                "备注": item["remark"],
                REQUEST_PRICE_SNAPSHOT_FIELD: float(item["unit_price_rmb"]),
                REQUEST_LINE_SUBTOTAL_FIELD: round(float(item["unit_price_rmb"]) * int(item["quantity"]), 2),
                "所属申请单": [request_record_id],
                "品类": [category_ids.get(str(item["product"]), "")],
                "产品型号": [model_ids.get(str(item["model"]), "")],
                "文化周边物料": [item["record_id"]],
            }
            line_row = feishu_create_record(REQUEST_LINE_TABLE_NAME, line_fields)
        line_record_id = feishu_record_id(line_row)
        ledger_key = f"cultural-request:{token}:{index}"
        current_culture_row = next(
            row for row in culture_rows if feishu_record_id(row) == item["record_id"]
        )
        current_stock = feishu_int(feishu_fields(current_culture_row), "当前库存")
        after_stock = current_stock - int(item["quantity"])
        if ledger_key in ledger_keys:
            existing_ledger = next(
                row for row in ledger_rows if feishu_text(feishu_fields(row), "幂等键") == ledger_key
            )
            after_stock = feishu_int(feishu_fields(existing_ledger), "变更后数量", after_stock)
        else:
            ledger_fields: dict[str, object] = {
                "操作": ACTION_RECEIVE,
                "数量": -int(item["quantity"]),
                "库存变化": -int(item["quantity"]),
                "变更前数量": current_stock,
                "变更后数量": after_stock,
                "幂等键": ledger_key,
                "流水业务类型": "文化周边",
                "文化周边战区快照": item["region"],
                "文化周边物料": [item["record_id"]],
                "关联明细": [line_record_id],
                "备注": f"文化周边申领 {request_no}：{item['product']} / {item['model']} / {item['region']}",
                "时间": feishu_datetime_value(LEDGER_TABLE_NAME, "时间", datetime.now()),
            }
            feishu_create_record(LEDGER_TABLE_NAME, ledger_fields)
            ledger_keys.add(ledger_key)
        feishu_update_record_fields(
            CULTURAL_MATERIAL_TABLE_NAME,
            str(item["record_id"]),
            cultural_stock_fields(after_stock),
        )
    feishu_update_record_fields(
        REQUEST_TABLE_NAME,
        request_record_id,
        {
            "物料明细文字信息": detail_text,
            "所属战区": request_regions,
            "物料用途": material_usage,
        },
    )
    return request_no, len(prepared), created_new


def render_cultural_request_page() -> None:
    initialize_cultural_request_state()
    catalog = cultural_request_catalog()
    products = list(catalog.get("products") or [])
    lines = [dict(line) for line in list(st.session_state.get("cultural_request_lines") or [])]
    if st.session_state.get("cultural_request_stage") == "review":
        draft = dict(st.session_state.get("cultural_request_draft") or {})
        review_lines = [dict(line) for line in list(draft.get("lines") or [])]
        with st.container(border=True):
            render_section_header("01", "文化周边申请确认", "提交后将直接登记发放并扣减库存")
            st.markdown(
                f"**{escape(ui_text('申请人'))}：** {escape(str(draft.get('requester') or '-'))}"
            )
            st.markdown(
                f"**文化衫用途（请填写展会名称）：** {escape(str(draft.get('material_usage') or '-'))}"
            )
        with st.container(border=True):
            render_section_header("02", "文化周边清单", f"共 {len(review_lines)} 种")
            edited = st.data_editor(
                pd.DataFrame(review_lines).rename(columns={"product": "物料品类", "model": "尺码", "region": "战区", "quantity": "申请数量", "remark": "备注"}),
                hide_index=True,
                width="stretch",
                disabled=["物料品类", "尺码", "战区", "备注"],
                column_config={"申请数量": st.column_config.NumberColumn(min_value=1, max_value=CULTURAL_REQUEST_MAX_TOTAL_QUANTITY, step=1, format="%d")},
                key="cultural_request_review_editor",
            )
            review_lines = [
                {"product": row["物料品类"], "model": row["尺码"], "region": row["战区"], "quantity": int(row["申请数量"]), "remark": row.get("备注", "")}
                for row in edited.to_dict("records")
            ]
            draft["lines"] = review_lines
            st.session_state["cultural_request_draft"] = draft
        back_col, _, submit_col = st.columns([1, 2, 1.3])
        if back_col.button("返回修改", key="cultural_request_back", width="stretch"):
            st.session_state["cultural_request_stage"] = "edit"
            st.rerun()
        if submit_col.button("确认提交", key="cultural_request_confirm", type="primary", width="stretch"):
            try:
                validate_cultural_request_quantity(review_lines)
            except RuntimeError as exc:
                st.warning(str(exc))
                return
            with fullscreen_data_sync("正在提交数据，请稍后......"):
                enqueue_feishu_cultural_request(draft, review_lines)
            clear_cultural_request_state()
            render_request_submission_success()
            st.stop()
        return

    with st.container(border=True):
        render_section_header("01", "申请人信息", "选择本次文化周边的申请人")
        requester_col, _ = st.columns([1.35, 1])
        department, department_id, requester, requester_open_id = render_request_contact_fields(requester_col)
        material_usage = st.text_input(
            "文化衫用途（请填写展会名称） *",
            key="cultural_request_material_usage",
            placeholder="请填写展会名称",
        )
    with st.container(border=True):
        render_section_header(
            "02",
            "选择文化周边",
            "选择品类、尺码和战区并加入申领车；文化衫每人累计最多 2 件，文化夹克每人累计最多 1 件。",
        )
        if not products:
            st.error("当前没有文化周边库存数据，请先更新文化周边页面缓存。")
            return
        columns = st.columns(6, gap="small")
        combinations = dict(catalog.get("combinations") or {})
        for index, product in enumerate(products):
            scoped = [value for key, value in combinations.items() if key[0] == product]
            models = sorted(
                unique_preserve(str(item["model"]) for item in scoped),
                key=cultural_size_sort_key,
            )
            regions = unique_preserve(str(item["region"]) for item in scoped)
            with columns[index % 6].container(border=True, key=f"cultural_product_card_{index}"):
                image_path = request_category_image_path(product)
                if image_path:
                    st.image(str(image_path), width="stretch")
                st.markdown(f"**{escape(cultural_request_display_category(product, catalog))}**")
                with st.popover("选择规格", key=f"cultural_select_{index}", icon=":material/checkroom:", width="stretch"):
                    selected_model = st.pills("尺码", models, key=f"cultural_model_{index}", selection_mode="single", default=models[0] if models else None, width="stretch")
                    valid_regions = unique_preserve(
                        str(item["region"]) for item in scoped if item["model"] == selected_model
                    )
                    st.markdown(
                        '<div class="pudu-cultural-region-label">'
                        f'<strong>{escape(ui_text("战区"))}</strong> '
                        f'<span style="color:#d92d20;font-weight:600;">{escape(ui_text("如无法确定战区，请选择您所参加活动所在的地区即可。如美国的展会选择美洲战区。"))}</span>'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                    selected_region = st.pills("战区", valid_regions, key=f"cultural_region_{index}", selection_mode="single", default=valid_regions[0] if valid_regions else None, width="stretch", label_visibility="collapsed")
                    line_limit = (
                        CULTURAL_JACKET_MAX_TOTAL_QUANTITY
                        if product == CULTURAL_JACKET_CATEGORY
                        else CULTURAL_REQUEST_MAX_TOTAL_QUANTITY
                    )
                    quantity = st.number_input("数量", min_value=1, max_value=line_limit, step=1, value=1, key=f"cultural_quantity_{index}")
                    remark = st.text_input("备注", key=f"cultural_remark_{index}")
                    if st.button("加入申领车", key=f"cultural_add_{index}", type="primary", width="stretch"):
                        if not selected_model or not selected_region:
                            st.warning("请选择尺码和战区。")
                        else:
                            key = (product, str(selected_model), str(selected_region))
                            existing = next((line for line in lines if (line["product"], line["model"], line["region"]) == key), None)
                            candidate_lines = [dict(line) for line in lines]
                            candidate_existing = next((line for line in candidate_lines if (line["product"], line["model"], line["region"]) == key), None)
                            if candidate_existing:
                                candidate_existing["quantity"] = int(candidate_existing["quantity"]) + int(quantity)
                            else:
                                candidate_lines.append({"product": product, "model": selected_model, "region": selected_region, "quantity": int(quantity), "remark": remark})
                            try:
                                validate_cultural_request_quantity(candidate_lines)
                            except RuntimeError as exc:
                                st.warning(str(exc))
                                return
                            if existing:
                                existing["quantity"] = int(existing["quantity"]) + int(quantity)
                            else:
                                lines.append({"product": product, "model": selected_model, "region": selected_region, "quantity": int(quantity), "remark": remark})
                            st.session_state["cultural_request_lines"] = lines
                            st.toast("已加入文化周边申领车", icon="✅")
                            st.rerun()
        if lines:
            st.markdown("#### 已选文化周边")
            edited = st.data_editor(
                pd.DataFrame(lines).rename(columns={"product": "物料品类", "model": "尺码", "region": "战区", "quantity": "数量", "remark": "备注"}),
                hide_index=True,
                width="stretch",
                num_rows="dynamic",
                disabled=["物料品类", "尺码", "战区"],
                column_config={"数量": st.column_config.NumberColumn(min_value=1, max_value=CULTURAL_REQUEST_MAX_TOTAL_QUANTITY, step=1, format="%d")},
                key="cultural_request_cart_editor",
            )
            lines = [
                {"product": row["物料品类"], "model": row["尺码"], "region": row["战区"], "quantity": max(1, int(row.get("数量") or 1)), "remark": str(row.get("备注") or "")}
                for row in edited.to_dict("records")
            ]
            st.session_state["cultural_request_lines"] = lines
        if st.button("提交文化周边申请", key="cultural_request_preview", type="primary", width="stretch", disabled=not lines):
            validation_errors: list[str] = []
            if not requester or not requester_open_id:
                validation_errors.append("请选择申请人。")
            if not str(material_usage or "").strip():
                validation_errors.append("请填写文化衫用途（展会名称）。")
            if validation_errors:
                show_request_validation_toast(validation_errors)
                return
            try:
                validate_cultural_request_quantity(lines)
            except RuntimeError as exc:
                st.warning(str(exc))
                return
            st.session_state["cultural_request_draft"] = {
                "requester": requester,
                "requester_open_id": requester_open_id,
                "department": department,
                "department_id": department_id,
                "material_usage": str(material_usage).strip(),
                "submission_token": st.session_state["cultural_request_submission_token"],
                "lines": lines,
            }
            st.session_state["cultural_request_stage"] = "review"
            st.rerun()


def render_management_page() -> None:
    current_section = str(st.session_state.get(MANAGEMENT_NAVIGATION_KEY, "库存登记"))
    if current_section in {"周边礼品项目", "项目礼品管理"}:
        st.session_state[MATERIAL_MANAGEMENT_CONTROL_KEY] = "项目礼品管理"
        current_section = "物料管理"
    elif current_section == "发货模板填写":
        st.session_state[MATERIAL_MANAGEMENT_CONTROL_KEY] = "发货模板"
        current_section = "物料管理"
    if current_section == "新增物料品类":
        st.session_state[MATERIAL_MANAGEMENT_CONTROL_KEY] = "品类管理"
        current_section = "物料管理"
    elif current_section == "品类管理":
        st.session_state[MATERIAL_MANAGEMENT_CONTROL_KEY] = current_section
        current_section = "物料管理"
    if current_section not in {
        "库存登记",
        "文化周边申领",
        "物料管理",
    }:
        current_section = "库存登记"
    # This write keeps the app-level navigation state alive while pages such as
    # category management render no workbench radio control.
    set_management_section(current_section)
    if (
        current_section == "库存登记"
        and st.session_state.get("request_form_stage") == "review"
    ):
        render_page_header(
            "申请信息确认",
            "提交前核对",
            "确认申请信息和全部物料明细后再同步至飞书。",
            page_key="request",
        )
        render_request_review()
        return
    page_copy = {
        "库存登记": ("营销物料领取登记", "申请工作台", "登记领取申请并提交至审批发放流程。"),
        "文化周边申领": ("文化周边申领", "文化周边工作台", "选择文化周边、尺码和战区，提交后直接登记发放。"),
        "物料管理": ("物料管理", "库存工作台", "采购补库与物料品类统一管理。"),
    }
    page_title, page_kicker, page_subtitle = page_copy.get(current_section, page_copy["库存登记"])
    page_cache_key = {
        "库存登记": "request",
        "文化周边申领": "cultural_request",
        "物料管理": (
            {
                "品类管理": "category",
                "战区管理": "cultural_request",
                "型号管理": "model_management",
                "语种管理": "language_management",
                "发货模板": "shipping",
                "下单排期管理": "order_scheduling",
                "项目礼品管理": "gift_projects",
                "仓库位置": "",
            }.get(
                str(st.session_state.get(MATERIAL_MANAGEMENT_CONTROL_KEY) or ""),
                "restock",
            )
        ),
    }[current_section]
    render_page_header(
        page_title,
        page_kicker,
        page_subtitle,
        page_key=page_cache_key,
    )
    if management_section_requires_admin(current_section) and not admin_auth_gate():
        return
    if current_section == "文化周边申领":
        render_page_cache_toolbar("cultural_request")
        render_cultural_request_page()
        return
    if current_section == "物料管理":
        if st.session_state.get(MATERIAL_MANAGEMENT_CONTROL_KEY) not in MATERIAL_MANAGEMENT_SECTIONS:
            st.session_state[MATERIAL_MANAGEMENT_CONTROL_KEY] = MATERIAL_MANAGEMENT_SECTIONS[0]
        material_section = st.radio(
            "物料管理功能",
            MATERIAL_MANAGEMENT_SECTIONS,
            horizontal=True,
            label_visibility="collapsed",
            key=MATERIAL_MANAGEMENT_CONTROL_KEY,
            on_change=request_material_management_navigation_loading,
        )
        cache_key = {
            "采购补库": "restock",
            "战区管理": "cultural_request",
            "品类管理": "category",
            "型号管理": "model_management",
            "语种管理": "language_management",
            "发货模板": "shipping",
            "下单排期管理": "order_scheduling",
            "项目礼品管理": "gift_projects",
        }.get(material_section)
        if cache_key:
            render_page_cache_toolbar(cache_key)
        if material_section == "采购补库":
            render_restock_form()
        elif material_section == "战区管理":
            render_dimension_management_page("region")
        elif material_section == "品类管理":
            render_add_category_form()
        elif material_section == "型号管理":
            render_dimension_management_page("model")
        elif material_section == "语种管理":
            render_dimension_management_page("language")
        elif material_section == "仓库位置":
            st.caption("仓库位置图片和申领页品类图片由本机“更新 PUDU 图片缓存”程序手动发布。")
            render_warehouse_location_view(show_header=False)
        elif material_section == "项目礼品管理":
            render_gift_projects_page()
        elif material_section == "下单排期管理":
            from order_scheduling_page import render_order_scheduling_page
            render_order_scheduling_page(APP_RUNTIME)
        else:
            render_shipping_template_page(load_feishu_category_records())
        return
    render_page_cache_toolbar("request")
    render_change_form(show_title=False)


def render_management_page_with_navigation_loading() -> None:
    st.session_state.pop(MANAGEMENT_NAVIGATION_LOADING_KEY, None)
    render_management_page()


def restore_default_sidebar_on_page_load() -> None:
    st.components.v1.html(
        """
        <script>
        (() => {
          const parentDocument = window.parent.document;
          const marker = "puduDefaultSidebarApplied";
          if (parentDocument.body.dataset[marker] === "true") return;
          let attempts = 0;
          const timer = window.setInterval(() => {
            attempts += 1;
            const sidebar = parentDocument.querySelector('[data-testid="stSidebar"]');
            const button = parentDocument.querySelector(
              '[data-testid="stSidebarCollapseButton"] button'
            );
            if (sidebar && button) {
              parentDocument.body.dataset[marker] = "true";
              if (sidebar.getAttribute("aria-expanded") === "false") button.click();
              window.clearInterval(timer);
            } else if (attempts >= 50) {
              window.clearInterval(timer);
            }
          }, 100);
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def render_request_inventory_review_page() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        [data-testid="stMainBlockContainer"] { max-width: 1180px !important; }
        </style>
        <span class="pudu-allocation-workbench-marker" aria-hidden="true"></span>
        """,
        unsafe_allow_html=True,
    )
    request_id = str(st.query_params.get("request_id", "")).strip()
    operator_open_id = str(st.query_params.get("operator", "")).strip()
    review_token = str(st.query_params.get("review_token", "")).strip()
    if not request_id:
        st.error("缺少申请单标识，请从管理员库存确认卡片重新打开。")
        return
    signed_admin = (
        valid_request_review_access_token(request_id, operator_open_id, review_token)
        and operator_open_id in cached_enabled_admin_open_ids(*feishu_config_args())
    )
    if not signed_admin and not admin_auth_gate():
        st.info("该页面仅供已授权管理员查看和编辑。")
        return

    with fullscreen_data_sync("正在抓取申请单数据，请稍候..."):
        context = request_inventory_review_page_context(request_id)
    request = dict(context["request"])
    lines = [dict(line) for line in list(context["lines"])]
    render_page_header(
        "配货工作台",
        "调整本次申请的配货方案",
        f"申请单 {request.get('request_no') or '-'}；实时库存更新于 {context.get('snapshot_at')}",
        page_key="",
    )
    from order_scheduling import SHIP_DATE, as_date as scheduling_as_date
    request_fields = feishu_fields(context.get("request_row") or {})
    current_ship_date = scheduling_as_date(request_fields.get(SHIP_DATE))
    ship_date = st.date_input(
        "申请单发货日期 *",
        value=current_ship_date,
        format="YYYY-MM-DD",
        key=f"request_inventory_ship_date_{request_id}",
    )
    if str(request.get("inventory_review_status") or "") == INVENTORY_REVIEW_CONFIRMED:
        st.success("该申请已经完成库存核实，无需再次处理。")
        return

    original_total_rmb = request_lines_total_rmb(lines)
    if not original_total_rmb:
        original_total_rmb = float(request.get("request_total_rmb") or 0)
    summary_cols = st.columns(5)
    summary_cols[0].metric("申请人", str(request.get("requester") or "-"))
    summary_cols[1].metric("申请部门", str(request.get("department") or "-"))
    summary_cols[2].metric("当前结论", str(context.get("result") or "-"))
    summary_cols[3].metric("变更次数", int(request.get("inventory_review_version") or 0))
    summary_cols[4].metric("原申请总金额", format_rmb(original_total_rmb))
    st.caption(f"申请原因：{request.get('request_reason') or '-'}")
    st.caption(f"物料用途：{request.get('material_usage') or '-'}")
    st.caption(f"收件人信息：{request.get('recipient_info') or '-'}")

    cache_data = load_static_request_form_cache()
    current_material_ids = {
        str(line.get("material_record_id") or "") for line in lines
    }
    material_records = cached_allocation_material_records(
        cache_data,
        list(context.get("material_rows") or []),
        current_material_ids=current_material_ids,
    )
    if not material_records:
        st.error("页面物料目录缓存为空，请先在主应用刷新申请页缓存。")
        return
    material_by_dimensions = {
        (
            str(item.get("category") or ""),
            str(item.get("model") or NO_MODEL_TEXT),
            str(item.get("language") or NO_LANGUAGE_TEXT),
        ): str(item.get("record_id") or "")
        for item in material_records
        if str(item.get("record_id") or "")
    }
    material_price_by_dimensions = {
        (
            str(item.get("category") or ""),
            str(item.get("model") or NO_MODEL_TEXT),
            str(item.get("language") or NO_LANGUAGE_TEXT),
        ): float(item.get("unit_price_rmb") or 0)
        for item in material_records
    }
    categories = unique_preserve(
        [str(item.get("category") or "") for item in material_records]
    )
    draft_key = (
        f"request_inventory_draft_{request_id}_"
        f"{int(request.get('inventory_review_version') or 0)}"
    )
    if draft_key not in st.session_state:
        st.session_state[draft_key] = [
            {
                "uid": str(line.get("record_id") or uuid.uuid4().hex),
                "category": str(line.get("product") or ""),
                "model": str(line.get("model") or NO_MODEL_TEXT),
                "language": str(line.get("language") or NO_LANGUAGE_TEXT),
                "quantity": max(1, int(line.get("quantity") or 1)),
                "remark": str(line.get("remark") or ""),
                "order_required": int(line.get("current_stock") or 0) < int(line.get("quantity") or 0),
            }
            for line in lines
        ]
    draft_rows = list(st.session_state[draft_key])
    st.markdown("#### 配货明细")
    st.caption(
        f"品类、型号和语种来自页面缓存（{cache_data.get('generated_at') or '未知时间'}）。"
        "页面内调整不会写入后台，点击提交后才会一次性进入任务队列。"
    )
    direct_confirm = st.button(
        "按原申请确认并提交",
        type="secondary",
        icon=":material/check_circle:",
        width="stretch",
    )
    if direct_confirm:
        if not ship_date:
            st.error("请选择申请单发货日期。")
            return
        with fullscreen_data_sync("正在提交库存确认，请稍后......"):
            task, _ = enqueue_feishu_background_write(
                QUEUE_TASK_TYPE_REQUEST_INVENTORY_CONFIRM,
                {
                    "draft": {
                        "request_id": request_id,
                        "expected_version": int(request.get("inventory_review_version") or 0),
                        "operator_open_id": operator_open_id if signed_admin else "",
                        "ship_date": ship_date.isoformat() if ship_date else "",
                        "generation_key": f"allocation:{request_id}:{int(request.get('inventory_review_version') or 0)}",
                    }
                },
                idempotency_key=(
                    f"request-inventory-confirm:{request_id}:"
                    f"{int(request.get('inventory_review_version') or 0)}:{ship_date.isoformat()}"
                ),
            )
        render_inventory_plan_submission_success()
        st.stop()
    remove_uid = ""
    line_cards = st.columns(2, gap="medium")
    for index, row in enumerate(draft_rows):
        uid = str(row.get("uid") or uuid.uuid4().hex)
        row["uid"] = uid
        widget_prefix = f"request_inventory_line_{request_id}_{uid}"
        with line_cards[index % len(line_cards)].container(border=True):
            category_key = f"{widget_prefix}_category"
            if st.session_state.get(category_key) not in categories:
                st.session_state[category_key] = (
                    str(row.get("category") or "")
                    if str(row.get("category") or "") in categories
                    else (categories[0] if categories else "")
                )
            category = st.selectbox(
                "品类",
                categories,
                key=category_key,
            )
            models = unique_preserve(
                [
                    str(item.get("model") or NO_MODEL_TEXT)
                    for item in material_records
                    if str(item.get("category") or "") == category
                ]
            )
            model_key = f"{widget_prefix}_model"
            if st.session_state.get(model_key) not in models:
                st.session_state[model_key] = (
                    str(row.get("model") or NO_MODEL_TEXT)
                    if str(row.get("model") or NO_MODEL_TEXT) in models
                    else (models[0] if models else NO_MODEL_TEXT)
                )
            model = st.selectbox("型号", models, key=model_key)
            languages = unique_preserve(
                [
                    str(item.get("language") or NO_LANGUAGE_TEXT)
                    for item in material_records
                    if str(item.get("category") or "") == category
                    and str(item.get("model") or NO_MODEL_TEXT) == model
                ]
            )
            language_key = f"{widget_prefix}_language"
            if st.session_state.get(language_key) not in languages:
                st.session_state[language_key] = (
                    str(row.get("language") or NO_LANGUAGE_TEXT)
                    if str(row.get("language") or NO_LANGUAGE_TEXT) in languages
                    else (languages[0] if languages else NO_LANGUAGE_TEXT)
                )
            language = st.selectbox("语种", languages, key=language_key)
            quantity_col, order_col = st.columns([1, 1], gap="small")
            quantity = int(
                quantity_col.number_input(
                    "数量",
                    min_value=1,
                    step=1,
                    value=max(1, int(row.get("quantity") or 1)),
                    key=f"{widget_prefix}_quantity",
                )
            )
            if order_col.button(
                "删除",
                key=f"{widget_prefix}_remove",
                disabled=len(draft_rows) <= 1,
            ):
                remove_uid = uid
            remark = st.text_input(
                "备注",
                value=str(row.get("remark") or ""),
                key=f"{widget_prefix}_remark",
            )
            order_choice = st.selectbox(
                "是否下单",
                ("需要下单", "无需下单"),
                index=0 if row.get("order_required") is True else 1,
                key=f"{widget_prefix}_order_required",
            )
        row.update(
            {
                "category": category,
                "model": model,
                "language": language,
                "quantity": quantity,
                "remark": remark,
                "order_required": order_choice == "需要下单",
            }
        )
    st.session_state[draft_key] = draft_rows
    allocated_total_rmb = round(
        sum(
            material_price_by_dimensions.get(
                (
                    str(row.get("category") or ""),
                    str(row.get("model") or NO_MODEL_TEXT),
                    str(row.get("language") or NO_LANGUAGE_TEXT),
                ),
                0.0,
            )
            * int(row.get("quantity") or 0)
            for row in draft_rows
        ),
        2,
    )
    amount_cols = st.columns(2)
    amount_cols[0].metric("原申请总金额", format_rmb(original_total_rmb))
    amount_cols[1].metric(
        "当前配货总金额",
        format_rmb(allocated_total_rmb),
        delta=format_rmb(allocated_total_rmb - original_total_rmb),
    )
    if remove_uid:
        st.session_state[draft_key] = [
            row for row in draft_rows if str(row.get("uid") or "") != remove_uid
        ]
        st.rerun()
    if st.button("新增明细", icon=":material/add:"):
        first = material_records[0] if material_records else {}
        draft_rows.append(
            {
                "uid": uuid.uuid4().hex,
                "category": str(first.get("category") or ""),
                "model": str(first.get("model") or NO_MODEL_TEXT),
                "language": str(first.get("language") or NO_LANGUAGE_TEXT),
                "quantity": 1,
                "remark": "",
            }
        )
        st.session_state[draft_key] = draft_rows
        st.rerun()
    change_note = st.text_area(
        "配货调整说明 *",
        placeholder="请说明替换、增加、删除物料或调整数量的原因；该说明会发送给申请人。",
        key=f"request_inventory_change_note_{request_id}",
    )
    confirmed = st.checkbox(
        "我已核对配货方案，并确认向申请人发送变更通知",
        key=f"request_inventory_edit_confirmed_{request_id}",
    )
    if not st.button(
        "提交配货方案",
        type="primary",
        icon=":material/send:",
        disabled=not confirmed,
        width="stretch",
    ):
        return

    if not ship_date:
        st.error("请选择申请单发货日期。")
        return

    rows = [dict(row) for row in list(st.session_state.get(draft_key) or [])]
    if not rows:
        st.error("配货方案必须至少保留一条物料明细。")
        return
    invalid_rows = [
        row
        for row in rows
        if (
            str(row.get("category") or ""),
            str(row.get("model") or NO_MODEL_TEXT),
            str(row.get("language") or NO_LANGUAGE_TEXT),
        )
        not in material_by_dimensions
    ]
    if invalid_rows:
        st.error("配货方案中存在无效物料，请重新选择。")
        return
    if not change_note.strip():
        st.error("请填写配货调整说明。")
        return
    payload_lines = [
        {
            "material_record_id": material_by_dimensions[
                (
                    str(row.get("category") or ""),
                    str(row.get("model") or NO_MODEL_TEXT),
                    str(row.get("language") or NO_LANGUAGE_TEXT),
                )
            ],
            "quantity": int(row.get("quantity") or 0),
            "remark": str(row.get("remark") or ""),
            "order_required": row.get("order_required") is True,
        }
        for row in rows
    ]
    if len({line["material_record_id"] for line in payload_lines}) != len(payload_lines):
        st.error("同一物料不能重复添加，请合并数量后再提交。")
        return
    with fullscreen_data_sync("正在提交配货方案，请稍后......"):
        task, _ = enqueue_feishu_background_write(
            QUEUE_TASK_TYPE_REQUEST_INVENTORY_EDIT,
            {
                "draft": {
                    "request_id": request_id,
                    "expected_version": int(request.get("inventory_review_version") or 0),
                    "change_note": change_note.strip(),
                    "operator_open_id": operator_open_id if signed_admin else "",
                    "ship_date": ship_date.isoformat(),
                    "generation_key": f"allocation:{request_id}:{int(request.get('inventory_review_version') or 0)}",
                    "before_lines": _request_review_line_summary(lines),
                    "lines": payload_lines,
                }
            },
            idempotency_key=(
                f"request-inventory-edit:{request_id}:"
                f"{int(request.get('inventory_review_version') or 0)}:"
                f"{hashlib.sha256(json.dumps(payload_lines, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()}"
            ),
        )
    render_inventory_plan_submission_success()
    st.stop()


def main() -> None:
    apply_ui_language_from_query()
    install_streamlit_ui_translation(st, get_ui_language)
    st.set_page_config(
        page_title=ui_text("营销物料管理系统"),
        page_icon=str(APP_ICON_PATH) if APP_ICON_PATH.exists() else ":material/inventory_2:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    prepare_live_cache_view()
    render_live_cache_notice()
    inject_global_styles()
    install_button_click_guard()
    apply_management_section_from_query()
    allocation_view = str(st.query_params.get("allocation", "")) == "request"
    if not allocation_view:
        restore_default_sidebar_on_page_load()
    stop_on_invalid_feishu_config()
    if not allocation_view:
        render_sidebar_link()

    view = str(st.query_params.get("view", ""))
    try:
        if allocation_view:
            render_request_inventory_review_page()
        elif view == "inventory":
            render_inventory_view()
        elif view == "warehouse":
            render_warehouse_location_view()
        elif view == "request_inventory_review":
            render_request_inventory_review_page()
        else:
            render_management_page_with_navigation_loading()
    except FeishuBitableError as exc:
        render_feishu_error(exc)


if __name__ == "__main__":
    main()
