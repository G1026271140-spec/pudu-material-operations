from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from scripts.generate_warehouse_location_cache import cached_images, cleanup_obsolete_images
from scripts.validate_warehouse_location_cache import validate_warehouse_location_cache


class WarehouseImageCacheTests(unittest.TestCase):
    @staticmethod
    def image_bytes() -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (10, 8), color=(25, 100, 180)).save(buffer, "PNG")
        return buffer.getvalue()

    def test_reuses_cache_and_tracks_deleted_attachment(self) -> None:
        attachment = {
            "file_token": "warehouse-image-1",
            "name": "shelf.png",
            "type": "image/png",
            "url": "https://example.invalid/image",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_dir = root / "assets" / "warehouse_locations"
            image_dir.mkdir(parents=True)
            with patch(
                "scripts.generate_warehouse_location_cache.download_attachment",
                return_value=self.image_bytes(),
            ) as download:
                first = cached_images(
                    [attachment],
                    prefix="shelf-h001",
                    access_token="token",
                    image_dir=image_dir,
                    cache_root=root,
                )
                second = cached_images(
                    [attachment],
                    prefix="shelf-h001",
                    access_token="token",
                    image_dir=image_dir,
                    cache_root=root,
                )
            self.assertEqual(first, second)
            download.assert_called_once()
            cache = {
                "schema_version": 1,
                "shelves": [{"images": first, "rows": []}],
                "image_count": 1,
            }
            self.assertEqual(
                validate_warehouse_location_cache(cache, cache_root=root),
                {"shelves": 1, "image_count": 1},
            )
            deleted = cleanup_obsolete_images(
                set(), image_dir=image_dir, cache_root=root
            )
            self.assertEqual(deleted, 1)
            self.assertEqual(list(image_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
