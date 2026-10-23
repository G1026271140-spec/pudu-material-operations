import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def main() -> int:
    try:
        cache = json.loads(app.REQUEST_FORM_STATIC_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            raise ValueError("申请页面缓存根节点必须是对象。")
        stats = app.validate_request_form_cache(cache, require_data=True)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"request_form_cache_invalid: {exc}", file=sys.stderr)
        return 1

    print(
        "request_form_cache_valid",
        app.REQUEST_FORM_STATIC_CACHE_PATH,
        f"schema={cache.get('schema_version')}",
        f"rows={stats['row_count']}",
        f"products={stats['product_count']}",
        f"combinations={stats['combination_count']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
