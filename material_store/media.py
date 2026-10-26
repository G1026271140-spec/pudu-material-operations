"""Durable local category images; upload to Feishu is deferred to the Worker."""
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError

from .db import connection

MAX_IMAGE_BYTES = 6 * 1024 * 1024
IMAGE_TYPES = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}


def root() -> Path:
    value = os.environ.get("PUDU_MEDIA_ROOT")
    if not value:
        raise RuntimeError("本地图片存储目录尚未配置。")
    return Path(value).resolve()


def validate_image(content: bytes):
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("品类图片大小须为 1 字节至 6 MB。")
    try:
        with Image.open(BytesIO(content)) as img:
            kind = img.format
            if kind not in IMAGE_TYPES or img.width * img.height > 24_000_000:
                raise ValueError("请选择不超过 2400 万像素的 PNG、JPEG 或 WebP 图片。")
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片文件无法读取。") from exc
    return IMAGE_TYPES[kind]


def save_image(content: bytes, filename: str, actor: str) -> dict:
    mime_type, suffix = validate_image(content)
    media_id = uuid4()
    directory = root()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (str(media_id) + suffix)
    # The user-supplied name is metadata only and never part of a filesystem path.
    label = filename.replace("\\", "/").rsplit("/", 1)[-1][:200] or "category" + suffix
    with path.open("xb") as target:
        target.write(content)
    path.chmod(0o600)
    try:
        with connection() as conn:
            conn.execute("""INSERT INTO material_ops.media
                (id,sha256,mime_type,filename,byte_size,storage_path,owner_open_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (media_id, sha256(content).hexdigest(), mime_type, label, len(content), path.name, actor))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"local_media_id": str(media_id), "name": label, "type": mime_type,
            "size": len(content), "path": "/api/admin/category-images/" + str(media_id)}


def load_image(media_id: str, *, conn=None) -> dict:
    identity = UUID(media_id)
    if conn is None:
        with connection() as opened:
            return load_image(media_id, conn=opened)
    else:
        row = conn.execute("""SELECT storage_path,mime_type,filename,feishu_file_token,sha256
            FROM material_ops.media WHERE id=%s""", (identity,)).fetchone()
    if not row:
        raise ValueError("本地图片不存在，请重新上传。")
    path = (root() / row[0]).resolve()
    if path.parent != root() or not path.is_file():
        raise ValueError("本地图片文件不存在。")
    return {"path": path, "type": row[1], "name": row[2], "file_token": row[3], "sha256": row[4]}


def remote_token(media_id: str, client) -> str:
    # A transaction-scoped advisory lock avoids duplicate uploads when retries overlap.
    identity = UUID(media_id)
    with connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("media:" + str(identity),))
        image = load_image(str(identity), conn=conn)
        if image["file_token"]:
            return image["file_token"]
        content = image["path"].read_bytes()
        if sha256(content).hexdigest() != image["sha256"]:
            raise ValueError("本地图片校验失败。")
        token = client.upload_media(image["name"], content, image["type"])
        conn.execute("UPDATE material_ops.media SET feishu_file_token=%s WHERE id=%s", (token, identity))
        return token
