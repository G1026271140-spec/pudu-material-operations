"""One repeatable-read snapshot per HTTP response, released by middleware."""
from material_store.db import connection
from material_store.client import DatabaseReadClient
from request_web.live_data import LiveReader


class PostgresReader(LiveReader):
    def __init__(self):
        super().__init__()
        self._connection_context=connection()
        self._connection=self._connection_context.__enter__()
        self._transaction=self._connection.transaction()
        self._transaction.__enter__()
        try:
            self._connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            imported=self._connection.execute("SELECT max(completed_at) FROM material_ops.import_runs WHERE state='done'").fetchone()[0]
            if imported is None:raise RuntimeError("数据库尚未完成初始数据导入。")
            modified=self._connection.execute("SELECT max(created_at) FROM material_ops.audit").fetchone()[0]
            self.generated_at=max(imported,modified or imported).strftime('%Y-%m-%d %H:%M:%S')
            self.client=DatabaseReadClient('primary',remote=getattr(self.client,'remote',self.client),conn=self._connection)
        except Exception:
            self.close()
            raise

    def close(self):
        if getattr(self,'_connection_context',None) is None:return
        try:
            self._transaction.__exit__(None,None,None)
        finally:
            self._connection_context.__exit__(None,None,None)
            self._connection_context=None

    def prefetch(self,names,*,contacts=False):
        self.table_ids()
        if contacts:self.document('contact_departments_cache.json')
        for name in dict.fromkeys(names):self.rows(name)

    def document(self,name):
        if name=='contact_departments_cache.json':
            if name not in self._documents:
                row=self._connection.execute("SELECT payload FROM material_ops.documents WHERE name=%s",(name,)).fetchone()
                if not row:raise RuntimeError("数据库通讯录未导入。")
                self._documents[name]=row[0]
            return self._documents[name]
        result=super().document(name)
        result['source']='postgresql'
        return result
