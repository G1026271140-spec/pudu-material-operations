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
