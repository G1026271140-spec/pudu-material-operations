from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
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
from ui_i18n import (
    LANGUAGE_EN,
    LANGUAGE_ZH,
    SUPPORTED_UI_LANGUAGES,
    install_streamlit_ui_translation,
    normalize_ui_language,
    translate_ui_text,
)


DEFAULT_PASSWORD = "376493"
NO_MODEL_TEXT = "无需型号"
NO_LANGUAGE_TEXT = "无需语种"
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
REQUEST_TABLE_NAME = "物料申请单"
REQUEST_LINE_TABLE_NAME = "申请明细"
MATERIAL_TABLE_NAME = "物料主数据"
CATEGORY_TABLE_NAME = "物料品类"
MODEL_TABLE_NAME = "产品型号"
LANGUAGE_TABLE_NAME = "物料语种"
LEDGER_TABLE_NAME = "库存流水"
USER_PERMISSION_TABLE_NAME = "用户权限表"
MODEL_LINK_FIELD_CANDIDATES = ("型号关联", "产品型号 2")
LANGUAGE_LINK_FIELD_CANDIDATES = ("语种关联", "物料语种", "语言种类 2")
UNIT_PRICE_FIELD_CANDIDATES = ("单价（美元）", "单价")
STATUS_ACTIVE = "启用"
STATUS_INACTIVE = "停用"
MATERIAL_STATUS_OPTIONS = (STATUS_ACTIVE, STATUS_INACTIVE)
INVENTORY_ZERO_SINCE_FIELD = "库存归零时间"
INVENTORY_AUTO_DISABLE_DAYS = 14
CATEGORY_CREATE_STAGE_KEY = "category_create_stage"
CATEGORY_CREATE_DRAFT_KEY = "category_create_draft"
CATEGORY_EDIT_STAGE_KEY = "category_edit_stage"
CATEGORY_EDIT_DRAFT_KEY = "category_edit_draft"
REQUEST_NO_PREFIX = "REQ"
RESTOCK_NO_PREFIX = "RST"
REQUEST_FORM_TITLE = "MKT营销物料领取流程(MKT Marketing Materials Collecting Process)"
DEFAULT_STREAMLIT_APP_URL = (
    "https://pudu-material-inventory-ndgbxrpkkrzgkbapvhzvix.streamlit.app/"
)
REQUEST_STATUS_PENDING = "待审批"
REQUEST_STATUS_PARTIAL = "部分发放"
REQUEST_STATUS_ISSUED = "已发放"
REQUEST_STATUS_WITHDRAWN = "已撤回"
REQUEST_LINE_STATUS_PENDING = "待审批"
REQUEST_LINE_STATUS_PARTIAL = "部分发放"
REQUEST_LINE_STATUS_ISSUED = "已发放"
REQUEST_LINE_STATUS_WITHDRAWN = "已撤回"
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
MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS_PER_REQUEST = 100
GITHUB_REPOSITORY = "G1026271140-spec/pudu-material-inventory"
GITHUB_CACHE_WORKFLOW_FILE = "refresh-static-cache.yml"
GITHUB_CACHE_WORKFLOW_URL = (
    f"https://github.com/{GITHUB_REPOSITORY}/actions/workflows/{GITHUB_CACHE_WORKFLOW_FILE}"
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
DATA_CACHE_TTL_SECONDS = 30
MAX_REQUEST_LINE_COUNT = 20
ADMIN_MANAGEMENT_SECTIONS = frozenset({"物料管理"})
MANAGEMENT_NAVIGATION_KEY = "management_section"
MANAGEMENT_NAVIGATION_LOADING_KEY = "management_navigation_loading"
MANAGEMENT_WORKBENCH_CONTROL_KEY = "management_section_control"
MANAGEMENT_WORKBENCH_SECTIONS = ("库存登记", "修改与撤回")
MATERIAL_MANAGEMENT_CONTROL_KEY = "material_management_section"
MATERIAL_MANAGEMENT_SECTIONS = ("采购补库", "品类管理", "物料数据库")
MATERIAL_DASHBOARD_MODULES = (
    "概览指标",
    "品类库存数量",
    "品类库存价值",
    "语种分布",
    "库存预警",
)
MATERIAL_STOCK_STATUSES = ("负库存", "零库存", "低库存", "正常库存")
DEFAULT_LOW_STOCK_THRESHOLD = 100
UI_LANGUAGE_SESSION_KEY = "ui_language"
REQUEST_CONTACT_USER_LOOKUP_KEY = "_request_contact_user_by_id"
REQUEST_FORM_STATIC_CACHE_PATH = Path(__file__).resolve().parent / "data" / "request_form_cache.json"
PAGE_DATA_STATIC_CACHE_PATH = Path(__file__).resolve().parent / "data" / "page_data_cache.json"
WAREHOUSE_LOCATION_CACHE_PATH = (
    Path(__file__).resolve().parent / "data" / "warehouse_location_cache.json"
)
CONTACT_DEPARTMENT_STATIC_CACHE_PATH = (
    Path(__file__).resolve().parent / "data" / "contact_departments_cache.json"
)
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "app-icon.png"
REQUEST_CATEGORY_IMAGE_DIR = (
    Path(__file__).resolve().parent / "assets" / "request_categories"
)
REQUEST_CATEGORY_IMAGE_RULES = (
    (("产品单页", "product flyer"), "product-flyer.webp"),
    (("品牌手册", "product brochure (all banner"), "brand-brochure.webp"),
    (
        ("工业产品线手册", "工业线产品手册", "industrial product line brochure", "industrial delivery robot"),
        "industrial-brochure.webp",
    ),
    (
        ("清洁产品线手册", "清洁线产品手册", "cleaning product line brochure", "cleaning robot product brochure"),
        "cleaning-brochure.webp",
    ),
    (("配送线产品手册", "delivery robot product brochure"), "delivery-brochure.webp"),
    (("具身线产品手册", "embodied ai robot product brochure"), "embodied-brochure.webp"),
    (("产品易拉宝", "易拉宝", "product roll-up"), "product-roll-up.webp"),
    (("公仔", "plush toy"), "plush-toy.webp"),
    (("冰箱贴", "fridge magnet"), "fridge-magnet.webp"),
    (("笔记本礼盒", "notebook gift box"), "notebook-gift-box.webp"),
    (("普渡logo无纺布手提袋", "pudu logo bag"), "pudu-logo-bag.webp"),
    (("扇子", "fan"), "fan.webp"),
)
REQUEST_FORM_CACHE_LOCK = threading.Lock()
REQUEST_FORM_CACHE_STATE: dict[str, object] = {
    "data": None,
    "refreshing": False,
    "error": "",
    "updated_at": "",
}
APPROVAL_LIVE_DATA_KEY = "approval_live_data"
LAST_APP_VIEW_KEY = "last_app_view"
ALL_PAGE_CACHE_TABLES = (
    CATEGORY_TABLE_NAME,
    MODEL_TABLE_NAME,
    LANGUAGE_TABLE_NAME,
    MATERIAL_TABLE_NAME,
    LEDGER_TABLE_NAME,
    REQUEST_TABLE_NAME,
    REQUEST_LINE_TABLE_NAME,
)
PAGE_CACHE_TABLES = {
    "request": (CATEGORY_TABLE_NAME, MODEL_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME),
    "restock": (CATEGORY_TABLE_NAME, MODEL_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME),
    "category": (CATEGORY_TABLE_NAME, MODEL_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME),
    "maintenance": ALL_PAGE_CACHE_TABLES,
    "material_database": (CATEGORY_TABLE_NAME, MODEL_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME),
    "approval": (REQUEST_TABLE_NAME, REQUEST_LINE_TABLE_NAME, MATERIAL_TABLE_NAME),
    "inventory": (CATEGORY_TABLE_NAME, LANGUAGE_TABLE_NAME, MATERIAL_TABLE_NAME, LEDGER_TABLE_NAME),
}
OPTIONAL_PAGE_CACHE_TABLES = {LANGUAGE_TABLE_NAME}


def get_ui_language() -> str:
    try:
        return normalize_ui_language(st.session_state.get(UI_LANGUAGE_SESSION_KEY, LANGUAGE_ZH))
    except (AttributeError, KeyError):
        return LANGUAGE_ZH


def ui_text(value: object) -> str:
    return str(translate_ui_text(value, get_ui_language()))


def request_option_display_label(value: object) -> str:
    text = str(value or "").strip()
    if get_ui_language() != LANGUAGE_EN:
        return text
    english_parts = re.findall(r"[（(]([^()（）]*[A-Za-z][^()（）]*)[）)]", text)
    if english_parts:
        return english_parts[-1].strip()
    return str(translate_ui_text(text, LANGUAGE_EN))


def request_category_display_label(value: object) -> str:
    text = str(value or "").strip()
    if get_ui_language() == LANGUAGE_EN:
        return request_option_display_label(text)
    chinese_label = re.split(r"[（(]", text, maxsplit=1)[0].strip()
    return chinese_label or text


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
        [data-testid="stHeader"] {
            height: 56px;
            background: rgba(255, 255, 255, 0.96);
            border-bottom: 1px solid var(--pudu-line-soft);
        }
        [data-testid="stMainBlockContainer"] {
            max-width: 1320px;
            padding: 3.5rem 2.25rem 4rem;
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
            padding-top: 1rem !important;
        }
        [data-testid="stSidebar"] hr {
            margin: 1rem 0;
            border-color: var(--pudu-line-soft);
        }
        [data-testid="stSidebar"] .stButton > button {
            justify-content: flex-start;
            min-height: 40px;
            padding: 0 0.75rem;
            background: #FFFFFF;
            border: 1px solid var(--pudu-line);
            color: var(--pudu-ink);
            box-shadow: none;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: var(--pudu-blue-soft);
            border-color: #9FB8CB;
            color: var(--pudu-blue);
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
        .st-key-sidebar_open_approval button,
        .st-key-sidebar_current_approval button {
            border-left: 3px solid var(--pudu-coral) !important;
        }
        .st-key-sidebar_open_material_database button {
            border-left: 3px solid var(--pudu-teal) !important;
        }
        .st-key-sidebar_open_material_management button {
            border-left: 3px solid var(--pudu-teal) !important;
        }
        .st-key-sidebar_open_category button {
            border-left: 3px solid var(--pudu-gold) !important;
        }
        .st-key-sidebar_open_request button:disabled {
            background: var(--pudu-navy-soft) !important;
            color: var(--pudu-navy) !important;
            opacity: 1;
        }
        .st-key-sidebar_current_approval button:disabled {
            background: var(--pudu-coral-soft) !important;
            color: #A6422D !important;
            opacity: 1;
        }
        .st-key-sidebar_open_material_database button:disabled {
            background: var(--pudu-teal-soft) !important;
            color: #116A6E !important;
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
            margin-bottom: 1rem;
            padding: 0.25rem 0 1rem;
            border-bottom: 1px solid var(--pudu-line);
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
            font-size: 1rem;
            font-weight: 680;
            line-height: 1.35;
        }
        .pudu-brand-subtitle {
            color: var(--pudu-muted) !important;
            font-size: 0.75rem;
            margin-top: 0.1rem;
        }
        .pudu-sidebar-label {
            color: var(--pudu-subtle) !important;
            font-size: 0.72rem;
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
        .pudu-header-status {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            white-space: nowrap;
            padding: 0.42rem 0.7rem;
            border: 1px solid #BFDCD8;
            border-radius: 999px;
            background: var(--pudu-teal-soft);
            color: #116A6E;
            font-size: 0.75rem;
            font-weight: 620;
        }
        .pudu-header-status::before {
            content: "";
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--pudu-green);
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
        .pudu-approval-line-marker {
            display: none;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-approval-line-marker) > [data-testid="stVerticalBlock"] {
            gap: 0.45rem;
            padding: 0.8rem 0.9rem;
            border-color: var(--pudu-line) !important;
            border-radius: 8px !important;
            background: #FFFFFF;
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-approval-line-shortage) > [data-testid="stVerticalBlock"] {
            border-color: #F2B8B5 !important;
            border-left: 3px solid #D14343 !important;
            background: #FFF8F7;
        }
        .pudu-approval-line-heading {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            padding-bottom: 0.42rem;
            border-bottom: 1px solid var(--pudu-line);
        }
        .pudu-approval-line-title {
            color: var(--pudu-ink);
            font-size: 0.88rem;
            font-weight: 700;
        }
        .pudu-approval-stock-badge {
            padding: 0.18rem 0.45rem;
            border-radius: 5px;
            background: #E5F4EF;
            color: #166A52;
            font-size: 0.72rem;
            font-weight: 700;
        }
        .pudu-approval-stock-badge.is-shortage {
            background: #FEE2E2;
            color: #991B1B;
        }
        .pudu-approval-control-label {
            margin-bottom: 0.2rem;
            color: var(--pudu-muted);
            font-size: 0.72rem;
            font-weight: 620;
        }
        .pudu-approval-line-reference {
            min-height: 2.1rem;
            padding: 0.15rem 0 0.55rem;
            color: var(--pudu-muted);
            font-size: 0.78rem;
            line-height: 1.45;
            overflow-wrap: anywhere;
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
            position: fixed;
            inset: 0;
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
            background: rgba(245, 246, 248, 0.82);
            backdrop-filter: blur(1.5px);
        }
        [data-testid="stSpinner"] > div {
            width: min(360px, calc(100vw - 2rem)) !important;
            min-width: 0;
            max-width: calc(100vw - 2rem);
            flex: 0 0 auto;
            padding: 1rem 1.15rem;
            border: 1px solid var(--pudu-line);
            border-radius: 8px;
            background: #FFFFFF;
            box-shadow: 0 8px 24px rgba(31, 35, 41, 0.12);
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
        .pudu-cart-marker,
        .pudu-full-cart-popover-marker {
            display: none;
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
        [data-testid="stLayoutWrapper"]:has(.pudu-product-card-marker) > [data-testid="stVerticalBlock"] {
            min-height: 286px;
            gap: 0.35rem;
            padding: 0.7rem !important;
            border-color: #D8E1E8 !important;
            border-radius: 10px !important;
            background: linear-gradient(145deg, #FFFFFF 0%, #F6FAFC 100%);
        }
        [data-testid="stLayoutWrapper"]:has(.pudu-product-card-marker) [data-testid="stImage"] img {
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
        hr {
            border-color: var(--pudu-line-soft);
        }
        [data-testid="stAppDeployButton"],
        [data-testid="stMainMenuButton"] {
            display: none;
        }
        @media (max-width: 900px) {
            [data-testid="stMainBlockContainer"] {
                padding: 3.5rem 1rem 3rem;
            }
            .pudu-page-header {
                align-items: flex-start;
                flex-direction: column;
                gap: 0.8rem;
            }
            .pudu-page-title {
                font-size: 1.55rem;
            }
            .pudu-header-status {
                white-space: normal;
            }
            [data-testid="stHorizontalBlock"] {
                gap: 0.75rem;
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
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(title: str, kicker: str, subtitle: str, status: str = "飞书数据已连接") -> None:
    title = ui_text(title)
    kicker = ui_text(kicker)
    subtitle = ui_text(subtitle)
    status = ui_text(status)
    st.markdown(
        f"""
        <div class="pudu-page-header">
            <div>
                <div class="pudu-page-kicker">{escape(kicker)}</div>
                <div class="pudu-page-title">{escape(title)}</div>
                <div class="pudu-page-subtitle">{escape(subtitle)}</div>
            </div>
            <div class="pudu-header-status">{escape(status)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
        return str(st.secrets.get("APPROVAL_VIEW_PASSWORD", get_inventory_password()))
    except (FileNotFoundError, KeyError, AttributeError):
        return get_inventory_password()


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
            "User-Agent": "pudu-material-inventory",
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


def feishu_bitable_app_token() -> str:
    return get_secret_value("FEISHU_BITABLE_APP_TOKEN")


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


def set_feishu_unit_price(
    table_name: str,
    fields: dict[str, object],
    value: object,
) -> None:
    set_first_plain_field(table_name, fields, list(UNIT_PRICE_FIELD_CANDIDATES), value)


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


def material_record_is_active(record: dict) -> bool:
    return normalize_enabled_status(record.get("status")) == STATUS_ACTIVE


def enforce_category_inventory_status(plan: dict, category_status: object) -> dict:
    if normalize_enabled_status(category_status) == STATUS_INACTIVE:
        for target in list(plan.get("targets") or []):
            target["status"] = STATUS_INACTIVE
    return plan


def normalize_option_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_category_match_key(value: object) -> str:
    """Match category labels even when bilingual suffix formatting differs."""
    normalized = unicodedata.normalize("NFKC", normalize_option_label(value))
    base_label = normalized.split("(", 1)[0].strip()
    return re.sub(r"\s+", "", base_label or normalized).casefold()


def request_category_image_path(product: object) -> Path | None:
    normalized_product = normalize_option_label(product).casefold()
    for aliases, filename in REQUEST_CATEGORY_IMAGE_RULES:
        if any(alias.casefold() in normalized_product for alias in aliases):
            path = REQUEST_CATEGORY_IMAGE_DIR / filename
            return path if path.exists() else None
    return None


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
            language_name = str(item[2]).strip()
            inventory_product_keys.add(product_key)
            if model_name and model_name != NO_MODEL_TEXT:
                product_models.setdefault(product_key, []).append(model_name)
            if language_name:
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
    all_models = sort_models(list(selection_context.get("models") or []))
    return bool(is_no_model_product), all_models or sort_models(list(scoped_models))


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
    if product_key in selection_context.get("no_language_product_keys", set()):
        return [NO_LANGUAGE_TEXT]
    available_languages = fallback_languages or list(selection_context["languages"])
    return sort_languages(list(available_languages))


def product_language_state(
    product: str,
    model: str,
    selection_context: dict[str, object],
    fallback_languages: list[str] | None = None,
) -> tuple[bool, list[str]]:
    product_key = normalize_option_label(product)
    is_no_language_product = product_key in selection_context.get("no_language_product_keys", set())
    return bool(is_no_language_product), product_language_options(
        product,
        model,
        selection_context,
        fallback_languages,
    )


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
                    "model": str(item[2]) or NO_MODEL_TEXT,
                    "language": str(item[3]),
                    "quantity": int(item[4] or 0),
                }
            )
    return {
        "schema_version": 1,
        "source": source,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "products": sort_request_products(list(options.get("products") or [])),
        "no_model_products": unique_preserve(list(options.get("no_model_products") or [])),
        "no_language_products": unique_preserve(list(options.get("no_language_products") or [])),
        "configured_language_products": unique_preserve(
            list(options.get("configured_language_products") or [])
        ),
        "models": sort_models(list(options.get("models") or [])),
        "languages": sort_languages(list(options.get("languages") or [])),
        "inventory_rows": rows,
        "row_count": len(rows),
    }


def build_live_request_form_cache() -> dict[str, object]:
    inventory_df = load_feishu_inventory_snapshot(*feishu_config_args())
    options = load_feishu_options_snapshot(*feishu_config_args())
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
            "no_language_products": [],
            "configured_language_products": [],
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


def refresh_request_form_cache_from_page_data() -> dict[str, object]:
    data = request_form_cache_from_inventory(
        load_feishu_options(),
        load_feishu_inventory(),
        source="session_page_refresh",
    )
    set_request_form_cache_state(
        data=data,
        refreshing=False,
        error="",
        updated_at=str(data.get("generated_at") or ""),
    )
    if not st.session_state.get("request_form_cache_locked"):
        st.session_state["request_form_cache_data"] = data
    return data


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

    products = sort_request_products(
        list(cache_data.get("products") or [])
        + [str(item.get("product") or "") for item in rows if isinstance(item, dict)]
    )
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
        "languages": languages,
        "no_model_product_keys": {
            normalize_option_label(product) for product in list(cache_data.get("no_model_products") or [])
        },
        "no_language_product_keys": no_language_product_keys,
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
        return
    user = user_lookup.get(open_id)
    if not isinstance(user, dict):
        return
    department_ids = [
        str(value)
        for value in list(user.get("department_ids") or [])
        if str(value).strip()
    ]
    current_department_id = str(st.session_state.get("request_department_id") or "")
    if department_ids and current_department_id not in department_ids:
        st.session_state["request_department_id"] = department_ids[0]


def get_request_form_selection_context() -> dict[str, object]:
    state = request_form_cache_state()
    live_data = state.get("data") if isinstance(state.get("data"), dict) else None
    runtime_data = request_form_cache_from_runtime_page_data()
    static_data = load_static_request_form_cache()
    if "request_form_cache_data" not in st.session_state:
        st.session_state["request_form_cache_data"] = runtime_data or live_data or static_data
    elif (runtime_data or live_data) and not st.session_state.get("request_form_cache_locked"):
        next_data = runtime_data or live_data
        current_generated_at = str(st.session_state["request_form_cache_data"].get("generated_at") or "")
        live_generated_at = str(next_data.get("generated_at") or "")
        if live_generated_at and live_generated_at != current_generated_at:
            st.session_state["request_form_cache_data"] = next_data
    return request_form_cache_to_selection_context(dict(st.session_state["request_form_cache_data"]))


def get_restock_selection_context() -> dict[str, object]:
    state = request_form_cache_state()
    live_data = state.get("data") if isinstance(state.get("data"), dict) else None
    runtime_data = request_form_cache_from_runtime_page_data()
    static_data = load_static_request_form_cache()
    selected_data = runtime_data or live_data or static_data
    return request_form_cache_to_selection_context(dict(selected_data))


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
            if material_record_is_active(row)
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


def navigate_to_approval(key: str, label: str = "打开审批发放页") -> None:
    if st.button(label, key=key, icon=":material/fact_check:", width="stretch"):
        st.query_params["view"] = "approval"
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
        if section == "物料管理":
            st.session_state[MANAGEMENT_NAVIGATION_LOADING_KEY] = section
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


@st.cache_data(show_spinner=False)
def load_static_page_data_cache() -> dict[str, object]:
    if not PAGE_DATA_STATIC_CACHE_PATH.exists():
        return {"schema_version": 1, "generated_at": "", "tables": {}}
    data = json.loads(PAGE_DATA_STATIC_CACHE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        raise RuntimeError("页面静态缓存文件格式不正确。")
    return data


@st.cache_resource(show_spinner=False)
def page_data_runtime_cache() -> dict[str, object]:
    return {
        "lock": threading.Lock(),
        "tables": {},
        "updated_at": {},
    }


def page_data_cache_rows(table_name: str) -> list[dict]:
    runtime_cache = page_data_runtime_cache()
    runtime_lock = runtime_cache["lock"]
    with runtime_lock:  # type: ignore[union-attr]
        runtime_tables = dict(runtime_cache.get("tables") or {})
        if table_name in runtime_tables:
            return list(runtime_tables[table_name])
    static_tables = dict(load_static_page_data_cache().get("tables") or {})
    table_data = static_tables.get(table_name, [])
    if isinstance(table_data, dict):
        table_data = table_data.get("rows", [])
    return list(table_data) if isinstance(table_data, list) else []


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


def refresh_page_cache_tables(table_names: list[str] | tuple[str, ...]) -> dict[str, object]:
    normalized_names = unique_preserve([str(table_name) for table_name in table_names])
    refreshed_tables = {table_name: safe_fresh_feishu_rows(table_name) for table_name in normalized_names}
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
    if normalized_names and all(table_name in runtime_tables for table_name in normalized_names):
        timestamps = [str(runtime_updated_at.get(table_name) or "") for table_name in normalized_names]
        return "服务缓存已刷新", max(timestamps) if timestamps else ""
    static_cache = load_static_page_data_cache()
    return "部署静态缓存", str(static_cache.get("generated_at") or "")


def build_page_data_static_snapshot() -> dict[str, object]:
    tables = {table_name: safe_fresh_feishu_rows(table_name) for table_name in ALL_PAGE_CACHE_TABLES}
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


@st.cache_data(show_spinner=False)
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
    return json.loads(CONTACT_DEPARTMENT_STATIC_CACHE_PATH.read_text(encoding="utf-8"))


def get_contact_directory_cache() -> dict[str, object]:
    cached = st.session_state.get("contact_department_cache_data")
    if not isinstance(cached, dict):
        cached = load_static_contact_department_cache()
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
    if not all(table_name in runtime_tables for table_name in PAGE_CACHE_TABLES["request"]):
        return None
    return request_form_cache_from_inventory(
        load_feishu_options(),
        load_feishu_inventory(),
        source="shared_runtime_page_cache",
    )


def render_page_cache_toolbar(page_key: str) -> None:
    table_names = PAGE_CACHE_TABLES[page_key]
    message_key = f"page_cache_message_{page_key}"
    message = st.session_state.pop(message_key, "")
    if message:
        st.success(message)
    warning = st.session_state.pop("post_write_cache_warning", "")
    if warning:
        st.warning(warning)

    source, updated_at = page_cache_status(table_names)
    status_col, button_col = st.columns([5, 1.35], vertical_alignment="center")
    updated_text = updated_at or "未记录"
    status_col.caption(f"数据来源：{source}　更新时间：{updated_text}")
    if button_col.button(
        "刷新本页数据",
        key=f"refresh_page_cache_{page_key}",
        icon=":material/refresh:",
        width="stretch",
    ):
        with st.spinner("正在同步本页数据，请稍后......"):
            try:
                result = refresh_page_cache_tables(table_names)
                if page_key == "request":
                    refresh_request_form_cache_from_page_data()
                    refresh_contact_departments_from_feishu()
            except Exception as exc:
                st.error("本页数据刷新失败，请检查飞书连接和数据表权限。")
                st.exception(exc)
                return
        st.session_state[message_key] = (
            f"本页数据已刷新，共同步 {result['row_count']} 条记录。"
        )
        st.rerun()


def fetch_approval_live_data() -> dict[str, object]:
    request_rows = fresh_feishu_rows(REQUEST_TABLE_NAME)
    line_rows = fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    model_rows = fresh_feishu_rows(MODEL_TABLE_NAME)
    return {
        "request_rows": request_rows,
        "line_rows": line_rows,
        "material_rows": material_rows,
        "category_rows": category_rows,
        "model_rows": model_rows,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "row_count": (
            len(request_rows)
            + len(line_rows)
            + len(material_rows)
            + len(category_rows)
            + len(model_rows)
        ),
    }


def render_approval_live_toolbar(*, refresh_on_open: bool) -> dict[str, object]:
    message = st.session_state.pop("approval_live_refresh_message", "")
    if message:
        st.success(message)
    warning = st.session_state.pop("post_write_cache_warning", "")
    if warning:
        st.warning(warning)

    live_data = st.session_state.get(APPROVAL_LIVE_DATA_KEY)
    if refresh_on_open or not isinstance(live_data, dict):
        with st.spinner("正在读取飞书审批数据，请稍后......"):
            live_data = fetch_approval_live_data()
        st.session_state[APPROVAL_LIVE_DATA_KEY] = live_data

    status_col, button_col = st.columns([5, 1.35], vertical_alignment="center")
    status_col.caption(
        "数据来源：飞书实时数据　更新时间："
        f"{str(live_data.get('updated_at') or '未记录')}"
    )
    if button_col.button(
        "刷新实时数据",
        key="refresh_approval_live_data",
        icon=":material/refresh:",
        width="stretch",
    ):
        with st.spinner("正在重新读取飞书审批数据，请稍后......"):
            live_data = fetch_approval_live_data()
        st.session_state[APPROVAL_LIVE_DATA_KEY] = live_data
        st.session_state["approval_live_refresh_message"] = (
            f"审批数据已刷新，共读取 {int(live_data.get('row_count') or 0)} 条记录。"
        )
        st.rerun()
    return live_data


def refresh_page_cache_after_write(page_key: str, *, update_request_form: bool = False) -> None:
    try:
        refresh_page_cache_tables(PAGE_CACHE_TABLES[page_key])
        if update_request_form:
            refresh_request_form_cache_from_page_data()
    except Exception as exc:
        st.session_state["post_write_cache_warning"] = (
            f"业务数据已保存，但页面缓存刷新失败：{exc}。请点击“刷新本页数据”重试。"
        )


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
        status = normalize_enabled_status(feishu_text(fields, "启用状态"))
        zero_since_raw = feishu_text(fields, INVENTORY_ZERO_SINCE_FIELD).strip()
        zero_since = inventory_maintenance_datetime(zero_since_raw)
        latest_change = latest_changes.get(record_id)
        update_fields: dict[str, object] = {}

        if quantity != 0:
            if status != STATUS_ACTIVE:
                update_fields["启用状态"] = STATUS_ACTIVE
                enabled_rows.append(inventory_status_row_summary(row))
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

            if status == STATUS_ACTIVE and anchor < cutoff:
                update_fields["启用状态"] = STATUS_INACTIVE
                disabled_rows.append(inventory_status_row_summary(row, zero_since=anchor))

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


def feishu_inventory_dataframe_from_rows(rows: list[dict]) -> pd.DataFrame:
    data: list[list[object]] = []
    for row in rows:
        fields = feishu_fields(row)
        material_code = feishu_text(fields, "物料编码")
        category = feishu_text(fields, "物料品类")
        if not material_code or not category:
            continue
        if normalize_enabled_status(feishu_text(fields, "启用状态")) != STATUS_ACTIVE:
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


def load_feishu_inventory() -> pd.DataFrame:
    return feishu_inventory_dataframe_from_rows(feishu_rows(MATERIAL_TABLE_NAME))


def feishu_options_from_rows(
    categories: list[dict],
    inventory_df: pd.DataFrame,
    model_rows: list[dict] | None = None,
    language_rows: list[dict] | None = None,
) -> dict:
    category_products: list[str] = []
    category_status_by_product: dict[str, str] = {}
    no_model_products: list[str] = []
    no_language_products: list[str] = []
    configured_language_products: list[str] = []
    for row in categories:
        fields = feishu_fields(row)
        product = feishu_text(fields, "物料品类")
        category_status = normalize_enabled_status(feishu_text(fields, "启用状态"))
        if product:
            category_status_by_product[product] = category_status
        if category_status != STATUS_ACTIVE:
            continue
        if product:
            category_products.append(product)
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
    dimension_models = [
        feishu_text(feishu_fields(row), "产品型号")
        for row in list(model_rows or [])
        if normalize_enabled_status(feishu_text(feishu_fields(row), "启用状态")) == STATUS_ACTIVE
    ]
    models = sort_models(dimension_models or inventory_models)
    inventory_languages = (
        unique_preserve(list(inventory_df[LANGUAGE_COL].astype(str)))
        if not inventory_df.empty
        else []
    )
    dimension_languages = [
        feishu_language_name(feishu_fields(row))
        for row in list(language_rows or [])
        if normalize_enabled_status(feishu_text(feishu_fields(row), "启用状态")) == STATUS_ACTIVE
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
        "languages": languages,
        "no_model_text": NO_MODEL_TEXT,
        "no_language_text": NO_LANGUAGE_TEXT,
        "row_count": len(inventory_df),
    }


@st.cache_data(show_spinner=False, ttl=DATA_CACHE_TTL_SECONDS)
def load_feishu_options_snapshot(app_id: str, app_secret: str, app_token: str) -> dict:
    return feishu_options_from_rows(
        load_feishu_rows_snapshot(CATEGORY_TABLE_NAME, app_id, app_secret, app_token),
        load_feishu_inventory_snapshot(app_id, app_secret, app_token),
        load_feishu_rows_snapshot(MODEL_TABLE_NAME, app_id, app_secret, app_token),
        page_data_cache_rows(LANGUAGE_TABLE_NAME),
    )


def load_feishu_options() -> dict:
    return feishu_options_from_rows(
        safe_feishu_rows(CATEGORY_TABLE_NAME),
        load_feishu_inventory(),
        safe_feishu_rows(MODEL_TABLE_NAME),
        safe_feishu_rows(LANGUAGE_TABLE_NAME),
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
    if not str(draft.get("operator") or "").strip():
        errors.append("请填写补库人")
    lines = [line for line in list(draft.get("lines") or []) if isinstance(line, dict)]
    if not lines:
        errors.append("请至少加入一种补库物料")
        return errors
    if len(lines) > MAX_REQUEST_LINE_COUNT:
        errors.append(f"一次补库最多可添加 {MAX_REQUEST_LINE_COUNT} 种物料")
    seen: set[tuple[str, str, str]] = set()
    for index, line in enumerate(lines, start=1):
        key = request_material_key(line)
        if not all(key):
            errors.append(f"第 {index} 条补库明细缺少品类、型号或语种")
        if int(line.get("quantity") or 0) <= 0:
            errors.append(f"第 {index} 条补库数量必须大于 0")
        if key in seen:
            errors.append(f"第 {index} 条补库物料重复，请合并数量")
        seen.add(key)
    return errors


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
    active_records = feishu_inventory_records_from_rows(
        material_rows,
        category_rows,
        active_only=True,
    )
    active_by_key = {
        (
            str(record.get("category") or ""),
            str(record.get("model") or NO_MODEL_TEXT),
            str(record.get("language") or NO_LANGUAGE_TEXT),
        ): record
        for record in active_records
    }
    restock_no = str(draft.get("restock_no") or "").strip()
    operator = str(draft.get("operator") or "").strip()
    purchase_order_no = str(draft.get("purchase_order_no") or "").strip()
    overall_note = str(draft.get("note") or "").strip()
    submission_token = str(draft.get("submission_token") or "").strip() or uuid.uuid4().hex
    occurred_at = datetime.now()
    prepared: list[dict[str, object]] = []
    for index, line in enumerate(list(draft.get("lines") or []), start=1):
        if not isinstance(line, dict):
            continue
        product, model, language = request_material_key(line)
        record = active_by_key.get((product, model, language))
        if record is None:
            raise RuntimeError(f"补库物料不存在或已停用：{product} / {model} / {language}")
        record_id = str(record.get("record_id") or "")
        raw_row = raw_material_by_id.get(record_id, {})
        before_quantity = feishu_int(feishu_fields(raw_row), "当前库存")
        quantity = int(line.get("quantity") or 0)
        after_quantity = before_quantity + quantity
        line_note = str(line.get("remark") or "").strip()
        note_parts = [f"补库单 {restock_no}", f"补库人：{operator}"]
        if purchase_order_no:
            note_parts.append(f"采购单号：{purchase_order_no}")
        if overall_note:
            note_parts.append(f"补库说明：{overall_note}")
        if line_note:
            note_parts.append(f"明细备注：{line_note}")
        prepared.append(
            {
                "record_id": record_id,
                "material_code": str(record.get("material_code") or ""),
                "product": product,
                "model": model,
                "language": language,
                "quantity": quantity,
                "before_quantity": before_quantity,
                "after_quantity": after_quantity,
                "remark": line_note,
                "ledger_note": "；".join(note_parts),
                "idempotency_key": f"restock:{submission_token}:{index}",
            }
        )

    inventory_updates = [
        {
            "record_id": str(item["record_id"]),
            "fields": {"当前库存": int(item["after_quantity"])},
        }
        for item in prepared
    ]
    rollback_updates = [
        {
            "record_id": str(item["record_id"]),
            "fields": {"当前库存": int(item["before_quantity"])},
        }
        for item in prepared
    ]
    ledger_fields = [
        build_feishu_ledger_fields(
            str(item["record_id"]),
            ACTION_PURCHASE,
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


def request_note_text(request_payload: dict[str, object], attachment_note: str = "") -> str:
    parts = [
        ("客户名称", request_payload.get("customer_name")),
        ("国家", request_payload.get("country")),
        ("收件人信息", request_payload.get("recipient_info")),
        ("运费承担者", request_payload.get("freight_payer")),
        ("物料用途", request_payload.get("material_usage")),
        ("申请人", request_payload.get("requester")),
        ("相关附件", attachment_note),
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


def enabled_admin_open_ids() -> list[str]:
    return enabled_role_open_ids("管理员")


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


def material_approval_url() -> str:
    base_url = get_secret_value("STREAMLIT_APP_URL", DEFAULT_STREAMLIT_APP_URL).strip()
    return f"{base_url.rstrip('/')}/?view=approval"


def material_request_notification_text(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> str:
    valid_lines = [line for line in lines if int(line.get("quantity") or 0) > 0]
    total_quantity = sum(int(line.get("quantity") or 0) for line in valid_lines)
    details = [
        (
            f"{index}. {str(line.get('product') or '-')} / "
            f"{str(line.get('model') or NO_MODEL_TEXT)} / "
            f"{str(line.get('language') or NO_LANGUAGE_TEXT)} × {int(line.get('quantity') or 0)}"
        )
        for index, line in enumerate(valid_lines, start=1)
    ]
    parts = [
        "【新的营销物料申请待处理】",
        f"申请单号：{request_no}",
        f"申请人：{str(request_payload.get('requester') or '-')}",
        f"申请部门：{str(request_payload.get('department') or '-')}",
        f"客户/国家：{str(request_payload.get('customer_name') or '-')} / {str(request_payload.get('country') or '-')}",
        f"物料用途：{str(request_payload.get('material_usage') or '-')}",
        f"申请合计：{len(valid_lines)} 种，共 {total_quantity} 件",
        "",
        *details,
        "",
        "请打开审批与发放页面处理：",
        material_approval_url(),
    ]
    return "\n".join(parts)


def _feishu_card_plain_text(value: object, *, max_length: int = 1600) -> str:
    text = str(value or "-").strip() or "-"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[:max_length]


def material_request_notification_card(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    valid_lines = [line for line in lines if int(line.get("quantity") or 0) > 0]
    total_quantity = sum(int(line.get("quantity") or 0) for line in valid_lines)
    attachments = list(request_payload.get("attachments") or [])
    attachment_names = [
        _feishu_card_plain_text(
            attachment.get("name") if isinstance(attachment, dict) else attachment,
            max_length=200,
        )
        for attachment in attachments
    ]

    def short_field(label: str, value: object) -> dict[str, object]:
        return {
            "is_short": True,
            "text": {
                "tag": "plain_text",
                "content": f"{label}\n{_feishu_card_plain_text(value, max_length=500)}",
            },
        }

    elements: list[dict[str, object]] = [
        {"tag": "markdown", "content": "**申请信息**"},
        {
            "tag": "div",
            "fields": [
                short_field("申请单号", request_no),
                short_field("申请人", request_payload.get("requester")),
                short_field("申请部门", request_payload.get("department")),
                short_field("标题", request_payload.get("title")),
                short_field("客户名称", request_payload.get("customer_name")),
                short_field("国家", request_payload.get("country")),
                short_field("运费承担者", request_payload.get("freight_payer")),
                short_field("申请合计", f"{len(valid_lines)} 种，共 {total_quantity} 件"),
            ],
        },
        {"tag": "hr"},
        {"tag": "markdown", "content": "**收件人信息**"},
        {
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": _feishu_card_plain_text(request_payload.get("recipient_info")),
            },
        },
        {"tag": "markdown", "content": "**物料用途**"},
        {
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": _feishu_card_plain_text(request_payload.get("material_usage")),
            },
        },
    ]
    if attachment_names:
        elements.extend(
            [
                {"tag": "markdown", "content": "**相关附件**"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": "、".join(attachment_names),
                    },
                },
            ]
        )

    elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": "**物料明细**"}])
    for index, line in enumerate(valid_lines, start=1):
        detail = (
            f"{index:02d}. {_feishu_card_plain_text(line.get('product'), max_length=300)} / "
            f"{_feishu_card_plain_text(line.get('model') or NO_MODEL_TEXT, max_length=200)} / "
            f"{_feishu_card_plain_text(line.get('language') or NO_LANGUAGE_TEXT, max_length=200)} "
            f"× {int(line.get('quantity') or 0)}"
        )
        remark = str(line.get("remark") or "").strip()
        if remark:
            detail += f"\n备注：{_feishu_card_plain_text(remark, max_length=500)}"
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "plain_text", "content": detail},
            }
        )

    elements.extend(
        [
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开审批与发放"},
                        "type": "primary",
                        "url": material_approval_url(),
                    }
                ],
            },
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text", "content": "新的营销物料申请待处理"},
        },
        "elements": elements,
    }


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
    return _send_feishu_message_compat(
        client,
        receive_id,
        "interactive",
        card,
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
    card = material_request_notification_card(request_no, request_payload, lines)
    for open_id in recipients:
        send_feishu_interactive_message(client, open_id, card)
    return len(recipients)


def material_restock_notification_card(
    draft: dict[str, object],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    total_quantity = sum(int(line.get("quantity") or 0) for line in lines)

    def short_field(label: str, value: object) -> dict[str, object]:
        return {
            "is_short": True,
            "text": {
                "tag": "plain_text",
                "content": f"{label}\n{_feishu_card_plain_text(value, max_length=500)}",
            },
        }

    elements: list[dict[str, object]] = [
        {"tag": "markdown", "content": "**补库信息**"},
        {
            "tag": "div",
            "fields": [
                short_field("补库单号", draft.get("restock_no")),
                short_field("补库人", draft.get("operator")),
                short_field("采购单号", draft.get("purchase_order_no") or "-"),
                short_field("补库合计", f"{len(lines)} 种，共 {total_quantity} 件"),
            ],
        },
    ]
    note = str(draft.get("note") or "").strip()
    if note:
        elements.extend(
            [
                {"tag": "markdown", "content": "**补库说明**"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": _feishu_card_plain_text(note),
                    },
                },
            ]
        )
    elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": "**补库明细**"}])
    for index, line in enumerate(lines, start=1):
        detail = (
            f"{index:02d}. {_feishu_card_plain_text(line.get('product'), max_length=300)} / "
            f"{_feishu_card_plain_text(line.get('model') or NO_MODEL_TEXT, max_length=200)} / "
            f"{_feishu_card_plain_text(line.get('language') or NO_LANGUAGE_TEXT, max_length=200)}\n"
            f"补库 {int(line.get('quantity') or 0)}，库存 "
            f"{int(line.get('before_quantity') or 0)} → {int(line.get('after_quantity') or 0)}"
        )
        remark = str(line.get("remark") or "").strip()
        if remark:
            detail += f"\n备注：{_feishu_card_plain_text(remark, max_length=500)}"
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "plain_text", "content": detail},
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text", "content": "采购补库已完成"},
        },
        "elements": elements,
    }


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
    for open_id in recipients:
        send_feishu_interactive_message(client, open_id, card)
    return len(recipients)


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
        action = "新增" if before is None else ("修改" if (
            before_quantity != after_quantity
            or before_unit_price != after_unit_price
            or before_customs_code != after_customs_code
            or before_status != after_status
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
                "状态变化": f"{normalize_enabled_status(before.get('status'))} → 移除", "海关编码变化": "-",
            })
    return rows


def category_edit_notification_card(
    draft: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    rows = category_edit_change_rows(draft)
    changed_rows = [row for row in rows if row["操作"] != "保留"]
    elements: list[dict[str, object]] = [{
        "tag": "markdown",
        "content": (
            f"**品类：** {_feishu_card_plain_text(draft.get('old_product'))} → "
            f"{_feishu_card_plain_text(draft.get('product'))}\n"
            f"**修改时间：** {_feishu_card_plain_text(draft.get('edited_at'))}\n"
            f"**结果：** 目标组合 {int(result.get('target_count') or 0)} 条，"
            f"新增 {int(result.get('created_count') or 0)} 条，移除 {int(result.get('deleted_count') or 0)} 条，"
            f"库存差额 {int(result.get('quantity_difference') or 0):+,}"
        ),
    }, {"tag": "hr"}, {"tag": "markdown", "content": "**编辑修改明细**"}]
    for index, row in enumerate(changed_rows[:40], start=1):
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": (
            f"{index:02d}. [{row['操作']}] {row['产品型号']} / {row['语种']}\n"
            f"库存：{row['库存变化']}；单价：{row['单价变化']}；状态：{row['状态变化']}；"
            f"海关编码：{row['海关编码变化']}"
        )}})
    if not changed_rows:
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": "库存组合明细无字段变化。"}})
    if len(changed_rows) > 40:
        elements.append({"tag": "markdown", "content": f"另有 **{len(changed_rows) - 40}** 条修改，请在品类管理中查看。"})
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": "物料品类编辑已完成"}},
        "elements": elements,
    }


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
    for open_id in recipients:
        send_feishu_interactive_message(client, open_id, card)
    return len(recipients)


def category_create_notification_card(
    draft: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    targets = [
        target
        for target in list(result.get("targets") or [])
        if isinstance(target, dict)
    ]
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": (
                f"**物料品类：** {_feishu_card_plain_text(draft.get('product'))}\n"
                f"**创建时间：** {_feishu_card_plain_text(draft.get('created_at'))}\n"
                f"**品类状态：** {_feishu_card_plain_text(draft.get('category_status'))}\n"
                f"**创建结果：** 库存组合 {int(result.get('target_count') or 0)} 条，"
                f"型号 {len(list(result.get('models') or []))} 个，"
                f"语种 {len(list(result.get('languages') or []))} 个，"
                f"初始库存 {int(result.get('target_quantity') or 0):,} 件"
            ),
        },
        {"tag": "hr"},
        {"tag": "markdown", "content": "**新增库存组合明细**"},
    ]
    for index, target in enumerate(targets[:40], start=1):
        elements.append({
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": (
                    f"{index:02d}. {_feishu_card_plain_text(target.get('model') or NO_MODEL_TEXT)} / "
                    f"{_feishu_card_plain_text(target.get('language') or NO_LANGUAGE_TEXT)}\n"
                    f"库存：{int(target.get('quantity') or 0)}；"
                    f"单价：{float(target.get('unit_price') or 0):g}；"
                    f"状态：{_feishu_card_plain_text(target.get('status'))}；"
                    f"海关编码：{_feishu_card_plain_text(target.get('customs_code'))}"
                ),
            },
        })
    if len(targets) > 40:
        elements.append({
            "tag": "markdown",
            "content": f"另有 **{len(targets) - 40}** 条新增组合，请在品类管理中查看。",
        })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text", "content": "新物料品类已创建"},
        },
        "elements": elements,
    }


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
    for open_id in recipients:
        send_feishu_interactive_message(client, open_id, card)
    return len(recipients)


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
    for index, row in enumerate(visible_rows, start=1):
        detail = (
            f"{index:02d}. {_feishu_card_plain_text(row.get('material_code'), max_length=100)} | "
            f"{_feishu_card_plain_text(row.get('product'), max_length=250)} / "
            f"{_feishu_card_plain_text(row.get('model') or NO_MODEL_TEXT, max_length=160)} / "
            f"{_feishu_card_plain_text(row.get('language') or NO_LANGUAGE_TEXT, max_length=160)}\n"
            f"库存：0；归零计时：{_feishu_card_plain_text(row.get('zero_since'), max_length=100)}"
        )
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "plain_text", "content": detail},
            }
        )
    if len(rows) > len(visible_rows):
        elements.append(
            {
                "tag": "markdown",
                "content": f"另有 **{len(rows) - len(visible_rows)}** 条，请在物料主数据中查看。",
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red",
            "title": {"tag": "plain_text", "content": "零库存行已自动停用"},
        },
        "elements": elements,
    }


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
    total_quantity = sum(int(line.get("quantity") or 0) for line in valid_lines)
    if english:
        return "\n".join(
            [
                "Your marketing material request is now being processed.",
                f"Request No.: {request_no}",
                f"Applicant: {str(request_payload.get('requester') or '-')}",
                f"Purpose: {str(request_payload.get('material_usage') or '-')}",
                f"Total requested: {len(valid_lines)} item types, {total_quantity} units",
                "",
                "The administrators have received your request. Please wait for the approval and issuance result.",
            ]
        )
    return "\n".join(
        [
            "【营销物料申请已进入处理流程】",
            f"申请单号：{request_no}",
            f"申请人：{str(request_payload.get('requester') or '-')}",
            f"物料用途：{str(request_payload.get('material_usage') or '-')}",
            f"申请合计：{len(valid_lines)} 种，共 {total_quantity} 件",
            "",
            "管理员已收到申请，请等待审批与发放结果。",
        ]
    )


def sales_request_received_notification_card(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    english = requester_prefers_english(request_payload)
    action_text = "Modify or withdraw this request" if english else "修改或撤回本条申请"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": (
                    "Material Request Received"
                    if english
                    else "营销物料申请已进入处理流程"
                ),
            },
        },
        "elements": [
            {
                "tag": "markdown",
                "content": sales_request_received_notification_text(
                    request_no, request_payload, lines, english=english
                ),
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": action_text},
                        "type": "primary",
                        "value": {
                            "action": "open_request_editor",
                            "request_no": request_no,
                            "language": "en" if english else "zh",
                        },
                    }
                ],
            },
        ],
    }


def notify_sales_request_received(
    request_no: str,
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> int:
    requester_open_id = str(request_payload.get("requester_open_id") or "").strip()
    if not requester_open_id or requester_open_id not in set(enabled_sales_open_ids()):
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


def sales_request_completed_notification_text(
    request: dict[str, object],
    lines: list[dict[str, object]],
    note: str,
    *,
    english: bool = False,
) -> str:
    status = str(request.get("status") or REQUEST_STATUS_ISSUED)
    details: list[str] = []
    for index, line in enumerate(lines, start=1):
        label = english_material_notification_label if english else lambda value: str(value or "-")
        requested_material = (
            f"{label(line.get('product'))} / "
            f"{label(line.get('model') or NO_MODEL_TEXT)} / "
            f"{label(line.get('language') or NO_LANGUAGE_TEXT)}"
        )
        actual_material = (
            f"{label(line.get('actual_product') or line.get('product'))} / "
            f"{label(line.get('actual_model') or line.get('model') or NO_MODEL_TEXT)} / "
            f"{label(line.get('actual_language') or line.get('language') or NO_LANGUAGE_TEXT)}"
        )
        requested_quantity = int(line.get("quantity") or 0)
        actual_quantity = int(line.get("actual_issue_qty") or 0)
        if requested_material == actual_material:
            details.append((
                f"{index}. {requested_material}: requested {requested_quantity}, issued {actual_quantity}"
                if english else
                f"{index}. {requested_material}：申请 {requested_quantity}，实际发放 {actual_quantity}"
            ))
        else:
            details.append((
                f"{index}. Requested: {requested_material} × {requested_quantity}\n"
                f"   Issued: {actual_material} × {actual_quantity}"
                if english else
                f"{index}. 申请：{requested_material} × {requested_quantity}\n"
                f"   实际发放：{actual_material} × {actual_quantity}"
            ))
    if english:
        parts = [
            "Your marketing material request has been processed.",
            f"Request No.: {str(request.get('request_no') or '-')}",
            f"Result: {translate_ui_text(status, LANGUAGE_EN)}",
            "",
            *details,
        ]
    else:
        parts = [
            "【营销物料申请审批已完成】",
            f"申请单号：{str(request.get('request_no') or '-')}",
            f"审批结果：{status}",
            "",
            *details,
        ]
    if note.strip():
        parts.extend(["", f"Approval / issuance note: {note.strip()}" if english else f"审批/发放备注：{note.strip()}"])
    return "\n".join(parts)


def sales_request_completed_notification_card(
    request: dict[str, object],
    lines: list[dict[str, object]],
    note: str,
) -> dict[str, object]:
    english = requester_prefers_english(request)
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {
                "tag": "plain_text",
                "content": (
                    "Material Request Completed"
                    if english
                    else "营销物料申请审批已完成"
                ),
            },
        },
        "elements": [{
            "tag": "markdown",
            "content": sales_request_completed_notification_text(
                request, lines, note, english=english
            ),
        }],
    }


def notify_sales_request_completed(
    request: dict[str, object],
    lines: list[dict[str, object]],
    note: str,
) -> int:
    requester_open_id = str(request.get("requester_open_id") or "").strip()
    if not requester_open_id or requester_open_id not in set(enabled_sales_open_ids()):
        return 0
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法发送销售审批反馈。")
    send_feishu_interactive_message(
        client,
        requester_open_id,
        sales_request_completed_notification_card(request, lines, note),
    )
    return 1


def submit_feishu_material_request(
    request_payload: dict[str, object],
    lines: list[dict[str, object]],
) -> tuple[str, int, bool]:
    refresh_feishu_schema_cache()
    valid_lines = [item for item in lines if int(item.get("quantity") or 0) > 0]
    if not valid_lines:
        raise RuntimeError("请至少填写一条数量大于 0 的物料明细。")
    if len(valid_lines) > MAX_REQUEST_LINE_COUNT:
        raise RuntimeError(f"一次申请最多可提交 {MAX_REQUEST_LINE_COUNT} 条物料明细。")
    submission_token = str(request_payload.get("submission_token") or "").strip()
    existing_submission = find_completed_submission(submission_token)
    if existing_submission is not None:
        existing_row, existing_line_count = existing_submission
        return feishu_text(feishu_fields(existing_row), "申请单号"), existing_line_count, False

    material_rows = feishu_material_rows()
    raw_material_by_id = {feishu_record_id(row): row for row in material_rows}
    material_index = {
        (str(record["category"]), str(record["model"]), str(record["language"])): raw_material_by_id[
            str(record["record_id"])
        ]
        for record in feishu_inventory_records_from_rows(
            material_rows,
            feishu_category_rows(),
            active_only=True,
        )
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

    now = datetime.now()
    material_usage = str(request_payload.get("material_usage") or "").strip()
    attachments = list(request_payload.get("attachments") or [])
    attachment_values: list[dict[str, str]] = []
    if attachments:
        if not feishu_has_field(REQUEST_TABLE_NAME, "相关附件"):
            raise RuntimeError("物料申请单缺少“相关附件”附件字段。")
        if feishu_field_type(REQUEST_TABLE_NAME, "相关附件") != 17:
            raise RuntimeError("物料申请单的“相关附件”必须是附件类型字段。")
        client = feishu_client()
        if client is None:
            raise RuntimeError("飞书未配置，无法上传附件。")
        for attachment in attachments:
            file_token = client.upload_media(
                str(attachment.get("name") or ""),
                bytes(attachment.get("content") or b""),
                str(attachment.get("content_type") or "application/octet-stream"),
            )
            attachment_values.append({"file_token": file_token})

    request_no = next_request_no()
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
    if attachment_values:
        request_fields["相关附件"] = attachment_values
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
    set_first_plain_field(REQUEST_TABLE_NAME, request_fields, ["附件说明", "相关附件说明"], request_payload.get("attachment_note"))

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
            "审批通过数量": int(item["quantity"]),
            "实际发放数量": 0,
            "明细状态": REQUEST_LINE_STATUS_PENDING,
            "备注": item["remark"],
        }
        set_first_plain_field(REQUEST_LINE_TABLE_NAME, line_fields, ["申请单号"], request_no)
        set_request_line_material_fields(
            line_fields,
            material_index[(str(item["product"]), str(item["model"]), str(item["language"]))],
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
                "status": feishu_text(fields, "审批状态"),
                "submitted_at": feishu_datetime_text(fields.get("提交时间", "")),
                "approved_at": feishu_datetime_text(fields.get("审批时间", "")),
                "approval_comment": feishu_text(fields, "审批意见"),
            }
        )
    records.sort(key=lambda item: str(item["request_no"]), reverse=True)
    return records


def load_feishu_request_line_records(
    rows: list[dict] | None = None,
    material_rows: list[dict] | None = None,
) -> list[dict[str, object]]:
    source_material_rows = material_rows if material_rows is not None else feishu_material_rows()
    material_by_id = {feishu_record_id(row): row for row in source_material_rows}
    records: list[dict[str, object]] = []
    source_rows = rows if rows is not None else feishu_rows(REQUEST_LINE_TABLE_NAME)
    for row in source_rows:
        fields = feishu_fields(row)
        request_ids = feishu_link_ids_any(fields, ["所属申请单", "申请单"])
        material_ids = feishu_link_ids_any(fields, ["物料", "物料编码"])
        material_row = material_by_id.get(material_ids[0], {}) if material_ids else {}
        material_fields = feishu_fields(material_row)
        product = feishu_text(fields, "物料品类") or feishu_text(material_fields, "物料品类")
        model = feishu_text(fields, "产品型号") or feishu_text(material_fields, "产品型号") or NO_MODEL_TEXT
        language = feishu_text(fields, "语种") or feishu_text(material_fields, "语种")
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
                "request_ids": request_ids,
                "request_no": feishu_text_any(fields, ["申请单号", "所属申请单", "申请单"]),
                "material_record_id": material_ids[0] if material_ids else "",
                "product": product,
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
                "current_stock": feishu_int(material_fields, "当前库存"),
                "approved_qty": approved_qty,
                "actual_issue_qty": actual_qty,
                "status": feishu_text(fields, "明细状态") or REQUEST_LINE_STATUS_PENDING,
            }
        )
    return records


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


def issue_request_lines(
    request: dict[str, object],
    edited_lines: list[dict[str, object]],
    note: str,
) -> list[list[object]]:
    client = feishu_client()
    if client is None:
        return []
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    category_rows = fresh_feishu_rows(CATEGORY_TABLE_NAME)
    raw_material_by_id = {feishu_record_id(row): row for row in material_rows}
    active_material_records = feishu_inventory_records_from_rows(
        material_rows,
        category_rows,
        active_only=True,
    )
    inventory_index = {
        (str(record["category"]), str(record["model"]), str(record["language"])): raw_material_by_id[
            str(record["record_id"])
        ]
        for record in active_material_records
    }
    logs: list[list[object]] = []
    now = datetime.now()
    request_record_id = str(request["record_id"])
    request_no = str(request["request_no"])

    if not edited_lines or not any(int(line.get("actual_issue_qty") or 0) > 0 for line in edited_lines):
        raise RuntimeError("请至少填写一条大于 0 的实际发放数量。")

    for line in edited_lines:
        actual_qty = int(line.get("actual_issue_qty") or 0)
        previous_actual_qty = int(line.get("previous_actual_issue_qty") or 0)
        if actual_qty < previous_actual_qty:
            raise RuntimeError(f"{line['product']} / {line['model']} / {line['language']} 实际发放数量不能小于已记录数量。")
        material_key = (
            str(line.get("product") or "").strip(),
            str(line.get("model") or NO_MODEL_TEXT).strip() or NO_MODEL_TEXT,
            str(line.get("language") or "").strip(),
        )
        material_row = inventory_index.get(material_key)
        if material_row is None:
            raise RuntimeError(f"未找到启用的物料组合：{' / '.join(material_key)}")
        next_material_id = feishu_record_id(material_row)
        previous_material_key = (
            str(line.get("previous_product") or line.get("product") or "").strip(),
            str(line.get("previous_model") or line.get("model") or NO_MODEL_TEXT).strip() or NO_MODEL_TEXT,
            str(line.get("previous_language") or line.get("language") or "").strip(),
        )
        if previous_actual_qty > 0 and previous_material_key != material_key:
            raise RuntimeError("已经发生部分发放的明细不能再更换物料组合，请新建申请明细处理。")
        line["resolved_material_row"] = material_row
        line["material_record_id"] = next_material_id

    for line in edited_lines:
        actual_qty = int(line.get("actual_issue_qty") or 0)
        requested_qty = int(line.get("quantity") or 0)
        if str(line.get("status")) == REQUEST_LINE_STATUS_ISSUED:
            continue
        previous_actual_qty = int(line.get("previous_actual_issue_qty") or 0)
        issue_delta = actual_qty - previous_actual_qty
        material_row = dict(line["resolved_material_row"])
        material_record_id = feishu_record_id(material_row)
        if issue_delta > 0:
            material_fields = feishu_fields(material_row)
            before_quantity = feishu_int(material_fields, "当前库存")
            after_quantity = before_quantity - issue_delta

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

        line_status = REQUEST_LINE_STATUS_ISSUED if actual_qty >= requested_qty else REQUEST_LINE_STATUS_PARTIAL
        line_update_fields: dict[str, object] = {
            "实际发放数量": actual_qty,
            "审批通过数量": actual_qty,
            "明细状态": line_status,
            "发放时间": feishu_datetime_value(REQUEST_LINE_TABLE_NAME, "发放时间", now),
            "缺货说明": note.strip() if actual_qty < requested_qty else "",
        }
        set_first_plain_field(
            REQUEST_LINE_TABLE_NAME,
            line_update_fields,
            ["实际发放物料品类"],
            str(line["product"]),
        )
        set_first_plain_field(
            REQUEST_LINE_TABLE_NAME,
            line_update_fields,
            ["实际发放产品型号"],
            str(line["model"]),
        )
        set_first_plain_field(
            REQUEST_LINE_TABLE_NAME,
            line_update_fields,
            ["实际发放语种"],
            str(line["language"]),
        )
        set_first_plain_field(
            REQUEST_LINE_TABLE_NAME,
            line_update_fields,
            ["实际发放物料编码"],
            feishu_text(feishu_fields(material_row), "物料编码"),
        )
        feishu_update_record_fields(
            REQUEST_LINE_TABLE_NAME,
            str(line["record_id"]),
            line_update_fields,
        )

    all_line_ids = {str(line["record_id"]) for line in edited_lines}
    fully_issued_ids = {
        str(line["record_id"])
        for line in edited_lines
        if int(line.get("actual_issue_qty") or 0) >= int(line.get("quantity") or 0)
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


def parse_feishu_inventory_record(row: dict) -> dict | None:
    fields = feishu_fields(row)
    if not fields:
        return None
    material_code = feishu_text(fields, "物料编码")
    category = feishu_text(fields, "物料品类")
    if not material_code or not category:
        return None
    quantity = feishu_int(fields, "当前库存")
    unit_price = feishu_float_any(fields, list(UNIT_PRICE_FIELD_CANDIDATES))
    return {
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
        "status": normalize_enabled_status(feishu_text(fields, "启用状态")),
    }


def feishu_inventory_records_from_rows(
    material_rows: list[dict],
    category_rows: list[dict] | None = None,
    *,
    active_only: bool = False,
) -> list[dict]:
    records = [
        parsed
        for row in material_rows
        if (parsed := parse_feishu_inventory_record(row)) is not None
    ]
    if active_only:
        category_status_by_name = {
            feishu_text(feishu_fields(row), "物料品类"): normalize_enabled_status(
                feishu_text(feishu_fields(row), "启用状态")
            )
            for row in list(category_rows or [])
            if feishu_text(feishu_fields(row), "物料品类")
        }
        records = [
            record
            for record in records
            if material_record_is_active(record)
            and category_status_by_name.get(str(record["category"]), STATUS_ACTIVE) == STATUS_ACTIVE
        ]
    records.sort(key=lambda item: (item["category"], item["model"], item["language"], item["material_code"]))
    return records


def load_feishu_inventory_records(*, active_only: bool = False) -> list[dict]:
    return feishu_inventory_records_from_rows(
        feishu_material_rows(),
        feishu_category_rows(),
        active_only=active_only,
    )


def load_feishu_category_records() -> list[dict]:
    records: list[dict] = []
    for row in feishu_category_rows():
        fields = feishu_fields(row)
        product = feishu_text(fields, "物料品类")
        if not product:
            continue
        unit_price_text = feishu_text_any(fields, list(UNIT_PRICE_FIELD_CANDIDATES))
        records.append(
            {
                "record_id": feishu_record_id(row),
                "category": product,
                "no_model": feishu_text(fields, "是否无需型号") == "是",
                "no_language": feishu_text(fields, "是否无需语种") == "是"
                or (
                    not feishu_text(fields, "是否无需语种")
                    and is_default_no_language_product(product)
                ),
                "status": normalize_enabled_status(feishu_text(fields, "启用状态")),
                "unit_price": parse_optional_unit_price(unit_price_text),
                "customs_code": feishu_text(fields, "海关编码"),
                "created_at": feishu_text(fields, "创建时间"),
                "remark": feishu_text(fields, "备注"),
            }
        )
    records.sort(key=lambda item: item["category"])
    return records


def build_category_inventory_plan(
    records: list[dict],
    target_product: str,
    target_models: list[str],
    target_languages: list[str],
    *,
    model_renames: dict[str, str] | None = None,
    carry_model: str = "",
    carry_language: str = "",
    initial_quantities: dict[tuple[str, str], int] | None = None,
    target_values: dict[tuple[str, str], dict[str, object]] | None = None,
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
        target_model = renamed_source_model if renamed_source_model in models else carry_model
        target_language = source_language if source_language in languages else carry_language
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
    return values


def category_inventory_preview_dataframe(targets: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": index,
                "产品型号": str(target.get("model") or NO_MODEL_TEXT),
                "语种": str(target.get("language") or NO_LANGUAGE_TEXT),
                "库存数量": int(target.get("quantity") or 0),
                "单价": float(target.get("unit_price") or 0),
                "海关编码": str(target.get("customs_code") or ""),
                "启用状态": normalize_enabled_status(target.get("status")),
            }
            for index, target in enumerate(targets, start=1)
        ],
        columns=["序号", "产品型号", "语种", "库存数量", "单价", "海关编码", "启用状态"],
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


def get_or_create_feishu_category_record(product: str, no_model: bool, no_language: bool = False) -> dict:
    client = feishu_client()
    if client is None:
        raise RuntimeError("飞书客户端未初始化。")
    existing = find_feishu_category_record(product)
    if existing is not None:
        updates: dict[str, object] = {}
        if no_model:
            updates["是否无需型号"] = "是"
        if no_language:
            updates["是否无需语种"] = "是"
        if updates:
            feishu_update_record_fields(
                "物料品类",
                feishu_record_id(existing),
                updates,
            )
        return existing
    created = feishu_batch_create_records(
        "物料品类",
        [
            {
                "物料品类": product,
                "是否无需型号": "是" if no_model else "否",
                "是否无需语种": "是" if no_language else "否",
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


def sync_feishu_category_inventory(
    *,
    old_product: str,
    new_product: str,
    no_model: bool,
    no_language: bool,
    target_models: list[str],
    target_languages: list[str],
    category_status: str = STATUS_ACTIVE,
    category_unit_price: float | None = None,
    category_customs_code: str = "",
    category_record_id: str = "",
    model_renames: dict[str, str] | None = None,
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
    category_unit_price = None if category_unit_price is None else float(category_unit_price)
    category_customs_code = category_customs_code.strip()
    models = [NO_MODEL_TEXT] if no_model else target_models
    languages = [NO_LANGUAGE_TEXT] if no_language else target_languages

    category_rows = fresh_feishu_rows("物料品类")
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
        carry_model=carry_model,
        carry_language=carry_language,
        initial_quantities=initial_quantities,
        target_values=target_values,
        referenced_ids=referenced_ids,
    )
    plan = enforce_category_inventory_status(plan, category_status)

    created_category = False
    if not category_record_id:
        category_fields: dict[str, object] = {
            "物料品类": new_product,
            "是否无需型号": "是" if no_model else "否",
            "是否无需语种": "是" if no_language else "否",
            "启用状态": category_status,
            "库存行数": plan["target_count"],
            "产品型号数量": len(plan["models"]),
            "语种数量": len(plan["languages"]),
            "备注": "",
        }
        set_feishu_unit_price(CATEGORY_TABLE_NAME, category_fields, category_unit_price)
        set_feishu_customs_code(CATEGORY_TABLE_NAME, category_fields, category_customs_code)
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
        "是否无需型号": "是" if no_model else "否",
        "是否无需语种": "是" if no_language else "否",
        "启用状态": category_status,
        "库存行数": plan["target_count"],
        "产品型号数量": len(plan["models"]),
        "语种数量": len(plan["languages"]),
    }
    set_feishu_unit_price(CATEGORY_TABLE_NAME, category_update_fields, category_unit_price)
    set_feishu_customs_code(CATEGORY_TABLE_NAME, category_update_fields, category_customs_code)
    feishu_update_record_fields(CATEGORY_TABLE_NAME, category_record_id, category_update_fields)

    return {
        **plan,
        "category_record_id": category_record_id,
        "created_category": created_category,
        "created_count": len(created_material_rows),
        "updated_count": len(keeper_updates),
        "deleted_count": deleted_count,
        "relation_update_count": relation_update_count,
    }


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


def sync_management_section_from_workbench_control() -> None:
    selected = st.session_state.get(MANAGEMENT_WORKBENCH_CONTROL_KEY, "库存登记")
    if selected in MANAGEMENT_WORKBENCH_SECTIONS:
        set_management_section(selected, sync_workbench_control=False)


def request_material_management_navigation_loading() -> None:
    selected = str(st.session_state.get(MATERIAL_MANAGEMENT_CONTROL_KEY, ""))
    if selected in MATERIAL_MANAGEMENT_SECTIONS:
        st.session_state[MANAGEMENT_NAVIGATION_LOADING_KEY] = selected


def management_navigation_uses_loading_overlay(section: object) -> bool:
    normalized = str(section or "")
    return (
        normalized in {"物料管理", "修改与撤回"}
        or normalized in MATERIAL_MANAGEMENT_SECTIONS
    )


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
            with st.spinner("正在提交 GitHub 缓存发布任务，请稍后......"):
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
        navigate_to_warehouse_locations(
            "sidebar_open_warehouse_locations",
            "物料仓库位置查询",
        )
        if current_view == "approval":
            st.button(
                "审批与发放",
                key="sidebar_current_approval",
                icon=":material/fact_check:",
                disabled=True,
                width="stretch",
            )
        else:
            navigate_to_approval("sidebar_open_approval", "审批与发放")
        navigate_to_management_section(
            "sidebar_open_material_management",
            "物料管理",
            "物料管理",
            ":material/inventory_2:",
        )
        st.divider()
        with st.container(key="sidebar_data_system_group"):
            st.markdown(
                f'<div class="pudu-sidebar-label">{escape(ui_text("数据与系统"))}</div>',
                unsafe_allow_html=True,
            )
            if not st.session_state.get("admin_unlocked"):
                with st.expander("数据与系统工具", expanded=False, icon=":material/lock:"):
                    sidebar_admin_auth_gate("data_system_tools")
            else:
                if st.button(
                    "更新全部数据缓存",
                    key="sidebar_refresh_data",
                    icon=":material/refresh:",
                    width="stretch",
                ):
                    with st.spinner("全部页面数据同步中，请稍后......"):
                        try:
                            maintenance = maintain_inventory_status()
                            result = refresh_page_cache_tables(ALL_PAGE_CACHE_TABLES)
                            refresh_request_form_cache_from_page_data()
                            refresh_contact_departments_from_feishu()
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
            f'<span class="pudu-required-star">*</span></span>{hint_html}</div>'
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
        "request_saved_attachments": [],
        "request_form_stage": "edit",
        "request_material_table_version": 0,
        "request_attachment_upload_version": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "request_submission_token" not in st.session_state:
        st.session_state["request_submission_token"] = uuid.uuid4().hex


def render_request_contact_fields(
    department_col: object,
    requester_col: object,
) -> tuple[str, str, str, str]:
    required_field_label(department_col, "申请部门")
    required_field_label(requester_col, "申请人")
    try:
        departments = get_contact_departments()
        directory_users = get_contact_users()
    except Exception as exc:
        st.warning(f"飞书通讯录暂时不可用，已切换为手动填写：{exc}")
        department = department_col.text_input(
            "申请部门",
            key="request_department_manual",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        requester = requester_col.text_input(
            "申请人",
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
    department_options = list(department_by_id)
    current_department_id = st.session_state.get("request_department_id")
    if current_department_id not in department_options:
        st.session_state["request_department_id"] = None
    department_id = department_col.selectbox(
        "申请部门",
        department_options,
        index=None,
        key="request_department_id",
        format_func=lambda value: str(department_by_id.get(str(value), {}).get("path") or value),
        placeholder="请选择飞书部门",
        label_visibility="collapsed",
        on_change=mark_request_form_dirty,
    )
    department = (
        str(department_by_id.get(str(department_id), {}).get("path") or "")
        if department_id
        else ""
    )
    st.session_state["request_department"] = department

    users: list[dict[str, object]] = list(directory_users)
    user_error = ""
    if not users and department_id:
        try:
            with st.spinner("正在读取部门成员，请稍后......"):
                users = [
                    {
                        **item,
                        "department_ids": [str(department_id)],
                        "department_paths": [department],
                    }
                    for item in load_contact_department_users(str(department_id))
                ]
        except Exception as exc:
            user_error = str(exc)
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
        placeholder="输入姓名搜索申请人" if directory_users else (
            "请先选择部门" if not department_id else "请选择飞书员工"
        ),
        disabled=not user_options,
        label_visibility="collapsed",
        on_change=sync_request_department_from_selected_applicant,
    )
    requester = (
        str(user_by_id.get(str(requester_open_id), {}).get("name") or "")
        if requester_open_id
        else ""
    )
    st.session_state["request_requester"] = requester
    if user_error:
        requester_col.caption("部门成员读取失败，请刷新本页数据后重试。")
    elif department_id and not users:
        requester_col.caption("该部门暂无可选成员。")
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
                "产品型号": line["model"],
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


def serialize_request_uploads(uploaded_files: object) -> list[dict[str, object]]:
    if not uploaded_files:
        return []
    return [
        {
            "name": str(file.name),
            "content": bytes(file.getvalue()),
            "content_type": str(file.type or "application/octet-stream"),
        }
        for file in uploaded_files
    ]


def merge_request_attachments(
    saved_attachments: object,
    uploaded_attachments: object,
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for attachment in list(saved_attachments or []) + list(uploaded_attachments or []):
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name", "")).strip()
        content = attachment.get("content", b"")
        if not name or not isinstance(content, (bytes, bytearray)):
            continue
        merged[name] = {
            "name": name,
            "content": bytes(content),
            "content_type": str(attachment.get("content_type") or "application/octet-stream"),
        }
    return list(merged.values())


def validate_request_draft(draft: dict[str, object]) -> list[str]:
    errors: list[str] = []
    missing = [
        label
        for label, value in [
            ("申请部门", draft.get("department")),
            ("申请人", draft.get("requester")),
            ("客户名称", draft.get("customer_name")),
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
    elif len(lines) > MAX_REQUEST_LINE_COUNT:
        errors.append(f"一次申请最多可添加 {MAX_REQUEST_LINE_COUNT} 种物料")
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            errors.append(f"第 {index + 1} 条物料明细无效")
            continue
        if not all(str(line.get(field, "")).strip() for field in ("product", "model", "language")):
            errors.append(f"第 {index + 1} 条物料缺少品类、型号或语种")
        if int(line.get("quantity") or 0) <= 0:
            errors.append(f"第 {index + 1} 条物料数量必须大于 0")

    attachments = list(draft.get("attachments") or [])
    if len(attachments) > MAX_ATTACHMENTS_PER_REQUEST:
        errors.append(f"相关附件最多上传 {MAX_ATTACHMENTS_PER_REQUEST} 个")
    oversized_names: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        content = attachment.get("content", b"")
        if isinstance(content, (bytes, bytearray)) and len(content) > MAX_ATTACHMENT_SIZE_BYTES:
            oversized_names.append(str(attachment.get("name", "")))
    if oversized_names:
        errors.append("以下附件超过飞书单文件 20 MB 限制：" + "、".join(oversized_names))
    return errors


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
    st.session_state["request_material_lines"] = [
        dict(line) for line in list(draft.get("lines") or []) if isinstance(line, dict)
    ]
    st.session_state["request_saved_attachments"] = [
        dict(attachment)
        for attachment in list(draft.get("attachments") or [])
        if isinstance(attachment, dict)
    ]
    st.session_state["request_material_table_version"] = (
        int(st.session_state.get("request_material_table_version", 0)) + 1
    )
    st.session_state["request_attachment_upload_version"] = (
        int(st.session_state.get("request_attachment_upload_version", 0)) + 1
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
    st.toast(message, icon="🛒", duration="short")


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
    attachments = [
        dict(attachment)
        for attachment in list(draft.get("attachments") or [])
        if isinstance(attachment, dict)
    ]
    total_quantity = sum(int(line.get("quantity") or 0) for line in lines)
    material_types_label = escape(ui_text("物料种类"))
    total_quantity_label = escape(ui_text("申请总数量"))
    attachment_count_label = escape(ui_text("附件数量"))
    st.markdown(
        f"""
        <div class="pudu-review-metrics">
            <div class="pudu-review-metric"><span>{material_types_label}</span><strong>{len(lines)}</strong></div>
            <div class="pudu-review-metric"><span>{total_quantity_label}</span><strong>{total_quantity}</strong></div>
            <div class="pudu-review-metric"><span>{attachment_count_label}</span><strong>{len(attachments)}</strong></div>
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
        render_request_review_field(overview_cols[2], "客户名称", draft.get("customer_name"))
        render_request_review_field(overview_cols[3], "国家", draft.get("country"))
        detail_cols = st.columns([1.2, 1, 1.4])
        render_request_review_field(detail_cols[0], "运费承担者", draft.get("freight_payer"))
        render_request_review_field(detail_cols[1], "物料用途", draft.get("material_usage"))
        render_request_review_field(detail_cols[2], "收件人信息", draft.get("recipient_info"))
        render_request_review_field(
            st,
            "相关附件",
            "、".join(str(item.get("name", "")) for item in attachments) or "无",
        )

    with st.container(border=True):
        render_section_header("02", "申请物料清单", f"共 {len(lines)} 种物料")
        review_df = pd.DataFrame(
            [
                {
                    "序号": index + 1,
                    "物料品类": line.get("product", ""),
                    "产品型号": line.get("model", ""),
                    "语种": line.get("language", ""),
                    "申请数量": int(line.get("quantity") or 0),
                    "备注": line.get("remark", ""),
                }
                for index, line in enumerate(lines)
            ]
        )
        st.dataframe(
            review_df,
            width="stretch",
            hide_index=True,
            height=min(820, max(150, 38 * (len(review_df) + 1) + 18)),
            row_height=34,
        )

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
            st.warning("；".join(errors))
            return
        with st.spinner("正在提交申请，请勿重复点击..."):
            with DATA_LOCK:
                try:
                    request_no, line_count, created_new_request = submit_feishu_material_request(
                        draft,
                        lines,
                    )
                except Exception as exc:
                    st.error("提交申请失败。请检查申请单/申请明细表字段、物料组合和飞书写入权限。")
                    st.exception(exc)
                    return
        notification_count = 0
        sales_receipt_count = 0
        sales_permission_result = ""
        notification_warning = ""
        try:
            with DATA_LOCK:
                sales_permission_result = ensure_requester_sales_permission(draft)
        except Exception as exc:
            notification_warning = (
                "申请已成功，但申请人的销售权限自动登记失败："
                f"{exc}"
            )
        if created_new_request:
            with st.spinner("申请已提交，正在通知审批人......"):
                try:
                    notification_count = notify_enabled_admins_of_material_request(
                        request_no,
                        draft,
                        lines,
                    )
                except Exception as exc:
                    admin_warning = (
                        "申请已成功，但机器人提醒发送失败。管理员可在审批页查看申请，"
                        f"并检查机器人权限或用户权限表：{exc}"
                    )
                    notification_warning = "；".join(
                        item for item in [notification_warning, admin_warning] if item
                    )
                try:
                    sales_receipt_count = notify_sales_request_received(
                        request_no,
                        draft,
                        lines,
                    )
                except Exception as exc:
                    sales_warning = f"申请人回执发送失败：{exc}"
                    notification_warning = "；".join(
                        item for item in [notification_warning, sales_warning] if item
                    )
        st.cache_data.clear()
        clear_request_application_state()
        notification_text = (
            f"机器人已提醒 {notification_count} 位管理员。" if notification_count else ""
        )
        if sales_receipt_count:
            notification_text += "已向申请人发送处理回执。"
        if sales_permission_result in {"created", "updated"}:
            notification_text += "已自动登记申请人的销售身份。"
        st.session_state["request_submit_message"] = (
            f"已提交申请单 {request_no}，共 {line_count} 条申请明细。{notification_text}"
        )
        if notification_warning:
            st.session_state["request_submit_warning"] = notification_warning
        st.session_state["request_scroll_to_top"] = True
        st.rerun()


def render_compact_request_cart(container: object, lines: list[dict[str, object]]) -> list[dict[str, object]]:
    total_quantity = sum(int(line.get("quantity") or 0) for line in lines)
    with container.popover(
        f"🛒 {len(lines)}",
        key="request_compact_cart",
        width="stretch",
    ):
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
            st.rerun()
    return lines


def render_request_material_builder(
    selection_context: dict[str, object],
    products: list[str],
    models: list[str],
    languages: list[str],
) -> tuple[list[dict[str, object]], bool]:
    lines = get_request_material_lines()
    render_request_cart_added_toast()

    with st.container(border=True):
        render_section_header(
            "02",
            "选择申请物料",
            f"像购物一样选择规格并加入采购车，最多 {MAX_REQUEST_LINE_COUNT} 种",
        )
        if not products:
            st.error("当前没有可申请的物料品类，请先刷新数据或联系管理员。")
            return lines, False

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
        )
        lines = render_compact_request_cart(cart_col, lines)
        preview_clicked = preview_col.button(
            "预览购物车并提交查看",
            key="request_preview",
            type="primary",
            icon=":material/preview:",
            width="stretch",
        )
        filtered_products = filter_request_catalog_products(products, search_query)
        if not filtered_products:
            st.info("没有找到匹配的物料，请更换关键词。")
        else:
            card_columns = st.columns(4, gap="small")
            for index, catalog_product in enumerate(filtered_products):
                product_state_key = normalize_option_label(catalog_product)
                is_no_model_product, scoped_models = product_model_state(
                    catalog_product,
                    selection_context,
                )
                if is_no_model_product:
                    model_options = [NO_MODEL_TEXT]
                elif scoped_models:
                    model_options = unique_preserve(scoped_models)
                else:
                    model_options = [
                        model for model in models if model != NO_MODEL_TEXT
                    ] or [NO_MODEL_TEXT]
                with card_columns[index % 4].container(border=True):
                    st.markdown('<span class="pudu-product-card-marker"></span>', unsafe_allow_html=True)
                    category_image_path = request_category_image_path(catalog_product)
                    if category_image_path:
                        st.image(
                            str(category_image_path),
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
                        st.markdown(
                            f"#### {escape(request_category_display_label(catalog_product))}",
                            unsafe_allow_html=True,
                        )
                        model_multi_key = f"request_cart_model_multi_{product_state_key}"
                        language_multi_key = f"request_cart_language_multi_{product_state_key}"
                        if len(model_options) <= 1:
                            st.session_state[model_multi_key] = False
                        multi_cols = st.columns(2, gap="small")
                        model_multi = multi_cols[0].toggle(
                            "型号多选",
                            key=model_multi_key,
                            disabled=len(model_options) <= 1,
                            on_change=enforce_request_cart_exclusive_multi_select,
                            args=(model_multi_key, language_multi_key),
                        )
                        language_multi = multi_cols[1].toggle(
                            "语种多选",
                            key=language_multi_key,
                            on_change=enforce_request_cart_exclusive_multi_select,
                            args=(language_multi_key, model_multi_key),
                        )
                        st.caption(
                            "型号多选与语种多选不可同时开启；多选时填写的数量将应用到全部所选规格。"
                        )

                        model_widget_key = (
                            f"request_cart_models_v2_{'multi' if model_multi else 'single'}_"
                            f"{get_ui_language()}_{product_state_key}"
                        )
                        current_models = st.session_state.get(model_widget_key)
                        if model_multi:
                            if not isinstance(current_models, list) or any(
                                model not in model_options for model in current_models
                            ):
                                st.session_state[model_widget_key] = [model_options[0]]
                        elif not isinstance(current_models, str) or current_models not in model_options:
                            st.session_state[model_widget_key] = model_options[0]
                        selected_model_values = st.pills(
                            "产品型号",
                            model_options,
                            selection_mode="multi" if model_multi else "single",
                            required=not model_multi,
                            format_func=request_option_display_label,
                            key=model_widget_key,
                            on_change=mark_request_form_dirty,
                            width="stretch",
                        )
                        selected_models = (
                            list(selected_model_values or [])
                            if model_multi
                            else [selected_model_values] if selected_model_values else []
                        )

                        language_options: list[str] = []
                        for selected_model in selected_models:
                            _, scoped_languages = product_language_state(
                                catalog_product,
                                selected_model,
                                selection_context,
                                languages,
                            )
                            language_options.extend(scoped_languages)
                        language_options = unique_preserve(language_options) or [NO_LANGUAGE_TEXT]
                        language_widget_key = (
                            f"request_cart_languages_v2_{'multi' if language_multi else 'single'}_"
                            f"{get_ui_language()}_{product_state_key}"
                        )
                        current_languages = st.session_state.get(language_widget_key)
                        if language_multi:
                            if not isinstance(current_languages, list) or any(
                                language not in language_options for language in current_languages
                            ):
                                st.session_state[language_widget_key] = [language_options[0]]
                        elif (
                            not isinstance(current_languages, str)
                            or current_languages not in language_options
                        ):
                            st.session_state[language_widget_key] = language_options[0]
                        selected_language_values = st.pills(
                            "语种",
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

                        option_cols = st.columns([0.8, 1.6], gap="small")
                        quantity = option_cols[0].number_input(
                            "数量",
                            min_value=1,
                            max_value=1_000_000,
                            value=1,
                            step=1,
                            key=f"request_cart_quantity_{product_state_key}",
                            on_change=mark_request_form_dirty,
                        )
                        remark = option_cols[1].text_input(
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
                            disabled=not selected_models or not selected_languages,
                            width="stretch",
                        )
                        if action_clicked:
                            selected_lines = build_request_cart_selection_lines(
                                selection_context,
                                catalog_product,
                                selected_models,
                                selected_languages,
                                int(quantity),
                                str(remark or ""),
                            )
                            if not selected_lines:
                                st.warning("所选型号和语种之间没有有效的物料组合。")
                            else:
                                existing_keys = {request_material_key(line) for line in lines}
                                new_keys = {
                                    request_material_key(line)
                                    for line in selected_lines
                                    if request_material_key(line) not in existing_keys
                                }
                                if len(lines) + len(new_keys) > MAX_REQUEST_LINE_COUNT:
                                    st.warning(
                                        f"本次选择会超过采购车 {MAX_REQUEST_LINE_COUNT} 种物料的上限。"
                                    )
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
                                    st.rerun()

        lines = get_request_material_lines()
    return lines, preview_clicked


def render_change_form(show_title: bool = True) -> None:
    initialize_request_form_state()
    scroll_request_page_to_top_if_needed()
    if st.session_state.get("request_form_stage") == "review":
        render_request_review()
        return

    with st.spinner("物料数据加载中，请稍后......"):
        selection_context = get_request_form_selection_context()
    products = list(selection_context["products"])
    models = unique_preserve([NO_MODEL_TEXT] + list(selection_context["models"]))
    languages = [language for language in selection_context["languages"] if language != NO_LANGUAGE_TEXT]

    if show_title:
        render_page_header(
            "营销物料领取登记",
            "申请工作台",
            "登记客户、收件信息和领取明细，提交后进入审批发放流程。",
        )
    message = st.session_state.pop("request_submit_message", "")
    if message:
        st.success(message)
    warning = st.session_state.pop("request_submit_warning", "")
    if warning:
        st.warning(warning)

    with st.container(border=True):
        render_section_header("01", "申请与业务信息", "填写领取申请的基础信息")
        top_cols = st.columns(4)
        department, department_id, requester, requester_open_id = render_request_contact_fields(
            top_cols[0],
            top_cols[1],
        )
        required_field_label(top_cols[2], "客户名称")
        customer_name = top_cols[2].text_input(
            "客户名称",
            key="request_customer_name",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        required_field_label(top_cols[3], "国家")
        country = top_cols[3].text_input(
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

        middle_cols = st.columns([2.4, 1])
        recipient_hint = (
            "Please specify the delivery address (including recipient information, postal code, and specific address)"
            if get_ui_language() == LANGUAGE_EN
            else "请写明快递地址（包含收件人信息，邮编，具体地址）"
        )
        required_field_label(middle_cols[0], "收件人信息", recipient_hint)
        recipient_info = middle_cols[0].text_area(
            "收件人信息",
            placeholder="请写明快递地址（包含收件人信息、邮编、具体地址）",
            height=84,
            key="request_recipient_info",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        required_field_label(middle_cols[1], "运费的承担者")
        if st.session_state.get("request_freight_payer") not in FREIGHT_PAYER_OPTIONS:
            st.session_state["request_freight_payer"] = DEFAULT_FREIGHT_PAYER
        freight_payer = middle_cols[1].selectbox(
            "运费的承担者",
            FREIGHT_PAYER_OPTIONS,
            key="request_freight_payer",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )

        bottom_cols = st.columns([2.4, 1])
        usage_hint = (
            "For promotional materials, please specify the exact name of the event."
            if get_ui_language() == LANGUAGE_EN
            else "活动物料请注明具体活动名称"
        )
        required_field_label(bottom_cols[0], "物料用途", usage_hint)
        material_usage = bottom_cols[0].text_area(
            "物料用途",
            placeholder="活动物料请注明具体活动名称",
            height=76,
            key="request_material_usage",
            label_visibility="collapsed",
            on_change=mark_request_form_dirty,
        )
        bottom_cols[1].markdown(
            f'<div class="pudu-field-label">{escape(ui_text("相关附件"))}</div>',
            unsafe_allow_html=True,
        )
        upload_version = int(st.session_state.get("request_attachment_upload_version", 0))
        uploaded_files: list[object] = []
        with bottom_cols[1].popover(
            "上传或管理附件",
            icon=":material/attach_file:",
            width="stretch",
            key=f"request_attachment_popover_{upload_version}",
        ):
            uploaded_files = st.file_uploader(
                "相关附件",
                accept_multiple_files=True,
                help="单个附件不超过 20 MB，最多上传 100 个。",
                key=f"request_attachment_upload_{upload_version}",
                on_change=mark_request_form_dirty,
            )
            saved_names = [
                str(item.get("name", ""))
                for item in list(st.session_state.get("request_saved_attachments") or [])
                if isinstance(item, dict)
            ]
            if saved_names:
                st.caption("已保留：" + "、".join(saved_names))
            if (saved_names or uploaded_files) and st.button(
                "清空附件",
                key=f"request_clear_attachments_{upload_version}",
                icon=":material/delete:",
                width="stretch",
            ):
                st.session_state["request_saved_attachments"] = []
                st.session_state["request_attachment_upload_version"] = upload_version + 1
                mark_request_form_dirty()
                st.rerun()
        attachment_count = len(list(st.session_state.get("request_saved_attachments") or [])) + len(
            uploaded_files or []
        )
        bottom_cols[1].caption(f"已选择 {attachment_count} 个附件" if attachment_count else "未上传附件")

    lines, preview_clicked = render_request_material_builder(
        selection_context,
        products,
        models,
        languages,
    )
    if preview_clicked:
        attachments = merge_request_attachments(
            st.session_state.get("request_saved_attachments"),
            serialize_request_uploads(uploaded_files),
        )
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
            "attachment_note": "\n".join(str(item.get("name", "")) for item in attachments),
            "submission_token": st.session_state["request_submission_token"],
            "attachments": attachments,
            "lines": [dict(line) for line in lines],
        }
        errors = validate_request_draft(draft)
        if errors:
            st.warning("；".join(errors))
            return
        st.session_state["request_saved_attachments"] = attachments
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
            "product": str(item.get("product") or "").strip(),
            "model": str(item.get("model") or "").strip() or NO_MODEL_TEXT,
            "language": str(item.get("language") or "").strip() or NO_LANGUAGE_TEXT,
            "quantity": int(item.get("quantity") or 0),
            "remark": str(item.get("remark") or "").strip(),
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
            "restock_line_model",
            "restock_line_language",
            "restock_line_quantity",
            "restock_line_remark",
        ):
            st.session_state.pop(key, None)
        st.session_state["restock_material_edit_index"] = None


def restock_scoped_models(
    selection_context: dict[str, object],
    product: str,
) -> tuple[bool, list[str]]:
    product_key = normalize_option_label(product)
    scoped_models = list(
        dict(selection_context.get("product_models") or {}).get(product_key, [])
    )
    is_no_model = product_key in set(selection_context.get("no_model_product_keys") or set())
    if is_no_model or not scoped_models:
        return True, [NO_MODEL_TEXT]
    return False, sort_models(scoped_models)


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
    return False, sort_languages(scoped_languages)


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
    with st.container(border=True):
        render_section_header(
            "02",
            "采购补库清单",
            f"逐条添加启用物料，最多 {MAX_REQUEST_LINE_COUNT} 种",
        )
        if not products:
            st.error("当前没有可补库的启用物料，请先刷新数据或在品类管理中启用库存行。")
            return lines

        editor_index_value = st.session_state.get("restock_material_edit_index")
        editor_index = (
            int(editor_index_value)
            if isinstance(editor_index_value, int) and 0 <= editor_index_value < len(lines)
            else None
        )
        editor_cols = st.columns(
            [2.2, 1.7, 1.5, 0.85, 1.5, 1.15],
            gap="small",
            vertical_alignment="bottom",
        )
        product_col, model_col, language_col, quantity_col, remark_col, action_col = editor_cols
        required_field_label(product_col, "物料品类")
        if st.session_state.get("restock_line_product") not in products:
            st.session_state["restock_line_product"] = products[0]
        product = product_col.selectbox(
            "物料品类",
            products,
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
            disabled=editor_index is None and len(lines) >= MAX_REQUEST_LINE_COUNT,
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
                st.warning("该品类、型号和语种的库存组合不存在或已停用，请重新选择。")
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
                st.session_state["restock_line_editor_reset"] = True
                st.rerun()

        lines = get_restock_material_lines()
        st.markdown(
            f"""
            <div class="pudu-material-list-status">
                <span>{escape(ui_text("采购补库清单"))}</span>
                <strong>{len(lines)} / {MAX_REQUEST_LINE_COUNT}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not lines:
            st.info("尚未添加补库物料。")
            return lines

        table_version = int(st.session_state.get("restock_material_table_version", 0))
        edited_df = st.data_editor(
            request_material_table_dataframe(lines).rename(columns={"数量": "补库数量"}),
            width="stretch",
            hide_index=True,
            height=min(520, max(140, 38 * (len(lines) + 1) + 22)),
            row_height=34,
            disabled=["序号", "物料品类", "产品型号", "语种"],
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", width="small"),
                "序号": st.column_config.NumberColumn("序号", width="small", format="%d"),
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
        with st.spinner("正在补充库存并写入库存流水，请稍后......"):
            with DATA_LOCK:
                try:
                    completed_lines = submit_inventory_restock(draft)
                except Exception as exc:
                    st.error("采购补库失败。请检查物料状态、库存字段和飞书写入权限。")
                    st.exception(exc)
                    return
        notification_count = 0
        notification_warning = ""
        with st.spinner("补库已完成，正在通知管理员......"):
            try:
                notification_count = notify_enabled_admins_of_restock(draft, completed_lines)
            except Exception as exc:
                notification_warning = f"补库已完成，但管理员通知发送失败：{exc}"
        refresh_page_cache_after_write("restock", update_request_form=True)
        restock_no = str(draft.get("restock_no") or "")
        clear_restock_form_state()
        st.session_state["restock_submit_message"] = (
            f"补库单 {restock_no} 已完成，共补充 {len(completed_lines)} 种、"
            f"{sum(int(line.get('quantity') or 0) for line in completed_lines)} 件物料。"
            + (f"已通知 {notification_count} 位管理员。" if notification_count else "")
        )
        if notification_warning:
            st.session_state["restock_submit_warning"] = notification_warning
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
        "category_status_new",
        "category_unit_price_new",
        "category_customs_code_new",
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
        "category_status_new",
        "category_unit_price_new",
        "category_customs_code_new",
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
        info_cols = st.columns(3)
        render_request_review_field(info_cols[0], "原品类名称", draft.get("old_product"))
        render_request_review_field(info_cols[1], "修改后名称", draft.get("product"))
        render_request_review_field(info_cols[2], "品类状态", draft.get("category_status"))
        if changed_rows:
            st.dataframe(
                pd.DataFrame(changed_rows),
                width="stretch",
                hide_index=True,
                height=min(720, max(180, 38 * (len(changed_rows) + 1))),
            )
        else:
            st.info("库存组合没有发生变化；请返回检查是否只修改了品类名称或基础配置。")
    st.info("点击“确认保存修改”后将立即写入飞书；完成后页面顶部会显示全宽结果提示，并通知管理员。")
    back_col, _, confirm_col = st.columns([1.1, 2.2, 1.5])
    if back_col.button("返回修改", icon=":material/arrow_back:", width="stretch", key="category_edit_review_back"):
        st.session_state[CATEGORY_EDIT_STAGE_KEY] = "edit"
        st.session_state.pop(CATEGORY_EDIT_DRAFT_KEY, None)
        st.rerun()
    if confirm_col.button("确认保存修改", type="primary", icon=":material/check_circle:", width="stretch", key="category_edit_review_confirm"):
        with st.spinner("正在保存品类配置并发送管理员通知，请勿关闭页面......"):
            with DATA_LOCK:
                try:
                    result = sync_feishu_category_inventory(**dict(draft["sync_args"]))
                except Exception as exc:
                    st.error("保存品类配置失败。数据未全部同步，请刷新页面检查飞书字段和关联后重试。")
                    st.exception(exc)
                    return
            notification_count = 0
            notification_warning = ""
            try:
                notification_count = notify_enabled_admins_of_category_edit(draft, result)
            except Exception as exc:
                notification_warning = f"品类已保存，但管理员通知发送失败：{exc}"
        refresh_page_cache_after_write("category", update_request_form=True)
        st.session_state.pop(CATEGORY_EDIT_DRAFT_KEY, None)
        st.session_state[CATEGORY_EDIT_STAGE_KEY] = "edit"
        st.session_state["category_added_message"] = (
            f"物料品类“{draft['product']}”已保存：目标组合 {result['target_count']} 条，"
            f"新增 {result['created_count']} 条，移除旧行 {result['deleted_count']} 条，"
            f"迁移关联 {result['relation_update_count']} 条，库存差额 {result['quantity_difference']:+,}。"
            + (f" 已通知 {notification_count} 位管理员。" if notification_count else "")
        )
        if notification_warning:
            st.session_state["category_admin_warning"] = notification_warning
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
        info_cols = st.columns(4)
        render_request_review_field(info_cols[0], "物料品类", product)
        render_request_review_field(info_cols[1], "品类启用状态", category_status)
        render_request_review_field(
            info_cols[2],
            "产品型号规则",
            NO_MODEL_TEXT if draft.get("no_model") else f"{len(list(draft.get('models') or []))} 个型号",
        )
        render_request_review_field(
            info_cols[3],
            "语种规则",
            NO_LANGUAGE_TEXT
            if draft.get("no_language")
            else f"{len(list(draft.get('languages') or []))} 个语种",
        )

    with st.container(border=True):
        render_section_header(
            "02",
            "新增库存行预览",
            "逐行填写初始库存数量；确认创建前不会写入飞书",
        )
        disabled_columns = ["序号", "产品型号", "语种"]
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
        with st.spinner("正在创建物料品类、库存行并发送管理员通知，请勿关闭页面......"):
            with DATA_LOCK:
                try:
                    result = sync_feishu_category_inventory(
                        old_product="",
                        new_product=product,
                        no_model=bool(draft.get("no_model")),
                        no_language=bool(draft.get("no_language")),
                        target_models=list(draft.get("models") or []),
                        target_languages=list(draft.get("languages") or []),
                        category_status=category_status,
                        category_unit_price=draft.get("category_unit_price"),
                        category_customs_code=str(draft.get("category_customs_code") or ""),
                        target_values=edited_values,
                    )
                except Exception as exc:
                    st.error("创建物料品类失败，尚未完成全部库存行写入。请检查飞书数据后重试。")
                    st.exception(exc)
                    return
            notification_count = 0
            notification_warning = ""
            notification_draft = {
                **dict(draft),
                "product": product,
                "category_status": category_status,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            try:
                notification_count = notify_enabled_admins_of_category_create(
                    notification_draft,
                    result,
                )
            except Exception as exc:
                notification_warning = f"品类已创建，但管理员通知发送失败：{exc}"
        refresh_page_cache_after_write("category", update_request_form=True)
        clear_new_category_creation_state()
        st.session_state["category_added_message"] = (
            f"物料品类“{product}”已创建，共生成 {result['created_count']} 条库存行，"
            f"初始库存合计 {result['target_quantity']:,}。"
            + (f" 已通知 {notification_count} 位管理员。" if notification_count else "")
        )
        if notification_warning:
            st.session_state["category_admin_warning"] = notification_warning
        st.rerun()


def render_add_category_form() -> None:
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

    message = st.session_state.pop("category_added_message", "") or st.session_state.pop(
        "category_admin_message", ""
    )
    if message:
        st.success(message)
    warning = st.session_state.pop("category_admin_warning", "")
    if warning:
        st.warning(warning)

    render_section_header("01", "物料品类管理", "新增或调整品类名称、型号、语种和对应库存组合")
    mode = st.radio(
        "操作类型",
        ["新增品类", "编辑现有品类"],
        horizontal=True,
        label_visibility="collapsed",
        key="category_management_mode",
    )
    is_edit = mode == "编辑现有品类"
    category_by_name = {str(item["category"]): item for item in categories}

    selected_category: dict | None = None
    if is_edit:
        if not category_by_name:
            st.info("暂无可编辑的物料品类，请先新增品类。")
            return
        selected_name = st.selectbox(
            "选择物料品类",
            list(category_by_name),
            key="category_management_selected_name",
        )
        selected_category = category_by_name[selected_name]

    category_id = str((selected_category or {}).get("record_id") or "")
    old_product = str((selected_category or {}).get("category") or "")
    current_records = [record for record in inventory_records if record["category"] == old_product] if is_edit else []
    current_models = unique_preserve([str(record["model"] or NO_MODEL_TEXT) for record in current_records])
    current_languages = unique_preserve([str(record["language"]) for record in current_records if record["language"]])
    current_no_model = bool((selected_category or {}).get("no_model")) or (
        bool(current_models) and set(current_models) == {NO_MODEL_TEXT}
    )
    current_no_language = bool((selected_category or {}).get("no_language")) or (
        bool(current_languages) and set(current_languages) == {NO_LANGUAGE_TEXT}
    )
    current_category_status = normalize_enabled_status((selected_category or {}).get("status"))
    current_category_unit_price = (selected_category or {}).get("unit_price")
    current_category_customs_code = str((selected_category or {}).get("customs_code") or "")
    editor_key = category_id or "new"

    with st.container(border=True):
        product_key = f"category_name_{editor_key}"
        product = st.text_input(
            "物料品类名称 *",
            placeholder="例如：新版宣传册(New Brochure)",
            key=product_key,
            **({} if product_key in st.session_state else {"value": old_product}),
        ).strip()
        metadata_status_col, metadata_price_col, metadata_customs_col = st.columns(
            [1.2, 1, 1.2],
            vertical_alignment="bottom",
        )
        category_status_key = f"category_status_{editor_key}"
        category_status = metadata_status_col.radio(
            "品类启用状态 *",
            list(MATERIAL_STATUS_OPTIONS),
            horizontal=True,
            help="停用品类不会出现在物料申请页；历史库存和申请记录仍会保留。",
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
            [
                language
                for language in sort_languages(current_languages + list(options["languages"]))
                if language and language != NO_LANGUAGE_TEXT
            ]
        )
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
            "语种 *",
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
            "新增自定义语种",
            placeholder="可用逗号、分号、顿号或换行分隔",
            disabled=no_language,
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
            with st.expander("修改已有型号", expanded=False):
                st.caption("一次选择一个型号进行修改；应用后可继续选择其他型号，库存和历史关联保持不变。")
                rename_select_col, rename_input_col, rename_button_col = st.columns(
                    [1.1, 1.5, 0.7],
                    vertical_alignment="bottom",
                )
                rename_source = rename_select_col.selectbox(
                    "选择要修改的型号",
                    editable_current_models,
                    key=f"category_model_rename_source_{editor_key}",
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

        renamed_selected_models = [model_renames.get(model, model) for model in selected_models]
        models = (
            [NO_MODEL_TEXT]
            if no_model
            else unique_preserve(renamed_selected_models + parse_custom_values(custom_models_text))
        )
        languages = (
            [NO_LANGUAGE_TEXT]
            if no_language
            else unique_preserve(selected_languages + parse_custom_values(custom_languages_text))
        )

        carry_model = models[0] if models else ""
        carry_language = languages[0] if languages else ""
        renamed_source_models = set(model_renames)
        removed_models = [
            model
            for model in current_models
            if model not in models and model not in renamed_source_models
        ]
        removed_languages = [language for language in current_languages if language not in languages]
        if current_records and models and removed_models:
            carry_model = st.selectbox(
                "被取消型号的历史关联迁移到 *",
                models,
                help="这里只决定申请明细和流水的关联去向；库存数量请在下方库存组合编辑区填写。",
                key=f"category_carry_model_{editor_key}",
            )
        if current_records and languages and removed_languages:
            carry_language = st.selectbox(
                "被取消语种的历史关联迁移到 *",
                languages,
                help="这里只决定申请明细和流水的关联去向；库存数量请在下方库存组合编辑区填写。",
                key=f"category_carry_language_{editor_key}",
            )

        plan: dict | None = None
        if product and models and languages and not model_rename_error and not category_metadata_error:
            try:
                plan = build_category_inventory_plan(
                    current_records,
                    product,
                    models,
                    languages,
                    model_renames=model_renames,
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
            st.caption("选择一个型号和语种后编辑对应库存组合；切换到其他组合时，已经填写的内容会自动保留。")
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
                if quantity_key in st.session_state:
                    values["quantity"] = int(st.session_state[quantity_key])
                if unit_price_key in st.session_state:
                    values["unit_price"] = float(st.session_state[unit_price_key] or 0)
                if customs_key in st.session_state:
                    values["customs_code"] = str(st.session_state[customs_key] or "").strip()
                if status_key in st.session_state:
                    values["status"] = normalize_enabled_status(st.session_state[status_key])
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
                for values in target_values.values():
                    if float(values.get("unit_price") or 0) == previous_price:
                        values["unit_price"] = category_defaults["unit_price"]
                    if str(values.get("customs_code") or "") == previous_customs:
                        values["customs_code"] = category_defaults["customs_code"]
                    if normalize_enabled_status(values.get("status")) == previous_status:
                        values["status"] = category_defaults["status"]
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
                carry_model=carry_model,
                carry_language=carry_language,
                target_values=target_values,
            )
            plan = enforce_category_inventory_status(plan, category_status)

            selector_model_col, selector_language_col = st.columns(2)
            selected_target_model = selector_model_col.selectbox(
                "选择要编辑的产品型号",
                models,
                key=f"category_combo_model_{editor_key}_{signature}",
            )
            selected_target_language = selector_language_col.selectbox(
                "选择要编辑的语种",
                languages,
                key=f"category_combo_language_{editor_key}_{signature}",
            )
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
            quantity_col, price_col, customs_col, status_col = st.columns(
                [1, 1, 1.4, 1.2],
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
            target_values[selected_target_key] = {
                "quantity": int(selected_quantity),
                "unit_price": float(selected_unit_price),
                "customs_code": selected_customs_code.strip(),
                "status": STATUS_INACTIVE
                if category_status == STATUS_INACTIVE
                else normalize_enabled_status(selected_status),
            }
            st.session_state[target_state_key] = target_values
            plan = build_category_inventory_plan(
                current_records,
                product,
                models,
                languages,
                model_renames=model_renames,
                carry_model=carry_model,
                carry_language=carry_language,
                target_values=target_values,
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
        elif product != old_product and product in existing_names:
            st.error("该物料品类名称已经存在。")
        elif not models:
            st.error("请至少保留或新增一个产品型号，或勾选“无需产品型号”。")
        elif not languages:
            st.error("请至少保留或新增一个语种，或勾选“无需语种”。")
        elif category_metadata_error:
            st.error(category_metadata_error)
        elif plan is None:
            st.error("请检查库存组合中的数量、单价、海关编码和启用状态。")
        elif plan["discarded_quantity"] > 0 and not discard_confirmed:
            st.warning("请确认直接舍弃未分配库存。")
        elif is_edit and not confirmed:
            st.warning("请先确认品类配置和库存组合。")
        elif not is_edit:
            st.session_state[CATEGORY_CREATE_DRAFT_KEY] = {
                "product": product,
                "no_model": no_model,
                "no_language": no_language,
                "models": list(models),
                "languages": list(languages),
                "category_status": category_status,
                "category_unit_price": category_unit_price,
                "category_customs_code": category_customs_code,
                "targets": [dict(target) for target in plan["targets"]],
                "target_state_key": target_state_key,
                "revision_key": revision_key,
                "form_state": {
                    "category_name_new": product,
                    "category_status_new": category_status,
                    "category_unit_price_new": category_unit_price_text,
                    "category_customs_code_new": category_customs_code,
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
                "no_language": no_language, "target_models": list(models),
                "target_languages": list(languages), "category_status": category_status,
                "category_unit_price": category_unit_price, "category_customs_code": category_customs_code,
                "category_record_id": category_id, "model_renames": dict(model_renames),
                "carry_model": carry_model, "carry_language": carry_language,
                "target_values": {key: dict(value) for key, value in target_values.items()},
            }
            st.session_state[CATEGORY_EDIT_DRAFT_KEY] = {
                "old_product": old_product, "product": product, "category_status": category_status,
                "edited_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "current_records": [dict(row) for row in current_records],
                "targets": [dict(target) for target in plan["targets"]],
                "quantity_difference": plan["quantity_difference"], "sync_args": sync_args,
            }
            st.session_state[CATEGORY_EDIT_STAGE_KEY] = "review"
            st.rerun()

    if is_edit and selected_category is not None:
        with st.expander("撤回当前品类"):
            quantity_sum = sum(int(record["quantity"] or 0) for record in current_records)
            st.caption("仅允许撤回库存合计为 0 且没有库存流水的品类。")
            delete_confirmed = st.checkbox("确认撤回该品类", key=f"delete_category_confirm_{category_id}")
            if st.button(
                "撤回当前品类",
                icon=":material/undo:",
                width="stretch",
                key=f"delete_category_{category_id}",
            ):
                transaction_count = count_feishu_category_transactions(old_product)
                if quantity_sum != 0 or transaction_count > 0:
                    st.error(f"当前库存合计 {quantity_sum}，流水 {transaction_count} 条，不能撤回。")
                elif not delete_confirmed:
                    st.warning("请先勾选确认撤回。")
                else:
                    with DATA_LOCK:
                        delete_feishu_category(old_product, category_id)
                    refresh_page_cache_after_write("category", update_request_form=True)
                    st.session_state["category_added_message"] = f"已撤回物料品类“{old_product}”。"
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
            with DATA_LOCK:
                try:
                    for transaction_id in active_selected_ids:
                        revert_feishu_transaction(transaction_id, revert_note)
                except Exception as exc:
                    st.error("批量撤回失败。请检查飞书应用是否有物料主数据和库存流水编辑权限。")
                    st.exception(exc)
                    return
            st.session_state["transaction_admin_message"] = f"已撤回 {len(active_selected_ids)} 条提交记录。"
            refresh_page_cache_after_write("maintenance", update_request_form=True)
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
                    refresh_page_cache_after_write("maintenance", update_request_form=True)
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
    delete_col_a.caption("仅允许删除库存为 0 且没有流水记录的库存行。")
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
    delete_col_a.caption("仅允许撤回所有库存行为 0 且没有流水记录的品类。")
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

def fetch_request_maintenance_live_data() -> dict[str, object]:
    """Always read request maintenance data directly from Feishu."""
    request_rows = fresh_feishu_rows(REQUEST_TABLE_NAME)
    line_rows = fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
    material_rows = fresh_feishu_rows(MATERIAL_TABLE_NAME)
    return {
        "requests": load_feishu_request_records(request_rows),
        "lines": load_feishu_request_line_records(line_rows, material_rows),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "row_count": len(request_rows) + len(line_rows),
    }


def update_pending_feishu_request(
    request: dict[str, object],
    request_updates: dict[str, object],
    edited_lines: list[dict[str, object]],
) -> None:
    request_id = str(request.get("record_id") or "")
    request_no = str(request.get("request_no") or "")
    current_request = next(
        (
            row
            for row in fresh_feishu_rows(REQUEST_TABLE_NAME)
            if feishu_record_id(row) == request_id
        ),
        None,
    )
    if current_request is None:
        raise RuntimeError("申请单不存在或已被删除，请刷新后重试。")
    if feishu_text(feishu_fields(current_request), "审批状态") != REQUEST_STATUS_PENDING:
        raise RuntimeError("只有待审批申请可以修改，请刷新后查看最新状态。")

    current_line_rows = [
        row
        for row in fresh_feishu_rows(REQUEST_LINE_TABLE_NAME)
        if request_id in feishu_link_ids_any(feishu_fields(row), ["所属申请单", "申请单"])
        or feishu_text_any(feishu_fields(row), ["申请单号", "所属申请单", "申请单"]) == request_no
    ]
    allowed_line_ids = {
        feishu_record_id(row)
        for row in current_line_rows
        if feishu_text(feishu_fields(row), "明细状态") != REQUEST_LINE_STATUS_WITHDRAWN
    }
    line_updates: list[dict] = []
    deleted_line_ids: set[str] = set()
    for line in edited_lines:
        line_id = str(line.get("record_id") or "")
        quantity = int(line.get("quantity") or 0)
        if line_id not in allowed_line_ids:
            raise RuntimeError("申请明细已发生变化，请刷新后重试。")
        delete_requested = bool(line.get("delete")) or quantity == 0
        if delete_requested:
            deleted_line_ids.add(line_id)
            line_updates.append(
                {
                    "record_id": line_id,
                    "fields": {"明细状态": REQUEST_LINE_STATUS_WITHDRAWN},
                }
            )
            continue
        if quantity <= 0:
            raise RuntimeError("申请数量必须大于 0。")
        line_updates.append(
            {
                "record_id": line_id,
                "fields": {
                    "申请数量": quantity,
                    "物料数量": quantity,
                    "审批通过数量": quantity,
                    "备注": str(line.get("remark") or "").strip(),
                },
            }
        )

    if not line_updates or not (allowed_line_ids - deleted_line_ids):
        raise RuntimeError("申请单至少需要保留一条物料明细。")
    feishu_update_record_fields(REQUEST_TABLE_NAME, request_id, request_updates)
    feishu_batch_update_record_fields(REQUEST_LINE_TABLE_NAME, line_updates)


def withdraw_pending_feishu_request(request: dict[str, object], note: str = "") -> None:
    request_id = str(request.get("record_id") or "")
    request_no = str(request.get("request_no") or "")
    current_request = next(
        (
            row
            for row in fresh_feishu_rows(REQUEST_TABLE_NAME)
            if feishu_record_id(row) == request_id
        ),
        None,
    )
    if current_request is None:
        raise RuntimeError("申请单不存在或已被删除，请刷新后重试。")
    current_fields = feishu_fields(current_request)
    if feishu_text(current_fields, "审批状态") != REQUEST_STATUS_PENDING:
        raise RuntimeError("只有待审批申请可以撤回，请刷新后查看最新状态。")

    line_updates: list[dict] = []
    for row in fresh_feishu_rows(REQUEST_LINE_TABLE_NAME):
        fields = feishu_fields(row)
        belongs_to_request = (
            request_id in feishu_link_ids_any(fields, ["所属申请单", "申请单"])
            or feishu_text_any(fields, ["申请单号", "所属申请单", "申请单"]) == request_no
        )
        if belongs_to_request:
            line_updates.append(
                {
                    "record_id": feishu_record_id(row),
                    "fields": {"明细状态": REQUEST_LINE_STATUS_WITHDRAWN},
                }
            )

    request_fields: dict[str, object] = {"审批状态": REQUEST_STATUS_WITHDRAWN}
    if note.strip():
        request_fields["备注"] = append_admin_note(
            feishu_text(current_fields, "备注"),
            "撤回备注",
            note,
        )
    feishu_update_record_fields(REQUEST_TABLE_NAME, request_id, request_fields)
    if line_updates:
        feishu_batch_update_record_fields(REQUEST_LINE_TABLE_NAME, line_updates)


def render_request_edit_revert_page() -> None:
    render_section_header("01", "物料申请修改与撤回", "实时读取飞书申请单；仅待审批申请允许修改或撤回")
    message = st.session_state.pop("request_maintenance_message", "")
    if message:
        st.success(message)

    with st.spinner("正在实时读取申请单和申请明细，请稍后......"):
        live_data = fetch_request_maintenance_live_data()
    requests = [
        request
        for request in list(live_data.get("requests") or [])
        if str(request.get("status") or "") == REQUEST_STATUS_PENDING
    ]
    lines = list(live_data.get("lines") or [])
    st.caption(
        "数据来源：飞书实时数据　更新时间："
        f"{str(live_data.get('updated_at') or '未记录')}"
    )
    if not requests:
        st.info("当前没有可修改或撤回的待审批申请。")
        return

    requester_options = unique_preserve(
        [str(request.get("requester") or "未填写申请人") for request in requests]
    )
    selected_requester = st.selectbox(
        "申请人",
        requester_options,
        key="request_maintenance_requester",
    )
    scoped_requests = [
        request
        for request in requests
        if str(request.get("requester") or "未填写申请人") == selected_requester
    ]
    request_by_label = {
        (
            f"{request.get('request_no')} · "
            f"{request.get('submitted_at') or '未记录时间'} · "
            f"{request.get('customer_name') or request.get('material_usage') or '物料申请'}"
        ): request
        for request in scoped_requests
    }
    selected_label = st.selectbox(
        "选择待审批申请单",
        list(request_by_label),
        key="request_maintenance_selector",
    )
    selected_request = request_by_label[selected_label]
    selected_lines = request_lines_for_request(selected_request, lines)

    info_col_a, info_col_b = st.columns(2)
    customer_name = info_col_a.text_input(
        "客户名称",
        value=str(selected_request.get("customer_name") or ""),
        key=f"request_edit_customer_{selected_request['record_id']}",
    )
    country = info_col_b.text_input(
        "国家",
        value=str(selected_request.get("country") or ""),
        key=f"request_edit_country_{selected_request['record_id']}",
    )
    recipient_info = st.text_area(
        "收件人信息",
        value=str(selected_request.get("recipient_info") or ""),
        key=f"request_edit_recipient_{selected_request['record_id']}",
    )
    detail_col_a, detail_col_b = st.columns(2)
    freight_payer = detail_col_a.text_input(
        "运费承担者",
        value=str(selected_request.get("freight_payer") or ""),
        key=f"request_edit_freight_{selected_request['record_id']}",
    )
    material_usage = detail_col_b.text_input(
        "物料用途",
        value=str(selected_request.get("material_usage") or ""),
        key=f"request_edit_usage_{selected_request['record_id']}",
    )

    line_df = pd.DataFrame(
        [
            {
                "删除": False,
                "记录ID": line["record_id"],
                "物料品类": request_category_display_label(line["product"]),
                "产品型号": line["model"],
                "语种": line["language"],
                "申请数量": int(line["quantity"]),
                "备注": line["remark"],
            }
            for line in selected_lines
            if str(line.get("status") or "") != REQUEST_LINE_STATUS_WITHDRAWN
        ]
    )
    edited_df = st.data_editor(
        line_df,
        hide_index=True,
        width="stretch",
        disabled=["记录ID", "物料品类", "产品型号", "语种"],
        column_config={
            "删除": st.column_config.CheckboxColumn(
                "删除",
                help="勾选后保存，将从该申请中移除这条物料明细。",
                width="small",
            ),
            "记录ID": None,
            "申请数量": st.column_config.NumberColumn("申请数量", min_value=1, step=1, required=True),
        },
        key=f"request_line_editor_{selected_request['record_id']}",
    )

    save_col, withdraw_col = st.columns(2)
    if save_col.button(
        "保存申请修改",
        type="primary",
        icon=":material/save:",
        width="stretch",
        key=f"save_request_edit_{selected_request['record_id']}",
    ):
        edited_lines = [
            {
                "record_id": str(row["记录ID"]),
                "quantity": int(row["申请数量"]),
                "remark": str(row.get("备注") or ""),
                "delete": bool(row.get("删除")),
            }
            for row in edited_df.to_dict("records")
        ]
        request_updates = {
            "客户名称": customer_name.strip(),
            "国家": country.strip(),
            "收件人信息": recipient_info.strip(),
            "运费的承担者": freight_payer.strip(),
            "运费承担者": freight_payer.strip(),
            "用途/活动": material_usage.strip(),
            "用途|活动": material_usage.strip(),
            "物料用途": material_usage.strip(),
        }
        with st.spinner("正在保存申请修改并同步飞书，请勿关闭页面......"):
            try:
                with DATA_LOCK:
                    update_pending_feishu_request(selected_request, request_updates, edited_lines)
            except Exception as exc:
                st.error(f"申请修改失败：{exc}")
                return
        st.session_state["request_maintenance_message"] = (
            f"申请单 {selected_request['request_no']} 已保存修改。"
        )
        st.rerun()

    with withdraw_col.popover("撤回这张申请单", width="stretch"):
        st.warning("撤回后该申请单不会再进入审批发放流程。")
        withdraw_note = st.text_input(
            "撤回备注",
            key=f"withdraw_request_note_{selected_request['record_id']}",
            placeholder="可选",
        )
        withdraw_confirmed = st.checkbox(
            "确认撤回该申请单",
            key=f"withdraw_request_confirm_{selected_request['record_id']}",
        )
        if st.button(
            "确认撤回",
            icon=":material/undo:",
            width="stretch",
            key=f"withdraw_request_button_{selected_request['record_id']}",
        ):
            if not withdraw_confirmed:
                st.warning("请先勾选确认撤回。")
            else:
                with st.spinner("正在撤回申请单并同步飞书，请勿关闭页面......"):
                    try:
                        with DATA_LOCK:
                            withdraw_pending_feishu_request(selected_request, withdraw_note)
                    except Exception as exc:
                        st.error(f"申请撤回失败：{exc}")
                        return
                st.session_state["request_maintenance_message"] = (
                    f"申请单 {selected_request['request_no']} 已撤回。"
                )
                st.rerun()


def render_edit_revert_page() -> None:
    render_request_edit_revert_page()


def render_material_database_page() -> None:
    action_spacer, action_col = st.columns([4, 1.35], vertical_alignment="center")
    action_spacer.empty()
    try:
        table_url = feishu_bitable_web_url(MATERIAL_TABLE_NAME)
    except Exception as exc:
        action_col.button(
            "打开飞书物料主数据表",
            key="open_feishu_material_database_unavailable",
            icon=":material/open_in_new:",
            disabled=True,
            width="stretch",
        )
        st.warning(f"暂时无法生成飞书物料主数据表链接：{exc}")
    else:
        action_col.link_button(
            "打开飞书物料主数据表",
            table_url,
            icon=":material/open_in_new:",
            width="stretch",
        )
    with st.spinner("物料数据加载中，请稍后......"):
        records = load_feishu_inventory_records(active_only=True)
    filtered_records = render_material_dashboard(records)
    render_material_data_admin(filtered_records)


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


def approval_inventory_context(live_data: dict[str, object]) -> dict[str, object]:
    material_rows = list(live_data.get("material_rows") or [])
    category_rows = list(live_data.get("category_rows") or [])
    model_rows = list(live_data.get("model_rows") or [])
    active_categories = {
        feishu_text(feishu_fields(row), "物料品类")
        for row in category_rows
        if normalize_enabled_status(feishu_text(feishu_fields(row), "启用状态")) == STATUS_ACTIVE
        and feishu_text(feishu_fields(row), "物料品类")
    }
    records = [
        record
        for record in feishu_inventory_records_from_rows(
            material_rows,
            category_rows,
            active_only=True,
        )
        if str(record["category"]) in active_categories
    ]
    models = sort_models(
        [
            feishu_text(feishu_fields(row), "产品型号")
            for row in model_rows
            if normalize_enabled_status(feishu_text(feishu_fields(row), "启用状态")) == STATUS_ACTIVE
        ]
        or [str(record["model"]) for record in records]
    )
    return {
        "records": records,
        "by_key": {
            (str(record["category"]), str(record["model"]), str(record["language"])): record
            for record in records
        },
        "products": sorted(unique_preserve([str(record["category"]) for record in records])),
        "models": models,
        "languages": sort_languages(unique_preserve([str(record["language"]) for record in records])),
    }


def inventory_is_insufficient(requested_quantity: object, current_quantity: object) -> bool:
    return int(requested_quantity or 0) > int(current_quantity or 0)


def approval_shortage_row_style(row: pd.Series) -> list[str]:
    if str(row.get("库存状态", "")).startswith("库存不足"):
        return ["background-color: #FEE2E2; color: #991B1B; font-weight: 600"] * len(row)
    return [""] * len(row)


def render_approval_control_label(container: object, label: str) -> None:
    container.markdown(
        f'<div class="pudu-approval-control-label">{escape(ui_text(label))}</div>',
        unsafe_allow_html=True,
    )


def render_approval_request_context(request: dict[str, object], lines: list[dict[str, object]]) -> None:
    detail_col_a, detail_col_b, detail_col_c = st.columns(3)
    detail_col_a.metric("申请单号", str(request["request_no"]))
    detail_col_b.metric("明细数", f"{len(lines):,}")
    detail_col_c.metric("状态", str(request.get("status") or "未设置"))
    st.caption(
        f"客户：{request.get('customer_name') or '-'}；国家：{request.get('country') or '-'}；"
        f"申请人：{request.get('requester') or '-'}；部门：{request.get('department') or '-'}"
    )
    if request.get("material_usage"):
        st.caption(f"物料用途：{request['material_usage']}")
    st.markdown(
        f"""
        <div class="pudu-fixed-recipient">
            <div class="pudu-fixed-recipient-label">{escape(ui_text("收件人信息"))}</div>
            <div class="pudu-fixed-recipient-value">{escape(str(request.get("recipient_info") or "-"))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def partial_approval_row_style(row: pd.Series, status_column: str) -> list[str]:
    if str(row.get(status_column, "")) == REQUEST_STATUS_PARTIAL:
        return ["background-color: #FEF3C7; color: #78350F"] * len(row)
    return [""] * len(row)


def render_pending_approval_requests(
    active_requests: list[dict[str, object]],
    request_line_map: dict[str, list[dict[str, object]]],
    inventory_context: dict[str, object],
) -> None:
    if not active_requests:
        st.info("暂无待审批或待发放的申请明细。")
        return

    render_section_header("01", "待审批申请", "选择申请单并填写实际发放数量")
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

    render_approval_request_context(selected_request, selected_lines)

    inventory_by_key = dict(inventory_context.get("by_key") or {})
    table_df = pd.DataFrame(
        [
            {
                "记录ID": line["record_id"],
                "申请物料品类": line["product"],
                "申请产品型号": line["model"],
                "申请语种": line["language"],
                "申请数量": int(line["quantity"]),
                "当前库存": int(
                    inventory_by_key.get(
                        (str(line["product"]), str(line["model"]), str(line["language"])),
                        {"quantity": line.get("current_stock") or 0},
                    ).get("quantity")
                    or 0
                ),
                "库存状态": (
                    "库存不足"
                    if inventory_is_insufficient(
                        line["quantity"],
                        inventory_by_key.get(
                            (str(line["product"]), str(line["model"]), str(line["language"])),
                            {"quantity": line.get("current_stock") or 0},
                        ).get("quantity"),
                    )
                    else "库存充足"
                ),
                "备注": line.get("remark") or line.get("usage", ""),
                "实际发放品类": line.get("actual_product") or line["product"],
                "实际发放型号": line.get("actual_model") or line["model"],
                "实际发放语种": line.get("actual_language") or line["language"],
                "实际发放数量": int(line.get("actual_issue_qty") or line.get("quantity") or 0),
            }
            for line in selected_lines
        ]
    )

    preview_df = pd.DataFrame(
        [
            {
                "序号": index,
                "物料品类": row["申请物料品类"],
                "产品型号": row["申请产品型号"],
                "语种": row["申请语种"],
                "申请数量": int(row["申请数量"]),
                "库存情况": f"{ui_text(str(row['库存状态']))} / {int(row['当前库存'])}",
                "备注": row.get("备注") or "-",
            }
            for index, row in enumerate(table_df.to_dict("records"), start=1)
        ]
    )
    with st.container(border=True):
        render_section_header("02", "申请物料清单", f"共 {len(preview_df)} 种物料")
        st.dataframe(
            preview_df,
            width="stretch",
            hide_index=True,
            height=min(820, max(150, 38 * (len(preview_df) + 1) + 18)),
            row_height=34,
        )

    shortage_rows = table_df[table_df["库存状态"] == "库存不足"]
    if not shortage_rows.empty:
        shortage_text = "；".join(
            f"{row['申请物料品类']} / {row['申请产品型号']} / {row['申请语种']}："
            f"申请 {int(row['申请数量'])}，当前库存 {int(row['当前库存'])}"
            for row in shortage_rows.to_dict("records")
        )
        st.error(f"库存不足：{shortage_text}。仍可调整实际发放物料或数量后继续审批。")

    product_options = sorted(
        unique_preserve(
            list(inventory_context.get("products") or [])
            + list(table_df["实际发放品类"].astype(str))
        )
    )
    model_options = unique_preserve(
        [NO_MODEL_TEXT]
        + sort_models(
            list(inventory_context.get("models") or [])
            + list(table_df["实际发放型号"].astype(str))
        )
    )
    language_options = sort_languages(
        unique_preserve(
            list(inventory_context.get("languages") or [])
            + list(table_df["实际发放语种"].astype(str))
        )
    )

    render_section_header("03", "实际发放编辑", "请根据申请明细填写实际发放物料与数量")
    edited_rows: list[dict[str, object]] = []
    with st.form(f"approval_issue_form_{selected_request['record_id']}"):
        for row_index, row in enumerate(table_df.to_dict("records"), start=1):
            line_id = str(row["记录ID"])
            is_shortage = str(row.get("库存状态") or "") == "库存不足"
            with st.container(border=True):
                marker_class = (
                    "pudu-approval-line-marker pudu-approval-line-shortage"
                    if is_shortage
                    else "pudu-approval-line-marker"
                )
                badge_class = "pudu-approval-stock-badge is-shortage" if is_shortage else "pudu-approval-stock-badge"
                st.markdown(
                    f"""
                    <span class="{marker_class}"></span>
                    <div class="pudu-approval-line-heading">
                        <span class="pudu-approval-line-title">{escape(ui_text("明细编号"))} {row_index:02d}</span>
                        <span class="{badge_class}">{escape(ui_text(str(row["库存状态"])))}</span>
                    </div>
                    <div class="pudu-approval-line-reference">
                        {escape(str(row["申请物料品类"]))} / {escape(str(row["申请产品型号"]))} /
                        {escape(str(row["申请语种"]))} · {escape(ui_text("申请数量"))} {int(row["申请数量"])}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                actual_cols = st.columns([2.8, 1.25, 1.35, 0.7], gap="small")
                product_key = f"approval_actual_product_{selected_request['record_id']}_{line_id}"
                model_key = f"approval_actual_model_{selected_request['record_id']}_{line_id}"
                language_key = f"approval_actual_language_{selected_request['record_id']}_{line_id}"
                quantity_key = f"approval_actual_quantity_{selected_request['record_id']}_{line_id}"
                initial_product = str(row.get("实际发放品类") or product_options[0])
                initial_model = str(row.get("实际发放型号") or model_options[0])
                initial_language = str(row.get("实际发放语种") or language_options[0])
                if st.session_state.get(product_key) not in product_options:
                    st.session_state[product_key] = initial_product if initial_product in product_options else product_options[0]
                if st.session_state.get(model_key) not in model_options:
                    st.session_state[model_key] = initial_model if initial_model in model_options else model_options[0]
                if st.session_state.get(language_key) not in language_options:
                    st.session_state[language_key] = (
                        initial_language if initial_language in language_options else language_options[0]
                    )
                if quantity_key not in st.session_state:
                    st.session_state[quantity_key] = int(row.get("实际发放数量") or 0)

                render_approval_control_label(actual_cols[0], "实际发放品类")
                actual_product = actual_cols[0].selectbox(
                    "实际发放品类",
                    product_options,
                    key=product_key,
                    label_visibility="collapsed",
                )
                render_approval_control_label(actual_cols[1], "实际发放型号")
                actual_model = actual_cols[1].selectbox(
                    "实际发放型号",
                    model_options,
                    key=model_key,
                    label_visibility="collapsed",
                )
                render_approval_control_label(actual_cols[2], "实际发放语种")
                actual_language = actual_cols[2].selectbox(
                    "实际发放语种",
                    language_options,
                    key=language_key,
                    label_visibility="collapsed",
                )
                render_approval_control_label(actual_cols[3], "实际发放数量")
                actual_quantity = actual_cols[3].number_input(
                    "实际发放数量",
                    min_value=0,
                    max_value=1_000_000,
                    step=1,
                    key=quantity_key,
                    label_visibility="collapsed",
                    help="填写实际发放数量并保存后，系统会按该数量更新物料库存。",
                )
                edited_rows.append(
                    {
                        "记录ID": line_id,
                        "实际发放品类": actual_product,
                        "实际发放型号": actual_model,
                        "实际发放语种": actual_language,
                        "实际发放数量": int(actual_quantity),
                    }
                )
        issue_note = st.text_input("审批/发放备注", key=f"approval_issue_note_{selected_request['record_id']}")
        submitted = st.form_submit_button(
            "保存实际发放并扣减库存",
            type="primary",
            icon=":material/check_circle:",
            width="stretch",
        )

    if submitted:
        edited_by_id = {str(row["记录ID"]): row for row in edited_rows}
        issue_lines: list[dict[str, object]] = []
        for line in selected_lines:
            row = edited_by_id.get(str(line["record_id"]))
            if not row:
                continue
            next_line = dict(line)
            next_line["previous_actual_issue_qty"] = int(line.get("actual_issue_qty") or 0)
            next_line["previous_product"] = str(line.get("actual_product") or line["product"])
            next_line["previous_model"] = str(line.get("actual_model") or line["model"])
            next_line["previous_language"] = str(line.get("actual_language") or line["language"])
            next_line["product"] = str(row.get("实际发放品类") or "").strip()
            next_line["model"] = str(row.get("实际发放型号") or NO_MODEL_TEXT).strip() or NO_MODEL_TEXT
            next_line["language"] = str(row.get("实际发放语种") or "").strip()
            next_line["actual_issue_qty"] = int(row.get("实际发放数量") or 0)
            issue_lines.append(next_line)
        invalid_lines = [
            line
            for line in issue_lines
            if (str(line["product"]), str(line["model"]), str(line["language"])) not in inventory_by_key
        ]
        if invalid_lines:
            invalid_text = "；".join(
                f"{line['product']} / {line['model']} / {line['language']}" for line in invalid_lines
            )
            st.error(f"以下实际发放组合不存在或已停用：{invalid_text}")
            return
        with st.spinner("正在发放并更新库存，请稍后......"):
            with DATA_LOCK:
                try:
                    logs = issue_request_lines(selected_request, issue_lines, issue_note)
                except Exception as exc:
                    st.error("审批发放失败。请检查实际发放数量、申请明细字段和飞书写入权限。")
                    st.exception(exc)
                    return
        completion_notification_count = 0
        completion_notification_warning = ""
        updated_request = dict(selected_request)
        updated_request["status"] = (
            REQUEST_STATUS_ISSUED
            if issue_lines
            and all(
                int(line.get("actual_issue_qty") or 0) >= int(line.get("quantity") or 0)
                for line in issue_lines
            )
            else REQUEST_STATUS_PARTIAL
        )
        with st.spinner("审批已保存，正在向申请人发送结果......"):
            try:
                completion_notification_count = notify_sales_request_completed(
                    updated_request,
                    issue_lines,
                    issue_note,
                )
            except Exception as exc:
                completion_notification_warning = (
                    f"审批已成功，但申请人结果通知发送失败：{exc}"
                )
        refresh_page_cache_after_write("approval", update_request_form=True)
        st.session_state.pop(APPROVAL_LIVE_DATA_KEY, None)
        notification_text = (
            "已向申请人发送审批结果。" if completion_notification_count else ""
        )
        st.session_state["approval_issue_message"] = (
            f"已完成申请单 {selected_request['request_no']} 的审批，"
            f"新增 {len(logs)} 条库存流水。{notification_text}"
        )
        if completion_notification_warning:
            st.session_state["approval_issue_warning"] = completion_notification_warning
        st.rerun()


def render_approval_history(
    history_requests: list[dict[str, object]],
    history_line_map: dict[str, list[dict[str, object]]],
) -> None:
    if not history_requests:
        st.info("暂无历史审批记录。")
        return

    render_section_header("02", "历史审批记录", "查看已完成审批及对应发放明细")
    history_rows: list[dict[str, object]] = []
    for request in history_requests:
        lines = history_line_map.get(str(request["record_id"]), [])
        history_rows.append(
            {
                "审批时间": request.get("approved_at") or request.get("submitted_at") or "-",
                "申请单号": request.get("request_no") or "-",
                "标题": request.get("title") or "-",
                "申请人": request.get("requester") or "-",
                "客户": request.get("customer_name") or "-",
                "国家": request.get("country") or "-",
                "物料用途": request.get("material_usage") or "-",
                "审批状态": request.get("status") or "-",
                "明细数": len(lines),
                "申请总数": sum(int(line.get("quantity") or 0) for line in lines),
                "实际发放总数": sum(int(line.get("actual_issue_qty") or 0) for line in lines),
                "审批意见": request.get("approval_comment") or "-",
            }
        )
    history_df = pd.DataFrame(history_rows)
    st.dataframe(
        history_df.style.apply(lambda row: partial_approval_row_style(row, "审批状态"), axis=1),
        width="stretch",
        hide_index=True,
        height=320,
    )

    option_labels = [
        f"{request['request_no']} | {request.get('status') or '未设置状态'} | "
        f"{request.get('approved_at') or request.get('submitted_at') or '-'}"
        for request in history_requests
    ]
    selected_label = st.selectbox("查看历史审批明细", option_labels, key="approval_history_selector")
    selected_request = history_requests[option_labels.index(selected_label)]
    selected_lines = history_line_map.get(str(selected_request["record_id"]), [])
    if str(selected_request.get("status")) == REQUEST_STATUS_PARTIAL:
        st.warning("该申请单为部分发放，审批已经完成。")
    render_approval_request_context(selected_request, selected_lines)

    detail_df = pd.DataFrame(
        [
            {
                "明细编号": line.get("record_id") or "-",
                "物料品类": line.get("product") or "-",
                "产品型号": line.get("model") or NO_MODEL_TEXT,
                "语种": line.get("language") or "-",
                "实际发放品类": line.get("actual_product") or line.get("product") or "-",
                "实际发放型号": line.get("actual_model") or line.get("model") or NO_MODEL_TEXT,
                "实际发放语种": line.get("actual_language") or line.get("language") or "-",
                "申请数量": int(line.get("quantity") or 0),
                "审批通过数量": int(line.get("approved_qty") or 0),
                "实际发放数量": int(line.get("actual_issue_qty") or 0),
                "明细状态": (
                    REQUEST_LINE_STATUS_PARTIAL
                    if str(selected_request.get("status")) == REQUEST_STATUS_PARTIAL
                    and str(line.get("status", "")) != REQUEST_LINE_STATUS_ISSUED
                    else line.get("status") or "-"
                ),
                "备注": line.get("remark") or line.get("usage") or "-",
            }
            for line in selected_lines
        ]
    )
    if detail_df.empty:
        st.info("该申请单暂无可显示的审批明细。")
        return
    st.dataframe(
        detail_df.style.apply(lambda row: partial_approval_row_style(row, "明细状态"), axis=1),
        width="stretch",
        hide_index=True,
        height=360,
    )


def render_approval_view(*, refresh_on_open: bool = False) -> None:
    render_page_header(
        "营销物料审批与发放",
        "审批工作台",
        "核对申请明细、登记实际发放数量并同步库存流水。",
    )
    if not admin_auth_gate():
        return
    live_data = render_approval_live_toolbar(refresh_on_open=refresh_on_open)

    message = st.session_state.pop("approval_issue_message", "")
    if message:
        st.success(message)
    warning = st.session_state.pop("approval_issue_warning", "")
    if warning:
        st.warning(warning)

    requests = load_feishu_request_records(list(live_data.get("request_rows") or []))
    all_lines = load_feishu_request_line_records(
        list(live_data.get("line_rows") or []),
        list(live_data.get("material_rows") or []),
    )
    inventory_context = approval_inventory_context(live_data)
    pending_line_statuses = {REQUEST_LINE_STATUS_PENDING, "待发放", "已通过", ""}
    completed_line_statuses = {REQUEST_LINE_STATUS_PARTIAL, REQUEST_LINE_STATUS_ISSUED}
    completed_request_statuses = {
        REQUEST_STATUS_PARTIAL,
        REQUEST_STATUS_ISSUED,
        "已审批",
        "审批通过",
        "已完成",
    }
    active_requests: list[dict[str, object]] = []
    active_line_map: dict[str, list[dict[str, object]]] = {}
    history_requests: list[dict[str, object]] = []
    history_line_map: dict[str, list[dict[str, object]]] = {}
    for request in requests:
        request_id = str(request["record_id"])
        request_lines = request_lines_for_request(request, all_lines)
        line_statuses = {str(line.get("status", "")) for line in request_lines}
        request_status = str(request.get("status", ""))
        is_history = request_status in completed_request_statuses or (
            bool(line_statuses) and line_statuses.issubset(completed_line_statuses)
        )
        if is_history:
            history_requests.append(request)
            history_line_map[request_id] = request_lines
            continue
        pending_lines = [line for line in request_lines if str(line.get("status", "")) in pending_line_statuses]
        if pending_lines:
            active_requests.append(request)
            active_line_map[request_id] = pending_lines

    approval_metric_a, approval_metric_b, approval_metric_c, approval_metric_d = st.columns(4)
    approval_metric_a.metric("待审批申请", f"{len(active_requests):,}")
    approval_metric_b.metric("待处理明细", f"{sum(len(lines) for lines in active_line_map.values()):,}")
    approval_metric_c.metric("历史申请", f"{len(history_requests):,}")
    approval_metric_d.metric(
        "历史发放数量",
        f"{sum(int(line.get('actual_issue_qty') or 0) for lines in history_line_map.values() for line in lines):,}",
    )

    pending_tab, history_tab = st.tabs(["待审批发放", "历史审批记录"])
    with pending_tab:
        render_pending_approval_requests(active_requests, active_line_map, inventory_context)
    with history_tab:
        render_approval_history(history_requests, history_line_map)


def render_inventory_view() -> None:
    render_page_header(
        "实时物料库存表",
        "库存视图",
        "按物料品类、产品型号和语种查看当前库存与价值。",
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


@st.cache_data(show_spinner=False)
def load_warehouse_location_cache() -> dict[str, object]:
    if not WAREHOUSE_LOCATION_CACHE_PATH.exists():
        return {"schema_version": 1, "generated_at": "", "shelves": []}
    data = json.loads(WAREHOUSE_LOCATION_CACHE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("shelves"), list):
        raise RuntimeError("仓库位置静态缓存文件格式不正确。")
    return data


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
        and (Path(__file__).resolve().parent / str(image.get("path") or "")).exists()
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
        image_path = Path(__file__).resolve().parent / str(image.get("path") or "")
        image_columns[index % len(image_columns)].image(
            str(image_path),
            caption=f"{caption} · {index + 1}",
            width="stretch",
        )


def render_warehouse_location_view() -> None:
    english = get_ui_language() == LANGUAGE_EN
    render_page_header(
        "物料仓库位置查询",
        "仓库位置图集",
        "按物料、型号、语种、货架编号或位置说明查询存放位置。",
        status="静态位置缓存",
    )
    cache = load_warehouse_location_cache()
    shelves = [dict(item) for item in list(cache.get("shelves") or []) if isinstance(item, dict)]
    st.info("本页面仅用于查询物料存放位置。如需拿取物料，请先提交物料申请。")
    generated_at = str(cache.get("generated_at") or ("Not recorded" if english else "未记录"))
    st.caption(
        f"Source: manually published static cache  Updated: {generated_at}  This page does not automatically sync Feishu data."
        if english
        else f"位置数据来源：人工发布的静态缓存　更新时间：{generated_at}　页面不会自动同步飞书数据。"
    )
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


def render_management_page() -> None:
    current_section = str(st.session_state.get(MANAGEMENT_NAVIGATION_KEY, "库存登记"))
    if current_section == "新增物料品类":
        st.session_state[MATERIAL_MANAGEMENT_CONTROL_KEY] = "品类管理"
        current_section = "物料管理"
    elif current_section in {"品类管理", "物料数据库"}:
        st.session_state[MATERIAL_MANAGEMENT_CONTROL_KEY] = current_section
        current_section = "物料管理"
    if current_section not in {
        "库存登记",
        "物料管理",
        "修改与撤回",
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
            status="等待确认",
        )
        render_request_review()
        return
    page_copy = {
        "库存登记": ("营销物料领取登记", "申请工作台", "登记领取申请并提交至审批发放流程。"),
        "物料管理": ("物料管理", "库存工作台", "采购补库、品类维护与物料数据库统一管理。"),
        "修改与撤回": ("物料申请修改与撤回", "申请工作台", "实时读取待审批申请，修改申请信息或撤回申请单。"),
    }
    page_title, page_kicker, page_subtitle = page_copy.get(current_section, page_copy["库存登记"])
    render_page_header(page_title, page_kicker, page_subtitle)
    if management_section_requires_admin(current_section) and not admin_auth_gate():
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
        render_page_cache_toolbar(
            {
                "采购补库": "restock",
                "品类管理": "category",
                "物料数据库": "material_database",
            }[material_section]
        )
        if material_section == "采购补库":
            render_restock_form()
        elif material_section == "品类管理":
            render_add_category_form()
        else:
            render_material_database_page()
        return
    if st.session_state.get(MANAGEMENT_WORKBENCH_CONTROL_KEY) not in MANAGEMENT_WORKBENCH_SECTIONS:
        st.session_state[MANAGEMENT_WORKBENCH_CONTROL_KEY] = current_section
    management_section = st.radio(
        "管理功能",
        MANAGEMENT_WORKBENCH_SECTIONS,
        horizontal=True,
        label_visibility="collapsed",
        key=MANAGEMENT_WORKBENCH_CONTROL_KEY,
        on_change=sync_management_section_from_workbench_control,
    )
    set_management_section(management_section, sync_workbench_control=False)
    if management_section == "库存登记":
        render_page_cache_toolbar("request")
        render_change_form(show_title=False)
    else:
        render_edit_revert_page()


def render_management_page_with_navigation_loading() -> None:
    loading_section = str(st.session_state.pop(MANAGEMENT_NAVIGATION_LOADING_KEY, ""))
    if not management_navigation_uses_loading_overlay(loading_section):
        render_management_page()
        return

    started_at = time.monotonic()
    with st.spinner("物料数据加载中，请稍后......"):
        render_management_page()
        # Streamlit delays short-lived spinners to prevent flicker. Keep this
        # navigation overlay alive long enough to provide visible feedback.
        remaining = 0.75 - (time.monotonic() - started_at)
        if remaining > 0:
            time.sleep(remaining)


def main() -> None:
    install_streamlit_ui_translation(st, get_ui_language)
    st.set_page_config(
        page_title=ui_text("营销物料管理系统"),
        page_icon=str(APP_ICON_PATH) if APP_ICON_PATH.exists() else ":material/inventory_2:",
        layout="wide",
        initial_sidebar_state="auto",
    )
    inject_global_styles()
    stop_on_invalid_feishu_config()
    render_sidebar_link()

    view = str(st.query_params.get("view", ""))
    previous_view = str(st.session_state.get(LAST_APP_VIEW_KEY, ""))
    entering_approval = view == "approval" and previous_view != "approval"
    st.session_state[LAST_APP_VIEW_KEY] = view
    try:
        if view == "inventory":
            render_inventory_view()
        elif view == "warehouse":
            render_warehouse_location_view()
        elif view == "approval":
            render_approval_view(refresh_on_open=entering_approval)
        else:
            render_management_page_with_navigation_loading()
    except FeishuBitableError as exc:
        render_feishu_error(exc)


if __name__ == "__main__":
    main()
