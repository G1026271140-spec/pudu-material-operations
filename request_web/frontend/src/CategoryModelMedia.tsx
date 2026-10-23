import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import CategoryCarousel from "./CategoryCarousel";
import "./model-viewer.css";

const ModelViewer = lazy(() => import("./ModelViewer"));

type Props = { images: string[]; alt: string; modelUrl: string; lang?: "zh" | "en" };
export default function CategoryModelMedia({ images, alt, modelUrl, lang = "zh" }: Props) {
  const [active, setActive] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const back = useRef<HTMLButtonElement>(null), close = useRef<HTMLButtonElement>(null);
  const t = (zh: string, en: string) => lang === "zh" ? zh : en;
  useEffect(() => {
    if (!expanded) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    close.current?.focus();
    return () => { document.body.style.overflow = previousOverflow; back.current?.focus(); };
  }, [expanded]);
  const viewer = <Suspense fallback={<p role="status">{t("正在加载三维查看器…", "Loading 3D viewer…")}</p>}><ModelViewer modelUrl={modelUrl} name={alt} lang={lang} /></Suspense>;
  return <div className="category-model-media">
    {active ? <div className="category-model-inline">{expanded ? null : viewer}</div> : <CategoryCarousel images={images} alt={alt} previousLabel={t("上一张图片", "Previous image")} nextLabel={t("下一张图片", "Next image")} imageLabel={t("图片", "Image")} />}
    <div className="category-model-actions">
      <button type="button" onClick={() => setActive(value => !value)}>{active ? t("返回图片", "Photos") : t("查看三维模型", "View 3D model")}</button>
      {active && <button ref={back} type="button" onClick={() => setExpanded(true)}>{t("放大查看", "Expand")}</button>}
    </div>
    {expanded && createPortal(<div className="category-model-overlay" onMouseDown={event => {if (event.target === event.currentTarget) setExpanded(false);}}>
      <section className="category-model-dialog" role="dialog" aria-modal="true" aria-label={`${alt} ${t("三维模型", "3D model")}`} onKeyDown={event => {
        if(event.key === "Escape") {event.stopPropagation();setExpanded(false);}
        if(event.key === "Tab") {
          const items = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],canvas[tabindex]')];
          const first=items[0], last=items[items.length-1];
          if(event.shiftKey && document.activeElement===first) {event.preventDefault();last?.focus();}
          if(!event.shiftKey && document.activeElement===last) {event.preventDefault();first?.focus();}
        }
      }}>
        <header><h2>{alt} · {t("三维模型", "3D Model")}</h2><button ref={close} type="button" aria-label={t("关闭三维模型", "Close 3D model")} onClick={() => setExpanded(false)}>×</button></header>
        {viewer}
      </section>
    </div>, document.body)}
  </div>;
}
