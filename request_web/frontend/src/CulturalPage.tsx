import { useEffect, useMemo, useState } from "react";
import CategoryCarousel from "./CategoryCarousel";

type Lang = "zh" | "en";
type User = {
  open_id: string;
  name: string;
  department_ids: string[];
  department_paths: string[];
};
type Department = { department_id: string; name: string; path: string };
type Combination = {
  product: string;
  model: string;
  region: string;
  stock: number;
  unitPriceRmb: number;
};
type Catalog = {
  combinations: Combination[];
  images: Record<string, string[]>;
  categoryLabels: Record<string, { zh?: string; en?: string }>;
  users: User[];
  departments: Department[];
  maxCulturalShirtQuantity: number;
  maxJacketQuantity: number;
};
type Line = {
  product: string;
  model: string;
  region: string;
  quantity: number;
  remark: string;
};

const c = {
  zh: {
    title: "文化周边申领",
    kicker: "文化周边工作台",
    subtitle: "选择文化周边、尺码和战区，提交后直接登记发放。",
    person: "申请人信息",
    personHint: "选择本次文化周边的申请人",
    applicant: "申请人",
    input: "填写中文名称",
    department: "申请部门",
    usage: "文化衫用途（请填写展会名称）",
    usagePlaceholder: "请填写展会名称",
    choose: "选择文化周边",
    chooseHint:
      "选择品类、尺码和战区并加入申领车；文化衫每人累计最多 2 件，文化夹克每人累计最多 1 件。",
    spec: "选择规格",
    size: "尺码",
    region: "战区",
    regionHint: "如无法确定战区，请选择您所参加活动所在的地区即可。",
    quantity: "数量",
    remark: "备注",
    add: "加入申领车",
    cart: "已选文化周边",
    submit: "提交文化周边申请",
    confirm: "文化周边申请确认",
    confirmHint: "提交后将直接登记发放并扣减库存",
    back: "返回修改",
    final: "确认提交",
    success: "提交成功",
    successHint: "申请已进入后台队列",
    empty: "当前没有文化周边库存数据。",
    jacketNoticeTitle: "文化夹克申领提示",
    jacketNotice: "技术岗同学如参加展会可申领polo，市场部暂无夹克库存哦，请勿申领~",
    poloNoticeTitle: "文化POLO衫申领提示",
    poloNotice: "销售同学可直接联系刘如蓓领取适合自己尺码的polo",
    jacketNoticeCancel: "取消",
    jacketNoticeConfirm: "我已知晓，继续申领",
    viewSizeChart: "查看尺码表",
    sizeChartHint: "点击图片可放大，手机端可左右滑动查看完整尺码表。",
    sizeChartClose: "关闭尺码表",
  },
  en: {
    title: "Cultural Merchandise Request",
    kicker: "Cultural Merchandise Workspace",
    subtitle:
      "Select merchandise, size and region, then submit for direct issuance.",
    person: "Applicant Information",
    personHint: "Select the applicant for this request",
    applicant: "Applicant",
    input: "Type a name",
    department: "Department",
    usage: "Cultural Apparel Usage (Exhibition Name)",
    usagePlaceholder: "Enter the exhibition name",
    choose: "Select Merchandise",
    chooseHint:
      "Choose a product, size and region. Each applicant may claim up to 2 shirts and 1 jacket cumulatively.",
    spec: "Select Options",
    size: "Size",
    region: "Region",
    regionHint: "If unsure, select the region where your event takes place.",
    quantity: "Quantity",
    remark: "Remarks",
    add: "Add to Cart",
    cart: "Selected Merchandise",
    submit: "Submit Cultural Request",
    confirm: "Confirm Cultural Request",
    confirmHint:
      "Submitting will issue the items and deduct inventory directly.",
    back: "Back to Edit",
    final: "Confirm Submit",
    success: "Submitted",
    successHint: "The request has entered the background queue",
    empty: "No cultural merchandise inventory is available.",
    jacketNoticeTitle: "Cultural Jacket Notice",
    jacketNotice:
      "Technical colleagues attending exhibitions may request a polo shirt. Marketing currently has no jacket inventory, so please do not request one.",
    poloNoticeTitle: "Cultural Polo Shirt Notice",
    poloNotice:
      "Sales colleagues can contact Liu Rubei directly to collect a polo shirt in a suitable size.",
    jacketNoticeCancel: "Cancel",
    jacketNoticeConfirm: "Understood, Continue",
    viewSizeChart: "View Size Chart",
    sizeChartHint:
      "Tap the image to enlarge it. Swipe horizontally on mobile to view the full chart.",
    sizeChartClose: "Close size chart",
  },
};

const CULTURAL_POLO = "文化POLO衫";
const CULTURAL_JACKET = "文化夹克";
const SIZE_CHARTS: Record<string, string> = {
  [CULTURAL_POLO]: "/app-assets/cultural-polo-size-chart.jpg",
  [CULTURAL_JACKET]: "/app-assets/cultural-jacket-size-chart.jpg",
};

export default function CulturalPage({ lang }: { lang: Lang }) {
  const t = c[lang];
  const [catalog, setCatalog] = useState<Catalog | null>(null),
    [error, setError] = useState("");
  const [requesterId, setRequesterId] = useState(""),
    [query, setQuery] = useState(""),
    [menu, setMenu] = useState(false),
    [materialUsage, setMaterialUsage] = useState("");
  const [active, setActive] = useState<string | null>(null),
    [model, setModel] = useState(""),
    [region, setRegion] = useState(""),
    [quantity, setQuantity] = useState(1),
    [remark, setRemark] = useState("");
  const [lines, setLines] = useState<Line[]>([]),
    [review, setReview] = useState(false),
    [productNotice, setProductNotice] = useState<string | null>(null),
    [sizeChartProduct, setSizeChartProduct] = useState<string | null>(null),
    [sizeChartZoomed, setSizeChartZoomed] = useState(false),
    [busy, setBusy] = useState(false),
    [done, setDone] = useState("");
  const [submissionToken] = useState(() => crypto.randomUUID().replaceAll("-", ""));
  useEffect(() => {
    fetch("/api/cultural-catalog")
      .then((r) => r.json())
      .then(setCatalog)
      .catch((e) => setError(e.message));
  }, []);
  const user = catalog?.users.find((u) => u.open_id === requesterId);
  const departmentId = user?.department_ids?.[0] || "";
  const department =
    catalog?.departments.find((d) => d.department_id === departmentId)?.path ||
    user?.department_paths?.[0] ||
    "";
  const users = useMemo(
    () =>
      (catalog?.users || [])
        .filter(
          (u) =>
            !query ||
            `${u.name} ${u.department_paths?.join(" ")}`
              .toLocaleLowerCase()
              .includes(query.toLocaleLowerCase()),
        )
        .slice(0, 80),
    [catalog, query],
  );
  const products = [
    ...new Set(catalog?.combinations.map((x) => x.product) || []),
  ];
  const options =
    catalog?.combinations.filter((x) => x.product === active) || [];
  const models = [...new Set(options.map((x) => x.model))];
  const regions = [
    ...new Set(
      options.filter((x) => !model || x.model === model).map((x) => x.region),
    ),
  ];
  const total = lines.reduce((sum, line) => sum + line.quantity, 0);
  const jacketTotal = lines
    .filter((line) => line.product === "文化夹克")
    .reduce((sum, line) => sum + line.quantity, 0);
  const culturalShirtTotal = total - jacketTotal;
  function open(product: string) {
    const scoped =
      catalog?.combinations.filter((x) => x.product === product) || [];
    setActive(product);
    setModel(scoped[0]?.model || "");
    setRegion(scoped[0]?.region || "");
    setQuantity(1);
    setRemark("");
  }
  function requestOpen(product: string) {
    if (product === CULTURAL_JACKET || product === CULTURAL_POLO) {
      setProductNotice(product);
      return;
    }
    open(product);
  }
  function closeSizeChart() {
    setSizeChartProduct(null);
    setSizeChartZoomed(false);
  }
  function add() {
    if (!active || !model || !region)
      return setError(
        lang === "zh" ? "请选择尺码和战区。" : "Select a size and region.",
      );
    const isJacket = active === "文化夹克";
    const bucketTotal = isJacket ? jacketTotal : culturalShirtTotal;
    const bucketLimit = isJacket
      ? catalog?.maxJacketQuantity || 1
      : catalog?.maxCulturalShirtQuantity || 2;
    if (bucketTotal + quantity > bucketLimit)
      return setError(
        lang === "zh"
          ? isJacket
            ? "每位申请人累计最多申领 1 件文化夹克。"
            : "每位申请人累计最多申领 2 件文化衫。"
          : isJacket
            ? "Each applicant may claim up to 1 jacket."
            : "Each applicant may claim up to 2 shirts.",
      );
    const key = `${active}\0${model}\0${region}`;
    setLines((old) => {
      const found = old.findIndex(
        (x) => `${x.product}\0${x.model}\0${x.region}` === key,
      );
      if (found < 0)
        return [...old, { product: active, model, region, quantity, remark }];
      return old.map((x, i) =>
        i === found
          ? {
              ...x,
              quantity: x.quantity + quantity,
              remark: remark || x.remark,
            }
          : x,
      );
    });
    setActive(null);
  }
  async function submit() {
    if (!user)
      return setError(
        lang === "zh" ? "请选择申请人。" : "Select an applicant.",
      );
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/cultural-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          requester: user.name,
          requester_open_id: user.open_id,
          department,
          department_id: departmentId,
          material_usage: materialUsage.trim(),
          submission_token: submissionToken,
          lines,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw Error(body.detail || "Submit failed");
      setDone(`${t.successHint} (${body.taskId})`);
      setReview(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setBusy(false);
    }
  }
  if (!catalog) return <main className="loading">{error || "Loading…"}</main>;
  if (done)
    return (
      <main className="success">
        <div>✓</div>
        <h1>{t.success}</h1>
        <p>{done}</p>
      </main>
    );
  return (
    <main className="cultural-page">
      <div className="legacy-page-header">
        <div>
          <small>{t.kicker}</small>
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>
        </div>
        <button>
          ↻&nbsp; {lang === "zh" ? "刷新本页数据" : "Refresh page data"}
        </button>
      </div>
      <section>
        <div className="section-title">
          <i>01</i>
          <div>
            <h2>{t.person}</h2>
            <p>{t.personHint}</p>
          </div>
        </div>
        <div className="culture-contact">
          <label>
            {t.applicant} *
            <div className="combobox">
              <input
                value={query}
                placeholder={t.input}
                onFocus={() => setMenu(true)}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setRequesterId("");
                  setMenu(true);
                }}
              />
              <button onClick={() => setMenu(!menu)}>⌄</button>
              {menu && (
                <div className="combo-menu">
                  {users.map((u) => (
                    <button
                      key={u.open_id}
                      onClick={() => {
                        setRequesterId(u.open_id);
                        setQuery(u.name);
                        setMenu(false);
                      }}
                    >
                      {u.name} · {u.department_paths?.join("、")}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </label>
          <label>
            {t.department}
            <input value={department} readOnly />
          </label>
          <label className="culture-usage">
            {t.usage} *
            <input
              value={materialUsage}
              maxLength={500}
              placeholder={t.usagePlaceholder}
              onChange={(e) => setMaterialUsage(e.target.value)}
            />
          </label>
        </div>
      </section>
      <section>
        <div className="section-title">
          <i>02</i>
          <div>
            <h2>{t.choose}</h2>
            <p>{t.chooseHint}</p>
          </div>
        </div>
        {!products.length ? (
          <p>{t.empty}</p>
        ) : (
          <div className="culture-cards">
            {products.map((product) => (
              <article key={product}>
                {catalog.images[product]?.length ? (
                  <CategoryCarousel
                    images={catalog.images[product]}
                    alt={catalog.categoryLabels[product]?.[lang] || product}
                    previousLabel={lang === "zh" ? "查看上一张图片" : "View previous image"}
                    nextLabel={lang === "zh" ? "查看下一张图片" : "View next image"}
                    imageLabel={lang === "zh" ? "图片" : "Image"}
                  />
                ) : (
                  <div className="placeholder">PUDU</div>
                )}
                <h3>
                  {catalog.categoryLabels[product]?.[lang] ||
                    (lang === "en" && product === "文化夹克"
                      ? "Cultural Jacket"
                      : product)}
                </h3>
                <button onClick={() => requestOpen(product)}>♧ {t.spec}</button>
              </article>
            ))}
          </div>
        )}
        {lines.length > 0 && (
          <div className="culture-cart">
            <h3>
              {t.cart} · {total}
            </h3>
            {lines.map((line, i) => (
              <div
                className="culture-line"
                key={`${line.product}${line.model}${line.region}`}
              >
                <span>{line.product}</span>
                <span>{line.model}</span>
                <span>{line.region}</span>
                <input
                  type="number"
                  min="1"
                  max={line.product === "文化夹克" ? catalog.maxJacketQuantity : catalog.maxCulturalShirtQuantity}
                  value={line.quantity}
                  onChange={(e) =>
                    setLines(
                      lines.map((x, j) =>
                        j === i
                          ? {
                              ...x,
                              quantity: Math.max(
                                1,
                                Math.min(
                                  x.product === "文化夹克"
                                    ? catalog.maxJacketQuantity
                                    : catalog.maxCulturalShirtQuantity,
                                  +e.target.value || 1,
                                ),
                              ),
                            }
                          : x,
                      ),
                    )
                  }
                />
                <button
                  onClick={() => setLines(lines.filter((_, j) => j !== i))}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        <button
          className="primary culture-submit"
          disabled={!lines.length}
          onClick={() => {
            if (!user)
              setError(
                lang === "zh" ? "请选择申请人。" : "Select an applicant.",
              );
            else if (!materialUsage.trim())
              setError(
                lang === "zh"
                  ? "请填写文化衫用途（展会名称）。"
                  : "Enter the cultural apparel usage (exhibition name).",
              );
            else setReview(true);
          }}
        >
          {t.submit}
        </button>
      </section>
      {error && (
        <div className="toast" onClick={() => setError("")}>
          {error} ×
        </div>
      )}
      {productNotice && (
        <div
          className="overlay jacket-notice-overlay"
          onMouseDown={() => setProductNotice(null)}
        >
          <div
            className="modal jacket-notice"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="jacket-notice-title"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              aria-label={t.jacketNoticeCancel}
              onClick={() => setProductNotice(null)}
            >
              ×
            </button>
            <div className="jacket-notice-mark" aria-hidden="true">!</div>
            <h2 id="jacket-notice-title">
              {productNotice === CULTURAL_JACKET
                ? t.jacketNoticeTitle
                : t.poloNoticeTitle}
            </h2>
            <p>
              {productNotice === CULTURAL_JACKET
                ? t.jacketNotice
                : t.poloNotice}
            </p>
            <div className="jacket-notice-actions">
              <button onClick={() => setProductNotice(null)}>
                {t.jacketNoticeCancel}
              </button>
              <button
                className="jacket-notice-confirm"
                onClick={() => {
                  const product = productNotice;
                  setProductNotice(null);
                  if (product) open(product);
                }}
              >
                {t.jacketNoticeConfirm}
              </button>
            </div>
          </div>
        </div>
      )}
      {active && !sizeChartProduct && (
        <div className="overlay" onMouseDown={() => setActive(null)}>
          <div
            className="modal cultural-modal"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <button className="close" onClick={() => setActive(null)}>
              ×
            </button>
            <h2>{active}</h2>
            {SIZE_CHARTS[active] && (
              <button
                type="button"
                className="size-chart-trigger"
                onClick={() => setSizeChartProduct(active)}
              >
                {t.viewSizeChart}
              </button>
            )}
            <h4>{t.size}</h4>
            <div className="pills">
              {models.map((x) => (
                <button
                  className={model === x ? "chosen" : ""}
                  onClick={() => {
                    setModel(x);
                    const first = options.find((o) => o.model === x);
                    setRegion(first?.region || "");
                  }}
                  key={x}
                >
                  {x}
                </button>
              ))}
            </div>
            <h4>{t.region}</h4>
            <p className="region-hint">{t.regionHint}</p>
            <div className="pills">
              {regions.map((x) => (
                <button
                  className={region === x ? "chosen" : ""}
                  onClick={() => setRegion(x)}
                  key={x}
                >
                  {x}
                </button>
              ))}
            </div>
            <div className="modalfoot">
              <label>
                {t.quantity}
                <input
                  type="number"
                  min="1"
                  max={active === "文化夹克" ? catalog.maxJacketQuantity : catalog.maxCulturalShirtQuantity}
                  value={quantity}
                  onChange={(e) =>
                    setQuantity(
                      Math.max(
                        1,
                        Math.min(
                          active === "文化夹克"
                            ? catalog.maxJacketQuantity
                            : catalog.maxCulturalShirtQuantity,
                          +e.target.value || 1,
                        ),
                      ),
                    )
                  }
                />
              </label>
              <label>
                {t.remark}
                <input
                  value={remark}
                  onChange={(e) => setRemark(e.target.value)}
                />
              </label>
              <button className="primary" onClick={add}>
                {t.add}
              </button>
            </div>
          </div>
        </div>
      )}
      {sizeChartProduct && SIZE_CHARTS[sizeChartProduct] && (
        <div className="overlay size-chart-overlay" onMouseDown={closeSizeChart}>
          <div
            className="modal size-chart-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="size-chart-title"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <button
              className="close"
              aria-label={t.sizeChartClose}
              onClick={closeSizeChart}
            >
              ×
            </button>
            <h2 id="size-chart-title">
              {lang === "zh"
                ? `${sizeChartProduct}尺码表`
                : sizeChartProduct === CULTURAL_JACKET
                  ? "Cultural Jacket Size Chart"
                  : "Cultural Polo Shirt Size Chart"}
            </h2>
            <p className="size-chart-hint">{t.sizeChartHint}</p>
            <div className="size-chart-scroll">
              <button
                type="button"
                className="size-chart-image-button"
                onClick={() => setSizeChartZoomed((value) => !value)}
                aria-label={t.viewSizeChart}
              >
                <img
                  className={sizeChartZoomed ? "zoomed" : ""}
                  src={SIZE_CHARTS[sizeChartProduct]}
                  alt={
                    lang === "zh"
                      ? `${sizeChartProduct}尺码表`
                      : "Size chart"
                  }
                />
              </button>
            </div>
          </div>
        </div>
      )}
      {review && (
        <div className="overlay">
          <div className="modal review">
            <button className="close" onClick={() => setReview(false)}>
              ×
            </button>
            <h2>{t.confirm}</h2>
            <p>{t.confirmHint}</p>
            <div className="reviewgrid">
              <p>
                {t.applicant}
                <b>{user?.name}</b>
              </p>
              <p>
                {t.department}
                <b>{department}</b>
              </p>
              <p className="review-usage">
                {t.usage}
                <b>{materialUsage.trim()}</b>
              </p>
            </div>
            <table>
              <tbody>
                {lines.map((line) => (
                  <tr key={`${line.product}${line.model}${line.region}`}>
                    <td>{line.product}</td>
                    <td>{line.model}</td>
                    <td>{line.region}</td>
                    <td>{line.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="reviewactions">
              <button onClick={() => setReview(false)}>{t.back}</button>
              <button className="primary" onClick={submit}>
                {t.final}
              </button>
            </div>
          </div>
        </div>
      )}
      {busy && (
        <div className="submit-overlay">
          <div className="spinner"></div>
          <strong>
            {lang === "zh"
              ? "正在提交数据，请稍后……"
              : "Submitting, please wait…"}
          </strong>
        </div>
      )}
    </main>
  );
}
