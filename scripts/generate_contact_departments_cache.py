import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def main() -> int:
    cache = app.build_live_contact_department_cache()
    if int(cache.get("row_count") or 0) <= 0:
        print(
            "contact_departments_cache_not_written: Feishu returned no departments",
            file=sys.stderr,
        )
        return 1
    cache["source"] = "static_snapshot"
    app.CONTACT_DEPARTMENT_STATIC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    app.CONTACT_DEPARTMENT_STATIC_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "contact_departments_cache_written",
        app.CONTACT_DEPARTMENT_STATIC_CACHE_PATH,
        f"rows={cache.get('row_count')}",
        f"users={cache.get('user_count')}",
        f"generated_at={cache.get('generated_at')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
