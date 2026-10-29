"""Versioned image files on the VM; database attachments remain authoritative."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from hashlib import sha256
from io import BytesIO
import logging,os,threading,time
from pathlib import Path
from uuid import uuid4
from PIL import Image,ImageOps
from .db import connection
from . import repository as repo,media

HEADERS={'Cache-Control':'private, max-age=86400, immutable'}
_executor=ThreadPoolExecutor(max_workers=4,thread_name_prefix='image-http')
_guard=threading.Lock();_locks={};_thread=None;_stop=threading.Event()


async def isolated(function,*args,**kwargs):
    """Network/image work cannot occupy the business HTTP thread pool."""
    context=copy_context()
    return await asyncio.get_running_loop().run_in_executor(_executor,lambda:context.run(function,*args,**kwargs))


def rendered(identity,loader):
    name=sha256(('webp1600-v1:'+identity).encode()).hexdigest()+'.webp'
    folder=media.root()/'image-assets';path=folder/name
    if path.is_file():return path
    with _guard:lock=_locks.setdefault(name,threading.Lock())
    with lock:
        if path.is_file():return path
        content=loader()
        with Image.open(BytesIO(content)) as original:
            original.draft('RGB',(1600,1600))
            picture=ImageOps.exif_transpose(original).convert('RGBA' if 'A' in original.getbands() else 'RGB')
            picture.thumbnail((1600,1600))
            output=BytesIO();picture.save(output,'WEBP',quality=78)
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=folder/(name+'.'+uuid4().hex+'.tmp')
        try:
            with temporary.open('xb') as target:target.write(output.getvalue())
            temporary.chmod(0o600);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
    return path


def local(image):
    return rendered('local:'+image['sha256'],image['path'].read_bytes)


def remote(info,row,remote_id,token,fields):
    """Caller has checked visibility; validate the current attachment again."""
    import app
    attached={item['file_token'] for field in fields for item in app.feishu_attachment_items(row['fields'],field)}
    if token not in attached:raise KeyError('图片已不属于此记录。')
    def load():
        # Frontend uploads already exist locally even after their token replaces
        # the local media ID in the source attachment field.
        with connection() as conn:
            found=conn.execute('SELECT id FROM material_ops.media WHERE feishu_file_token=%s ORDER BY created_at LIMIT 1',(token,)).fetchone()
            image=media.load_image(str(found[0]),conn=conn) if found else None
        if image:return image['path'].read_bytes()
        if not remote_id:raise KeyError('图片尚未发布。')
        app_token=app.feishu_bitable_app_token() if info['source']=='primary' else app.corporate_apparel_source_app_token()
        native=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app_token)
        current=native.get_record(info['table_id'],remote_id)
        attachment=next((item for field in fields for item in app.feishu_attachment_items(current.get('fields') or {},field) if item['file_token']==token),None)
        if not attachment:raise KeyError('飞书附件已移除。')
        return native.download_bitable_attachment(token,attachment['url'])
    return rendered(info['source']+':'+token,load)


def primary(table,record_id,token):
    from request_web.live_data import IMAGE_FIELDS
    if table not in IMAGE_FIELDS:raise KeyError('不支持的图片来源。')
    with connection() as conn:
        info=repo.named_table(conn,table);raw=repo.raw_record(conn,info,record_id)
        row=repo.feishu_record(info,raw)
    return remote(info,row,raw['remote_id'],token,IMAGE_FIELDS[table])


def catalog_items():
    """Only image metadata is read; no business table or cache snapshot is changed."""
    import app
    from . import apparel
    items=[];seen=set()
    with connection() as conn:
        infos=[(repo.named_table(conn,name),fields) for name,fields in
               [('物料品类',('申领页图片',)),('文化周边编码及库存数量',('图片',))]]
        infos.append((apparel.source_info(conn),('图片',)))
        for info,fields in infos:
            for row in repo.rows(conn,info):
                for field in fields:
                    for image in row['fields'].get(field) or []:
                        if not isinstance(image,dict):continue
                        if info['source']=='primary' and not image.get('local_media_id') and not str(image.get('name','')).lower().endswith(('.png','.jpg','.jpeg','.webp','.gif','.avif','.bmp')):continue
                        token=image.get('file_token');local_id=image.get('local_media_id')
                        identity=(info['source'],token or local_id)
                        if not identity[1] or identity in seen:continue
                        seen.add(identity)
                        if local_id:
                            items.append(('local_id',local_id))
                        elif token:
                            raw=repo.raw_record(conn,info,row['record_id'])
                            items.append(('remote',(info,row,raw['remote_id'],token,fields)))
    return items


def warm_once(items=None):
    started=time.monotonic();items=catalog_items() if items is None else items
    failures=[]
    def prepare(item):
        try:
            if item[0]=='local_id':local(media.load_image(item[1]))
            elif item[0]=='local':local(item[1])
            else:remote(*item[1])
            return True
        except Exception as exc:
            failures.append({'kind':item[0],'error':type(exc).__name__,'detail':str(exc) if isinstance(exc,ValueError) else ''})
            logging.warning('Image preparation will retry: %s',type(exc).__name__)
            return False
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix='image-warm') as pool:ready=sum(pool.map(prepare,items))
    return {'images':len(items),'ready':ready,'errors':len(items)-ready,'duration_ms':round((time.monotonic()-started)*1000),'failures':failures[:10]}


def start():
    global _thread
    if os.environ.get('PUDU_IMAGE_PREWARM_ENABLED')!='1':return
    if _thread and _thread.is_alive():return
    _stop.clear()
    def loop():
        import app,backend_runtime as runtime
        from psycopg.types.json import Jsonb
        while not _stop.is_set():
            with runtime.request_scope():
                try:
                    result=warm_once()
                    with connection() as conn:conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES ('worker:image-assets',%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",(Jsonb({'version':app.APP_VERSION,**result}),))
                except Exception as exc:logging.warning('Image preparation unavailable: %s',type(exc).__name__)
                finally:runtime.release_database_snapshot()
            _stop.wait(60)
    _thread=threading.Thread(target=loop,name='image-assets',daemon=True);_thread.start()


def stop():
    _stop.set()
    if _thread:_thread.join(timeout=1)
