import { useEffect, useMemo, useRef, useState } from "react";
import { useDatabaseRefresh } from "./useDatabaseRefresh";
import CategoryCarousel from "./CategoryCarousel";
import { withCurrentUser } from "./identity";
import type { CurrentUser } from "./identity";
import "./corporate-apparel.css";

type User = { open_id: string; name: string; department_ids: string[]; department_paths: string[] };
type Department = { department_id: string; path: string };
type Item = {
  record_id: string;
  product: string;
  size: string;
  code: string;
  available: number;
  images: string[];
};
type Catalog = { products: string[]; items: Item[]; users: User[]; departments: Department[] };
type Line = { product: string; size: string; quantity: number };
type Lang = "zh" | "en";

const reasonValues = ["入职", "销售标配", "OA流程申请（如未提报OA流程，一律驳回，请慎选）"] as const;
type Reason = typeof reasonValues[number] | "";
const reasonLabels: Record<Exclude<Reason, "">, string> = {
  "入职": "New Hire",
  "销售标配": "Standard Sales Kit",
  "OA流程申请（如未提报OA流程，一律驳回，请慎选）": "OA Process Request (Requests without an OA submission will be rejected. Please choose carefully.)",
};

const poloProduct = "休闲商务POLO-黑色（短袖）";
const perProductLimits: Record<string, number> = {
  [poloProduct]: 2,
  "T恤-黑色（短袖）": 1,
  "休闲商务夹克-黑色（长袖）": 1,
  "商务衬衫-黑色（长袖）": 1,
  "冲锋衣-黑色": 1,
};

const productLabels: Record<string, string> = {
  "T恤-黑色（短袖）": "T-Shirt - Black (Short Sleeve)",
  "休闲商务POLO-黑色（短袖）": "Casual Business Polo - Black (Short Sleeve)",
  "休闲商务夹克-黑色（长袖）": "Casual Business Jacket - Black (Long Sleeve)",
  "商务衬衫-黑色（长袖）": "Business Shirt - Black (Long Sleeve)",
  "冲锋衣-黑色": "Windbreaker - Black",
};

const copy = {
  zh: {
    title: "企业文化衫领取", person: "申请人信息", applicant: "申请人",
    applicantPlaceholder: "输入姓名或下拉选择", department: "申请部门",
    reason: "申请事由", reasonPlaceholder: "请选择申请事由",
    departmentPlaceholder: "选择申请人后自动显示", choose: "选择企业文化衫",
    category: "企业文化衫", available: (value: number) => `可领取 ${value} 件`,
    noStock: "暂无库存", selectSize: "选择尺码", cart: "领取清单",
    itemUnit: "件", remove: "删除", submit: "提交领取申请", chooseSize: "请选择尺码",
    remaining: (value: number) => `余 ${value}`, quantity: "领取数量", add: "加入领取清单",
    confirm: "确认领取信息", noDepartment: "未填写部门", back: "返回修改",
    submitting: "正在提交…", confirmSubmit: "确认提交", success: "您的申请已提交",
    queued: (taskId: string) => `申请已进入后台队列（${taskId}）`, loading: "正在加载…",
    stockLoading: "正在核实实时库存，您可以先填写申请人信息…",
    stockFailed: "实时库存读取失败，请重试。", retry: "重试",
    previousImage: "上一张", nextImage: "下一张", image: "图片",
    loadFailed: "页面数据加载失败", selectApplicant: "请选择申请人。",
    selectReason: "请选择申请事由。",
    selectOne: "请至少选择一件企业文化衫。", selectAvailableSize: "请选择有库存的尺码。",
    sizeUnavailable: "该尺码当前已无可领取库存。",
    quantityInvalid: "请输入有效的领取数量。",
    requestLimit: (product: string, limit: number) => `${product} 本次最多选择 ${limit} 件。历史领取数量将在提交后由系统继续校验。`,
    submitFailed: "提交失败",
  },
  en: {
    title: "Corporate Apparel Collection", person: "Applicant Information", applicant: "Applicant",
    applicantPlaceholder: "Type a name or choose from the list", department: "Department",
    reason: "Reason for Request", reasonPlaceholder: "Select a reason",
    departmentPlaceholder: "Shown after selecting an applicant", choose: "Select Corporate Apparel",
    category: "Corporate Apparel", available: (value: number) => `${value} available`,
    noStock: "Out of stock", selectSize: "Select Size", cart: "Collection List",
    itemUnit: "item(s)", remove: "Remove", submit: "Submit Collection Request", chooseSize: "Select a size",
    remaining: (value: number) => `${value} left`, quantity: "Quantity", add: "Add to List",
    confirm: "Confirm Collection Details", noDepartment: "No department", back: "Back to Edit",
    submitting: "Submitting…", confirmSubmit: "Confirm Submission", success: "Your request has been submitted",
    queued: (taskId: string) => `Your request has entered the background queue (${taskId})`, loading: "Loading…",
    stockLoading: "Checking live stock. You can fill in the applicant details first…",
    stockFailed: "Could not load live stock. Please retry.", retry: "Retry",
    previousImage: "Previous image", nextImage: "Next image", image: "Image",
    loadFailed: "Failed to load page data", selectApplicant: "Select an applicant.",
    selectReason: "Select a reason for the request.",
    selectOne: "Select at least one apparel item.", selectAvailableSize: "Select an available size.",
    sizeUnavailable: "This size is no longer available.",
    quantityInvalid: "Enter a valid quantity.",
    requestLimit: (product: string, limit: number) => `${product} is limited to ${limit} item(s) in this request. Historical claims are checked again after submission.`,
    submitFailed: "Submission failed",
  },
};

export default function CorporateApparelPage({ currentUser = null }: { currentUser?: CurrentUser | null }) {
  const [lang, setLang] = useState<Lang>(() => localStorage.getItem("pudu-lang") === "en" ? "en" : "zh");
  const t = copy[lang];
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [liveItems, setLiveItems] = useState<Item[] | null>(null);
  const [stockError, setStockError] = useState(false);
  const [stockBusy, setStockBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [requesterId, setRequesterId] = useState("");
  const [reason, setReason] = useState<Reason>("");
  const [menu, setMenu] = useState(false);
  const [active, setActive] = useState("");
  const [size, setSize] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [lines, setLines] = useState<Line[]>([]);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [submissionToken] = useState(() => crypto.randomUUID().replaceAll("-", ""));
  const requesterTouched = useRef(false);
  useDatabaseRefresh(async()=>{
    const response=await fetch('/api/corporate-apparel-catalog',{cache:'no-store'});
    if(!response.ok)throw Error('目录读取失败');
    setCatalog(await response.json());
    await loadStock();
  });

  useEffect(() => {
    const loadInEnglish = localStorage.getItem("pudu-lang") === "en";
    fetch("/api/corporate-apparel-catalog")
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw Error(loadInEnglish ? copy.en.loadFailed : body.detail || copy.zh.loadFailed);
        return body;
      })
      .then(setCatalog)
      .catch((reason) => setError(reason instanceof Error ? reason.message : loadInEnglish ? copy.en.loadFailed : copy.zh.loadFailed));
    void loadStock();
  }, []);

  async function loadStock() {
    setStockBusy(true);
    setStockError(false);
    try {
      const response = await fetch("/api/corporate-apparel-stock");
      if (!response.ok) throw Error("Live stock unavailable");
      const body = await response.json();
      setLiveItems(body.items as Item[]);
    } catch {
      setStockError(true);
    } finally {
      setStockBusy(false);
    }
  }

  useEffect(() => {
    if (!catalog || !currentUser || currentUser.permission_status === "disabled" || requesterTouched.current || requesterId) return;
    const person = catalog.users.find((item) => item.open_id === currentUser.open_id) || currentUser;
    setRequesterId(person.open_id);
    setQuery(person.name);
  }, [catalog, currentUser, requesterId]);
  const user = catalog?.users.find((item) => item.open_id === requesterId)
    || (currentUser?.open_id === requesterId ? currentUser : undefined);
  const departmentId = user?.department_ids?.[0] || "";
  const department = catalog?.departments.find((item) => item.department_id === departmentId)?.path || user?.department_paths?.[0] || "";
  const users = useMemo(
    () => withCurrentUser(catalog?.users || [], currentUser).filter((item) => !query || `${item.name} ${item.department_paths?.join(" ")}`.toLowerCase().includes(query.toLowerCase())).slice(0, 80),
    [catalog, query, currentUser],
  );
  const activeItems = liveItems?.filter((item) => item.product === active && item.available > 0) || [];
  const productImages = (product: string) => [
    ...new Set(
      (catalog?.items || [])
        .filter((item) => item.product === product)
        .flatMap((item) => item.images || []),
    ),
  ];

  function open(product: string) {
    if (!liveItems) return setError(t.stockFailed);
    const first = liveItems.find((item) => item.product === product && item.available > 0);
    setActive(product);
    setSize(first?.size || "");
    setQuantity(1);
    setError("");
  }

  function changeLang(next: Lang) {
    localStorage.setItem("pudu-lang", next);
    setLang(next);
    setError("");
  }

  function productLabel(product: string) {
    return lang === "en" ? productLabels[product] || product : product;
  }

  function reasonLabel(value: Exclude<Reason, "">) {
    return lang === "en" ? reasonLabels[value] : value;
  }

  function materialUsage() {
    return reason;
  }

  function add() {
    if (!liveItems) return setError(t.stockFailed);
    if (!active || !size) return setError(t.selectAvailableSize);
    const selected = activeItems.find((item) => item.size === size);
    if (!selected || selected.available < 1) return setError(t.sizeUnavailable);
    const requested = active === poloProduct ? Math.trunc(quantity) : 1;
    if (!Number.isFinite(requested) || requested < 1 || requested > selected.available) return setError(t.quantityInvalid);
    const limit = perProductLimits[active] || 1;
    const currentProductTotal = lines.filter((line) => line.product === active).reduce((sum, line) => sum + line.quantity, 0);
    const existing = lines.find((line) => line.product === active && line.size === size);
    if (currentProductTotal + requested > limit) return setError(t.requestLimit(productLabel(active), limit));
    setLines((current) => existing
      ? current.map((line) => line.product === active && line.size === size ? { ...line, quantity: line.quantity + requested } : line)
      : [...current, { product: active, size, quantity: requested }]);
    setActive("");
  }

  async function submit() {
    if (!liveItems) return setError(t.stockFailed);
    if (!user) return setError(t.selectApplicant);
    if (!reason) return setError(t.selectReason);
    if (!lines.length) return setError(t.selectOne);
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/corporate-apparel-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          requester: user.name,
          requester_open_id: user.open_id,
          department,
          department_id: departmentId,
          material_usage: materialUsage(),
          submission_token: submissionToken,
          lines,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw Error(lang === "zh" ? body.detail || t.submitFailed : t.submitFailed);
      setDone(String(body.taskId || ""));
      setReview(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t.submitFailed);
    } finally {
      setBusy(false);
    }
  }

  if (!catalog) return <main className="corporate-loading">{error || t.loading}</main>;
  if (done) return <main className="corporate-success"><div>✓</div><h1>{t.success}</h1><p>{t.queued(done)}</p></main>;
  return (
    <main className="corporate-page">
      <header className="corporate-header">
        <img src="/app-assets/pudu-logo-blue.png" alt="PUDU" />
        <div className="corporate-header-title"><h1>{t.title}</h1></div>
        <div className="corporate-language-switch" role="group" aria-label="Language / 语言">
          <span className={lang === "en" ? "is-en" : ""} aria-hidden="true" />
          <button type="button" className={lang === "zh" ? "active" : ""} onClick={() => changeLang("zh")}>中文</button>
          <button type="button" className={lang === "en" ? "active" : ""} onClick={() => changeLang("en")}>English</button>
        </div>
      </header>

      <section className="corporate-section">
        <div className="corporate-title"><i>01</i><div><h2>{t.person}</h2></div></div>
        <div className="corporate-contact">
          <label>{t.applicant} *
            <div className="corporate-combo">
              <input value={query} placeholder={t.applicantPlaceholder} onFocus={() => setMenu(true)} onChange={(event) => { requesterTouched.current = true; setQuery(event.target.value); setRequesterId(""); setMenu(true); }} />
              <button type="button" onClick={() => setMenu(!menu)}>⌄</button>
              {menu && <div>{users.map((item) => <button type="button" key={item.open_id} onClick={() => { requesterTouched.current = true; setRequesterId(item.open_id); setQuery(item.name); setMenu(false); }}>{item.name} · {item.department_paths?.join("、")}</button>)}</div>}
            </div>
          </label>
          <label>{t.department}<input value={department} readOnly placeholder={t.departmentPlaceholder} /></label>
          <label>{t.reason} *<select value={reason} onChange={(event) => setReason(event.target.value as Reason)}><option value="">{t.reasonPlaceholder}</option>{reasonValues.map((value) => <option value={value} key={value}>{reasonLabel(value)}</option>)}</select></label>
        </div>
      </section>

      <section className="corporate-section">
        <div className="corporate-title"><i>02</i><div><h2>{t.choose}</h2></div></div>
        {!liveItems && <p className="corporate-stock-status" role="status">{stockError ? t.stockFailed : t.stockLoading}{stockError && !stockBusy && <button type="button" onClick={() => void loadStock()}>{t.retry}</button>}</p>}
        <div className="corporate-cards">
          {catalog.products.map((product) => {
            const available = (liveItems || []).filter((item) => item.product === product).reduce((sum, item) => sum + Math.max(0, item.available), 0);
            return <article key={product}>
              {productImages(product).length ? <CategoryCarousel images={productImages(product)} alt={productLabel(product)} previousLabel={t.previousImage} nextLabel={t.nextImage} imageLabel={t.image} /> : <div className="corporate-placeholder">PUDU</div>}
              <div className="corporate-card-copy"><small>{t.category}</small><h3>{productLabel(product)}</h3><span>{!liveItems ? t.stockLoading : available > 0 ? t.available(available) : t.noStock}</span></div>
              <button type="button" disabled={!liveItems || available <= 0} onClick={() => open(product)}>{t.selectSize}</button>
            </article>;
          })}
        </div>
        {lines.length > 0 && <div className="corporate-cart"><h3>{t.cart} · {lines.reduce((sum, line) => sum + line.quantity, 0)} {t.itemUnit}</h3>{lines.map((line) => <div key={`${line.product}\0${line.size}`}><span>{productLabel(line.product)}</span><b>{line.size} × {line.quantity}</b><button type="button" onClick={() => setLines(lines.filter((item) => item.product !== line.product || item.size !== line.size))}>{t.remove}</button></div>)}</div>}
        <button type="button" className="corporate-submit" disabled={!liveItems || !lines.length} onClick={() => { setError(""); setReview(true); }}>{t.submit}</button>
      </section>

      {error && <div className="corporate-toast" role="alert">⚠ {error}<button type="button" onClick={() => setError("")}>×</button></div>}
      {active && <div className="corporate-overlay"><div className="corporate-modal"><button className="corporate-close" onClick={() => setActive("")}>×</button><h2>{productLabel(active)}</h2><p>{t.chooseSize}</p><div className="corporate-sizes">{activeItems.map((item) => <button type="button" className={size === item.size ? "active" : ""} key={item.record_id} onClick={() => { setSize(item.size); setQuantity(1); }}><b>{item.size}</b><span>{t.remaining(item.available)}</span></button>)}</div>{active === poloProduct && <label className="corporate-quantity">{t.quantity}<input type="number" inputMode="numeric" min={1} max={Math.min(2, activeItems.find((item) => item.size === size)?.available || 1)} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></label>}<button type="button" className="corporate-primary" onClick={add}>{t.add}</button></div></div>}
      {review && <div className="corporate-overlay"><div className="corporate-modal corporate-review"><button className="corporate-close" onClick={() => setReview(false)}>×</button><h2>{t.confirm}</h2><p>{user?.name} · {department || t.noDepartment}</p><p><b>{t.reason}：</b>{materialUsage()}</p>{lines.map((line) => <div className="corporate-review-line" key={`${line.product}\0${line.size}`}><span>{productLabel(line.product)}</span><b>{line.size} × {line.quantity}</b></div>)}<div className="corporate-review-actions"><button type="button" onClick={() => setReview(false)}>{t.back}</button><button type="button" className="corporate-primary" disabled={busy} onClick={submit}>{busy ? t.submitting : t.confirmSubmit}</button></div></div></div>}
    </main>
  );
}
