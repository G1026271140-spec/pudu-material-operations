from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .models import CloudflareMode, DeploymentConfig, DeploymentMode


MAGIC = "PUDU-MATERIAL-MIGRATION-1"
ITERATIONS = 600_000


def _derive_key(password: str, salt: bytes) -> bytes:
    if len(password) < 10:
        raise ValueError("迁移包密码至少需要 10 个字符。")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode("utf-8"))


def export_bundle(path: Path, config: DeploymentConfig, password: str) -> None:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    payload = {
        "schema": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "config": asdict(config),
    }
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_derive_key(password, salt)).encrypt(nonce, plaintext, MAGIC.encode("ascii"))
    envelope = {
        "format": MAGIC,
        "kdf": {"name": "PBKDF2-SHA256", "iterations": ITERATIONS, "salt": base64.b64encode(salt).decode("ascii")},
        "cipher": {"name": "AES-256-GCM", "nonce": base64.b64encode(nonce).decode("ascii")},
        "payload": base64.b64encode(ciphertext).decode("ascii"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_bundle(path: Path, password: str) -> DeploymentConfig:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("format") != MAGIC:
            raise ValueError("文件不是受支持的 PUDU 迁移包。")
        salt = base64.b64decode(envelope["kdf"]["salt"])
        nonce = base64.b64decode(envelope["cipher"]["nonce"])
        ciphertext = base64.b64decode(envelope["payload"])
        raw = AESGCM(_derive_key(password, salt)).decrypt(nonce, ciphertext, MAGIC.encode("ascii"))
    except InvalidTag as exc:
        raise ValueError("迁移包密码错误，或文件已被修改。") from exc
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(("迁移包", "文件不是", "迁移包密码")):
            raise
        raise ValueError("迁移包格式损坏或不完整。") from exc
    data = json.loads(raw.decode("utf-8"))["config"]
    data["mode"] = DeploymentMode(data.get("mode", DeploymentMode.TAKEOVER))
    data["cloudflare_mode"] = CloudflareMode(data.get("cloudflare_mode", CloudflareMode.MANUAL))
    return DeploymentConfig(**data)
