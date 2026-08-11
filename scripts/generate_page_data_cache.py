import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts.validate_page_data_cache import validate_page_data_cache  # noqa: E402


def main() -> int:
    cache = app.build_page_data_static_snapshot()
    counts = cache.get("row_counts") or {}
    required_counts = {
        app.CATEGORY_TABLE_NAME: int(counts.get(app.CATEGORY_TABLE_NAME) or 0),
        app.MATERIAL_TABLE_NAME: int(counts.get(app.MATERIAL_TABLE_NAME) or 0),
    }
    if any(row_count <= 0 for row_count in required_counts.values()):
        print(
            "page_data_cache_not_written: required Feishu tables returned no rows",
            required_counts,
            file=sys.stderr,
        )
        return 1
    try:
        stats = validate_page_data_cache(cache, require_data=True)
    except (TypeError, ValueError) as exc:
        print(f"page_data_cache_not_written: {exc}", file=sys.stderr)
        return 1
    app.PAGE_DATA_STATIC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    app.PAGE_DATA_STATIC_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "page_data_cache_written",
        app.PAGE_DATA_STATIC_CACHE_PATH,
        f"generated_at={cache.get('generated_at')}",
        f"rows={sum(int(value) for value in counts.values())}",
        f"gift_categories={stats['gift_categories']}",
    )
    for table_name, row_count in counts.items():
        print(f"  {table_name}: {row_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
