"""Administrator-only table view. No arbitrary SQL or authentication bypass."""
from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse
import backend_runtime


def register_database_api(api, require_admin):
    from material_store.db import connection
    from contextlib import contextmanager

    @contextmanager
    def database_connection(*,write=False):
        source=backend_runtime.request_state.get('_live_reader')
        if not write and source is not None and getattr(source,'_connection_context',None) is not None:
            yield source._connection
            return
        if write:backend_runtime.release_database_snapshot()
        with connection() as conn:yield conn

    def store():
        from material_store import repository
        return repository

    def enabled():
        if not backend_runtime.database_reads():raise HTTPException(404,"数据库工作台尚未启用。")

    @api.get('/api/database-image/{media_id}')
    def category_image(media_id:str):
        # The enterprise middleware authenticates this request. Only images
        # attached to a published category are available to ordinary users.
        enabled()
        repo=store()
        from uuid import UUID
        from psycopg import sql
        from psycopg.types.json import Jsonb
        from material_store.media import load_image
        try:
            UUID(media_id)
            with database_connection() as conn:
                category=repo.named_table(conn,'物料品类')
                fid=next(f['field_id'] for f in category['fields'] if f['field_name']=='申领页图片')
                attached=conn.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM material_data.{} WHERE NOT _deleted AND _fields->%s @> %s)').format(sql.Identifier(category['sql_table'])),(fid,Jsonb([{'local_media_id':media_id}]))).fetchone()[0]
                if not attached:raise ValueError('图片未关联至品类。')
                image=load_image(media_id,conn=conn)
            from material_store import image_assets
            return FileResponse(image_assets.local(image),media_type='image/webp',headers=image_assets.HEADERS)
        except (ValueError,TypeError) as exc:raise HTTPException(404,'图片不存在。') from exc

    @api.get('/api/admin/database/reconcile')
    def reconcile_status(_:str=Depends(require_admin)):
        enabled()
        from material_store.manual_reconcile import status
        with database_connection() as conn:return status(conn)

    @api.post('/api/admin/database/reconcile',status_code=202)
    def reconcile_start(body:dict,actor:str=Depends(require_admin)):
        enabled()
        if not backend_runtime.database_worker_enabled():raise HTTPException(403,'后台同步尚未启用。')
        from material_store.manual_reconcile import request
        try:return request(actor,body)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @api.get('/api/admin/database/tables')
    def tables(_:str=Depends(require_admin)):
        enabled()
        repo=store()
        with database_connection() as conn:
            imported=conn.execute("SELECT completed_at FROM material_ops.import_runs WHERE state='done' ORDER BY completed_at DESC LIMIT 1").fetchone()
            pending=conn.execute("SELECT count(*) FROM material_ops.outbox WHERE state IN ('pending','retry','processing')").fetchone()[0]
            conflicts=conn.execute("SELECT count(*) FROM material_ops.outbox WHERE state='conflict'").fetchone()[0]
            heartbeat=conn.execute("SELECT count(*) FROM material_ops.documents WHERE name IN ('worker:ordinary','worker:cultural','worker:admin') AND updated_at>now()-interval '2 minutes'").fetchone()[0]
            return {'tables':repo.list_tables(conn),'imported_at':imported[0].isoformat() if imported else None,
                    'pending_sync':pending,'conflicts':conflicts,'editor_enabled':backend_runtime.database_editor_enabled(),
                    'sync_enabled':backend_runtime.database_worker_enabled(),'workers_healthy':heartbeat==3}

    @api.get('/api/admin/database/tables/{table_id}/records')
    def records(table_id:str,page:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),q:str=Query('',max_length=300),
                sort_field:str|None=None,descending:bool=False,_:str=Depends(require_admin)):
        enabled()
        repo=store()
        with database_connection() as conn:
            try:
                result=repo.browse(conn,table_id,page=page,limit=limit,query=q,sort_field=sort_field,descending=descending)
                if not backend_runtime.database_editor_enabled():
                    for field in result['fields']:
                        field.update(editable=False,read_only_reason='编辑入口尚未启用。')
                result['labels']={}
                from psycopg import sql
                for field in result['fields']:
                    if field['type'] not in {18,21}:continue
                    target_id=(field.get('property') or {}).get('table_id')
                    if not target_id:continue
                    target=repo.table(conn,target_id)
                    ids=list({rid for row in result['records'] for rid in repo.link_ids(row['fields'].get(field['field_id']))})
                    linked=conn.execute(sql.SQL('SELECT _record_key,_remote_id,_fields FROM material_data.{} WHERE _record_key=ANY(%s) OR _remote_id=ANY(%s)').format(sql.Identifier(target['sql_table'])),(ids,ids)).fetchall() if ids else []
                    labels={}
                    for key,remote,values in linked:
                        text=record_label(target,values)
                        labels[key]=text
                        if remote:labels[remote]=text
                    result['labels'][field['field_id']]=labels
                return result
            except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @api.patch('/api/admin/database/tables/{table_id}/records/{record_id}')
    def update(table_id:str,record_id:str,body:dict,actor:str=Depends(require_admin)):
        enabled()
        repo=store()
        if not backend_runtime.database_editor_enabled():raise HTTPException(403,'数据库编辑尚未启用。')
        with database_connection(write=True) as conn:
            try:
                if type(body.get('expected_version')) is not int:raise ValueError('缺少记录版本，请刷新后重试。')
                result=repo.patch_record(conn,table_id,record_id,body.get('patch'),body['expected_version'],body.get('idempotency_key'),actor)
                return {'saved':True,'record':result,'sync_status':'pending','message':'已保存到本地数据库，等待后台同步飞书。'}
            except repo.VersionConflict as exc:raise HTTPException(409,str(exc)) from exc
            except (ValueError,TypeError,ArithmeticError) as exc:raise HTTPException(422,str(exc)) from exc

    @api.get('/api/admin/database/tables/{table_id}/options/{field_id}')
    def options(table_id:str,field_id:str,q:str=Query('',max_length=200),selected:str=Query('',max_length=8000),_:str=Depends(require_admin)):
        enabled()
        repo=store()
        with database_connection() as conn:
            try:
                info=repo.table(conn,table_id)
                field=next((f for f in info['fields'] if f['field_id']==field_id),None)
                if not field:raise ValueError('字段不存在。')
                ids=set(selected.split(',')) if selected else set()
                if len(ids)>100:raise ValueError('一次最多显示 100 个已选项。')
                if field['type']==11:
                    row=conn.execute("SELECT payload FROM material_ops.documents WHERE name='contact_departments_cache.json'").fetchone()
                    people=(row[0].get('users',[]) if row else [])
                    result=[{'id':p['open_id'],'label':p.get('name') or p['open_id']} for p in people if p['open_id'] in ids or q.casefold() in (p.get('name','')+' '.join(p.get('department_paths',[]))).casefold()]
                    result.sort(key=lambda p:p['id'] not in ids)
                    return {'options':result[:100],'multiple':(field.get('property') or {}).get('multiple',True)}
                if field['type'] in {18,21}:
                    target=repo.table(conn,(field.get('property') or {})['table_id'])
                    result=repo.browse(conn,target['table_id'],query=q,limit=100)['records']
                    known={r['record_id'] for r in result}
                    for rid in ids-known:
                        try:result.insert(0,repo.raw_record(conn,target,rid))
                        except ValueError:pass
                    return {'options':[{'id':r['record_id'],'label':record_label(target,r['fields'])} for r in result],
                            'multiple':(field.get('property') or {}).get('multiple',False)}
                raise ValueError('此字段没有人员或关联记录选项。')
            except ValueError as exc:raise HTTPException(422,str(exc)) from exc


def record_label(info,values):
    from material_store.field_registry import scalar_text
    named={f['field_name']:values.get(f['field_id']) for f in info['fields']}
    for name in ['申请单号','物料编码','文化周边编码','货架编号','货架行','物料品类','产品型号','语言种类','战区名称','款式','用户账号']:
        text=scalar_text(named.get(name))
        if text:
            details=[scalar_text(named.get(n)) for n in ['产品型号','语种','战区管理','码数'] if n!=name and named.get(n)]
            return ' · '.join([text]+details)
    primary=next((f for f in info['fields'] if f.get('is_primary')),info['fields'][0])
    return scalar_text(values.get(primary['field_id'])) or '未命名记录'
