"""Shared sample attachment for new ordinary requests. It is never logistics evidence."""
from functools import lru_cache
from hashlib import sha256
import os
from pathlib import Path
from uuid import NAMESPACE_URL,uuid4,uuid5

TEXT='发货单号及文字信息'
IMAGES='发货图片'
PENDING='待补充'
FILENAME='示例图片-发货图片待补充.png'


@lru_cache(maxsize=1)
def asset():
    data=(Path(__file__).resolve().parents[1]/'assets/shipping-placeholder-v1.png').read_bytes()
    digest=sha256(data).hexdigest()
    return data,digest,str(uuid5(NAMESPACE_URL,'pudu:shipping-placeholder:v1:'+digest))


def ensure_image(conn):
    from .media import root,validate_image
    data,digest,identity=asset();validate_image(data)
    directory=root();directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/(identity+'.png')
    if not path.exists():
        temporary=directory/(identity+'.'+uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(data);temporary.chmod(0o600);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
    conn.execute('''INSERT INTO material_ops.media(id,sha256,mime_type,filename,byte_size,storage_path,owner_open_id)
        VALUES (%s,%s,'image/png',%s,%s,%s,'system:shipping-placeholder') ON CONFLICT(id) DO NOTHING''',
        (identity,digest,FILENAME,len(data),path.name))
    return {'local_media_id':identity,'name':FILENAME,'type':'image/png','size':len(data)}


def initial_fields(conn, fields):
    result=dict(fields)
    if not str(result.get(TEXT) or '').strip():result[TEXT]=PENDING
    if not result.get(IMAGES):result[IMAGES]=[ensure_image(conn)]
    return result


def real_images(conn, images):
    values=[item for item in images or [] if isinstance(item,dict)]
    if not values:return []
    identity=asset()[2]
    row=conn.execute('SELECT feishu_file_token FROM material_ops.media WHERE id=%s',(identity,)).fetchone()
    token=row[0] if row else None
    return [item for item in values if item.get('local_media_id')!=identity and not (token and item.get('file_token')==token)]


def real_text(value):
    value=str(value or '').strip()
    return '' if value==PENDING else value
