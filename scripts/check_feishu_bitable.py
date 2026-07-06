from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from feishu_bitable import FeishuBitableClient, FeishuBitableConfig, FeishuBitableError

SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
OUTPUT_PATH = ROOT / "work" / "feishu_bitable_schema.json"

EXPECTED_TABLES = [
    "物料主数据",
    "物料品类",
    "库存流水",
    "物料申请单",
    "申请明细",
    "库存批量操作",
]

EXPECTED_FIELDS = {
    "物料主数据": ["物料编码", "物料品类", "产品型号", "语种", "当前库存", "备注", "单价", "海关编码"],
    "物料品类": ["物料品类", "是否无需型号"],
    "库存流水": ["发生时间", "流水类型", "物料编码", "数量", "变更前数量", "变更后数量", "备注"],
    "物料申请单": ["申请单号", "申请人", "审批状态"],
    "申请明细": ["明细编号", "所属申请单", "物料编码", "申请数量", "明细状态"],
    "库存批量操作": ["批次号", "操作类型", "批次状态"],
}


def load_config() -> FeishuBitableConfig:
    if not SECRETS_PATH.exists():
        raise SystemExit(f"Missing secrets file: {SECRETS_PATH}")
    secrets = tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    values = {
        "app_id": str(secrets.get("FEISHU_APP_ID", "")).strip(),
        "app_secret": str(secrets.get("FEISHU_APP_SECRET", "")).strip(),
        "app_token": str(secrets.get("FEISHU_BITABLE_APP_TOKEN", "")).strip(),
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise SystemExit("Missing Feishu secrets: " + ", ".join(missing))
    return FeishuBitableConfig(**values)


def main() -> int:
    client = FeishuBitableClient(load_config())
    try:
        schema = client.discover_schema()
    except FeishuBitableError as exc:
        print(f"ERROR: {exc}")
        return 1

    tables = schema["tables"]
    print("Feishu connection: OK")
    print(f"Tables found: {len(tables)}")

    failed = False
    for table_name in EXPECTED_TABLES:
        table = tables.get(table_name)
        if not table:
            print(f"MISSING TABLE: {table_name}")
            failed = True
            continue
        fields = table["fields"]
        print(f"TABLE OK: {table_name} ({table['table_id']}) fields={len(fields)}")
        for field_name in EXPECTED_FIELDS.get(table_name, []):
            if field_name not in fields:
                print(f"  MISSING FIELD: {field_name}")
                failed = True

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Schema cache written: {OUTPUT_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
