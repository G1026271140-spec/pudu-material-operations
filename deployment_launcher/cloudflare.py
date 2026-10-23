from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .models import DeploymentConfig


API_ROOT = "https://api.cloudflare.com/client/v4"


class CloudflareError(RuntimeError):
    pass


@dataclass(slots=True)
class CloudflareResult:
    tunnel_id: str
    tunnel_token: str
    dns_record_id: str
    created_tunnel: bool
    created_dns_record: bool


class CloudflareClient:
    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self.token = token.strip()
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict[str, object] | None = None) -> object:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            API_ROOT + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CloudflareError(f"Cloudflare API 返回 HTTP {exc.code}: {detail[:800]}") from exc
        except urllib.error.URLError as exc:
            raise CloudflareError(f"无法连接 Cloudflare API: {exc.reason}") from exc
        if not payload.get("success"):
            messages = "; ".join(str(item.get("message", item)) for item in payload.get("errors", []))
            raise CloudflareError(messages or "Cloudflare API 请求失败。")
        return payload.get("result")

    def verify_zone(self, zone_id: str) -> dict[str, object]:
        result = self.request("GET", f"/zones/{zone_id}")
        if not isinstance(result, dict):
            raise CloudflareError("Cloudflare Zone 返回格式异常。")
        return result

    def list_tunnels(self, account_id: str, name: str) -> list[dict[str, object]]:
        query = urllib.parse.urlencode({"name": name, "is_deleted": "false"})
        result = self.request("GET", f"/accounts/{account_id}/cfd_tunnel?{query}")
        return result if isinstance(result, list) else []

    def create_tunnel(self, account_id: str, name: str) -> dict[str, object]:
        return self.request("POST", f"/accounts/{account_id}/cfd_tunnel", {"name": name, "config_src": "cloudflare"})  # type: ignore[return-value]

    def get_tunnel_token(self, account_id: str, tunnel_id: str) -> str:
        result = self.request("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token")
        if not isinstance(result, str) or not result:
            raise CloudflareError("Cloudflare 未返回 Tunnel 运行 Token。")
        return result

    def configure_tunnel(self, account_id: str, tunnel_id: str, hostname: str, port: int) -> None:
        self.request(
            "PUT",
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            {"config": {"ingress": [{"hostname": hostname, "service": f"http://127.0.0.1:{port}"}, {"service": "http_status:404"}]}},
        )

    def list_dns(self, zone_id: str, hostname: str) -> list[dict[str, object]]:
        query = urllib.parse.urlencode({"type": "CNAME", "name": hostname})
        result = self.request("GET", f"/zones/{zone_id}/dns_records?{query}")
        return result if isinstance(result, list) else []

    def create_dns(self, zone_id: str, hostname: str, tunnel_id: str) -> dict[str, object]:
        return self.request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            {"type": "CNAME", "name": hostname, "content": f"{tunnel_id}.cfargotunnel.com", "proxied": True, "ttl": 1, "comment": "Managed by PUDU deployment launcher"},
        )  # type: ignore[return-value]

    def delete_dns(self, zone_id: str, record_id: str) -> None:
        self.request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")

    def delete_tunnel(self, account_id: str, tunnel_id: str) -> None:
        self.request("DELETE", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}")


def configure_cloudflare(config: DeploymentConfig, *, client: CloudflareClient | None = None) -> CloudflareResult:
    client = client or CloudflareClient(config.cloudflare_api_token)
    zone = client.verify_zone(config.cloudflare_zone_id)
    zone_name = str(zone.get("name", "")).lower()
    if config.hostname != zone_name and not config.hostname.endswith("." + zone_name):
        raise CloudflareError(f"域名 {config.hostname} 不属于所选 Zone {zone_name}。")
    tunnels = client.list_tunnels(config.cloudflare_account_id, config.cloudflare_tunnel_name)
    created_tunnel = False
    created_dns = False
    tunnel_id = ""
    dns_id = ""
    try:
        if tunnels:
            tunnel_id = str(tunnels[0].get("id", ""))
        else:
            tunnel = client.create_tunnel(config.cloudflare_account_id, config.cloudflare_tunnel_name)
            tunnel_id = str(tunnel.get("id", ""))
            created_tunnel = True
        if not tunnel_id:
            raise CloudflareError("无法确定 Cloudflare Tunnel ID。")
        client.configure_tunnel(config.cloudflare_account_id, tunnel_id, config.hostname, config.port)
        token = client.get_tunnel_token(config.cloudflare_account_id, tunnel_id)
        records = client.list_dns(config.cloudflare_zone_id, config.hostname)
        if records:
            record = records[0]
            dns_id = str(record.get("id", ""))
            expected = f"{tunnel_id}.cfargotunnel.com"
            if str(record.get("content", "")).lower() != expected.lower():
                raise CloudflareError(f"域名已有其他 CNAME 记录，当前指向 {record.get('content')}。启动器不会自动覆盖。")
        else:
            record = client.create_dns(config.cloudflare_zone_id, config.hostname, tunnel_id)
            dns_id = str(record.get("id", ""))
            created_dns = True
        return CloudflareResult(tunnel_id, token, dns_id, created_tunnel, created_dns)
    except Exception:
        if created_dns and dns_id:
            try:
                client.delete_dns(config.cloudflare_zone_id, dns_id)
            except Exception:
                pass
        if created_tunnel and tunnel_id:
            try:
                client.delete_tunnel(config.cloudflare_account_id, tunnel_id)
            except Exception:
                pass
        raise


def manual_instructions(config: DeploymentConfig) -> list[str]:
    return [
        f"在 Cloudflare Zero Trust 中创建或选择 Tunnel：{config.cloudflare_tunnel_name}",
        f"将 Public Hostname 设置为 {config.hostname}",
        f"Service 设置为 http://127.0.0.1:{config.port}",
        f"在 DNS 中确认 CNAME 指向 <Tunnel-ID>.cfargotunnel.com，并启用代理。",
        "复制 Tunnel 运行 Token 回到启动器。启动器会启动本地服务并验证公网健康接口。",
    ]
