from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app
from scripts.generate_page_data_cache import sync_gift_image_cache
from scripts.validate_page_data_cache import validate_page_data_cache


class GiftImageCacheTests(unittest.TestCase):
    @staticmethod
    def png_bytes() -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (8, 6), color=(20, 140, 110)).save(buffer, "PNG")
        return buffer.getvalue()

    @staticmethod
    def cache() -> dict:
        return {
            "tables": {
                app.MODEL_TABLE_NAME: [],
                app.CULTURAL_MATERIAL_TABLE_NAME: [],
                app.CATEGORY_TABLE_NAME: [
                    {
                        "record_id": "category-gift",
                        "fields": {
                            "物料品类": "定制帽子",
                            "品类定义": app.CATEGORY_DEFINITION_GIFT,
                        },
                    }
                ],
                app.MATERIAL_TABLE_NAME: [
                    {
                        "record_id": "material-hat",
                        "fields": {
                            "物料编码": "MAT-0001",
                            "物料品类": "定制帽子",
                        },
                    }
                ],
                app.GIFT_PROJECT_TABLE_NAME: [
                    {
                        "record_id": "project-hat",
                        "fields": {
                            "项目名称": "展会",
                            "物料名称": "定制帽子",
                            "物料图片": [
                                {
                                    "file_token": "file-hat",
                                    "name": "hat.png",
                                    "type": "image/png",
                                    "url": "https://open.feishu.cn/image",
                                }
                            ],
                        },
                    }
                ],
            },
            "row_counts": {
                app.MODEL_TABLE_NAME: 0,
                app.CULTURAL_MATERIAL_TABLE_NAME: 0,
                app.CATEGORY_TABLE_NAME: 1,
                app.MATERIAL_TABLE_NAME: 1,
                app.GIFT_PROJECT_TABLE_NAME: 1,
            },
        }

    def test_sync_downloads_reuses_and_deletes_static_gift_images(self) -> None:
        cache = self.cache()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_dir = root / "assets" / "gift_projects"
            image_dir.mkdir(parents=True)
            obsolete = image_dir / "obsolete.webp"
            obsolete.write_bytes(b"old")

            with patch.object(
                app,
                "load_feishu_attachment",
                return_value=self.png_bytes(),
            ) as loader:
                stats = sync_gift_image_cache(
                    cache,
                    image_dir=image_dir,
                    cache_root=root,
                )

            attachment = cache["tables"][app.GIFT_PROJECT_TABLE_NAME][0]["fields"][
                "物料图片"
            ][0]
            cached_path = str(attachment["cached_path"])
            self.assertEqual(stats["downloaded_count"], 1)
            self.assertEqual(stats["deleted_count"], 1)
            self.assertFalse(obsolete.exists())
            self.assertTrue((root / cached_path).is_file())
            loader.assert_called_once()

            with patch.object(app, "load_feishu_attachment") as reused_loader:
                reused_stats = sync_gift_image_cache(
                    cache,
                    image_dir=image_dir,
                    cache_root=root,
                )

            self.assertEqual(reused_stats["downloaded_count"], 0)
            reused_loader.assert_not_called()
            validation = validate_page_data_cache(
                cache,
                require_data=True,
                require_cached_gift_images=True,
                cache_root=root,
            )
            self.assertEqual(validation["gift_image_count"], 1)

            cache["tables"][app.GIFT_PROJECT_TABLE_NAME][0]["fields"][
                "物料图片"
            ] = []
            removed_stats = sync_gift_image_cache(
                cache,
                image_dir=image_dir,
                cache_root=root,
            )

            self.assertEqual(removed_stats["deleted_count"], 1)
            self.assertEqual(list(image_dir.iterdir()), [])

    def test_validator_rejects_missing_cached_gift_image_file(self) -> None:
        cache = self.cache()
        cache["tables"][app.GIFT_PROJECT_TABLE_NAME][0]["fields"]["物料图片"][0][
            "cached_path"
        ] = "assets/gift_projects/missing.webp"
        cache["gift_image_cache"] = {
            "directory": "assets/gift_projects",
            "image_count": 1,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "周边礼品静态图片不存在"):
                validate_page_data_cache(
                    cache,
                    require_data=True,
                    require_cached_gift_images=True,
                    cache_root=Path(temp_dir),
                )


if __name__ == "__main__":
    unittest.main()
