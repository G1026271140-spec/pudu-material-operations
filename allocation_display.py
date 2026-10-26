"""Read-only presentation fields for the allocation workbench.

Requested arrival is never inferred from a planned receipt/shipping/use date.
The historical source spelling '要求达到开始日期' is intentional.
"""
from datetime import date, datetime, timedelta, timezone

CHINA_TZ = timezone(timedelta(hours=8))


def _display_date(value: object, *, include_time: bool = False) -> str:
    if value is None or value == "" or isinstance(value, bool):
        return ""
    if isinstance(value, list):
        value = "".join(str(item.get("text") or "") if isinstance(item, dict) else str(item) for item in value)
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            parsed = datetime.fromtimestamp(float(value) / 1000, CHINA_TZ)
        elif isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            return value.isoformat()
        else:
            parsed = datetime.fromisoformat(str(value).strip().replace("/", "-"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(CHINA_TZ)
        if include_time and (parsed.hour or parsed.minute):
            return parsed.strftime("%Y-%m-%d %H:%M")
        return parsed.date().isoformat()
    except (ValueError, TypeError, OSError, OverflowError):
        return str(value).strip()


def required_arrival_fields(fields: dict) -> dict[str, str]:
    """Expose the exact field plus the existing arrival window, without I/O."""
    return {
        "required_arrival_time": _display_date(fields.get("物料要求到达时间"), include_time=True),
        "required_arrival_start": _display_date(fields.get("要求达到开始日期") or fields.get("要求到达开始日期")),
        "required_arrival_end": _display_date(fields.get("要求到达结束日期")),
    }
