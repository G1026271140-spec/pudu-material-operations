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
            result=repo.rows(conn,info)
            if field_names is not None:
                result=[{**r,"fields":{k:v for k,v in r["fields"].items() if k in field_names}} for r in result]
            return result
        return self._call(operation)

    def get_record(self,table_id,record_id):
        def operation(conn):
            info=repo.table(conn,table_id)
            if info["source"]!=self.source:raise ValueError("来源不匹配。")
            return repo.feishu_record(info,repo.raw_record(conn,info,record_id))
        return self._call(operation)

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

    def batch_create_records(self,table_id,records):
        from uuid import uuid4
        from psycopg import sql
        from psycopg.types.json import Jsonb
        import backend_runtime as runtime
        info=repo.table(self.conn,table_id)
        if info['source']!=self.source:raise ValueError('来源不匹配。')
        result=[]
        for fields in records:
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
        return result

    def update_record(self,table_id,record_id,fields):
        from uuid import uuid4
        import backend_runtime as runtime
        info=repo.table(self.conn,table_id)
        old=repo.raw_record(self.conn,info,record_id,lock=True)
        patch=repo.source_values(info,fields)
        changed={fid:value for fid,value in patch.items() if old['fields'].get(fid)!=value}
        if changed:
            created=self.conn.execute("SELECT id,patch FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND operation='create' AND state='pending' ORDER BY created_at LIMIT 1",(table_id,old['record_id'])).fetchone()
            if created and not old['remote_id']:
                from psycopg.types.json import Jsonb
                values=repo.recalculate(info,{**old['fields'],**changed})
                repo.replace_values(self.conn,info,old['record_id'],values)
                self.conn.execute('UPDATE material_ops.outbox SET patch=%s WHERE id=%s',(Jsonb({**created[1],**changed}),created[0]))
            else:
                repo._save_change(self.conn,info,old,changed,runtime.request_state.get('_write_actor','system'),str(uuid4()),runtime.request_state.get('_write_lane','ordinary'))
        return repo.feishu_record(info,repo.raw_record(self.conn,info,old['record_id']))

    def batch_update_records(self,table_id,records):
        return [self.update_record(table_id,row['record_id'],row.get('fields') or {}) for row in records]

    def delete_record(self,table_id,record_id):
        from psycopg import sql
        info=repo.table(self.conn,table_id)
        row=repo.raw_record(self.conn,info,record_id)
        if row['remote_id']:raise ValueError('业务记录不能在申请事务中删除。')
        self.conn.execute('DELETE FROM material_ops.outbox WHERE table_id=%s AND record_key=%s',(table_id,record_id))
        self.conn.execute(sql.SQL('DELETE FROM material_data.{} WHERE _record_key=%s').format(sql.Identifier(info['sql_table'])),(record_id,))
