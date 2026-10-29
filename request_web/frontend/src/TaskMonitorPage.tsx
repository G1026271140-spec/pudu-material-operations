import { useEffect, useRef, useState } from "react";
import ToastMessage from "./ToastMessage";
import "./task-monitor.css";

type Lang = "zh" | "en";
export type Task = {kind:string;id:string;title:string;subject:string;lane:string;state:string;created_at:string;completed_at:string|null;available_at:string|null;started_at:string|null;attempts:number;last_error:string|null;job_id:string|null};
type Count = {state:string;count:number;kind?:string};
type Snapshot = {entries:Task[];total:number;next_cursor:string;checked_at:string;global_counts:Count[];workers:{name:string;updated_at:string;version:string;healthy:boolean}[]};
type Detail = {task:Task;data:Record<string,unknown>;related:Task[];related_counts:Count[];checked_at:string};
const kinds = ["all","jobs","outbox","effects","reconcile","import"];
const labels:Record<string,[string,string]> = {
  all:["全部类型","All types"],jobs:["业务处理","Business"],outbox:["飞书同步","Feishu sync"],effects:["卡片与通知","Cards & notifications"],reconcile:["定时校验","Reconciliation"],import:["数据导入","Import"],
  active:["进行中","In progress"],pending:["等待处理","Waiting"],processing:["正在执行","Running"],retry:["等待重试","Retry scheduled"],problem:["失败与冲突","Failures & conflicts"],done:["已完成","Completed"],failed:["失败","Failed"],conflict:["同步冲突","Sync conflict"],cancelled:["已取消","Cancelled"],
  send_interactive_message:["发送飞书卡片","Send Feishu card"],update_interactive_message:["更新原卡片","Update original card"],send_text_message:["发送飞书消息","Send Feishu message"],
};
export const taskLabel = (key:string,lang:Lang) => labels[key]?.[lang==="zh"?0:1] || key;
export const taskTime = (value:string|null,lang:Lang) => value ? new Date(value).toLocaleString(lang==="zh"?"zh-CN":"en-GB",{timeZone:"Asia/Shanghai",hour12:false}) : "—";
const json = async (url:string,signal:AbortSignal) => {const r=await fetch(url,{cache:"no-store",signal});const body=await r.json();if(!r.ok)throw Error(typeof body.detail==="string"?body.detail:"任务读取失败");return body;};

export function TaskTable({entries,lang,onOpen}:{entries:Task[];lang:Lang;onOpen:(task:Task)=>void}) {
  const tr=(zh:string,en:string)=>lang==="zh"?zh:en;
  return <div className="task-table-scroll"><table className="task-table"><thead><tr>
    {[tr("任务 / 类型","Task / type"),tr("业务对象","Business record"),tr("状态","Status"),tr("提交时间（北京时间）","Submitted (China time)"),tr("执行次数","Attempts"),tr("处理情况","Result / error"),tr("详情","Details")].map(label=><th key={label} scope="col">{label}</th>)}
  </tr></thead><tbody>{entries.map(task=><tr key={task.kind+task.id}>
    <td><strong>{taskLabel(task.title,lang)}</strong><small>{taskLabel(task.kind,lang)} · {task.id.slice(0,8)}</small></td>
    <td className="task-subject">{task.subject||"—"}</td>
    <td><span className={`task-status ${task.state}`}>{taskLabel(task.state,lang)}</span></td>
    <td className="task-time">{taskTime(task.created_at,lang)}</td><td>{task.attempts}</td>
    <td className={task.last_error?"task-error-cell":"task-result-cell"} title={task.last_error||""}>{task.last_error || (task.completed_at?tr("完成于 ","Completed ")+taskTime(task.completed_at,lang):task.state==="retry"?tr("下次尝试 ","Next attempt ")+taskTime(task.available_at,lang):task.state==="processing"?tr("Worker 正在处理","Worker is processing"):tr("等待 Worker 或前序依赖","Waiting for worker or dependencies"))}</td>
    <td><button type="button" onClick={()=>onOpen(task)}>{tr("查看","View")}</button></td>
  </tr>)}</tbody></table></div>;
}

export default function TaskMonitorPage({lang}:{lang:Lang}) {
  const tr=(zh:string,en:string)=>lang==="zh"?zh:en;
  const [kind,setKind]=useState("all"),[state,setState]=useState("active"),[query,setQuery]=useState(""),[q,setQ]=useState(""),[since,setSince]=useState(""),[until,setUntil]=useState(""),[jobId,setJobId]=useState("");
  const [cursors,setCursors]=useState([""]),[auto,setAuto]=useState(true),[reload,setReload]=useState(0);
  const [data,setData]=useState<Snapshot|null>(null),[dataKey,setDataKey]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [selected,setSelected]=useState<Task|null>(null),[detail,setDetail]=useState<Detail|null>(null),[detailError,setDetailError]=useState("");
  const dialog=useRef<HTMLDialogElement>(null);
  const cursor=cursors[cursors.length-1];
  const key=JSON.stringify([kind,state,q,since,until,jobId,cursor]);
  useEffect(()=>{const timer=setTimeout(()=>{setQ(query);setCursors([""]);},300);return()=>clearTimeout(timer);},[query]);
  useEffect(()=>{
    const controller=new AbortController();let working=false;
    async function refresh() {
      if(working||document.visibilityState==="hidden")return;
      working=true;setBusy(true);
      const params=new URLSearchParams({kind,state,q,cursor,limit:"50"});if(since)params.set("since",since);if(until)params.set("until",until);if(jobId)params.set("job_id",jobId);
      const list=json("/api/admin/tasks?"+params,controller.signal).then(body=>{if(!controller.signal.aborted){setData(body);setDataKey(key);setError("");}}).catch(e=>{if(e.name!=="AbortError")setError(e.message);});
      const item=selected?json(`/api/admin/tasks/${selected.kind}/${selected.id}`,controller.signal).then(body=>{if(!controller.signal.aborted){setDetail(body);setDetailError("");}}).catch(e=>{if(e.name!=="AbortError")setDetailError(e.message);}):Promise.resolve();
      await Promise.all([list,item]);working=false;if(!controller.signal.aborted)setBusy(false);
    }
    void refresh();const timer=auto?setInterval(()=>void refresh(),2000):undefined;
    const visible=()=>{if(document.visibilityState==="visible"&&auto)void refresh();};document.addEventListener("visibilitychange",visible);
    return()=>{controller.abort();if(timer)clearInterval(timer);document.removeEventListener("visibilitychange",visible);};
  },[key,selected?.kind,selected?.id,auto,reload]);
  useEffect(()=>{const node=dialog.current;if(selected&&!node?.open)node?.showModal();if(!selected&&node?.open)node.close();},[selected]);
  function open(task:Task){setSelected(task);setDetail(null);setDetailError("");}
  function filter(action:()=>void){action();setCursors([""]);}
  const current=dataKey===key?data:null;
  const global=(name:string)=>data?.global_counts.find(row=>row.state===name)?.count||0;
  const active=global("pending")+global("processing")+global("retry");
  const count=(mode:string)=>mode==="active"?active:mode==="problem"?global("failed")+global("conflict"):global(mode);
  const relatedTotal=detail?.related_counts.reduce((sum,row)=>sum+row.count,0)||0;
  return <section className="task-monitor" aria-label={tr("后台任务","Background tasks")}>
    {error&&<ToastMessage onClick={()=>setError("")}>{error} · {tr("更新失败，当前数据可能已过期","Refresh failed; displayed data may be stale")}</ToastMessage>}
    <div className="task-live-bar"><strong>{tr("实时任务","Live tasks")}</strong><span className={error?"task-stale":""} role="status">{error?tr("更新失败","Refresh failed"):auto?tr("每 2 秒自动刷新","Refreshes every 2 seconds"):tr("自动刷新已暂停","Auto-refresh paused")}{busy?tr(" · 更新中"," · Refreshing"):""}</span>
      <span className="task-updated">{tr("最近更新：","Updated: ")}{data?taskTime(data.checked_at,lang):"—"}</span>
      <button type="button" onClick={()=>setAuto(!auto)}>{auto?tr("暂停刷新","Pause"):tr("恢复实时","Resume live")}</button><button type="button" disabled={busy} onClick={()=>setReload(n=>n+1)}>{tr("立即刷新","Refresh now")}</button>
    </div>
    <div className="task-overview" aria-label={tr("全局任务概况","Global task status")}>
      {["active","processing","pending","retry","problem","done"].map(mode=><button type="button" key={mode} className={state===mode?"active":""} onClick={()=>filter(()=>setState(mode))}><span>{taskLabel(mode,lang)}</span><b>{count(mode)}</b></button>)}
    </div>
    <div className="task-panel">
      <div className="task-kind-tabs" role="group" aria-label={tr("任务类型","Task type")}>{kinds.map(item=><button type="button" key={item} aria-pressed={kind===item} className={kind===item?"active":""} onClick={()=>filter(()=>setKind(item))}>{taskLabel(item,lang)}</button>)}</div>
      <div className="task-filters"><label className="task-search"><span>{tr("搜索任务","Search tasks")}</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={tr("单号、品类、任务类型或任务 ID","Request, category, task type or ID")}/></label>
        <label><span>{tr("状态","Status")}</span><select value={state} onChange={e=>filter(()=>setState(e.target.value))}>{["active","processing","pending","retry","problem","failed","conflict","done","cancelled","all"].map(item=><option key={item} value={item}>{item==="all"?tr("全部状态","All states"):taskLabel(item,lang)}</option>)}</select></label>
        <label><span>{tr("开始日期","From")}</span><input type="date" value={since} onChange={e=>filter(()=>setSince(e.target.value))}/></label><label><span>{tr("结束日期","To")}</span><input type="date" value={until} onChange={e=>filter(()=>setUntil(e.target.value))}/></label>
        <button type="button" onClick={()=>{setKind("all");setState("active");setQuery("");setQ("");setSince("");setUntil("");setJobId("");setCursors([""]);}}>{tr("重置","Reset")}</button>
      </div>
      {jobId&&<div className="task-related-filter">{tr("仅看关联任务：","Related job: ")}{jobId}<button type="button" onClick={()=>filter(()=>setJobId(""))}>{tr("清除","Clear")}</button></div>}
      <div className="task-list-caption"><span>{current?tr(`符合条件 ${current.total} 条`,`Matching ${current.total} records`):tr("正在读取任务…","Loading tasks…")}</span><small>{tr("业务处理完成后，飞书同步和通知可能仍在执行，可打开详情查看关联记录。","Business completion can precede Feishu sync and notifications. Open details to inspect related work.")}</small></div>
      {current?.entries.length?<TaskTable entries={current.entries} lang={lang} onOpen={open}/>:<div className="task-empty">{!current?tr("正在读取任务…","Loading tasks…"):state==="active"?tr("当前没有符合条件的进行中任务","No matching tasks in progress"):tr("没有符合条件的任务记录","No matching task records")}</div>}
      <div className="task-pagination"><span>{tr(`第 ${cursors.length} 页 · 每页 50 条`,`Page ${cursors.length} · 50 per page`)}</span><button type="button" disabled={cursors.length===1||busy} onClick={()=>setCursors(c=>c.slice(0,-1))}>{tr("上一页","Previous")}</button><button type="button" disabled={!current?.next_cursor||busy} onClick={()=>current?.next_cursor&&setCursors(c=>[...c,current.next_cursor])}>{tr("下一页","Next")}</button></div>
    </div>
    {data&&<details className="task-workers"><summary>{tr("后台服务心跳","Worker heartbeats")} · {data.workers.filter(worker=>worker.healthy).length}/{data.workers.length} {tr("近期有活动","recently active")}</summary><div>{data.workers.map(worker=><p key={worker.name}><b>{worker.name.replace("worker:","")}</b><span className={worker.healthy?"":"task-stale"}>{worker.healthy?tr("近期有活动","Recently active"):tr("心跳已过期，需核对","Stale heartbeat")}</span><time>{taskTime(worker.updated_at,lang)}</time><span>{worker.version}</span></p>)}</div></details>}
    <dialog ref={dialog} className="task-detail" onCancel={()=>setSelected(null)} onClose={()=>setSelected(null)} aria-labelledby="task-detail-title">
      <div className="task-detail-head"><h2 id="task-detail-title">{tr("任务详情","Task details")}</h2><button type="button" onClick={()=>setSelected(null)} aria-label={tr("关闭详情","Close details")}>×</button></div>
      {detailError&&<p className="task-detail-error" role="alert">{detailError} · {tr("详情更新失败","Details refresh failed")}</p>}
      {!detail?<p>{tr("正在读取详情…","Loading details…")}</p>:<>
        <dl className="task-facts"><div><dt>{tr("任务","Task")}</dt><dd>{taskLabel(detail.task.title,lang)}</dd></div><div><dt>{tr("状态","Status")}</dt><dd><span className={`task-status ${detail.task.state}`}>{taskLabel(detail.task.state,lang)}</span></dd></div><div><dt>{tr("业务对象","Business record")}</dt><dd>{detail.task.subject||"—"}</dd></div><div><dt>ID</dt><dd>{detail.task.id}</dd></div><div><dt>{tr("提交时间","Submitted")}</dt><dd>{taskTime(detail.task.created_at,lang)}</dd></div><div><dt>{tr("完成时间","Completed")}</dt><dd>{taskTime(detail.task.completed_at,lang)}</dd></div><div><dt>{tr("执行次数","Attempts")}</dt><dd>{detail.task.attempts}</dd></div><div><dt>{tr("下次尝试","Next attempt")}</dt><dd>{["pending","retry"].includes(detail.task.state)?taskTime(detail.task.available_at,lang):"—"}</dd></div><div><dt>{tr("详情更新","Details updated")}</dt><dd>{taskTime(detail.checked_at,lang)}</dd></div></dl>
        {detail.task.last_error&&<div className="task-detail-error"><strong>{tr("失败原因 / 最近错误","Failure / latest error")}</strong><p>{detail.task.last_error}</p></div>}
        {Object.entries(detail.data).map(([name,value])=><details key={name} className="task-json" open={name==="result"||name==="progress"||name==="summary"}><summary>{({payload:tr("提交内容","Submitted data"),result:tr("处理结果","Result"),patch:tr("同步字段","Synced fields"),progress:tr("执行进度","Progress"),dependencies:tr("同步依赖","Sync dependencies"),summary:tr("校验 / 导入结果","Run result")}[name]||name)}</summary><pre>{JSON.stringify(value,null,2)}</pre></details>)}
        {detail.task.job_id&&<div className="task-related"><div><h3>{tr("关联处理记录","Related work")} · {relatedTotal}</h3><button type="button" onClick={()=>{const id=detail.task.job_id||"";setSelected(null);setJobId(id);setState("all");setKind("all");setQuery("");setQ("");setSince("");setUntil("");setCursors([""]);}}>{tr("查看全部关联记录","View all related work")}</button></div><TaskTable entries={detail.related} lang={lang} onOpen={open}/></div>}
      </>}
    </dialog>
  </section>;
}
