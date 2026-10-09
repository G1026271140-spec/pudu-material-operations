import { useEffect, useState } from "react";
import RequestPage from "./App";
import CulturalPage from "./CulturalPage";
import ManagementPage from "./ManagementPage";
import type { ManagementTab } from "./ManagementPage";
import AllocationWorkbench from "./AllocationWorkbench";
import "./portal.css";

type Lang = "zh" | "en";
type PortalPage = "request" | "cultural" | "management";

const managementPaths: Record<ManagementTab, string> = {
  allocation: "/management/allocation",
  schedule: "/management/shipping-schedule",
  shipping: "/management/shipping-template",
  restock: "/management/restock",
  category: "/management/categories",
  model: "/management/models",
  language: "/management/languages",
  region: "/management/regions",
};

function normalizedPath(): string {
  return window.location.pathname.replace(/\/+$/, "").toLowerCase() || "/";
}

function managementTabFromLocation(): ManagementTab {
  const path = normalizedPath();
  const match = (Object.entries(managementPaths) as [ManagementTab, string][])
    .find(([, route]) => route === path);
  return match?.[0] || "allocation";
}

function pageFromLocation(): PortalPage {
  const path = normalizedPath();
  const section = new URLSearchParams(window.location.search).get("section");
  if (path === "/cultural" || section === "cultural_request" || section === "cultural") {
    return "cultural";
  }
  if (path === "/management" || path.startsWith("/management/") || section === "management") {
    return "management";
  }
  return "request";
}

function pagePath(page: PortalPage): string {
  if (page === "cultural") return "/cultural";
  if (page === "management") return managementPaths.allocation;
  return "/request";
}

const text = {
  zh: {
    app: "营销物料管理系统",
    language: "语言设置 / Language",
    nav: "工作台导航",
    request: "物料申领",
    cultural: "文化周边申领",
    management: "物料管理",
    tools: "数据与系统工具",
    version: "当前应用版本 V3.0.2",
    locked: "此功能暂未对外开放",
    password: "请输入管理员密码",
    unlock: "解锁",
    wrong: "密码不正确",
    collapse: "收起左侧导航",
    expand: "展开左侧导航",
  },
  en: {
    app: "Marketing Materials System",
    language: "Language / 语言设置",
    nav: "Workspace Navigation",
    request: "Material Request",
    cultural: "Cultural Merchandise Request",
    management: "Material Management",
    tools: "Data & System Tools",
    version: "Current Version V3.0.2",
    locked: "This feature is not publicly available",
    password: "Enter administrator password",
    unlock: "Unlock",
    wrong: "Incorrect password",
    collapse: "Collapse sidebar",
    expand: "Expand sidebar",
  },
};

export default function Portal() {
  const params = new URLSearchParams(window.location.search);
  const directAllocation = params.get("allocation") === "request" && Boolean(params.get("request_id"));
  const [lang, setLang] = useState<Lang>(() =>
    localStorage.getItem("pudu-lang") === "en" ? "en" : "zh",
  );
  const [page, setPage] = useState<PortalPage>(pageFromLocation);
  const [managementTab, setManagementTab] = useState<ManagementTab>(managementTabFromLocation);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [unlocked, setUnlocked] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("pudu-sidebar-collapsed") === "true",
  );
  const t = text[lang];
  useEffect(() => {
    fetch("/api/admin/status")
      .then((response) => response.json())
      .then((body) => setUnlocked(Boolean(body.unlocked)))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    const handlePopState = () => {
      setPage(pageFromLocation());
      setManagementTab(managementTabFromLocation());
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);
  if (directAllocation) {
    return <AllocationWorkbench lang={lang} directRequestId={params.get("request_id") || ""} operator={params.get("operator") || ""} reviewToken={params.get("review_token") || ""} />;
  }
  function changeLang(next: Lang) {
    localStorage.setItem("pudu-lang", next);
    setLang(next);
  }
  function setCollapsed(collapsed: boolean) {
    localStorage.setItem("pudu-sidebar-collapsed", String(collapsed));
    setSidebarCollapsed(collapsed);
  }
  function navigate(next: PortalPage) {
    const url = new URL(window.location.href);
    url.pathname = pagePath(next);
    url.searchParams.delete("section");
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setPage(next);
    if (next === "management") setManagementTab("allocation");
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  function navigateManagementTab(next: ManagementTab) {
    const url = new URL(window.location.href);
    url.pathname = managementPaths[next];
    url.searchParams.delete("section");
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setPage("management");
    setManagementTab(next);
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  async function unlock() {
    setError("");
    const response = await fetch("/api/admin/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) {
      setError(t.wrong);
      return;
    }
    setUnlocked(true);
  }
  return (
    <div className={`portal${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <button
          type="button"
          className="sidebar-collapse"
          aria-label={t.collapse}
          title={t.collapse}
          onClick={() => setCollapsed(true)}
        >
          «
        </button>
        <div className="sidebar-brand">
          <img
            className="pudu-logo"
            src="/app-assets/pudu-logo-blue.png"
            alt="PUDU"
          />
          <img className="app-icon" src="/app-assets/app-icon.png" alt="" />
          <div>
            <strong>{t.app}</strong>
            <span>PUDU Material Operations</span>
          </div>
        </div>
        <div className="sidebar-label">{t.language}</div>
        <div className="language-switch">
          <button
            className={lang === "zh" ? "active" : ""}
            onClick={() => changeLang("zh")}
          >
            中文
          </button>
          <button
            className={lang === "en" ? "active" : ""}
            onClick={() => changeLang("en")}
          >
            English
          </button>
        </div>
        <div className="sidebar-label">{t.nav}</div>
        <nav>
          <button
            className={page === "request" ? "active" : ""}
            onClick={() => navigate("request")}
          >
            <span>☷</span>
            {t.request}
          </button>
          <button
            className={page === "cultural" ? "active" : ""}
            onClick={() => navigate("cultural")}
          >
            <span>♧</span>
            {t.cultural}
          </button>
          <button
            className={page === "management" ? "active" : ""}
            onClick={() => navigate("management")}
          >
            <span>▣</span>
            {t.management}
            <i>🔒</i>
          </button>
        </nav>
        <div className="sidebar-system">
          <div className="sidebar-label">{t.tools}</div>
          <div className="version-row">
            <span>{t.version}</span>
            <span>🔒</span>
          </div>
        </div>
      </aside>
      <button
        type="button"
        className="sidebar-expand"
        aria-label={t.expand}
        title={t.expand}
        onClick={() => setCollapsed(false)}
      >
        »
      </button>
      <div className="portal-content">
        {page === "request" ? (
          <RequestPage lang={lang} />
        ) : page === "cultural" ? (
          <CulturalPage lang={lang} />
        ) : unlocked ? (
          <ManagementPage
            lang={lang}
            initialTab={managementTab}
            onTabChange={navigateManagementTab}
          />
        ) : (
          <main className="locked-page">
            <img src="/app-assets/app-icon.png" alt="" />
            <h1>{t.management}</h1>
            <div className="unlock-card">
              <div className="lock-mark">🔒</div>
              <h2>{t.locked}</h2>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && unlock()}
                placeholder={t.password}
              />
              <button onClick={unlock}>{t.unlock}</button>
              {error && <p>{error}</p>}
            </div>
          </main>
        )}
      </div>
    </div>
  );
}
