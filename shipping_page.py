from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from datetime import date
import pandas as pd
import streamlit as st

from shipping_template import (
    DEFAULT_PAYMENT_TERM,
    DEFAULT_PRODUCT_MODEL,
    Carton,
    CartonAllocation,
    ShippingLine,
    build_invoice_number,
    generate_shipping_workbook,
    infer_address_code,
)


PACKING_TYPE_OPTIONS = ("Flyers", "Brochures", "Banners", "Give aways")
LINE_IDS_KEY = "shipping_template_line_ids"
ALLOCATION_ROWS_KEY = "shipping_template_allocations"
LINE_FIELD_SUFFIXES = (
    "category",
    "invoice_name",
    "packing_name",
    "packing_type",
    "quantity",
    "unit_price",
    "customs",
    "model",
    "sku",
)
CARTON_FIELD_DEFAULTS: dict[str, object] = {
    "carton_quantity": 1,
    "net_weight": 0.0,
    "gross_weight": 0.0,
    "override_cbm": False,
    "length": 0.0,
    "width": 0.0,
    "height": 0.0,
    "cbm_override": 0.0,
}


def _new_line_id() -> str:
    return uuid.uuid4().hex[:10]


def _category_label(category: dict[str, object]) -> str:
    invoice_name = str(category.get("commercial_invoice_name") or "").strip()
    category_name = str(category.get("category") or "").strip()
    return f"{invoice_name or category_name} · {category_name}"


def _category_options(categories: list[dict]) -> list[dict[str, object]]:
    return [
        category
        for category in categories
        if str(category.get("record_id") or "").strip()
    ]


def _apply_category_to_line(line_id: str, category_by_id: dict[str, dict[str, object]]) -> None:
    category_id = str(st.session_state.get(f"shipping_category_{line_id}") or "")
    category = category_by_id.get(category_id)
    if not category:
        return
    invoice_name = str(category.get("commercial_invoice_name") or category.get("category") or "").strip()
    st.session_state[f"shipping_invoice_name_{line_id}"] = invoice_name
    st.session_state[f"shipping_packing_name_{line_id}"] = invoice_name
    st.session_state[f"shipping_packing_type_{line_id}"] = str(
        category.get("packing_list_product_type") or PACKING_TYPE_OPTIONS[-1]
    )
    st.session_state[f"shipping_unit_price_{line_id}"] = float(category.get("unit_price") or 0)
    st.session_state[f"shipping_customs_{line_id}"] = str(category.get("customs_code") or "")


def initialize_shipping_line_state(
    session_state: MutableMapping[str, object],
    line_id: str,
    category: dict[str, object] | None,
    source_line_id: str | None = None,
) -> None:
    category = category or {}
    category_id = str(category.get("record_id") or "")
    invoice_name = str(category.get("commercial_invoice_name") or category.get("category") or "").strip()
    defaults: dict[str, object] = {
        "category": category_id,
        "invoice_name": invoice_name,
        "packing_name": invoice_name,
        "packing_type": str(
            category.get("packing_list_product_type") or PACKING_TYPE_OPTIONS[-1]
        ),
        "quantity": 1,
        "unit_price": float(category.get("unit_price") or 0),
        "customs": str(category.get("customs_code") or ""),
        "model": DEFAULT_PRODUCT_MODEL,
        "sku": "/",
    }
    for suffix, default_value in defaults.items():
        target_key = f"shipping_{suffix}_{line_id}"
        source_key = f"shipping_{suffix}_{source_line_id}" if source_line_id else ""
        source_value = (
            session_state[source_key]
            if source_key and source_key in session_state
            else default_value
        )
        session_state.setdefault(target_key, source_value)


def _initialize_line(
    line_id: str,
    category: dict[str, object] | None,
    source_line_id: str | None = None,
) -> None:
    initialize_shipping_line_state(
        st.session_state,
        line_id,
        category,
        source_line_id,
    )


def initialize_shipping_carton_state(
    session_state: MutableMapping[str, object],
    carton_no: int,
    source_carton_no: int | None = None,
) -> None:
    for suffix, default_value in CARTON_FIELD_DEFAULTS.items():
        target_key = f"shipping_{suffix}_{carton_no}"
        source_key = f"shipping_{suffix}_{source_carton_no}" if source_carton_no else ""
        source_value = (
            session_state[source_key]
            if source_key and source_key in session_state
            else default_value
        )
        session_state.setdefault(target_key, source_value)


def _delete_line_state(line_id: str) -> None:
    for suffix in LINE_FIELD_SUFFIXES:
        st.session_state.pop(f"shipping_{suffix}_{line_id}", None)


def _render_recipient_fields(template_date: date) -> tuple[date, str, dict[str, object]]:
    with st.container(border=True):
        st.subheader("发票与收件信息")
        top_a, top_b = st.columns([1, 1])
        selected_date = top_a.date_input(
            "填写模板日期", value=template_date, key="shipping_template_date"
        )
        address = st.text_area(
            "收货地址",
            key="shipping_recipient_address",
            height=92,
            placeholder="可填写中文或英文地址",
        )
        inferred_code = infer_address_code(address)
        previous_address = str(st.session_state.get("shipping_address_for_code") or "")
        previous_auto_code = str(st.session_state.get("shipping_auto_address_code") or "")
        if address != previous_address:
            current_code = str(st.session_state.get("shipping_address_code") or "")
            if not current_code or current_code == previous_auto_code:
                st.session_state["shipping_address_code"] = inferred_code
            st.session_state["shipping_address_for_code"] = address
            st.session_state["shipping_auto_address_code"] = inferred_code
        address_code = top_b.text_input(
            "收货地址英文缩写",
            key="shipping_address_code",
            placeholder="例如：MX",
            max_chars=8,
        )
        try:
            invoice_number = build_invoice_number(selected_date, address_code)
        except ValueError:
            invoice_number = "等待填写地址缩写"
        st.code(invoice_number, language=None)

        row_a = st.columns(3)
        contact = row_a[0].text_input("联系人", key="shipping_recipient_contact")
        company = row_a[1].text_input("公司", key="shipping_recipient_company")
        postal_code = row_a[2].text_input("邮政编码", key="shipping_recipient_postal")
        row_b = st.columns(3)
        phone = row_b[0].text_input("电话", key="shipping_recipient_phone")
        email = row_b[1].text_input("邮箱", key="shipping_recipient_email")
        delivery_term = row_b[2].text_input("交货条款", key="shipping_delivery_term")
        payment_term = st.text_input(
            "付款条款",
            value=DEFAULT_PAYMENT_TERM,
            key="shipping_payment_term",
        )
    return selected_date, address_code, {
        "contact": contact,
        "company": company,
        "address": address,
        "postal_code": postal_code,
        "phone": phone,
        "email": email,
        "delivery_term": delivery_term,
        "payment_term": payment_term,
    }


def _render_invoice_lines(categories: list[dict]) -> list[ShippingLine]:
    category_options = _category_options(categories)
    category_by_id = {str(item.get("record_id") or ""): item for item in category_options}
    if LINE_IDS_KEY not in st.session_state or not st.session_state[LINE_IDS_KEY]:
        st.session_state[LINE_IDS_KEY] = [_new_line_id()]
    line_ids = list(st.session_state[LINE_IDS_KEY])
    default_category = category_options[0] if category_options else None
    for line_id in line_ids:
        _initialize_line(line_id, default_category)

    header_col, add_col = st.columns([5, 1], vertical_alignment="center")
    header_col.subheader("商业发票物料明细")
    add_line_clicked = add_col.button(
        "新增明细",
        icon=":material/add:",
        type="primary",
        width="stretch",
        key="shipping_add_invoice_line",
    )

    lines: list[ShippingLine] = []
    for index, line_id in enumerate(line_ids, start=1):
        with st.container(border=True):
            title_col, delete_col = st.columns([8, 1], vertical_alignment="center")
            title_col.markdown(f"**明细 {index:02d}**")
            if delete_col.button(
                "删除",
                icon=":material/delete:",
                width="stretch",
                disabled=len(line_ids) == 1,
                key=f"shipping_delete_line_{line_id}",
            ):
                _delete_line_state(line_id)
                st.session_state[LINE_IDS_KEY] = [value for value in line_ids if value != line_id]
                st.session_state.pop(ALLOCATION_ROWS_KEY, None)
                st.rerun()

            if category_options:
                category_ids = list(category_by_id)
                current_category_id = str(st.session_state.get(f"shipping_category_{line_id}") or "")
                if current_category_id not in category_by_id:
                    st.session_state[f"shipping_category_{line_id}"] = category_ids[0]
                    _apply_category_to_line(line_id, category_by_id)
                st.selectbox(
                    "物料品类",
                    category_ids,
                    key=f"shipping_category_{line_id}",
                    format_func=lambda value, mapping=category_by_id: _category_label(mapping[value]),
                    on_change=_apply_category_to_line,
                    args=(line_id, category_by_id),
                )
            else:
                st.warning("当前没有可选择的物料品类，仍可手动填写全部字段。")

            name_a, name_b, type_col = st.columns([1.5, 1.5, 1])
            invoice_name = name_a.text_input(
                "商业发票产品名称",
                key=f"shipping_invoice_name_{line_id}",
            )
            packing_name = name_b.text_input(
                "装箱单产品名称",
                key=f"shipping_packing_name_{line_id}",
            )
            current_type = str(st.session_state.get(f"shipping_packing_type_{line_id}") or "")
            packing_type_options = list(PACKING_TYPE_OPTIONS)
            if current_type and current_type not in packing_type_options:
                packing_type_options.append(current_type)
            packing_type = type_col.selectbox(
                "装箱单产品类型",
                packing_type_options,
                key=f"shipping_packing_type_{line_id}",
            )
            quantity_col, price_col, customs_col = st.columns([1, 1, 1.4])
            quantity = quantity_col.number_input(
                "数量",
                min_value=1,
                step=1,
                key=f"shipping_quantity_{line_id}",
            )
            unit_price = price_col.number_input(
                "单价（美元）",
                min_value=0.0,
                step=0.01,
                format="%.3f",
                key=f"shipping_unit_price_{line_id}",
            )
            customs_code = customs_col.text_input(
                "海关编码",
                key=f"shipping_customs_{line_id}",
            )
            with st.expander("其他发票字段", expanded=False):
                sku_col, model_col = st.columns([1, 4])
                sku = sku_col.text_input("SKU", key=f"shipping_sku_{line_id}")
                product_model = model_col.text_input(
                    "Product Model",
                    key=f"shipping_model_{line_id}",
                )
            lines.append(
                ShippingLine(
                    line_id=line_id,
                    invoice_name=invoice_name.strip(),
                    packing_name=packing_name.strip(),
                    packing_type=packing_type,
                    quantity=int(quantity),
                    unit_price=float(unit_price),
                    customs_code=customs_code.strip(),
                    product_model=product_model.strip() or DEFAULT_PRODUCT_MODEL,
                    sku=sku.strip() or "/",
                )
            )
    if add_line_clicked:
        new_id = _new_line_id()
        source_line_id = line_ids[-1] if line_ids else None
        _initialize_line(new_id, default_category, source_line_id)
        st.session_state[LINE_IDS_KEY] = [*line_ids, new_id]
        st.rerun()
    return lines


def _render_cartons() -> list[Carton]:
    st.subheader("纸箱信息")
    carton_count = int(
        st.number_input(
            "纸箱组数",
            min_value=1,
            max_value=100,
            value=1,
            step=1,
            key="shipping_carton_count",
        )
    )
    cartons: list[Carton] = []
    for carton_no in range(1, carton_count + 1):
        initialize_shipping_carton_state(
            st.session_state,
            carton_no,
            carton_no - 1 if carton_no > 1 else None,
        )
        with st.container(border=True):
            st.markdown(f"**纸箱 {carton_no:02d}**")
            first = st.columns(4)
            carton_quantity = first[0].number_input(
                "箱数",
                min_value=1,
                step=1,
                key=f"shipping_carton_quantity_{carton_no}",
            )
            net_weight = first[1].number_input(
                "净重（KG）",
                min_value=0.0,
                step=0.1,
                key=f"shipping_net_weight_{carton_no}",
            )
            gross_weight = first[2].number_input(
                "毛重（KG）",
                min_value=0.0,
                step=0.1,
                key=f"shipping_gross_weight_{carton_no}",
            )
            override_cbm = first[3].toggle(
                "手动填写体积",
                key=f"shipping_override_cbm_{carton_no}",
            )
            dimensions = st.columns(4)
            length_cm = dimensions[0].number_input(
                "长（CM）", min_value=0.0, step=1.0, key=f"shipping_length_{carton_no}"
            )
            width_cm = dimensions[1].number_input(
                "宽（CM）", min_value=0.0, step=1.0, key=f"shipping_width_{carton_no}"
            )
            height_cm = dimensions[2].number_input(
                "高（CM）", min_value=0.0, step=1.0, key=f"shipping_height_{carton_no}"
            )
            calculated_cbm = float(length_cm * width_cm * height_cm / 1_000_000)
            if override_cbm:
                cbm_override = dimensions[3].number_input(
                    "体积（CBM）",
                    min_value=0.0,
                    step=0.001,
                    format="%.3f",
                    key=f"shipping_cbm_override_{carton_no}",
                )
            else:
                dimensions[3].metric("体积（CBM）", f"{calculated_cbm:.3f}")
                cbm_override = None
            cartons.append(
                Carton(
                    carton_no=carton_no,
                    carton_quantity=int(carton_quantity),
                    net_weight=float(net_weight),
                    gross_weight=float(gross_weight),
                    length_cm=float(length_cm),
                    width_cm=float(width_cm),
                    height_cm=float(height_cm),
                    cbm_override=None if cbm_override is None else float(cbm_override),
                )
            )
    return cartons


def _allocation_defaults(lines: list[ShippingLine], carton_count: int) -> list[dict[str, object]]:
    existing = st.session_state.get(ALLOCATION_ROWS_KEY)
    rows = [dict(row) for row in existing] if isinstance(existing, list) else []
    valid_line_numbers = set(range(1, len(lines) + 1))
    rows = [
        row for row in rows
        if int(row.get("物料行") or 0) in valid_line_numbers
        and 1 <= int(row.get("箱号") or 0) <= carton_count
    ]
    allocated_lines = {int(row.get("物料行") or 0) for row in rows}
    for index, line in enumerate(lines, start=1):
        if index not in allocated_lines:
            rows.append({"箱号": 1, "物料行": index, "产品名称": line.packing_name, "数量": line.quantity})
    for row in rows:
        line_index = int(row.get("物料行") or 0)
        if line_index in valid_line_numbers:
            row["产品名称"] = lines[line_index - 1].packing_name
    return rows


def _render_allocations(lines: list[ShippingLine], cartons: list[Carton]) -> list[CartonAllocation]:
    st.subheader("箱内货物分配")
    defaults = _allocation_defaults(lines, len(cartons))
    edited = st.data_editor(
        pd.DataFrame(defaults, columns=["箱号", "物料行", "产品名称", "数量"]),
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        row_height=36,
        column_config={
            "箱号": st.column_config.SelectboxColumn(
                "箱号", options=list(range(1, len(cartons) + 1)), required=True, width="small"
            ),
            "物料行": st.column_config.SelectboxColumn(
                "物料行", options=list(range(1, len(lines) + 1)), required=True, width="small"
            ),
            "产品名称": st.column_config.TextColumn("产品名称", disabled=True, width="large"),
            "数量": st.column_config.NumberColumn(
                "数量", min_value=1, step=1, required=True, width="small"
            ),
        },
        key=f"shipping_allocation_editor_{len(lines)}_{len(cartons)}",
    )
    rows: list[dict[str, object]] = []
    allocations: list[CartonAllocation] = []
    for _, row in edited.iterrows():
        if pd.isna(row.get("箱号")) or pd.isna(row.get("物料行")) or pd.isna(row.get("数量")):
            continue
        carton_no = int(row["箱号"])
        line_number = int(row["物料行"])
        if not (1 <= carton_no <= len(cartons) and 1 <= line_number <= len(lines)):
            continue
        quantity = int(row["数量"])
        normalized = {
            "箱号": carton_no,
            "物料行": line_number,
            "产品名称": lines[line_number - 1].packing_name,
            "数量": quantity,
        }
        rows.append(normalized)
        allocations.append(
            CartonAllocation(
                carton_no=carton_no,
                line_id=lines[line_number - 1].line_id,
                quantity=quantity,
            )
        )
    st.session_state[ALLOCATION_ROWS_KEY] = rows
    return allocations


def _render_live_summary(
    lines: list[ShippingLine], cartons: list[Carton], allocations: list[CartonAllocation]
) -> None:
    allocated = {line.line_id: 0 for line in lines}
    for allocation in allocations:
        allocated[allocation.line_id] = allocated.get(allocation.line_id, 0) + allocation.quantity
    mismatch_count = sum(1 for line in lines if allocated.get(line.line_id, 0) != line.quantity)
    metrics = st.columns(5)
    metrics[0].metric("发票物料", len(lines))
    metrics[1].metric("总数量", sum(line.quantity for line in lines))
    metrics[2].metric("纸箱数", sum(carton.carton_quantity for carton in cartons))
    metrics[3].metric("毛重", f"{sum(carton.gross_weight for carton in cartons):g} KG")
    metrics[4].metric("分配差异", mismatch_count)


def render_shipping_template_page(
    categories: list[dict],
) -> None:
    template_date = st.session_state.get("shipping_template_date", date.today())
    if not isinstance(template_date, date):
        template_date = date.today()
    template_date, address_code, recipient = _render_recipient_fields(template_date)
    lines = _render_invoice_lines(categories)
    cartons = _render_cartons()
    allocations = _render_allocations(lines, cartons)
    _render_live_summary(lines, cartons, allocations)

    generated = st.session_state.get("shipping_generated_workbook")
    action_col, download_col = st.columns([1, 1], vertical_alignment="bottom")
    if action_col.button(
        "生成发货模板",
        type="primary",
        icon=":material/description:",
        width="stretch",
        key="shipping_generate_workbook",
    ):
        try:
            invoice_number, workbook_data = generate_shipping_workbook(
                template_date=template_date,
                address_code=address_code,
                recipient=recipient,
                lines=lines,
                cartons=cartons,
                allocations=allocations,
            )
        except Exception as exc:
            st.error(str(exc))
        else:
            generated = {
                "invoice_number": invoice_number,
                "data": workbook_data,
                "file_name": f"{invoice_number}_INV_PL.xlsx",
            }
            st.session_state["shipping_generated_workbook"] = generated
            st.success(f"发货模板已生成：{invoice_number}")
    if isinstance(generated, dict) and generated.get("data"):
        download_col.download_button(
            "下载 Excel",
            data=generated["data"],
            file_name=str(generated.get("file_name") or "shipping-template.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            width="stretch",
            key="shipping_download_workbook",
        )
