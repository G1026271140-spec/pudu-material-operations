import { useState } from "react";

type Lang = "zh" | "en";

const SCHEDULE_URL = "https://pudutech.feishu.cn/share/base/webpage/shrcn7T5KaZ9FHiA7BJxppjpGTe";
const EDIT_URL = "https://pudutech.feishu.cn/wiki/G7vbwubTbiagPokSvAiceK8AnZc?table=blkFyA0zYCNs7BsW";

export default function ShippingSchedulePage({ lang }: { lang: Lang }) {
  const tr = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const [loaded, setLoaded] = useState(false);

  return (
    <section className="shipping-schedule-page" aria-label={tr("发货排期", "Shipping Schedule")}>
      <div className="shipping-schedule-toolbar">
        <div className="shipping-schedule-actions">
          <a href={SCHEDULE_URL} target="_blank" rel="noreferrer">{tr("打开实时排期", "Open Live Schedule")}</a>
          <a className="primary" href={EDIT_URL} target="_blank" rel="noreferrer">{tr("发货编辑", "Edit Shipping")}</a>
        </div>
      </div>
      <div className="shipping-schedule-frame-wrap">
        {!loaded && (
          <div className="shipping-schedule-loading" role="status">
            <strong>{tr("正在载入实时发货排期…", "Loading live shipping schedule…")}</strong>
            <span>{tr("如飞书要求登录或未能显示，请使用上方“打开实时排期”。", "If Feishu asks you to sign in or cannot display here, use “Open Live Schedule” above.")}</span>
          </div>
        )}
        <iframe
          title={tr("飞书发货排期实时视图", "Feishu live shipping schedule")}
          src={SCHEDULE_URL}
          onLoad={() => setLoaded(true)}
          referrerPolicy="strict-origin-when-cross-origin"
        />
      </div>
    </section>
  );
}
