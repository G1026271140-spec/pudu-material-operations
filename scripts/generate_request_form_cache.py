import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def main() -> int:
    cache = app.build_live_request_form_cache()
    try:
        stats = app.validate_request_form_cache(cache, require_data=True)
    except ValueError as exc:
        print(
            f"request_form_cache_not_written: {exc}",
            file=sys.stderr,
        )
        return 1
    cache["source"] = "static_snapshot"
    cache["built_from"] = "live_feishu"
    app.REQUEST_FORM_STATIC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    app.REQUEST_FORM_STATIC_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "request_and_restock_form_cache_written",
        app.REQUEST_FORM_STATIC_CACHE_PATH,
        f"rows={stats['row_count']}",
        f"products={stats['product_count']}",
        f"combinations={stats['combination_count']}",
        f"generated_at={cache.get('generated_at')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
