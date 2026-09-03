"""Ordinary-material ordering rules. No I/O, Streamlit, or inventory mutations."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json

CHINA_TZ = timezone(timedelta(hours=8))
BATCH_TABLE = "物料下单批次"
DETAIL_TABLE = "物料下单批次明细"
REASONS = ("代理活动", "展会需求", "客户来访")
# Verified against the user's live Base on 2026-09-03. Retain their spelling.
ARRIVAL_START = "要求达到开始日期"
ARRIVAL_END = "要求到达结束日期"
READY_DATE = "预计完成制作日期"
ORDER_DATE = "需要下单日期"
TIME_CLASS = "时间判定"
RESTOCK_KEY = "补库幂等建"
GENERATED = "下单表生成状态"


def today() -> date:
    return datetime.now(CHINA_TZ).date()


def as_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(CHINA_TZ).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.fromtimestamp(float(value) / 1000, CHINA_TZ).date()
    return date.fromisoformat(str(value)[:10].replace("/", "-"))


def date_ms(value: object) -> int:
    parsed = as_date(value)
    if parsed is None:
        raise ValueError("日期不能为空。")
    return int(datetime.combine(parsed, time.min, CHINA_TZ).timestamp() * 1000)


def calculate_dates(start: object, end: object, reason: str, roles: list[str], *, submitted: object) -> dict:
    start_day, end_day, submitted_day = as_date(start), as_date(end), as_date(submitted)
    if reason not in REASONS:
        raise ValueError("请选择申请原因：代理活动、展会需求或客户来访。")
    if start_day is None or end_day is None or submitted_day is None:
        raise ValueError("请选择完整的要求到达日期。")
    if end_day < start_day:
        raise ValueError("到达结束日期不能早于开始日期。")
    lead_days = (start_day - submitted_day).days
    if lead_days < 0:
        raise ValueError("要求到达日期不能早于提交申请当天。")
    role_set = set(roles) or {"销售"}
    sales_only = role_set == {"销售"}
    exempt = reason == "客户来访" or "区域市场经理" in role_set or not sales_only
    if not exempt and lead_days < 7:
        raise ValueError("销售物料申请须至少提前7个自然日；7～14天为加急，15天起为普通申请。")
    classification = "时间豁免" if exempt else "加急申请" if lead_days <= 14 else "普通申请"
    return {
        "申请原因": reason, ARRIVAL_START: date_ms(start_day), ARRIVAL_END: date_ms(end_day),
        ORDER_DATE: date_ms(start_day - timedelta(days=15)),
        READY_DATE: date_ms(start_day - timedelta(days=10)), TIME_CLASS: classification,
        "申请时角色快照": "、".join(sorted(role_set)),
    }


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def ordinary_request(fields: dict) -> bool:
    # Do not classify an unknown/missing type as ordinary: never import cultural requests.
    return fields.get("申请类型") == "普通物料申请"


def validate_planned_receipt(planned: object, *, now: date, confirmed_arrived: bool = False) -> date:
    planned_day = as_date(planned)
    if planned_day is None:
        raise ValueError("请填写计划到仓日期。")
    if planned_day < now and not confirmed_arrived:
        raise ValueError("计划到仓日期已过，请调整日期，或明确确认已经制作完成并到仓。")
    return planned_day


def aggregate_export_rows(lines: list[dict]) -> list[list]:
    """Keep unlike usage/production remarks separate; identifiers remain in batch detail rows."""
    grouped: dict[tuple, int] = {}
    for line in lines:
        key = tuple(str(line.get(k) or "") for k in ("category", "model", "language", "usage", "remark"))
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError("下单数量必须是正整数。")
        grouped[key] = grouped.get(key, 0) + qty
    return [[category, model, language, quantity,
             usage + (f"\n制作备注：{remark}" if remark else "")]
            for (category, model, language, usage, remark), quantity in grouped.items()]


# Explicit contracts: new schema failures disable only this module, never create fields.
SCHEMA = {
    "物料申请单": {
        "申请原因": (3, REASONS), ARRIVAL_START: (5, None), ARRIVAL_END: (5, None),
        ORDER_DATE: (5, None), READY_DATE: (5, None), "申请时角色快照": (1, None),
        TIME_CLASS: (3, ("普通申请", "加急申请", "时间豁免", "待补充日期")),
        "排期编辑版本": (2, None),
    },
    "申请明细": {GENERATED: (3, ("未生成", "生成中", "已生成"))},
    BATCH_TABLE: {
        "下单批次号": (1, None), "批次状态": (3, ("生成中", "已生成", "生成失败", "已作废")),
        "生成人": (11, None), "生成时间": (5, None),
        "生成幂等键": (1, None), "启用自动补库": (7, None), "批次备注": (1, None),
    },
    DETAIL_TABLE: {
        "批次明细编号": (1, None), "所属下单批次": (18, BATCH_TABLE),
        "来源申请单": (18, "物料申请单"), "来源申请明细": (18, "申请明细"),
        "关联物料": (18, "物料主数据"), "品类名称快照": (1, None), "型号或尺码快照": (1, None),
        "语种快照": (1, None), "下单数量": (2, None), "申请用途快照": (1, None),
        "明细备注快照": (1, None), "计划到仓日期": (5, None),
        "补库状态": (3, ("待补库", "补库中", "已补库", "补库异常", "已取消")),
        "实际补库时间": (5, None), "关联库存流水": (18, "库存流水"),
        RESTOCK_KEY: (1, None), "补库异常说明": (1, None),
    },
}


def schema_errors(tables: dict) -> list[str]:
    errors = []
    for table, requirements in SCHEMA.items():
        actual = tables.get(table, {}).get("fields", {})
        for name, (kind, extra) in requirements.items():
            field = actual.get(name)
            if not field:
                errors.append(f"{table}缺少字段：{name}")
                continue
            if field.get("type") != kind:
                errors.append(f"{table}.{name}类型不匹配：应为{kind}，实际{field.get('type')}")
                continue
            prop = field.get("property") or {}
            if kind == 18 and prop.get("table_id") != tables.get(extra, {}).get("table_id"):
                errors.append(f"{table}.{name}必须关联到{extra}")
            if kind == 3:
                options = {item.get("name") for item in prop.get("options", [])}
                missing = set(extra) - options
                if missing:
                    errors.append(f"{table}.{name}缺少选项：{'、'.join(sorted(missing))}")
    return errors
