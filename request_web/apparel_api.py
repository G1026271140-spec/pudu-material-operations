"""HR/admin-only apparel management; claim-page images remain enterprise-only."""
from fastapi import Depends,HTTPException,Request
from fastapi.responses import FileResponse,Response
from starlette.concurrency import run_in_threadpool
from urllib.parse import unquote
from uuid import UUID
import backend_runtime as runtime
from material_store import apparel,repository as repo
from material_store.db import connection

def register(api,require_hr):
    @api.get('/api/hr/corporate-apparel/catalog')
    def catalog(_:str=Depends(require_hr)):
        runtime.release_database_snapshot()
        with connection() as conn:return apparel.manager_catalog(conn)

    @api.post('/api/hr/corporate-apparel/save')
    def save(body:dict,actor:str=Depends(require_hr)):
        try:return apparel.save(actor,body)
        except repo.VersionConflict as e:raise HTTPException(409,str(e)) from e
        except (ValueError,TypeError) as e:raise HTTPException(422,str(e)) from e

    @api.post('/api/hr/corporate-apparel/images')
    async def upload(request:Request,actor:str=Depends(require_hr)):
        from material_store.media import save_image,MAX_IMAGE_BYTES
        runtime.release_database_snapshot();content=bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content)>MAX_IMAGE_BYTES:raise HTTPException(413,'图片不能超过 6 MB。')
        try:
            result=await run_in_threadpool(save_image,bytes(content),unquote(request.headers.get('X-File-Name','apparel')),actor)
            result['path']='/api/hr/corporate-apparel/images/'+result['local_media_id']
            return result
        except ValueError as e:raise HTTPException(422,str(e)) from e

    @api.get('/api/hr/corporate-apparel/images/{media_id}')
    def preview(media_id:str,actor:str=Depends(require_hr)):
        from material_store.media import load_image
        runtime.release_database_snapshot()
        try:
            UUID(media_id)
            with connection() as conn:
                owner=conn.execute('SELECT owner_open_id FROM material_ops.media WHERE id=%s',(media_id,)).fetchone()
                if not owner or owner[0]!=actor:raise ValueError('图片不属于当前上传人。')
                image=load_image(media_id,conn=conn)
            return FileResponse(image['path'],media_type=image['type'],headers={'Cache-Control':'no-store'})
        except (ValueError,TypeError) as e:raise HTTPException(404,'图片不存在。') from e

    def attached(conn,*,record_id=None,token=None,media_id=None,hr=False):
        rows=repo.rows(conn,apparel.source_info(conn))
        for group in apparel.group_rows(rows):
            if not hr and not group['visible']:continue
            for row in group['records']:
                if record_id and row['record_id']!=record_id:continue
                if any((media_id and item.get('local_media_id')==media_id) or (token and item.get('file_token')==token) for item in row['fields'].get('图片') or [] if isinstance(item,dict)):
                    return row
        raise ValueError('图片未关联至可见款式。')

    @api.get('/api/apparel-local-image/{media_id}')
    def local_image(media_id:str,request:Request):
        from material_store.media import load_image
        try:
            try:require_hr(request);hr=True
            except HTTPException:hr=False
            runtime.release_database_snapshot()
            with connection() as conn:
                attached(conn,media_id=media_id,hr=hr);image=load_image(media_id,conn=conn)
            from material_store import image_assets
            return FileResponse(image_assets.local(image),media_type='image/webp',headers=image_assets.HEADERS)
        except (ValueError,TypeError) as e:raise HTTPException(404,'图片不存在。') from e

    @api.get('/api/apparel-image/{record_id}/{file_token}')
    async def remote_image(record_id:str,file_token:str,request:Request):
        from material_store import image_assets
        def prepare():
            try:require_hr(request);hr=True
            except HTTPException:hr=False
            runtime.release_database_snapshot()
            with connection() as conn:
                row=attached(conn,record_id=record_id,token=file_token,hr=hr)
                info=apparel.source_info(conn);remote_id=repo.raw_record(conn,info,row['record_id'])['remote_id']
            path=image_assets.remote(info,row,remote_id,file_token,('图片',))
            return FileResponse(path,media_type='image/webp',headers=image_assets.HEADERS)
        try:return await image_assets.isolated(prepare)
        except (ValueError,TypeError,KeyError,OSError) as e:raise HTTPException(404,'图片不存在。') from e
