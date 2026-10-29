// Draft operations preserve total quantities when two selections converge.
export type AllocationMaterial = { record_id: string; category: string; model: string; language: string; category_definition?: string; quantity?: number };
type Row = { material_record_id: string; quantity: number; remark?: string; order_required?: boolean; split_source_line_id?: string; split_source_line_ids?: string[]; [key: string]: unknown };

export function chooseAllocationMaterial(materials: AllocationMaterial[], row: Pick<AllocationMaterial, "category" | "model" | "language">, key: "category" | "model" | "language", value: string) {
  const next = { ...row, [key]: value };
  const candidates = materials.filter(item => item.category === next.category &&
    (key === "category" || item.model === next.model) && (key !== "language" || item.language === value));
  return candidates.find(item => item.model === next.model && item.language === next.language)
    || candidates.find(item => item.language === next.language) || candidates[0];
}

export function nextAllocationMaterial(materials: AllocationMaterial[], rows: Row[]) {
  const used = new Set(rows.map(row => row.material_record_id));
  return materials.find(material => !used.has(material.record_id));
}

export function mergeAllocationRows<T extends Row>(rows: T[]): T[] {
  const result: T[] = [], byId = new Map<string, T>();
  for (const row of rows) {
    if (!row.material_record_id || !Number.isSafeInteger(Number(row.quantity)) || Number(row.quantity) < 1)
      throw Error('配货方案中存在无效物料或数量 / Invalid material or quantity');
    const old = byId.get(row.material_record_id);
    if (!old) { const copy = { ...row }; result.push(copy); byId.set(row.material_record_id, copy); continue; }
    const quantity = Number(old.quantity) + Number(row.quantity);
    if (!Number.isSafeInteger(quantity)) throw Error('配货数量超出范围 / Quantity out of range');
    old.quantity = quantity;
    old.remark = [...new Set([old.remark, row.remark].map(value => String(value || '').trim()).filter(Boolean))].join('；');
    old.order_required = old.order_required === true || row.order_required === true;
    old.split_source_line_ids = [...new Set([...(old.split_source_line_ids || []), ...(row.split_source_line_ids || []), old.split_source_line_id, row.split_source_line_id].filter((value): value is string => Boolean(value)))];
    if (!old.split_source_line_id && row.split_source_line_id) old.split_source_line_id = row.split_source_line_id;
  }
  return result;
}
