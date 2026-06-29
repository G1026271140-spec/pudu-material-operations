from __future__ import annotations

import csv
import json
import re
import threading
from datetime import datetime
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

PASSWORD = "376493"
NO_MODEL_TEXT = "无需型号"

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


def ensure_data() -> None:
    if INVENTORY_XLSX.exists() and OPTIONS_JSON.exists():
        return
    from scripts.generate_inventory import main as generate_inventory

    generate_inventory()


def load_options() -> dict:
    ensure_data()
    return json.loads(OPTIONS_JSON.read_text(encoding="utf-8"))


def save_options(options: dict) -> None:
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


def parse_custom_values(raw_text: str) -> list[str]:
    parts = re.split(r"[\n,，;；、]+", raw_text)
    return unique_preserve(parts)


def load_inventory() -> pd.DataFrame:
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


def save_inventory(df: pd.DataFrame) -> None:
    df = df[INVENTORY_HEADERS].copy()
    for column in ["物料编码", PRODUCT_COL, MODEL_COL, LANGUAGE_COL, UPDATED_COL]:
        df[column] = df[column].fillna("").astype(str)
    df[QTY_COL] = pd.to_numeric(df[QTY_COL], errors="coerce").fillna(0).astype(int)
    df[PRICE_COL] = pd.to_numeric(df[PRICE_COL], errors="coerce").fillna(0)
    df[VALUE_COL] = df[QTY_COL] * df[PRICE_COL]

    INVENTORY_XLSX.write_bytes(workbook_bytes(df))
    df.to_csv(INVENTORY_CSV, index=False, encoding="utf-8-sig")


def append_transactions(rows: list[list[object]]) -> None:
    if not TRANSACTIONS_CSV.exists():
        with TRANSACTIONS_CSV.open("w", encoding="utf-8-sig", newline="") as file:
            csv.writer(file).writerow(TRANSACTION_HEADERS)

    with TRANSACTIONS_CSV.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(rows)


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
    password = st.text_input("请输入查看密码", type="password")
    if password == PASSWORD:
        st.session_state["inventory_unlocked"] = True
        st.rerun()
    if password:
        st.error("密码不正确")
    return False


def render_sidebar_link() -> None:
    st.sidebar.subheader("实时库存链接")
    password = st.sidebar.text_input("查看密码", type="password", key="sidebar_password")
    if password == PASSWORD:
        st.session_state["inventory_unlocked"] = True
        st.sidebar.link_button("打开实时库存表", "?view=inventory")
        st.sidebar.caption("本地链接: http://localhost:8501/?view=inventory")
    elif password:
        st.sidebar.error("密码不正确")


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
    options = load_options()
    products = options["products"]
    no_model_products = set(options["no_model_products"])
    models = options["models"]
    languages = options["languages"]

    if show_title:
        st.title("物料库存更新")
    else:
        st.subheader("物料库存更新")
    st.caption("一次可以填写多种物料。选择品类后，绿色底纹品类会自动使用“无需型号”。")

    row_count = get_row_count()
    changes: list[dict[str, object]] = []

    with st.form("inventory_change_form", clear_on_submit=False):
        for index in range(row_count):
            st.markdown(f"**第 {index + 1} 项**")
            product_col, model_col, language_col, action_col, qty_col = st.columns([2.2, 1.5, 1.6, 1.2, 1.1])

            product = product_col.selectbox(
                "物料品类",
                products,
                key=f"product_{index}",
            )
            model_options = [NO_MODEL_TEXT] if product in no_model_products else models
            model = model_col.selectbox(
                "产品型号",
                model_options,
                key=f"model_{index}",
                disabled=product in no_model_products,
            )
            language = language_col.selectbox(
                "语种",
                languages,
                key=f"language_{index}",
            )
            action = action_col.selectbox(
                "操作",
                ["入库增加", "出库减少", "盘点设为"],
                key=f"action_{index}",
            )
            quantity = qty_col.number_input(
                "数量",
                min_value=0,
                max_value=1_000_000,
                value=0,
                step=1,
                key=f"quantity_{index}",
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

        submitted = st.form_submit_button("提交更新", width="stretch")

    if submitted:
        apply_changes(changes)


def render_add_category_form() -> None:
    options = load_options()
    existing_products = options["products"]
    existing_models = options["models"]
    existing_languages = options["languages"]

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
        product_exists = product in set(options["products"]) or product in set(df[PRODUCT_COL].astype(str))
        if product_exists:
            st.error("该物料品类已存在。如需给已有品类补充型号或语种，可以先使用一个新的品类名称。")
            return

        new_rows, skipped = build_new_material_rows(df, product, models, languages)
        if not new_rows:
            st.warning("没有生成新的库存行，可能这些组合已经存在。")
            return

        new_df = pd.DataFrame(new_rows, columns=INVENTORY_HEADERS)
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


def apply_changes(changes: list[dict[str, object]]) -> None:
    valid_changes = [item for item in changes if int(item["quantity"]) > 0 or item["action"] == "盘点设为"]
    if not valid_changes:
        st.warning("请至少填写一项数量大于 0 的物料。")
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

            if action == "入库增加":
                after = before + quantity
            elif action == "出库减少":
                after = before - quantity
                if after < 0:
                    st.error(f"库存不足: {product} / {model} / {language}，当前 {before}，出库 {quantity}")
                    return
            else:
                after = quantity

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

    df = load_inventory()
    product_filter, model_filter, language_filter, stocked_filter = st.columns([2.2, 1.6, 1.6, 1])

    selected_products = product_filter.multiselect("物料品类", sorted(df[PRODUCT_COL].unique()))
    filtered = df[df[PRODUCT_COL].isin(selected_products)] if selected_products else df

    selected_models = model_filter.multiselect("产品型号", sorted(filtered[MODEL_COL].unique()))
    if selected_models:
        filtered = filtered[filtered[MODEL_COL].isin(selected_models)]

    selected_languages = language_filter.multiselect("语种", sorted(filtered[LANGUAGE_COL].unique()))
    if selected_languages:
        filtered = filtered[filtered[LANGUAGE_COL].isin(selected_languages)]

    only_stocked = stocked_filter.checkbox("仅看有库存")
    if only_stocked:
        filtered = filtered[filtered[QTY_COL] > 0]

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("组合总数", f"{len(filtered):,}")
    metric_b.metric("有库存组合", f"{int((filtered[QTY_COL] > 0).sum()):,}")
    metric_c.metric("库存总数量", f"{int(filtered[QTY_COL].sum()):,}")
    metric_d.metric("库存总价值", f"{float(filtered[VALUE_COL].sum()):,.2f}")

    st.dataframe(filtered, width="stretch", hide_index=True, height=560)

    excel_data = workbook_bytes(filtered)
    csv_data = filtered.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    download_col_a, download_col_b = st.columns(2)
    download_col_a.download_button(
        "下载当前筛选 Excel",
        data=excel_data,
        file_name="实时物料库存表.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    download_col_b.download_button(
        "下载当前筛选 CSV",
        data=csv_data,
        file_name="实时物料库存表.csv",
        mime="text/csv",
        width="stretch",
    )


def render_management_page() -> None:
    st.title("物料库存管理")
    update_tab, add_tab = st.tabs(["库存增减", "新增物料品类"])
    with update_tab:
        render_change_form(show_title=False)
    with add_tab:
        render_add_category_form()


def main() -> None:
    st.set_page_config(page_title="物料库存管理", layout="wide")
    ensure_data()
    render_sidebar_link()

    view = st.query_params.get("view", "")
    if view == "inventory":
        render_inventory_view()
    else:
        render_management_page()


if __name__ == "__main__":
    main()
