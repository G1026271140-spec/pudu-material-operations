import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


REPORT_DIR = ROOT / "work"


class SmokeTest:
    def __init__(self) -> None:
        self.client = app.feishu_client()
        if self.client is None:
            raise RuntimeError("Feishu client is not configured.")
        self.run_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self.prefix = f"DEBUG-SMOKE-{self.run_id}"
        self.results: list[dict[str, object]] = []
        self.cleanup_records: dict[str, set[str]] = {
            "物料申请单": set(),
            "申请明细": set(),
            "库存流水": set(),
            "物料主数据": set(),
            "物料品类": set(),
        }
        self.restore_stock_ids: set[str] = set()

    def log(self, name: str, ok: bool, detail: str = "") -> None:
        item = {"name": name, "ok": ok, "detail": detail}
        self.results.append(item)
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    def table_id(self, table_name: str) -> str:
        return app.feishu_table_id(table_name)

    def delete_record(self, table_name: str, record_id: str) -> None:
        if record_id:
            self.client.delete_record(self.table_id(table_name), record_id)

    def set_stock_1000(self, material_record_id: str) -> None:
        if material_record_id:
            self.client.update_record(self.table_id("物料主数据"), material_record_id, {"当前库存": 1000})

    def clear_cache(self) -> None:
        app.st.cache_data.clear()

    def live_fields(self, table_name: str) -> dict[str, dict]:
        fields = self.client.list_fields(self.table_id(table_name))
        return {str(field.get("field_name")): field for field in fields}

    def pick_materials(self, count: int) -> list[dict[str, object]]:
        materials: list[dict[str, object]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in app.feishu_material_rows():
            fields = app.feishu_fields(row)
            product = app.feishu_text(fields, "物料品类")
            model = app.feishu_text(fields, "产品型号") or app.NO_MODEL_TEXT
            language = app.feishu_text(fields, "语种")
            key = (product, model, language)
            if product and language and key not in seen:
                materials.append(
                    {
                        "record_id": app.feishu_record_id(row),
                        "product": product,
                        "model": model,
                        "language": language,
                    }
                )
                seen.add(key)
            if len(materials) >= count:
                break
        if len(materials) < count:
            raise RuntimeError(f"Only found {len(materials)} materials, need {count}.")
        return materials

    def find_request(self, request_no: str) -> dict | None:
        for row in app.feishu_rows(app.REQUEST_TABLE_NAME):
            if app.feishu_text(app.feishu_fields(row), "申请单号") == request_no:
                return row
        return None

    def cleanup_debug_records(self) -> None:
        # Delete linked children before parents.
        for table_name in ["库存流水", "申请明细", "物料主数据", "物料品类", "物料申请单"]:
            table_id = self.table_id(table_name)
            for record_id in list(self.cleanup_records.get(table_name, set())):
                try:
                    self.client.delete_record(table_id, record_id)
                except Exception as exc:
                    print(f"[WARN] cleanup failed {table_name} {record_id}: {exc}")
                finally:
                    self.cleanup_records[table_name].discard(record_id)
        for record_id in list(self.restore_stock_ids):
            try:
                self.set_stock_1000(record_id)
            except Exception as exc:
                print(f"[WARN] stock restore failed {record_id}: {exc}")

    def collect_debug_records(self) -> None:
        for table_name in ["物料申请单", "申请明细", "库存流水", "物料主数据", "物料品类"]:
            for row in self.client.list_records(self.table_id(table_name)):
                fields = app.feishu_fields(row)
                should_cleanup = False
                if table_name == "物料申请单":
                    should_cleanup = self.prefix in app.feishu_text(fields, "申请单号")
                elif table_name == "申请明细":
                    should_cleanup = self.prefix in app.feishu_text(fields, "明细编号") or self.prefix in app.feishu_text(fields, "备注")
                elif table_name == "库存流水":
                    should_cleanup = self.prefix in app.feishu_text(fields, "备注") or self.prefix in app.feishu_text(fields, "幂等键")
                elif table_name == "物料主数据":
                    should_cleanup = (
                        app.feishu_text(fields, "物料编码").startswith(f"SMOKE-{self.run_id}")
                        or app.feishu_text(fields, "物料品类").startswith(self.prefix)
                    )
                elif table_name == "物料品类":
                    should_cleanup = app.feishu_text(fields, "物料品类").startswith(self.prefix)
                if should_cleanup:
                    self.cleanup_records.setdefault(table_name, set()).add(app.feishu_record_id(row))

    def test_schema_links(self) -> None:
        line_fields = self.live_fields(app.REQUEST_LINE_TABLE_NAME)
        request_fields = self.live_fields(app.REQUEST_TABLE_NAME)
        ledger_fields = self.live_fields("库存流水")
        checks = [
            (line_fields["所属申请单"]["type"] == 21, "申请明细.所属申请单 is link"),
            (line_fields["所属申请单"].get("property", {}).get("table_name") == app.REQUEST_TABLE_NAME, "申请明细.所属申请单 links request table"),
            (line_fields["物料编码"]["type"] == 21, "申请明细.物料编码 is link"),
            (line_fields["物料编码"].get("property", {}).get("table_name") == "物料主数据", "申请明细.物料编码 links material table"),
            (line_fields["备注"]["type"] == 1, "申请明细.备注 is text"),
            (request_fields["物料用途"]["type"] == 1, "物料申请单.物料用途 is text"),
            (ledger_fields["物料编码"]["type"] == 21, "库存流水.物料编码 is link"),
            (ledger_fields["物料编码"].get("property", {}).get("table_name") == "物料主数据", "库存流水.物料编码 links material table"),
        ]
        failed = [detail for ok, detail in checks if not ok]
        self.log("字段与关联关系检查", not failed, "; ".join(failed))

    def test_inventory_and_options(self) -> None:
        inventory = app.load_feishu_inventory()
        self.log("实时库存读取", not inventory.empty, f"rows={len(inventory)}")
        not_1000 = int((inventory[app.QTY_COL] != 1000).sum())
        self.log("库存统一为1000校验", not_1000 == 0, f"not_1000={not_1000}")
        options = app.load_feishu_options()
        self.log(
            "登记页选项读取",
            bool(options.get("products")) and bool(options.get("languages")),
            f"products={len(options.get('products') or [])}, languages={len(options.get('languages') or [])}",
        )
        context = app.build_inventory_selection_context()
        no_model_products = list(options.get("no_model_products") or [])
        if no_model_products:
            product = no_model_products[0]
            is_no_model, models = app.product_model_state(product, context)
            self.log("无需型号品类逻辑", is_no_model and not models, product)
        else:
            self.log("无需型号品类逻辑", True, "no configured no-model products")

    def test_stock_transaction_and_revert(self) -> None:
        material = self.pick_materials(1)[0]
        self.restore_stock_ids.add(str(material["record_id"]))
        self.set_stock_1000(str(material["record_id"]))
        self.clear_cache()
        note = f"{self.prefix}-STOCK"
        app.apply_feishu_changes(
            [
                {
                    "action": app.ACTION_PURCHASE,
                    "product": material["product"],
                    "model": material["model"],
                    "language": material["language"],
                    "quantity": 5,
                    "note": note,
                }
            ]
        )
        self.clear_cache()
        row = app.find_feishu_material_by_id(str(material["record_id"]))
        after_add = app.feishu_int(app.feishu_fields(row or {}), "当前库存")
        self.log("库存登记增加库存", after_add == 1005, f"after={after_add}")
        tx = next(
            (
                item
                for item in app.feishu_rows("库存流水")
                if note in app.feishu_text(app.feishu_fields(item), "备注")
            ),
            None,
        )
        self.log("库存流水写入", tx is not None, note)
        tx_id = app.feishu_record_id(tx or {})
        if tx_id:
            self.cleanup_records["库存流水"].add(tx_id)
            app.revert_feishu_transaction(tx_id, f"{self.prefix}-REVERT")
        self.clear_cache()
        row = app.find_feishu_material_by_id(str(material["record_id"]))
        after_revert = app.feishu_int(app.feishu_fields(row or {}), "当前库存")
        self.log("流水撤回恢复库存", after_revert == 1000, f"after={after_revert}")
        self.collect_debug_records()

    def test_request_and_approval(self) -> None:
        materials = self.pick_materials(10)
        for material in materials:
            self.restore_stock_ids.add(str(material["record_id"]))
            self.set_stock_1000(str(material["record_id"]))
        self.clear_cache()
        request_no = f"{self.prefix}-REQ"
        original_next = app.next_request_no
        app.next_request_no = lambda: request_no
        try:
            payload = {
                "title": app.REQUEST_FORM_TITLE,
                "department": "DEBUG-DEPT",
                "requester": "DEBUG-USER",
                "position": "DEBUG-POSITION",
                "customer_name": "DEBUG-CUSTOMER",
                "country": "DEBUG-COUNTRY",
                "recipient_info": "DEBUG-RECIPIENT",
                "freight_payer": "DEBUG-PAYER",
                "material_usage": f"{self.prefix}-USAGE",
                "attachment_note": "",
            }
            lines = [
                {
                    "product": material["product"],
                    "model": material["model"],
                    "language": material["language"],
                    "quantity": 2,
                    "remark": f"{self.prefix}-LINE-{index:02d}",
                }
                for index, material in enumerate(materials, 1)
            ]
            created_no, line_count = app.submit_feishu_material_request(payload, lines)
        finally:
            app.next_request_no = original_next
        self.clear_cache()
        self.log("申请单提交10条明细", created_no == request_no and line_count == 10, f"{created_no}, lines={line_count}")
        request_row = self.find_request(request_no)
        request_id = app.feishu_record_id(request_row or {})
        self.log("申请单记录创建", bool(request_id), request_no)
        self.cleanup_records["物料申请单"].add(request_id)
        request_records = app.load_feishu_request_records()
        request = next(item for item in request_records if item["request_no"] == request_no)
        line_records = [
            line
            for line in app.load_feishu_request_line_records()
            if request_id in [str(item) for item in line.get("request_ids", [])]
        ]
        self.log("申请明细关联申请单", len(line_records) == 10, f"lines={len(line_records)}")
        for line in line_records:
            self.cleanup_records["申请明细"].add(str(line["record_id"]))
        issue_lines = []
        for line in line_records:
            next_line = dict(line)
            next_line["previous_actual_issue_qty"] = int(line.get("actual_issue_qty") or 0)
            next_line["actual_issue_qty"] = 1
            issue_lines.append(next_line)
        logs = app.issue_request_lines(request, issue_lines, f"{self.prefix}-APPROVAL")
        self.clear_cache()
        self.log("审批发放扣库存", len(logs) == 10, f"logs={len(logs)}")
        for material in materials:
            row = app.find_feishu_material_by_id(str(material["record_id"]))
            qty = app.feishu_int(app.feishu_fields(row or {}), "当前库存")
            if qty != 999:
                self.log("审批后库存校验", False, f"{material['record_id']}={qty}")
        self.log("审批后库存校验", True, "10 materials at 999")
        self.collect_debug_records()

    def test_category_and_material_admin(self) -> None:
        product = f"{self.prefix}-CATEGORY"
        renamed_product = f"{self.prefix}-CATEGORY-RENAMED"
        df = pd.DataFrame(
            [
                [
                    f"SMOKE-{self.run_id}-001",
                    product,
                    "SMOKE-MODEL",
                    "SMOKE-LANG",
                    0,
                    0,
                    0,
                    "",
                ]
            ],
            columns=app.INVENTORY_HEADERS,
        )
        inserted = app.add_feishu_material_category_payload(product, False, False, df)
        self.clear_cache()
        self.log("新增物料品类", inserted == 1, f"inserted={inserted}")
        category = app.find_feishu_category_record(product)
        self.log("品类记录创建", category is not None, product)
        category_id = app.feishu_record_id(category or {})
        self.cleanup_records["物料品类"].add(category_id)
        material = app.find_feishu_material_record(product, "SMOKE-MODEL", "SMOKE-LANG")
        material_id = app.feishu_record_id(material or {})
        self.log("新增品类生成库存行", bool(material_id), material_id)
        self.cleanup_records["物料主数据"].add(material_id)
        app.update_feishu_inventory_item(
            material_id,
            f"SMOKE-{self.run_id}-UPDATED",
            product,
            "SMOKE-MODEL",
            "SMOKE-LANG",
            1.23,
            f"{self.prefix}-MATERIAL-REMARK",
            "SMOKE-CUSTOMS",
        )
        self.clear_cache()
        updated = app.find_feishu_material_by_id(material_id)
        updated_fields = app.feishu_fields(updated or {})
        self.log(
            "库存行编辑",
            app.feishu_text(updated_fields, "物料编码").endswith("UPDATED")
            and app.feishu_text(updated_fields, "备注") == f"{self.prefix}-MATERIAL-REMARK",
            material_id,
        )
        app.update_feishu_category(product, renamed_product, False, False, category_id)
        self.clear_cache()
        renamed = app.find_feishu_category_record(renamed_product)
        self.log("物料品类编辑", renamed is not None, renamed_product)
        material_after_rename = app.find_feishu_material_record(renamed_product, "SMOKE-MODEL", "SMOKE-LANG")
        self.log("品类编辑同步库存行", material_after_rename is not None, renamed_product)
        app.delete_feishu_category(renamed_product, category_id)
        self.cleanup_records["物料品类"].discard(category_id)
        self.cleanup_records["物料主数据"].discard(material_id)
        self.clear_cache()
        self.log("物料品类撤回", app.find_feishu_category_record(renamed_product) is None, renamed_product)

    def test_no_model_created_category(self) -> None:
        product = f"{self.prefix}-NO-MODEL"
        df = pd.DataFrame(
            [
                [f"SMOKE-{self.run_id}-NM1", product, app.NO_MODEL_TEXT, "SMOKE-LANG-A", 0, 0, 0, ""],
                [f"SMOKE-{self.run_id}-NM2", product, app.NO_MODEL_TEXT, "SMOKE-LANG-B", 0, 0, 0, ""],
            ],
            columns=app.INVENTORY_HEADERS,
        )
        inserted = app.add_feishu_material_category_payload(product, True, False, df)
        self.clear_cache()
        category = app.find_feishu_category_record(product)
        category_id = app.feishu_record_id(category or {})
        self.cleanup_records["物料品类"].add(category_id)
        no_model_material_ids: set[str] = set()
        for row in app.feishu_material_rows():
            if app.feishu_text(app.feishu_fields(row), "物料品类") == product:
                material_id = app.feishu_record_id(row)
                no_model_material_ids.add(material_id)
                self.cleanup_records["物料主数据"].add(material_id)
        context = app.build_inventory_selection_context()
        is_no_model, models = app.product_model_state(product, context)
        languages = app.product_language_options(product, app.NO_MODEL_TEXT, context)
        self.log(
            "新增无需型号品类显示逻辑",
            inserted == 2 and is_no_model and not models and {"SMOKE-LANG-A", "SMOKE-LANG-B"}.issubset(set(languages)),
            f"inserted={inserted}, is_no_model={is_no_model}, models={models}, languages={languages}",
        )
        app.delete_feishu_category(product, category_id)
        self.cleanup_records["物料品类"].discard(category_id)
        for material_id in no_model_material_ids:
            self.cleanup_records["物料主数据"].discard(material_id)
        self.clear_cache()

    def run(self) -> int:
        failed = False
        try:
            self.test_schema_links()
            self.test_inventory_and_options()
            self.test_stock_transaction_and_revert()
            self.test_request_and_approval()
            self.test_category_and_material_admin()
            self.test_no_model_created_category()
        except Exception as exc:
            failed = True
            self.results.append({"name": "exception", "ok": False, "detail": repr(exc)})
            print(f"[FAIL] exception - {exc!r}")
        finally:
            self.collect_debug_records()
            self.cleanup_debug_records()
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            report_path = REPORT_DIR / f"full_feishu_smoke_test_{self.run_id}.json"
            report_path.write_text(json.dumps(self.results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"report={report_path}")
        return 1 if failed or any(not item["ok"] for item in self.results) else 0


if __name__ == "__main__":
    sys.exit(SmokeTest().run())
