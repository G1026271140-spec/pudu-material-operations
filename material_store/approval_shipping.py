"""Import final approved logistics without replaying issue/stock workflows."""
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from uuid import NAMESPACE_URL, uuid4, uuid5
from psycopg.types.json import Jsonb
from .db import connection
from . import shipping_defaults as defaults, media

ASSET_PREFIX='approval-shipping-assets:'


def image_key(conn,image):
    """Keep the receipt identity stable across local-file and Feishu-token reads."""
    local=image.get('local_media_id');token=image.get('file_token')
    if not local and not token:return None
    row=conn.execute("""SELECT id::text FROM material_ops.media WHERE owner_open_id='system:approval-shipping'
        AND (id::text=%s OR feishu_file_token=%s) LIMIT 1""",(local or '',token or '')).fetchone()
    return 'approval:'+row[0] if row else None


def _extract(form):
    result={'version':1}
    for item in form:
        name=item.get('name')
        if name in {defaults.TEXT,'快递单号及文字信息'}:
            value=item.get('value')
            if value is not None and not isinstance(value,str):raise ValueError('审批物流文字格式无效。')
            text=str(value or '').strip()
            if len(text)>20000:raise ValueError('审批物流文字超过 20000 字。')
            if 'text' in result and result['text']!=text:raise ValueError('审批中存在内容不同的物流文字控件。')
            result['text']=text
        elif name==defaults.IMAGES:
            refs=item.get('value') or []
            if not isinstance(refs,list) or any(not isinstance(v,str) for v in refs):raise ValueError('审批发货图片格式无效。')
            if len(refs)>12:raise ValueError('审批发货图片最多 12 张。')
            # ext is the attachment label, not a Bitable file token.
            label=str(item.get('ext') or '审批发货图片')
            result['images']=[{'url':v,'name':label if len(refs)==1 else '审批发货图片-'+str(i+1)} for i,v in enumerate(refs)]
    return result


def extract(form):
    try:return _extract(form)
    except ValueError as exc:return {'version':1,'error':str(exc)}


def due(saved,native,code,number):
    return bool(code and native.get('code')==code and native.get('status')=='APPROVED'
        and native.get('request_no')==number and saved.get('logistics_import_code')!=code)


def validate_url(url):
    parsed=urlsplit(url)
    host=(parsed.hostname or '').lower()
    allowed=any(host==domain or host.endswith('.'+domain) for domain in ('feishu.cn','larksuite.com','byteimg.com','bytednsdoc.com','feishucdn.com'))
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or not allowed:
        raise ValueError('审批图片下载地址不属于支持的飞书 HTTPS 文件服务。')


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def download(url):
    validate_url(url)
    try:
        # Signed approval URLs need no app credential. Never forward authorization.
        with build_opener(SafeRedirect()).open(Request(url,headers={'Accept':'image/*'}),timeout=20) as response:
            validate_url(response.geturl())
            data=response.read(media.MAX_IMAGE_BYTES+1)
    except ValueError:raise
    except Exception as exc:raise ValueError('审批发货图片暂时无法下载，后台将重试。') from None
    media.validate_image(data)
    return data


def store_image(code,data,label):
    mime,suffix=media.validate_image(data)
    digest=sha256(data).hexdigest()
    if digest==defaults.asset()[1]:return None
    identity=str(uuid5(NAMESPACE_URL,'pudu:approval-shipping:v1:'+code+':'+digest))
    directory=media.root();directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/(identity+suffix)
    if not path.exists():
        temporary=directory/(identity+'.'+uuid4().hex+'.tmp')
        try:temporary.write_bytes(data);temporary.chmod(0o600);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
    name=label.replace('\\','/').rsplit('/',1)[-1][:180] or '审批发货图片'+suffix
    if not Path(name).suffix:name+=suffix
    with connection() as conn:
        conn.execute('''INSERT INTO material_ops.media(id,sha256,mime_type,filename,byte_size,storage_path,owner_open_id)
            VALUES (%s,%s,%s,%s,%s,%s,'system:approval-shipping') ON CONFLICT(id) DO NOTHING''',
            (identity,digest,mime,name,len(data),path.name))
    return {'local_media_id':identity,'name':name,'type':mime,'size':len(data)}


def images(code,refs):
    if not refs:return []
    name=ASSET_PREFIX+code
    # The final APPROVED snapshot is imported once. Cache its durable local files;
    # expiring signed URLs are neither the cache key nor exposed in Git or errors.
    with connection() as conn:
        old=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',(name,)).fetchone()
        if old:
            for item in old[0]['images']:media.load_image(item['local_media_id'],conn=conn)
            return old[0]['images']
    result=[]
    for ref in refs:
        item=store_image(code,download(ref['url']),ref['name'])
        if item and not any(x['local_media_id']==item['local_media_id'] for x in result):result.append(item)
    with connection() as conn:
        conn.execute('''INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)
            ON CONFLICT(name) DO NOTHING''',(name,Jsonb({'images':result})))
    return result


def prepare(native,fields,*,legacy=False):
    import app
    final=native.get('shipping') or {}
    result={};text=defaults.real_text(final.get('text'))
    if final.get('error'):return result,final['error']
    old=app.feishu_text(fields,defaults.TEXT)
    if text and text!=old and not (legacy and defaults.real_text(old)):
        result[defaults.TEXT]=text
    refs=final.get('images') or []
    if refs:
        with connection() as conn:
            current_real=defaults.real_images(conn,fields.get(defaults.IMAGES))
        if not (legacy and current_real):
            try:actual=images(native['code'],refs)
            except ValueError as exc:return result,str(exc)
            if actual:result[defaults.IMAGES]=actual
    return result,''
