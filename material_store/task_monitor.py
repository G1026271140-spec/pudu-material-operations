"""Bounded, read-only task inspection. No worker actions or remote requests."""
import base64
from datetime import date, datetime, time, timedelta, timezone
import json
import re
from uuid import UUID

from psycopg import sql
from psycopg.rows import dict_row

KINDS = ('jobs', 'outbox', 'effects', 'reconcile', 'import')
STATES = ('all', 'active', 'problem', 'pending', 'processing', 'retry', 'done', 'failed', 'conflict', 'cancelled')
CN = timezone(timedelta(hours=8))
LABEL_FIELDS = ('申请单号', '明细编号', '物料编码', '文化周边编码', '物料品类', '产品型号', '款式')


def redact(value, depth=0):
    if depth > 8:
        return '…'
    if isinstance(value, dict):
        return {str(k): '[已隐藏]' if re.search(r'password|passwd|secret|token|authorization|cookie|credential|密码|密钥', str(k), re.I)
                else redact(v, depth+1) for k,v in list(value.items())[:100]}
    if isinstance(value, list):
        return [redact(v, depth+1) for v in value[:100]]
    if isinstance(value, str):
        return re.sub(r'(?i)((?:password|passwd|app_secret|access_token|authorization|cookie)\s*[=:]\s*)[^\s&,;]+', r'\1[已隐藏]', value[:8000])
    return value


def _rows(conn, query, params=()):
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, params).fetchall()


def _labels(conn, *, keys=None, query=None):
    definitions = _rows(conn, """SELECT t.table_id,t.sql_table,f.field_id,f.field_name FROM material_meta.tables t
        JOIN material_meta.fields f USING(table_id) WHERE f.field_name=ANY(%s) ORDER BY t.table_id""", (list(LABEL_FIELDS),))
    tables = {}
    for row in definitions:
        tables.setdefault((row['table_id'],row['sql_table']),{})[row['field_name']] = row['field_id']
    result=[]
    for (tid,table),fields in tables.items():
        expressions=[sql.SQL("NULLIF(_fields->>{},'')").format(sql.Literal(fields[name])) for name in LABEL_FIELDS if name in fields]
        label=sql.SQL("COALESCE({},'')").format(sql.SQL(',').join(expressions))
        condition=sql.SQL('(_record_key=ANY(%s) OR _remote_id=ANY(%s))') if keys is not None else sql.SQL("strpos(lower({}),lower(%s))>0").format(label)
        params=(keys,keys) if keys is not None else (query,)
        result.extend(_rows(conn,sql.SQL("SELECT {}::text table_id,_record_key,_remote_id,{} subject FROM material_data.{} WHERE NOT _deleted AND ").format(sql.Literal(tid),label,sql.Identifier(table))+condition,params))
    return result


def _enrich(conn, items):
    keys=list({str(row.get('subject') or '') for row in items}|{str(row.get('record_key') or '') for row in items})
    labels=_labels(conn,keys=[key for key in keys if key]) if any(keys) else []
    for row in items:
        match=next((label for label in labels if row.get('subject') in (label['_record_key'],label['_remote_id']) or
            (row.get('table_id')==label['table_id'] and row.get('record_key') in (label['_record_key'],label['_remote_id']))),None)
        if match:row['subject']=match['subject']
    return items


def _feed(conn):
    return sql.SQL('''WITH activity AS MATERIALIZED (
        SELECT d.payload->>'job_id' job_id,d.payload FROM material_ops.documents d
        JOIN pg_stat_activity p ON p.pid=(d.payload->>'pid')::integer
          AND p.backend_start=(d.payload->>'backend_start')::timestamptz
        WHERE strpos(d.name,'task-activity:')=1
    ), job_info AS MATERIALIZED (
        SELECT j.*,a.payload activity,
        COALESCE(NULLIF(j.payload#>>'{{draft,request_no}}',''),NULLIF(j.payload->>'request_no',''),
          NULLIF(j.payload#>>'{{draft,restock_no}}',''),NULLIF(j.payload#>>'{{draft,category}}',''),
          NULLIF(j.payload#>>'{{draft,category_name}}',''),NULLIF(j.payload#>>'{{draft,name}}',''),
          NULLIF(j.payload#>>'{{draft,request_id}}',''),NULLIF(j.payload->>'request_id',''),
          NULLIF(j.payload->>'record_id',''),'') subject_key FROM material_ops.jobs j
        LEFT JOIN activity a ON a.job_id=j.id::text
    ), feed AS (
        SELECT 'jobs'::text kind,j.id::text id,j.task_type title,j.lane,
          CASE WHEN j.activity IS NOT NULL AND j.state IN ('pending','retry') THEN 'processing' ELSE j.state END state,
          j.created_at,j.completed_at,j.available_at,j.attempts,j.last_error,j.id::text job_id,
          ''::text table_id,''::text record_key,COALESCE(j.subject_key,'') subject,
          j.activity->>'started_at' started_at FROM job_info j
        UNION ALL
        SELECT 'outbox',o.id::text,COALESCE(t.table_name,o.table_id)||' · '||o.operation,o.lane,o.state,
          o.created_at,o.completed_at,o.available_at,o.attempts,o.last_error,o.job_id,o.table_id,o.record_key,
          COALESCE(NULLIF(j.subject_key,''),o.record_key),NULL FROM material_ops.outbox o
        LEFT JOIN material_meta.tables t ON t.table_id=o.table_id
        LEFT JOIN job_info j ON j.id::text=o.job_id
        UNION ALL
        SELECT 'effects',e.id::text,e.method,COALESCE(j.lane,'admin'),e.state,
          e.created_at,e.completed_at,e.available_at,e.attempts,e.last_error,e.job_id::text,'','',
          COALESCE(j.subject_key,''),e.first_attempt_at::text FROM material_ops.effects e
        LEFT JOIN job_info j ON j.id=e.job_id
        UNION ALL
        SELECT 'reconcile',r.id::text,'每日飞书校验','system',CASE WHEN r.state='running' THEN 'processing' ELSE r.state END,
          r.started_at,r.completed_at,NULL,0,CASE WHEN r.state='failed' THEN r.summary::text ELSE NULL END,
          NULL,'','',r.source_authority,NULL FROM material_ops.reconcile_runs r
        UNION ALL
        SELECT 'import',i.id::text,'数据导入','system',CASE WHEN i.state='running' THEN 'processing' ELSE i.state END,
          i.started_at,i.completed_at,NULL,0,CASE WHEN i.state='failed' THEN i.summary::text ELSE NULL END,
          NULL,'','','',NULL FROM material_ops.import_runs i
    ) ''')


def _cursor(value):
    try:
        raw=json.loads(base64.urlsafe_b64decode(value).decode())
        if not isinstance(raw,list) or len(raw)!=3 or raw[2] not in KINDS:
            raise ValueError()
        return datetime.fromisoformat(raw[0]),str(UUID(raw[1])),raw[2]
    except Exception as exc:
        raise ValueError('分页标识无效，请刷新列表。') from exc


def _where(kind, state, q, since, until, job_id, search_keys):
    if kind not in ('all',*KINDS) or state not in STATES:
        raise ValueError('不支持的任务类型或状态。')
    clauses=['true'];params=[]
    if kind!='all':clauses.append('kind=%s');params.append(kind)
    if state=='active':clauses.append("state IN ('pending','processing','retry')")
    elif state=='problem':clauses.append("state IN ('failed','conflict')")
    elif state!='all':clauses.append('state=%s');params.append(state)
    if q:
        clauses.append("(strpos(lower(concat_ws(' ',id,title,subject,record_key,job_id)),lower(%s))>0 OR subject=ANY(%s) OR record_key=ANY(%s))");params.extend([q.strip(),search_keys,search_keys])
    if since:clauses.append('created_at>=%s');params.append(datetime.combine(since,time(),CN))
    if until:clauses.append('created_at<%s');params.append(datetime.combine(until+timedelta(days=1),time(),CN))
    if since and until and since>until:raise ValueError('开始日期不能晚于结束日期。')
    if job_id:clauses.append('job_id=%s');params.append(str(UUID(str(job_id))))
    return ' AND '.join(clauses),params


def list_tasks(conn, *, kind='all',state='active',q='',since=None,until=None,job_id=None,cursor='',limit=50):
    if not 1<=limit<=100 or len(q)>200 or len(cursor)>400:raise ValueError('查询范围无效。')
    prefix=_feed(conn)
    search_keys=list({key for row in _labels(conn,query=q.strip()) for key in (row['_record_key'],row['_remote_id']) if key}) if q.strip() else []
    where,params=_where(kind,state,q,since,until,job_id,search_keys)
    counts=_rows(conn,prefix+sql.SQL('SELECT kind,state,count(*) count FROM feed WHERE '+where+' GROUP BY kind,state'),params)
    paged=where;page_params=list(params)
    if cursor:
        paged+=' AND (created_at,id,kind)<(%s,%s,%s)';page_params.extend(_cursor(cursor))
    entries=_rows(conn,prefix+sql.SQL('SELECT * FROM feed WHERE '+paged+' ORDER BY created_at DESC,id DESC,kind DESC LIMIT %s'),[*page_params,limit+1])
    next_cursor=''
    if len(entries)>limit:
        entries=entries[:limit];last=entries[-1]
        next_cursor=base64.urlsafe_b64encode(json.dumps([last['created_at'].isoformat(),last['id'],last['kind']]).encode()).decode()
    _enrich(conn,entries)
    global_counts=_rows(conn,prefix+sql.SQL('SELECT state,count(*) count FROM feed GROUP BY state'))
    workers=_rows(conn,"SELECT name,updated_at,payload->>'version' version,updated_at>clock_timestamp()-interval '2 minutes' healthy FROM material_ops.documents WHERE strpos(name,'worker:')=1 ORDER BY name")
    return {'entries':[{**row,'last_error':redact(row['last_error'])} for row in entries],
            'total':sum(row['count'] for row in counts),'counts':counts,'global_counts':global_counts,
            'workers':workers,'next_cursor':next_cursor,'checked_at':datetime.now(timezone.utc).isoformat(),'refresh_seconds':2}


def detail(conn, kind, identity):
    if kind not in KINDS:raise ValueError('任务类型不存在。')
    identity=str(UUID(identity))
    items=_rows(conn,_feed(conn)+sql.SQL('SELECT * FROM feed WHERE kind=%s AND id=%s'),(kind,identity))
    if not items:raise LookupError('任务不存在。')
    item=_enrich(conn,items)[0];data={}
    if kind=='jobs':
        data=_rows(conn,'SELECT payload,result FROM material_ops.jobs WHERE id=%s',(identity,))[0]
        active=_rows(conn,"SELECT payload->'progress' progress FROM material_ops.documents WHERE name=%s",('task-activity:'+identity,))
        if item['state']=='processing' and active:data['progress']=active[0]['progress']
    elif kind=='outbox':
        data=_rows(conn,'SELECT operation,local_version,patch,lease_until FROM material_ops.outbox WHERE id=%s',(identity,))[0]
        names={r['field_id']:r['field_name'] for r in _rows(conn,'SELECT field_id,field_name FROM material_meta.fields WHERE table_id=%s',(item['table_id'],))}
        data['patch']={names.get(k,k):v for k,v in data['patch'].items()}
    elif kind=='effects':
        data=_rows(conn,'SELECT method,args,kwargs,remote_id,lease_until FROM material_ops.effects WHERE id=%s',(identity,))[0]
        ids=(data.get('kwargs') or {}).get('_outbox_ids',[])
        data['dependencies']=_rows(conn,'SELECT id,state,last_error FROM material_ops.outbox WHERE id::text=ANY(%s)',(ids,)) if isinstance(ids,list) else []
    else:
        # kind is checked against a closed enum before selecting a table.
        table='reconcile_runs' if kind=='reconcile' else 'import_runs'
        data=_rows(conn,sql.SQL('SELECT summary FROM material_ops.{} WHERE id=%s').format(sql.Identifier(table)),(identity,))[0]
    related=[];related_counts=[]
    if item['job_id']:
        prefix=_feed(conn)
        related=_rows(conn,prefix+sql.SQL('SELECT * FROM feed WHERE job_id=%s ORDER BY created_at,id,kind LIMIT 100'),(item['job_id'],))
        related_counts=_rows(conn,prefix+sql.SQL('SELECT kind,state,count(*) count FROM feed WHERE job_id=%s GROUP BY kind,state'),(item['job_id'],))
    _enrich(conn,related)
    return redact({'task':item,'data':data,'related':related,'related_counts':related_counts,'checked_at':datetime.now(timezone.utc).isoformat()})
