import {useEffect,useState} from "react";
import CategoryImageEditor from "./CategoryImageEditor";
import type {CategoryImage} from "./CategoryImageEditor";
import RequiredMark from "./RequiredMark";
import "./management.css";
import "./apparel-management.css";

type Row={record_id:string;size:string;code:string;original:number;correction:number;external_redeemed:number;system_redeemed:number;available:number;remark:string};
type Style={key:string;source_style:string;label:string;visible:boolean;limit:number;rows:Row[];expected_versions:Record<string,number>;images:CategoryImage[];total_stock:number};
type Catalog={styles:Style[];sizes:string[];schema_ready:boolean};
const emptyRow=():Row=>({record_id:"",size:"",code:"",original:0,correction:0,external_redeemed:0,system_redeemed:0,available:0,remark:""});
const emptyStyle=():Style=>({key:"",source_style:"",label:"",visible:true,limit:1,rows:[emptyRow()],expected_versions:{},images:[],total_stock:0});

export default function ApparelManagementPage({lang}:{lang:"zh"|"en"}){
 const tr=(zh:string,en:string)=>lang==="zh"?zh:en;
 const [catalog,setCatalog]=useState<Catalog|null>(null);
 const [form,setForm]=useState<Style>(emptyStyle);
 const [operation,setOperation]=useState<"create"|"edit"|"delete">("edit");
 const [imagesChanged,setImagesChanged]=useState(false);
 const [uploading,setUploading]=useState(false);
 const [busy,setBusy]=useState(false);
 const [review,setReview]=useState(false);
 const [confirmation,setConfirmation]=useState("");
 const [query,setQuery]=useState("");
 const [error,setError]=useState("");
 const [success,setSuccess]=useState("");
 const [saveToken,setSaveToken]=useState(()=>crypto.randomUUID());
 function select(style:Style){setForm(structuredClone(style));setOperation("edit");setImagesChanged(false);setReview(false);setConfirmation("");setSaveToken(crypto.randomUUID());setError("");}
 async function load(key?:string){
  try{const response=await fetch('/api/hr/corporate-apparel/catalog',{cache:'no-store'});const body=await response.json();if(!response.ok)throw Error(body.detail||tr("数据读取失败","Could not load data"));setCatalog(body);const selected=body.styles.find((item:Style)=>item.key===key)||body.styles[0];if(selected)select(selected);else{setForm(emptyStyle());setOperation("create");}}
  catch(e){setError(e instanceof Error?e.message:"读取失败");}
 }
 useEffect(()=>{void load();},[]);
 function create(){setForm(emptyStyle());setOperation("create");setImagesChanged(false);setReview(false);setConfirmation("");setSaveToken(crypto.randomUUID());setError("");setSuccess("");}
 function updateRow(index:number,patch:Partial<Row>){setForm(current=>({...current,rows:current.rows.map((row,i)=>i===index?{...row,...patch}:row)}));}
 function preview(){
  setError("");
  if(operation!=="delete"){
   if(!form.source_style.trim()||!form.label.trim())return setError(tr("请填写行政源表款式名称和申领页显示名称。","Enter the source style and display name."));
   if(!Number.isInteger(form.limit)||form.limit<1||form.limit>9999)return setError(tr("每人累计领取上限须为 1 至 9999 的整数。","The cumulative limit must be an integer from 1 to 9999."));
   if(!form.rows.length||form.rows.some(row=>!row.size)||new Set(form.rows.map(row=>row.size)).size!==form.rows.length)return setError(tr("请至少保留一个尺码，尺码不能重复。","Keep at least one size and remove duplicate sizes."));
  }
  setConfirmation("");setReview(true);
 }
 async function save(){
  setBusy(true);setError("");
  try{
   const body={operation,style_key:form.key,source_style:form.source_style,label:form.label,visible:form.visible,limit:form.limit,
    expected_versions:form.expected_versions,idempotency_key:saveToken,confirm_delete:confirmation,
    rows:form.rows.map(({record_id,size,code,original,correction,remark})=>({record_id,size,code,original,correction,remark})),
    ...((imagesChanged||operation==="create")?{images:form.images.map(image=>image.local_media_id?{local_media_id:image.local_media_id}:{file_token:image.file_token})}:{})};
   const response=await fetch('/api/hr/corporate-apparel/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   const result=await response.json();if(!response.ok)throw Error(result.detail||tr("保存失败","Save failed"));
   setReview(false);setSuccess(tr("已保存，申领页已更新，正在同步飞书。","Saved. The request page is updated and synchronization is pending."));await load(result.style_key);
  }catch(e){setError(e instanceof Error?e.message:"保存失败");}finally{setBusy(false);}
 }
 if(!catalog)return <main className="management-page"><div className="loading">{error||tr("正在读取企业文化衫…","Loading corporate apparel…")}</div></main>;
 const original=catalog.styles.find(item=>item.key===form.key);
 const total=form.rows.reduce((sum,row)=>sum+Number(row.original)+Number(row.correction)-Number(row.external_redeemed)-Number(row.system_redeemed),0);
 return <main className="management-page apparel-management-page" aria-label={tr("企业文化衫管理","Corporate apparel management")}>
  <div className="management-body">
   <div className="apparel-toolbar apparel-actions-only"><div><button onClick={()=>void load(form.key)} disabled={busy||uploading}>{tr("刷新数据","Refresh data")}</button><button className="primary" onClick={create} disabled={busy||uploading}>{tr("＋ 新增款式","＋ New style")}</button></div></div>
   {success&&<div role="status" className="success-banner">{success}</div>}
   {!catalog.schema_ready&&<div className="danger-box">{tr("行政源表的申领设置字段尚未就绪，请联系管理员。","The source settings are not ready. Contact an administrator.")}</div>}
   <div className="apparel-management-layout">
    <aside className="apparel-style-list"><input aria-label={tr("搜索款式","Search styles")} placeholder={tr("搜索款式名称","Search styles")} value={query} onChange={event=>setQuery(event.target.value)}/>{catalog.styles.filter(item=>`${item.source_style} ${item.label}`.toLowerCase().includes(query.toLowerCase())).map(item=><button key={item.key} className={item.key===form.key?"active":""} onClick={()=>select(item)} disabled={busy||uploading}><strong>{item.label}</strong><span>{item.rows.length} {tr("个尺码","sizes")} · {item.total_stock} {tr("件","items")}</span><small>{item.visible?tr("申领页显示","Visible on request page"):tr("未展示","Hidden")}</small></button>)}</aside>
    <div className="apparel-editor">
     <div className="apparel-edit-heading"><h3>{operation==="create"?tr("新增款式","New style"):form.label}</h3>{form.key&&<div className="operation-switch"><button className={operation==="edit"?"active":""} onClick={()=>setOperation("edit")}>{tr("编辑款式","Edit")}</button><button className={operation==="delete"?"active":""} onClick={()=>{if(original)setForm(structuredClone(original));setOperation("delete");}}>{tr("删除款式","Delete")}</button></div>}</div>
     {operation==="delete"?<div className="danger-box">{tr("将删除此款式在行政源表中的全部规格。有领用历史的规格不能删除，可改为关闭申领页显示。","This removes every source SKU for the style. Styles with claim history must be hidden instead.")}</div>:<>
      <section className="admin-section apparel-settings"><h3>{tr("申领展示与额度","Display and quota")}</h3><div className="form-grid three">
       <label><span className="field-label">{tr("行政源表款式名称","Source style name")}<RequiredMark/></span><input value={form.source_style} maxLength={200} onChange={event=>setForm({...form,source_style:event.target.value})}/></label>
       <label><span className="field-label">{tr("申领页显示名称","Display name")}<RequiredMark/></span><input value={form.label} maxLength={120} onChange={event=>setForm({...form,label:event.target.value})}/></label>
       <label><span className="field-label">{tr("每人累计领取上限","Cumulative per-person limit")}<RequiredMark/></span><input type="number" min="1" max="9999" step="1" value={form.limit} onChange={event=>setForm({...form,limit:Number(event.target.value)})}/></label>
      </div><label className="apparel-visible"><input type="checkbox" checked={form.visible} onChange={event=>setForm({...form,visible:event.target.checked})}/>{tr("在企业文化衫申领页显示此款式","Show this style on the request page")}</label>
      <CategoryImageEditor images={form.images} onChange={images=>{setForm(current=>({...current,images}));setImagesChanged(true);}} tr={tr} onBusy={setUploading} uploadUrl="/api/hr/corporate-apparel/images"/>
      </section>
     </>}
     <section className="admin-section"><div className="apparel-stock-heading"><h3>{tr("尺码与库存","Sizes and stock")}</h3><b>{total} {tr("件可领取","available")}</b></div>
      <div className="table-wrap"><table className="admin-table"><thead><tr>{[tr("尺码","Size"),tr("编码","Code"),tr("原始库存","Original"),tr("入库／纠正","Correction"),tr("表格兑换","External claims"),tr("系统领取","System claims"),tr("可领取","Available"),tr("备注","Notes"),tr("操作","Action")].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{form.rows.map((row,index)=><tr key={row.record_id||`new-${index}`}>
       <td><select aria-label={tr(`第 ${index+1} 行尺码`,`Size in row ${index+1}`)} disabled={operation==="delete"} value={row.size} onChange={event=>updateRow(index,{size:event.target.value})}><option value="">{tr("选择尺码","Select size")}</option>{catalog.sizes.map(size=><option key={size}>{size}</option>)}</select></td>
       <td><input disabled={operation==="delete"} value={row.code} placeholder={tr("留空自动生成","Generated if empty")} onChange={event=>updateRow(index,{code:event.target.value})}/></td>
       <td><input type="number" min="0" step="1" disabled={operation==="delete"} value={row.original} onChange={event=>updateRow(index,{original:Number(event.target.value)})}/></td>
       <td><input type="number" step="1" disabled={operation==="delete"} value={row.correction} onChange={event=>updateRow(index,{correction:Number(event.target.value)})}/></td>
       <td>{row.external_redeemed}</td><td>{row.system_redeemed}</td><td><strong>{Number(row.original)+Number(row.correction)-row.external_redeemed-row.system_redeemed}</strong></td>
       <td><input disabled={operation==="delete"} value={row.remark} onChange={event=>updateRow(index,{remark:event.target.value})}/></td>
       <td>{operation!=="delete"&&<button className="apparel-remove" onClick={()=>setForm({...form,rows:form.rows.filter((_,i)=>i!==index)})}>{tr("移除","Remove")}</button>}</td></tr>)}</tbody></table></div>
      {operation!=="delete"&&<button className="apparel-add-size" onClick={()=>setForm({...form,rows:[...form.rows,emptyRow()]})}>{tr("＋ 新增尺码","＋ Add size")}</button>}
     </section>
     <div className="admin-actions"><span>{tr("兑换数量与计算库存由系统维护","Claim counts and available stock are maintained by the system")}</span><button className="primary" disabled={busy||uploading||!catalog.schema_ready} onClick={preview}>{tr("预览变更","Review changes")}</button></div>
    </div>
   </div>
  </div>
  {busy&&<div className="submit-overlay"><div className="spinner"/><strong>{tr("正在保存，请稍候…","Saving, please wait…")}</strong></div>}
  {error&&<div className="toast" role="alert" onClick={()=>setError("")}>{error} ×</div>}
  {review&&<div className="overlay"><div className="modal admin-review apparel-review"><button className="close" disabled={busy} onClick={()=>setReview(false)}>×</button><h2>{operation==="delete"?tr("确认删除款式","Confirm deletion"):tr("确认款式变更","Confirm style changes")}</h2><p><b>{form.label}</b> · {form.source_style}</p><dl><dt>{tr("申领页显示","Visible")}</dt><dd>{form.visible?tr("是","Yes"):tr("否","No")}</dd><dt>{tr("每人累计上限","Cumulative limit")}</dt><dd>{form.limit}</dd><dt>{tr("库存规格","Size rows")}</dt><dd>{original?.rows.length||0} → {operation==="delete"?0:form.rows.length}</dd><dt>{tr("目标可领取库存","Available stock")}</dt><dd>{operation==="delete"?0:total}</dd></dl><ul>{form.rows.map((row,index)=><li key={index}>{row.size||tr("未选尺码","No size")} · {Number(row.original)+Number(row.correction)-row.external_redeemed-row.system_redeemed} {tr("件","items")}</li>)}</ul>{operation==="delete"&&<label>{tr("输入款式显示名称确认删除","Type the display name to confirm deletion")}<input value={confirmation} onChange={event=>setConfirmation(event.target.value)}/></label>}<button className="primary" disabled={busy||(operation==="delete"&&confirmation!==form.label)} onClick={()=>void save()}>{busy?tr("正在保存…","Saving…"):tr("确认保存","Confirm")}</button></div></div>}
 </main>;
}
