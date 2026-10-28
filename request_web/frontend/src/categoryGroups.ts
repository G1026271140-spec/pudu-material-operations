export type CategoryGroup<T> = { category: string; entries: { item: T; index: number }[]; quantity: number };

export function groupByCategory<T>(items: readonly T[], category: (item: T) => string, quantity: (item: T) => number = item => Number((item as { quantity?: number }).quantity || 0)): CategoryGroup<T>[] {
  const groups = new Map<string, CategoryGroup<T>>();
  items.forEach((item, index) => {
    const name = String(category(item) || '').trim();
    if (!groups.has(name)) groups.set(name, { category: name, entries: [], quantity: 0 });
    const group = groups.get(name)!;
    group.entries.push({ item, index }); group.quantity += quantity(item);
  });
  return [...groups.values()];
}

type AllocationRow = { uid: string; category: string; material_record_id: string; quantity: number; line_record_id?: string; split_source_line_id?: string; split_source_line_ids?: string[]; remark?: string; [key: string]: unknown };
type Material = { record_id: string; category: string; model: string; language: string; quantity?: number; category_definition?: string };

export function splitCategoryRows<T extends AllocationRow>(rows: T[], category: string, quantities: Record<string, number>, materials: Record<string, Material>, sourceIds: string[], uid: () => string): T[] {
  const group = rows.filter(row => row.category === category);
  if (!group.length) throw Error('未找到本品类明细 / Category no longer exists');
  const selected = Object.entries(quantities).filter(([,quantity]) => Number(quantity) > 0);
  if (!selected.length) throw Error('请至少选择一种规格组合 / Select at least one combination');
  const existing = new Map(group.map(row => [row.material_record_id, row]));
  const remarks = [...new Set(group.map(row => row.remark).filter(Boolean))].join('；');
  const next = selected.map(([id, quantity]) => {
    const material = materials[id];
    if (!material || material.category !== category || !Number.isSafeInteger(quantity) || quantity < 1) throw Error('分装品类或数量无效 / Invalid category or quantity');
    const old = existing.get(id);
    return { uid: old?.uid || uid(), line_record_id: old?.line_record_id || '', split_source_line_id: sourceIds[0] || '', split_source_line_ids: [...sourceIds],
      material_record_id: id, category, model: material.model, language: material.language, quantity,
      remark: old?.remark || remarks, order_required: material.category_definition === '印刷物料' && Number(material.quantity || 0) < quantity } as unknown as T;
  });
  const first = rows.findIndex(row => row.category === category);
  return [...rows.slice(0, first), ...next, ...rows.slice(first).filter(row => row.category !== category)];
}
