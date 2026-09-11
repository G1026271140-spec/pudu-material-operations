import { useEffect, useMemo, useState } from "react";

type Option = {
  materialCode: string;
  model: string;
  modelDisplay: string;
  productLine: string;
  language: string;
  stock: number;
  unitPriceRmb: number;
};
type Product = {
  name: string;
  nameDisplay?: { zh?: string; en?: string };
  image?: string;
  options: Option[];
};
type User = {
  open_id: string;
  name: string;
  department_ids: string[];
  department_paths: string[];
};
type Department = { department_id: string; name: string; path: string };
type Catalog = {
  generatedAt: string;
  products: Product[];
  users: User[];
  departments: Department[];
  rolesByUser: Record<string, string[]>;
  reasons: string[];
};
type Line = {
  product: string;
  model: string;
  language: string;
  quantity: number;
  remark: string;
  current_stock: number;
  inventory_status: string;
  unitPriceRmb: number;
};

const clean = (value: string) =>
  value.replace(/\([^)]*\)|（[^）]*）/g, "").trim();

export default function App({ lang = "zh" }: { lang?: "zh" | "en" }) {
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const [catalog, setCatalog] = useState<Catalog | null>(null),
    [error, setError] = useState(""),
    [search, setSearch] = useState("");
  const [active, setActive] = useState<Product | null>(null),
    [cartOpen, setCartOpen] = useState(false),
    [review, setReview] = useState(false),
    [busy, setBusy] = useState(false),
    [done, setDone] = useState("");
  const [requesterId, setRequesterId] = useState(""),
    [requesterQuery, setRequesterQuery] = useState(""),
    [requesterOpen, setRequesterOpen] = useState(false),
    [customer, setCustomer] = useState(""),
    [country, setCountry] = useState(""),
    [recipient, setRecipient] = useState(""),
    [usage, setUsage] = useState(""),
    [reason, setReason] = useState(""),
    [date, setDate] = useState("");
  const [submissionToken] = useState(() => crypto.randomUUID().replaceAll("-", ""));
  const [selectedModels, setSelectedModels] = useState<string[]>([]),
    [selectedLanguages, setSelectedLanguages] = useState<string[]>([]),
    [qty, setQty] = useState(1),
    [remark, setRemark] = useState(""),
    [lines, setLines] = useState<Line[]>([]);
  useEffect(() => {
    fetch("/api/catalog")
      .then((r) => {
        if (!r.ok) throw Error("目录加载失败");
        return r.json();
      })
      .then(setCatalog)
      .catch((e) => setError(e.message));
  }, []);
  const user = catalog?.users.find((u) => u.open_id === requesterId);
  const depId = user?.department_ids?.[0] || "";
  const dep = catalog?.departments.find((d) => d.department_id === depId);
  const department =
    dep?.path || dep?.name || user?.department_paths?.[0] || "";
  const requesterOptions = useMemo(() => {
    const q = requesterQuery.trim().toLocaleLowerCase();
    return (catalog?.users || [])
      .filter(
        (u) =>
          !q ||
          `${u.name} ${u.department_paths?.join(" ")}`
            .toLocaleLowerCase()
            .includes(q),
      )
      .slice(0, 80);
  }, [catalog, requesterQuery]);
  const requesterLabel = (u: User) =>
    `${u.name}${u.department_paths?.length ? ` · ${u.department_paths.join("、")}` : ""}`;
  function chooseRequester(u: User) {
    setRequesterId(u.open_id);
    setRequesterQuery(u.name);
    setRequesterOpen(false);
  }
  const total = lines.reduce((s, l) => s + l.quantity * l.unitPriceRmb, 0),
    count = lines.reduce((s, l) => s + l.quantity, 0);
  const products =
    catalog?.products.filter((p) =>
      p.name.toLowerCase().includes(search.toLowerCase()),
    ) || [];
  const models = useMemo(
    () => [...new Set(active?.options.map((o) => o.model || "无需型号") || [])],
    [active],
  );
  const modelMeta = useMemo(
    () =>
      new Map(
        active?.options.map((o) => [
          o.model || "无需型号",
          {
            line: o.productLine || "未分组",
            display: o.modelDisplay || o.model,
          },
        ]) || [],
      ),
    [active],
  );
  const modelGroups = useMemo(() => {
    const order = ["IR", "CR", "SR", "GR"];
    const groups = new Map<string, string[]>();
    models.forEach((model) => {
      const line = modelMeta.get(model)?.line || "未分组";
      groups.set(line, [...(groups.get(line) || []), model]);
    });
    if (groups.size < 2) return [["", models] as [string, string[]]];
    return [
      ...order
        .filter((line) => groups.get(line)?.length)
        .map((line) => [line, groups.get(line)!] as [string, string[]]),
      ...[...groups].filter(([line]) => !order.includes(line)),
    ];
  }, [models, modelMeta]);
  const modelColumns = useMemo(() => {
    const columnCount =
      modelGroups.length > 1 ? Math.min(3, modelGroups.length) : 1;
    const columns: Array<Array<[string, string[]]>> = Array.from(
      { length: columnCount },
      () => [],
    );
    const weights = Array(columnCount).fill(0);
    modelGroups.forEach((group, index) => {
      const column =
        index < columnCount ? index : weights.indexOf(Math.min(...weights));
      columns[column].push(group);
      weights[column] += 2 + Math.max(1, Math.ceil(group[1].length / 2));
    });
    return columns;
  }, [modelGroups]);
  const languages = useMemo(
    () => [
      ...new Set(
        active?.options
          .filter(
            (o) =>
              !selectedModels.length ||
              selectedModels.includes(o.model || "无需型号"),
          )
          .map((o) => o.language || "无需语种") || [],
      ),
    ],
    [active, selectedModels],
  );
  function open(p: Product) {
    setActive(p);
    const ms = [...new Set(p.options.map((o) => o.model || "无需型号"))];
    const ls = [...new Set(p.options.map((o) => o.language || "无需语种"))];
    setSelectedModels(ms.length === 1 ? ms : []);
    setSelectedLanguages(ls.length === 1 ? ls : []);
    setQty(1);
    setRemark("");
  }
  const toggle = (
    list: string[],
    value: string,
    setter: (v: string[]) => void,
  ) =>
    setter(
      list.includes(value) ? list.filter((x) => x !== value) : [...list, value],
    );
  function add() {
    if (!active) return;
    if (!selectedModels.length || !selectedLanguages.length) {
      setError("请先选择产品型号和语种");
      return;
    }
    const options = active.options.filter(
      (o) =>
        selectedModels.includes(o.model || "无需型号") &&
        selectedLanguages.includes(o.language || "无需语种"),
    );
    if (!options.length) {
      setError("所选型号和语种之间没有有效的物料组合");
      return;
    }
    setLines((prev) => {
      const next = [...prev];
      options.forEach((o) => {
        const i = next.findIndex(
          (x) =>
            x.product === active.name &&
            x.model === o.model &&
            x.language === o.language,
        );
        const line = {
          product: active.name,
          model: o.model,
          language: o.language,
          quantity: qty,
          remark,
          current_stock: o.stock,
          inventory_status: o.stock >= qty ? "库存充足" : "库存不足",
          unitPriceRmb: o.unitPriceRmb,
        };
        if (i >= 0) next[i] = { ...next[i], quantity: next[i].quantity + qty };
        else next.push(line);
      });
      return next;
    });
    setActive(null);
    setError("");
  }
  function draft() {
    const acceptedRoles = catalog?.rolesByUser?.[requesterId]?.length
      ? catalog.rolesByUser[requesterId]
      : ["销售"];
    const acceptedNow = new Date();
    const acceptedDate = new Date(
      acceptedNow.getTime() - acceptedNow.getTimezoneOffset() * 60_000,
    )
      .toISOString()
      .slice(0, 10);
    return {
      submission_token: submissionToken,
      accepted_roles: acceptedRoles,
      accepted_date: acceptedDate,
      accepted_at_ms: acceptedNow.getTime(),
      title: `${usage || "物料用途"}-${user?.name || "申请人"}-营销物料领取`,
      department,
      department_id: depId,
      requester: user?.name || "",
      requester_open_id: requesterId,
      customer_name: customer,
      country,
      recipient_info: recipient,
      freight_payer: "PUDU",
      material_usage: usage,
      request_reason: reason,
      arrival_start: date,
      arrival_end: date,
      lines: lines.map(({ unitPriceRmb, ...l }) => l),
    };
  }
  function localErrors() {
    const errors: string[] = [];
    if (!requesterId || !user)
      errors.push("请选择有效的申请人，才能核对申请时效权限");
    if (!reason)
      errors.push("请选择申请原因：代理活动、展会需求、客户来访或其他");
    if (!date) errors.push("请选择完整的要求到达日期");
    else {
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const arrival = new Date(`${date}T00:00:00`);
      const leadDays = Math.round(
        (arrival.getTime() - today.getTime()) / 86400000,
      );
      if (leadDays < 0) errors.push("要求到达日期不能早于提交申请当天");
      const roles = new Set(
        catalog?.rolesByUser?.[requesterId]?.length
          ? catalog.rolesByUser[requesterId]
          : ["销售"],
      );
      const salesOnly = roles.size === 1 && roles.has("销售");
      const exempt =
        reason === "客户来访" ||
        roles.has("区域市场经理") ||
        roles.has("区域市场负责人") ||
        !salesOnly;
      if (!exempt && leadDays < 7)
        errors.push(
          "销售物料申请须至少提前7个自然日；7～14天为加急，15天起为普通申请",
        );
    }
    return errors;
  }
  const errorMessage = (detail: unknown, fallback: string) =>
    Array.isArray(detail)
      ? detail
          .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
          .join("；")
      : typeof detail === "string"
        ? detail
        : fallback;
  async function preview() {
    setError("");
    const local = localErrors();
    if (local.length) {
      setError(local.join("；"));
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft()),
      });
      const body = await r.json();
      if (!r.ok || !body.valid)
        throw Error(errorMessage(body.errors || body.detail, "请检查必填项"));
      setReview(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "校验失败");
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    setError("");
    const local = localErrors();
    if (local.length) {
      setError(local.join("；"));
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft()),
      });
      const body = await r.json();
      if (!r.ok) throw Error(errorMessage(body.detail, "提交失败"));
      setDone(`申请已进入后台队列（任务 ${body.taskId}）`);
      setReview(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }
  if (!catalog)
    return (
      <main className="loading">
        {error || t("正在读取本地物料缓存…", "Loading material cache…")}
      </main>
    );
  if (done)
    return (
      <main className="success">
        <div>✓</div>
        <h1>{t("提交成功", "Submitted")}</h1>
        <p>{done}</p>
        <button onClick={() => location.reload()}>
          {t("继续申请", "New Request")}
        </button>
      </main>
    );
  return (
    <>
      <header className="request-page-header">
        <b>PUDU</b>
        <span>Material Operations</span>
        <em>物料申领</em>
      </header>
      <main className="request-page">
        <section>
          <div className="section-title">
            <i>01</i>
            <div>
              <h2>
                {t("申请与业务信息", "Application & Business Information")}
              </h2>
              <p>
                {t("填写领取申请的基础信息", "Complete the request details")}
              </p>
            </div>
          </div>
          <div className="grid3">
            <label>
              {t("申请人", "Applicant")} *
              <div className="combobox">
                <input
                  value={requesterQuery}
                  placeholder={t("填写中文名称", "Type a name")}
                  autoComplete="off"
                  onFocus={() => setRequesterOpen(true)}
                  onChange={(e) => {
                    setRequesterQuery(e.target.value);
                    setRequesterId("");
                    setRequesterOpen(true);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setRequesterOpen(false);
                  }}
                />
                <button
                  type="button"
                  aria-label={t("展开申请人列表", "Open applicant list")}
                  onClick={() => setRequesterOpen(!requesterOpen)}
                >
                  ⌄
                </button>
                {requesterOpen && (
                  <div className="combo-menu">
                    {requesterOptions.length ? (
                      requesterOptions.map((u) => (
                        <button
                          type="button"
                          key={u.open_id}
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => chooseRequester(u)}
                        >
                          {requesterLabel(u)}
                        </button>
                      ))
                    ) : (
                      <p>{t("没有匹配的申请人", "No matching applicants")}</p>
                    )}
                  </div>
                )}
              </div>
            </label>
            <label>
              {t("申请部门", "Department")}
              <input
                value={department}
                readOnly
                placeholder={t(
                  "选择申请人后自动显示",
                  "Shown after selecting an applicant",
                )}
              />
            </label>
            <label>
              {t("客户名称", "Customer Name")} *
              <input
                value={customer}
                onChange={(e) => setCustomer(e.target.value)}
              />
            </label>
            <label>
              {t("国家", "Country")} *
              <input
                value={country}
                onChange={(e) => setCountry(e.target.value)}
              />
            </label>
          </div>
          <div className="titlebar">
            {t("申请标题", "Request Title")} <b>{draft().title}</b>
          </div>
          <div className="grid2">
            <label>
              {t("收件人信息", "Recipient Information")} *
              <textarea
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder={t(
                  "地址及邮编、公司、收件人和联系方式",
                  "Address, postal code, company, recipient and contact",
                )}
              />
            </label>
            <label>
              {t("物料用途", "Material Usage")} *
              <textarea
                value={usage}
                onChange={(e) => setUsage(e.target.value)}
                placeholder={t(
                  "活动物料请注明具体活动名称",
                  "For events, include the event name",
                )}
              />
            </label>
            <label>
              {t("申请原因", "Request Reason")} *
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              >
                <option value="">{t("请选择", "Select")}</option>
                {catalog.reasons.map((x) => (
                  <option key={x} value={x}>
                    {lang === "zh"
                      ? x
                      : (
                          {
                            代理活动: "Partner Event",
                            展会需求: "Exhibition",
                            客户来访: "Customer Visit",
                            其他: "Other",
                          } as Record<string, string>
                        )[x] || x}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("物料使用时间", "Material Use Date")} *
              <input
                type="date"
                min={new Date().toISOString().slice(0, 10)}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
          </div>
        </section>
        <section>
          <div className="section-head">
            <div className="section-title">
              <i>02</i>
              <div>
                <h2>{t("选择申请物料", "Select Materials")}</h2>
                <p>
                  {t(
                    "11 个规格弹层已随页面一次加载完成",
                    "All 11 option panels are preloaded",
                  )}
                </p>
              </div>
            </div>
            <div className="metrics">
              <span>
                {lines.length} {t("种", "types")} / {count} {t("件", "items")}
              </span>
              <strong>
                {t("预计", "Est.")} ¥{total.toFixed(2)}
              </strong>
            </div>
          </div>
          <div className="toolbar">
            <input
              placeholder={t(
                "⌕ 输入品类名称搜索",
                "⌕ Search material categories",
              )}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button className="cart" onClick={() => setCartOpen(!cartOpen)}>
              🛒 {lines.length} {cartOpen ? "⌃" : "⌄"}
            </button>
            <button className="primary" onClick={preview} disabled={busy}>
              {t("提交物料申请", "Submit Material Request")}
            </button>
          </div>
          {cartOpen && (
            <div className="cartpanel">
              {!lines.length ? (
                <p>
                  {t(
                    "采购车为空，请先选择物料。",
                    "Your cart is empty. Select materials first.",
                  )}
                </p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>{t("品类", "Category")}</th>
                      <th>{t("型号", "Model")}</th>
                      <th>{t("语种", "Language")}</th>
                      <th>{t("数量", "Quantity")}</th>
                      <th>{t("备注", "Remarks")}</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l, i) => (
                      <tr key={`${l.product}${l.model}${l.language}`}>
                        <td>{clean(l.product)}</td>
                        <td>{l.model}</td>
                        <td>{l.language}</td>
                        <td>
                          <input
                            type="number"
                            min="1"
                            max="1000000"
                            value={l.quantity}
                            onChange={(e) =>
                              setLines(
                                lines.map((x, j) =>
                                  j === i
                                    ? { ...x, quantity: +e.target.value }
                                    : x,
                                ),
                              )
                            }
                          />
                        </td>
                        <td>
                          <input
                            value={l.remark}
                            onChange={(e) =>
                              setLines(
                                lines.map((x, j) =>
                                  j === i
                                    ? { ...x, remark: e.target.value }
                                    : x,
                                ),
                              )
                            }
                          />
                        </td>
                        <td>
                          <button
                            onClick={() =>
                              setLines(lines.filter((_, j) => j !== i))
                            }
                          >
                            {t("删除", "Delete")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
          <div className="cards">
            {products.map((p) => (
              <article key={p.name}>
                {p.image ? (
                  <img src={p.image} />
                ) : (
                  <div className="placeholder">PUDU</div>
                )}
                <small>{t("物料品类", "Material Category")}</small>
                <h3>{p.nameDisplay?.[lang] || clean(p.name)}</h3>
                <button onClick={() => open(p)}>
                  🛒 {t("选择规格", "Select Options")}
                </button>
              </article>
            ))}
          </div>
        </section>
        {error && (
          <div className="toast" onClick={() => setError("")}>
            {error} ×
          </div>
        )}
      </main>
      {active && (
        <div className="overlay request-overlay" onMouseDown={() => setActive(null)}>
          <div className="modal request-spec-modal" onMouseDown={(e) => e.stopPropagation()}>
            <button className="close" onClick={() => setActive(null)}>
              ×
            </button>
            <h2>{active.nameDisplay?.[lang] || clean(active.name)}</h2>
            <p>
              {t(
                "选择需要加入采购车的规格，可同时框选多个型号和多个语种。",
                "Select one or more models and languages to add to the cart.",
              )}
            </p>
            <div className="selector">
              <h4>{t("产品型号", "Product Model")}</h4>
              <div className={modelGroups.length > 1 ? "model-line-grid" : ""}>
                {modelColumns.map((column, columnIndex) => (
                  <div className="model-line-column" key={columnIndex}>
                    {column.map(([line, groupModels]) => (
                      <div className="model-line" key={line || "all"}>
                        {line && <small>{line}</small>}
                        <div className="pills">
                          {groupModels.map((model) => (
                            <button
                              className={
                                selectedModels.includes(model) ? "chosen" : ""
                              }
                              onClick={() =>
                                toggle(selectedModels, model, setSelectedModels)
                              }
                              key={model}
                            >
                              {modelMeta.get(model)?.display || model}
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
              <h4>{t("语种", "Language")}</h4>
              <div className="pills">
                {languages.map((language) => (
                  <button
                    className={
                      selectedLanguages.includes(language) ? "chosen" : ""
                    }
                    onClick={() =>
                      toggle(selectedLanguages, language, setSelectedLanguages)
                    }
                    key={language}
                  >
                    {language}
                  </button>
                ))}
              </div>
            </div>
            <div className="selection-note">
              已选 {selectedModels.length} 个型号、{selectedLanguages.length}{" "}
              个语种，将加入{" "}
              {
                active.options.filter(
                  (o) =>
                    selectedModels.includes(o.model || "无需型号") &&
                    selectedLanguages.includes(o.language || "无需语种"),
                ).length
              }{" "}
              条有效明细
            </div>
            <div className="modalfoot">
              <label>
                {t("自定义数量", "Quantity")}
                <input
                  type="number"
                  min="1"
                  max="1000000"
                  value={qty}
                  onChange={(e) => setQty(+e.target.value)}
                />
              </label>
              <div className="presets">
                <button onClick={() => setQty(20)}>20</button>
                <button onClick={() => setQty(50)}>50</button>
              </div>
              <label>
                {t("备注", "Remarks")}
                <input
                  value={remark}
                  onChange={(e) => setRemark(e.target.value)}
                  placeholder={t("可选", "Optional")}
                />
              </label>
              <button className="primary" onClick={add}>
                🛒 {t("加入采购车", "Add to Cart")}
              </button>
            </div>
          </div>
        </div>
      )}
      {review && (
        <div className="overlay request-overlay">
          <div className="modal review request-review-modal">
            <button className="close" onClick={() => setReview(false)}>
              ×
            </button>
            <h2>{t("申请信息确认", "Confirm Request")}</h2>
            <div className="reviewgrid">
              <p>
                {t("申请人", "Applicant")}
                <b>{user?.name}</b>
              </p>
              <p>
                {t("申请部门", "Department")}
                <b>{department}</b>
              </p>
              <p>
                {t("客户名称", "Customer")}
                <b>{customer}</b>
              </p>
              <p>
                {t("国家", "Country")}
                <b>{country}</b>
              </p>
              <p>
                {t("申请原因", "Reason")}
                <b>{reason}</b>
              </p>
              <p>
                {t("使用时间", "Use Date")}
                <b>{date}</b>
              </p>
            </div>
            <h3>
              {t("申请物料清单", "Material List")} · {lines.length}{" "}
              {t("种", "types")} / {count} {t("件", "items")} / ¥
              {total.toFixed(2)}
            </h3>
            <table>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i}>
                    <td>{clean(l.product)}</td>
                    <td>{l.model}</td>
                    <td>{l.language}</td>
                    <td>{l.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="reviewactions">
              <button onClick={() => setReview(false)}>
                {t("返回修改", "Back to Edit")}
              </button>
              <button className="primary" disabled={busy} onClick={submit}>
                {t("确认提交", "Confirm Submit")}
              </button>
            </div>
          </div>
        </div>
      )}
      {busy && review && (
        <div className="submit-overlay" role="status">
          <div className="spinner"></div>
          <strong>
            {t("正在提交数据，请稍后……", "Submitting, please wait…")}
          </strong>
          <span>
            {t(
              "申请正在进入后台处理队列，请勿重复提交",
              "The request is entering the background queue. Do not submit again.",
            )}
          </span>
        </div>
      )}
    </>
  );
}
