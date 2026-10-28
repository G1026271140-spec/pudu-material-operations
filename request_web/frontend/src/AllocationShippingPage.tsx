import AllocationWorkbench from "./AllocationWorkbench";
import ShippingCalendarPage from "./ShippingCalendarPage";
import "./management.css";
import "./allocation-shipping.css";

export type AllocationShippingTab = "allocation" | "shipping";

export default function AllocationShippingPage({ lang, tab, onTabChange }: {
  lang: "zh" | "en";
  tab: AllocationShippingTab;
  onTabChange: (tab: AllocationShippingTab) => void;
}) {
  const tr = (zh: string, en: string) => lang === "zh" ? zh : en;
  return <section className="allocation-shipping-page" aria-label={tr("配货与发货", "Allocation & Shipping")}>
    <nav className="management-tabs allocation-shipping-tabs" aria-label={tr("配货与发货功能", "Allocation and shipping sections")}>
      <button type="button" className={tab === "allocation" ? "active" : ""} aria-current={tab === "allocation" ? "page" : undefined} onClick={() => onTabChange("allocation")}>{tr("配货工作台", "Allocation Workbench")}</button>
      <button type="button" className={tab === "shipping" ? "active" : ""} aria-current={tab === "shipping" ? "page" : undefined} onClick={() => onTabChange("shipping")}>{tr("物料发货日历", "Material Shipping Calendar")}</button>
    </nav>
    {tab === "allocation" ? <AllocationWorkbench lang={lang} embedded /> : <ShippingCalendarPage lang={lang} />}
  </section>;
}
