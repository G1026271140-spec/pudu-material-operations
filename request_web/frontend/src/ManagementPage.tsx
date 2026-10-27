import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import AllocationWorkbench from "./AllocationWorkbench";
import ShippingSchedulePage from "./ShippingSchedulePage";
import ShippingTemplatePage from "./ShippingTemplatePage";
import CategoryCarousel from "./CategoryCarousel";
import CategoryModelMedia from "./CategoryModelMedia";
import { categoryDeletePreview } from "./categoryDeletion";
import type { CategoryDeleteScope } from "./categoryDeletion";
import CategoryImageEditor from "./CategoryImageEditor";
import DatabaseWorkbench from "./DatabaseWorkbench";
import type { CategoryImage } from "./CategoryImageEditor";
import "./management.css";

type Lang = "zh" | "en";
type Operation = "create" | "edit" | "delete";
type Kind = "model" | "language" | "region";
export type ManagementTab = "allocation" | "schedule" | "shipping" | "restock" | "category" | "database" | Kind;
type Catalog = {
  generatedAt: string;
  categories: any[];
  inventory: any[];
  restockInventory: any[];
  restockImages: Record<string, string[]>;
  restockModels?: Record<string, string>;
  culturalInventory: any[];
  dimensions: Record<Kind, any[]>;
  categoryDefinitions: string[];
  packingTypes: string[];
  statuses: string[];
  visibilityOptions: string[];
  modelTypes: string[];
  noModelText: string;
  noLanguageText: string;
  maxRestockLines: number;
};

const unique = (values: string[]) => [...new Set(values.filter(Boolean))];
const splitValues = (value: string) => unique(value.split(/[\n,，;；、]+/).map((item) => item.trim()));
const token = () => crypto.randomUUID().replaceAll("-", "");
const detailText = (detail: unknown, fallback: string) =>
  Array.isArray(detail) ? detail.join("；") : typeof detail === "string" ? detail : fallback;

async function post(url: string, body: unknown) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(detailText(data.detail, "操作失败"));
  return data;
}

export default function ManagementPage({
  lang,
  initialTab = "allocation",
  onTabChange,
}: {
  lang: Lang;
  initialTab?: ManagementTab;
  onTabChange?: (tab: ManagementTab) => void;
}) {
  const tr = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [tab, setTab] = useState<ManagementTab>(initialTab);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => {
    setError("");
    fetch("/api/admin/management-catalog")
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw Error(data.detail || "管理数据读取失败");
        return data;
      })
      .then(setCatalog)
      .catch((e) => setError(e.message));
  };
  // Allocation and shipping schedule do not use the large management catalog.
  // Let their own data load immediately instead of blocking the whole page.
  useEffect(() => {
    if (tab !== "allocation" && tab !== "schedule" && tab !== "database" && !catalog) load();
  }, [tab, catalog]);
  useEffect(() => setTab(initialTab), [initialTab]);
  function selectTab(next: ManagementTab) {
    if(next===tab)return;
    if(document.querySelector('meta[name="pudu-data-source"]')?.getAttribute('content')==='postgresql')setCatalog(null);
    setTab(next);
    setError("");
    setSuccess("");
    onTabChange?.(next);
  }
  const needsCatalog = tab !== "allocation" && tab !== "schedule" && tab !== "database";
  const tabs = [
    ["allocation", tr("配货工作台", "Allocation")],
    ["schedule", tr("发货排期", "Shipping Schedule")],
    ["shipping", tr("发货模板", "Shipping Template")],
    ["restock", tr("采购补库", "Restock")],
    ["category", tr("品类管理", "Categories")],
    ["model", tr("型号管理", "Models")],
    ["language", tr("语种管理", "Languages")],
    ["region", tr("战区管理", "Regions")],
    ["database", tr("数据库工作台", "Database")],
  ] as const;
  return (
    <main className="management-page">
      <div className="legacy-page-header">
        <div><small>{tr("库存工作台", "Inventory Workspace")}</small><h1>{tr("物料管理", "Material Management")}</h1><p>{tr("采购补库与基础维度统一管理", "Restocking and material dimensions")}</p></div>
        {needsCatalog && <button onClick={load}>↻ {tr("刷新本页数据", "Refresh page data")}</button>}
      </div>
      <div className="management-body">
        <div className="management-tabs">{tabs.filter(([key])=>key!=="database"||document.querySelector('meta[name="pudu-data-source"]')?.getAttribute('content')==='postgresql').map(([key, label]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => selectTab(key)}>{label}</button>)}</div>
        {success && <div className="success-banner">✓ {success}</div>}
        {needsCatalog && !catalog && <div className="loading">{error || tr("正在读取管理数据缓存…", "Loading management cache…")}</div>}
        {tab === "allocation" && <AllocationWorkbench lang={lang} embedded />}
        {tab === "schedule" && <ShippingSchedulePage lang={lang} />}
        {tab === "database" && <DatabaseWorkbench lang={lang} />}
        {tab === "shipping" && catalog && <ShippingTemplatePage catalog={catalog} lang={lang} />}
        {tab === "restock" && catalog && <Restock catalog={catalog} tr={tr} setBusy={setBusy} setError={setError} setSuccess={setSuccess} />}
        {tab === "category" && catalog && <CategoryManager catalog={catalog} tr={tr} setBusy={setBusy} setError={setError} setSuccess={setSuccess} />}
        {(["model", "language", "region"] as string[]).includes(tab) && catalog && <DimensionManager key={tab} kind={tab as Kind} catalog={catalog} tr={tr} setBusy={setBusy} setError={setError} setSuccess={setSuccess} />}
      </div>
      {error && <div className="toast" onClick={() => setError("")}>{error} ×</div>}
      {busy && <div className="submit-overlay"><div className="spinner"/><strong>{tr("正在提交数据，请稍后……", "Submitting, please wait…")}</strong><span>{tr("任务正在进入后台队列，请勿重复提交", "The task is entering the background queue")}</span></div>}
    </main>
  );
}

function Section({ index, title, hint, children }: { index: string; title: string; hint: string; children: ReactNode }) {
  return <section className="admin-section"><div className="section-title"><i>{index}</i><div><h2>{title}</h2><p>{hint}</p></div></div>{children}</section>;
}

function Restock({ catalog, tr, setBusy, setError, setSuccess }: any) {
  const [mode, setMode] = useState<"restock" | "reduce">("restock");
  const [operator, setOperator] = useState("");
  const [po, setPo] = useState("");
  const [note, setNote] = useState("");
  const [search, setSearch] = useState("");
  const [activeProduct, setActiveProduct] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [selectedLanguages, setSelectedLanguages] = useState<string[]>([]);
  const [quantity, setQuantity] = useState(1);
  const [remark, setRemark] = useState("");
  const [lines, setLines] = useState<any[]>([]);
  const [review, setReview] = useState(false);
  const productOptions = unique(catalog.restockInventory.map((x: any) => x.category));
  const visibleProducts = productOptions.filter((name: string) => name.toLowerCase().includes(search.toLowerCase()));
  const scoped = catalog.restockInventory.filter((x: any) => x.category === activeProduct);
  const models = unique(scoped.map((x: any) => x.model));
  const languages = unique(scoped.filter((x: any) => !selectedModels.length || selectedModels.includes(x.model)).map((x: any) => x.language));
  const modelMeta = (name: string) => catalog.dimensions.model.find((x: any) => x.name === name) || {};
  const modelGroups = useMemo(() => {
    const groups = new Map<string, string[]>();
    models.forEach((name: string) => {
      const line = String(modelMeta(name).product_line || tr("未分组", "Other"));
      groups.set(line, [...(groups.get(line) || []), name]);
    });
    return [...groups.entries()];
  }, [activeProduct]);
  const toggle = (values: string[], value: string, setter: (next: string[]) => void) => setter(values.includes(value) ? values.filter(x => x !== value) : [...values, value]);
  function openProduct(product: string) {
    const options = catalog.restockInventory.filter((x: any) => x.category === product);
    const nextModels = unique(options.map((x: any) => x.model));
    const nextLanguages = unique(options.map((x: any) => x.language));
    setActiveProduct(product);
    setSelectedModels(nextModels.length === 1 ? nextModels : []);
    setSelectedLanguages(nextLanguages.length === 1 ? nextLanguages : []);
    setQuantity(1); setRemark("");
  }
  function add() {
    if (!activeProduct || !selectedModels.length || !selectedLanguages.length || quantity < 1) return setError(tr("请选择型号、语种并填写数量。", "Select models, languages, and quantity."));
    const options = scoped.filter((x: any) => selectedModels.includes(x.model) && selectedLanguages.includes(x.language));
    if (!options.length) return setError(tr("所选型号和语种之间没有有效物料组合。", "No valid material combinations selected."));
    if (lines.length + options.filter((x: any) => !lines.some((line: any) => line.key === `${x.category}\0${x.model}\0${x.language}`)).length > catalog.maxRestockLines) return setError(`${tr("清单最多添加", "The list supports at most")} ${catalog.maxRestockLines} ${tr("种物料", "materials")}`);
    setLines((current: any[]) => {
      const next = [...current];
      options.forEach((source: any) => {
        const key = `${source.category}\0${source.model}\0${source.language}`;
        const index = next.findIndex(x => x.key === key);
        const item = { key, category_definition: catalog.categories.find((c: any) => c.category === source.category)?.category_definition || "", product: source.category, model: source.model, language: source.language, quantity, remark, snapshot_quantity: source.quantity, snapshot_in_transit: source.in_transit_quantity || 0 };
        if (index >= 0) next[index] = { ...next[index], quantity: next[index].quantity + quantity, remark: remark || next[index].remark };
        else next.push(item);
      });
      return next;
    });
    setActiveProduct("");
    setSuccess(tr("已加入操作清单", "Added to inventory list"));
  }
  async function submit() {
    const label = mode === "reduce" ? tr("减库", "Stock Reduction") : tr("补库", "Restock");
    if (!operator.trim()) return setError(tr("请填写操作人。", "Enter the operator."));
    if (!lines.length) return setError(`${tr("请至少加入一种", "Add at least one material for ")}${label}${tr("物料。", ".")}`);
    setBusy(true); setError("");
    try { const data = await post("/api/admin/restock/submit", { mode, operator, purchase_order_no: po, note, submission_token: token(), lines: lines.map(({ key, ...x }) => x) }); setSuccess(`${label}${tr("任务已进入后台队列", " task queued")}（${data.restockNo}）`); setReview(false); setLines([]); }
    catch (e) { setError(e instanceof Error ? e.message : "提交失败"); } finally { setBusy(false); }
  }
  const total = lines.reduce((sum, x) => sum + Number(x.quantity), 0);
  const modeLabel = mode === "reduce" ? tr("减库", "Stock Reduction") : tr("补库", "Restock");
  return <>
    <Section index="01" title={tr("库存操作信息", "Inventory Operation")} hint={tr("选择补库或减库；两种操作均通过后台队列写入库存流水", "Choose restock or reduction; both are processed by the background queue") }>
      <div className="inventory-mode-switch"><button className={mode === "restock" ? "active" : ""} onClick={() => setMode("restock")}>＋ {tr("补库（增加库存）", "Restock (increase)")}</button><button className={mode === "reduce" ? "active reduce" : ""} onClick={() => setMode("reduce")}>－ {tr("减库（减少库存）", "Reduce (decrease)")}</button></div>
      <div className="form-grid three"><label>{tr("操作人", "Operator")} *<input value={operator} onChange={e => setOperator(e.target.value)} /></label><label>{tr("采购/业务单号", "Reference No.")}<input value={po} onChange={e => setPo(e.target.value)} /></label><label>{tr("操作说明", "Notes")}<input value={note} onChange={e => setNote(e.target.value)} /></label></div>
    </Section>
    <Section index="02" title={`${modeLabel}${tr("物料清单", " Material List")}`} hint={`${tr("按品类卡片选择型号和语种，可同时多选；最多", "Select models and languages from category cards; maximum")} ${catalog.maxRestockLines}`}>
      <div className="restock-toolbar"><input value={search} onChange={e => setSearch(e.target.value)} placeholder={tr("⌕ 输入品类名称搜索", "⌕ Search material categories")} /><strong>{lines.length} {tr("种", "types")} / {total} {tr("件", "items")}</strong><button className="primary" onClick={() => lines.length ? setReview(true) : setError(tr("请先添加操作物料。","Add materials first."))}>{tr("预览", "Review")}{modeLabel}</button></div>
      {lines.length > 0 && (
        <DataTable tr={tr} rows={lines} columns={["product", "model", "language", "snapshot_quantity", "snapshot_in_transit", "quantity", "remark"]} labels={[tr("物料品类","Category"),tr("产品型号","Model"),tr("语种","Language"),tr("缓存库存","Cached Stock"),tr("在途库存","In Transit"),`${modeLabel}${tr("数量"," Qty")}`,tr("备注","Remark")]} onDelete={(i: number) => setLines(lines.filter((_: any, j: number) => i !== j))} onQuantity={(i: number,v: number) => setLines(lines.map((x: any,j: number) => j === i ? {...x,quantity:Math.max(1,v)}:x))}/>
      )}
      <div className="restock-cards">{visibleProducts.map((product: string) => { const category = catalog.categories.find((c: any) => c.category === product); const images = catalog.restockImages?.[product] || []; const modelUrl=catalog.restockModels?.[product]; return <article key={product}>{modelUrl ? <CategoryModelMedia images={images} alt={product} modelUrl={modelUrl} lang={tr("zh","en")} /> : images.length ? <CategoryCarousel images={images} alt={product} previousLabel={tr("查看上一张图片", "View previous image")} nextLabel={tr("查看下一张图片", "View next image")} imageLabel={tr("图片", "Image")} /> : <div className="restock-placeholder">PUDU</div>}<small>{category?.category_definition || tr("物料品类","Material Category")}</small><h3>{product}</h3><button onClick={() => openProduct(product)}>🛒 {tr("选择规格", "Select Options")}</button></article>; })}</div>
    </Section>
    {activeProduct && <div className="overlay restock-overlay" onMouseDown={() => setActiveProduct("")}><div className="modal restock-spec-modal" onMouseDown={e => e.stopPropagation()}><button className="close" onClick={() => setActiveProduct("")}>×</button><h2>{activeProduct}</h2><p>{tr("可同时选择多个型号和多个语种加入操作清单。", "Select multiple models and languages to add to the list.")}</p><div className="restock-selector"><h4>{tr("产品型号", "Product Model")}</h4><div className="restock-model-grid">{modelGroups.map(([line, values]) => <div className="restock-model-line" key={line}><small>{line}</small><div className="restock-pills">{values.map((value: string) => <button className={selectedModels.includes(value) ? "chosen" : ""} onClick={() => toggle(selectedModels,value,setSelectedModels)} key={value}>{modelMeta(value).zh_page_name || value}</button>)}</div></div>)}</div><h4>{tr("语种", "Language")}</h4><div className="restock-pills">{languages.map((value: string) => <button className={selectedLanguages.includes(value) ? "chosen" : ""} onClick={() => toggle(selectedLanguages,value,setSelectedLanguages)} key={value}>{value}</button>)}</div></div><div className="restock-modal-foot"><label>{modeLabel}{tr("数量", " Quantity")}<input type="number" min="1" value={quantity} onChange={e => setQuantity(Math.max(1,+e.target.value))} /></label><label>{tr("备注", "Remark")}<input value={remark} onChange={e => setRemark(e.target.value)} placeholder={tr("可选","Optional")} /></label><button className="primary" onClick={add}>🛒 {tr("加入操作清单", "Add to List")}</button></div></div></div>}
    {review && <Review tr={tr} title={`${modeLabel}${tr("信息确认"," Confirmation")}`} onClose={() => setReview(false)} onSubmit={submit}><p><b>{tr("操作人","Operator")}：</b>{operator}　<b>{tr("业务单号","Reference")}：</b>{po || "-"}</p>{mode === "reduce" && <div className="danger-box">{tr("减库允许产生负库存；提交后将按后台执行时的实时库存计算。", "Reduction may result in negative inventory; final values use live stock at execution time.")}</div>}<DataTable tr={tr} rows={lines.map((x:any) => ({...x,estimated_after: Number(x.snapshot_quantity) + (mode === "reduce" ? -Number(x.quantity) : Number(x.quantity))}))} columns={["product","model","language","snapshot_quantity","quantity","estimated_after"]} labels={[tr("物料品类","Category"),tr("产品型号","Model"),tr("语种","Language"),tr("当前缓存库存","Cached Stock"),`${modeLabel}${tr("数量"," Qty")}`,tr("预计操作后库存","Estimated After")]} /></Review>}
  </>;
}

function DataTable({ rows, columns, labels, onDelete, onQuantity, tr }: any) {
  if (!rows.length) return <div className="empty-box">{tr ? tr("暂无数据", "No data") : "暂无数据"}</div>;
  return <div className="table-wrap"><table className="admin-table"><thead><tr>{labels.map((x: string) => <th key={x}>{x}</th>)}{onDelete && <th/>}</tr></thead><tbody>{rows.map((row: any, i: number) => <tr key={row.record_id || row.key || i}>{columns.map((key: string) => <td key={key}>{key === "quantity" && onQuantity ? <input type="number" min="1" value={row[key]} onChange={e => onQuantity(i,+e.target.value)} /> : String(row[key] ?? "")}</td>)}{onDelete && <td><button className="danger-link" onClick={() => onDelete(i)}>{tr ? tr("删除", "Delete") : "删除"}</button></td>}</tr>)}</tbody></table></div>;
}

function Review({ title, children, onClose, onSubmit, tr, submitDisabled = false, submitLabel }: any) { return <div className="overlay" onMouseDown={onClose}><div className="modal admin-review" onMouseDown={e => e.stopPropagation()}><button className="close" onClick={onClose}>×</button><h2>{title}</h2>{children}<div className="reviewactions"><button onClick={onClose}>{tr ? tr("返回修改", "Back to Edit") : "返回修改"}</button><button className="primary" disabled={submitDisabled} onClick={onSubmit}>{submitLabel || (tr ? tr("确认提交", "Confirm Submit") : "确认提交")}</button></div></div></div>; }

function DimensionManager({ kind, catalog, tr, setBusy, setError, setSuccess }: { kind: Kind; catalog: Catalog; tr: (zh:string,en:string)=>string; setBusy:(value:boolean)=>void; setError:(value:string)=>void; setSuccess:(value:string)=>void }) {
  const labels: Record<Kind,[string,string]> = { model:["型号","Model"], language:["语种","Language"], region:["战区","Region"] };
  const label = tr(...labels[kind]);
  const records = catalog.dimensions[kind];
  const [operation,setOperation] = useState<Operation>("edit");
  const [recordId,setRecordId] = useState(records[0]?.record_id || "");
  const selected = records.find((x:any) => x.record_id === recordId);
  const [name,setName] = useState(selected?.name || "");
  const [status,setStatus] = useState(selected?.status || catalog.statuses[0]);
  const [productLine,setProductLine] = useState(selected?.product_line || "");
  const [modelType,setModelType] = useState(selected?.model_type || catalog.modelTypes[0]);
  const [zhName,setZhName] = useState(selected?.zh_page_name || "");
  const [enName,setEnName] = useState(selected?.en_page_name || "");
  const [query,setQuery] = useState("");
  const inventory = kind === "region" ? catalog.culturalInventory : catalog.inventory;
  const counterpart = kind === "model" ? "language" : "model";
  const currentName = selected?.name || "";
  const existing = new Set<string>(inventory.filter((x:any) => String(kind === "model" ? x.model : kind === "language" ? x.language : x.region) === currentName).map((x:any) => `${x.category}\0${x[counterpart]}`));
  const [selectedKeys,setSelectedKeys] = useState<string[]>([...existing]);
  const categories = catalog.categories.filter((c:any) => kind === "region" ? c.category_definition === "文化周边" : kind === "model" ? !c.no_model : !c.no_language).map((c:any) => c.category);
  const counterparts = unique([...catalog.dimensions[kind === "model" ? "language" : "model"].map((x:any) => x.name), ...inventory.map((x:any) => x[counterpart])]);
  const associations = useMemo(() => categories.flatMap((category:string) => counterparts.map((value:string) => ({category,value,key:`${category}\0${value}`}))).filter((x:any) => !query || `${x.category} ${x.value}`.toLowerCase().includes(query.toLowerCase())),[query,operation,recordId]);
  const [preview,setPreview] = useState<any>(null);
  function selectRecord(id:string) { const x=records.find((r:any)=>r.record_id===id); setRecordId(id); setName(x?.name||""); setStatus(x?.status||catalog.statuses[0]); setProductLine(x?.product_line||""); setModelType(x?.model_type||catalog.modelTypes[0]); setZhName(x?.zh_page_name||x?.name||""); setEnName(x?.en_page_name||x?.name||""); const keys=inventory.filter((r:any)=>String(kind === "model" ? r.model : kind === "language" ? r.language : r.region)===x?.name).map((r:any)=>`${r.category}\0${r[counterpart]}`); setSelectedKeys(unique(keys)); }
  function changeOperation(op:Operation) { setOperation(op); setPreview(null); if(op==="create"){setRecordId("");setName("");setZhName("");setEnName("");setProductLine("");setSelectedKeys([]);} else selectRecord(records[0]?.record_id||""); }
  const draft = { kind, operation, record_id:recordId, old_name:currentName, name, status, product_line:productLine, model_type:modelType, zh_page_name:zhName||name, en_page_name:enName||name, selected_keys:selectedKeys.map(x=>x.split("\0")), submission_token:token() };
  async function makePreview(){ try{setError("");setPreview(await post("/api/admin/dimension/preview",draft));}catch(e){setError(e instanceof Error?e.message:"预览失败");}}
  async function submit(){setBusy(true);try{const data=await post("/api/admin/dimension/submit",preview.draft);setSuccess(`${label}${tr("管理任务已进入后台队列"," task queued")}（${data.taskId}）`);setPreview(null);}catch(e){setError(e instanceof Error?e.message:"提交失败");}finally{setBusy(false);}}
  return <Section index="01" title={`${label}${tr("管理"," Management")}`} hint={`${tr("新增、编辑或删除", "Create, edit, or delete ")}${label}${tr("，提交前需核对全部关联变更。", " and review association changes.")}`}>
    <OperationSwitch value={operation} onChange={changeOperation} tr={tr}/>
    {operation!=="create"&&<label>{tr("选择","Select ")}{label}<select value={recordId} onChange={e=>selectRecord(e.target.value)}>{records.map((x:any)=><option value={x.record_id} key={x.record_id}>{x.name} · {x.status}</option>)}</select></label>}
    {operation==="delete"?<div className="danger-box">{tr(`删除该${label}会同时删除引用它的物料主数据，请在预览后仔细确认。`,`Deleting this ${label} also deletes referencing material rows.`)}</div>:<div className="form-grid four"><label>{label}{tr("名称"," Name")} *<input value={name} onChange={e=>setName(e.target.value)}/></label><label>{tr("启用状态","Status")}<select value={status} onChange={e=>setStatus(e.target.value)}>{catalog.statuses.map((x:string)=><option key={x}>{x}</option>)}</select></label>{kind==="model"&&<><label>{tr("产品线","Product Line")}<input value={productLine} onChange={e=>setProductLine(e.target.value)}/></label><label>{tr("型号类型","Model Type")}<select value={modelType} onChange={e=>setModelType(e.target.value)}>{catalog.modelTypes.map((x:string)=><option key={x}>{x}</option>)}</select></label><label>{tr("中文页面名称","Chinese Display Name")}<input value={zhName} onChange={e=>setZhName(e.target.value)}/></label><label>{tr("英文页面名称","English Display Name")}<input value={enName} onChange={e=>setEnName(e.target.value)}/></label></>}</div>}
    {operation!=="delete"&&<div className="association-box"><h3>{tr(`选择该${label}需要关联的物料组合`,`Select material associations`)}</h3><p>{tr("勾选会新增缺失组合；取消勾选会在确认后删除已有关联行。","Checking creates missing rows; unchecking removes existing associations after confirmation.")}</p><input placeholder={tr("搜索品类或关联维度","Search category or dimension")} value={query} onChange={e=>setQuery(e.target.value)}/><div className="association-list">{associations.map((x:any)=><label key={x.key}><input type="checkbox" checked={selectedKeys.includes(x.key)} onChange={e=>setSelectedKeys(e.target.checked?[...selectedKeys,x.key]:selectedKeys.filter(k=>k!==x.key))}/><span>{x.category}</span><b>{x.value}</b></label>)}</div><small>{tr("已选择","Selected")} {selectedKeys.length} / {categories.length*counterparts.length}</small></div>}
    <div className="admin-actions"><span/><button className="primary" onClick={makePreview}>{tr("预览变更","Preview Changes")}</button></div>
    {preview&&<Review tr={tr} title={tr(`确认${operation==="create"?"新增":operation==="edit"?"修改":"删除"}${label}`,`Confirm ${label}`)} onClose={()=>setPreview(null)} onSubmit={submit}><p><b>{tr("操作","Operation")}：</b>{operation}　<b>{label}：</b>{name}　<b>{tr("启用状态","Status")}：</b>{status}</p>{preview.changes.length?<DataTable tr={tr} rows={preview.changes} columns={["action","category","model","language","region","quantity"]} labels={[tr("操作","Action"),tr("物料品类","Category"),tr("型号","Model"),tr("语种","Language"),tr("战区","Region"),tr("库存","Stock")]}/>:<div className="empty-box">{tr("关联物料组合没有变化，本次只保存基础信息。","No association changes; only base information will be saved.")}</div>}</Review>}
  </Section>;
}

function OperationSwitch({value,onChange,tr}:any){return <div className="operation-switch">{(["create","edit","delete"] as Operation[]).map((x,i)=><button key={x} className={value===x?"active":""} onClick={()=>onChange(x)}>{[tr("＋ 新增","＋ Create"),tr("✎ 编辑","✎ Edit"),tr("－ 删除","－ Delete")][i]}</button>)}</div>}

export function CategoryManager({catalog,tr,setBusy,setError,setSuccess}:any){
  const [operation,setOperation]=useState<Operation>("edit");
  const [categoryId,setCategoryId]=useState(catalog.categories[0]?.record_id||"");
  const selected=catalog.categories.find((x:any)=>x.record_id===categoryId);
  const initial=(x:any)=>({name:x?.category||"",zh:x?.zh_page_name||x?.category||"",en:x?.en_page_name||x?.category||"",definition:x?.category_definition||catalog.categoryDefinitions[0],invoice:x?.commercial_invoice_name||"",packing:x?.packing_list_product_type||catalog.packingTypes[0],status:x?.status||catalog.statuses[0],visible:x?.request_visible||catalog.visibilityOptions[0],price:x?.unit_price??"",customs:x?.customs_code||"",noModel:!!x?.no_model,noLanguage:!!x?.no_language});
  const [form,setForm]=useState(initial(selected)); const [review,setReview]=useState<any>(null);
  const [images,setImages]=useState<CategoryImage[]>(selected?.images||[]);
  const [imagesChanged,setImagesChanged]=useState(false);
  const [expectedImageTokens,setExpectedImageTokens]=useState<string[]>((selected?.images||[]).map((x:CategoryImage)=>x.file_token).filter(Boolean));
  const [imagesUploading,setImagesUploading]=useState(false);
  function updateImages(next:CategoryImage[]){setImages(next);setImagesChanged(true);setReview(null);}
  const rowsFor=(category:any)=>((category?.category_definition==="文化周边"?catalog.culturalInventory:catalog.inventory).filter((x:any)=>x.category===category?.category));
  const sourceRows=rowsFor(selected);
  const allModels=unique(catalog.dimensions.model.map((x:any)=>x.name).filter((x:string)=>x!==catalog.noModelText));
  const allLanguages=unique(catalog.dimensions.language.map((x:any)=>x.name).filter((x:string)=>x!==catalog.noLanguageText));
  const allRegions=unique(catalog.dimensions.region.map((x:any)=>x.name));
  const [models,setModels]=useState(unique(sourceRows.map((x:any)=>x.model).filter((x:string)=>x!==catalog.noModelText)));
  const [languages,setLanguages]=useState(unique(sourceRows.map((x:any)=>x.language).filter((x:string)=>x!==catalog.noLanguageText)));
  const [customModels,setCustomModels]=useState("");
  const [customLanguages,setCustomLanguages]=useState("");
  const [targets,setTargets]=useState<any[]>(sourceRows);
  const [deleteRows,setDeleteRows]=useState<string[]>([]);
  const [deleteScope,setDeleteScope]=useState<CategoryDeleteScope>("material_rows");
  const [deleteConfirmed,setDeleteConfirmed]=useState(false);
  const [deleteCategoryName,setDeleteCategoryName]=useState("");
  function selectCategory(id:string){if(imagesUploading)return;const c=catalog.categories.find((x:any)=>x.record_id===id);const rows=rowsFor(c);setCategoryId(id);setForm(initial(c));setImages(c?.images||[]);setImagesChanged(false);setExpectedImageTokens((c?.images||[]).map((x:CategoryImage)=>x.file_token).filter(Boolean));setModels(unique(rows.map((x:any)=>x.model).filter((x:string)=>x!==catalog.noModelText)));setLanguages(unique(rows.map((x:any)=>x.language).filter((x:string)=>x!==catalog.noLanguageText)));setTargets(rows);setDeleteRows([]);setDeleteScope("material_rows");setReview(null);setDeleteConfirmed(false);setDeleteCategoryName("");setCustomModels("");setCustomLanguages("");}
  function changeOp(op:Operation){if(imagesUploading)return;setOperation(op);setReview(null);if(op==="create"){setCategoryId("");setForm(initial(null));setImages([]);setImagesChanged(false);setExpectedImageTokens([]);setModels([]);setLanguages([]);setTargets([]);setCustomModels("");setCustomLanguages("");}else selectCategory(catalog.categories[0]?.record_id||"");}
  const dimension2=form.definition==="文化周边"?allRegions:allLanguages;
  const selectedDimension2=form.noLanguage&&form.definition!=="文化周边"?[catalog.noLanguageText]:unique([...languages,...(form.definition==="文化周边"?[]:splitValues(customLanguages))]);
  const selectedModels=form.noModel?[catalog.noModelText]:unique([...models,...splitValues(customModels)]);
  const computedTargets=selectedModels.flatMap((model:string)=>selectedDimension2.map((language:string)=>{const old=targets.find((x:any)=>x.model===model&&x.language===language);return {model,language,values:{quantity:Number(old?.quantity||0),unit_price:Number(old?.unit_price ?? form.price ?? 0),customs_code:old?.customs_code||form.customs,remark:old?.remark||"",status:old?.status||form.status,request_visible:old?.request_visible||form.visible}};}));
  function updateTarget(i:number,key:string,value:any){const row=computedTargets[i];const next=targets.filter((x:any)=>!(x.model===row.model&&x.language===row.language));next.push({model:row.model,language:row.language,...row.values,[key]:value});setTargets(next);}
  function previewCategory(){setError("");if(operation==="delete"){try{const draft=categoryDeletePreview(selected?.category||"",sourceRows,deleteRows,deleteScope);setDeleteConfirmed(false);setDeleteCategoryName("");setReview({draft,submission_token:token()});}catch(e){setError(e instanceof Error?e.message:"预览失败");}return;}if(!form.name.trim()||!form.zh.trim()||!form.en.trim()||!form.invoice.trim())return setError(tr("请填写品类名称、中英文页面名称和商业发票产品名称。","Complete category and shipping names."));if(!selectedModels.length||!selectedDimension2.length)return setError(tr("请至少选择一个型号和语种/战区。","Select at least one model and language/region."));setReview(true);}
  async function submit(){setBusy(true);try{let body:any;if(operation==="delete"){if(!review?.draft||!deleteConfirmed||(review.draft.delete_kind==="categories"&&deleteCategoryName!==review.draft.category_names[0]))throw Error(tr("请核对删除明细并完成确认。","Review the deletion details and confirm."));body={operation,submission_token:review.submission_token,draft:{...review.draft,scope_confirmed:true,confirmed_category_name:deleteCategoryName}};}else{const target_values_rows=computedTargets.map((x:any)=>({model:x.model,language:x.language,values:x.values}));const sync_args={old_product:operation==="edit"?selected.category:"",new_product:form.name,no_model:form.noModel,no_language:form.definition==="文化周边"?false:form.noLanguage,target_models:selectedModels,target_languages:selectedDimension2,category_definition:form.definition,category_zh_page_name:form.zh,category_en_page_name:form.en,category_status:form.status,category_request_visible:form.visible,category_unit_price:form.price===""?null:Number(form.price),category_customs_code:form.customs,commercial_invoice_name:form.invoice,packing_list_product_type:form.packing,category_record_id:operation==="edit"?categoryId:"",target_values_rows};body={operation,submission_token:token(),sync_args,draft:{product:form.name,old_product:selected?.category||"",category_definition:form.definition,category_status:form.status,category_request_visible:form.visible,commercial_invoice_name:form.invoice,packing_list_product_type:form.packing,targets:computedTargets}};}if(operation!=="delete"&&imagesChanged){body.category_media={images:images.map(x=>x.local_media_id?{local_media_id:x.local_media_id}:{file_token:x.file_token}),expected_image_tokens:expectedImageTokens};}const data=await post("/api/admin/category/submit",body);setSuccess(`${tr("品类管理任务已进入后台队列","Category task queued")}（${data.taskId}）`);setReview(false);}catch(e){setError(e instanceof Error?e.message:"提交失败");}finally{setBusy(false);}}
  const sourceTotal=sourceRows.reduce((sum:number,row:any)=>sum+Number(row.quantity||0),0);const targetTotal=computedTargets.reduce((sum:number,row:any)=>sum+Number(row.values.quantity||0),0);
  return <Section index="01" title={tr("物料品类管理","Material Category Management")} hint={tr("新增、编辑或删除品类，并在提交前核对全部变更","Create, edit, or delete categories and review all changes")}>
    <OperationSwitch value={operation} onChange={changeOp} tr={tr}/>{operation!=="create"&&<label>{tr("选择物料品类","Select Category")}<select value={categoryId} onChange={e=>selectCategory(e.target.value)}>{catalog.categories.map((x:any)=><option value={x.record_id} key={x.record_id}>{x.category} · {x.status}</option>)}</select></label>}
    {operation==="delete"?<><fieldset className="category-delete-scope"><legend>{tr("删除范围","Deletion Scope")}</legend><label><input type="radio" name="category-delete-scope" checked={deleteScope==="material_rows"} onChange={()=>{setDeleteScope("material_rows");setReview(null);}}/>{tr("仅删除勾选的物料行（保留品类）","Delete selected material rows only (keep category)")}</label><label><input type="radio" name="category-delete-scope" checked={deleteScope==="categories"} onChange={()=>{setDeleteScope("categories");setReview(null);}}/>{tr("删除整个品类及其全部物料行","Delete the entire category and all its material rows")}</label></fieldset><div className="danger-box">{deleteScope==="material_rows"?tr(`已勾选 ${deleteRows.length} / ${sourceRows.length} 行。只删除所选行，未勾选不会删除品类。`,`${deleteRows.length} / ${sourceRows.length} rows selected. Only selected rows will be deleted; the category is kept.`):tr(`将删除整个品类及全部 ${sourceRows.length} 行；预览后还需输入品类名称确认。`,`The entire category and all ${sourceRows.length} rows will be deleted. Type its name in the preview to confirm.`)}</div><div className="association-list delete-list">{sourceRows.map((x:any)=><label key={x.record_id}><input type="checkbox" disabled={deleteScope==="categories"} checked={deleteScope==="categories"||deleteRows.includes(x.record_id)} onChange={e=>setDeleteRows(e.target.checked?[...deleteRows,x.record_id]:deleteRows.filter(id=>id!==x.record_id))}/><span>{x.material_code} · {x.model}</span><b>{x.language} · {x.quantity}</b></label>)}</div></>:<><div className="form-grid four"><label>{tr("物料品类名称","Category Name")} *<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>{tr("中文页面名称","Chinese Display Name")} *<input value={form.zh} onChange={e=>setForm({...form,zh:e.target.value})}/></label><label>{tr("英文页面名称","English Display Name")} *<input value={form.en} onChange={e=>setForm({...form,en:e.target.value})}/></label><label>{tr("品类定义","Definition")}<select value={form.definition} onChange={e=>setForm({...form,definition:e.target.value})}>{catalog.categoryDefinitions.map((x:string)=><option key={x}>{x}</option>)}</select></label><label>{tr("商业发票产品名称","Commercial Invoice Name")} *<input value={form.invoice} onChange={e=>setForm({...form,invoice:e.target.value})}/></label><label>{tr("装箱单产品类型","Packing List Type")}<select value={form.packing} onChange={e=>setForm({...form,packing:e.target.value})}>{catalog.packingTypes.map((x:string)=><option key={x}>{x}</option>)}</select></label><label>{tr("启用状态","Status")}<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>{catalog.statuses.map((x:string)=><option key={x}>{x}</option>)}</select></label><label>{tr("申领页显示","Request Page Visibility")}<select value={form.visible} onChange={e=>setForm({...form,visible:e.target.value})}>{catalog.visibilityOptions.map((x:string)=><option key={x}>{x}</option>)}</select></label><label>{tr("单价（美元）","Unit Price (USD)")}<input type="number" step="0.0001" value={form.price} onChange={e=>setForm({...form,price:e.target.value})}/></label><label>{tr("海关编码","Customs Code")}<input value={form.customs} onChange={e=>setForm({...form,customs:e.target.value})}/></label><label className="check-field"><input type="checkbox" checked={form.noModel} onChange={e=>setForm({...form,noModel:e.target.checked})}/>{tr("该品类无需产品型号","No product model")}</label>{form.definition!=="文化周边"&&<label className="check-field"><input type="checkbox" checked={form.noLanguage} onChange={e=>setForm({...form,noLanguage:e.target.checked})}/>{tr("该品类无需语种","No language")}</label>}</div>{catalog.categoryImagesEnabled&&<CategoryImageEditor key={`${operation}:${categoryId}`} images={images} onChange={updateImages} tr={tr} onBusy={setImagesUploading}/>}<div className="multi-columns"><div><MultiSelect title={tr("产品型号","Models")} options={unique([...allModels,...splitValues(customModels)])} selected={models} setSelected={setModels} disabled={form.noModel}/><label>{tr("新增型号（逗号、分号或换行分隔）","New models (comma, semicolon, or new line)")}<textarea disabled={form.noModel} value={customModels} onChange={e=>setCustomModels(e.target.value)}/></label></div><div><MultiSelect title={form.definition==="文化周边"?tr("战区","Regions"):tr("语种","Languages")} options={unique([...dimension2,...splitValues(customLanguages)])} selected={languages} setSelected={setLanguages} disabled={form.noLanguage&&form.definition!=="文化周边"}/>{form.definition!=="文化周边"&&<label>{tr("新增语种（逗号、分号或换行分隔）","New languages (comma, semicolon, or new line)")}<textarea disabled={form.noLanguage} value={customLanguages} onChange={e=>setCustomLanguages(e.target.value)}/></label>}</div></div><div className="inventory-metrics"><span>{tr("当前库存","Current stock")}<b>{sourceTotal}</b></span><span>{tr("目标库存","Target stock")}<b>{targetTotal}</b></span><span>{tr("库存差额","Difference")}<b className={targetTotal-sourceTotal<0?"negative":""}>{targetTotal-sourceTotal>=0?"+":""}{targetTotal-sourceTotal}</b></span></div><div className="table-wrap"><table className="admin-table"><thead><tr><th>{tr("型号","Model")}</th><th>{form.definition==="文化周边"?tr("战区","Region"):tr("语种","Language")}</th><th>{tr("库存数量","Stock")}</th><th>{tr("单价","Price")}</th><th>{tr("海关编码","Customs")}</th><th>{tr("状态","Status")}</th><th>{tr("申领页显示","Visible")}</th><th>{tr("备注","Remark")}</th></tr></thead><tbody>{computedTargets.map((x:any,i:number)=><tr key={`${x.model}\0${x.language}`}><td>{x.model}</td><td>{x.language}</td><td><input type="number" min="0" value={x.values.quantity} onChange={e=>updateTarget(i,"quantity",+e.target.value)}/></td><td><input type="number" step="0.0001" value={x.values.unit_price} onChange={e=>updateTarget(i,"unit_price",+e.target.value)}/></td><td><input value={x.values.customs_code} onChange={e=>updateTarget(i,"customs_code",e.target.value)}/></td><td><select value={x.values.status} onChange={e=>updateTarget(i,"status",e.target.value)}>{catalog.statuses.map((v:string)=><option key={v}>{v}</option>)}</select></td><td><select value={x.values.request_visible} onChange={e=>updateTarget(i,"request_visible",e.target.value)}>{catalog.visibilityOptions.map((v:string)=><option key={v}>{v}</option>)}</select></td><td><input value={x.values.remark} onChange={e=>updateTarget(i,"remark",e.target.value)}/></td></tr>)}</tbody></table></div></>}
    <div className="admin-actions"><span>{operation!=="delete"&&`${computedTargets.length} ${tr("个目标库存组合","target combinations")}`}</span><button className="primary" disabled={imagesUploading||(operation==="delete"&&deleteScope==="material_rows"&&!deleteRows.length)} onClick={previewCategory}>{tr("预览变更","Preview Changes")}</button></div>{review&&<Review tr={tr} title={operation==="delete"?tr("删除内容确认","Confirm Deletion Details"):tr("品类变更确认","Confirm Category Changes")} onClose={()=>setReview(null)} onSubmit={submit} submitDisabled={operation==="delete"&&(!deleteConfirmed||(review.draft.delete_kind==="categories"&&deleteCategoryName!==review.draft.category_names[0]))} submitLabel={operation==="delete"?tr("确认删除","Confirm Deletion"):undefined}><p><b>{tr("操作","Operation")}：</b>{operation==="delete"?tr("删除","Delete"):operation}　<b>{tr("品类","Category")}：</b>{operation==="delete"?review.draft.category_names[0]:form.name||selected?.category}</p>{operation!=="delete"&&imagesChanged&&<p>{tr(`品类图片：${images.length} 张（已修改）`,`Category images: ${images.length} (changed)`)}</p>}{operation==="delete"?<><p className="danger-box">{review.draft.delete_kind==="material_rows"?tr(`本次仅删除以下 ${review.draft.records.length} 条物料行，保留 ${review.draft.remaining_count} 条，品类记录不会删除。`,`Delete only the ${review.draft.records.length} rows below; keep ${review.draft.remaining_count} rows and the category record.`):tr(`本次删除整个品类及以下全部 ${review.draft.records.length} 条物料行。`,`Delete the entire category and all ${review.draft.records.length} rows below.`)}</p>{review.draft.records.length?<DataTable rows={review.draft.records.map((row:any)=>({...row,in_transit_quantity:row.in_transit_quantity??0}))} columns={["material_code","category","model","language","quantity","in_transit_quantity","unit_price","status"]} labels={[tr("物料编码","Material Code"),tr("品类","Category"),tr("型号","Model"),tr("语种/战区","Language/Region"),tr("库存","Stock"),tr("在途库存","In Transit"),tr("单价","Price"),tr("状态","Status")]}/>:<p>{tr("该品类没有物料行，仅删除品类记录。","This category has no material rows; only its category record will be deleted.")}</p>}<p>{tr("删除不可撤销，执行前会再次核对明细；如数据已变化，本次操作将被拦截。","Deletion is irreversible. Execution rechecks the previewed rows and stops if they have changed.")}</p>{review.draft.delete_kind==="categories"&&<label className="category-delete-name">{tr("请输入完整品类名称以确认整品类删除：","Type the full category name to confirm:")}<b>{review.draft.category_names[0]}</b><input value={deleteCategoryName} onChange={e=>setDeleteCategoryName(e.target.value)} autoComplete="off"/></label>}<label className="category-delete-confirm"><input type="checkbox" checked={deleteConfirmed} onChange={e=>setDeleteConfirmed(e.target.checked)}/>{tr("我已逐项核对以上删除范围和物料明细","I have checked the deletion scope and every material row above")}</label></>:<DataTable tr={tr} rows={computedTargets.map((x:any)=>({model:x.model,language:x.language,...x.values}))} columns={["model","language","quantity","unit_price","status","request_visible"]} labels={[tr("型号","Model"),tr("语种/战区","Language/Region"),tr("库存","Stock"),tr("单价","Price"),tr("状态","Status"),tr("申领页显示","Visible")]}/>}</Review>}
  </Section>;
}

function MultiSelect({title,options,selected,setSelected,disabled}:any){return <div className={`multi-select ${disabled?"disabled":""}`}><h3>{title}</h3><div>{options.map((x:string)=><button key={x} disabled={disabled} className={selected.includes(x)?"chosen":""} onClick={()=>setSelected(selected.includes(x)?selected.filter((v:string)=>v!==x):[...selected,x])}>{x}</button>)}</div></div>}
