export type SplitOption = { record_id: string; model: string; language: string };
export type SplitQuantities = Record<string, number>;

export function toggleSplitModel(current: SplitQuantities, options: readonly SplitOption[], model: string, total: number): SplitQuantities {
  const matches = options.filter(option => option.model === model);
  if (!matches.length) throw Error('型号已变化，请刷新 / Model no longer available');
  const next = { ...current };
  if (matches.some(option => option.record_id in next)) matches.forEach(option => delete next[option.record_id]);
  else {
    const language = options.find(option => option.record_id in current)?.language;
    const first = matches.find(option => option.language === language) || matches.find(option => /英语|English/i.test(option.language)) || matches[0];
    next[first.record_id] = 1;
  }
  const ids = Object.keys(next);
  ids.forEach((id, index) => { next[id] = Math.max(1, Math.floor(total / ids.length) + (index < total % ids.length ? 1 : 0)); });
  return next;
}

export function changeSplitLanguage(current: SplitQuantities, options: readonly SplitOption[], fromId: string, toId: string): SplitQuantities {
  const from = options.find(option => option.record_id === fromId), to = options.find(option => option.record_id === toId);
  if (!(fromId in current) || !from || !to || from.model !== to.model) throw Error('只能修改当前型号的语种 / Select a language for this model');
  if (fromId === toId) return current;
  const next = { ...current }; const quantity = next[fromId]; delete next[fromId];
  next[toId] = (next[toId] || 0) + quantity;
  return next;
}

export function addSplitLanguage(current: SplitQuantities, options: readonly SplitOption[], model: string): SplitQuantities {
  const matches = options.filter(option => option.model === model);
  const added = matches.find(option => !(option.record_id in current));
  if (!added) return current;
  const next = { ...current }, selected = matches.filter(option => option.record_id in current);
  const total = selected.reduce((sum, option) => sum + current[option.record_id], 0) || 1;
  const ids = [...selected.map(option => option.record_id), added.record_id];
  ids.forEach((id, index) => { next[id] = Math.max(1, Math.floor(total / ids.length) + (index < total % ids.length ? 1 : 0)); });
  return next;
}
