from __future__ import annotations

from collections.abc import MutableMapping
from datetime import date
import backend_runtime as runtime

from shipping_template import (
    DEFAULT_SHIPPING_COST,
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
CATEGORY_DEFINITION_CULTURAL = "文化周边"
CATEGORY_DEFINITION_UNDEFINED = "未定义"
CATEGORY_DEFINITION_POOLS = (
    ("print", CATEGORY_DEFINITION_PRINT),
    ("gift", CATEGORY_DEFINITION_GIFT),
    ("cultural", CATEGORY_DEFINITION_CULTURAL),
    ("undefined", CATEGORY_DEFINITION_UNDEFINED),
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


def calculate_carton_cbm(length_cm: float, width_cm: float, height_cm: float) -> float:
    return float(length_cm * width_cm * height_cm / 1_000_000)


def estimate_packaging_weight(cbm: float, gross_weight: float) -> float:
    volume_tier = 1 if cbm <= 0.05 else 2 if cbm <= 0.12 else 3
    weight_tier = 1 if gross_weight <= 15 else 2 if gross_weight <= 30 else 3
    return float(max(volume_tier, weight_tier))


def calculate_net_weight(gross_weight: float, packaging_weight: float) -> float:
    return max(0.0, round(float(gross_weight) - float(packaging_weight), 3))


def _category_label(category: dict[str, object]) -> str:
    zh_page_name = str(category.get("zh_page_name") or "").strip()
    category_name = str(category.get("category") or "").strip()
    return zh_page_name or category_name


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
    runtime.request_state[f"shipping_carton_preset_{carton_no}"] = None


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
    pool_by_definition = {
        definition: pool_id
        for pool_id, definition in CATEGORY_DEFINITION_POOLS
        if definition != CATEGORY_DEFINITION_UNDEFINED
    }
    for category_id, category in category_by_id.items():
        definition = str(category.get("category_definition") or "").strip()
        pool_id = pool_by_definition.get(definition, "undefined")
        options[pool_id].append(category_id)
    return options


def shipping_category_pool_columns(
    pool_options: dict[str, list[str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Balance visible category-definition pools into two stable columns."""
    visible_pools = [
        (pool_id, definition)
        for pool_id, definition in CATEGORY_DEFINITION_POOLS
        if pool_options.get(pool_id)
    ]
    if len(visible_pools) <= 1:
        return visible_pools, []

    first_pool = visible_pools[0]
    remaining_pools = visible_pools[1:]
    best_columns: tuple[list[tuple[str, str]], list[tuple[str, str]]] | None = None
    best_score: tuple[int, int] | None = None
    for mask in range(1 << len(remaining_pools)):
        left = [first_pool]
        right: list[tuple[str, str]] = []
        for index, pool in enumerate(remaining_pools):
            (left if mask & (1 << index) else right).append(pool)
        if not right:
            continue
        left_count = sum(len(pool_options[pool_id]) for pool_id, _ in left)
        right_count = sum(len(pool_options[pool_id]) for pool_id, _ in right)
        score = (abs(left_count - right_count), abs(len(left) - len(right)))
        if best_score is None or score < best_score:
            best_columns = (left, right)
            best_score = score
    return best_columns or (visible_pools, [])


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
    raw_value = str(runtime.request_state.get("shipping_address_code") or "").strip()
    if not raw_value:
        runtime.request_state["shipping_address_code"] = ""
        return
    normalized_code = normalize_address_code(raw_value)
    if normalized_code:
        runtime.request_state["shipping_address_code"] = normalized_code


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
