from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import zlib
import zipfile
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests

OPEN_API = "https://open.feishu.cn/open-apis"
UPLOAD_ALL_LIMIT = 20 * 1024 * 1024
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")
IMAGE_EXTENSIONS = {".arw", ".bmp", ".cr2", ".cr3", ".dng", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".nef", ".orf", ".png", ".raf", ".raw", ".tif", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".3gp", ".avi", ".flv", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".webm", ".wmv"}
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


class AutomationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    app_id: str
    app_secret: str
    app_token: str
    table_id: str
    source_field: str
    image_field: str
    video_field: str
    download_root: Path
    state_file: Path
    log_file: Path
    poll_interval_seconds: int
    request_timeout_seconds: int
    max_extract_bytes: int
    max_archive_entries: int
    delete_archive_after_success: bool


def expand_path(value: str, base_dir: Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(value.strip())))
    return (path if path.is_absolute() else base_dir / path).resolve()


def load_settings(config_path: Path) -> Settings:
    config_path = config_path.resolve()
    if not config_path.exists():
        raise AutomationError(f"配置文件不存在：{config_path}")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    feishu = dict(config.get("feishu") or {})
    worker = dict(config.get("worker") or {})
    credentials: dict[str, Any] = {}
    credentials_file = str(feishu.get("credentials_file") or "").strip()
    if credentials_file:
        credentials_path = expand_path(credentials_file, config_path.parent)
        if not credentials_path.exists():
            raise AutomationError(f"飞书凭据文件不存在：{credentials_path}")
        credentials = tomllib.loads(credentials_path.read_text(encoding="utf-8"))
    app_id = str(os.getenv("FEISHU_APP_ID") or feishu.get("app_id") or credentials.get("FEISHU_APP_ID") or "").strip()
    app_secret = str(os.getenv("FEISHU_APP_SECRET") or feishu.get("app_secret") or credentials.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise AutomationError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET。")
    names = ("app_token", "table_id", "source_field", "image_field", "video_field")
    required = {name: str(feishu.get(name) or "").strip() for name in names}
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise AutomationError(f"配置缺少字段：{', '.join(missing)}")
    return Settings(
        app_id=app_id, app_secret=app_secret, app_token=required["app_token"], table_id=required["table_id"],
        source_field=required["source_field"], image_field=required["image_field"], video_field=required["video_field"],
        download_root=expand_path(str(worker.get("download_root") or "~/Desktop/全球之旅素材整理"), config_path.parent),
        state_file=expand_path(str(worker.get("state_file") or "state/processed.json"), config_path.parent),
        log_file=expand_path(str(worker.get("log_file") or "logs/worker.log"), config_path.parent),
        poll_interval_seconds=max(10, int(worker.get("poll_interval_seconds") or 30)),
        request_timeout_seconds=max(30, int(worker.get("request_timeout_seconds") or 120)),
        max_extract_bytes=max(1024 * 1024, int(worker.get("max_extract_bytes") or 50 * 1024**3)),
        max_archive_entries=max(1, int(worker.get("max_archive_entries") or 10000)),
        delete_archive_after_success=bool(worker.get("delete_archive_after_success", True)),
    )


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("global_journey_material_automation")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


class FeishuClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self._token = ""
        self._token_expires_at = 0.0

    def tenant_access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        response = self.session.post(
            f"{OPEN_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.settings.app_id, "app_secret": self.settings.app_secret},
            timeout=self.settings.request_timeout_seconds,
        )
        data = self._json_response(response)
        self._token = str(data.get("tenant_access_token") or "").strip()
        if not self._token:
            raise AutomationError("飞书未返回 tenant_access_token。")
        self._token_expires_at = time.time() + int(data.get("expire") or 7200) - 120
        return self._token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tenant_access_token()}"}

    def list_fields(self) -> list[dict[str, Any]]:
        return self._paged_get(
            f"/bitable/v1/apps/{quote(self.settings.app_token)}/tables/{quote(self.settings.table_id)}/fields"
        )

    def list_records(self) -> list[dict[str, Any]]:
        return self._paged_get(
            f"/bitable/v1/apps/{quote(self.settings.app_token)}/tables/{quote(self.settings.table_id)}/records",
            page_size=500,
        )

    def update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        response = self.session.put(
            f"{OPEN_API}/bitable/v1/apps/{quote(self.settings.app_token)}/tables/{quote(self.settings.table_id)}/records/{quote(record_id)}",
            headers=self.headers(),
            json={"fields": fields},
            timeout=self.settings.request_timeout_seconds,
        )
        self._json_response(response)

    def download_attachment(self, attachment: dict[str, Any], destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        temporary.unlink(missing_ok=True)
        tmp_url = str(attachment.get("tmp_url") or "").strip()
        if tmp_url:
            response = self.session.get(tmp_url, headers=self.headers(), timeout=self.settings.request_timeout_seconds)
            data = self._json_response(response)
            candidates = list((data.get("data") or {}).get("tmp_download_urls") or [])
            file_token = str(attachment.get("file_token") or "")
            signed_url = next(
                (str(item.get("tmp_download_url") or "") for item in candidates if str(item.get("file_token") or "") == file_token),
                str(candidates[0].get("tmp_download_url") or "") if candidates else "",
            ).strip()
            if not signed_url:
                raise AutomationError(f"飞书未返回附件下载地址：{attachment.get('name')}")
            download_response = self.session.get(signed_url, stream=True, timeout=self.settings.request_timeout_seconds)
        else:
            file_token = str(attachment.get("file_token") or "").strip()
            if not file_token:
                raise AutomationError("附件缺少 file_token。")
            download_response = self.session.get(
                f"{OPEN_API}/drive/v1/medias/{quote(file_token)}/download",
                headers=self.headers(),
                stream=True,
                timeout=self.settings.request_timeout_seconds,
            )
        try:
            download_response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in download_response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
            if not temporary.exists() or temporary.stat().st_size == 0:
                raise AutomationError(f"下载得到空文件：{destination.name}")
            os.replace(temporary, destination)
        finally:
            download_response.close()
            temporary.unlink(missing_ok=True)

    def upload_attachment(self, path: Path) -> str:
        if path.stat().st_size <= UPLOAD_ALL_LIMIT:
            return self._upload_all(path)
        return self._multipart_upload(path)

    def _upload_all(self, path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = {
            "file_name": path.name,
            "parent_type": "bitable_file",
            "parent_node": self.settings.app_token,
            "size": str(path.stat().st_size),
            "extra": json.dumps({"drive_route_token": self.settings.app_token}),
        }
        with path.open("rb") as content:
            response = self.session.post(
                f"{OPEN_API}/drive/v1/medias/upload_all",
                headers=self.headers(),
                data=data,
                files={"file": (path.name, content, mime_type)},
                timeout=self.settings.request_timeout_seconds,
            )
        return self._require_file_token(self._json_response(response), path)

    def _multipart_upload(self, path: Path) -> str:
        response = self.session.post(
            f"{OPEN_API}/drive/v1/medias/upload_prepare",
            headers=self.headers(),
            json={
                "file_name": path.name,
                "parent_type": "bitable_file",
                "parent_node": self.settings.app_token,
                "size": path.stat().st_size,
                "extra": json.dumps({"drive_route_token": self.settings.app_token}),
            },
            timeout=self.settings.request_timeout_seconds,
        )
        data = dict(self._json_response(response).get("data") or {})
        upload_id = str(data.get("upload_id") or "").strip()
        block_size = int(data.get("block_size") or 0)
        block_num = int(data.get("block_num") or 0)
        if not upload_id or block_size <= 0 or block_num <= 0:
            raise AutomationError(f"飞书未返回有效的大文件上传参数：{path.name}")
        with path.open("rb") as content:
            for sequence in range(block_num):
                chunk = content.read(block_size)
                if not chunk:
                    raise AutomationError(f"大文件分片数量不匹配：{path.name}")
                part = self.session.post(
                    f"{OPEN_API}/drive/v1/medias/upload_part",
                    headers=self.headers(),
                    data={
                        "upload_id": upload_id,
                        "seq": str(sequence),
                        "size": str(len(chunk)),
                        "checksum": str(zlib.adler32(chunk) & 0xFFFFFFFF),
                    },
                    files={"file": (path.name, chunk, "application/octet-stream")},
                    timeout=self.settings.request_timeout_seconds,
                )
                self._json_response(part)
        finish = self.session.post(
            f"{OPEN_API}/drive/v1/medias/upload_finish",
            headers=self.headers(),
            json={"upload_id": upload_id, "block_num": block_num},
            timeout=self.settings.request_timeout_seconds,
        )
        return self._require_file_token(self._json_response(finish), path)

    def probe_download(self, attachment: dict[str, Any]) -> None:
        tmp_url = str(attachment.get("tmp_url") or "").strip()
        if not tmp_url:
            return
        response = self.session.get(tmp_url, headers=self.headers(), timeout=self.settings.request_timeout_seconds)
        candidates = list((self._json_response(response).get("data") or {}).get("tmp_download_urls") or [])
        if not candidates:
            raise AutomationError("附件下载权限检查失败：没有临时下载地址。")
        probe = self.session.get(
            str(candidates[0].get("tmp_download_url") or ""),
            headers={"Range": "bytes=0-0"},
            stream=True,
            timeout=self.settings.request_timeout_seconds,
        )
        try:
            probe.raise_for_status()
            next(probe.iter_content(chunk_size=1), b"")
        finally:
            probe.close()

    def _paged_get(self, path: str, page_size: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            response = self.session.get(
                OPEN_API + path,
                headers=self.headers(),
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            data = dict(self._json_response(response).get("data") or {})
            items.extend(list(data.get("items") or []))
            if not data.get("has_more"):
                return items
            page_token = str(data.get("page_token") or "").strip()
            if not page_token:
                return items

    @staticmethod
    def _require_file_token(payload: dict[str, Any], path: Path) -> str:
        file_token = str((payload.get("data") or {}).get("file_token") or "").strip()
        if not file_token:
            raise AutomationError(f"飞书未返回上传后的 file_token：{path.name}")
        return file_token

    @staticmethod
    def _json_response(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AutomationError(f"飞书 HTTP {response.status_code} 返回了非 JSON 内容。") from exc
        if response.status_code >= 400:
            raise AutomationError(f"飞书 HTTP {response.status_code}: {payload.get('msg') or response.reason}")
        if payload.get("code") not in (None, 0):
            raise AutomationError(f"飞书 API {payload.get('code')}: {payload.get('msg')}")
        return payload


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AutomationError(f"状态文件损坏：{path}") from exc
        else:
            self.data = {"version": 1, "initialized": False, "sources": {}}
        self.data.setdefault("initialized", False)
        self.data.setdefault("sources", {})

    @property
    def initialized(self) -> bool:
        return bool(self.data.get("initialized"))

    def contains(self, file_token: str) -> bool:
        return file_token in self.data["sources"]

    def source(self, file_token: str) -> dict[str, Any]:
        return self.data["sources"].setdefault(file_token, {})

    def mark_baseline(self, file_token: str, record_id: str, file_name: str) -> None:
        if not self.contains(file_token):
            self.source(file_token).update({
                "status": "baseline", "record_id": record_id,
                "file_name": file_name, "updated_at": int(time.time()),
            })

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)


def extract_display_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("text", "name", "value", "full_name"):
            if value.get(key) is not None:
                return str(value[key]).strip()
        return ""
    return str(value).strip()


def sanitize_component(value: Any, fallback: str, limit: int = 60) -> str:
    if isinstance(value, list):
        text = "_".join(extract_display_text(item) for item in value)
    else:
        text = extract_display_text(value)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", text).strip(" ._")
    text = re.sub(r"\s+", " ", text)
    return text[:limit].rstrip(" ._") or fallback


def attachment_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and item.get("file_token")]


def attachment_tokens(value: Any) -> list[str]:
    return [str(item["file_token"]) for item in attachment_items(value)]


def record_has_results(fields: dict[str, Any], image_field: str, video_field: str) -> bool:
    """Return whether a row already contains any material produced by this task."""
    return bool(attachment_items(fields.get(image_field)) or attachment_items(fields.get(video_field)))


def classify_file(path: Path) -> str | None:
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return "image"
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        return "video"
    return None


def safe_extract_zip(archive_path: Path, destination: Path, max_extract_bytes: int, max_archive_entries: int) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    extracted: list[Path] = []
    with zipfile.ZipFile(archive_path, metadata_encoding="gbk") as archive:
        members = archive.infolist()
        if len(members) > max_archive_entries:
            raise AutomationError(f"压缩包文件数量超过限制：{len(members)}")
        total_size = sum(max(0, item.file_size) for item in members)
        if total_size > max_extract_bytes:
            raise AutomationError(f"压缩包解压后大小超过限制：{total_size} 字节")
        for member in members:
            if member.flag_bits & 0x1:
                raise AutomationError(f"不支持加密压缩包：{archive_path.name}")
            if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                continue
            target = (destination / member.filename).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise AutomationError(f"压缩包包含不安全路径：{member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted.append(target)
    return extracted


def archive_match_key(name: str) -> str:
    return re.sub(r"[\s_]+", "", name).casefold()


def find_existing_archive(root: Path, file_name: str) -> Path | None:
    direct = root / file_name
    if direct.is_file():
        return direct
    wanted = archive_match_key(file_name)
    suffix_matches: list[Path] = []
    for path in root.glob("*"):
        if path.is_file() and path.suffix.lower() in {".zip", ".rar", ".7z"}:
            candidate = archive_match_key(path.name)
            if candidate == wanted:
                return path
            if candidate.endswith(wanted):
                suffix_matches.append(path)
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    return None


def safe_delete_archive(path: Path, root: Path) -> bool:
    if path.suffix.lower() not in {".zip", ".rar", ".7z"}:
        raise AutomationError(f"拒绝删除非压缩文件：{path}")
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if path_resolved.parent != root_resolved:
        raise AutomationError(f"拒绝删除素材目录外的文件：{path}")
    if not path_resolved.exists():
        return False
    if not path_resolved.is_file():
        raise AutomationError(f"拒绝删除非普通文件：{path}")
    path_resolved.unlink()
    return True


def find_7zip() -> Path | None:
    candidates = [
        shutil.which("7z.exe"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    return next((Path(item) for item in candidates if item and Path(item).is_file()), None)


def extract_archive(archive_path: Path, destination: Path, settings: Settings) -> list[Path]:
    suffix = archive_path.suffix.lower()
    if suffix not in {".zip", ".rar", ".7z"} and not zipfile.is_zipfile(archive_path):
        raise AutomationError(f"不支持的压缩格式：{archive_path.name}")
    seven_zip = find_7zip()
    if not seven_zip:
        if suffix == ".zip" or zipfile.is_zipfile(archive_path):
            return safe_extract_zip(archive_path, destination, settings.max_extract_bytes, settings.max_archive_entries)
        raise AutomationError("处理 RAR/7z 需要安装 7-Zip。")
    destination.mkdir(parents=True, exist_ok=True)
    subprocess_options: dict[str, Any] = {}
    if sys.platform == "win32":
        subprocess_options["creationflags"] = subprocess.CREATE_NO_WINDOW
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = 0
        subprocess_options["startupinfo"] = startup_info
    result = subprocess.run(
        [str(seven_zip), "x", "-y", f"-o{destination}", str(archive_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        **subprocess_options,
    )
    if result.returncode not in {0, 1}:
        raise AutomationError(f"7-Zip 解压失败：{result.stderr or result.stdout}")
    files = [path for path in destination.rglob("*") if path.is_file()]
    total_size = sum(path.stat().st_size for path in files)
    if total_size > settings.max_extract_bytes:
        raise AutomationError(f"解压后大小超过限制：{total_size} 字节")
    return files


def iter_media_files(paths: Iterable[Path]) -> list[tuple[Path, str]]:
    results = []
    for path in paths:
        ignored = path.name.lower() in IGNORED_NAMES or path.name.startswith("._") or "__MACOSX" in path.parts
        category = classify_file(path)
        if path.is_file() and not ignored and category:
            results.append((path, category))
    return sorted(results, key=lambda item: str(item[0]).lower())


def merge_tokens(existing: Iterable[str], new: Iterable[str]) -> list[str]:
    result: list[str] = []
    for token in [*existing, *new]:
        token = str(token).strip()
        if token and token not in result:
            result.append(token)
    return result


class MaterialAutomation:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.client = FeishuClient(settings)
        self.state = StateStore(settings.state_file)

    def check(self) -> None:
        fields = self.client.list_fields()
        by_name = {str(field.get("field_name")): field for field in fields}
        expected = (self.settings.source_field, self.settings.image_field, self.settings.video_field)
        missing = [name for name in expected if name not in by_name]
        if missing:
            raise AutomationError(f"目标表缺少字段：{', '.join(missing)}")
        wrong_type = [name for name in expected if int(by_name[name].get("type") or 0) != 17]
        if wrong_type:
            raise AutomationError(f"以下字段不是附件字段：{', '.join(wrong_type)}")
        records = self.client.list_records()
        first_attachment = next((item for record in records for item in attachment_items((record.get("fields") or {}).get(self.settings.source_field))), None)
        if first_attachment:
            self.client.probe_download(first_attachment)
        self.settings.download_root.mkdir(parents=True, exist_ok=True)
        self.logger.info("检查通过：目标表 %s，共 %d 条记录。", self.settings.table_id, len(records))

    def initialize(self) -> int:
        count = 0
        for record in self.client.list_records():
            record_id = str(record.get("record_id") or "")
            fields = dict(record.get("fields") or {})
            for item in attachment_items(fields.get(self.settings.source_field)):
                file_token = str(item.get("file_token") or "")
                if file_token and not self.state.contains(file_token):
                    self.state.mark_baseline(file_token, record_id, str(item.get("name") or ""))
                    count += 1
        self.state.data["initialized"] = True
        self.state.data["initialized_at"] = int(time.time())
        self.state.save()
        self.logger.info("初始化完成：已将 %d 个现有压缩包标记为历史数据。", count)
        return count

    def run_once(self) -> int:
        if not self.state.initialized:
            self.logger.warning("首次运行先建立历史基线，再补处理结果栏为空的记录。")
            self.initialize()
        processed = 0
        incomplete_record_ids: set[str] = set()
        candidates: list[tuple[int, int, str, dict[str, Any], dict[str, Any]]] = []
        for record in self.client.list_records():
            record_id = str(record.get("record_id") or "").strip()
            fields = dict(record.get("fields") or {})
            has_results = record_has_results(fields, self.settings.image_field, self.settings.video_field)
            for attachment in attachment_items(fields.get(self.settings.source_field)):
                file_token = str(attachment.get("file_token") or "").strip()
                status = str(self.state.data["sources"].get(file_token, {}).get("status") or "")
                if not record_id or not file_token:
                    continue
                # The live row is the source of truth. A stale local baseline/complete
                # marker must not hide a row whose result columns are still empty.
                if status in {"baseline", "complete"} and has_results:
                    continue
                if not has_results:
                    incomplete_record_ids.add(record_id)
                    if status in {"baseline", "complete"}:
                        source_state = self.state.source(file_token)
                        source_state.update({
                            "status": "pending", "record_id": record_id,
                            "file_name": str(attachment.get("name") or ""),
                            "reconciled_at": int(time.time()),
                        })
                file_name = sanitize_component(attachment.get("name"), file_token, 180)
                local_priority = 0 if find_existing_archive(self.settings.download_root, file_name) else 1
                file_size = int(attachment.get("size") or 0)
                candidates.append((local_priority, file_size, record_id, fields, attachment))
        self.state.save()
        self.logger.info(
            "本轮已检查全表，发现 %d 条未完成记录、%d 个待处理附件。",
            len(incomplete_record_ids), len(candidates),
        )
        for _, _, record_id, fields, attachment in sorted(candidates, key=lambda item: (item[0], item[1])):
            try:
                self._process_source(record_id, fields, attachment)
                processed += 1
            except Exception:
                continue
        if processed:
            self.logger.info("本轮处理完成：%d 个新附件。", processed)
        return processed

    def requeue_incomplete(self, record_id_filter: str = "") -> int:
        queued = 0
        for record in self.client.list_records():
            record_id = str(record.get("record_id") or "").strip()
            if record_id_filter and record_id != record_id_filter:
                continue
            fields = dict(record.get("fields") or {})
            if attachment_items(fields.get(self.settings.image_field)) or attachment_items(fields.get(self.settings.video_field)):
                continue
            for attachment in attachment_items(fields.get(self.settings.source_field)):
                file_token = str(attachment.get("file_token") or "").strip()
                if not file_token:
                    continue
                source_state = self.state.source(file_token)
                source_state.update({
                    "status": "pending", "record_id": record_id,
                    "file_name": str(attachment.get("name") or ""),
                    "requeued_at": int(time.time()),
                })
                queued += 1
        self.state.save()
        self.logger.info("已重新入队 %d 个未完成压缩包。", queued)
        return queued

    def cleanup_completed_archives(self) -> int:
        deleted = 0
        for source_state in self.state.data["sources"].values():
            if source_state.get("status") != "complete":
                continue
            file_name = str(source_state.get("file_name") or "").strip()
            if not file_name:
                continue
            archive_path = find_existing_archive(self.settings.download_root, file_name)
            if archive_path is None:
                source_state.setdefault("archive_deleted_at", int(time.time()))
                continue
            if safe_delete_archive(archive_path, self.settings.download_root):
                deleted += 1
                source_state["archive_deleted_at"] = int(time.time())
                source_state["archive_path"] = str(archive_path)
                self.logger.info("已删除成功任务的本地压缩包：%s", archive_path)
        self.state.save()
        self.logger.info("历史成功压缩包清理完成：删除 %d 个文件。", deleted)
        return deleted

    def _record_directory(self, record_id: str, fields: dict[str, Any]) -> Path:
        date_text = sanitize_component(fields.get("提交日期 | Submission Date"), time.strftime("%Y-%m-%d"), 20)
        city = sanitize_component(fields.get("地区+城市 | Region + City"), "未填写城市")
        landmark = sanitize_component(fields.get("点位 | Landmark Name"), "未填写点位")
        folder = self.settings.download_root / f"{date_text}_{city}_{landmark}_{record_id[-8:]}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _write_attachment_field_best_effort(
        self,
        record_id: str,
        field_name: str,
        existing_tokens: list[str],
        new_tokens: list[str],
        batch_size: int = 20,
    ) -> tuple[list[str], bool]:
        """Write as many attachments as the Base field accepts, preserving partial success."""
        committed = merge_tokens(existing_tokens, [])
        pending = [token for token in merge_tokens([], new_tokens) if token not in committed]
        limit_reached = False
        while pending:
            chunk = pending[:batch_size]
            candidate = merge_tokens(committed, chunk)
            try:
                self.client.update_record(
                    record_id,
                    {field_name: [{"file_token": token} for token in candidate]},
                )
                committed = candidate
                pending = pending[len(chunk):]
                continue
            except AutomationError as exc:
                if "AttachFieldConvFail" not in str(exc):
                    raise

            # The batch crossed the attachment-field limit. Add items one at a
            # time so any remaining capacity is still used.
            for token in chunk:
                candidate = merge_tokens(committed, [token])
                try:
                    self.client.update_record(
                        record_id,
                        {field_name: [{"file_token": item} for item in candidate]},
                    )
                    committed = candidate
                except AutomationError as exc:
                    if "AttachFieldConvFail" not in str(exc):
                        raise
                    limit_reached = True
                    self.logger.warning(
                        "记录 %s 的字段“%s”已达到附件上限，保留已成功写入的 %d 个附件。",
                        record_id, field_name, len(committed),
                    )
                    return committed, limit_reached
            pending = pending[len(chunk):]
        return committed, limit_reached

    def _process_source(self, record_id: str, fields: dict[str, Any], attachment: dict[str, Any]) -> None:
        file_token = str(attachment["file_token"])
        file_name = sanitize_component(attachment.get("name"), f"{file_token}.zip", 180)
        record_dir = self._record_directory(record_id, fields)
        archive_path = find_existing_archive(self.settings.download_root, file_name)
        if archive_path is None:
            archive_path = self.settings.download_root / file_name
        extracted_dir = self.settings.download_root / f"{archive_path.stem}_已解压"
        source_state = self.state.source(file_token)
        source_state.update({
            "status": "processing", "record_id": record_id, "file_name": file_name,
            "record_dir": str(record_dir), "uploaded": dict(source_state.get("uploaded") or {}),
            "updated_at": int(time.time()),
        })
        self.state.save()
        self.logger.info("开始处理记录 %s 的附件：%s", record_id, file_name)
        try:
            if not archive_path.exists() or archive_path.stat().st_size == 0:
                self.client.download_attachment(attachment, archive_path)
                self.logger.info("已下载：%s", archive_path)
            if archive_path.suffix.lower() in {".zip", ".rar", ".7z"} or zipfile.is_zipfile(archive_path):
                if extracted_dir.exists():
                    shutil.rmtree(extracted_dir)
                extracted = extract_archive(archive_path, extracted_dir, self.settings)
                media_files = iter_media_files(extracted)
                self.logger.info("已解压 %d 个文件，识别到 %d 个图片/视频。", len(extracted), len(media_files))
            else:
                category = classify_file(archive_path)
                media_files = [(archive_path, category)] if category else []

            uploaded_state = dict(source_state.get("uploaded") or {})
            new_tokens: dict[str, list[str]] = {"image": [], "video": []}
            for media_path, category in media_files:
                relative_name = str(media_path.relative_to(self.settings.download_root)) if self.settings.download_root in media_path.parents else media_path.name
                uploaded_token = str((uploaded_state.get(relative_name) or {}).get("file_token") or "").strip()
                if not uploaded_token:
                    self.logger.info("上传%s：%s", "图片" if category == "image" else "视频", media_path.name)
                    uploaded_token = self.client.upload_attachment(media_path)
                    uploaded_state[relative_name] = {
                        "file_token": uploaded_token, "category": category, "size": media_path.stat().st_size,
                    }
                    source_state["uploaded"] = uploaded_state
                    source_state["updated_at"] = int(time.time())
                    self.state.save()
                new_tokens[category].append(uploaded_token)

            written_counts: dict[str, int] = {"image": 0, "video": 0}
            limits_reached: dict[str, bool] = {"image": False, "video": False}
            output_fields = {
                "image": self.settings.image_field,
                "video": self.settings.video_field,
            }
            for category, field_name in output_fields.items():
                if not new_tokens[category]:
                    continue
                existing_tokens = attachment_tokens(fields.get(field_name))
                committed_tokens, limit_reached = self._write_attachment_field_best_effort(
                    record_id, field_name, existing_tokens, new_tokens[category],
                )
                written_counts[category] = max(0, len(committed_tokens) - len(existing_tokens))
                limits_reached[category] = limit_reached
                fields[field_name] = [{"file_token": token} for token in committed_tokens]

            is_archive = archive_path.suffix.lower() in {".zip", ".rar", ".7z"}
            if self.settings.delete_archive_after_success and is_archive and (written_counts["image"] or written_counts["video"]):
                if safe_delete_archive(archive_path, self.settings.download_root):
                    source_state["archive_deleted_at"] = int(time.time())
                    source_state["archive_path"] = str(archive_path)
                    self.logger.info("飞书回写成功，已删除本地压缩包：%s", archive_path)
            source_state.update({
                "status": "complete", "image_count": written_counts["image"],
                "video_count": written_counts["video"], "completed_at": int(time.time()),
                "updated_at": int(time.time()),
            })
            if limits_reached["image"] or limits_reached["video"]:
                source_state["attachment_limit_reached"] = True
                source_state["unwritten_image_count"] = max(0, len(new_tokens["image"]) - written_counts["image"])
                source_state["unwritten_video_count"] = max(0, len(new_tokens["video"]) - written_counts["video"])
            else:
                source_state.pop("attachment_limit_reached", None)
                source_state.pop("unwritten_image_count", None)
                source_state.pop("unwritten_video_count", None)
            source_state.pop("error", None)
            self.state.save()
            self.logger.info("处理成功：%s，写入图片 %d 个、视频 %d 个。", file_name, written_counts["image"], written_counts["video"])
        except Exception as exc:
            source_state.update({"status": "error", "error": str(exc), "updated_at": int(time.time())})
            self.state.save()
            self.logger.exception("处理失败：%s", file_name)
            raise


class SingleInstance:
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self.handle: Any = None

    def __enter__(self) -> "SingleInstance":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+b")
        if self.handle.seek(0, os.SEEK_END) == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise AutomationError("自动化处理器已经在运行。") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全球之旅素材附件自动整理与回传")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    mode.add_argument("--requeue-incomplete", action="store_true")
    mode.add_argument("--cleanup-completed", action="store_true")
    parser.add_argument("--record-id", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        settings = load_settings(args.config)
        logger = setup_logging(settings.log_file)
        automation = MaterialAutomation(settings, logger)
        if args.check:
            automation.check()
            return 0
        with SingleInstance(settings.state_file.with_suffix(".lock")):
            if args.initialize:
                automation.check()
                automation.initialize()
                return 0
            if args.requeue_incomplete:
                automation.requeue_incomplete(args.record_id)
                return 0
            if args.cleanup_completed:
                automation.cleanup_completed_archives()
                return 0
            if args.once:
                automation.run_once()
                return 0
            logger.info("自动化处理器已启动，轮询间隔 %d 秒。", settings.poll_interval_seconds)
            while True:
                try:
                    automation.run_once()
                except Exception:
                    logger.exception("本轮扫描失败，将在下一个周期重试。")
                time.sleep(settings.poll_interval_seconds)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.getLogger("global_journey_material_automation").exception("启动失败：%s", exc)
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
