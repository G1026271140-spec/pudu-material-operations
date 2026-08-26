import hashlib
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts.validate_page_data_cache import validate_page_data_cache  # noqa: E402

GIFT_IMAGE_CACHE_RELATIVE_DIR = Path("assets") / "gift_projects"
GIFT_IMAGE_CACHE_DIR = ROOT / GIFT_IMAGE_CACHE_RELATIVE_DIR
REQUEST_IMAGE_CACHE_RELATIVE_DIR = Path("assets") / "request_categories"
REQUEST_IMAGE_CACHE_DIR = ROOT / REQUEST_IMAGE_CACHE_RELATIVE_DIR
GIFT_IMAGE_MAX_DIMENSION = 1600


def is_image_attachment(attachment: dict) -> bool:
    media_type = str(attachment.get("type") or "").strip().lower()
    suffix = Path(str(attachment.get("name") or "")).suffix.lower()
    return media_type.startswith("image/") or suffix in {
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


def gift_image_attachments(cache: dict) -> list[dict]:
    tables = dict(cache.get("tables") or {})
    attachments: list[dict] = []
    for row in list(tables.get(app.GIFT_PROJECT_TABLE_NAME) or []):
        fields = app.feishu_fields(row)
        values = fields.get("物料图片")
        if not isinstance(values, list):
            continue
        attachments.extend(
            attachment
            for attachment in values
            if isinstance(attachment, dict)
            and str(attachment.get("file_token") or "").strip()
            and is_image_attachment(attachment)
        )
    return attachments


def request_category_image_attachments(cache: dict) -> list[dict]:
    tables = dict(cache.get("tables") or {})
    attachments: list[dict] = []
    for row in list(tables.get(app.CATEGORY_TABLE_NAME) or []):
        fields = app.feishu_fields(row)
        values = fields.get(app.REQUEST_CATEGORY_IMAGE_FIELD)
        if not isinstance(values, list):
            continue
        attachments.extend(
            attachment
            for attachment in values
            if isinstance(attachment, dict)
            and str(attachment.get("file_token") or "").strip()
            and is_image_attachment(attachment)
        )
    return attachments


def write_cached_gift_image(content: bytes, target: Path) -> None:
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image.thumbnail(
                (GIFT_IMAGE_MAX_DIMENSION, GIFT_IMAGE_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            image.save(temporary, "WEBP", quality=82, method=6)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def sync_gift_image_cache(
    cache: dict,
    *,
    image_dir: Path = GIFT_IMAGE_CACHE_DIR,
    cache_root: Path = ROOT,
) -> dict[str, int]:
    resolved_root = cache_root.resolve()
    resolved_image_dir = image_dir.resolve()
    if resolved_root != resolved_image_dir and resolved_root not in resolved_image_dir.parents:
        raise ValueError("周边礼品图片缓存目录必须位于项目目录内。")
    resolved_image_dir.mkdir(parents=True, exist_ok=True)

    expected_files: set[Path] = set()
    downloaded_count = 0
    attachments = gift_image_attachments(cache)
    for attachment in attachments:
        file_token = str(attachment.get("file_token") or "").strip()
        digest = hashlib.sha256(file_token.encode("utf-8")).hexdigest()[:20]
        target = resolved_image_dir / f"{digest}.webp"
        expected_files.add(target)
        if not target.is_file() or target.stat().st_size <= 0:
            content = app.load_feishu_attachment(
                file_token,
                str(attachment.get("tmp_url") or attachment.get("url") or ""),
            )
            write_cached_gift_image(content, target)
            downloaded_count += 1
        attachment["cached_path"] = target.relative_to(resolved_root).as_posix()

    deleted_count = 0
    for path in resolved_image_dir.iterdir():
        if path.is_file() and path not in expected_files:
            path.unlink()
            deleted_count += 1

    cache["gift_image_cache"] = {
        "directory": GIFT_IMAGE_CACHE_RELATIVE_DIR.as_posix(),
        "image_count": len(expected_files),
    }
    return {
        "image_count": len(expected_files),
        "downloaded_count": downloaded_count,
        "deleted_count": deleted_count,
    }


def sync_request_category_image_cache(
    cache: dict,
    *,
    image_dir: Path = REQUEST_IMAGE_CACHE_DIR,
    cache_root: Path = ROOT,
) -> dict[str, int]:
    resolved_root = cache_root.resolve()
    resolved_image_dir = image_dir.resolve()
    if resolved_root != resolved_image_dir and resolved_root not in resolved_image_dir.parents:
        raise ValueError("申领页图片缓存目录必须位于项目目录内。")
    resolved_image_dir.mkdir(parents=True, exist_ok=True)
    expected_files: set[Path] = set()
    downloaded_count = 0
    for attachment in request_category_image_attachments(cache):
        file_token = str(attachment.get("file_token") or "").strip()
        digest = hashlib.sha256(file_token.encode("utf-8")).hexdigest()[:20]
        target = resolved_image_dir / f"{digest}.webp"
        expected_files.add(target)
        if not target.is_file() or target.stat().st_size <= 0:
            content = app.load_feishu_attachment(
                file_token,
                str(attachment.get("tmp_url") or attachment.get("url") or ""),
            )
            write_cached_gift_image(content, target)
            downloaded_count += 1
        attachment["cached_path"] = target.relative_to(resolved_root).as_posix()
    deleted_count = 0
    for path in resolved_image_dir.iterdir():
        if path.is_file() and path not in expected_files:
            path.unlink()
            deleted_count += 1
    cache["request_category_image_cache"] = {
        "directory": REQUEST_IMAGE_CACHE_RELATIVE_DIR.as_posix(),
        "image_count": len(expected_files),
    }
    return {
        "image_count": len(expected_files),
        "downloaded_count": downloaded_count,
        "deleted_count": deleted_count,
    }


def main() -> int:
    try:
        link_stats = app.sync_feishu_gift_project_category_links()
    except (RuntimeError, ValueError, app.FeishuBitableError) as exc:
        print(f"gift_project_category_links_not_synced: {exc}", file=sys.stderr)
        return 1
    cache = app.build_page_data_static_snapshot()
    counts = cache.get("row_counts") or {}
    required_counts = {
        app.CATEGORY_TABLE_NAME: int(counts.get(app.CATEGORY_TABLE_NAME) or 0),
        app.MATERIAL_TABLE_NAME: int(counts.get(app.MATERIAL_TABLE_NAME) or 0),
        app.CULTURAL_MATERIAL_TABLE_NAME: int(counts.get(app.CULTURAL_MATERIAL_TABLE_NAME) or 0),
    }
    if any(row_count <= 0 for row_count in required_counts.values()):
        print(
            "page_data_cache_not_written: required Feishu tables returned no rows",
            required_counts,
            file=sys.stderr,
        )
        return 1
    try:
        image_stats = sync_gift_image_cache(cache)
        stats = validate_page_data_cache(
            cache,
            require_data=True,
            require_cached_gift_images=True,
            cache_root=ROOT,
        )
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
        f"gift_images={image_stats['image_count']}",
        f"downloaded={image_stats['downloaded_count']}",
        f"deleted={image_stats['deleted_count']}",
        f"gift_link_updates={link_stats['written_count']}",
    )
    for table_name, row_count in counts.items():
        print(f"  {table_name}: {row_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
