from __future__ import annotations

import ipaddress
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse


DOMAIN_NOTICE = (
    "该域名必须归当前部署者所有，并已接入对应的 Cloudflare 账号。"
    "选择自动配置时，需要提供仅包含 Tunnel 与 DNS 编辑权限的 Cloudflare API Token；"
    "选择手动配置时，启动器会提供配置内容并负责验证。"
)


class DeploymentMode(StrEnum):
    TAKEOVER = "takeover"
    STANDBY = "standby"


class CloudflareMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


def normalize_hostname(value: str) -> str:
    text = value.strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    hostname = (parsed.hostname or "").strip(".").lower()
    if not hostname:
        raise ValueError("请填写公网域名。")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("公网入口必须使用域名，不能填写 IP 地址。")
    if len(hostname) > 253 or not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", hostname):
        raise ValueError("公网域名格式不正确。")
    return hostname


@dataclass(slots=True)
class DeploymentConfig:
    mode: DeploymentMode = DeploymentMode.TAKEOVER
    install_root: str = str(Path.home() / "PuduMaterialOperations")
    source: str = "manual"
    repository: str = "G1026271140-spec/pudu-material-inventory"
    branch: str = "master"
    hostname: str = "pudu-material-operations.gaohongyuan.me"
    port: int = 8501
    cloudflare_mode: CloudflareMode = CloudflareMode.MANUAL
    domain_ownership_confirmed: bool = False
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    cloudflare_zone_id: str = ""
    cloudflare_tunnel_name: str = "pudu-material-operations"
    cloudflare_tunnel_token: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_bitable_app_token: str = ""
    feishu_bitable_web_url: str = ""
    approval_writeback_app_id: str = ""
    approval_writeback_app_secret: str = ""
    github_token: str = ""
    inventory_password: str = ""
    approval_password: str = ""
    extra_secrets: dict[str, object] = field(default_factory=dict)

    @property
    def public_url(self) -> str:
        return f"https://{normalize_hostname(self.hostname)}"

    def validate(self) -> None:
        self.hostname = normalize_hostname(self.hostname)
        root = Path(self.install_root).expanduser()
        if not root.is_absolute():
            raise ValueError("安装目录必须是绝对路径。")
        if not 1024 <= int(self.port) <= 65535:
            raise ValueError("本地端口必须在 1024 到 65535 之间。")
        if not self.domain_ownership_confirmed:
            raise ValueError("请确认域名归当前部署者所有并已接入对应 Cloudflare 账号。")
        if self.cloudflare_mode == CloudflareMode.AUTOMATIC:
            missing = [
                label
                for value, label in (
                    (self.cloudflare_api_token, "Cloudflare API Token"),
                    (self.cloudflare_account_id, "Cloudflare Account ID"),
                    (self.cloudflare_zone_id, "Cloudflare Zone ID"),
                    (self.cloudflare_tunnel_name, "Tunnel 名称"),
                )
                if not str(value).strip()
            ]
            if missing:
                raise ValueError("自动配置缺少：" + "、".join(missing))
        elif not self.cloudflare_tunnel_token.strip():
            raise ValueError("手动配置需要填写已创建 Tunnel 的运行 Token。")
        required = {
            "飞书 App ID": self.feishu_app_id,
            "飞书 App Secret": self.feishu_app_secret,
            "飞书多维表格 App Token": self.feishu_bitable_app_token,
        }
        missing = [label for label, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError("业务配置缺少：" + "、".join(missing))

    def safe_dict(self) -> dict[str, object]:
        data = asdict(self)
        for key in list(data):
            if any(term in key for term in ("token", "secret", "password")):
                data[key] = "***" if data[key] else ""
        data["extra_secrets"] = {key: "***" for key in self.extra_secrets}
        return data
