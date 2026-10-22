export type CategoryDeleteScope = "material_rows" | "categories";

export function categoryDeletePreview(
  category: string,
  sourceRows: any[],
  selectedIds: string[],
  scope: CategoryDeleteScope,
) {
  if (!category) throw Error("请先选择要操作的物料品类。 / Select a category first.");
  if (scope !== "material_rows" && scope !== "categories") throw Error("无效的删除范围。 / Invalid deletion scope.");
  const ids = new Set(selectedIds);
  const records = scope === "material_rows"
    ? sourceRows.filter(row => ids.has(row.record_id))
    : sourceRows;
  if (scope === "material_rows" && (!ids.size || records.length !== ids.size)) {
    throw Error("请勾选要删除的物料行；未勾选不会删除整个品类。 / Select valid material rows; an empty selection never deletes the category.");
  }
  if (records.some(row => !row.record_id || row.category !== category)
      || new Set(records.map(row => row.record_id)).size !== records.length) {
    throw Error("物料行范围异常，请刷新本页数据后重试。 / Invalid material scope; refresh and try again.");
  }
  // Freeze exactly what was displayed. Submit must not rebuild scope from live UI state.
  const frozenRecords = structuredClone(records);
  return {
    delete_kind: scope,
    category_names: [category],
    record_ids: frozenRecords.map(row => row.record_id),
    records: frozenRecords,
    requires_explicit_confirmation: true,
    remaining_count: sourceRows.length - records.length,
  };
}
