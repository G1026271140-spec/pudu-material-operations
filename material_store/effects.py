"""Durable Feishu messages, outside business transactions and retried separately."""
from __future__ import annotations
import json
import logging
import re
import time
from uuid import uuid4
from psycopg import sql
from psycopg.types.json import Jsonb
from .db import connection
from . import repository as repo
import backend_runtime as runtime

METHODS={'send_text_message','send_interactive_message','reply_text_message','reply_interactive_message','update_interactive_message'}
PREFIX='pendingmsg_'

def defer(source,method,args,kwargs):
    conn=runtime.request_state['_write_conn']
    job_id=runtime.request_state.get('_job_id')
    if not job_id:raise RuntimeError('外部通知必须属于持久化业务任务。')
    ordinal=runtime.request_state.get('_effect_ordinal',0)+1
    runtime.request_state['_effect_ordinal']=ordinal
    row=conn.execute('INSERT INTO material_ops.effects(job_id,ordinal,source_key,method,args,kwargs) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
        (job_id,ordinal,source,method,Jsonb(list(args)),Jsonb(kwargs))).fetchone()
    return PREFIX+row[0].hex if method!='update_interactive_message' else None

def resolve(conn,value):
    encoded=json.dumps(value,ensure_ascii=False)
    for token in set(re.findall(r'pendingmsg_[0-9a-f]{32}',encoded)):
        row=conn.execute('SELECT remote_id,state FROM material_ops.effects WHERE id=%s',(token[len(PREFIX):],)).fetchone()
        if not row or row[1]!='done':
            from .outbox_worker import DependencyPending
            raise DependencyPending('通知消息尚未取得飞书 ID。')
        encoded=encoded.replace(token,row[0] or '')
    return json.loads(encoded)

def _replace_alias(conn,token,remote):
    # Only rows with the exact internal alias are locked. Ordinary writes keep
    # their versions; the alias is infrastructure, never a user field change.
    for (tid,) in conn.execute('SELECT table_id FROM material_meta.tables ORDER BY table_id').fetchall():
        info=repo.table(conn,tid)
        rows=conn.execute(sql.SQL('SELECT _record_key,_fields FROM material_data.{} WHERE _fields::text LIKE %s FOR UPDATE').format(sql.Identifier(info['sql_table'])),('%'+token+'%',)).fetchall()
        for key,values in rows:
            repo.replace_values(conn,info,key,json.loads(json.dumps(values,ensure_ascii=False).replace(token,remote)))
    rows=conn.execute('SELECT id,patch FROM material_ops.outbox WHERE patch::text LIKE %s FOR UPDATE',('%'+token+'%',)).fetchall()
    for identity,patch in rows:
        conn.execute('UPDATE material_ops.outbox SET patch=%s WHERE id=%s',(Jsonb(json.loads(json.dumps(patch,ensure_ascii=False).replace(token,remote))),identity))

def run_once(clients):
    token=uuid4()
    with connection() as conn,conn.transaction():
        row=conn.execute("""SELECT id,source_key,method,args,kwargs,attempts,(first_attempt_at<now()-interval '50 minutes') FROM material_ops.effects e
          WHERE ((state IN ('pending','retry') AND available_at<=now()) OR (state='processing' AND lease_until<now()))
          AND NOT EXISTS(SELECT 1 FROM material_ops.effects p WHERE p.job_id=e.job_id AND p.ordinal<e.ordinal AND p.state NOT IN ('done','failed'))
          ORDER BY created_at,ordinal LIMIT 1 FOR UPDATE SKIP LOCKED""").fetchone()
        if row is None:return None
        if row[6] and row[2]!='update_interactive_message':
            conn.execute("UPDATE material_ops.effects SET state='failed',last_error='消息结果需要人工核对，防止超出去重窗口后重复发送',claim_token=NULL,lease_until=NULL WHERE id=%s",(row[0],))
            return {'id':str(row[0]),'state':'failed'}
        conn.execute("UPDATE material_ops.effects SET state='processing',claim_token=%s,lease_until=now()+interval '3 minutes',attempts=attempts+1,first_attempt_at=COALESCE(first_attempt_at,now()) WHERE id=%s",(token,row[0]))
    try:
        with connection() as conn:
            args=resolve(conn,row[3]);kwargs=resolve(conn,row[4])
        client=clients[row[1]]
        if row[2] in {'send_text_message','send_interactive_message'}:
            kind='text' if row[2]=='send_text_message' else 'interactive'
            content={'text':args[1]} if kind=='text' else args[1]
            response=client._request('POST','/im/v1/messages',params={'receive_id_type':kwargs.get('receive_id_type','open_id')},
                payload={'receive_id':args[0],'msg_type':kind,'content':json.dumps(content,ensure_ascii=False),'uuid':str(row[0])})
            remote=str((response.get('data') or {}).get('message_id') or '')
            if not remote:raise RuntimeError('飞书未返回消息 ID。')
        else:
            remote=getattr(client,row[2])(*args,**kwargs) or ''
        with connection() as conn,conn.transaction():
            current=conn.execute('SELECT state,claim_token FROM material_ops.effects WHERE id=%s FOR UPDATE',(row[0],)).fetchone()
            if current!=('processing',token):raise RuntimeError('消息任务租约已改变。')
            _replace_alias(conn,PREFIX+row[0].hex,remote)
            conn.execute("UPDATE material_ops.effects SET state='done',remote_id=%s,completed_at=now(),lease_until=NULL,claim_token=NULL,last_error=NULL WHERE id=%s",(remote,row[0]))
        return {'id':str(row[0]),'state':'done'}
    except Exception as exc:
        # Permission errors are visible failures; no applicant message is
        # silently recorded as sent when Feishu rejects it.
        with connection() as conn:
            conn.execute("UPDATE material_ops.effects SET state=%s,last_error=%s,available_at=now()+interval '30 seconds',lease_until=NULL,claim_token=NULL WHERE id=%s AND claim_token=%s",
                ('failed' if row[5]>=9 else 'retry',type(exc).__name__+': '+str(exc)[:400],row[0],token))
        logging.warning('Effect %s failed: %s',row[0],type(exc).__name__)
        return {'id':str(row[0]),'state':'retry'}

def main():
    if not runtime.database_reads():raise RuntimeError('PostgreSQL mode required')
    import app
    clients={'primary':app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())}
    clients['apparel_admin']=clients['primary']
    logging.basicConfig(level=logging.INFO)
    beat=0
    while True:
        result=run_once(clients)
        if time.monotonic()-beat>10:
            from .jobs import heartbeat
            heartbeat('effects');beat=time.monotonic()
        if result is None:time.sleep(1)

if __name__=='__main__':main()
