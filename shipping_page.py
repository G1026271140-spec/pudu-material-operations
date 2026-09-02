from __future__ import annotations

from collections.abc import MutableMapping
from datetime import date
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
    normalize_address_code,
)


PACKING_TYPE_OPTIONS = ("Flyers", "Brochures", "Banners", "Give aways")
CATEGORY_DEFINITION_PRINT = "印刷物料"
CATEGORY_DEFINITION_GIFT = "周边礼品"
CATEGORY_DEFINITION_POOLS = (
    ("print", CATEGORY_DEFINITION_PRINT),
    ("gift", CATEGORY_DEFINITION_GIFT),
)
CARTON_FIELD_DEFAULTS: dict[str, object] = {
    "gross_weight": 0.0,
    "length": 0.0,
    "width": 0.0,
    "height": 0.0,
}
CARTON_PRESETS: dict[str, dict[str, float]] = {
    "单页箱": {"length": 44.0, "width": 30.0, "height": 13.0, "gross_weight": 6.0},
    "手册箱": {"length": 44.0, "width": 32.0, "height": 20.0, "gross_weight": 7.0},
    "易拉宝箱": {"length": 80.0, "width": 30.0, "height": 35.0, "gross_weight": 11.0},
    "笔记本礼盒箱": {"length": 73.0, "width": 26.0, "height": 40.0, "gross_weight": 10.0},
    "小箱": {"length": 43.0, "width": 27.0, "height": 17.0, "gross_weight": 6.5},
    "中小箱": {"length": 40.0, "width": 35.0, "height": 29.0, "gross_weight": 8.0},
    "中大箱": {"length": 68.0, "width": 50.0, "height": 52.0, "gross_weight": 14.0},
    "大箱": {"length": 63.0, "width": 50.0, "height": 66.0, "gross_weight": 16.0},
}


def _render_shipping_page_styles() -> None:
    st.markdown(
        """
        <style>
        [class*="st-key-shipping_recipient_panel"] {
            padding: 0.7rem 0.9rem 0.75rem !important;
        }
        [class*="st-key-shipping_recipient_panel"] [data-testid="stVerticalBlock"] {
            gap: 0.38rem !important;
        }
        [class*="st-key-shipping_recipient_panel"] h3 {
            margin: 0 0 0.1rem !important;
            font-size: 1.18rem !important;
            line-height: 1.25 !important;
        }
        [class*="st-key-shipping_recipient_panel"] label p,
        [class*="st-key-shipping_recipient_panel"] [data-testid="stWidgetLabel"] p {
            font-size: 0.76rem !important;
            line-height: 1.1 !important;
        }
        [class*="st-key-shipping_recipient_panel"] input,
        [class*="st-key-shipping_recipient_panel"] button {
            min-height: 2rem !important;
            height: 2rem !important;
            font-size: 0.78rem !important;
        }
        [class*="st-key-shipping_recipient_panel"] textarea {
            min-height: 3.35rem !important;
            height: 3.35rem !important;
            font-size: 0.78rem !important;
            line-height: 1.25 !important;
        }
        [class*="st-key-shipping_recipient_panel"] [data-testid="stCode"] {
            padding: 0.42rem 0.62rem !important;
            min-height: 2rem !important;
        }
        [class*="st-key-shipping_recipient_panel"] [data-testid="stCode"] code {
            font-size: 0.76rem !important;
        }

        [class*="st-key-shipping_carton_card_"] {
            padding: 0.62rem 0.72rem 0.68rem !important;
        }
        [class*="st-key-shipping_carton_card_"] [data-testid="stVerticalBlock"] {
            gap: 0.34rem !important;
        }
        [class*="st-key-shipping_carton_card_"] label p,
        [class*="st-key-shipping_carton_card_"] [data-testid="stWidgetLabel"] p,
        [class*="st-key-shipping_carton_card_"] [data-testid="stCaptionContainer"] p {
            font-size: 0.7rem !important;
            line-height: 1.12 !important;
        }
        [class*="st-key-shipping_carton_card_"] input,
        [class*="st-key-shipping_carton_card_"] button {
            min-height: 1.9rem !important;
            height: 1.9rem !important;
            font-size: 0.74rem !important;
        }
        [class*="st-key-shipping_carton_card_"] [data-testid="stMetric"] {
            padding: 0.08rem 0 !important;
        }
        [class*="st-key-shipping_carton_card_"] [data-testid="stMetricLabel"] p {
            font-size: 0.66rem !important;
        }
        [class*="st-key-shipping_carton_card_"] [data-testid="stMetricValue"] {
            font-size: 0.92rem !important;
        }
        [class*="st-key-shipping_carton_card_"] [data-testid="stPills"] button {
            min-height: 1.7rem !important;
            height: auto !important;
            padding: 0.12rem 0.38rem !important;
        }

        @media (max-width: 900px) {
            [class*="st-key-shipping_carton_row_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
            }
            [class*="st-key-shipping_carton_row_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
                flex: 1 1 100% !important;
                width: 100% !important;
                min-width: 100% !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def calculate_carton_cbm(length_cm: float, width_cm: float, height_cm: float) -> float:
    return float(length_cm * width_cm * height_cm / 1_000_000)


def estimate_packaging_weight(cbm: float, gross_weight: float) -> float:
    volume_tier = 1 if cbm <= 0.05 else 2 if cbm <= 0.12 else 3
    weight_tier = 1 if gross_weight <= 15 else 2 if gross_weight <= 30 else 3
    return float(max(volume_tier, weight_tier))


def calculate_net_weight(gross_weight: float, packaging_weight: float) -> float:
    return max(0.0, round(float(gross_weight) - float(packaging_weight), 3))


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


def initialize_shipping_product_state(
    session_state: MutableMapping[str, object],
    category_id: str,
    category: dict[str, object] | None,
) -> None:
    category = category or {}
    invoice_name = str(category.get("commercial_invoice_name") or category.get("category") or "").strip()
    defaults: dict[str, object] = {
        "invoice_name": invoice_name,
        "packing_name": invoice_name,
        "packing_type": str(
            category.get("packing_list_product_type") or PACKING_TYPE_OPTIONS[-1]
        ),
        "unit_price": float(category.get("unit_price") or 0),
        "customs": str(category.get("customs_code") or ""),
        "model": DEFAULT_PRODUCT_MODEL,
        "sku": "/",
    }
    for suffix, default_value in defaults.items():
        session_state.setdefault(
            f"shipping_product_{suffix}_{category_id}",
            default_value,
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
    preset_key = f"shipping_carton_preset_{carton_no}"
    source_preset_key = (
        f"shipping_carton_preset_{source_carton_no}" if source_carton_no else ""
    )
    session_state.setdefault(
        preset_key,
        session_state.get(source_preset_key) if source_preset_key else None,
    )


def shipping_carton_preset_label(preset_name: str) -> str:
    preset = CARTON_PRESETS[preset_name]
    return (
        f"{preset_name} · {preset['length']:g}×{preset['width']:g}×"
        f"{preset['height']:g} CM · {preset['gross_weight']:g} KG"
    )


def apply_shipping_carton_preset(
    session_state: MutableMapping[str, object],
    carton_no: int,
) -> bool:
    preset_name = str(session_state.get(f"shipping_carton_preset_{carton_no}") or "")
    preset = CARTON_PRESETS.get(preset_name)
    if preset is None:
        return False
    for suffix in CARTON_FIELD_DEFAULTS:
        session_state[f"shipping_{suffix}_{carton_no}"] = float(preset[suffix])
    return True


def clear_shipping_carton_preset(carton_no: int) -> None:
    """Mark a preset carton as manually adjusted after a dimension/weight edit."""
    st.session_state[f"shipping_carton_preset_{carton_no}"] = None


def _carton_categories_key(carton_no: int) -> str:
    return f"shipping_carton_categories_{carton_no}"


def _carton_category_pool_key(carton_no: int, pool_id: str) -> str:
    return f"shipping_carton_categories_{pool_id}_{carton_no}"


def _carton_item_quantity_key(carton_no: int, category_id: str) -> str:
    return f"shipping_carton_item_quantity_{carton_no}_{category_id}"


def _normalized_category_ids(
    value: object,
    valid_category_ids: set[str],
) -> list[str]:
    values = list(value) if isinstance(value, (list, tuple, set)) else []
    normalized: list[str] = []
    for item in values:
        category_id = str(item or "")
        if category_id in valid_category_ids and category_id not in normalized:
            normalized.append(category_id)
    return normalized


def shipping_category_pool_options(
    category_by_id: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    options = {pool_id: [] for pool_id, _ in CATEGORY_DEFINITION_POOLS}
    for category_id, category in category_by_id.items():
        definition = str(category.get("category_definition") or "").strip()
        pool_id = "gift" if definition == CATEGORY_DEFINITION_GIFT else "print"
        options[pool_id].append(category_id)
    return options


def initialize_shipping_carton_category_pool_state(
    session_state: MutableMapping[str, object],
    carton_no: int,
    pool_options: dict[str, list[str]],
) -> None:
    selected_category_ids = list(
        session_state.get(_carton_categories_key(carton_no)) or []
    )
    for pool_id, _ in CATEGORY_DEFINITION_POOLS:
        pool_key = _carton_category_pool_key(carton_no, pool_id)
        valid_category_ids = set(pool_options.get(pool_id, []))
        if pool_key not in session_state:
            session_state[pool_key] = [
                category_id
                for category_id in selected_category_ids
                if category_id in valid_category_ids
            ]
        else:
            session_state[pool_key] = _normalized_category_ids(
                session_state.get(pool_key),
                valid_category_ids,
            )


def shipping_carton_category_pool_selection(
    session_state: MutableMapping[str, object],
    carton_no: int,
    pool_options: dict[str, list[str]],
) -> list[str]:
    selected: list[str] = []
    for pool_id, _ in CATEGORY_DEFINITION_POOLS:
        selected.extend(
            _normalized_category_ids(
                session_state.get(_carton_category_pool_key(carton_no, pool_id)),
                set(pool_options.get(pool_id, [])),
            )
        )
    return selected


def initialize_shipping_carton_contents_state(
    session_state: MutableMapping[str, object],
    carton_no: int,
    valid_category_ids: set[str],
    source_carton_no: int | None = None,
) -> None:
    target_key = _carton_categories_key(carton_no)
    if target_key not in session_state:
        source_value = (
            session_state.get(_carton_categories_key(source_carton_no), [])
            if source_carton_no
            else []
        )
        session_state[target_key] = _normalized_category_ids(
            source_value,
            valid_category_ids,
        )
    else:
        session_state[target_key] = _normalized_category_ids(
            session_state.get(target_key),
            valid_category_ids,
        )

    selected_category_ids = list(session_state.get(target_key) or [])
    for category_id in selected_category_ids:
        quantity_key = _carton_item_quantity_key(carton_no, category_id)
        source_quantity_key = (
            _carton_item_quantity_key(source_carton_no, category_id)
            if source_carton_no
            else ""
        )
        source_quantity = (
            session_state[source_quantity_key]
            if source_quantity_key and source_quantity_key in session_state
            else 1
        )
        session_state.setdefault(quantity_key, source_quantity)


def aggregate_shipping_carton_items(
    carton_items: list[dict[str, object]],
) -> tuple[list[str], dict[str, int]]:
    ordered_category_ids: list[str] = []
    quantities_by_category: dict[str, int] = {}
    categories_by_carton: dict[int, set[str]] = {}
    for item in carton_items:
        carton_no = int(item.get("carton_no") or 0)
        category_id = str(item.get("category_id") or "").strip()
        quantity = int(item.get("quantity") or 0)
        if carton_no <= 0 or not category_id:
            raise ValueError("箱内物料必须包含有效箱号和物料品类。")
        if quantity <= 0:
            raise ValueError("箱内物料数量必须大于 0。")
        carton_categories = categories_by_carton.setdefault(carton_no, set())
        if category_id in carton_categories:
            raise ValueError(f"箱子 {carton_no:02d} 内不能重复选择同一物料品类。")
        carton_categories.add(category_id)
        if category_id not in quantities_by_category:
            ordered_category_ids.append(category_id)
            quantities_by_category[category_id] = 0
        quantities_by_category[category_id] += quantity
    return ordered_category_ids, quantities_by_category


def _normalize_shipping_address_code_input() -> None:
    raw_value = str(st.session_state.get("shipping_address_code") or "").strip()
    if not raw_value:
        st.session_state["shipping_address_code"] = ""
        return
    normalized_code = normalize_address_code(raw_value)
    if normalized_code:
        st.session_state["shipping_address_code"] = normalized_code


def _render_recipient_fields(template_date: date) -> tuple[date, str, dict[str, object]]:
    with st.container(border=True, key="shipping_recipient_panel"):
        st.subheader("发票与收件信息")
        top_a, top_b, top_c = st.columns([1, 1, 1])
        selected_date = top_a.date_input(
            "填写模板日期", value=template_date, key="shipping_template_date"
        )
        address_code = top_b.text_input(
            "国家名称或英文缩写",
            key="shipping_address_code",
            placeholder="例如：泰国、Thailand 或 TH",
            max_chars=64,
            on_change=_normalize_shipping_address_code_input,
        )
        try:
            invoice_number = build_invoice_number(selected_date, address_code)
        except ValueError:
            invoice_number = "等待填写地址缩写"
        top_c.markdown("<small>发票编号（自动）</small>", unsafe_allow_html=True)
        top_c.code(invoice_number, language=None)

        address = st.text_area(
            "收货地址",
            key="shipping_recipient_address",
            height=56,
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
        row_a = st.columns(4)
        contact = row_a[0].text_input("联系人", key="shipping_recipient_contact")
        company = row_a[1].text_input("公司", key="shipping_recipient_company")
        postal_code = row_a[2].text_input("邮政编码", key="shipping_recipient_postal")
        phone = row_a[3].text_input("电话", key="shipping_recipient_phone")
        row_b = st.columns(3)
        email = row_b[0].text_input("邮箱", key="shipping_recipient_email")
        delivery_term = row_b[1].text_input("交货条款", key="shipping_delivery_term")
        payment_term = row_b[2].text_input(
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


def _render_cartons_and_contents(
    categories: list[dict],
) -> tuple[list[Carton], list[dict[str, object]], dict[str, dict[str, object]]]:
    category_options = _category_options(categories)
    category_by_id = {str(item.get("record_id") or ""): item for item in category_options}
    valid_category_ids = set(category_by_id)
    category_pool_options = shipping_category_pool_options(category_by_id)

    st.subheader("按箱填写装箱单")
    st.caption(
        "先填写每个实际箱子的货物；同一箱内品类不会重复，不同箱子可选择同一品类。"
    )
    carton_count = int(
        st.number_input(
            "实际箱数",
            min_value=1,
            max_value=100,
            value=1,
            step=1,
            key="shipping_carton_count",
        )
    )
    if not category_options:
        st.warning("当前没有可选择的物料品类，请先更新物料品类缓存。")

    cartons: list[Carton] = []
    carton_items: list[dict[str, object]] = []
    carton_columns = []
    for carton_no in range(1, carton_count + 1):
        source_carton_no = carton_no - 1 if carton_no > 1 else None
        initialize_shipping_carton_state(
            st.session_state,
            carton_no,
            source_carton_no,
        )
        initialize_shipping_carton_contents_state(
            st.session_state,
            carton_no,
            valid_category_ids,
            source_carton_no,
        )
        initialize_shipping_carton_category_pool_state(
            st.session_state,
            carton_no,
            category_pool_options,
        )
        if carton_no % 2 == 1:
            with st.container(key=f"shipping_carton_row_{(carton_no + 1) // 2}"):
                carton_columns = st.columns(2, gap="small")
        carton_column = carton_columns[(carton_no - 1) % 2]
        with carton_column.container(
            border=True,
            key=f"shipping_carton_card_{carton_no}",
        ):
            selected_before = shipping_carton_category_pool_selection(
                st.session_state,
                carton_no,
                category_pool_options,
            )
            st.session_state[_carton_categories_key(carton_no)] = selected_before
            title_col, item_count_col = st.columns(
                [5, 1],
                vertical_alignment="center",
            )
            title_col.markdown(f"**箱子 {carton_no:02d}**")
            item_count_col.metric("品类", len(selected_before))

            st.pills(
                "箱型模板（可选）",
                list(CARTON_PRESETS),
                selection_mode="single",
                format_func=shipping_carton_preset_label,
                key=f"shipping_carton_preset_{carton_no}",
                on_change=apply_shipping_carton_preset,
                args=(st.session_state, carton_no),
                width="stretch",
            )

            dimensions = st.columns(4)
            dimensions[0].markdown(
                '<span class="pudu-required-control-marker"></span>',
                unsafe_allow_html=True,
            )
            length_cm = dimensions[0].number_input(
                "长（CM） *",
                min_value=0.0,
                step=1.0,
                key=f"shipping_length_{carton_no}",
                on_change=clear_shipping_carton_preset,
                args=(carton_no,),
            )
            dimensions[1].markdown(
                '<span class="pudu-required-control-marker"></span>',
                unsafe_allow_html=True,
            )
            width_cm = dimensions[1].number_input(
                "宽（CM） *",
                min_value=0.0,
                step=1.0,
                key=f"shipping_width_{carton_no}",
                on_change=clear_shipping_carton_preset,
                args=(carton_no,),
            )
            dimensions[2].markdown(
                '<span class="pudu-required-control-marker"></span>',
                unsafe_allow_html=True,
            )
            height_cm = dimensions[2].number_input(
                "高（CM） *",
                min_value=0.0,
                step=1.0,
                key=f"shipping_height_{carton_no}",
                on_change=clear_shipping_carton_preset,
                args=(carton_no,),
            )
            calculated_cbm = calculate_carton_cbm(length_cm, width_cm, height_cm)
            dimensions[3].metric("体积（自动）", f"{calculated_cbm:.3f} CBM")

            weights = st.columns(3)
            weights[0].markdown(
                '<span class="pudu-required-control-marker"></span>',
                unsafe_allow_html=True,
            )
            gross_weight = weights[0].number_input(
                "毛重（KG） *",
                min_value=0.0,
                step=0.1,
                key=f"shipping_gross_weight_{carton_no}",
                on_change=clear_shipping_carton_preset,
                args=(carton_no,),
            )
            packaging_weight = estimate_packaging_weight(
                calculated_cbm,
                float(gross_weight),
            )
            net_weight = calculate_net_weight(
                float(gross_weight),
                packaging_weight,
            )
            weights[1].metric(
                "包材重量（自动）",
                f"{packaging_weight:g} KG",
                help="根据箱体积和毛重自动估算为 1、2 或 3 KG。",
            )
            weights[2].metric(
                "净重（自动）",
                f"{net_weight:g} KG",
                help="净重等于毛重减去自动估算的包材重量。",
            )

            selected_category_ids: list[str] = []
            pool_columns = st.columns(2, gap="small")
            for pool_column, (pool_id, definition) in zip(
                pool_columns,
                CATEGORY_DEFINITION_POOLS,
            ):
                options = category_pool_options.get(pool_id, [])
                with pool_column.container(border=True):
                    st.markdown(f"**{definition}**")
                    st.caption(f"可选 {len(options)} 项")
                    if options:
                        pool_selection = st.pills(
                            f"{definition}品类",
                            options,
                            selection_mode="multi",
                            format_func=lambda value, mapping=category_by_id: _category_label(
                                mapping[value]
                            ),
                            key=_carton_category_pool_key(carton_no, pool_id),
                            label_visibility="collapsed",
                            width="stretch",
                        )
                        selected_category_ids.extend(pool_selection or [])
                    else:
                        st.caption("暂无可选品类")
            st.session_state[_carton_categories_key(carton_no)] = selected_category_ids
            if not selected_category_ids:
                st.info("这个箱子还没有添加物料。")
            for item_index, category_id in enumerate(selected_category_ids):
                category = category_by_id[category_id]
                initialize_shipping_product_state(
                    st.session_state,
                    category_id,
                    category,
                )
                quantity_key = _carton_item_quantity_key(carton_no, category_id)
                if quantity_key not in st.session_state:
                    source_quantity_key = (
                        _carton_item_quantity_key(source_carton_no, category_id)
                        if source_carton_no
                        else ""
                    )
                    previous_category_id = (
                        selected_category_ids[item_index - 1]
                        if item_index > 0
                        else ""
                    )
                    previous_quantity_key = (
                        _carton_item_quantity_key(carton_no, previous_category_id)
                        if previous_category_id
                        else ""
                    )
                    if source_quantity_key and source_quantity_key in st.session_state:
                        default_quantity = st.session_state[source_quantity_key]
                    elif previous_quantity_key:
                        default_quantity = st.session_state.get(previous_quantity_key, 1)
                    else:
                        default_quantity = 1
                    st.session_state[quantity_key] = max(
                        1,
                        int(default_quantity or 1),
                    )

                item_info_col, quantity_col = st.columns(
                    [4, 1],
                    vertical_alignment="bottom",
                )
                product_name = str(category.get("category") or "未命名品类")
                packing_name = str(
                    st.session_state.get(
                        f"shipping_product_packing_name_{category_id}"
                    )
                    or product_name
                )
                packing_type = str(
                    st.session_state.get(
                        f"shipping_product_packing_type_{category_id}"
                    )
                    or PACKING_TYPE_OPTIONS[-1]
                )
                customs_code = str(
                    st.session_state.get(
                        f"shipping_product_customs_{category_id}"
                    )
                    or ""
                )
                item_info_col.markdown(f"**{product_name}**")
                item_info_col.caption(
                    f"装箱单：{packing_name} · {packing_type} · 海关编码 {customs_code or '-'}"
                )
                quantity = quantity_col.number_input(
                    "数量",
                    min_value=1,
                    step=1,
                    key=quantity_key,
                )
                carton_items.append(
                    {
                        "carton_no": carton_no,
                        "category_id": category_id,
                        "quantity": int(quantity),
                    }
                )

            cartons.append(
                Carton(
                    carton_no=carton_no,
                    carton_quantity=1,
                    net_weight=float(net_weight),
                    gross_weight=float(gross_weight),
                    length_cm=float(length_cm),
                    width_cm=float(width_cm),
                    height_cm=float(height_cm),
                )
            )
    return cartons, carton_items, category_by_id


def _render_invoice_summary(
    category_by_id: dict[str, dict[str, object]],
    carton_items: list[dict[str, object]],
) -> list[ShippingLine]:
    ordered_category_ids, quantities_by_category = aggregate_shipping_carton_items(
        carton_items
    )
    st.subheader("INV 自动汇总")
    st.caption("每个物料品类只生成一行，数量为所有箱子中该品类数量的合计。")
    if not ordered_category_ids:
        st.info("请先在箱内清单中选择物料品类。")
        return []

    lines: list[ShippingLine] = []
    for category_id in ordered_category_ids:
        category = category_by_id[category_id]
        initialize_shipping_product_state(
            st.session_state,
            category_id,
            category,
        )
        product_name = str(category.get("category") or "未命名品类")
        total_quantity = quantities_by_category[category_id]
        with st.container(border=True):
            name_col, quantity_col = st.columns(
                [5, 1],
                vertical_alignment="center",
            )
            name_col.markdown(f"**{product_name}**")
            quantity_col.metric("汇总数量", total_quantity)

            names = st.columns([1.5, 1.5, 1])
            invoice_name = names[0].text_input(
                "商业发票产品名称",
                key=f"shipping_product_invoice_name_{category_id}",
            )
            packing_name = names[1].text_input(
                "装箱单产品名称",
                key=f"shipping_product_packing_name_{category_id}",
            )
            current_type = str(
                st.session_state.get(
                    f"shipping_product_packing_type_{category_id}"
                )
                or ""
            )
            packing_type_options = list(PACKING_TYPE_OPTIONS)
            if current_type and current_type not in packing_type_options:
                packing_type_options.append(current_type)
            packing_type = names[2].selectbox(
                "装箱单产品类型",
                packing_type_options,
                key=f"shipping_product_packing_type_{category_id}",
            )

            details = st.columns([1, 1.4])
            unit_price = details[0].number_input(
                "单价（美元）",
                min_value=0.0,
                step=0.01,
                format="%.3f",
                key=f"shipping_product_unit_price_{category_id}",
            )
            customs_code = details[1].text_input(
                "海关编码",
                key=f"shipping_product_customs_{category_id}",
            )
            with st.expander("其他发票字段", expanded=False):
                sku_col, model_col = st.columns([1, 4])
                sku = sku_col.text_input(
                    "SKU",
                    key=f"shipping_product_sku_{category_id}",
                )
                product_model = model_col.text_input(
                    "Product Model",
                    key=f"shipping_product_model_{category_id}",
                )

            lines.append(
                ShippingLine(
                    line_id=category_id,
                    invoice_name=invoice_name.strip(),
                    packing_name=packing_name.strip(),
                    packing_type=packing_type,
                    quantity=total_quantity,
                    unit_price=float(unit_price),
                    customs_code=customs_code.strip(),
                    product_model=product_model.strip() or DEFAULT_PRODUCT_MODEL,
                    sku=sku.strip() or "/",
                )
            )
    return lines


def build_shipping_carton_allocations(
    carton_items: list[dict[str, object]],
) -> list[CartonAllocation]:
    aggregate_shipping_carton_items(carton_items)
    return [
        CartonAllocation(
            carton_no=int(item["carton_no"]),
            line_id=str(item["category_id"]),
            quantity=int(item["quantity"]),
        )
        for item in carton_items
    ]


def _render_live_summary(
    lines: list[ShippingLine], cartons: list[Carton], allocations: list[CartonAllocation]
) -> None:
    metrics = st.columns(5)
    metrics[0].metric("实际箱数", len(cartons))
    metrics[1].metric("PL 货物行", len(allocations))
    metrics[2].metric("INV 品类", len(lines))
    metrics[3].metric("货物总数量", sum(allocation.quantity for allocation in allocations))
    metrics[4].metric("毛重", f"{sum(carton.gross_weight for carton in cartons):g} KG")


def render_shipping_template_page(
    categories: list[dict],
) -> None:
    _render_shipping_page_styles()
    template_date = st.session_state.get("shipping_template_date", date.today())
    if not isinstance(template_date, date):
        template_date = date.today()
    template_date, address_code, recipient = _render_recipient_fields(template_date)
    cartons, carton_items, category_by_id = _render_cartons_and_contents(categories)
    lines = _render_invoice_summary(category_by_id, carton_items)
    allocations = build_shipping_carton_allocations(carton_items)
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
