import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def main() -> int:
    cache = app.build_live_request_form_cache()
    cache["source"] = "static_snapshot"
    cache["built_from"] = "live_feishu"
    app.REQUEST_FORM_STATIC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    app.REQUEST_FORM_STATIC_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "request_form_cache_written",
        app.REQUEST_FORM_STATIC_CACHE_PATH,
        f"rows={cache.get('row_count')}",
        f"generated_at={cache.get('generated_at')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
