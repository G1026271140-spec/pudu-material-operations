"""Persist application submissions before any Feishu network request."""
from __future__ import annotations

import backend_runtime as runtime
import hashlib,json
from psycopg.types.json import Jsonb
from .db import connection


def submit_groups(standard=None,cultural=None):
    import app
    standard=standard or None;cultural=cultural or None
    if not standard and not cultural:raise ValueError('申请没有可提交的物料。')
    runtime.release_database_snapshot()
    results=[]
    with connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        runtime.request_state['_write_conn']=conn
        from request_web.live_data import LiveReader
        runtime.request_state['_live_reader']=LiveReader()
        try:
            # The same token is serialized across HTTP processes. This check
            # precedes quota evaluation, so retries never reserve quota twice.
            for payload,_ in (group for group in (standard,cultural) if group):
                token=str(payload.get('submission_token') or '')
                if not token:raise ValueError('缺少申请提交标识。')
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('submission:'+token,))
            hashes={}
            for payload,lines in (group for group in (standard,cultural) if group):
                token=payload['submission_token']
                stable={k:v for k,v in payload.items() if k not in {'accepted_at_ms','accepted_date'}}
                digest=hashlib.sha256(json.dumps({'payload':stable,'lines':lines},sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
                hashes[token]=digest
                prior=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',('submission:'+token,)).fetchone()
                if prior and prior[0].get('hash')!=digest:
                    raise ValueError('同一提交标识已经用于不同申请内容。')
            if standard:
                existing=app.find_completed_submission(standard[0]['submission_token'])
                if existing:
                    results.append({'request_no':app.feishu_text(existing[0]['fields'],'申请单号'),'line_count':existing[1],'created':False,'lane':'ordinary'})
                    standard=None
            if cultural:
                existing=app.find_completed_submission(cultural[0]['submission_token'])
                if existing:
                    results.append({'request_no':app.feishu_text(existing[0]['fields'],'申请单号'),'line_count':existing[1],'created':False,'lane':'cultural'})
                    cultural=None
            if standard:
                payload,lines=standard
                runtime.request_state['_write_lane']='ordinary'
                runtime.request_state['_write_actor']=payload.get('submitter_open_id') or payload.get('requester_open_id')
                requester=payload.get('requester_open_id') or ''
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('user-permission:'+requester,))
                app.ensure_requester_sales_permission(payload)
                number,count,created=app.submit_feishu_material_request(payload,lines)
                results.append({'request_no':number,'line_count':count,'created':created,'lane':'ordinary'})
            if cultural:
                payload,lines=cultural
                runtime.request_state['_write_lane']='cultural'
                runtime.request_state['_write_actor']=payload.get('submitter_open_id') or payload.get('requester_open_id')
                requester=payload.get('requester_open_id') or ''
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('user-permission:'+requester,))
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('culture-quota:'+requester,))
                for line in sorted(lines,key=lambda r:(r.get('product',''),r.get('model',''),r.get('region',''))):
                    resource='culture-stock:'+str(line.get('product'))+':'+str(line.get('model'))+':'+str(line.get('region'))
                    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(resource,))
                from psycopg import sql
                from . import repository as repo
                stock=repo.named_table(conn,app.CULTURAL_MATERIAL_TABLE_NAME)
                names={f['field_name']:f['field_id'] for f in stock['fields']}
                for line in sorted(lines,key=lambda r:(r.get('product',''),r.get('model',''),r.get('region',''))):
                    conn.execute(sql.SQL("SELECT _record_key FROM material_data.{} WHERE NOT _deleted AND _fields->>%s=%s AND _fields->>%s=%s AND _fields->>%s=%s ORDER BY _record_key FOR UPDATE").format(sql.Identifier(stock['sql_table'])),
                                 (names['物料品类'],line['product'],names['产品型号'],line['model'],names['战区管理'],line['region'])).fetchall()
                quota=app.cultural_request_quota_snapshot(payload,lines)
                if not quota['allowed']:
                    raise ValueError('文化周边申领已超过申请人额度。')
                number,count,created=app.submit_feishu_cultural_request(payload,lines)
                app.update_cultural_request_cumulative_quantity(quota['permission_record_id'],quota['target_quantity'],quota['target_jacket_quantity'])
                results.append({'request_no':number,'line_count':count,'created':created,'lane':'cultural'})
            for token,digest in hashes.items():
                conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO NOTHING",
                             ('submission:'+token,Jsonb({'hash':digest})))
        finally:
            for name in ('_write_conn','_write_lane','_write_actor','_live_reader'):
                runtime.request_state.pop(name,None)
    return results
