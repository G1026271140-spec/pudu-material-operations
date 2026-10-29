"""Administrator-only GET endpoints for local queues."""
from datetime import date
from uuid import UUID
from fastapi import Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
import backend_runtime as runtime


def register(api, require_admin):
    from material_store import task_monitor as monitor
    from material_store.db import connection

    def read(callback):
        if not runtime.database_reads():raise HTTPException(404,'本地任务查看尚未启用。')
        runtime.release_database_snapshot()
        try:
            with connection() as conn,conn.transaction():
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                conn.execute("SET LOCAL statement_timeout='4000ms'")
                result=callback(conn)
            return JSONResponse(jsonable_encoder(result),headers={'Cache-Control':'no-store'})
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc

    @api.get('/api/admin/tasks')
    def tasks(kind:str='all',state:str='active',q:str=Query('',max_length=200),
              since:date|None=None,until:date|None=None,job_id:UUID|None=None,
              cursor:str=Query('',max_length=400),limit:int=Query(50,ge=1,le=100),_:str=Depends(require_admin)):
        return read(lambda conn:monitor.list_tasks(conn,kind=kind,state=state,q=q,since=since,until=until,job_id=job_id,cursor=cursor,limit=limit))

    @api.get('/api/admin/tasks/{kind}/{identity}')
    def task(kind:str,identity:UUID,_:str=Depends(require_admin)):
        return read(lambda conn:monitor.detail(conn,kind,str(identity)))
