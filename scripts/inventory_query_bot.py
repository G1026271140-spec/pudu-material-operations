from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable


MAX_QUERY_ITEMS = 20
NO_MODEL_TEXT = "无型号"
NO_LANGUAGE_TEXT = "无需语种"


@dataclass(frozen=True)
class InventoryQuery:
    category: str
    model: str
    language: str
    quantity: int


@dataclass(frozen=True)
class InventoryQueryResult:
    query: InventoryQuery
    status: str
    available: int
    similar: tuple[dict[str, Any], ...] = ()


def normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def value_aliases(value: object) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return ()
    aliases = [text]
    for outside, inside in re.findall(r"([^()（）]*)[（(]([^()（）]+)[）)]", text):
        aliases.extend([outside.strip(), inside.strip()])
    aliases.extend(part.strip() for part in re.split(r"[/／]", text) if part.strip())

    normalized = normalized_text(text)
    if normalized in {normalized_text(NO_MODEL_TEXT), "nomodel", "none"}:
        aliases.extend([NO_MODEL_TEXT, "无需型号", "no model", "none", "n/a"])
    if normalized in {normalized_text(NO_LANGUAGE_TEXT), "nolanguage", "none"}:
        aliases.extend([NO_LANGUAGE_TEXT, "无语种", "no language", "none", "n/a"])

    unique: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        alias_key = normalized_text(alias)
        if alias_key and alias_key not in seen:
            seen.add(alias_key)
            unique.append(alias.strip())
    return tuple(unique)


def dimension_equal(left: object, right: object) -> bool:
    left_aliases = {normalized_text(alias) for alias in value_aliases(left)}
    right_aliases = {normalized_text(alias) for alias in value_aliases(right)}
    return bool(left_aliases & right_aliases)


def extract_image_keys(content: object) -> list[str]:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return []

    keys: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"image_key", "img_key"} and isinstance(child, str):
                    normalized_key = child.strip()
                    if normalized_key and normalized_key not in keys:
                        keys.append(normalized_key)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(content)
    return keys


def extract_message_text(content: object) -> str:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content.strip()

    parts: list[str] = []

    def add_text(value: object) -> None:
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"text", "title"} and isinstance(child, str):
                    add_text(child)
                elif isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(content)
    return "\n".join(parts)


def has_inventory_query_intent(text: object) -> bool:
    raw_text = unicodedata.normalize("NFKC", str(text or "")).strip()
    key = normalized_text(raw_text)
    if any(
        marker in key
        for marker in (
            "库存",
            "物料",
            "品类",
            "型号",
            "语种",
            "语言",
            "数量",
            "inventory",
            "stock",
            "quantity",
            "qty",
        )
    ):
        return True
    parts = [part for part in re.split(r"[\s,，/／|;；]+", raw_text) if part]
    return bool(re.search(r"\d", raw_text) and len(parts) >= 4)


def _catalog_values(records: Iterable[dict[str, Any]], field: str) -> list[str]:
    values = {
        str(record.get(field) or "").strip()
        for record in records
        if str(record.get(field) or "").strip()
    }
    return sorted(values, key=lambda value: (-len(normalized_text(value)), value.casefold()))


def _alias_is_in_text(alias: str, text: str) -> bool:
    alias_key = normalized_text(alias)
    text_key = normalized_text(text)
    if not alias_key or not text_key:
        return False
    if alias_key.isascii() and len(alias_key) <= 3:
        folded = unicodedata.normalize("NFKC", text).casefold()
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(alias.casefold())}(?![a-z0-9])",
                folded,
            )
        )
    return alias_key in text_key


def _match_catalog_value(text: str, values: Iterable[str]) -> str:
    matches: list[tuple[int, str]] = []
    for value in values:
        for alias in value_aliases(value):
            if _alias_is_in_text(alias, text):
                matches.append((len(normalized_text(alias)), value))
                break
    if not matches:
        return ""
    matches.sort(key=lambda item: (-item[0], item[1].casefold()))
    return matches[0][1]


def _canonical_or_raw(value: str, catalog: Iterable[str]) -> str:
    matched = _match_catalog_value(value, catalog)
    return matched or value.strip(" \t:：,，;；")


def _extract_quantity(text: str, *, allow_unlabelled: bool) -> int | None:
    labelled = re.search(
        r"(?:需求数量|申请数量|数量|需要|需求|qty|quantity|count)\s*[:：x×*]?\s*(\d+)",
        text,
        flags=re.IGNORECASE,
    )
    if labelled:
        return int(labelled.group(1))
    if not allow_unlabelled:
        return None
    standalone = re.fullmatch(r"\s*(\d+)\s*(?:件|个|套|本|张|份|pcs?)?\s*", text, re.I)
    if standalone:
        return int(standalone.group(1))
    multiplied = re.search(r"(?:x|×|\*)\s*(\d+)\s*$", text, re.I)
    if multiplied:
        return int(multiplied.group(1))
    trailing = re.search(
        r"(?<![A-Za-z0-9])(\d+)\s*(?:件|个|套|本|张|份|pcs?)?\s*$",
        text,
        re.I,
    )
    return int(trailing.group(1)) if trailing else None


def _labelled_value(text: str, labels: str) -> str:
    next_label = (
        r"(?:物料品类|物料名称|品类|产品型号|型号|语种|语言)\s*[:：]"
        r"|(?:需求数量|申请数量|数量|需要|需求|qty|quantity|count)\s*[:：]?"
    )
    match = re.search(
        rf"(?:{labels})\s*[:：]\s*(.+?)(?=[\s,，;；]*(?:{next_label})|$)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _parse_labelled_query(
    text: str,
    categories: Iterable[str],
    models: Iterable[str],
    languages: Iterable[str],
    *,
    require_quantity: bool,
) -> InventoryQuery | None:
    category = _labelled_value(text, r"物料品类|物料名称|品类")
    model = _labelled_value(text, r"产品型号|型号")
    language = _labelled_value(text, r"语种|语言")
    quantity = _extract_quantity(text, allow_unlabelled=False)
    if not category or not model or not language:
        return None
    if require_quantity and not quantity:
        return None
    return InventoryQuery(
        category=_canonical_or_raw(category, categories),
        model=_canonical_or_raw(model, models),
        language=_canonical_or_raw(language, languages),
        quantity=int(quantity or 0),
    )


def _is_header_line(text: str) -> bool:
    key = normalized_text(text)
    header_terms = (
        "物料品类",
        "物料名称",
        "品类",
        "产品型号",
        "型号",
        "语种",
        "语言",
        "需求数量",
        "申请数量",
        "数量",
        "quantity",
        "qty",
    )
    return sum(normalized_text(term) in key for term in header_terms) >= 2


def _is_ignorable_line(text: str) -> bool:
    key = normalized_text(text)
    if not key:
        return True
    return key in {
        "库存确认清单",
        "物料需求清单",
        "库存查询",
        "请确认库存",
        "inventorycheck",
    }


def _looks_like_language(text: str) -> bool:
    key = normalized_text(text)
    return any(
        token in key
        for token in (
            "中文",
            "简中",
            "繁中",
            "英语",
            "英文",
            "法语",
            "德语",
            "日语",
            "韩语",
            "西班牙语",
            "葡萄牙语",
            "意大利语",
            "俄语",
            "阿拉伯语",
            "chinese",
            "english",
            "french",
            "german",
            "japanese",
            "korean",
            "spanish",
            "portuguese",
            "italian",
            "russian",
            "arabic",
            normalized_text(NO_LANGUAGE_TEXT),
        )
    )


def _fill_unique_dimensions(
    query: InventoryQuery,
    records: Iterable[dict[str, Any]],
) -> InventoryQuery:
    candidates = [
        record
        for record in records
        if dimension_equal(record.get("category"), query.category)
    ]
    model = query.model
    language = query.language
    if not model:
        models = _catalog_values(candidates, "model")
        if len(models) == 1:
            model = models[0]
    if not language:
        languages = _catalog_values(candidates, "language")
        if len(languages) == 1:
            language = languages[0]
    return InventoryQuery(query.category, model, language, query.quantity)


def parse_inventory_queries(
    text_list: Iterable[object],
    inventory_records: Iterable[dict[str, Any]],
    *,
    category_names: Iterable[object] = (),
    max_items: int = MAX_QUERY_ITEMS,
    require_quantity: bool = True,
) -> list[InventoryQuery]:
    records = [dict(record) for record in inventory_records]
    categories = sorted(
        {
            *(_catalog_values(records, "category")),
            *(str(value).strip() for value in category_names if str(value).strip()),
        },
        key=lambda value: (-len(normalized_text(value)), value.casefold()),
    )
    models = _catalog_values(records, "model")
    languages = _catalog_values(records, "language")
    lines = [
        part.strip()
        for value in text_list
        for part in re.split(r"[\r\n\t|]+", str(value or ""))
        if part.strip()
    ]

    queries: list[InventoryQuery] = []
    current: dict[str, Any] = {"category": "", "model": "", "language": "", "quantity": 0}

    def flush() -> None:
        nonlocal current
        query = InventoryQuery(
            str(current.get("category") or "").strip(),
            str(current.get("model") or "").strip(),
            str(current.get("language") or "").strip(),
            int(current.get("quantity") or 0),
        )
        query = _fill_unique_dimensions(query, records)
        if (
            query.category
            and query.model
            and query.language
            and (query.quantity > 0 or not require_quantity)
        ):
            queries.append(query)
        current = {"category": "", "model": "", "language": "", "quantity": 0}

    for line in lines:
        if len(queries) >= max_items:
            break
        labelled_query = _parse_labelled_query(
            line,
            categories,
            models,
            languages,
            require_quantity=require_quantity,
        )
        if labelled_query is not None:
            flush()
            queries.append(labelled_query)
            continue
        if _is_header_line(line) or _is_ignorable_line(line):
            continue

        category = _match_catalog_value(line, categories)
        model = _match_catalog_value(line, models)
        language = _match_catalog_value(line, languages)
        contains_dimension = bool(category or model or language)
        quantity = _extract_quantity(line, allow_unlabelled=not contains_dimension)
        if contains_dimension:
            trailing_quantity = _extract_quantity(line, allow_unlabelled=True)
            if trailing_quantity and not (
                (model and dimension_equal(line.strip(), model))
                or (language and dimension_equal(line.strip(), language))
            ):
                quantity = trailing_quantity

        if category and current["category"] and not dimension_equal(category, current["category"]):
            flush()
        elif model and current["model"] and not dimension_equal(model, current["model"]):
            flush()

        if category:
            current["category"] = category
        if model:
            current["model"] = model
        if language:
            current["language"] = language
        if quantity:
            current["quantity"] = quantity
            flush()
            continue
        if contains_dimension:
            continue

        raw_value = line.strip(" \t:：,，;；")
        if not raw_value or len(raw_value) > 80 or re.fullmatch(r"\d+", raw_value):
            continue
        if current["category"]:
            if _looks_like_language(raw_value) and not current["language"]:
                current["language"] = raw_value
            elif not current["model"]:
                current["model"] = raw_value
            elif not current["language"]:
                current["language"] = raw_value
        elif current["model"] or current["language"]:
            current["category"] = raw_value

    flush()

    merged: dict[tuple[str, str, str], InventoryQuery] = {}
    for query in queries[:max_items]:
        key = (
            normalized_text(query.category),
            normalized_text(query.model),
            normalized_text(query.language),
        )
        existing = merged.get(key)
        merged[key] = InventoryQuery(
            query.category,
            query.model,
            query.language,
            query.quantity + (existing.quantity if existing else 0),
        )
    return list(merged.values())


def _dimension_similarity(left: object, right: object) -> float:
    left_aliases = [normalized_text(alias) for alias in value_aliases(left)]
    right_aliases = [normalized_text(alias) for alias in value_aliases(right)]
    if not left_aliases or not right_aliases:
        return 0.0
    if set(left_aliases) & set(right_aliases):
        return 1.0
    return max(
        SequenceMatcher(None, left_alias, right_alias).ratio()
        for left_alias in left_aliases
        for right_alias in right_aliases
    )


def _similar_inventory(
    query: InventoryQuery,
    records: Iterable[dict[str, Any]],
    *,
    limit: int = 3,
) -> tuple[dict[str, Any], ...]:
    ranked: list[tuple[int, float, int, dict[str, Any]]] = []
    for record in records:
        category_score = _dimension_similarity(query.category, record.get("category"))
        model_score = _dimension_similarity(query.model, record.get("model"))
        language_score = _dimension_similarity(query.language, record.get("language"))
        exact_dimensions = sum(score == 1.0 for score in (category_score, model_score, language_score))
        score = category_score * 0.5 + model_score * 0.3 + language_score * 0.2
        if exact_dimensions == 0 and score < 0.58:
            continue
        ranked.append(
            (
                exact_dimensions,
                score,
                int(record.get("quantity") or 0),
                dict(record),
            )
        )
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2]))

    similar: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, _, _, record in ranked:
        key = (
            normalized_text(record.get("category")),
            normalized_text(record.get("model")),
            normalized_text(record.get("language")),
        )
        if key in seen:
            continue
        seen.add(key)
        similar.append(record)
        if len(similar) >= limit:
            break
    return tuple(similar)


def match_inventory_queries(
    queries: Iterable[InventoryQuery],
    inventory_records: Iterable[dict[str, Any]],
) -> list[InventoryQueryResult]:
    records = [dict(record) for record in inventory_records]
    results: list[InventoryQueryResult] = []
    for query in queries:
        exact = [
            record
            for record in records
            if dimension_equal(query.category, record.get("category"))
            and dimension_equal(query.model, record.get("model"))
            and dimension_equal(query.language, record.get("language"))
        ]
        if exact:
            available = sum(int(record.get("quantity") or 0) for record in exact)
            if query.quantity <= 0:
                status = "found"
            else:
                status = "available" if available >= query.quantity else "insufficient"
            results.append(InventoryQueryResult(query, status, available))
            continue
        results.append(
            InventoryQueryResult(
                query,
                "missing",
                0,
                _similar_inventory(query, records),
            )
        )
    return results


def _plain_text(content: object) -> dict[str, str]:
    return {"tag": "plain_text", "content": str(content or "")}


def _markdown_escape(value: object) -> str:
    escaped = str(value or "")
    for character in "*~><[]()#:_":
        escaped = escaped.replace(character, f"&#{ord(character)};")
    return escaped


def inventory_result_card(results: Iterable[InventoryQueryResult]) -> dict[str, Any]:
    result_list = list(results)
    found_count = sum(result.status == "found" for result in result_list)
    available_count = sum(result.status == "available" for result in result_list)
    insufficient_count = sum(result.status == "insufficient" for result in result_list)
    missing_count = sum(result.status == "missing" for result in result_list)
    status_labels = {
        "found": "已找到",
        "available": "库存充足",
        "insufficient": "库存不足",
        "missing": "无此组合",
    }
    rows = [
        {
            "material": (
                f"{result.query.category} / {result.query.model} / {result.query.language}"
            ),
            "requested": str(result.query.quantity) if result.query.quantity > 0 else "-",
            "stock": str(result.available) if result.status != "missing" else "未找到",
            "status": status_labels[result.status],
        }
        for result in result_list
    ]
    elements: list[dict[str, Any]] = [
        {
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "background_style": "blue-50",
                    "corner_radius": "8px",
                    "padding": "12px",
                    "vertical_spacing": "4px",
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"**共查询 {len(result_list)} 项物料**",
                        },
                        {
                            "tag": "markdown",
                            "content": " · ".join(
                                label
                                for count, label in (
                                    (found_count, f"已找到 {found_count} 项"),
                                    (available_count, f"库存充足 {available_count} 项"),
                                    (insufficient_count, f"库存不足 {insufficient_count} 项"),
                                    (missing_count, f"无此组合 {missing_count} 项"),
                                )
                                if count
                            ),
                            "text_size": "notation",
                        },
                    ],
                }
            ],
            "margin": "0px 0px 12px 0px",
        },
        {
            "tag": "table",
            "columns": [
                {"name": "material", "display_name": "物料", "data_type": "text", "width": "46%"},
                {"name": "requested", "display_name": "需求", "data_type": "text", "width": "14%"},
                {"name": "stock", "display_name": "库存", "data_type": "text", "width": "16%"},
                {"name": "status", "display_name": "结果", "data_type": "text", "width": "24%"},
            ],
            "rows": rows,
            "page_size": min(10, max(1, len(rows))),
            "row_height": "auto",
            "row_max_height": "80px",
            "freeze_first_column": True,
            "header_style": {
                "background_style": "grey",
                "bold": True,
                "lines": 1,
            },
            "margin": "0px",
        },
    ]

    similar_lines: list[str] = []
    for result in result_list:
        if not result.similar:
            continue
        target = " / ".join(
            _markdown_escape(value)
            for value in (result.query.category, result.query.model, result.query.language)
        )
        candidates = "；".join(
            (
                f"{_markdown_escape(item.get('category'))} / "
                f"{_markdown_escape(item.get('model'))} / "
                f"{_markdown_escape(item.get('language'))}（库存 {int(item.get('quantity') or 0)}）"
            )
            for item in result.similar
        )
        similar_lines.append(f"- **{target}**：{candidates}")
    if similar_lines:
        elements.append(
            {
                "tag": "markdown",
                "content": "**相似库存组合**\n" + "\n".join(similar_lines),
                "text_size": "notation",
                "margin": "12px 0px 0px 0px",
            }
        )

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "fill",
            "summary": {"content": f"库存查询结果：共 {len(result_list)} 项"},
        },
        "header": {
            "title": _plain_text("物料库存查询结果"),
            "subtitle": _plain_text("实时读取物料库存"),
            "template": "blue",
            "icon": {"tag": "standard_icon", "token": "search_outlined"},
            "text_tag_list": [
                {"tag": "text_tag", "text": _plain_text("实时库存"), "color": "blue"}
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": elements,
        },
    }
