import { useEffect, useRef, useState } from 'react';
import ToastMessage from './ToastMessage';
import './stock-workbench.css';

type Kind='ordinary'|'cultural'|'apparel';
type Row={kind:Kind;kind_label:string;record_id:string;table_id:string;table_name:string;source:string;version:number;sync_state:string;
  code:string;category:string;model:string;language:string;regions:string[];quantity:number|null;in_transit:number|null;editable:boolean;read_only_reason:string};
type Filters={kind:string;category:string;model:string;language:string;region:string;q:string};
type Data={records:Row[];count:number;facets:Record<string,string[]>;kinds:{value:string;label:string}[];editor_enabled:boolean};
const EMPTY:Filters={kind:'all',category:'',model:'',language:'',region:'',q:''};
async function json(url:string,init?:RequestInit){
  const r=await fetch(url,{cache:'no-store',...init});
  if(!r.headers.get('content-type')?.includes('application/json'))throw Error('请重新登录后再试 / Please sign in again');
  const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'数据操作失败 / Request failed');return d;
}

export default function StockWorkbench({lang,onBusy}:{lang:'zh'|'en';onBusy:(busy:boolean)=>void}){
  const tr=(zh:string,en:string)=>lang==='zh'?zh:en;
  const [filters,setFilters]=useState<Filters>(EMPTY),[page,setPage]=useState(0),[data,setData]=useState<Data|null>(null);
  const [loading,setLoading]=useState(true),[reload,setReload]=useState(0),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [edit,setEdit]=useState<Row|null>(null),[target,setTarget]=useState(''),[note,setNote]=useState(''),[saving,setSaving]=useState(false),[saveError,setSaveError]=useState('');
  const dialog=useRef<HTMLDialogElement>(null),epoch=useRef(0),attempt=useRef<{signature:string;token:string}|null>(null);
  useEffect(()=>{
    const controller=new AbortController(),generation=++epoch.current;
    const timer=setTimeout(()=>{
      setLoading(true);setError('');
      json('/api/admin/database/stock?'+new URLSearchParams({...filters,page:String(page),limit:'50'}),{signal:controller.signal})
        .then(value=>{if(generation===epoch.current)setData(value);})
        .catch(e=>{if(e.name!=='AbortError'&&generation===epoch.current)setError(e.message);})
        .finally(()=>{if(generation===epoch.current)setLoading(false);});
    },filters.q?180:0);
    return()=>{clearTimeout(timer);controller.abort();};
  },[filters,page,reload]);
  useEffect(()=>{
    const timer=setInterval(()=>{if(!document.hidden&&!edit&&!saving)setReload(n=>n+1);},5000);
    return()=>clearInterval(timer);
  },[edit,saving]);
  useEffect(()=>{if(edit)dialog.current?.showModal();else dialog.current?.close();onBusy(Boolean(edit)||saving);},[edit,saving]);
  function filter(key:keyof Filters,value:string){setFilters(old=>key==='kind'?{...EMPTY,kind:value}:key==='category'?{...old,category:value,model:'',language:'',region:''}:key==='model'?{...old,model:value,language:'',region:''}:{...old,[key]:value});setPage(0);}
  function open(row:Row){setEdit(row);setTarget(String(row.quantity??''));setNote('');setSaveError('');attempt.current=null;}
  const numeric=target.trim()===''?NaN:Number(target),valid=Number.isInteger(numeric)&&Math.abs(numeric)<=1000000000;
  const delta=edit&&valid?numeric-(edit.quantity||0):null;
  async function save(){
    if(!edit||saving||!valid)return;setSaving(true);setSaveError('');
    const body={kind:edit.kind,record_id:edit.record_id,expected_version:edit.version,quantity:numeric,note};
    const signature=JSON.stringify(body);if(attempt.current?.signature!==signature)attempt.current={signature,token:crypto.randomUUID()};
    try{
      const result=await json('/api/admin/database/stock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,idempotency_key:attempt.current.token})});
      setData(old=>old?{...old,records:old.records.map(row=>row.kind===result.record.kind&&row.record_id===result.record.record_id?result.record:row)}:old);
      setEdit(null);setReload(n=>n+1);attempt.current=null;
      setNotice(result.changed?tr(`库存已保存：${result.before} → ${result.after}，等待后台同步飞书。`,`Stock saved: ${result.before} → ${result.after}. Feishu sync pending.`):tr('库存未变化。','Stock unchanged.'));
      window.dispatchEvent(new Event('pudu-business-data-changed'));
      if(typeof BroadcastChannel!=='undefined'){const c=new BroadcastChannel('pudu-business-data');c.postMessage('changed');c.close();}
    }catch(e){setSaveError(e instanceof Error?e.message:tr('保存失败，修改仍保留。','Save failed. Your edits are retained.'));}
    finally{setSaving(false);}
  }
  const labels:Record<string,[string,string]>={category:['品类','Category'],model:['型号 / 尺码','Model / size'],language:['语种','Language'],region:['战区','Region']};
  const state=(value:string)=>value==='pending'?tr('本地已保存 · 待同步','Saved locally · Pending'):value==='conflict'?tr('同步冲突','Sync conflict'):tr('已同步','Synced');
  return <section className="stock-workbench" aria-label={tr('库存查询','Inventory lookup')}>
    <div className="stock-searchbar"><label><span>{tr('库存类型','Inventory type')}</span><select value={filters.kind} onChange={e=>filter('kind',e.target.value)}><option value="all">{tr('全部库存','All inventory')}</option>{(data?.kinds||[]).map(item=><option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label className="stock-keyword"><span>{tr('搜索物料','Find item')}</span><input type="search" placeholder={tr('输入编码、品类或规格','Code, category or specification')} value={filters.q} onChange={e=>filter('q',e.target.value)}/></label>
      <button type="button" disabled={loading} onClick={()=>setReload(n=>n+1)}>{tr('刷新库存','Refresh')}</button><button type="button" onClick={()=>{setFilters(EMPTY);setPage(0);}}>{tr('重置筛选','Reset filters')}</button></div>
    <div className="stock-filters">{Object.entries(labels).map(([key,label])=><label key={key}><span>{tr(...label)}</span><select value={filters[key as keyof Filters]} onChange={e=>filter(key as keyof Filters,e.target.value)}><option value="">{tr('全部'+label[0],'All '+label[1].toLowerCase())}</option>{[...new Set([...(data?.facets[key]||[]),filters[key as keyof Filters]])].filter(Boolean).map(value=><option key={value}>{value}</option>)}</select></label>)}</div>
    <div className="stock-result-meta"><strong>{data?.count??0} {tr('个库存规格','inventory specifications')}</strong><span>{tr('普通物料按语种管理；文化周边按战区管理；文化衫库存对应行政源表。','Ordinary items use languages, cultural items use regions, and apparel uses the administrative source.')}</span></div>
    {error&&<ToastMessage role="alert">{error}</ToastMessage>}{notice&&!error&&<ToastMessage role="status">{notice}</ToastMessage>}
    <div className="stock-table-wrap" aria-busy={loading}><table className="stock-table"><thead><tr>{[['库存类型','Type'],['物料编码','Code'],['品类','Category'],['型号 / 尺码','Model / size'],['语种','Language'],['战区','Region'],['当前库存','Current stock'],['在途库存','In transit'],['同步状态','Sync status'],['操作','Action']].map(label=><th key={label[0]}>{tr(label[0],label[1])}</th>)}</tr></thead>
      <tbody>{data?.records.map(row=><tr key={row.kind+':'+row.record_id}><td><span className="stock-kind">{row.kind_label}</span></td><td className="stock-code" title={row.table_name+' / '+row.record_id}>{row.code||'—'}</td><td className="stock-category">{row.category}</td><td>{row.model||'—'}</td><td>{row.language||'—'}</td><td>{row.regions.join('、')||'—'}</td><td className={'stock-number '+((row.quantity??0)<0?'negative':'')}><strong>{row.quantity??'—'}</strong></td><td className="stock-number">{row.in_transit??'—'}</td><td><span className={'stock-sync '+row.sync_state}>{state(row.sync_state)}</span></td><td><button type="button" disabled={!data.editor_enabled||!row.editable} title={row.read_only_reason||undefined} onClick={()=>open(row)}>{tr('修改库存','Edit stock')}</button></td></tr>)}</tbody></table>
      {!data?.records.length&&<div className="stock-empty">{loading?tr('正在读取库存…','Loading inventory…'):error||tr('没有匹配的库存，请调整筛选条件。','No inventory matches. Change the filters.')}</div>}</div>
    <footer className="stock-pagination"><span>{loading?tr('正在刷新…','Refreshing…'):tr('库存来自虚拟机 PostgreSQL，保存后后台同步飞书。','Inventory is read from PostgreSQL; saved changes synchronize to Feishu.')}</span><div><button disabled={page===0||loading} onClick={()=>setPage(n=>n-1)}>{tr('上一页','Previous')}</button><span>{page+1} / {Math.max(1,Math.ceil((data?.count||0)/50))}</span><button disabled={loading||(page+1)*50>=(data?.count||0)} onClick={()=>setPage(n=>n+1)}>{tr('下一页','Next')}</button></div></footer>
    <dialog ref={dialog} className="database-dialog stock-dialog" aria-labelledby="stock-edit-title" onCancel={e=>{e.preventDefault();if(!saving)setEdit(null);}}>{edit&&<>
      <header><div><small>{edit.kind_label} · {edit.code}</small><h3 id="stock-edit-title">{tr('修改库存','Edit inventory')}</h3></div><button aria-label={tr('关闭','Close')} disabled={saving} onClick={()=>setEdit(null)}>×</button></header>
      <p className="stock-edit-spec"><strong>{edit.category}</strong><br/>{[edit.model,edit.language,...edit.regions].filter(Boolean).join(' / ')}</p>
      <div className="stock-edit-numbers"><div><span>{tr('当前库存','Current stock')}</span><strong>{edit.quantity}</strong></div><label><span>{tr('修改后库存','New stock')} <b className="stock-required">*</b></span><input autoFocus type="number" step="1" min="-1000000000" max="1000000000" value={target} disabled={saving} onChange={e=>setTarget(e.target.value)}/></label><div><span>{tr('库存变动','Change')}</span><strong>{delta==null?'—':delta>0?'+'+delta:delta}</strong></div></div>
      <label className="stock-edit-note"><span>{tr('调整说明（选填）','Reason (optional)')}</span><textarea rows={3} maxLength={1000} disabled={saving} value={note} onChange={e=>setNote(e.target.value)}/></label>
      <p>{tr('保存后更新本地库存并记录流水，再由 Worker 同步飞书。','Saving updates local inventory and records the adjustment, then Worker synchronizes Feishu.')}{edit.kind==='apparel'&&' '+tr('通过“入库/纠正”更新库存，保留已有兑换数量。','The correction field changes; redeemed quantities are retained.')}</p>
      {saveError&&<ToastMessage role="alert">{saveError}</ToastMessage>}<footer><button disabled={saving} onClick={()=>setEdit(null)}>{tr('取消','Cancel')}</button><button className="primary" disabled={saving||!valid} onClick={()=>void save()}>{saving?tr('正在保存…','Saving…'):tr('保存库存','Save stock')}</button></footer>
    </>}</dialog>
  </section>;
}
