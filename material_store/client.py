"""Read adapter for existing business builders; writes go through domain services."""
from .db import connection
from . import repository as repo


class DatabaseReadClient:
    def __init__(self, source="primary", remote=None, conn=None):
        self.source=source
        self.remote=remote
        self.conn=conn

    def _call(self, operation):
        if self.conn is not None:return operation(self.conn)
        import backend_runtime as runtime
        if runtime.in_request_scope():
            source=runtime.request_state.get('_live_reader')
            if source is not None and getattr(source,'_connection_context',None) is not None:
                return operation(source._connection)
        with connection() as conn:return operation(conn)

    def list_tables(self):
        return self._call(lambda conn:[{"table_id":r[0],"name":r[1]} for r in conn.execute("SELECT table_id,table_name FROM material_meta.tables WHERE source_key=%s ORDER BY table_id",(self.source,))])

    def list_fields(self,table_id):
        return self._call(lambda conn:repo.table(conn,table_id)["fields"])

    def list_records(self,table_id,page_size=500,*,field_names=None):
        def operation(conn):
            info=repo.table(conn,table_id)
            if info["source"]!=self.source:raise ValueError("来源不匹配。")
            import backend_runtime as runtime
            if runtime.request_state.get('_write_conn') is conn and info['name'] in {'物料主数据','文化周边管理库存','文化周边编码及库存数量'}:
                from psycopg import sql
                conn.execute(sql.SQL('SELECT _record_key FROM material_data.{} WHERE NOT _deleted ORDER BY _record_key FOR UPDATE').format(sql.Identifier(info['sql_table']))).fetchall()
            result=repo.business_rows(conn,info,repo.rows(conn,info))
            if field_names is not None:
                result=[{**r,"fields":{k:v for k,v in r["fields"].items() if k in field_names}} for r in result]
            return result
        return self._call(operation)

    def get_record(self,table_id,record_id):
        def operation(conn):
            info=repo.table(conn,table_id)
            if info["source"]!=self.source:raise ValueError("来源不匹配。")
            return repo.business_rows(conn,info,[repo.feishu_record(info,repo.raw_record(conn,info,record_id))])[0]
        return self._call(operation)

    def search_records(self,table_id,field_name,value,page_size=100):
        from .field_registry import scalar_text
        return [r for r in self.list_records(table_id) if scalar_text(r['fields'].get(field_name))==str(value)]

    def discover_schema(self):
        return {"tables":{t["name"]:{"table_id":t["table_id"],"name":t["name"],"fields":{
            f["field_name"]:{"field_id":f["field_id"],"type":f["type"]} for f in self.list_fields(t["table_id"])}}
            for t in self.list_tables()}}

    def __getattr__(self,name):
        if any(x in name for x in ("create_record","update_record","delete_record","create_table","update_table","create_field","update_field")):
            raise RuntimeError("当前阶段的业务写入尚未切换，请使用数据库工作台中开放的编辑字段。")
        if self.remote is None:raise AttributeError(name)
        return getattr(self.remote,name)


class DatabaseWriteClient(DatabaseReadClient):
    """Reuse the proven request builders inside a single PostgreSQL transaction."""
    def __init__(self,conn,source='primary'):
        super().__init__(source,conn=conn)

    def _invalidate(self):
        import backend_runtime as runtime
        reader=runtime.request_state.get('_live_reader')
        if reader is not None:
            reader._rows.clear()
            reader._documents.clear()

    def batch_create_records(self,table_id,records):
        from uuid import uuid4
        from psycopg import sql
        from psycopg.types.json import Jsonb
        import backend_runtime as runtime
        info=repo.table(self.conn,table_id)
        if info['source']!=self.source:raise ValueError('来源不匹配。')
        result=[]
        for fields in records:
            fields=dict(fields)
            if info['name']=='用户权限表' and '用户编号' in fields:
                self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('permission-number',0))")
                used=[str(row['fields'].get('用户编号') or '') for row in repo.rows(self.conn,info)]
                if str(fields['用户编号']) in used:
                    fields['用户编号']=str(max([int(value) for value in used if value.isdigit()] or [0])+1)
            values=repo.source_values(info,fields)
            rid='local_'+uuid4().hex
            self.conn.execute(sql.SQL("INSERT INTO material_data.{} (_record_key,_fields,_baseline,_local_version,_sync_state) VALUES (%s,%s,'{{}}'::jsonb,1,'pending')").format(sql.Identifier(info['sql_table'])),(rid,Jsonb(values)))
            repo.replace_values(self.conn,info,rid,values)
            self.conn.execute("INSERT INTO material_ops.outbox(idempotency_key,lane,table_id,record_key,local_version,patch,operation) VALUES (%s,%s,%s,%s,1,%s,'create')",
                              (str(uuid4()),runtime.request_state.get('_write_lane','ordinary'),table_id,rid,Jsonb(values)))
            self.conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,after_value,local_version,actor_open_id) VALUES (%s,%s,'frontend',%s,1,%s)",
                              (table_id,rid,Jsonb(values),runtime.request_state.get('_write_actor','system')))
            # Feishu maintains reciprocal links remotely. Mirror that behavior
            # locally without creating circular parent/child outbox dependencies.
            for field in info['fields']:
                back=(field.get('property') or {}).get('back_field_id')
                if field['type']!=21 or not back:continue
                target=repo.table(self.conn,field['property']['table_id'])
                for target_id in repo.link_ids(values.get(field['field_id'])):
                    parent=repo.raw_record(self.conn,target,target_id,lock=True)
                    updated=dict(parent['fields'])
                    updated[back]=list(dict.fromkeys([*repo.link_ids(updated.get(back)),rid]))
                    repo.replace_values(self.conn,target,parent['record_id'],updated)
            result.append({'record_id':rid,'fields':fields})
        self._invalidate()
        return result

    def update_record(self,table_id,record_id,fields):
        from uuid import uuid4
        import backend_runtime as runtime
        info=repo.table(self.conn,table_id)
        if info['source']!=self.source:raise ValueError('来源不匹配。')
        old=repo.raw_record(self.conn,info,record_id,lock=True)
        patch=repo.source_values(info,fields)
        changed={fid:value for fid,value in patch.items() if old['fields'].get(fid)!=value}
        if changed:
            created=self.conn.execute("SELECT id,patch FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND operation='create' AND state='pending' ORDER BY created_at LIMIT 1 FOR UPDATE",(table_id,old['record_id'])).fetchone()
            if created and not old['remote_id']:
                from psycopg.types.json import Jsonb
                values=repo.recalculate(info,{**old['fields'],**changed})
                version=old['version']+1
                repo.replace_values(self.conn,info,old['record_id'],values,version=version,state='pending')
                self.conn.execute('UPDATE material_ops.outbox SET patch=%s,local_version=%s WHERE id=%s',(Jsonb({**created[1],**changed}),version,created[0]))
                self.conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,before_value,after_value,local_version,actor_open_id) VALUES (%s,%s,'frontend',%s,%s,%s,%s)",
                    (table_id,old['record_id'],Jsonb(old['fields']),Jsonb(values),version,runtime.request_state.get('_write_actor','system')))
            else:
                repo._save_change(self.conn,info,old,changed,runtime.request_state.get('_write_actor','system'),str(uuid4()),runtime.request_state.get('_write_lane','ordinary'))
        self._invalidate()
        return repo.feishu_record(info,repo.raw_record(self.conn,info,old['record_id']))

    def batch_update_records(self,table_id,records):
        return [self.update_record(table_id,row['record_id'],row.get('fields') or {}) for row in records]


    def delete_record(self,table_id,record_id):
        from psycopg import sql
        from psycopg.types.json import Jsonb
        from uuid import uuid4
        import backend_runtime as runtime
        info=repo.table(self.conn,table_id)
        if info['source']!=self.source:raise ValueError('来源不匹配。')
        prior=repo.raw_record(self.conn,info,record_id)
        key=prior['record_id']
        self.conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('outbox-record:'+table_id+':'+key,))
        old=repo.raw_record(self.conn,info,key,lock=True)
        version=old['version']+1
        # Cancel unpublished writes before deletion; publishers hold the same
        # reconciliation lock, so the transaction also takes a per-record lock.
        self.conn.execute("UPDATE material_ops.outbox SET state='cancelled',last_error='记录已由业务操作删除',claim_token=NULL,lease_until=NULL WHERE table_id=%s AND record_key=%s AND state IN ('pending','retry')",(table_id,key))
        self.conn.execute(sql.SQL("UPDATE material_data.{} SET _deleted=true,_local_version=%s,_sync_state=%s,_updated_at=now() WHERE _record_key=%s").format(sql.Identifier(info['sql_table'])),(version,'pending' if old['remote_id'] else 'synced',key))
        if old['remote_id']:
            self.conn.execute("INSERT INTO material_ops.outbox(idempotency_key,lane,table_id,record_key,local_version,patch,operation) VALUES (%s,%s,%s,%s,%s,'{}','delete')",(str(uuid4()),runtime.request_state.get('_write_lane','admin'),table_id,key,version))
        self.conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,before_value,after_value,local_version,actor_open_id) VALUES (%s,%s,'frontend',%s,%s,%s,%s)",
            (table_id,key,Jsonb(old['fields']),Jsonb({'deleted':True}),version,runtime.request_state.get('_write_actor','system')))

        for field in info['fields']:
            back=(field.get('property') or {}).get('back_field_id')
            if field['type']!=21 or not back:continue
            target=repo.table(self.conn,field['property']['table_id'])
            for target_key in repo.link_ids(old['fields'].get(field['field_id'])):
                try:parent=repo.raw_record(self.conn,target,target_key,lock=True)
                except ValueError:continue
                updated=dict(parent['fields'])
                updated[back]=[linked for linked in repo.link_ids(updated.get(back)) if linked not in {key,old['remote_id']}]
                repo.replace_values(self.conn,target,parent['record_id'],updated)
        self._invalidate()

    def batch_delete_records(self,table_id,record_ids):
        for key in record_ids:self.delete_record(table_id,key)

    def _request(self,method,path,*,params=None,payload=None,**kwargs):
        if method=='POST' and path=='/im/v1/messages' and payload:
            from .effects import defer
            import json
            kind=payload.get('msg_type')
            content=json.loads(payload['content'])
            if kind not in {'text','interactive'}:raise ValueError('不支持的通知类型。')
            remote=defer(self.source,'send_text_message' if kind=='text' else 'send_interactive_message',
                (payload['receive_id'],content['text'] if kind=='text' else content),params or {})
            return {'data':{'message_id':remote}}
        raise RuntimeError('本地事务禁止直接访问飞书 API。')

    def tenant_access_token(self):
        return 'local-database-no-http'

    def __getattr__(self,name):
        from .effects import METHODS,defer
        if name in METHODS:return lambda *args,**kwargs:defer(self.source,name,args,kwargs)
        raise RuntimeError('本地业务事务不允许调用外部接口：'+name)
