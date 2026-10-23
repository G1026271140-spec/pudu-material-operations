from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts.generate_page_data_cache import sync_request_category_image_cache  # noqa: E402


def main() -> int:
    cache = app.load_static_page_data_cache()
    stats = sync_request_category_image_cache(cache)
    print(
        "request_category_image_cache_written",
        f"images={stats['image_count']}",
        f"downloaded={stats['downloaded_count']}",
        f"deleted={stats['deleted_count']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
