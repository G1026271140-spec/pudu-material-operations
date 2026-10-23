import { useEffect, useRef, useState } from "react";
import { mountModelScene } from "./modelScene";

type Props = { modelUrl: string; name: string; lang?: "zh" | "en" };
export default function ModelViewer({ modelUrl, name, lang="zh" }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<ReturnType<typeof mountModelScene> | null>(null);
  const [status,setStatus] = useState("loading");
  const t = (zh:string,en:string)=>lang==="zh"?zh:en;
  useEffect(()=>{
    setStatus("loading");
    try {view.current=mountModelScene(host.current!,modelUrl,()=>setStatus("ready"),()=>setStatus("error"));}
    catch {setStatus("error");}
    return ()=>{view.current?.dispose();view.current=null;};
  },[modelUrl]);
  return <div className="model-viewer">
    <div ref={host} className="model-canvas" aria-label={`${name} ${t("三维展示", "3D preview")}`} />
    {status!=="ready" && <p role="status" className="model-status">{status==="loading"?t("正在加载三维模型…","Loading 3D model…"):t("三维展示暂不可用，请返回图片或下载模型查看。","3D preview is unavailable. View photos or download the model.")}</p>}
    <div className="model-tools">
      <button type="button" aria-label={t("向左旋转", "Rotate left")} onClick={()=>view.current?.rotate(-.35)}>↶</button>
      <button type="button" aria-label={t("向右旋转", "Rotate right")} onClick={()=>view.current?.rotate(.35)}>↷</button>
      <button type="button" aria-label={t("放大模型", "Zoom in")} onClick={()=>view.current?.zoom(.85)}>＋</button>
      <button type="button" aria-label={t("缩小模型", "Zoom out")} onClick={()=>view.current?.zoom(1.15)}>−</button>
      <button type="button" onClick={()=>view.current?.reset()}>{t("复位", "Reset")}</button>
      <a href={modelUrl} download="T300-building-blocks.glb">{t("下载模型", "Download GLB")}</a>
    </div>
    <p className="model-disclaimer">{t("拖动旋转，滚轮或双指缩放。参考图片重建，非实测模型。", "Drag to orbit, wheel or pinch to zoom. Reference-image reconstruction; not measured CAD.")}</p>
  </div>;
}
