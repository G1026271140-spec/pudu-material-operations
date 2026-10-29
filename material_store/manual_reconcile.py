"""Admin-requested Feishu-authoritative reconciliation, executed by inbound worker."""
from uuid import UUID
from psycopg.types.json import Jsonb
from .db import connection

TASK = '手动飞书校验同步'


def status(conn):
    row = conn.execute("SELECT id,state,result,last_error,created_at,completed_at FROM material_ops.jobs WHERE task_type=%s ORDER BY created_at DESC LIMIT 1", (TASK,)).fetchone()
    latest = None
    if row:
        latest = dict(zip(('id','state','progress','error','created_at','completed_at'),row))
        for name in ('id','created_at','completed_at'):
            if latest[name] is not None: latest[name] = str(latest[name])
        running=conn.execute("SELECT EXISTS(SELECT 1 FROM material_ops.documents d JOIN pg_stat_activity p ON p.pid=(d.payload->>'pid')::int AND p.backend_start=(d.payload->>'backend_start')::timestamptz WHERE d.name=%s)",('task-activity:'+str(row[0]),)).fetchone()[0]
        if latest['state'] in {'pending','retry'} and running:
            latest['state'] = 'processing'
    run = conn.execute('SELECT id,state,started_at,completed_at,summary FROM material_ops.reconcile_runs ORDER BY started_at DESC LIMIT 1').fetchone()
    busy=not conn.execute("SELECT pg_try_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))").fetchone()[0]
    last=dict(zip(('id','state','started_at','completed_at','summary'), [str(v) if i in {0,2,3} and v is not None else v for i,v in enumerate(run)])) if run else None
    if last and last['state']=='running' and not busy:last['state']='interrupted'
    return {'manual':latest,'last_run':last,'full_run_active':busy}


def request(actor, body):
    if not isinstance(body,dict) or set(body) != {'confirmed','idempotency_key'} or body['confirmed'] is not True:
        raise ValueError('请确认以飞书为准校验同步全部数据。')
    try: token = str(UUID(body['idempotency_key']))
    except (ValueError,TypeError,AttributeError): raise ValueError('同步提交标识无效。') from None
    if not actor: raise ValueError('缺少管理员身份。')
    import backend_runtime
    from .jobs import enqueue
    backend_runtime.release_database_snapshot()
    with connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('manual-feishu-reconciliation',0))")
        prior = conn.execute('SELECT id,payload FROM material_ops.jobs WHERE idempotency_key=%s',('manual-reconcile:'+token,)).fetchone()
        if prior:
            if prior[1].get('actor') != actor: raise ValueError('同步标识已被其他管理员使用。')
            return {'task_id':str(prior[0]),'reused':True,**status(conn)}
        active = conn.execute("SELECT id FROM material_ops.jobs WHERE task_type=%s AND state IN ('pending','retry') ORDER BY created_at LIMIT 1",(TASK,)).fetchone()
        if active:return {'task_id':str(active[0]),'reused':True,**status(conn)}
        # Daily and manual executions share the same lock. Do not queue behind an active full run.
        if not conn.execute("SELECT pg_try_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))").fetchone()[0]:
            raise ValueError('全量数据校验正在进行，请等待当前任务结束。')
        task,_ = enqueue(TASK,'manual-reconcile:'+token,{'actor':actor,'authority':'feishu'},conn=conn)
        return {'task_id':task.task_id,'reused':False,**status(conn)}


def execute(guard, job_id, payload):
    from . import reconcile
    def progress(value):
        guard.execute('UPDATE material_ops.jobs SET result=%s WHERE id=%s',(Jsonb(value),job_id))
    return reconcile.run(reconcile.clients(), progress=progress, trigger='manual', actor=payload['actor'], db_connection=guard)
