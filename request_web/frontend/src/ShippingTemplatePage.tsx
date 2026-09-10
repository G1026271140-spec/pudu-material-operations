import { useEffect, useMemo, useState } from "react";
import "./shipping.css";

type Lang = "zh" | "en";
type Carton = { id: string; preset: string; length: number; width: number; height: number; gross: number; items: Record<string, number> };
const today = () => new Date().toISOString().slice(0, 10);
const uid = () => crypto.randomUUID();
const poolNames: Record<string, [string, string]> = { "印刷物料": ["印刷物料", "Printed Materials"], "周边礼品": ["周边礼品", "Giveaways"], "文化周边": ["文化周边", "Cultural Merchandise"], "未定义": ["未定义", "Undefined"] };
const estimatePackaging = (cbm: number, gross: number) => Math.max(cbm <= .05 ? 1 : cbm <= .12 ? 2 : 3, gross <= 15 ? 1 : gross <= 30 ? 2 : 3);

export default function ShippingTemplatePage({ catalog, lang }: { catalog: any; lang: Lang }) {
  const tr = (zh: string, en: string) => lang === "zh" ? zh : en;
  const categories = catalog.categories.filter((x: any) => x.record_id);
  const presets = catalog.shipping?.cartonPresets || {};
  const [templateDate, setTemplateDate] = useState(today());
  const [addressCode, setAddressCode] = useState("");
  const [address, setAddress] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [recipient, setRecipient] = useState({ contact: "", company: "", postal_code: "", phone: "", email: "", delivery_term: "", payment_term: "T/T 100% payment in advance" });
  const [cartons, setCartons] = useState<Carton[]>([{ id: uid(), preset: "", length: 0, width: 0, height: 0, gross: 0, items: {} }]);
  const [products, setProducts] = useState<Record<string, any>>({});
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const handle = setTimeout(async () => {
      try {
        const response = await fetch("/api/admin/shipping/invoice-preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template_date: templateDate, address_code: addressCode, address }) });
        const body = await response.json();
        if (response.ok) { if (body.addressCode && body.addressCode !== addressCode) setAddressCode(body.addressCode); setInvoiceNumber(body.invoiceNumber || ""); }
      } catch { /* Preview is non-blocking. */ }
    }, 180);
    return () => clearTimeout(handle);
  }, [templateDate, addressCode, address]);

  const totals = useMemo(() => {
    const result: Record<string, number> = {};
    cartons.forEach(c => Object.entries(c.items).forEach(([id, quantity]) => { result[id] = (result[id] || 0) + Number(quantity || 0); }));
    return result;
  }, [cartons]);
  const selectedIds = Object.keys(totals).filter(id => totals[id] > 0);
  const totalGross = cartons.reduce((sum, c) => sum + c.gross, 0);

  function categoryDefaults(id: string) {
    const category = categories.find((x: any) => x.record_id === id) || {};
    return { invoice_name: category.commercial_invoice_name || category.category || "", packing_name: category.commercial_invoice_name || category.category || "", packing_type: category.packing_list_product_type || "Give aways", unit_price: Number(category.unit_price || 0), customs_code: category.customs_code || "", product_model: "N/A", sku: "/" };
  }
  function product(id: string) { return products[id] || categoryDefaults(id); }
  function updateProduct(id: string, key: string, value: any) { setProducts({ ...products, [id]: { ...product(id), [key]: value } }); }
  function updateCarton(index: number, patch: Partial<Carton>) { setCartons(cartons.map((c, i) => i === index ? { ...c, ...patch } : c)); }
  function applyPreset(index: number, name: string) { const value = presets[name]; updateCarton(index, value ? { preset: name, length: value.length, width: value.width, height: value.height, gross: value.gross_weight } : { preset: "" }); }
  function toggleItem(index: number, id: string) { const carton = cartons[index]; const items = { ...carton.items }; if (items[id]) delete items[id]; else items[id] = 1; updateCarton(index, { items }); }
  function addCarton() { const previous = cartons.at(-1)!; setCartons([...cartons, { ...previous, id: uid(), items: { ...previous.items } }]); }
  function setCartonCount(count: number) { const safe = Math.max(1, Math.min(100, count)); if (safe < cartons.length) setCartons(cartons.slice(0, safe)); else { const next = [...cartons]; while (next.length < safe) { const p = next.at(-1)!; next.push({ ...p, id: uid(), items: { ...p.items } }); } setCartons(next); } }

  async function generate() {
    setError(""); setSuccess("");
    const lines = selectedIds.map(id => ({ line_id: id, ...product(id), quantity: totals[id] }));
    const cartonRows = cartons.map((c, i) => { const cbm = c.length * c.width * c.height / 1_000_000; const packaging = estimatePackaging(cbm, c.gross); return { carton_no: i + 1, carton_quantity: 1, net_weight: Math.max(0, Number((c.gross - packaging).toFixed(3))), gross_weight: c.gross, length_cm: c.length, width_cm: c.width, height_cm: c.height }; });
    const allocations = cartons.flatMap((c, i) => Object.entries(c.items).filter(([, q]) => Number(q) > 0).map(([id, q]) => ({ carton_no: i + 1, line_id: id, quantity: Number(q) })));
    setBusy(true);
    try {
      const response = await fetch("/api/admin/shipping/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template_date: templateDate, address_code: addressCode, recipient: { ...recipient, address }, lines, cartons: cartonRows, allocations }) });
      if (!response.ok) { const body = await response.json(); throw Error(Array.isArray(body.detail) ? body.detail.join("；") : body.detail || "生成失败"); }
      const blob = await response.blob(); const href = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = href; a.download = `${invoiceNumber || "shipping-template"}_INV_PL.xlsx`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(href);
      setSuccess(`${tr("发货模板已生成并开始下载", "Shipping workbook generated and downloading")}：${invoiceNumber}`);
    } catch (e) { setError(e instanceof Error ? e.message : "生成失败"); }
    finally { setBusy(false); }
  }

  return <div className="shipping-page">
    {error && <div className="shipping-toast" onClick={() => setError("")}>{error} ×</div>}
    {success && <div className="shipping-success">✓ {success}</div>}
    <section className="shipping-section"><div className="shipping-section-title"><i>01</i><div><h2>{tr("发票与收件信息", "Invoice & Recipient")}</h2><p>{tr("填写模板日期和收件信息，系统自动生成发票编号", "Complete recipient details and generate the invoice number")}</p></div></div>
      <div className="shipping-grid three"><label>{tr("填写模板日期", "Template Date")}<input type="date" value={templateDate} onChange={e => setTemplateDate(e.target.value)}/></label><label>{tr("国家名称或英文缩写", "Country Name or Code")}<input maxLength={64} placeholder={tr("例如：泰国、Thailand 或 TH", "e.g. Thailand or TH")} value={addressCode} onChange={e => setAddressCode(e.target.value)}/></label><div className="invoice-code"><span>{tr("发票编号（自动）", "Invoice Number")}</span><b>{invoiceNumber || tr("等待填写地址缩写", "Waiting for country code")}</b></div></div>
      <label>{tr("收货地址", "Shipping Address")}<textarea value={address} onChange={e => setAddress(e.target.value)} placeholder={tr("可填写中文或英文地址", "Chinese or English address")}/></label>
      <div className="shipping-grid four"><label>{tr("联系人", "Contact")}<input value={recipient.contact} onChange={e => setRecipient({...recipient,contact:e.target.value})}/></label><label>{tr("公司", "Company")}<input value={recipient.company} onChange={e => setRecipient({...recipient,company:e.target.value})}/></label><label>{tr("邮政编码", "Postal Code")}<input value={recipient.postal_code} onChange={e => setRecipient({...recipient,postal_code:e.target.value})}/></label><label>{tr("电话", "Phone")}<input value={recipient.phone} onChange={e => setRecipient({...recipient,phone:e.target.value})}/></label><label>{tr("邮箱", "Email")}<input value={recipient.email} onChange={e => setRecipient({...recipient,email:e.target.value})}/></label><label>{tr("交货条款", "Delivery Term")}<input value={recipient.delivery_term} onChange={e => setRecipient({...recipient,delivery_term:e.target.value})}/></label><label>{tr("付款条款", "Payment Term")}<input value={recipient.payment_term} onChange={e => setRecipient({...recipient,payment_term:e.target.value})}/></label></div>
    </section>
    <section className="shipping-section"><div className="shipping-section-title"><i>02</i><div><h2>{tr("按箱填写装箱单", "Packing List by Carton")}</h2><p>{tr("先填写每个实际箱子的货物；同一箱内品类不会重复，不同箱子可选择同一品类。", "Enter each physical carton; a category may be split across cartons.")}</p></div></div><label className="carton-count">{tr("实际箱数", "Actual Cartons")}<input type="number" min="1" max="100" value={cartons.length} onChange={e => setCartonCount(Number(e.target.value))}/></label>
      <div className="carton-grid">{cartons.map((carton, index) => { const cbm = carton.length * carton.width * carton.height / 1_000_000; const packaging = estimatePackaging(cbm, carton.gross); const known=["印刷物料","周边礼品","文化周边"]; const grouped = Object.entries(poolNames).map(([definition, labels]) => ({ definition, label: labels[lang === "zh" ? 0 : 1], rows: categories.filter((x: any) => (known.includes(x.category_definition) ? x.category_definition : "未定义") === definition) })).filter(x => x.rows.length); return <article className="carton-card" key={carton.id}><div className="carton-title"><h3>{tr("箱子", "Carton")} {String(index + 1).padStart(2,"0")}</h3><span>{Object.keys(carton.items).length} {tr("品类", "categories")}</span></div><label>{tr("箱型模板（可选）", "Carton Preset (Optional)")}<select value={carton.preset} onChange={e => applyPreset(index,e.target.value)}><option value="">{tr("不使用模板", "No preset")}</option>{Object.entries(presets).map(([name, p]: any) => <option key={name} value={name}>{name} · {p.length}×{p.width}×{p.height} CM · {p.gross_weight} KG</option>)}</select></label><div className="shipping-grid four compact"><label>{tr("长（CM）", "Length (CM)")} *<input type="number" min="0" value={carton.length} onChange={e => updateCarton(index,{length:Number(e.target.value),preset:""})}/></label><label>{tr("宽（CM）", "Width (CM)")} *<input type="number" min="0" value={carton.width} onChange={e => updateCarton(index,{width:Number(e.target.value),preset:""})}/></label><label>{tr("高（CM）", "Height (CM)")} *<input type="number" min="0" value={carton.height} onChange={e => updateCarton(index,{height:Number(e.target.value),preset:""})}/></label><div className="mini-metric">{tr("体积（自动）", "Volume")}<b>{cbm.toFixed(3)} CBM</b></div></div><div className="shipping-grid three compact"><label>{tr("毛重（KG）", "Gross Weight (KG)")} *<input type="number" min="0" step="0.1" value={carton.gross} onChange={e => updateCarton(index,{gross:Number(e.target.value),preset:""})}/></label><div className="mini-metric">{tr("包材重量（自动）", "Packaging Weight")}<b>{packaging} KG</b></div><div className="mini-metric">{tr("净重（自动）", "Net Weight")}<b>{Math.max(0,carton.gross-packaging).toFixed(1)} KG</b></div></div><div className="category-pools">{grouped.map(pool => <div key={pool.definition}><h4>{pool.label}<small>{pool.rows.length}</small></h4><div>{pool.rows.map((category: any) => <button className={carton.items[category.record_id] ? "selected" : ""} key={category.record_id} onClick={() => toggleItem(index,category.record_id)}>{category.zh_page_name || category.category}</button>)}</div></div>)}</div>{Object.entries(carton.items).length ? <div className="carton-items">{Object.entries(carton.items).map(([id, quantity]) => { const category = categories.find((x:any)=>x.record_id===id); const p=product(id); return <div key={id}><span><b>{category?.category}</b><small>{p.packing_name} · {p.packing_type} · {p.customs_code || "-"}</small></span><label>{tr("数量", "Qty")}<input type="number" min="1" value={quantity} onChange={e => updateCarton(index,{items:{...carton.items,[id]:Math.max(1,Number(e.target.value))}})}/></label></div>})}</div> : <div className="shipping-empty">{tr("这个箱子还没有添加物料。", "No materials in this carton.")}</div>}</article>})}</div><button className="add-carton" onClick={addCarton}>＋ {tr("新增箱子（复制上一箱）", "Add Carton (Copy Previous)")}</button>
    </section>
    <section className="shipping-section"><div className="shipping-section-title"><i>03</i><div><h2>{tr("INV 自动汇总", "INV Automatic Summary")}</h2><p>{tr("每个物料品类只生成一行，数量为所有箱子中该品类数量的合计。", "Each category becomes one invoice line, aggregated across cartons.")}</p></div></div>{selectedIds.length ? <div className="invoice-products">{selectedIds.map(id => { const category=categories.find((x:any)=>x.record_id===id); const p=product(id); return <article key={id}><div className="invoice-product-title"><b>{category?.category}</b><span>{tr("汇总数量", "Total Qty")} {totals[id]}</span></div><div className="shipping-grid three"><label>{tr("商业发票产品名称", "Invoice Product Name")}<input value={p.invoice_name} onChange={e=>updateProduct(id,"invoice_name",e.target.value)}/></label><label>{tr("装箱单产品名称", "Packing Product Name")}<input value={p.packing_name} onChange={e=>updateProduct(id,"packing_name",e.target.value)}/></label><label>{tr("装箱单产品类型", "Packing Product Type")}<select value={p.packing_type} onChange={e=>updateProduct(id,"packing_type",e.target.value)}>{catalog.shipping.packingTypes.map((x:string)=><option key={x}>{x}</option>)}</select></label><label>{tr("单价（美元）", "Unit Price (USD)")}<input type="number" min="0" step="0.001" value={p.unit_price} onChange={e=>updateProduct(id,"unit_price",Number(e.target.value))}/></label><label>{tr("海关编码", "Customs Code")}<input value={p.customs_code} onChange={e=>updateProduct(id,"customs_code",e.target.value)}/></label><label>SKU<input value={p.sku} onChange={e=>updateProduct(id,"sku",e.target.value)}/></label><label>Product Model<input value={p.product_model} onChange={e=>updateProduct(id,"product_model",e.target.value)}/></label></div></article>})}</div> : <div className="shipping-empty">{tr("请先在箱内清单中选择物料品类。", "Select material categories in the cartons first.")}</div>}
      <div className="shipping-metrics"><span>{tr("实际箱数", "Cartons")}<b>{cartons.length}</b></span><span>{tr("PL 货物行", "PL Lines")}<b>{cartons.reduce((sum,c)=>sum+Object.keys(c.items).length,0)}</b></span><span>{tr("INV 品类", "INV Categories")}<b>{selectedIds.length}</b></span><span>{tr("货物总数量", "Total Units")}<b>{Object.values(totals).reduce((a,b)=>a+b,0)}</b></span><span>{tr("毛重", "Gross Weight")}<b>{totalGross.toFixed(1)} KG</b></span></div><button className="generate-shipping" onClick={generate}>{tr("生成并下载发货模板 Excel", "Generate & Download Shipping Excel")}</button>
    </section>
    {busy && <div className="shipping-overlay"><i/><b>{tr("正在生成发货模板，请稍后……", "Generating shipping workbook…")}</b><span>{tr("文件只在当前页面生成并下载，不会写入后台队列", "The file is generated for immediate download only")}</span></div>}
  </div>;
}
