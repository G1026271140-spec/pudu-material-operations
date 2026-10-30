import { useEffect, useRef, useState } from 'react';
import ToastMessage from './ToastMessage';

async function json(url:string,init?:RequestInit) {
  const r=await fetch(url,{cache:'no-store',...init});
  if(!r.headers.get('content-type')?.includes('application/json'))throw Error('请重新登录后再试 / Please sign in again');
  const value=await r.json();if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'同步请求失败 / Sync request failed');return value;
}

export default function DatabaseReconcile({lang,blocked,onCompleted}:{lang:'zh'|'en';blocked:boolean;onCompleted:()=>void}) {
  const tr=(zh:string,en:string)=>lang==='zh'?zh:en;
  const [data,setData]=useState<any>(null),[error,setError]=useState(''),[sending,setSending]=useState(false),[confirm,setConfirm]=useState(false);
  const dialog=useRef<HTMLDialogElement>(null),token=useRef(''),lastDone=useRef(''),refresh=useRef(onCompleted);
  refresh.current=onCompleted;
  useEffect(()=>{
    let disposed=false,timer:ReturnType<typeof setTimeout>;
    const load=async()=>{
      if(!document.hidden)try{
        const result=await json('/api/admin/database/reconcile');
        if(disposed)return;
        setData(result);
        const done=result.manual?.state==='done'?result.manual.id:'';
        if(done&&lastDone.current&&lastDone.current!==done)refresh.current();
        if(result.manual)lastDone.current=done||'running';
      }catch(e){if(!disposed)setError(e instanceof Error?e.message:'读取失败');}
      if(!disposed)timer=setTimeout(load,2000);
    };
    void load();return()=>{disposed=true;clearTimeout(timer);};
  },[]);
  useEffect(()=>{if(confirm)dialog.current?.showModal();else dialog.current?.close();},[confirm]);
  const task=data?.manual,active=task&&['pending','retry','processing'].includes(task.state);
  const last=data?.last_run,progress=active?task?.progress:last?.state==='running'?last?.summary:null;
  const running=active||last?.state==='running';
  const manualFailed=task?.state==='failed'&&(!last?.completed_at||new Date(task.created_at).valueOf()>=new Date(last.completed_at).valueOf());
  const stages:Record<string,string>={waiting_lock:tr('等待同步任务释放校验锁','Waiting for synchronization lock'),metadata:tr('正在核对字段定义','Checking field definitions'),source_fetch:tr('正在读取飞书数据','Reading Feishu data'),apply:tr('正在更新本地数据库','Updating local database')};
  async function submit(){
    if(sending)return;setSending(true);setError('');
    if(!token.current)token.current=crypto.randomUUID();
    try{
      const result=await json('/api/admin/database/reconcile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,idempotency_key:token.current})});
      setData(result);lastDone.current='running';token.current='';setConfirm(false);
    }catch(e){setError(e instanceof Error?e.message:'同步请求失败');}finally{setSending(false);}
  }
  return <>
    <div className="database-reconcile" aria-label={tr('飞书数据校验同步','Feishu reconciliation')}>
      <div><strong>{tr('飞书 → 本地数据库','Feishu → local database')}</strong>
        <span role="status">{running?(stages[progress?.stage]||tr('已提交，等待后台执行','Queued for background execution'))+(progress?.total?` · ${progress.fetched}/${progress.total} ${tr('张表','tables')}`:''):manualFailed?tr('上次手动校验失败，请查看后台任务','Last manual run failed; check background tasks'):last?`${last.state==='done'?tr('最近校验完成','Last reconciliation completed'):last.state==='failed'?tr('最近校验失败','Last reconciliation failed'):last.state==='interrupted'?tr('上次校验中断，可重新执行','Previous run interrupted; retry available'):tr('全量校验进行中','Full reconciliation running')} · ${new Date(last.completed_at||last.started_at).toLocaleString(lang==='zh'?'zh-CN':'en-GB')}`:tr('可手动核对全部来源表，日常 03:00 校验照常执行','Reconcile all source tables; the daily 03:00 run remains scheduled')}</span>
        {last?.state==='failed'&&last.summary?.reason==='lock_timeout'&&<small>{tr('等待同步任务释放校验锁超时；本次未应用数据，可稍后重试。','Timed out waiting for synchronization; no data was applied. Retry later.')}</small>}
        {!running&&last?.state==='done'&&<small>{last.summary?.tables} {tr('张表','tables')} · {tr('更新','Updated')} {last.summary?.changed||0} · {tr('新增','Created')} {last.summary?.created||0} · {tr('源表已删除','Source deleted')} {last.summary?.deleted||0} · {tr('冲突留档','Conflicts recorded')} {last.summary?.conflicts||0}</small>}
      </div>
      <button type="button" className="primary" disabled={blocked||sending||!data||running||data?.full_run_active} onClick={()=>setConfirm(true)}>{running?tr('校验同步中…','Reconciling…'):tr('手动校验同步飞书','Reconcile from Feishu')}</button>
    </div>
    {error&&<ToastMessage role="alert">{error}<button onClick={()=>setError('')}>×</button></ToastMessage>}
    <dialog ref={dialog} className="database-dialog" aria-labelledby="reconcile-title" onCancel={e=>{e.preventDefault();if(!sending)setConfirm(false);}}>
      <header><h3 id="reconcile-title">{tr('以飞书为准校验同步全部数据','Reconcile all data using Feishu as authority')}</h3></header>
      <p>{tr('将读取全部飞书来源表，核对字段后更新本地数据库，包含飞书手动修改、清空和删除的记录。尚未获得飞书记录 ID 的本地新建记录会保留。','All Feishu source tables will be read and validated before updating the local database, including manual changes, cleared fields and deleted records. Local new records without Feishu IDs are retained.')}</p>
      <p>{tr('与飞书冲突的旧本地同步任务会保留冲突记录，不再覆盖飞书。任务在后台执行，可在这里或“后台任务”查看进度。','Older local writes that conflict with Feishu are recorded as conflicts. The run executes in the background; progress is available here and in Background tasks.')}</p>
      <footer><button disabled={sending} onClick={()=>setConfirm(false)}>{tr('取消','Cancel')}</button><button className="primary" disabled={sending} onClick={()=>void submit()}>{sending?tr('正在提交…','Submitting…'):tr('确定校验同步','Confirm reconciliation')}</button></footer>
    </dialog>
  </>;
}
