from fastapi import Depends,HTTPException
from fastapi.responses import FileResponse
import backend_runtime as runtime
from material_store import order_packing as exports,repository as repo
from material_store.db import connection


def register(api,require_admin):
    def enabled():
        if not runtime.database_reads():raise HTTPException(404,'本地数据库尚未启用。')
    def fail(exc):return HTTPException(409 if isinstance(exc,repo.VersionConflict) else 403 if isinstance(exc,PermissionError) else 422,str(exc))

    @api.get('/api/admin/order-packing/catalog')
    def catalog(_:str=Depends(require_admin)):
        enabled();runtime.release_database_snapshot()
        with connection() as conn,conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return exports.read_source(conn)[0]

    @api.post('/api/admin/order-packing/preview')
    def preview(body:dict,_:str=Depends(require_admin)):
        enabled();runtime.release_database_snapshot()
        try:
            with connection() as conn,conn.transaction():
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                snapshot=exports.prepare(conn,body)
            return {**exports.views(snapshot),'preview_hash':exports.digest(snapshot)}
        except (ValueError,TypeError,ArithmeticError) as exc:raise fail(exc) from exc

    @api.post('/api/admin/order-packing/generate',status_code=202)
    def generate(body:dict,actor:str=Depends(require_admin)):
        enabled()
        if not runtime.database_worker_enabled():raise HTTPException(403,'后台生成服务尚未启用。')
        try:return exports.enqueue(actor,body)
        except (ValueError,TypeError,PermissionError) as exc:raise fail(exc) from exc

    @api.get('/api/admin/order-packing/history')
    def history(_:str=Depends(require_admin)):
        enabled();runtime.release_database_snapshot()
        with connection() as conn:return {'entries':exports.history(conn)}

    @api.get('/api/admin/order-packing/{task_id}/download')
    def download(task_id:str,_:str=Depends(require_admin)):
        enabled();runtime.release_database_snapshot()
        try:
            with connection() as conn:path,filename=exports.download(conn,task_id)
            return FileResponse(path,filename=filename,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Cache-Control':'private, no-store'})
        except (ValueError,LookupError) as exc:raise HTTPException(404,str(exc)) from exc
