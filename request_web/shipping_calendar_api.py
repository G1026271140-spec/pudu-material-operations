"""Administrator shipping calendar and request-scoped image access."""
from urllib.parse import unquote
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

import backend_runtime as runtime
from material_store import repository as repo, shipping_calendar as shipping
from material_store.db import connection


def register(api, require_admin):
    @api.get('/api/admin/shipping-calendar')
    def catalog(_: str = Depends(require_admin)):
        runtime.release_database_snapshot()
        with connection() as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return shipping.catalog(conn)

    @api.post('/api/admin/shipping-calendar/save')
    def save(body: dict, actor: str = Depends(require_admin)):
        try:
            return shipping.save(actor, body)
        except repo.VersionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.post('/api/admin/shipping-calendar/images')
    async def upload(request: Request, actor: str = Depends(require_admin)):
        from material_store.media import save_image, MAX_IMAGE_BYTES
        runtime.release_database_snapshot()
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_IMAGE_BYTES:
                raise HTTPException(413, '单张发货图片不能超过 6 MB。')
        try:
            image = await run_in_threadpool(save_image, bytes(content), unquote(request.headers.get('X-File-Name', 'shipping')), actor)
            image['path'] = '/api/admin/shipping-calendar/uploads/' + image['local_media_id']
            return image
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get('/api/admin/shipping-calendar/uploads/{media_id}')
    def preview(media_id: str, actor: str = Depends(require_admin)):
        from material_store.media import load_image
        runtime.release_database_snapshot()
        try:
            UUID(media_id)
            with connection() as conn:
                owner = conn.execute('SELECT owner_open_id FROM material_ops.media WHERE id=%s', (media_id,)).fetchone()
                if not owner or owner[0] != actor:
                    raise ValueError('图片不属于当前上传人。')
                image = load_image(media_id, conn=conn)
            return FileResponse(image['path'], media_type=image['type'], headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError) as exc:
            raise HTTPException(404, '图片不存在。') from exc

    def attached(conn, request_id, name, identity):
        info = shipping.source_info(conn)
        raw = repo.raw_record(conn, info, request_id)
        fields = repo.feishu_record(info, raw)['fields']
        if not shipping.eligible(fields):
            raise ValueError('申请单不在发货日历中。')
        item = next((item for item in fields.get(shipping.IMAGES) or [] if isinstance(item, dict) and item.get(name) == identity), None)
        if not item:
            raise ValueError('图片未关联至此申请单。')
        return info, raw, item

    @api.get('/api/admin/shipping-calendar/{request_id}/local-images/{media_id}')
    def local_image(request_id: str, media_id: str, _: str = Depends(require_admin)):
        from material_store.media import load_image
        runtime.release_database_snapshot()
        try:
            UUID(media_id)
            with connection() as conn:
                attached(conn, request_id, 'local_media_id', media_id)
                image = load_image(media_id, conn=conn)
            return FileResponse(image['path'], media_type=image['type'], headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError) as exc:
            raise HTTPException(404, '图片不存在或已移除。') from exc

    @api.get('/api/admin/shipping-calendar/{request_id}/remote-images/{file_token}')
    def remote_image(request_id: str, file_token: str, _: str = Depends(require_admin)):
        import app
        runtime.release_database_snapshot()
        try:
            with connection() as conn:
                info, raw, _ = attached(conn, request_id, 'file_token', file_token)
                remote_id = raw['remote_id']
            if not remote_id:
                raise ValueError('申请单尚未同步。')
            native = app._native_feishu_bitable_client(app.feishu_app_id(), app.feishu_app_secret(), app.feishu_bitable_app_token())
            current = native.get_record(info['table_id'], remote_id)
            image = next((item for item in app.feishu_attachment_items(current.get('fields') or {}, shipping.IMAGES) if item['file_token'] == file_token), None)
            if not image:
                raise ValueError('飞书图片已移除。')
            content = native.download_bitable_attachment(file_token, image['url'])
            mime = 'image/' + ('png' if content.startswith(b'\x89PNG') else 'webp' if content[8:12] == b'WEBP' else 'jpeg')
            return Response(content, media_type=mime, headers={'Cache-Control': 'private, max-age=300'})
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(404, '图片不存在或已移除。') from exc
