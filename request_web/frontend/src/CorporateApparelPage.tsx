import { useEffect, useMemo, useState } from "react";
import CategoryCarousel from "./CategoryCarousel";
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

export default function CorporateApparelPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [requesterId, setRequesterId] = useState("");
  const [menu, setMenu] = useState(false);
  const [active, setActive] = useState("");
  const [size, setSize] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [submissionToken] = useState(() => crypto.randomUUID().replaceAll("-", ""));

  useEffect(() => {
    fetch("/api/corporate-apparel-catalog")
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw Error(body.detail || "页面数据加载失败");
        return body;
      })
      .then(setCatalog)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "页面数据加载失败"));
  }, []);

  const user = catalog?.users.find((item) => item.open_id === requesterId);
  const departmentId = user?.department_ids?.[0] || "";
  const department = catalog?.departments.find((item) => item.department_id === departmentId)?.path || user?.department_paths?.[0] || "";
  const users = useMemo(
    () => (catalog?.users || []).filter((item) => !query || `${item.name} ${item.department_paths?.join(" ")}`.toLowerCase().includes(query.toLowerCase())).slice(0, 80),
    [catalog, query],
  );
  const activeItems = catalog?.items.filter((item) => item.product === active && item.available > 0) || [];
  const productImages = (product: string) => [
    ...new Set(
      (catalog?.items || [])
        .filter((item) => item.product === product)
        .flatMap((item) => item.images || []),
    ),
  ];

  function open(product: string) {
    const first = catalog?.items.find((item) => item.product === product && item.available > 0);
    setActive(product);
    setSize(first?.size || "");
    setError("");
  }

  function add() {
    if (!active || !size) return setError("请选择有库存的尺码。");
    const selected = activeItems.find((item) => item.size === size);
    if (!selected || selected.available < 1) return setError("该尺码当前已无可领取库存。");
    const already = lines.find((line) => line.product === active);
    if (already) return setError("每个品类每次只能选择一个尺码；如需更换，请先删除清单中的品类。");
    setLines((current) => [...current, { product: active, size, quantity: 1 }]);
    setActive("");
  }

  async function submit() {
    if (!user) return setError("请选择申请人。");
    if (!lines.length) return setError("请至少选择一件企业文化衫。");
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
          submission_token: submissionToken,
          lines,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw Error(body.detail || "提交失败");
      setDone(`申请已进入后台队列（${body.taskId}）`);
      setReview(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  if (!catalog) return <main className="corporate-loading">{error || "正在加载…"}</main>;
  if (done) return <main className="corporate-success"><div>✓</div><h1>提交成功</h1><p>{done}</p></main>;
  return (
    <main className="corporate-page">
      <header className="corporate-header">
        <img src="/app-assets/pudu-logo-blue.png" alt="PUDU" />
        <div><small>PUDU 企业文化</small><h1>企业文化衫领取</h1><p>选择申请人、服装品类和尺码，提交后由系统登记领取数量。</p></div>
      </header>

      <section className="corporate-section">
        <div className="corporate-title"><i>01</i><div><h2>申请人信息</h2><p>首次使用的申请人会自动登记为销售权限。</p></div></div>
        <div className="corporate-contact">
          <label>申请人 *
            <div className="corporate-combo">
              <input value={query} placeholder="输入姓名或下拉选择" onFocus={() => setMenu(true)} onChange={(event) => { setQuery(event.target.value); setRequesterId(""); setMenu(true); }} />
              <button type="button" onClick={() => setMenu(!menu)}>⌄</button>
              {menu && <div>{users.map((item) => <button type="button" key={item.open_id} onClick={() => { setRequesterId(item.open_id); setQuery(item.name); setMenu(false); }}>{item.name} · {item.department_paths?.join("、")}</button>)}</div>}
            </div>
          </label>
          <label>申请部门<input value={department} readOnly placeholder="选择申请人后自动显示" /></label>
        </div>
      </section>

      <section className="corporate-section">
        <div className="corporate-title"><i>02</i><div><h2>选择企业文化衫</h2><p>POLO 和夹克与文化周边申领共用个人领取上限；其余品类每人最多 1 件。</p></div></div>
        <div className="corporate-cards">
          {catalog.products.map((product) => {
            const available = catalog.items.filter((item) => item.product === product).reduce((sum, item) => sum + Math.max(0, item.available), 0);
            return <article key={product}>
              {productImages(product).length ? <CategoryCarousel images={productImages(product)} alt={product} previousLabel="上一张" nextLabel="下一张" imageLabel="图片" /> : <div className="corporate-placeholder">PUDU</div>}
              <div className="corporate-card-copy"><small>企业文化衫</small><h3>{product}</h3><span>{available > 0 ? `可领取 ${available} 件` : "暂无库存"}</span></div>
              <button type="button" disabled={available <= 0} onClick={() => open(product)}>选择尺码</button>
            </article>;
          })}
        </div>
        {lines.length > 0 && <div className="corporate-cart"><h3>领取清单 · {lines.length} 件</h3>{lines.map((line) => <div key={line.product}><span>{line.product}</span><b>{line.size}</b><button type="button" onClick={() => setLines(lines.filter((item) => item.product !== line.product))}>删除</button></div>)}</div>}
        <button type="button" className="corporate-submit" disabled={!lines.length} onClick={() => { setError(""); setReview(true); }}>提交领取申请</button>
      </section>

      {error && <div className="corporate-toast" role="alert">⚠ {error}<button type="button" onClick={() => setError("")}>×</button></div>}
      {active && <div className="corporate-overlay"><div className="corporate-modal"><button className="corporate-close" onClick={() => setActive("")}>×</button><h2>{active}</h2><p>请选择尺码</p><div className="corporate-sizes">{activeItems.map((item) => <button type="button" className={size === item.size ? "active" : ""} key={item.record_id} onClick={() => setSize(item.size)}><b>{item.size}</b><span>余 {item.available}</span></button>)}</div><button type="button" className="corporate-primary" onClick={add}>加入领取清单</button></div></div>}
      {review && <div className="corporate-overlay"><div className="corporate-modal corporate-review"><button className="corporate-close" onClick={() => setReview(false)}>×</button><h2>确认领取信息</h2><p>{user?.name} · {department || "未填写部门"}</p>{lines.map((line) => <div className="corporate-review-line" key={line.product}><span>{line.product}</span><b>{line.size} × 1</b></div>)}<div className="corporate-review-actions"><button type="button" onClick={() => setReview(false)}>返回修改</button><button type="button" className="corporate-primary" disabled={busy} onClick={submit}>{busy ? "正在提交…" : "确认提交"}</button></div></div></div>}
    </main>
  );
}
