from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib import request

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402


CACHE_PATH = ROOT / "data" / "warehouse_location_cache.json"
IMAGE_DIR = ROOT / "assets" / "warehouse_locations"
SHELF_TABLE = "物料货架"
LOCATION_TABLE = "仓库物料位置"


def link_ids(fields: dict, field_name: str) -> list[str]:
    return app.feishu_link_ids(fields, field_name)


def attachment_items(fields: dict, field_name: str) -> list[dict]:
    value = fields.get(field_name)
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def download_attachment(url: str, token: str) -> bytes:
    req = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with request.urlopen(req, timeout=90) as response:
        return response.read()


IMAGE_SUFFIXES = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


def is_image_attachment(attachment: dict) -> bool:
    media_type = str(attachment.get("type") or "").strip().lower()
    suffix = Path(str(attachment.get("name") or "")).suffix.lower()
    return media_type.startswith("image/") or suffix in IMAGE_SUFFIXES


def cached_images(
    attachments: list[dict],
    *,
    prefix: str,
    access_token: str,
    image_dir: Path = IMAGE_DIR,
    cache_root: Path = ROOT,
) -> list[dict[str, str]]:
    image_dir = image_dir.resolve()
    cache_root = cache_root.resolve()
    if cache_root != image_dir and cache_root not in image_dir.parents:
        raise ValueError("仓库位置图片缓存目录必须位于项目目录内。")
    images: list[dict[str, str]] = []
    for index, attachment in enumerate(attachments, start=1):
        if not is_image_attachment(attachment):
            continue
        url = str(attachment.get("url") or attachment.get("tmp_url") or "").strip()
        file_token = str(attachment.get("file_token") or "").strip()
        if not file_token:
            continue
        digest = hashlib.sha256(file_token.encode("utf-8")).hexdigest()[:12]
        file_name = f"{prefix}-{index:02d}-{digest}.webp"
        target = image_dir / file_name
        if not target.is_file() or target.stat().st_size <= 0:
            if url:
                raw = download_attachment(url, access_token)
            else:
                raw = app.load_feishu_attachment(file_token)
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                temporary = target.with_suffix(target.suffix + ".tmp")
                try:
                    image.save(temporary, "WEBP", quality=78, method=6)
                    temporary.replace(target)
                finally:
                    if temporary.exists():
                        temporary.unlink()
        images.append(
            {
                "path": target.relative_to(cache_root).as_posix(),
                "name": str(attachment.get("name") or file_name),
            }
        )
    return images


def material_summary(row: dict) -> dict[str, str]:
    fields = app.feishu_fields(row)
    return {
        "material_code": app.feishu_text(fields, "物料编码"),
        "category": app.feishu_text(fields, "物料品类"),
        "model": app.feishu_text(fields, "产品型号") or app.NO_MODEL_TEXT,
        "language": app.feishu_text(fields, "语种") or app.NO_LANGUAGE_TEXT,
    }


def cleanup_obsolete_images(
    referenced_images: set[str],
    *,
    image_dir: Path = IMAGE_DIR,
    cache_root: Path = ROOT,
) -> int:
    image_dir = image_dir.resolve()
    cache_root = cache_root.resolve()
    if cache_root != image_dir and cache_root not in image_dir.parents:
        raise ValueError("仓库位置图片缓存目录必须位于项目目录内。")
    deleted_count = 0
    for image_path in image_dir.glob("*.webp"):
        relative = image_path.relative_to(cache_root).as_posix()
        if relative not in referenced_images:
            image_path.unlink()
            deleted_count += 1
    return deleted_count


def build_cache() -> dict:
    app.refresh_feishu_schema_cache()
    schema_tables = app.feishu_schema().get("tables", {})
    for table_name in (SHELF_TABLE, LOCATION_TABLE):
        if table_name not in schema_tables:
            raise RuntimeError(f"飞书多维表格缺少数据表：{table_name}")

    shelves = app.fresh_feishu_rows(SHELF_TABLE)
    locations = app.fresh_feishu_rows(LOCATION_TABLE)
    materials = app.fresh_feishu_rows(app.MATERIAL_TABLE_NAME)
    material_by_id = {
        app.feishu_record_id(row): material_summary(row)
        for row in materials
        if app.feishu_record_id(row)
    }
    location_by_id = {
        app.feishu_record_id(row): row for row in locations if app.feishu_record_id(row)
    }
    client = app.feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法生成仓库位置缓存。")
    access_token = client.tenant_access_token()
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    output_shelves: list[dict] = []
    referenced_images: set[str] = set()
    for shelf in shelves:
        shelf_id = app.feishu_record_id(shelf)
        fields = app.feishu_fields(shelf)
        shelf_code = app.feishu_text(fields, "货架编号")
        if not shelf_code:
            continue
        shelf_images = cached_images(
            attachment_items(fields, "货架图片"),
            prefix=f"shelf-{shelf_code.lower()}",
            access_token=access_token,
            image_dir=IMAGE_DIR,
            cache_root=ROOT,
        )
        referenced_images.update(image["path"] for image in shelf_images)
        row_records: list[dict] = []
        for location_id in link_ids(fields, "关联货架行"):
            location = location_by_id.get(location_id)
            if location is None:
                continue
            location_fields = app.feishu_fields(location)
            row_code = app.feishu_text(location_fields, "货架行")
            row_images = cached_images(
                attachment_items(location_fields, "图片"),
                prefix=f"row-{row_code.lower() or location_id.lower()}",
                access_token=access_token,
                image_dir=IMAGE_DIR,
                cache_root=ROOT,
            )
            referenced_images.update(image["path"] for image in row_images)
            row_materials = [
                material_by_id[record_id]
                for record_id in link_ids(location_fields, "关联物料")
                if record_id in material_by_id
            ]
            row_records.append(
                {
                    "row_code": row_code,
                    "description": app.feishu_text(location_fields, "放置物料文字说明"),
                    "images": row_images,
                    "materials": row_materials,
                }
            )
        direct_materials = [
            material_by_id[record_id]
            for record_id in link_ids(fields, "关联物料")
            if record_id in material_by_id
        ]
        output_shelves.append(
            {
                "shelf_id": shelf_id,
                "shelf_code": shelf_code,
                "ground_location": app.feishu_text(fields, "货架地面位置"),
                "description": app.feishu_text(fields, "放置物料"),
                "images": shelf_images,
                "materials": direct_materials,
                "rows": row_records,
            }
        )

    cleanup_obsolete_images(referenced_images)
    image_count = len(referenced_images)

    return {
        "schema_version": 1,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "manual_feishu_snapshot",
        "image_count": image_count,
        "shelves": output_shelves,
    }


def main() -> None:
    cache = build_cache()
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    image_count = int(cache.get("image_count") or 0)
    print(
        f"Generated {CACHE_PATH} with {len(cache['shelves'])} shelves and {image_count} images."
    )


if __name__ == "__main__":
    main()
