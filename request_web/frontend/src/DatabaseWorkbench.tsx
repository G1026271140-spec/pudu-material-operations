import { useEffect, useRef, useState } from "react";
import CategoryImageEditor from "./CategoryImageEditor";
import type { CategoryImage } from "./CategoryImageEditor";
import "./database.css";

type Field = { field_id:string;field_name:string;type:number;editable:boolean;read_only_reason:string;edit_via?:string;property?:any };
type Row = {record_id:string;fields:Record<string,any>;version:number;sync_state:string};
type Table = {table_id:string;name:string;label:string;source:string;count:number};
type Result = {table:Table;fields:Field[];records:Row[];count:number;labels:Record<string,Record<string,string>>};
type Edit = {row:Row;field:Field;key:string};
type Option = {id:string;label:string};
const text = (v:any):string => v==null?"":Array.isArray(v)?v.map(x=>typeof x==="object"?x?.name||x?.text||x?.id||"":String(x)).join("、"):typeof v==="object"?(v.value!=null?text(v.value):v.text||v.name||v.link||JSON.stringify(v)):String(v);
const ids = (v:any):string[] => [...new Set<string>((Array.isArray(v)?v:[v]).flatMap(x=>typeof x==="string"?[x]:x&&typeof x==="object"?[x.record_id||x.id,...(Array.isArray(x.record_ids)?x.record_ids:[]),...(Array.isArray(x.link_record_ids)?x.link_record_ids:[])]:[]).filter(x=>typeof x==="string"&&x))];
const scalar = (field:Field) => [1,2,3,5,7,13].includes(field.type);
const dateInput = (v:any) => {if(v==null||v==="")return "";const d=new Date(Number(v));return Number.isNaN(d.valueOf())?"":`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}T${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;};
async function json(url:string,init?:RequestInit){const r=await fetch(url,{cache:"no-store",...init});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==="string"?d.detail:"数据操作失败");return d;}

export default function DatabaseWorkbench({lang}:{lang:"zh"|"en"}){
  const tr=(zh:string,en:string)=>lang==="zh"?zh:en;
  const [tables,setTables]=useState<Table[]>([]),[tableId,setTableId]=useState("");
  const [status,setStatus]=useState<any>(null),[data,setData]=useState<Result|null>(null);
  const [page,setPage]=useState(0),[query,setQuery]=useState(""),[sort,setSort]=useState(""),[descending,setDescending]=useState(false);
  const [loading,setLoading]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const [edit,setEdit]=useState<Edit|null>(null),[saving,setSaving]=useState(false),[reload,setReload]=useState(0);
  const [visible,setVisible]=useState<string[]|null>(null),[columnMenu,setColumnMenu]=useState(false);
  const grid=useRef<HTMLTableElement>(null);
  const requestEpoch=useRef(0);
  const loadTables=()=>json("/api/admin/database/tables").then(d=>{setTables(d.tables);setStatus(d);setTableId(old=>old||d.tables.find((t:Table)=>t.name==="物料品类"&&t.source==="primary")?.table_id||d.tables[0]?.table_id||"");});
  useEffect(()=>{loadTables().catch(e=>setError(e.message));},[]);
  useEffect(()=>{
    if(!status?.sync_enabled)return;
    const handle=setInterval(()=>{if(document.visibilityState==='visible'&&!edit&&!saving){void loadTables().catch(()=>{});setReload(n=>n+1);}},5000);
    return ()=>clearInterval(handle);
  },[status?.sync_enabled,edit,saving]);
  useEffect(()=>{
    if(!tableId)return;
    const controller=new AbortController();const epoch=++requestEpoch.current;
    const timer=setTimeout(()=>{
      setLoading(true);setError("");
      const params=new URLSearchParams({page:String(page),limit:"50",q:query,descending:String(descending)});if(sort)params.set("sort_field",sort);
      json(`/api/admin/database/tables/${tableId}/records?${params}`,{signal:controller.signal})
        .then(d=>{if(epoch===requestEpoch.current)setData(d);})
        .catch(e=>{if(e.name!=="AbortError"&&epoch===requestEpoch.current)setError(e.message);})
        .finally(()=>{if(epoch===requestEpoch.current)setLoading(false);});
    },query?220:0);
    return ()=>{clearTimeout(timer);controller.abort();};
  },[tableId,page,query,sort,descending,reload]);
  function selectTable(id:string){if(saving)return;setTableId(id);setData(null);setPage(0);setQuery("");setSort("");setVisible(null);setEdit(null);setError("");setNotice("");}
  function open(row:Row,field:Field){if(saving)return;setError("");setEdit({row,field,key:crypto.randomUUID()});}
  async function save(value:any){
    if(!edit||saving)return;
    const current=edit;setSaving(true);setError("");
    try{
      const result=await json(`/api/admin/database/tables/${tableId}/records/${current.row.record_id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_version:current.row.version,idempotency_key:current.key,patch:{[current.field.field_id]:value}})});
      setData(d=>d?{...d,records:d.records.map(r=>r.record_id===result.record.record_id?result.record:r)}:d);
      setNotice(tr("已保存到本地数据库，等待后台同步飞书。","Saved locally; waiting for Feishu sync."));
      setEdit(null);setReload(x=>x+1);void loadTables();
      window.dispatchEvent(new Event("pudu-business-data-changed"));
      if(typeof BroadcastChannel!=="undefined"){const c=new BroadcastChannel("pudu-business-data");c.postMessage("changed");c.close();}
    }catch(e){setError(e instanceof Error?e.message:"保存失败");}finally{setSaving(false);}
  }
  const columns=(data?.fields||[]).filter(f=>visible===null||visible.includes(f.field_id));
  function content(row:Row,field:Field){
    const value=row.fields[field.field_id];
    if([2,20].includes(field.type)&&value!=null){const raw=typeof value==="object"?value.value:value;const n=Number(Array.isArray(raw)?raw[0]:raw);const formatter=field.property?.formatter||"";if(Number.isFinite(n)&&/^0(\.0+)?$/.test(formatter)){const digits=(formatter.split(".")[1]||"").length;return n.toLocaleString(lang==="zh"?"zh-CN":"en-GB",{useGrouping:false,minimumFractionDigits:digits,maximumFractionDigits:digits});}}
    if(field.type===7)return value?"✓":"—";
    if(field.type===5&&value!=null)return new Date(Number(value)).toLocaleString(lang==="zh"?"zh-CN":"en-GB");
    if([18,21].includes(field.type))return ids(value).map(id=>data?.labels[field.field_id]?.[id]||tr("关联记录","Linked record")).join("、");
    if(field.type===17)return Array.isArray(value)?value.map(x=>x.name||tr("附件","Attachment")).join("、"):"";
    return text(value);
  }
  const activeTable=tables.find(t=>t.table_id===tableId);
  return <section className="database-workbench" aria-label={tr("数据库工作台","Database workspace")}>
    <header className="database-heading"><div><h2>{tr("数据库工作台","Database workspace")}</h2><p>{tr("双击单元格或按 Enter 编辑，保存后立即更新本地数据。","Double-click a cell or press Enter to edit. Changes update the local database immediately.")}</p></div><button onClick={()=>{setReload(x=>x+1);void loadTables();}} disabled={saving}>{tr("刷新数据","Refresh")}</button></header>
    {status&&<div className="database-source"><span>PostgreSQL</span><span>{tr("最近导入","Last imported")}：{status.imported_at?new Date(status.imported_at).toLocaleString():"—"}</span><span>{status.pending_sync} {tr("条任务待同步","pending sync tasks")}</span><small>{status.sync_enabled?(status.workers_healthy?tr("飞书同步运行中 · 本地保存后自动同步","Feishu sync running · local changes sync automatically"):tr("飞书同步已启用，正在检查 Worker 状态","Feishu sync enabled; checking workers")):tr("飞书后台同步尚未启用；本页修改会持久保存在数据库。","Feishu sync is not enabled yet. Edits are durably saved in the database.")}{status.conflicts>0&&` · ${status.conflicts} ${tr("条历史冲突任务","historical conflicts")}`}</small></div>}
    {error&&<div className="database-error" role="alert">{error}<button onClick={()=>{setEdit(null);setReload(x=>x+1);}}>{tr("重新读取","Reload")}</button></div>}
    {notice&&!error&&<div className="database-notice" role="status">✓ {notice}</div>}
    <div className="database-layout"><aside className="database-tables" aria-label={tr("数据表","Tables")}>{tables.map(t=><button key={t.table_id} className={t.table_id===tableId?"active":""} onClick={()=>selectTable(t.table_id)}><span>{t.label}</span><small>{t.count}</small></button>)}</aside>
      <div className="database-main"><div className="database-toolbar"><select aria-label={tr("选择数据表","Select table")} value={tableId} onChange={e=>selectTable(e.target.value)}>{tables.map(t=><option key={t.table_id} value={t.table_id}>{t.label} ({t.count})</option>)}</select><strong>{activeTable?.label}</strong><input aria-label={tr("搜索当前表","Search this table")} placeholder={tr("搜索当前表…","Search this table…")} value={query} onChange={e=>{setQuery(e.target.value);setPage(0);}}/><button onClick={()=>setColumnMenu(v=>!v)}>{tr("显示字段","Columns")} ({columns.length})</button></div>
      {columnMenu&&data&&<div className="database-columns"><button onClick={()=>setVisible(null)}>{tr("显示全部","Show all")}</button>{data.fields.map(f=><label key={f.field_id}><input type="checkbox" checked={visible===null||visible.includes(f.field_id)} onChange={e=>setVisible(e.target.checked?[...(visible||data.fields.map(x=>x.field_id)),f.field_id]:(visible||data.fields.map(x=>x.field_id)).filter(x=>x!==f.field_id))}/>{f.field_name}</label>)}</div>}
      <div className="database-grid-wrap" aria-busy={loading}>{!data?<div className="database-empty">{error||tr("正在读取数据库…","Loading database…")}</div>:<table className="database-grid" role="grid" ref={grid}><thead><tr><th className="database-row-number">#</th>{columns.map(f=><th key={f.field_id} title={f.read_only_reason||f.field_name}><button onClick={()=>{if(sort===f.field_id)setDescending(v=>!v);else{setSort(f.field_id);setDescending(false);}setPage(0);}}>{!f.editable&&<span aria-label={tr("只读","Read only")}>{[19,20].includes(f.type)?"ƒx":"◇"} </span>}{f.field_name}{sort===f.field_id?(descending?" ↓":" ↑"):""}</button></th>)}<th>{tr("保存状态","Save status")}</th></tr></thead><tbody>{data.records.map((row,ri)=><tr key={row.record_id}><th className="database-row-number">{page*50+ri+1}</th>{columns.map((field,ci)=>{
        const editing=edit?.row.record_id===row.record_id&&edit.field.field_id===field.field_id&&field.editable&&scalar(field);
        return <td key={field.field_id} role="gridcell" tabIndex={0} data-row={ri} data-col={ci} data-field={field.field_id} data-record={row.record_id} aria-readonly={!field.editable} aria-label={`${ri+1} · ${field.field_name}`} className={`${!field.editable?"readonly":""} ${editing?"editing":""}`} title={field.editable?content(row,field):field.read_only_reason} onDoubleClick={()=>open(row,field)} onKeyDown={e=>{if(editing)return;if(e.key==="Enter"){e.preventDefault();open(row,field);}const delta:Record<string,[number,number]>={ArrowDown:[1,0],ArrowUp:[-1,0],ArrowLeft:[0,-1],ArrowRight:[0,1]};if(delta[e.key]){e.preventDefault();const [dr,dc]=delta[e.key];grid.current?.querySelector<HTMLElement>(`[data-row="${ri+dr}"][data-col="${ci+dc}"]`)?.focus();}}}>
          {editing?<InlineEditor key={edit!.key} field={field} value={row.fields[field.field_id]} saving={saving} onSave={save} onCancel={()=>setEdit(null)}/>:<span>{content(row,field)||<i>—</i>}</span>}</td>;
      })}<td className="database-state"><span className={row.sync_state}>{row.sync_state==="pending"?tr("本地已保存 · 待同步","Saved locally · Pending"):row.sync_state==="conflict"?tr("同步冲突","Sync conflict"):tr("已导入","Imported")}</span></td></tr>)}</tbody></table>}
      {data&&!data.records.length&&<div className="database-empty">{tr("没有匹配的记录","No matching records")}</div>}</div>
      <footer className="database-footer"><span>{data?.count??0} {tr("条记录","records")}{loading&&` · ${tr("正在读取…","Loading…")}`}</span><div><button disabled={page===0||loading||saving} onClick={()=>setPage(v=>v-1)}>{tr("上一页","Previous")}</button><span>{page+1} / {Math.max(1,Math.ceil((data?.count||0)/50))}</span><button disabled={!data||(page+1)*50>=data.count||loading||saving} onClick={()=>setPage(v=>v+1)}>{tr("下一页","Next")}</button></div></footer>
    </div></div>
    {edit&&(!edit.field.editable||!scalar(edit.field))&&<ComplexEditor key={edit.key} edit={edit} fields={data?.fields||[]} tableId={tableId} tr={tr} saving={saving} onSave={save} onClose={()=>setEdit(null)} onSource={field=>{const row=edit.row;setVisible(v=>v!==null&&!v.includes(field.field_id)?[...v,field.field_id]:v);open(row,field);requestAnimationFrame(()=>{const cell=grid.current?.querySelector<HTMLElement>(`[data-field="${field.field_id}"][data-record="${row.record_id}"]`);cell?.scrollIntoView({block:"nearest",inline:"nearest"});cell?.querySelector<HTMLInputElement>("input")?.focus();});}}/>}
  </section>;
}

function InlineEditor({field,value,saving,onSave,onCancel}:{field:Field;value:any;saving:boolean;onSave:(v:any)=>void;onCancel:()=>void}){
  const initial=field.type===5?dateInput(value):field.type===7?Boolean(value):text(value);
  const [draft,setDraft]=useState<any>(initial),[changed,setChanged]=useState(false);
  const submitted=useRef(false);
  function commit(next=draft){if(submitted.current||saving)return;if(!changed&&next===initial){onCancel();return;}submitted.current=true;onSave(field.type===2?(next===""?null:Number(next)):field.type===5?(next?new Date(next).valueOf():null):field.type===3&&next===""?null:next);}
  useEffect(()=>{if(!saving)submitted.current=false;},[saving]);
  const keyDown=(e:React.KeyboardEvent)=>{if(e.key==="Escape"){e.preventDefault();e.stopPropagation();submitted.current=true;onCancel();}if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();commit();}};
  if(field.type===3)return <select autoFocus disabled={saving} aria-label={field.field_name} value={draft} onChange={e=>{setChanged(true);setDraft(e.target.value);commit(e.target.value);}} onBlur={()=>commit()} onKeyDown={keyDown}><option value="">—</option>{(field.property?.options||[]).map((o:any)=><option key={o.id||o.name}>{o.name}</option>)}</select>;
  if(field.type===7)return <input autoFocus disabled={saving} type="checkbox" aria-label={field.field_name} checked={draft} onChange={e=>{setChanged(true);setDraft(e.target.checked);commit(e.target.checked);}} onBlur={()=>commit()} onKeyDown={keyDown}/>;
  if(field.type===1)return <textarea autoFocus rows={1} disabled={saving} aria-label={field.field_name} value={draft} onChange={e=>{setChanged(true);setDraft(e.target.value);}} onBlur={()=>commit()} onKeyDown={keyDown}/>;
  return <input autoFocus disabled={saving} aria-label={field.field_name} type={field.type===2?"number":field.type===5?"datetime-local":"text"} step="any" value={draft} onChange={e=>{setChanged(true);setDraft(e.target.value);}} onBlur={()=>commit()} onKeyDown={keyDown}/>;
}

function ComplexEditor({edit,fields,tableId,tr,saving,onSave,onClose,onSource}:{edit:Edit;fields:Field[];tableId:string;tr:(zh:string,en:string)=>string;saving:boolean;onSave:(v:any)=>void;onClose:()=>void;onSource:(field:Field)=>void}){
  const f=edit.field,original=edit.row.fields[f.field_id];
  const [value,setValue]=useState<any>(original),[options,setOptions]=useState<Option[]>([]),[q,setQ]=useState(""),[error,setError]=useState(""),[uploading,setUploading]=useState(false);
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{dialog.current?.showModal();return()=>dialog.current?.close();},[]);
  useEffect(()=>{if(!f.editable||![11,18,21].includes(f.type))return;const controller=new AbortController();const timer=setTimeout(()=>{const p=new URLSearchParams({q,selected:ids(original).join(",")});json(`/api/admin/database/tables/${tableId}/options/${f.field_id}?${p}`,{signal:controller.signal}).then(d=>setOptions(d.options)).catch(e=>{if(e.name!=="AbortError")setError(e.message);});},180);return()=>{clearTimeout(timer);controller.abort();};},[q]);
  const selected=f.type===4?(Array.isArray(value)?value:[]):ids(value);
  const isImage=(x:any)=>String(x.type||"").startsWith("image/")||/\.(png|jpe?g|webp|gif|avif|bmp)$/i.test(x.name||"");
  const attachments=Array.isArray(value)?value:[];
  const formula=String(f.property?.formula_expression||f.property?.formula||"");
  const dependencies=fields.filter(source=>formula.includes(`$field[${source.field_id}]`)||source.field_id===f.edit_via);
  const images:CategoryImage[]=attachments.filter(isImage).map(x=>({...x,path:x.local_media_id?`/api/admin/category-images/${x.local_media_id}`:`/api/live-image/${encodeURIComponent("物料品类")}/${edit.row.record_id}/${x.file_token}`}));
  function choose(id:string,on:boolean){const multiple=f.type===4||f.property?.multiple!==false;const next=on?(multiple?[...selected,id]:[id]):selected.filter((x:string)=>x!==id);setValue(f.type===11?next.map((x:string)=>({id:x,name:options.find(o=>o.id===x)?.label||text((original||[]).find((v:any)=>v.id===x)?.name)})):next);}
  return <dialog ref={dialog} className="database-dialog" onCancel={e=>{e.preventDefault();if(!saving&&!uploading)onClose();}}><header><div><small>{f.editable?tr("编辑单元格","Edit cell"):tr("只读字段","Read-only field")}</small><h3>{f.field_name}</h3></div><button aria-label={tr("关闭","Close")} disabled={saving||uploading} onClick={onClose}>×</button></header>
    {!f.editable?<><p>{f.read_only_reason}</p><pre>{typeof original==="object"?JSON.stringify(original,null,2):text(original)||"—"}</pre>{dependencies.length>0&&<div className="database-formula-sources"><p>{tr("修改来源字段后会重新计算：","Recalculated when these source fields change:")}</p>{dependencies.map(source=><button key={source.field_id} disabled={!source.editable} onClick={()=>onSource(source)}>{source.field_name} {source.editable?"↗":""}</button>)}</div>}</>:f.type===17?<CategoryImageEditor images={images} tr={tr} onBusy={setUploading} onChange={next=>setValue([...attachments.filter(x=>!isImage(x)),...next])}/>:f.type===15?<div className="database-link-editor"><label>{tr("显示文字","Display text")}<input value={value?.text||""} onChange={e=>setValue({...value,text:e.target.value})}/></label><label>URL<input type="url" value={value?.link||""} onChange={e=>setValue({...value,link:e.target.value})}/></label></div>:<><input className="database-option-search" autoFocus placeholder={tr("搜索选项…","Search options…")} value={q} onChange={e=>setQ(e.target.value)}/><div className="database-options">{(f.type===4?(f.property?.options||[]).map((o:any)=>({id:o.name,label:o.name})):options).filter((o:Option)=>f.type!==4||o.label.toLowerCase().includes(q.toLowerCase())).map((o:Option)=><label key={o.id}><input disabled={saving} type="checkbox" checked={selected.includes(o.id)} onChange={e=>choose(o.id,e.target.checked)}/><span>{o.label}</span></label>)}</div></>}
    {error&&<p role="alert">{error}</p>}<details><summary>{tr("字段对应关系","Field mapping")}</summary><code>{f.field_id}</code></details><footer><button disabled={saving||uploading} onClick={onClose}>{tr("关闭","Close")}</button>{f.editable&&<button className="primary" disabled={saving||uploading} onClick={()=>onSave(value)}>{saving?tr("保存中…","Saving…"):tr("保存","Save")}</button>}</footer>
  </dialog>;
}
