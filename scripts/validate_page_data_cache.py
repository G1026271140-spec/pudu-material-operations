import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def validate_page_data_cache(
    cache: object,
    *,
    require_data: bool = False,
    require_cached_gift_images: bool = False,
    cache_root: Path = ROOT,
) -> dict[str, int]:
    if not isinstance(cache, dict):
        raise ValueError("页面缓存根节点必须是对象。")
    tables = cache.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("页面缓存缺少 tables 对象。")

    required_tables = (
        app.CATEGORY_TABLE_NAME,
        app.MATERIAL_TABLE_NAME,
        app.GIFT_PROJECT_TABLE_NAME,
    )
    missing_tables = [table_name for table_name in required_tables if table_name not in tables]
    if missing_tables:
        raise ValueError(f"页面缓存缺少必需数据表：{', '.join(missing_tables)}")

    rows_by_table: dict[str, list[dict]] = {}
    for table_name in required_tables:
        rows = tables.get(table_name)
        if not isinstance(rows, list):
            raise ValueError(f"页面缓存数据表格式不正确：{table_name}")
        rows_by_table[table_name] = rows

    row_counts = cache.get("row_counts")
    if not isinstance(row_counts, dict):
        raise ValueError("页面缓存缺少 row_counts 对象。")
    for table_name, rows in rows_by_table.items():
        if int(row_counts.get(table_name, -1)) != len(rows):
            raise ValueError(f"页面缓存行数不一致：{table_name}")

    category_rows = rows_by_table[app.CATEGORY_TABLE_NAME]
    material_rows = rows_by_table[app.MATERIAL_TABLE_NAME]
    gift_project_rows = rows_by_table[app.GIFT_PROJECT_TABLE_NAME]
    if require_data and (not category_rows or not material_rows):
        raise ValueError("页面缓存中的物料品类或物料主数据为空。")

    gift_category_ids = {
        str(category.get("record_id") or "")
        for category in app.feishu_category_records_from_rows(category_rows)
        if category.get("category_definition") == app.CATEGORY_DEFINITION_GIFT
    }
    gallery = app.gift_gallery_records_from_rows(category_rows, gift_project_rows, material_rows)
    gallery_ids = {str(item.get("record_id") or "") for item in gallery}
    if gallery_ids != gift_category_ids:
        raise ValueError("周边礼品页面缓存与品类定义不一致。")

    image_cache = cache.get("gift_image_cache")
    validate_images = require_cached_gift_images or isinstance(image_cache, dict)
    cached_image_paths: set[str] = set()
    if validate_images:
        if not isinstance(image_cache, dict):
            raise ValueError("页面缓存缺少周边礼品静态图片配置。")
        resolved_root = cache_root.resolve()
        for row in gift_project_rows:
            values = app.feishu_fields(row).get("物料图片")
            if not isinstance(values, list):
                continue
            for attachment in values:
                if not isinstance(attachment, dict):
                    continue
                media_type = str(attachment.get("type") or "").lower()
                suffix = Path(str(attachment.get("name") or "")).suffix.lower()
                if not media_type.startswith("image/") and suffix not in {
                    ".avif",
                    ".bmp",
                    ".gif",
                    ".jpeg",
                    ".jpg",
                    ".png",
                    ".tif",
                    ".tiff",
                    ".webp",
                }:
                    continue
                cached_path = str(attachment.get("cached_path") or "").strip()
                if not cached_path:
                    raise ValueError("周边礼品附件缺少静态图片缓存路径。")
                image_path = (resolved_root / cached_path).resolve()
                if resolved_root not in image_path.parents or not image_path.is_file():
                    raise ValueError(f"周边礼品静态图片不存在：{cached_path}")
                cached_image_paths.add(cached_path)
        configured_image_count = int(image_cache.get("image_count") or 0)
        if configured_image_count != len(cached_image_paths):
            raise ValueError("周边礼品静态图片缓存数量不一致。")

    return {
        "category_rows": len(category_rows),
        "material_rows": len(material_rows),
        "gift_project_rows": len(gift_project_rows),
        "gift_categories": len(gift_category_ids),
        "gift_gallery_rows": len(gallery),
        "gift_image_count": len(cached_image_paths),
    }


def main() -> int:
    try:
        cache = json.loads(app.PAGE_DATA_STATIC_CACHE_PATH.read_text(encoding="utf-8"))
        stats = validate_page_data_cache(
            cache,
            require_data=True,
            require_cached_gift_images=bool(cache.get("gift_image_cache")),
            cache_root=ROOT,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"page_data_cache_invalid: {exc}", file=sys.stderr)
        return 1
    print(
        "page_data_cache_valid",
        f"categories={stats['category_rows']}",
        f"materials={stats['material_rows']}",
        f"gift_projects={stats['gift_project_rows']}",
        f"gift_categories={stats['gift_categories']}",
        f"gift_images={stats['gift_image_count']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
