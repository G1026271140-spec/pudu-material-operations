from __future__ import annotations

import csv
import json
import re
import threading
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
INVENTORY_XLSX = DATA_DIR / "inventory.xlsx"
INVENTORY_CSV = DATA_DIR / "inventory.csv"
OPTIONS_JSON = DATA_DIR / "options.json"
TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"

DEFAULT_PASSWORD = "376493"
NO_MODEL_TEXT = "无需型号"
ACTION_RECEIVE = "物料领取（减少库存）"
ACTION_PURCHASE = "物料采购（增加库存）"
ACTION_OPTIONS = [ACTION_RECEIVE, ACTION_PURCHASE]
DECREASE_ACTIONS = {ACTION_RECEIVE, "出库减少"}
INCREASE_ACTIONS = {ACTION_PURCHASE, "入库增加"}

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


def get_secret_value(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default)).strip()
    except (FileNotFoundError, KeyError, AttributeError):
        return default


def supabase_url() -> str:
    return get_secret_value("SUPABASE_URL")


def supabase_service_role_key() -> str:
    return get_secret_value("SUPABASE_SERVICE_ROLE_KEY")


def legacy_supabase_key() -> str:
    return get_secret_value("SUPABASE_KEY")


def supabase_configured() -> bool:
    return bool(supabase_url() and supabase_service_role_key())


def stop_on_invalid_supabase_config() -> None:
    url = supabase_url()
    service_key = supabase_service_role_key()
    legacy_key = legacy_supabase_key()

    if not url and not service_key and not legacy_key:
        return

    if url and service_key:
        return

    if legacy_key and not service_key:
        st.error(
            "检测到 Supabase 配置不完整：请使用 `SUPABASE_SERVICE_ROLE_KEY`，不要使用 `SUPABASE_KEY`/anon/public key。"
        )
    elif service_key and not url:
        st.error("检测到 `SUPABASE_SERVICE_ROLE_KEY`，但缺少 `SUPABASE_URL`。")
    else:
        st.error("Supabase 配置不完整：请同时填写 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`。")

    st.info(
        "请在 Streamlit Secrets 中填写 service_role/secret key；这个密钥只放在 Secrets，不能提交到 GitHub。"
    )
    st.stop()


@st.cache_resource(show_spinner=False)
def get_supabase_client(url: str, key: str):
    from supabase import create_client

    return create_client(url, key)


def supabase_client():
    url = supabase_url()
    key = supabase_service_role_key()
    if not url or not key:
        return None
    return get_supabase_client(url, key)


def storage_mode_label() -> str:
    if supabase_url() and not supabase_service_role_key():
        return "Supabase 配置不完整"
    return "Supabase 长期数据库" if supabase_configured() else "本地 Excel 文件"


def count_supabase_table(table: str) -> int | None:
    client = supabase_client()
    if client is None:
        return None
    response = client.table(table).select("id", count="exact").limit(1).execute()
    return response.count


def render_storage_diagnostics() -> None:
    with st.sidebar.expander("存储状态", expanded=True):
        st.write(f"当前存储：**{storage_mode_label()}**")
        st.write(f"SUPABASE_URL：{'已读取' if bool(supabase_url()) else '未读取'}")
        st.write(f"SUPABASE_SERVICE_ROLE_KEY：{'已读取' if bool(supabase_service_role_key()) else '未读取'}")
        if legacy_supabase_key():
            st.warning("检测到 SUPABASE_KEY。请删除它，只保留 SUPABASE_SERVICE_ROLE_KEY。")

        if supabase_configured():
            try:
                categories_count = count_supabase_table("material_categories")
                inventory_count = count_supabase_table("inventory_items")
                transactions_count = count_supabase_table("inventory_transactions")
                st.success("Supabase 连接成功")
                st.caption(
                    f"品类 {categories_count or 0} 条 / 库存 {inventory_count or 0} 条 / 流水 {transactions_count or 0} 条"
                )
            except Exception as exc:
                st.error("Supabase 连接失败")
                st.caption(str(exc))
        else:
            st.info("未启用 Supabase 时，应用会读取本地 Excel。")

        if st.button("重新检查连接", key="refresh_storage_status", width="stretch"):
            st.session_state.pop("supabase_seed_checked", None)
            st.cache_resource.clear()
            st.rerun()


def ensure_data() -> None:
    if INVENTORY_XLSX.exists() and OPTIONS_JSON.exists():
        return
    from scripts.generate_inventory import main as generate_inventory

    generate_inventory()


def load_local_options() -> dict:
    ensure_data()
    return json.loads(OPTIONS_JSON.read_text(encoding="utf-8"))


def save_local_options(options: dict) -> None:
    OPTIONS_JSON.write_text(
        json.dumps(options, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def day_start(value: date) -> str:
    return datetime.combine(value, time.min).isoformat()


def day_end(value: date) -> str:
    return datetime.combine(value, time.max).isoformat()


def format_datetime(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value or "")
    return parsed.strftime("%Y-%m-%d %H:%M")


def transaction_status(row: dict) -> str:
    if row.get("reversed_at"):
        return "已撤回"
    if row.get("reversal_of"):
        return "撤回记录"
    return "有效"


def selected_ids_from_editor(df: pd.DataFrame, id_column: str = "ID") -> list[int]:
    if df.empty or "选择" not in df.columns or id_column not in df.columns:
        return []
    selected = df[df["选择"].fillna(False)]
    return [int(value) for value in selected[id_column].tolist()]


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


def navigate_to_management(key: str, label: str = "返回库存管理") -> None:
    if st.button(label, key=key, width="stretch"):
        st.query_params.clear()
        st.rerun()


def load_local_inventory() -> pd.DataFrame:
    ensure_data()
    df = pd.read_excel(INVENTORY_XLSX, keep_default_na=False)
    for column in INVENTORY_HEADERS:
        if column not in df.columns:
            df[column] = "" if column != QTY_COL else 0
    for column in ["物料编码", PRODUCT_COL, MODEL_COL, LANGUAGE_COL, UPDATED_COL]:
        df[column] = df[column].fillna("").astype(str)
    df[QTY_COL] = pd.to_numeric(df[QTY_COL], errors="coerce").fillna(0).astype(int)
    df[PRICE_COL] = pd.to_numeric(df[PRICE_COL], errors="coerce").fillna(0)
    df[VALUE_COL] = df[QTY_COL] * df[PRICE_COL]
    return df[INVENTORY_HEADERS]


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


def save_local_inventory(df: pd.DataFrame) -> None:
    df = df[INVENTORY_HEADERS].copy()
    for column in ["物料编码", PRODUCT_COL, MODEL_COL, LANGUAGE_COL, UPDATED_COL]:
        df[column] = df[column].fillna("").astype(str)
    df[QTY_COL] = pd.to_numeric(df[QTY_COL], errors="coerce").fillna(0).astype(int)
    df[PRICE_COL] = pd.to_numeric(df[PRICE_COL], errors="coerce").fillna(0)
    df[VALUE_COL] = df[QTY_COL] * df[PRICE_COL]

    INVENTORY_XLSX.write_bytes(workbook_bytes(df))
    df.to_csv(INVENTORY_CSV, index=False, encoding="utf-8-sig")


def append_local_transactions(rows: list[list[object]]) -> None:
    if not TRANSACTIONS_CSV.exists():
        with TRANSACTIONS_CSV.open("w", encoding="utf-8-sig", newline="") as file:
            csv.writer(file).writerow(TRANSACTION_HEADERS)

    with TRANSACTIONS_CSV.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(rows)


def select_all_supabase_rows(table: str, columns: str = "*", order: str | None = None) -> list[dict]:
    client = supabase_client()
    if client is None:
        return []

    rows: list[dict] = []
    start = 0
    page_size = 1000
    while True:
        query = client.table(table).select(columns)
        if order:
            query = query.order(order)
        response = query.range(start, start + page_size - 1).execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def inventory_df_to_supabase_records(df: pd.DataFrame) -> list[dict]:
    normalized = df[INVENTORY_HEADERS].copy()
    normalized[QTY_COL] = pd.to_numeric(normalized[QTY_COL], errors="coerce").fillna(0).astype(int)
    normalized[PRICE_COL] = pd.to_numeric(normalized[PRICE_COL], errors="coerce").fillna(0)

    records: list[dict] = []
    for row in normalized.itertuples(index=False):
        records.append(
            {
                "material_code": str(row[0]),
                "category": str(row[1]),
                "model": str(row[2]) or NO_MODEL_TEXT,
                "language": str(row[3]),
                "quantity": int(row[4]),
                "unit_price": float(row[5]),
            }
        )
    return records


def upsert_supabase_categories(options: dict) -> None:
    client = supabase_client()
    if client is None:
        return

    no_model_products = set(options.get("no_model_products", []))
    for product in options.get("products", []):
        save_supabase_category(str(product), str(product) in no_model_products)


def save_supabase_category(product: str, no_model: bool) -> None:
    client = supabase_client()
    if client is None:
        return

    product = product.strip()
    existing = (
        client.table("material_categories")
        .select("id")
        .eq("category", product)
        .limit(1)
        .execute()
    )
    if existing.data:
        client.table("material_categories").update({"no_model": bool(no_model)}).eq("category", product).execute()
    else:
        client.table("material_categories").insert({"category": product, "no_model": bool(no_model)}).execute()


def save_supabase_inventory(df: pd.DataFrame) -> None:
    client = supabase_client()
    if client is None:
        return

    records = inventory_df_to_supabase_records(df)
    for start in range(0, len(records), 500):
        client.table("inventory_items").upsert(
            records[start : start + 500],
            on_conflict="material_code",
        ).execute()


def insert_supabase_inventory(df: pd.DataFrame) -> None:
    client = supabase_client()
    if client is None:
        return

    records = inventory_df_to_supabase_records(df)
    for start in range(0, len(records), 500):
        client.table("inventory_items").insert(records[start : start + 500]).execute()


def add_supabase_material_category_payload(product: str, no_model: bool, df: pd.DataFrame) -> int:
    client = supabase_client()
    if client is None:
        return 0

    payload = {
        "category": product.strip(),
        "no_model": bool(no_model),
        "items": inventory_df_to_supabase_records(df),
    }
    response = client.rpc("add_material_category_payload", {"p_payload": payload}).execute()
    result = (response.data or [{}])[0]
    return int(result.get("inserted_count") or 0)


def ensure_supabase_seeded() -> None:
    if not supabase_configured():
        return
    if st.session_state.get("supabase_seed_checked"):
        return

    client = supabase_client()
    if client is None:
        return

    try:
        existing = client.table("inventory_items").select("material_code").limit(1).execute()
    except Exception as exc:
        error_text = str(exc)
        if "permission denied" in error_text or "42501" in error_text:
            st.error("Supabase 已连接，但当前密钥没有表权限。通常是 Streamlit Secrets 里填成了 anon/public key。")
            st.info("请把 `SUPABASE_SERVICE_ROLE_KEY` 改成 Supabase 的 service_role/secret key，然后重启应用。")
        else:
            st.error("Supabase 数据表还没有准备好。请先在 Supabase SQL Editor 运行 `supabase/schema.sql`。")
        st.exception(exc)
        st.stop()

    if not existing.data:
        local_options = load_local_options()
        local_df = load_local_inventory()
        upsert_supabase_categories(local_options)
        save_supabase_inventory(local_df)

    st.session_state["supabase_seed_checked"] = True


def load_supabase_inventory() -> pd.DataFrame:
    ensure_supabase_seeded()
    rows = select_all_supabase_rows("inventory_items", "*", order="material_code")
    data = []
    for row in rows:
        quantity = int(row.get("quantity") or 0)
        unit_price = float(row.get("unit_price") or 0)
        data.append(
            [
                row.get("material_code", ""),
                row.get("category", ""),
                row.get("model") or NO_MODEL_TEXT,
                row.get("language", ""),
                quantity,
                unit_price,
                quantity * unit_price,
                row.get("updated_at", "") or "",
            ]
        )
    return pd.DataFrame(data, columns=INVENTORY_HEADERS)


def load_supabase_options() -> dict:
    ensure_supabase_seeded()
    categories = select_all_supabase_rows("material_categories", "category,no_model,created_at", order="created_at")
    df = load_supabase_inventory()
    products = [row["category"] for row in categories if row.get("category")]
    if not products:
        products = unique_preserve(list(df[PRODUCT_COL].astype(str)))

    category_no_model_products = [row["category"] for row in categories if row.get("no_model")]
    local_no_model_products = load_local_options().get("no_model_products", [])
    inventory_no_model_products: list[str] = []
    if not df.empty:
        inventory_no_model_products = unique_preserve(
            list(df.loc[df[MODEL_COL] == NO_MODEL_TEXT, PRODUCT_COL].astype(str))
        )
    no_model_products = unique_preserve(
        category_no_model_products + inventory_no_model_products + local_no_model_products
    )
    models = unique_preserve([value for value in df[MODEL_COL].astype(str) if value and value != NO_MODEL_TEXT])
    languages = unique_preserve(list(df[LANGUAGE_COL].astype(str)))
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "products": products,
        "no_model_products": no_model_products,
        "models": models,
        "languages": languages,
        "no_model_text": NO_MODEL_TEXT,
        "row_count": len(df),
    }


def load_options() -> dict:
    if supabase_configured():
        return load_supabase_options()
    return load_local_options()


def save_options(options: dict) -> None:
    if supabase_configured():
        upsert_supabase_categories(options)
        return
    save_local_options(options)


def load_inventory() -> pd.DataFrame:
    if supabase_configured():
        return load_supabase_inventory()
    return load_local_inventory()


def save_inventory(df: pd.DataFrame) -> None:
    if supabase_configured():
        save_supabase_inventory(df)
        return
    save_local_inventory(df)


def append_supabase_transactions(rows: list[list[object]]) -> None:
    client = supabase_client()
    if client is None or not rows:
        return
    records = []
    for row in rows:
        records.append(
            {
                "created_at": row[0],
                "action": row[1],
                "category": row[2],
                "model": row[3] or NO_MODEL_TEXT,
                "language": row[4],
                "quantity": int(row[5]),
                "before_quantity": int(row[6]),
                "after_quantity": int(row[7]),
                "note": row[8],
            }
        )
    client.table("inventory_transactions").insert(records).execute()


def append_transactions(rows: list[list[object]]) -> None:
    if supabase_configured():
        append_supabase_transactions(rows)
        return
    append_local_transactions(rows)


def load_transactions_dataframe() -> pd.DataFrame:
    if not supabase_configured():
        if TRANSACTIONS_CSV.exists():
            return pd.read_csv(TRANSACTIONS_CSV, keep_default_na=False)
        return pd.DataFrame(columns=TRANSACTION_HEADERS)

    rows = select_all_supabase_rows("inventory_transactions", "*", order="created_at")
    data = []
    for row in rows:
        data.append(
            [
                row.get("created_at", ""),
                row.get("action", ""),
                row.get("category", ""),
                row.get("model") or NO_MODEL_TEXT,
                row.get("language", ""),
                int(row.get("quantity") or 0),
                int(row.get("before_quantity") or 0),
                int(row.get("after_quantity") or 0),
                row.get("note", "") or "",
            ]
        )
    return pd.DataFrame(data, columns=TRANSACTION_HEADERS)


def apply_supabase_changes(changes: list[dict[str, object]]) -> list[list[object]]:
    client = supabase_client()
    if client is None:
        return []

    logs: list[list[object]] = []
    for item in changes:
        response = client.rpc(
            "apply_inventory_change",
            {
                "p_action": str(item["action"]),
                "p_category": str(item["product"]),
                "p_model": str(item["model"]) or NO_MODEL_TEXT,
                "p_language": str(item["language"]),
                "p_quantity": int(item["quantity"]),
                "p_note": str(item["note"]).strip(),
            },
        ).execute()
        result = (response.data or [{}])[0]
        logs.append(
            [
                result.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                result.get("action", item["action"]),
                result.get("category", item["product"]),
                result.get("model") or NO_MODEL_TEXT,
                result.get("language", item["language"]),
                int(result.get("quantity", item["quantity"]) or 0),
                int(result.get("before_quantity", 0) or 0),
                int(result.get("after_quantity", 0) or 0),
                result.get("note", item["note"]) or "",
            ]
        )
    return logs


def rpc_rows_to_transaction_logs(rows: list[dict]) -> list[list[object]]:
    logs: list[list[object]] = []
    for row in rows:
        logs.append(
            [
                row.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                row.get("action", ""),
                row.get("category", ""),
                row.get("model") or NO_MODEL_TEXT,
                row.get("language", ""),
                int(row.get("quantity", 0) or 0),
                int(row.get("before_quantity", 0) or 0),
                int(row.get("after_quantity", 0) or 0),
                row.get("note", "") or "",
            ]
        )
    return logs


def load_supabase_transaction_records(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 1000,
) -> list[dict]:
    client = supabase_client()
    if client is None:
        return []
    query = client.table("inventory_transactions").select(
        "id,created_at,action,category,model,language,quantity,before_quantity,after_quantity,note,reversed_at,reversal_of"
    )
    if start_date:
        query = query.gte("created_at", day_start(start_date))
    if end_date:
        query = query.lte("created_at", day_end(end_date))
    response = query.order("created_at", desc=True).limit(limit).execute()
    return response.data or []


def load_supabase_inventory_records(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 2000,
) -> list[dict]:
    client = supabase_client()
    if client is None:
        return []
    query = client.table("inventory_items").select("*")
    if start_date:
        query = query.gte("created_at", day_start(start_date))
    if end_date:
        query = query.lte("created_at", day_end(end_date))
    response = query.order("created_at", desc=True).limit(limit).execute()
    return response.data or []


def load_supabase_category_records(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 1000,
) -> list[dict]:
    client = supabase_client()
    if client is None:
        return []
    query = client.table("material_categories").select("id,category,no_model,created_at")
    if start_date:
        query = query.gte("created_at", day_start(start_date))
    if end_date:
        query = query.lte("created_at", day_end(end_date))
    response = query.order("created_at", desc=True).limit(limit).execute()
    return response.data or []


def revert_supabase_transaction(transaction_id: int, note: str) -> list[list[object]]:
    client = supabase_client()
    if client is None:
        return []
    response = client.rpc(
        "revert_inventory_transaction",
        {"p_transaction_id": int(transaction_id), "p_note": note.strip()},
    ).execute()
    return rpc_rows_to_transaction_logs(response.data or [])


def replace_supabase_transaction(
    transaction_id: int,
    action: str,
    product: str,
    model: str,
    language: str,
    quantity: int,
    note: str,
) -> list[list[object]]:
    client = supabase_client()
    if client is None:
        return []
    response = client.rpc(
        "replace_inventory_transaction",
        {
            "p_transaction_id": int(transaction_id),
            "p_action": action,
            "p_category": product,
            "p_model": model or NO_MODEL_TEXT,
            "p_language": language,
            "p_quantity": int(quantity),
            "p_note": note.strip(),
        },
    ).execute()
    return rpc_rows_to_transaction_logs(response.data or [])


def update_supabase_inventory_item(
    item_id: int,
    material_code: str,
    product: str,
    model: str,
    language: str,
) -> None:
    client = supabase_client()
    if client is None:
        return
    product = product.strip()
    model = model.strip() or NO_MODEL_TEXT
    language = language.strip()
    client.table("inventory_items").update(
        {
            "material_code": material_code.strip(),
            "category": product,
            "model": model,
            "language": language,
            "updated_at": datetime.now().isoformat(),
        }
    ).eq("id", int(item_id)).execute()
    save_supabase_category(product, model == NO_MODEL_TEXT)


def count_supabase_item_transactions(product: str, model: str, language: str) -> int:
    client = supabase_client()
    if client is None:
        return 0
    response = (
        client.table("inventory_transactions")
        .select("id", count="exact")
        .eq("category", product)
        .eq("model", model or NO_MODEL_TEXT)
        .eq("language", language)
        .limit(1)
        .execute()
    )
    return int(response.count or 0)


def delete_supabase_inventory_item(item_id: int) -> None:
    client = supabase_client()
    if client is None:
        return
    client.table("inventory_items").delete().eq("id", int(item_id)).execute()


def count_supabase_category_transactions(product: str) -> int:
    client = supabase_client()
    if client is None:
        return 0
    response = (
        client.table("inventory_transactions")
        .select("id", count="exact")
        .eq("category", product)
        .limit(1)
        .execute()
    )
    return int(response.count or 0)


def delete_supabase_category(product: str) -> None:
    client = supabase_client()
    if client is None:
        return
    client.table("inventory_items").delete().eq("category", product).execute()
    client.table("material_categories").delete().eq("category", product).execute()


def update_supabase_category(old_product: str, new_product: str, no_model: bool) -> None:
    client = supabase_client()
    if client is None:
        return
    old_product = old_product.strip()
    new_product = new_product.strip()
    client.table("inventory_items").update({"category": new_product}).eq("category", old_product).execute()
    client.table("material_categories").update(
        {"category": new_product, "no_model": bool(no_model)}
    ).eq("category", old_product).execute()


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


def render_sidebar_link() -> None:
    st.sidebar.subheader("实时库存链接")
    navigate_to_inventory("sidebar_open_inventory", "打开实时库存表")
    st.sidebar.caption("实时库存页只需要输入一次密码。部署后复制浏览器地址栏链接，即可分享给其他管理人。")
    st.sidebar.divider()
    st.sidebar.caption("多人共同管理时，请让所有人访问同一个已部署的 Streamlit 应用地址；本地端口只适合开发和测试。")


def get_row_count() -> int:
    return int(
        st.number_input(
            "本次填写物料种类数",
            min_value=1,
            max_value=30,
            value=3,
            step=1,
        )
    )


def render_change_form(show_title: bool = True) -> None:
    selection_context = build_inventory_selection_context()
    products = list(selection_context["products"])
    models = list(selection_context["models"])
    languages = list(selection_context["languages"])

    if show_title:
        st.title("营销物料领取登记")
    else:
        st.subheader("营销物料领取登记")
    st.caption("一次可以填写多种物料。")

    row_count = get_row_count()
    changes: list[dict[str, object]] = []

    with st.container(border=True):
        for index in range(row_count):
            st.markdown(f"**第 {index + 1} 项**")
            product_col, model_col, language_col, action_col, qty_col = st.columns([2.2, 1.5, 1.6, 1.2, 1.1])

            product = product_col.selectbox(
                "物料品类",
                products,
                key=f"product_{index}",
            )
            is_no_model_product, scoped_models = product_model_state(product, selection_context)
            if is_no_model_product:
                model_col.text_input(
                    "产品型号",
                    value=NO_MODEL_TEXT,
                    key=f"model_blank_{index}",
                    disabled=True,
                )
                model = NO_MODEL_TEXT
            else:
                model = model_col.selectbox(
                    "产品型号",
                    scoped_models or models,
                    key=f"model_{index}",
                )
            language_options = product_language_options(product, model, selection_context, languages)
            language = language_col.selectbox(
                "语种",
                language_options,
                key=f"language_{index}",
            )
            action = action_col.selectbox(
                "操作",
                ACTION_OPTIONS,
                key=f"action_{index}",
            )
            action_color = "#DC2626" if action == ACTION_RECEIVE else "#059669"
            action_col.markdown(
                f"<div style='height:8px'></div><div style='color:{action_color};font-weight:700;'>{action}</div>",
                unsafe_allow_html=True,
            )
            quantity = qty_col.number_input(
                "数量",
                min_value=0,
                max_value=1_000_000,
                value=0,
                step=1,
                key=f"quantity_{index}_{action}",
            )
            note = st.text_input("备注", key=f"note_{index}", placeholder="可选")
            changes.append(
                {
                    "product": product,
                    "model": model,
                    "language": language,
                    "action": action,
                    "quantity": int(quantity),
                    "note": note,
                }
            )

        submitted = st.button("提交更新", type="primary", width="stretch")

    if submitted:
        apply_changes(changes)


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
            selected_or_custom_models=unique_preserve(selected_models + custom_models),
            selected_or_custom_languages=languages,
        )


def add_material_category(
    product: str,
    models: list[str],
    languages: list[str],
    no_model: bool,
    selected_or_custom_models: list[str],
    selected_or_custom_languages: list[str],
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
        if supabase_configured():
            client = supabase_client()
            if client is None:
                st.error("Supabase 未配置成功。")
                return
            try:
                inserted_count = add_supabase_material_category_payload(product, no_model, new_df)
            except Exception as exc:
                st.error("新增物料品类写入 Supabase 失败。请先在 SQL Editor 运行最新的 `supabase/upgrade_material_category_json.sql`。")
                st.exception(exc)
                return
            if inserted_count <= 0:
                st.warning("没有写入新的库存行，可能这些组合已经存在。")
                return
        else:
            updated_df = pd.concat([df, new_df], ignore_index=True)
            save_inventory(updated_df)

            options["products"] = unique_preserve(options["products"] + [product])
            if no_model:
                options["no_model_products"] = unique_preserve(options["no_model_products"] + [product])
            else:
                options["models"] = unique_preserve(options["models"] + selected_or_custom_models)
            options["languages"] = unique_preserve(options["languages"] + selected_or_custom_languages)
            options["row_count"] = int(len(updated_df))
            options["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_options(options)

    skipped_text = f"，跳过 {len(skipped)} 条已存在组合" if skipped else ""
    st.session_state["category_added_message"] = f"已新增物料品类“{product}”，生成 {len(new_rows)} 条库存行{skipped_text}。"
    st.cache_data.clear()
    st.rerun()


def render_download_center(full_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    transactions_df = load_transactions_dataframe()
    transaction_data = transactions_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

    st.subheader("下载库存数据")
    st.caption("下载按钮导出的是当前 Streamlit 应用内保存的最新数据。")

    full_col_a, full_col_b, log_col = st.columns(3)
    full_col_a.download_button(
        "下载完整库存 Excel",
        data=workbook_bytes(full_df),
        file_name=f"完整物料库存表_{timestamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    full_col_b.download_button(
        "下载完整库存 CSV",
        data=full_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"完整物料库存表_{timestamp}.csv",
        mime="text/csv",
        width="stretch",
    )
    log_col.download_button(
        "下载库存变更流水",
        data=transaction_data,
        file_name=f"库存变更流水_{timestamp}.csv",
        mime="text/csv",
        width="stretch",
    )

    filtered_col_a, filtered_col_b = st.columns(2)
    filtered_col_a.download_button(
        "下载当前筛选 Excel",
        data=workbook_bytes(filtered_df),
        file_name=f"当前筛选物料库存表_{timestamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    filtered_col_b.download_button(
        "下载当前筛选 CSV",
        data=filtered_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"当前筛选物料库存表_{timestamp}.csv",
        mime="text/csv",
        width="stretch",
    )


def format_transaction_option(row: dict) -> str:
    status = "已撤回" if row.get("reversed_at") else ("撤回记录" if row.get("reversal_of") else "有效")
    return (
        f"#{row.get('id')} | {row.get('created_at', '')} | {status} | "
        f"{row.get('action', '')} | {row.get('category', '')} / {row.get('model') or NO_MODEL_TEXT} / "
        f"{row.get('language', '')} | {row.get('before_quantity', 0)} -> {row.get('after_quantity', 0)}"
    )


def format_inventory_item_option(row: dict) -> str:
    return (
        f"{row.get('material_code', '')} | {row.get('category', '')} / "
        f"{row.get('model') or NO_MODEL_TEXT} / {row.get('language', '')} | "
        f"库存 {int(row.get('quantity') or 0)}"
    )


def render_transaction_admin() -> None:
    st.subheader("库存提交记录修改与撤回")
    if not supabase_configured():
        st.info("该功能需要 Supabase 长期数据库。当前本地 Excel 模式下请通过下载的流水表人工核对。")
        return

    filter_col_a, filter_col_b, filter_col_c, filter_col_d = st.columns([1, 1, 1, 1])
    default_end = date.today()
    default_start = default_end - timedelta(days=30)
    start_date = filter_col_a.date_input("开始日期", value=default_start, key="tx_start_date")
    end_date = filter_col_b.date_input("结束日期", value=default_end, key="tx_end_date")
    status_filter = filter_col_c.selectbox("记录状态", ["有效", "全部", "已撤回", "撤回记录"], key="tx_status_filter")
    limit = int(filter_col_d.number_input("最多显示", min_value=100, max_value=5000, value=1000, step=100, key="tx_limit"))
    if start_date > end_date:
        st.warning("开始日期不能晚于结束日期。")
        return

    try:
        records = load_supabase_transaction_records(start_date=start_date, end_date=end_date, limit=limit)
    except Exception as exc:
        st.error("Supabase 还没有升级修改/撤回功能。请先在 SQL Editor 运行 `supabase/upgrade_edit_revert_inventory.sql`。")
        st.exception(exc)
        return

    if status_filter != "全部":
        records = [row for row in records if transaction_status(row) == status_filter]

    if not records:
        st.info("暂无库存提交记录。")
        return

    record_map = {int(row["id"]): row for row in records if row.get("id") is not None}
    table_df = pd.DataFrame(
        [
            {
                "选择": False,
                "ID": int(row.get("id")),
                "时间": format_datetime(row.get("created_at")),
                "状态": transaction_status(row),
                "操作": row.get("action", ""),
                "物料品类": row.get("category", ""),
                "产品型号": row.get("model") or NO_MODEL_TEXT,
                "语种": row.get("language", ""),
                "数量": int(row.get("quantity") or 0),
                "变更前": int(row.get("before_quantity") or 0),
                "变更后": int(row.get("after_quantity") or 0),
                "库存变化": int(row.get("after_quantity") or 0) - int(row.get("before_quantity") or 0),
                "备注": row.get("note", "") or "",
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
    selected_ids = selected_ids_from_editor(edited_df)
    selected_records = [record_map[item_id] for item_id in selected_ids if item_id in record_map]
    active_selected_ids = [int(row["id"]) for row in selected_records if transaction_status(row) == "有效"]
    inactive_count = len(selected_records) - len(active_selected_ids)

    action_col_a, action_col_b, action_col_c = st.columns([1.4, 1, 1])
    revert_note = action_col_a.text_input("批量撤回备注", key="tx_batch_revert_note", placeholder="可选")
    revert_confirmed = action_col_b.checkbox("确认批量撤回", key="tx_batch_revert_confirmed")
    if action_col_c.button("批量撤回选中提交", type="primary", width="stretch", key="tx_batch_revert_button"):
        if not active_selected_ids:
            st.warning("请先勾选至少一条有效提交记录。")
        elif inactive_count:
            st.warning("选中记录包含已撤回或撤回记录，请取消这些记录后再操作。")
        elif not revert_confirmed:
            st.warning("请先勾选确认批量撤回。")
        else:
            try:
                logs: list[list[object]] = []
                for transaction_id in active_selected_ids:
                    logs.extend(revert_supabase_transaction(transaction_id, revert_note))
                st.success(f"已撤回 {len(active_selected_ids)} 条提交记录。")
                st.dataframe(pd.DataFrame(logs, columns=TRANSACTION_HEADERS), width="stretch", hide_index=True)
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.error("批量撤回失败。请确认已经运行 `supabase/upgrade_edit_revert_inventory.sql`。")
                st.exception(exc)

    if len(active_selected_ids) == 1:
        selected_id = active_selected_ids[0]
        selected = record_map[selected_id]
        with st.expander("编辑选中提交", expanded=True):
            selection_context = build_inventory_selection_context()
            edit_col_a, edit_col_b, edit_col_c, edit_col_d, edit_col_e = st.columns([2, 1.3, 1.5, 1.1, 1])
            products = unique_preserve([str(selected.get("category", ""))] + list(selection_context["products"]))
            replace_product = edit_col_a.selectbox(
                "物料品类",
                products,
                index=products.index(str(selected.get("category", ""))) if str(selected.get("category", "")) in products else 0,
                key=f"replace_product_{selected_id}",
            )
            is_no_model_product, scoped_models = product_model_state(replace_product, selection_context)
            old_model = str(selected.get("model") or NO_MODEL_TEXT)
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
            languages = unique_preserve([str(selected.get("language", ""))] + scoped_languages)
            replace_language = edit_col_c.selectbox(
                "语种",
                languages,
                index=languages.index(str(selected.get("language", ""))) if str(selected.get("language", "")) in languages else 0,
                key=f"replace_language_{selected_id}",
            )
            actions = ACTION_OPTIONS
            old_action = str(selected.get("action", ACTION_RECEIVE))
            if old_action in DECREASE_ACTIONS or old_action == "盘点设为":
                default_action = ACTION_RECEIVE
            elif old_action in INCREASE_ACTIONS:
                default_action = ACTION_PURCHASE
            else:
                default_action = ACTION_RECEIVE
            replace_action = edit_col_d.selectbox(
                "操作",
                actions,
                index=actions.index(default_action),
                key=f"replace_action_{selected_id}",
            )
            replace_default_quantity = max(int(selected.get("quantity") or 0), 0)
            replace_quantity = edit_col_e.number_input(
                "数量",
                min_value=0,
                max_value=1_000_000,
                value=replace_default_quantity,
                step=1,
                key=f"replace_quantity_{selected_id}_{replace_action}",
            )
            replace_note = st.text_input("修正备注", key=f"replace_note_{selected_id}", placeholder="可选")
            replace_confirmed = st.checkbox("确认撤回原记录并保存修正记录", key=f"replace_confirmed_{selected_id}")
            if st.button("保存选中记录的编辑", type="primary", width="stretch", key=f"replace_transaction_button_{selected_id}"):
                if not replace_confirmed:
                    st.warning("请先勾选确认修正。")
                else:
                    try:
                        logs = replace_supabase_transaction(
                            selected_id,
                            replace_action,
                            replace_product,
                            replace_model,
                            replace_language,
                            int(replace_quantity),
                            replace_note,
                        )
                        st.success("已撤回原提交，并保存新的修正提交。")
                        st.dataframe(pd.DataFrame(logs, columns=TRANSACTION_HEADERS), width="stretch", hide_index=True)
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as exc:
                        st.error("修正失败。请确认已经运行 `supabase/upgrade_edit_revert_inventory.sql`。")
                        st.exception(exc)
    elif len(selected_ids) > 1:
        st.info("已选择多条记录，可批量撤回；如需编辑，请只勾选一条有效记录。")
    else:
        st.caption("勾选一条有效记录可编辑；勾选多条有效记录可批量撤回。")


def render_material_data_admin() -> None:
    st.subheader("库存行修改与删除")
    if not supabase_configured():
        st.info("该功能需要 Supabase 长期数据库。当前本地 Excel 模式下请直接维护本地库存文件。")
        return

    filter_col_a, filter_col_b, filter_col_c = st.columns([1, 1, 2])
    default_end = date.today()
    default_start = default_end - timedelta(days=90)
    start_date = filter_col_a.date_input("创建开始日期", value=default_start, key="item_start_date")
    end_date = filter_col_b.date_input("创建结束日期", value=default_end, key="item_end_date")
    search_text = filter_col_c.text_input("搜索库存行", key="item_search_text", placeholder="物料编码 / 品类 / 型号 / 语种")
    if start_date > end_date:
        st.warning("开始日期不能晚于结束日期。")
        return

    try:
        records = load_supabase_inventory_records(start_date=start_date, end_date=end_date)
    except Exception as exc:
        st.error("读取物料行失败。请检查 Supabase 连接。")
        st.exception(exc)
        return
    if not records:
        st.info("暂无物料行。")
        return

    record_map = {int(row["id"]): row for row in records if row.get("id") is not None}
    table_df = pd.DataFrame(
        [
            {
                "选择": False,
                "ID": int(row.get("id")),
                "创建时间": format_datetime(row.get("created_at")),
                "更新时间": format_datetime(row.get("updated_at")),
                "物料编码": row.get("material_code", ""),
                "物料品类": row.get("category", ""),
                "产品型号": row.get("model") or NO_MODEL_TEXT,
                "语种": row.get("language", ""),
                "库存数量": int(row.get("quantity") or 0),
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
    selected_ids = selected_ids_from_editor(edited_df)
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
                product = str(row.get("category", ""))
                model = str(row.get("model") or NO_MODEL_TEXT)
                language = str(row.get("language", ""))
                quantity = int(row.get("quantity") or 0)
                tx_count = count_supabase_item_transactions(product, model, language)
                if quantity != 0 or tx_count > 0:
                    blocked.append(f"{row.get('material_code', '')}（库存 {quantity}，流水 {tx_count}）")
            if blocked:
                st.error("以下库存行不能删除：" + "；".join(blocked[:8]))
            else:
                try:
                    for row in selected_records:
                        delete_supabase_inventory_item(int(row["id"]))
                    st.success(f"已删除 {len(selected_records)} 条库存行。")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error("批量删除库存行失败。")
                    st.exception(exc)

    if len(selected_records) == 1:
        item = selected_records[0]
        selected_item_id = int(item["id"])
        current_product = str(item.get("category", ""))
        current_model = str(item.get("model") or NO_MODEL_TEXT)
        current_language = str(item.get("language", ""))
        with st.expander("编辑选中库存行", expanded=True):
            edit_col_a, edit_col_b, edit_col_c, edit_col_d = st.columns([1.2, 2, 1.3, 1.4])
            material_code = edit_col_a.text_input("物料编码", value=str(item.get("material_code", "")), key=f"edit_material_code_{selected_item_id}")
            product = edit_col_b.text_input("物料品类", value=current_product, key=f"edit_material_product_{selected_item_id}")
            no_model = edit_col_c.checkbox("无需型号", value=current_model == NO_MODEL_TEXT, key=f"edit_material_no_model_{selected_item_id}")
            if no_model:
                edit_col_d.text_input("产品型号", value=NO_MODEL_TEXT, disabled=True, key=f"edit_material_model_blank_{selected_item_id}")
                model = NO_MODEL_TEXT
            else:
                model = edit_col_d.text_input("产品型号", value=current_model, key=f"edit_material_model_{selected_item_id}")
            language = st.text_input("语种", value=current_language, key=f"edit_material_language_{selected_item_id}")
            if st.button("保存选中库存行修改", type="primary", width="stretch", key=f"save_inventory_item_edit_{selected_item_id}"):
                if not material_code.strip() or not product.strip() or not language.strip():
                    st.error("物料编码、物料品类和语种不能为空。")
                elif count_supabase_item_transactions(current_product, current_model, current_language) > 0:
                    st.error("该库存行已经有流水记录。为保证历史可追溯，请先撤回相关库存提交后再修改行信息。")
                else:
                    try:
                        update_supabase_inventory_item(selected_item_id, material_code, product, model, language)
                        st.success("库存行信息已修改。")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as exc:
                        st.error("修改失败，可能是物料编码或“品类+型号+语种”与现有行重复。")
                        st.exception(exc)
    elif len(selected_records) > 1:
        st.info("已选择多条库存行，可批量删除；如需编辑，请只勾选一条。")
    else:
        st.caption("勾选一条库存行可编辑；勾选多条可批量删除。")


def render_category_admin() -> None:
    st.subheader("物料品类修改与撤回")
    if not supabase_configured():
        st.info("该功能需要 Supabase 长期数据库。当前本地 Excel 模式下请直接维护本地库存文件。")
        return

    filter_col_a, filter_col_b = st.columns(2)
    default_end = date.today()
    default_start = default_end - timedelta(days=90)
    start_date = filter_col_a.date_input("创建开始日期", value=default_start, key="category_start_date")
    end_date = filter_col_b.date_input("创建结束日期", value=default_end, key="category_end_date")
    if start_date > end_date:
        st.warning("开始日期不能晚于结束日期。")
        return

    try:
        categories = load_supabase_category_records(start_date=start_date, end_date=end_date)
        all_categories = load_supabase_category_records(limit=5000)
        inventory_df = load_inventory()
    except Exception as exc:
        st.error("读取物料品类失败。请检查 Supabase 连接。")
        st.exception(exc)
        return
    if not categories:
        st.info("暂无物料品类。")
        return

    existing_category_names = {str(row.get("category", "")) for row in all_categories}
    summary: dict[str, dict[str, int]] = {}
    if not inventory_df.empty:
        for product, group in inventory_df.groupby(PRODUCT_COL):
            summary[str(product)] = {
                "row_count": int(len(group)),
                "nonzero_count": int((group[QTY_COL] != 0).sum()),
                "quantity_sum": int(group[QTY_COL].sum()),
                "real_model_count": int((group[MODEL_COL] != NO_MODEL_TEXT).sum()),
            }

    record_map = {int(row["id"]): row for row in categories if row.get("id") is not None}
    table_df = pd.DataFrame(
        [
            {
                "选择": False,
                "ID": int(row.get("id")),
                "创建时间": format_datetime(row.get("created_at")),
                "物料品类": row.get("category", ""),
                "无需型号": bool(row.get("no_model")),
                "库存行数": summary.get(str(row.get("category", "")), {}).get("row_count", 0),
                "非零库存行": summary.get(str(row.get("category", "")), {}).get("nonzero_count", 0),
                "库存合计": summary.get(str(row.get("category", "")), {}).get("quantity_sum", 0),
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
    selected_ids = selected_ids_from_editor(edited_df)
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
                product = str(row.get("category", ""))
                stats = summary.get(product, {"nonzero_count": 0})
                tx_count = count_supabase_category_transactions(product)
                if int(stats.get("nonzero_count", 0)) > 0 or tx_count > 0:
                    blocked.append(f"{product}（非零库存行 {stats.get('nonzero_count', 0)}，流水 {tx_count}）")
            if blocked:
                st.error("以下品类不能撤回：" + "；".join(blocked[:8]))
            else:
                try:
                    for row in selected_records:
                        delete_supabase_category(str(row.get("category", "")))
                    st.success(f"已撤回 {len(selected_records)} 个物料品类。")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error("批量撤回物料品类失败。")
                    st.exception(exc)

    if len(selected_records) == 1:
        category = selected_records[0]
        category_id = int(category["id"])
        old_product = str(category.get("category", ""))
        stats = summary.get(old_product, {"real_model_count": 0})
        with st.expander("编辑选中物料品类", expanded=True):
            edit_col_a, edit_col_b = st.columns([2, 1])
            new_product = edit_col_a.text_input("物料品类名称", value=old_product, key=f"edit_category_name_{category_id}")
            no_model = edit_col_b.checkbox("无需型号", value=bool(category.get("no_model")), key=f"edit_category_no_model_{category_id}")
            if st.button("保存选中品类修改", type="primary", width="stretch", key=f"save_category_edit_{category_id}"):
                if not new_product.strip():
                    st.error("物料品类名称不能为空。")
                elif no_model and int(stats.get("real_model_count", 0)) > 0:
                    st.error("该品类已有具体产品型号，不能直接改为无需型号。")
                elif new_product.strip() != old_product and (
                    new_product.strip() in existing_category_names
                    or new_product.strip() in set(inventory_df[PRODUCT_COL].astype(str))
                ):
                    st.error("新的物料品类名称已经存在。")
                elif count_supabase_category_transactions(old_product) > 0:
                    st.error("该品类已有流水记录。为保证历史可追溯，请先撤回相关库存提交后再修改品类。")
                else:
                    try:
                        update_supabase_category(old_product, new_product, no_model)
                        st.success("物料品类已修改。")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as exc:
                        st.error("修改物料品类失败，可能与现有品类重复。")
                        st.exception(exc)
    elif len(selected_records) > 1:
        st.info("已选择多个品类，可批量撤回；如需编辑，请只勾选一个。")
    else:
        st.caption("勾选一个品类可编辑；勾选多个可批量撤回。")


def render_edit_revert_page() -> None:
    tx_tab, item_tab, category_tab = st.tabs(["提交记录", "库存行", "物料品类"])
    with tx_tab:
        render_transaction_admin()
    with item_tab:
        render_material_data_admin()
    with category_tab:
        render_category_admin()


def apply_changes(changes: list[dict[str, object]]) -> None:
    valid_changes = [item for item in changes if int(item["quantity"]) > 0]
    if not valid_changes:
        st.warning("请至少填写一项数量大于 0 的物料。")
        return

    if supabase_configured():
        with DATA_LOCK:
            try:
                logs = apply_supabase_changes(valid_changes)
            except Exception as exc:
                error_text = str(exc)
                if "42702" in error_text or "ambiguous" in error_text:
                    st.error("Supabase 库存更新函数需要升级。请在 SQL Editor 运行 `supabase/upgrade_edit_revert_inventory.sql`。")
                elif "inventory_items_quantity_check" in error_text or "violates check constraint" in error_text:
                    st.error("Supabase 还没有放开负库存。请在 SQL Editor 运行 `supabase/upgrade_edit_revert_inventory.sql`。")
                else:
                    st.error("Supabase 库存更新失败。请确认已经运行 `supabase/schema.sql`，且 Secrets 配置正确。")
                st.exception(exc)
                return

        st.success(f"已更新 {len(logs)} 项物料库存。")
        st.dataframe(pd.DataFrame(logs, columns=TRANSACTION_HEADERS), width="stretch", hide_index=True)
        st.cache_data.clear()
        return

    with DATA_LOCK:
        df = load_inventory()
        working = df.copy()
        logs: list[list[object]] = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for item in valid_changes:
            product = str(item["product"])
            model = str(item["model"])
            language = str(item["language"])
            action = str(item["action"])
            quantity = int(item["quantity"])
            note = str(item["note"]).strip()

            mask = (
                (working[PRODUCT_COL] == product)
                & (working[MODEL_COL] == model)
                & (working[LANGUAGE_COL] == language)
            )
            if not mask.any():
                st.error(f"未找到物料组合: {product} / {model} / {language}")
                return

            row_index = working.index[mask][0]
            before = int(working.at[row_index, QTY_COL])

            if action in INCREASE_ACTIONS:
                after = before + quantity
            elif action in DECREASE_ACTIONS:
                after = before - quantity
            else:
                st.error(f"不支持的操作: {action}")
                return

            working.at[row_index, QTY_COL] = after
            working.at[row_index, VALUE_COL] = after * float(working.at[row_index, PRICE_COL])
            working.at[row_index, UPDATED_COL] = now
            logs.append([now, action, product, model, language, quantity, before, after, note])

        save_inventory(working)
        append_transactions(logs)

    st.success(f"已更新 {len(logs)} 项物料库存。")
    st.dataframe(pd.DataFrame(logs, columns=TRANSACTION_HEADERS), width="stretch", hide_index=True)
    st.cache_data.clear()


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


def render_management_page() -> None:
    st.title("物料库存管理")
    navigate_to_inventory("management_open_inventory")
    update_tab, add_tab, edit_tab = st.tabs(["库存登记", "新增物料品类", "修改与撤回"])
    with update_tab:
        render_change_form(show_title=False)
    with add_tab:
        render_add_category_form()
    with edit_tab:
        render_edit_revert_page()


def main() -> None:
    st.set_page_config(page_title="物料库存管理", layout="wide")
    inject_global_styles()
    stop_on_invalid_supabase_config()
    ensure_data()
    render_sidebar_link()
    render_storage_diagnostics()

    view = st.query_params.get("view", "")
    if view == "inventory":
        render_inventory_view()
    else:
        render_management_page()


if __name__ == "__main__":
    main()
