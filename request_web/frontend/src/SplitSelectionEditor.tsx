import { addSplitLanguage, changeSplitLanguage, toggleSplitModel } from './splitSelection';
import type { SplitOption, SplitQuantities } from './splitSelection';

export default function SplitSelectionEditor({ options, quantities, total, lang, onChange }: {
  options: SplitOption[]; quantities: SplitQuantities; total: number; lang: 'zh' | 'en'; onChange: (next: SplitQuantities) => void;
}) {
  const tr = (zh: string, en: string) => lang === 'zh' ? zh : en;
  const models = [...new Set(options.map(option => option.model))];
  const selected = options.filter(option => option.record_id in quantities);
  const count = new Set(selected.map(option => option.model)).size;
  return <div className="split-selection-editor">
    <div className="split-selected-heading"><strong>{tr('已选物料', 'Selected materials')}</strong><span>{tr(`${selected.length} 条明细`, `${selected.length} lines`)}</span></div>
    <div className="split-selected-table-wrap"><table className="split-selected-table"><thead><tr><th>{tr('型号', 'Model')}</th><th>{tr('语种', 'Language')}</th><th>{tr('数量', 'Quantity')}</th><th>{tr('比例 %', 'Share %')}</th><th>{tr('操作', 'Actions')}</th></tr></thead>
      <tbody>{selected.map(option => {
        const languages = options.filter(item => item.model === option.model);
        return <tr key={option.record_id}><th scope="row">{option.model}</th><td><select aria-label={tr(`${option.model} 的语种`, `Language for ${option.model}`)} value={option.record_id} onChange={event => onChange(changeSplitLanguage(quantities, options, option.record_id, event.target.value))}>{languages.map(item => <option key={item.record_id} value={item.record_id}>{item.language}</option>)}</select></td>
          <td><input aria-label={tr(`${option.model} ${option.language} 数量`, `Quantity for ${option.model} ${option.language}`)} type="number" min="1" step="1" value={quantities[option.record_id]} onChange={event => onChange({ ...quantities, [option.record_id]: Math.max(1, Math.floor(Number(event.target.value) || 1)) })}/></td>
          <td><input aria-label={tr(`${option.model} ${option.language} 比例`, `Share for ${option.model} ${option.language}`)} type="number" min="0" step="0.1" value={Number((quantities[option.record_id] / total * 100).toFixed(1))} onChange={event => onChange({ ...quantities, [option.record_id]: Math.max(1, Math.round(total * (Number(event.target.value) || 0) / 100)) })}/></td>
          <td className="split-row-actions"><button type="button" disabled={languages.every(item => item.record_id in quantities)} onClick={() => onChange(addSplitLanguage(quantities, options, option.model))}>{tr('＋语种', '+ Language')}</button><button type="button" onClick={() => { const next = { ...quantities }; delete next[option.record_id]; onChange(next); }}>{tr('移除', 'Remove')}</button></td>
        </tr>;
      })}</tbody></table>{selected.length === 0 && <div className="split-pool-empty">{tr('请在下方框选池选择型号', 'Choose models in the pool below')}</div>}</div>
    <div className="split-model-pool" role="group" aria-label={tr('型号框选池', 'Model selection pool')}><div className="split-pool-heading"><strong>{tr('产品型号', 'Product Model')}</strong><span>{tr(`已选 ${count} 个型号`, `${count} models selected`)}</span></div>
      <div className="pills">{models.map(model => { const chosen = selected.some(option => option.model === model); return <button type="button" key={model} className={chosen ? 'chosen' : ''} aria-pressed={chosen} onClick={() => onChange(toggleSplitModel(quantities, options, model, total))}>{model}</button>; })}</div>
    </div>
  </div>;
}
