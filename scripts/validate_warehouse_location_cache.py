from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def validate_warehouse_location_cache(
    cache: object,
    *,
    cache_root: Path = ROOT,
    require_data: bool = False,
) -> dict[str, int]:
    if not isinstance(cache, dict) or not isinstance(cache.get("shelves"), list):
        raise ValueError("仓库位置缓存根节点或货架数据格式不正确。")
    shelves = [item for item in cache["shelves"] if isinstance(item, dict)]
    if require_data and not shelves:
        raise ValueError("仓库位置缓存没有货架数据。")
    resolved_root = cache_root.resolve()
    paths: set[str] = set()
    for shelf in shelves:
        for image in list(shelf.get("images") or []):
            _validate_image(image, resolved_root, paths)
        for row in list(shelf.get("rows") or []):
            if not isinstance(row, dict):
                raise ValueError("仓库位置缓存包含无效货架行。")
            for image in list(row.get("images") or []):
                _validate_image(image, resolved_root, paths)
    configured_count = cache.get("image_count")
    if configured_count is None:
        if require_data:
            raise ValueError("仓库位置缓存缺少静态图片数量配置。")
    elif int(configured_count) != len(paths):
        raise ValueError("仓库位置静态图片缓存数量不一致。")
    return {"shelves": len(shelves), "image_count": len(paths)}


def _validate_image(image: object, root: Path, paths: set[str]) -> None:
    if not isinstance(image, dict):
        raise ValueError("仓库位置缓存包含无效图片项。")
    relative = str(image.get("path") or "").strip()
    if not relative:
        raise ValueError("仓库位置图片缺少静态缓存路径。")
    image_path = (root / relative).resolve()
    if root not in image_path.parents or not image_path.is_file():
        raise ValueError(f"仓库位置静态图片不存在：{relative}")
    paths.add(relative)


def main() -> int:
    try:
        cache = json.loads(app.WAREHOUSE_LOCATION_CACHE_PATH.read_text(encoding="utf-8"))
        stats = validate_warehouse_location_cache(cache, require_data=True)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"warehouse_location_cache_invalid: {exc}", file=sys.stderr)
        return 1
    print(
        "warehouse_location_cache_valid",
        f"shelves={stats['shelves']}",
        f"images={stats['image_count']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
