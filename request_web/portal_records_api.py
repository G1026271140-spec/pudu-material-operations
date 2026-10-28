from fastapi import Depends,HTTPException,Request
from uuid import UUID
import backend_runtime as runtime
from material_store import portal_records,user_permissions,repository as repo
from material_store.db import connection

def register(api,require_viewer,require_admin,require_hr):
    @api.get('/api/request-history')
    def history(scope:str='mine',actor:str=Depends(require_viewer)):
        runtime.release_database_snapshot()
        try:
            with connection() as conn,conn.transaction():
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                return portal_records.history(conn,actor,scope)
        except PermissionError as e:raise HTTPException(403,str(e)) from e
        except ValueError as e:raise HTTPException(422,str(e)) from e

    @api.get('/api/admin/user-permissions')
    def permissions(_:str=Depends(require_admin)):
        runtime.release_database_snapshot()
        with connection() as conn,conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return user_permissions.catalog(conn)

    @api.post('/api/admin/user-permissions')
    def save(body:dict,actor:str=Depends(require_admin)):
        try:return user_permissions.save(actor,body)
        except PermissionError as e:raise HTTPException(403,str(e)) from e
        except repo.VersionConflict as e:raise HTTPException(409,str(e)) from e
        except (ValueError,TypeError) as e:raise HTTPException(422,str(e)) from e

    @api.post('/api/request-history/reject-apparel')
    def reject(body:dict,actor:str=Depends(require_hr)):
        try:return portal_records.reject_apparel(actor,body)
        except PermissionError as e:raise HTTPException(403,str(e)) from e
        except (ValueError,TypeError,RuntimeError) as e:raise HTTPException(422,str(e)) from e

    @api.post('/api/request-history/reject-cultural')
    def reject_culture(body:dict,actor:str=Depends(require_hr)):
        try:return portal_records.reject_cultural(actor,body)
        except PermissionError as e:raise HTTPException(403,str(e)) from e
        except (ValueError,TypeError,RuntimeError) as e:raise HTTPException(422,str(e)) from e

    @api.post('/api/admin/user-permissions/directory-refresh')
    def refresh_directory(actor:str=Depends(require_admin)):
        from material_store.contacts import enqueue_refresh
        runtime.release_database_snapshot()
        try:return enqueue_refresh(actor)
        except PermissionError as e:raise HTTPException(403,str(e)) from e

    @api.get('/api/admin/user-permissions/directory-refresh/{job_id}')
    def directory_refresh_status(job_id:UUID,_:str=Depends(require_admin)):
        from material_store.contacts import refresh_status
        runtime.release_database_snapshot()
        try:return refresh_status(job_id)
        except ValueError as e:raise HTTPException(404,str(e)) from e
