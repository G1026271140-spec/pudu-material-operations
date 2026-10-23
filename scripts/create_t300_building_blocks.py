"""Create the requested hidden gift category via the normal background queue.

Uploads are application-owned attachments. Business records and attachment-field
writes are checkpointed by the existing category queue handler. A fixed key and
a local upload receipt make reruns recover the same request rather than duplicate
it. No model dimension, stock ledger, or procurement price is invented here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app
from submission_queue import QUEUE_TASK_TYPE_CATEGORY_SYNC, find_task_by_idempotency_key


KEY = "category:create:building-blocks:T300:20261022"


def main() -> int:
    client = app.feishu_client()
    if client is None:
        raise RuntimeError("营销物料管理应用身份未配置。")
    existing_task = find_task_by_idempotency_key(client, KEY)
    if existing_task:
        print(json.dumps({"task_id": existing_task.task_id, "status": existing_task.status,
                          "result": existing_task.result}, ensure_ascii=False))
        return 0
    tables = {table["name"]: table["table_id"] for table in client.list_tables()}
    model_rows = client.search_records(tables[app.MODEL_TABLE_NAME], "产品型号", "T300")
    exact = [row for row in model_rows if app.feishu_text(app.feishu_fields(row), "产品型号") == "T300"]
    if len(exact) != 1:
        raise RuntimeError("必须唯一匹配现有 T300 型号，不允许创建新型号。")
    categories = client.search_records(tables[app.CATEGORY_TABLE_NAME], "物料品类", "积木")
    if categories:
        raise RuntimeError("积木品类已存在，请核对，不重复创建。")

    source = ROOT / "assets/category_models"
    receipt = ROOT / "work/t300-building-blocks-upload-receipt.json"
    uploads = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {}
    files = [(f"reference-{number}.png", "image/png") for number in range(1, 5)] + [
        ("t300-building-blocks.glb", "model/gltf-binary"),
        ("t300-building-blocks-demo.html", "text/html"),
    ]
    for filename, content_type in files:
        if filename not in uploads:
            uploads[filename] = client.upload_media(filename, (source / filename).read_bytes(), content_type)
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps(uploads, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"attachment_ready {filename}", flush=True)

    remark = (
        "T300 工业配送机器人仓储场景主题积木；参考用户提供的四张图片重建三维展示，"
        "非原始 CAD，未见背面与内部结构含推测，不能作为生产/搭建图纸。"
        "真实尺寸、颗粒数、材质、采购单价与海关编码待内部确认；初始库存为 0，"
        "物料行的 0 单价仅为系统占位，不代表免费或已核价。"
        "T300 产品背景来源：https://www.pudurobotics.com/about/news/6625d9c13383390044375e78"
    )
    sync_args = {
        "old_product": "", "new_product": "积木", "no_model": False,
        "no_language": True, "target_models": ["T300"], "target_languages": [app.NO_LANGUAGE_TEXT],
        "category_definition": app.CATEGORY_DEFINITION_GIFT,
        "category_zh_page_name": "积木", "category_en_page_name": "Building Blocks",
        "category_status": app.STATUS_ACTIVE, "category_request_visible": app.REQUEST_PAGE_HIDDEN_VALUE,
        "category_unit_price": None, "category_customs_code": "",
        "commercial_invoice_name": "T300 Robot Building Block Set", "packing_list_product_type": "Give aways",
        "target_values": {("T300", app.NO_LANGUAGE_TEXT): {
            "quantity": 0, "unit_price": 0, "customs_code": "", "remark": remark,
            "status": app.STATUS_ACTIVE, "request_visible": app.REQUEST_PAGE_HIDDEN_VALUE,
        }},
    }
    draft = {"product": "积木", "category_definition": app.CATEGORY_DEFINITION_GIFT,
             "category_status": app.STATUS_ACTIVE, "category_request_visible": app.REQUEST_PAGE_HIDDEN_VALUE,
             "commercial_invoice_name": sync_args["commercial_invoice_name"],
             "packing_list_product_type": "Give aways",
             "targets": [{"model": "T300", "language": app.NO_LANGUAGE_TEXT, "quantity": 0, "unit_price": 0}]}
    task, created = app.enqueue_feishu_background_write(
        QUEUE_TASK_TYPE_CATEGORY_SYNC,
        {"sync_args": app.serialize_category_sync_args(sync_args), "draft": draft,
         "notification_kind": "create", "category_media": {
             "file_tokens": [uploads[filename] for filename, _ in files], "remark": remark}},
        idempotency_key=KEY,
    )
    print(json.dumps({"task_id": task.task_id, "created": created, "status": task.status,
                      "existing_model_record_id": app.feishu_record_id(exact[0])}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
