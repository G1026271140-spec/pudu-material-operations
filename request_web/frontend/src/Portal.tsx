import { useEffect, useState } from "react";
import RequestPage from "./App";
import CulturalPage from "./CulturalPage";
import ManagementPage from "./ManagementPage";
import type { ManagementTab } from "./ManagementPage";
import AllocationWorkbench from "./AllocationWorkbench";
import AllocationShippingPage from "./AllocationShippingPage";
import type { AllocationShippingTab } from "./AllocationShippingPage";
import CorporateApparelPage from "./CorporateApparelPage";
import DatabaseWorkbench from "./DatabaseWorkbench";
import TaskMonitorPage from "./TaskMonitorPage";
import ApparelManagementPage from "./ApparelManagementPage";
import RequestHistoryPage from "./RequestHistoryPage";
import UserPermissionsPage from "./UserPermissionsPage";
import type { CurrentUser } from "./identity";
import "./portal.css";

type Lang = "zh" | "en";
type PortalPage = "request" | "cultural" | "management" | "allocation" | "database" | "apparelManagement" | "history" | "permissions" | "tasks";

const managementPaths: Record<ManagementTab, string> = {
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
  return match?.[0] || "category";
}

function pageFromLocation(): PortalPage {
  const path = normalizedPath();
  const section = new URLSearchParams(window.location.search).get("section");
  if (path === "/management/allocation" || path === "/management/shipping-calendar") return "allocation";
  if (path === "/management/request-history") return "history";
  if (path === "/management/user-permissions") return "permissions";
  if (path === "/management/tasks") return "tasks";
  if (path === "/management/database") return "database";
  if (path === "/management/corporate-apparel") return "apparelManagement";
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
  if (page === "management") return managementPaths.category;
  if (page === "allocation") return "/management/allocation";
  if (page === "history") return "/management/request-history";
  if (page === "permissions") return "/management/user-permissions";
  if (page === "tasks") return "/management/tasks";
  if (page === "database") return "/management/database";
  if (page === "apparelManagement") return "/management/corporate-apparel";
  return "/request";
}

function IdentityBar({ user, lang }: { user: CurrentUser | null; lang: Lang }) {
  if (!user) return null;
  const role = user.permission_status === "disabled"
    ? (lang === "zh" ? "权限已停用" : "Access disabled")
    : user.roles.join("、") || (lang === "zh" ? "未设置角色" : "No role");
  return (
    <div className="identity-bar" aria-label={lang === "zh" ? "当前登录身份" : "Signed-in identity"}>
      <div className="identity-person">
        {user.read_only && <span role="status">{user.data_source==='postgresql'?(lang==='zh'?'业务申请暂未开放 · 虚拟数据库可编辑':'Submissions disabled · database editing available'):(lang === 'zh' ? '浏览验证 · 提交暂未开放' : 'Preview · submissions disabled')}</span>}
        {user.avatar_url ? <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" /> : <span className="identity-avatar">{user.name.slice(0, 1)}</span>}
        <span className="identity-name">{user.name}</span>
        <span className="identity-role">{role}</span>
      </div>
      <a href="/auth/feishu/logout">{lang === "zh" ? "退出" : "Sign out"}</a>
    </div>
  );
}

const text = {
  zh: {
    app: "营销物料管理系统",
    language: "语言设置 / Language",
    nav: "工作台导航",
    request: "物料申领",
    cultural: "文化周边申领",
    management: "物料管理",
    allocation: "配货与发货",
    database: "虚拟数据库",
    tasks: "后台任务",
    history: "申请记录与额度",
    permissions: "用户权限管理",
    apparelManagement: "企业文化衫管理",
    corporateApparel: "企业文化衫领取",
    corporateApparelHint: "在新页面打开企业文化衫领取",
    historyGroup: "历史数据",
    editingGroup: "后台编辑",
    systemGroup: "系统工具",
    version: "当前应用版本",
    denied: "仅已启用的管理员可访问物料管理",
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
    allocation: "Allocation & Shipping",
    database: "Virtual Database",
    tasks: "Background Tasks",
    history: "History & Allowances",
    permissions: "User Permissions",
    apparelManagement: "Corporate Apparel Management",
    corporateApparel: "Corporate Apparel Request",
    corporateApparelHint: "Open Corporate Apparel Request in a new tab",
    historyGroup: "History",
    editingGroup: "Administration",
    systemGroup: "System Tools",
    version: "Current Version",
    denied: "Only enabled administrators can access Material Management",
    collapse: "Collapse sidebar",
    expand: "Expand sidebar",
  },
};

export default function Portal() {
  const params = new URLSearchParams(window.location.search);
  const directAllocation = params.get("allocation") === "request" && Boolean(params.get("request_id"));
  const directCorporateApparel = normalizedPath() === "/corporate-apparel";
  const [lang, setLang] = useState<Lang>(() =>
    localStorage.getItem("pudu-lang") === "en" ? "en" : "zh",
  );
  const [page, setPage] = useState<PortalPage>(pageFromLocation);
  const [allocationVisited, setAllocationVisited] = useState(page === "allocation");
  useEffect(() => { if (page === "allocation") setAllocationVisited(true); }, [page]);
  const [managementTab, setManagementTab] = useState<ManagementTab>(managementTabFromLocation);
  const [allocationShippingTab, setAllocationShippingTab] = useState<AllocationShippingTab>(() => normalizedPath() === "/management/shipping-calendar" ? "shipping" : "allocation");
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [identityLoaded, setIdentityLoaded] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("pudu-sidebar-collapsed") === "true",
  );
  const t = text[lang];
  const canManage = currentUser?.permission_status === "enabled" && currentUser.roles.includes("管理员");
  const canManageApparel = currentUser?.permission_status === "enabled" && currentUser.roles.some(role => role === "HR" || role === "管理员");
  const canEditShipping = currentUser?.permission_status === "enabled" && currentUser.roles.some(role => role === "中台" || role === "管理员");
  useEffect(() => {
    const refreshIdentity = () => {
      fetch("/api/auth/me", { cache: "no-store" })
        .then((response) => response.ok ? response.json() : null)
        .then((identity) => setCurrentUser(identity))
        .catch(() => setCurrentUser(null))
        .finally(() => setIdentityLoaded(true));
    };
    refreshIdentity();
    window.addEventListener("pudu-permissions-updated", refreshIdentity);
    return () => window.removeEventListener("pudu-permissions-updated", refreshIdentity);
  }, []);
  useEffect(() => {
    const handlePopState = () => {
      setPage(pageFromLocation());
      setManagementTab(managementTabFromLocation());
      setAllocationShippingTab(normalizedPath() === "/management/shipping-calendar" ? "shipping" : "allocation");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);
  if (directAllocation) {
    return <><IdentityBar user={currentUser} lang={lang} /><AllocationWorkbench lang={lang} directRequestId={params.get("request_id") || ""} operator={params.get("operator") || ""} reviewToken={params.get("review_token") || ""} /></>;
  }
  if (directCorporateApparel) {
    return <><IdentityBar user={currentUser} lang={lang} /><CorporateApparelPage currentUser={currentUser} /></>;
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
    if (next === "management") setManagementTab("category");
    if (next === "allocation") {
      setAllocationShippingTab(canManage ? "allocation" : "shipping");
      if (!canManage) { url.pathname = "/management/shipping-calendar"; window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`); }
    }
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  function navigateAllocationShippingTab(next: AllocationShippingTab) {
    if (next === allocationShippingTab) return;
    const url = new URL(window.location.href);
    url.pathname = next === "shipping" ? "/management/shipping-calendar" : "/management/allocation";
    url.searchParams.delete("section");
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setPage("allocation");
    setAllocationShippingTab(next);
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


          {canManage && <a
            className="corporate-apparel-link"
            href="/corporate-apparel"
            target="_blank"
            rel="noopener noreferrer"
            title={t.corporateApparelHint}
          >
            <span aria-hidden="true">↗</span>
            {t.corporateApparel}
          </a>}
        </nav>
        <div className="sidebar-system">
          {currentUser && <div className="sidebar-tool-group" role="group" aria-label={t.historyGroup}>
            <div className="sidebar-label">{t.historyGroup}</div>
            <button className={`database-nav-link${page === "history" ? " active" : ""}`} onClick={() => navigate("history")}>{t.history}</button>
          </div>}
          {currentUser && <div className="sidebar-tool-group" role="group" aria-label={t.editingGroup}>
            <div className="sidebar-label">{t.editingGroup}</div>
            <button className={`database-nav-link${page === "allocation" ? " active" : ""}`} onClick={() => navigate("allocation")}>{t.allocation}</button>
            {canManage && <button className={`database-nav-link${page === "management" ? " active" : ""}`} onClick={() => navigate("management")}>{t.management}</button>}
            {canManageApparel && <button className={`database-nav-link${page === "apparelManagement" ? " active" : ""}`} onClick={() => navigate("apparelManagement")}>{t.apparelManagement}</button>}
          </div>}
          {canManage && <div className="sidebar-tool-group" role="group" aria-label={t.systemGroup}>
            <div className="sidebar-label">{t.systemGroup}</div>
            <button className={`database-nav-link${page === "permissions" ? " active" : ""}`} onClick={() => navigate("permissions")}>{t.permissions}</button>
            {currentUser?.data_source === 'postgresql' && <>
              <button className={`database-nav-link${page === "database" ? " active" : ""}`} onClick={() => navigate("database")}>{t.database}</button>
              <button className={`database-nav-link${page === "tasks" ? " active" : ""}`} onClick={() => navigate("tasks")}>{t.tasks}</button>
            </>}
          </div>}
          <div className="version-row">
            <span>{t.version} {currentUser?.version || "—"}</span>
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
        <IdentityBar user={currentUser} lang={lang} />
        {page === "request" ? (
          <RequestPage lang={lang} currentUser={currentUser} />
        ) : page === "cultural" ? (
          <CulturalPage lang={lang} currentUser={currentUser} />
        ) : page === "history" ? (
          currentUser ? <RequestHistoryPage lang={lang} currentUser={currentUser} /> : null
        ) : page === "permissions" ? (
          canManage && currentUser ? <UserPermissionsPage lang={lang} currentUser={currentUser} /> : identityLoaded ? <main className="locked-page"><h1>{t.permissions}</h1><p>{t.denied}</p></main> : null
        ) : page === "tasks" ? (
          canManage && currentUser?.data_source === "postgresql" ? <TaskMonitorPage lang={lang} /> : identityLoaded ? <main className="locked-page"><h1>{t.tasks}</h1><p>{lang === "zh" ? "仅已启用的管理员可查看后台任务。" : "Only enabled administrators can view background tasks."}</p></main> : null
        ) : page === "apparelManagement" ? (
          canManageApparel ? <ApparelManagementPage lang={lang} /> : identityLoaded ? <main className="locked-page"><h1>{t.apparelManagement}</h1><p>{lang === "zh" ? "仅已启用的 HR 和管理员可访问此页面。" : "Only enabled HR staff and administrators can access this page."}</p></main> : null
        ) : currentUser && page === "allocation" ? (
          null
        ) : canManage && page === "database" ? (
          <DatabaseWorkbench lang={lang} />
        ) : canManage ? (
          <ManagementPage
            lang={lang}
            initialTab={managementTab}
            onTabChange={navigateManagementTab}
          />
        ) : identityLoaded ? (
          <main className="locked-page">
            <img src="/app-assets/app-icon.png" alt="" />
            <h1>{t.management}</h1>
            <div className="unlock-card">
              <div className="lock-mark">🔒</div>
              <h2>{t.denied}</h2>
            </div>
          </main>
        ) : null}
        {currentUser && (allocationVisited || page === "allocation") && <div hidden={page !== "allocation"}><AllocationShippingPage lang={lang} tab={canManage ? allocationShippingTab : "shipping"} onTabChange={navigateAllocationShippingTab} active={page === "allocation"} canManage={canManage} canEditShipping={canEditShipping} /></div>}
      </div>
    </div>
  );
}
