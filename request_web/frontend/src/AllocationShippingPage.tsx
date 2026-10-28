import { useEffect, useState } from "react";
import AllocationWorkbench from "./AllocationWorkbench";
import ShippingCalendarPage from "./ShippingCalendarPage";
import "./management.css";
import "./allocation-shipping.css";

export type AllocationShippingTab = "allocation" | "shipping";

export default function AllocationShippingPage({ lang, tab, onTabChange, active = true, canManage = false, canEditShipping = false }: {
  active?: boolean;
  canManage?: boolean;
  canEditShipping?: boolean;
  lang: "zh" | "en";
  tab: AllocationShippingTab;
  onTabChange: (tab: AllocationShippingTab) => void;
}) {
  const applicantView = new URLSearchParams(window.location.search).get("shipping_view") === "readonly";
  const selectedTab = applicantView ? "shipping" : tab;
  const [shippingVisited, setShippingVisited] = useState(selectedTab === "shipping");
  useEffect(() => { if (selectedTab === "shipping") setShippingVisited(true); }, [tab]);
  const tr = (zh: string, en: string) => lang === "zh" ? zh : en;
  return <section className="allocation-shipping-page" aria-label={tr("配货与发货", "Allocation & Shipping")}>
    <nav className="management-tabs allocation-shipping-tabs" aria-label={tr("配货与发货功能", "Allocation and shipping sections")}>
      {canManage && !applicantView && <button type="button" className={selectedTab === "allocation" ? "active" : ""} aria-current={selectedTab === "allocation" ? "page" : undefined} onClick={() => onTabChange("allocation")}>{tr("配货工作台", "Allocation Workbench")}</button>}
      <button type="button" className={selectedTab === "shipping" ? "active" : ""} aria-current={selectedTab === "shipping" ? "page" : undefined} onClick={() => onTabChange("shipping")}>{tr("物料发货日历", "Material Shipping Calendar")}</button>
    </nav>
    {canManage && !applicantView && selectedTab === "allocation" && <AllocationWorkbench lang={lang} embedded />}
    {(shippingVisited || selectedTab === "shipping") && <div hidden={selectedTab !== "shipping"}><ShippingCalendarPage lang={lang} active={active && selectedTab === "shipping"} editable={!applicantView && (canManage || canEditShipping)} /></div>}
  </section>;
}
