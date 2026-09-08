from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
BASE_TOKEN = "OrBAb4nCDaOpCPspdhWcWm34nLe"
SOURCE_TABLE = "tbl40ELOL01nFo4M"
TARGET_TABLE = "tbl5QU4Tg36AGN6T"
SOURCE_LINK = "2026 Confirmed | US-Australia-UK Region"
TARGET_LINK = "2026 已确定"
REGIONS = {"美洲战区", "澳新战队", "拉美战队"}
POLL_SECONDS = 600

FIELD_MAP = {
    "开始时间 | Start": "Start",
    "结束时间 | End": "End",
    "活动名称 | Event Name": "Event Name",
    "战区 | Region": "Region",
    "地点 | Location": "Location",
    "活动属性 |  Event Type": "Event Type",
    "活动状态 | Status": "Status",
    "活动分级 | Event Tiering": "Event Tiering",
    "活动举办主体 | Event Organizer": "Event Organizer",
    "活动分类（目标受众）": "Event Category (Target Audience)",
    "活动目的": "Event Objective",
    "活动预算": "Event Budget",
    "行业 | Industry": "Industry",
    "产品线相关 | Product Line Related": "Product Line Related",
    "主展品 | Main Exhibit": "Main Exhibit",
    "副展品（仅做引流|辅助展示） | Secondary Exhibits (for Traffic Generation / Supporting Display Only)": "Secondary Exhibits (for Traffic Generation | Supporting Display Only)",
    "需要国内运输到海外机器 | Machines Requiring International Shipping from China": "Machines Requiring International Shipping from China",
    "产品发货相关": "Product Shipping Details",
    "品牌人员是否参与": "Brand Team Participation",
    "现场市场人员": "On-site Marketing Staff",
    "Pudu Owner": "Pudu Owner",
    "展位面积（若是展会）| Booth Area (if applicable)": "Booth Area (if applicable)",
    "合办展位代理名称": "Co-exhibiting Distributor Name",
    "展会信息|项目表": "Exhibition Information | Project Sheet",
    "展会复盘文档": "Exhibition Review Document",
    "其他文档": "Other Documents",
    "备注（其他 | Remarks (Other)": "Remarks (Other)",
    "周维度进展说明 | Weekly Progress Update": "Weekly Progress Update",
    "年度": "Year",
    "费控-活动名称": "Expense Control - Event Name",
}

TARGET_SELECT_FIELDS = {
    "Region", "Event Type", "Status", "Event Tiering", "Event Organizer", "Event Category (Target Audience)",
    "Industry", "Product Line Related", "Main Exhibit", "On-site Marketing Staff", "Pudu Owner", "Year",
    "Co-exhibiting Distributor Name", "Remarks (Other)", "Expense Control - Event Name",
}
TARGET_SINGLE_SELECT_FIELDS = {
    "Region", "Event Type", "Status", "Event Tiering", "Event Organizer", "Event Category (Target Audience)",
    "Year", "Co-exhibiting Distributor Name", "Remarks (Other)",
}
TARGET_TEXT_FIELDS = set(FIELD_MAP.values()) - TARGET_SELECT_FIELDS - {"Start", "End"}

FIXED = {
    "美洲战区": "Americas Region", "澳新战队": "Australia & New Zealand Region", "拉美战队": "Latin America Region",
    "展会": "Exhibition", "公司活动": "Corporate Event", "研讨会/沙龙/论坛": "Seminar / Salon / Forum", "其他": "Other", "线上活动": "Online Event",
    "已完成 Finished ": "Finished ", "待开始 - 已报名": "Not Started - Registered", "待开始 Not Started Yet": "Not Started Yet",
    "待定 TBD": "TBD", "进行中": "In Progress", "代理活动-待复盘确认": "Distributor Event - Review Pending", "取消 Cancelled": "Cancelled",
    "1级": "Tier 1", "2级": "Tier 2", "3级": "Tier 3",
    "PUDU与代理联合参加": "PUDU and Distributor Joint Participation", "PUDU参展/会": "PUDU Participation",
    "PUDU自办活动": "PUDU-Hosted Event", "代理参加": "Distributor Participation", "PUDU参加（仅参会）": "PUDU Attendance Only",
    "公众活动": "Public Event", "行业活动": "Industry Event", "渠道活动": "Channel Event", "终端活动": "End-Customer Event",
    "清洁": "Cleaning", "工业": "Industrial", "餐饮": "Food & Beverage", "零售": "Retail", "娱乐": "Entertainment",
    "酒店": "Hospitality", "泛科技": "General Technology", "医疗养老": "Healthcare & Senior Care", "仓储物流": "Warehousing & Logistics",
    "机器人": "Robotics", "地产物业保洁": "Property & Facility Cleaning", "综合性（3个及以上产品线）": "Comprehensive (3 or More Product Lines)",
    "新项目": "New Project", "新项目产品": "New Project Product", "贝拉Pro": "Bella Pro", "叉车（待定）": "Forklift (TBD)",
}


def setup_logger() -> logging.Logger:
    path = ROOT / "logs" / "event_translation_sync.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("event_translation_sync")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


class FeishuAppClient:
    def __init__(self) -> None:
        config = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
        credentials_path = Path(config["feishu"]["credentials_file"])
        credentials = tomllib.loads(credentials_path.read_text(encoding="utf-8"))
        self.app_id = str(credentials.get("FEISHU_APP_ID") or credentials.get("app_id") or "")
        self.app_secret = str(credentials.get("FEISHU_APP_SECRET") or credentials.get("app_secret") or "")
        if not self.app_id or not self.app_secret:
            raise RuntimeError("营销物料管理应用凭据缺少 App ID 或 App Secret。")
        self.session = requests.Session()
        self._token = ""
        self._expires_at = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires_at:
            return self._token
        response = self.session.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=60)
        payload = response.json()
        if response.status_code >= 400 or payload.get("code") not in (None, 0):
            raise RuntimeError(f"获取应用令牌失败：{payload.get('msg') or response.text}")
        self._token = payload["tenant_access_token"]
        self._expires_at = time.time() + int(payload.get("expire") or 7200) - 120
        return self._token

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.token()}"
        response = self.session.request(method, "https://open.feishu.cn/open-apis" + path, headers=headers, timeout=120, **kwargs)
        payload = response.json()
        if response.status_code >= 400 or payload.get("code") not in (None, 0):
            raise RuntimeError(f"飞书接口失败 {path}：{payload.get('code')} {payload.get('msg') or response.text}")
        return payload

    def list_records(self, table_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            payload = self.request("GET", f"/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records", params=params)
            data = payload.get("data") or {}
            for item in data.get("items") or []:
                records.append({"record_id": item["record_id"], **dict(item.get("fields") or {})})
            if not data.get("has_more"):
                return records
            page_token = str(data.get("page_token") or "")

    def translate(self, text: str) -> str:
        payload = self.request("POST", "/translation/v1/text/translate", json={
            "source_language": "zh", "target_language": "en", "text": text,
            "glossary": [{"from": "普渡", "to": "PUDU"}, {"from": "拉美战队", "to": "Latin America Region"}],
        })
        time.sleep(0.06)
        return str((payload.get("data") or {}).get("text") or "")

    def batch_update(self, updates: dict[str, dict[str, Any]]) -> None:
        records = [{"record_id": record_id, "fields": fields} for record_id, fields in updates.items()]
        self.request("POST", f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TARGET_TABLE}/records/batch_update", json={"records": records})

    def batch_create(self, creates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = self.request("POST", f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TARGET_TABLE}/records/batch_create", json={"records": [{"fields": fields} for fields in creates]})
        return list((payload.get("data") or {}).get("records") or [])


def selected_source(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        value = record.get("战区 | Region")
        values = {value} if isinstance(value, str) else set(value or [])
        if REGIONS.intersection(values):
            selected.append(record)
    return selected


def source_hash(record: dict[str, Any]) -> str:
    values = {name: record.get(name) for name in FIELD_MAP}
    raw = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def field_hashes(record: dict[str, Any]) -> dict[str, str]:
    return {
        name: hashlib.sha256(json.dumps(record.get(name), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        for name in FIELD_MAP
    }


def translate_fixed(value: Any) -> Any:
    if isinstance(value, list):
        return [FIXED.get(str(item), str(item)) for item in value]
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict) and "text" in value:
        return translate_fixed(value.get("text"))
    if value is None:
        return None
    return FIXED.get(str(value), str(value))


def needs_ai(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def ai_translate(client: FeishuAppClient, texts: dict[str, str]) -> dict[str, str]:
    if not texts:
        return {}
    return {key: client.translate(value) for key, value in texts.items()}


def translated_fields(client: FeishuAppClient, source: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    pending: dict[str, str] = {}
    pending_targets: dict[str, tuple[str, bool]] = {}
    for source_name, target_name in FIELD_MAP.items():
        value = translate_fixed(source.get(source_name))
        if isinstance(value, list):
            converted = []
            for index, item in enumerate(value):
                key = f"{target_name}::{index}"
                if needs_ai(item):
                    pending[key] = item
                    pending_targets[key] = (target_name, True)
                else:
                    converted.append(item)
            result[target_name] = converted
        elif isinstance(value, str) and needs_ai(value):
            pending[target_name] = value
            pending_targets[target_name] = (target_name, False)
        else:
            result[target_name] = value
    translations = ai_translate(client, pending)
    for key, translated in translations.items():
        target_name, is_list = pending_targets[key]
        if is_list:
            result.setdefault(target_name, []).append(translated)
        else:
            result[target_name] = translated
    for target_name in TARGET_SELECT_FIELDS:
        if target_name in result and result[target_name] is not None and not isinstance(result[target_name], list):
            result[target_name] = [str(result[target_name])]
    for target_name in TARGET_SINGLE_SELECT_FIELDS:
        if target_name in result and isinstance(result[target_name], list):
            result[target_name] = result[target_name][0] if result[target_name] else None
        if target_name in result and result[target_name] == "":
            result[target_name] = None
    for target_name in TARGET_TEXT_FIELDS:
        if target_name in result and isinstance(result[target_name], list):
            result[target_name] = ", ".join(str(item) for item in result[target_name])
    return result


def load_state() -> dict[str, Any]:
    path = ROOT / "state" / "event_translation_sync.json"
    if not path.exists():
        return {"version": 1, "records": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    path = ROOT / "state" / "event_translation_sync.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sync_once(initialize: bool, logger: logging.Logger) -> tuple[int, int]:
    client = FeishuAppClient()
    sources = selected_source(client.list_records(SOURCE_TABLE))
    targets = client.list_records(TARGET_TABLE)
    targets_by_source = {
        source_id: target
        for target in targets
        for link in (target.get(TARGET_LINK) or [])
        for source_id in (link.get("record_ids") or [])
    }
    state = load_state()
    changed = 0
    created = 0
    updates: dict[str, dict[str, Any]] = {}
    creates: list[dict[str, Any]] = []
    for source in sources:
        source_id = source["record_id"]
        digest = source_hash(source)
        target = targets_by_source.get(source_id)
        current_field_hashes = field_hashes(source)
        expected_region = translate_fixed(source.get("战区 | Region"))
        if initialize and target:
            if target.get("Region") != expected_region:
                updates[target["record_id"]] = {"Region": expected_region}
                changed += 1
            state["records"][source_id] = {
                "hash": digest, "field_hashes": current_field_hashes,
                "target_id": target["record_id"], "updated_at": int(time.time()),
            }
            continue
        prior = state["records"].get(source_id) or {}
        if target and prior.get("hash") == digest:
            continue
        fields = translated_fields(client, source)
        if target and prior.get("field_hashes"):
            changed_sources = {name for name, value in current_field_hashes.items() if prior["field_hashes"].get(name) != value}
            fields = {FIELD_MAP[name]: fields[FIELD_MAP[name]] for name in changed_sources}
        if target:
            updates[target["record_id"]] = fields
            changed += 1
            target_id = target["record_id"]
        else:
            fields[TARGET_LINK] = [source_id]
            creates.append(fields)
            created += 1
            target_id = "pending"
        state["records"][source_id] = {
            "hash": digest, "field_hashes": current_field_hashes,
            "target_id": target_id, "updated_at": int(time.time()),
        }
    if updates:
        client.batch_update(updates)
    if creates:
        response = client.batch_create(creates)
        logger.info("创建 %d 条英文记录。", len(response))
    save_state(state)
    logger.info("本轮扫描 %d 条目标战区记录，更新 %d 条，创建 %d 条。", len(sources), changed, created)
    return changed, created


def main() -> int:
    parser = argparse.ArgumentParser(description="全球活动英文表增量翻译同步")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    logger = setup_logger()
    try:
        if args.initialize:
            sync_once(True, logger)
            return 0
        if args.once:
            sync_once(False, logger)
            return 0
        logger.info("英文表同步任务已启动，轮询间隔 %d 秒。", POLL_SECONDS)
        while True:
            try:
                sync_once(False, logger)
            except Exception:
                logger.exception("本轮同步失败，将在下一周期重试。")
            time.sleep(POLL_SECONDS)
    except Exception as exc:
        logger.exception("任务失败：%s", exc)
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
