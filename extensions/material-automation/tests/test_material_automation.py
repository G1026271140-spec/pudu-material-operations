from __future__ import annotations

import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch
from pathlib import Path

from material_automation import AutomationError, MaterialAutomation, Settings, archive_match_key, classify_file, extract_archive, find_existing_archive, merge_tokens, record_has_results, safe_delete_archive, safe_extract_zip, sanitize_component


class MaterialAutomationTests(unittest.TestCase):
    def make_settings(self, root: Path) -> Settings:
        return Settings("id", "secret", "token", "table", "source", "images", "videos", root, root / "state.json", root / "log.txt", 30, 30, 1024, 10, True)

    def test_classifies_images_and_videos(self) -> None:
        self.assertEqual(classify_file(Path("photo.JPG")), "image")
        self.assertEqual(classify_file(Path("clip.MP4")), "video")
        self.assertIsNone(classify_file(Path("notes.txt")))

    def test_sanitizes_windows_path_characters(self) -> None:
        self.assertEqual(sanitize_component('深圳:地标/一号*', "unknown"), "深圳_地标_一号")

    def test_merges_tokens_without_duplicates(self) -> None:
        self.assertEqual(merge_tokens(["a", "b"], ["b", "c", ""]), ["a", "b", "c"])

    def test_detects_results_in_either_output_field(self) -> None:
        self.assertFalse(record_has_results({"images": [], "videos": []}, "images", "videos"))
        self.assertTrue(record_has_results({"images": [{"file_token": "image-1"}]}, "images", "videos"))
        self.assertTrue(record_has_results({"videos": [{"file_token": "video-1"}]}, "images", "videos"))

    def test_run_once_requeues_stale_complete_row_with_empty_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            automation = MaterialAutomation(self.make_settings(root), Mock())
            automation.state.data = {
                "version": 1,
                "initialized": True,
                "sources": {"source-1": {"status": "complete"}},
            }
            automation.client = Mock()
            automation.client.list_records.return_value = [{
                "record_id": "rec-missed",
                "fields": {
                    "source": [{"file_token": "source-1", "name": "missed.zip", "size": 1}],
                    "images": [],
                    "videos": [],
                },
            }]
            automation._process_source = Mock()

            self.assertEqual(automation.run_once(), 1)
            automation._process_source.assert_called_once()
            self.assertEqual(automation.state.data["sources"]["source-1"]["status"], "pending")

    def test_run_once_keeps_completed_row_skipped_when_results_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            automation = MaterialAutomation(self.make_settings(root), Mock())
            automation.state.data = {
                "version": 1,
                "initialized": True,
                "sources": {"source-1": {"status": "complete"}},
            }
            automation.client = Mock()
            automation.client.list_records.return_value = [{
                "record_id": "rec-done",
                "fields": {
                    "source": [{"file_token": "source-1", "name": "done.zip", "size": 1}],
                    "images": [{"file_token": "result-1"}],
                    "videos": [],
                },
            }]
            automation._process_source = Mock()

            self.assertEqual(automation.run_once(), 0)
            automation._process_source.assert_not_called()

    def test_attachment_field_keeps_partial_success_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            automation = MaterialAutomation(self.make_settings(root), Mock())
            automation.client = Mock()

            def update_record(_record_id, fields):
                tokens = [item["file_token"] for item in fields["images"]]
                if len(tokens) > 3:
                    raise AutomationError("飞书 API 1254069: AttachFieldConvFail")

            automation.client.update_record.side_effect = update_record
            committed, limited = automation._write_attachment_field_best_effort(
                "rec-1", "images", ["old-1"], ["new-1", "new-2", "new-3", "new-4"], batch_size=20,
            )

            self.assertEqual(committed, ["old-1", "new-1", "new-2"])
            self.assertTrue(limited)

    def test_attachment_field_reraises_unrelated_api_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            automation = MaterialAutomation(self.make_settings(root), Mock())
            automation.client = Mock()
            automation.client.update_record.side_effect = AutomationError("permission denied")

            with self.assertRaisesRegex(AutomationError, "permission denied"):
                automation._write_attachment_field_best_effort("rec-1", "images", [], ["new-1"])

    def test_direct_image_is_written_without_archive_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "photo.jpg"
            source.write_bytes(b"image")
            automation = MaterialAutomation(self.make_settings(root), Mock())
            automation.client = Mock()
            automation.client.upload_attachment.return_value = "uploaded-image"
            automation.state.data = {"version": 1, "initialized": True, "sources": {}}

            with patch("material_automation.safe_delete_archive") as delete_archive:
                automation._process_source(
                    "rec-image",
                    {"images": [], "videos": []},
                    {"file_token": "source-image", "name": "photo.jpg"},
                )

            delete_archive.assert_not_called()
            automation.client.update_record.assert_called_once_with(
                "rec-image", {"images": [{"file_token": "uploaded-image"}]},
            )
            self.assertEqual(automation.state.data["sources"]["source-image"]["status"], "complete")

    def test_archive_matching_ignores_spaces_and_underscores(self) -> None:
        self.assertEqual(archive_match_key("2026 MT1 Max 素材.zip"), archive_match_key("2026_MT1_Max_素材.zip"))

    def test_finds_unique_archive_with_local_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prefixed = root / "土耳其wetransfer_media.zip"
            prefixed.write_bytes(b"zip")
            self.assertEqual(find_existing_archive(root, "wetransfer_media.zip"), prefixed)

    def test_extracts_safe_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "media.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("images/photo.jpg", b"image")
            extracted = safe_extract_zip(archive, root / "out", 1024, 10)
            self.assertEqual(len(extracted), 1)
            self.assertEqual(extracted[0].read_bytes(), b"image")

    def test_rejects_zip_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escape.jpg", b"image")
            with self.assertRaises(AutomationError):
                safe_extract_zip(archive, root / "out", 1024, 10)

    def test_deletes_archive_only_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "materials"
            root.mkdir()
            archive = root / "done.zip"
            archive.write_bytes(b"zip")
            self.assertTrue(safe_delete_archive(archive, root))
            self.assertFalse(archive.exists())

    def test_rejects_deleting_archive_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "materials"
            root.mkdir()
            archive = base / "outside.zip"
            archive.write_bytes(b"zip")
            with self.assertRaises(AutomationError):
                safe_delete_archive(archive, root)
            self.assertTrue(archive.exists())

    @unittest.skipUnless(__import__("sys").platform == "win32", "Windows-only process flags")
    def test_7zip_runs_without_a_console_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "media.rar"
            archive.write_bytes(b"rar")
            destination = root / "out"
            settings = Settings("id", "secret", "token", "table", "source", "images", "videos", root, root / "state.json", root / "log.txt", 30, 30, 1024, 10, True)
            with patch("material_automation.find_7zip", return_value=Path("C:/fake/7z.exe")), patch("material_automation.subprocess.run") as mocked_run:
                mocked_run.return_value.returncode = 0
                extract_archive(archive, destination, settings)
                kwargs = mocked_run.call_args.kwargs
                self.assertEqual(kwargs["creationflags"], __import__("subprocess").CREATE_NO_WINDOW)
                self.assertTrue(kwargs["startupinfo"].dwFlags & __import__("subprocess").STARTF_USESHOWWINDOW)


if __name__ == "__main__":
    unittest.main()
