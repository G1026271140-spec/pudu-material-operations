import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import { transformWithOxc } from "vite";

const source = await fs.readFile(new URL("../src/categoryDeletion.ts", import.meta.url), "utf8");
const { code } = await transformWithOxc(source, "categoryDeletion.ts");
const { categoryDeletePreview } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const rows = [
  { record_id: "row-1", category: "公仔", model: "BG1", quantity: 0 },
  { record_id: "row-2", category: "公仔", model: "BellaBot", quantity: 561 },
  { record_id: "row-3", category: "公仔", model: "KettyBot Pro", quantity: 242 },
];

test("empty/stale selection never becomes an entire category deletion", () => {
  for (const ids of [[], ["missing"], ["row-1", "missing"]]) {
    assert.throws(() => categoryDeletePreview("公仔", rows, ids, "material_rows"));
  }
});
test("preview contains exactly the selected rows and freezes their values", () => {
  const input = structuredClone(rows);
  const preview = categoryDeletePreview("公仔", input, ["row-1"], "material_rows");
  assert.equal(preview.delete_kind, "material_rows");
  assert.deepEqual(preview.record_ids, ["row-1"]);
  assert.equal(preview.remaining_count, 2);
  input[0].quantity = 100;
  input.splice(0, 1);
  assert.equal(preview.records[0].quantity, 0);
});
test("selecting all rows still keeps the category", () => {
  const preview = categoryDeletePreview("公仔", rows, rows.map(x => x.record_id), "material_rows");
  assert.equal(preview.delete_kind, "material_rows");
  assert.equal(preview.remaining_count, 0);
});
test("whole-category deletion must explicitly select its separate scope", () => {
  const preview = categoryDeletePreview("公仔", rows, [], "categories");
  assert.equal(preview.delete_kind, "categories");
  assert.equal(preview.records.length, 3);
  assert.equal(preview.requires_explicit_confirmation, true);
});
test("invalid category, duplicate rows, and unknown scope are rejected", () => {
  assert.throws(() => categoryDeletePreview("其他品类", rows, ["row-1"], "material_rows"));
  assert.throws(() => categoryDeletePreview("公仔", [rows[0], rows[0]], [], "categories"));
  assert.throws(() => categoryDeletePreview("公仔", rows, [], ""));
});
