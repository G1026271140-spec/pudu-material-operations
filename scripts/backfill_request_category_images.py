from __future__ import annotations

import mimetypes
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def main() -> int:
    client = app.feishu_client()
    if client is None:
        raise RuntimeError("飞书未配置，无法迁移申领页图片。")
    updates: list[dict[str, object]] = []
    for row in app.fresh_feishu_rows(app.CATEGORY_TABLE_NAME):
        fields = app.feishu_fields(row)
        if list(fields.get(app.REQUEST_CATEGORY_IMAGE_FIELD) or []):
            continue
        category = app.feishu_text(fields, "物料品类")
        image_path = app.legacy_request_category_image_path(category)
        record_id = app.feishu_record_id(row)
        if not record_id or image_path is None:
            continue
        content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        file_token = client.upload_media(image_path.name, image_path.read_bytes(), content_type)
        updates.append(
            {
                "record_id": record_id,
                "fields": {app.REQUEST_CATEGORY_IMAGE_FIELD: [{"file_token": file_token}]},
            }
        )
    updated_count = app.feishu_batch_update_record_fields(app.CATEGORY_TABLE_NAME, updates)
    print(f"request_category_images_backfilled updated={updated_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
