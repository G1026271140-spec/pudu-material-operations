"""Submission latency and VM image files, with isolated PG and fake Feishu."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from time import monotonic,sleep
from uuid import uuid4
from unittest.mock import Mock
import asyncio
import pytest
from PIL import Image
import app,backend_runtime as runtime
from material_store import image_assets as assets,repository as repo,jobs
from test_shipping_calendar import store


def png(color='blue'):
    output=BytesIO();Image.new('RGB',(800,600),color).save(output,'PNG');return output.getvalue()


def test_http_accepts_durably_without_waiting_for_a_busy_business_lane(store,monkeypatch):
    import psycopg,os
    conn=store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(jobs,'connection',same_connection)
    dispatch=Mock(side_effect=AssertionError('The HTTP request cannot run business'))
    monkeypatch.setattr(jobs,'run_one',dispatch)
    with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as busy,busy.transaction():
        busy.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:admin',0))")
        conn.execute("SET LOCAL statement_timeout='750ms'")
        started=monotonic();task,created=jobs.submit('物料品类同步','latency-'+uuid4().hex,{'draft':{'rows':list(range(500))}})
        assert monotonic()-started<1.5 and created and task.status=='待处理'
        assert conn.execute('SELECT state FROM material_ops.jobs WHERE id=%s',(task.task_id,)).fetchone()==('pending',)
        again,created=jobs.submit(task.task_type,task.idempotency_key,task.payload)
        assert again.task_id==task.task_id and not created
        dispatch.assert_not_called()


def test_business_admin_worker_does_not_wait_for_external_callback(monkeypatch):
    from material_store import inbound
    called=Mock(side_effect=AssertionError('The admin lane must not perform source HTTP'))
    monkeypatch.setattr(inbound,'run_one',called)
    @contextmanager
    def no_work():raise RuntimeError('database reached');yield
    monkeypatch.setattr(jobs,'connection',no_work)
    with pytest.raises(RuntimeError,match='database reached'):jobs.run_one('admin',raise_errors=True)
    called.assert_not_called()


def test_external_worker_uses_existing_persistent_callback_jobs(monkeypatch):
    from material_store import inbound
    callback=Mock(return_value={'state':'done'});monkeypatch.setattr(inbound,'run_one',callback)
    assert jobs.run_one('inbound')=={'state':'done'}
    callback.assert_called_once_with(None,None)


def test_remote_image_downloads_once_and_removed_attachment_is_denied(store,monkeypatch):
    conn=store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(assets,'connection',same_connection)
    info=repo.named_table(conn,app.CATEGORY_TABLE_NAME)
    key='image-'+uuid4().hex;token='token-'+uuid4().hex
    row={'record_id':key,'fields':{'物料品类':'隔离图片','申领页图片':[{'file_token':token,'name':'photo.png','url':'https://example.invalid/image'}]}}
    repo.insert_source_records(conn,info,[row])
    native=Mock();native.get_record.return_value=row;native.download_bitable_attachment.return_value=png()
    monkeypatch.setattr(app,'_native_feishu_bitable_client',lambda *a:native)
    first=assets.primary(app.CATEGORY_TABLE_NAME,key,token)
    assert first.is_file() and first.read_bytes()[8:12]==b'WEBP'
    assert assets.primary(app.CATEGORY_TABLE_NAME,key,token)==first
    native.get_record.assert_called_once();native.download_bitable_attachment.assert_called_once()
    row['fields']['申领页图片']=[];repo.insert_source_records(conn,info,[row])
    with pytest.raises(KeyError):assets.primary(app.CATEGORY_TABLE_NAME,key,token)
    assert first.is_file()  # Old files never bypass current database attachment checks.


def test_new_attachment_token_reads_new_picture(store,monkeypatch):
    conn=store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(assets,'connection',same_connection)
    info=repo.named_table(conn,app.CATEGORY_TABLE_NAME);key='replace-'+uuid4().hex
    native=Mock();monkeypatch.setattr(app,'_native_feishu_bitable_client',lambda *a:native)
    files=[]
    for color in ('blue','red'):
        token=uuid4().hex;row={'record_id':key,'fields':{'物料品类':'替换图片','申领页图片':[{'file_token':token,'name':'image.png','url':'https://example.invalid/image'}]}}
        repo.insert_source_records(conn,info,[row]);native.get_record.return_value=row;native.download_bitable_attachment.return_value=png(color)
        files.append(assets.primary(app.CATEGORY_TABLE_NAME,key,token))
    assert files[0]!=files[1] and files[0].read_bytes()!=files[1].read_bytes()


def test_concurrent_image_requests_only_prepare_one_file(store):
    calls=[]
    def download():calls.append(1);sleep(.03);return png()
    with ThreadPoolExecutor(max_workers=8) as pool:paths=list(pool.map(lambda _:assets.rendered('concurrent-'+str(id(calls)),download),range(8)))
    assert len(calls)==1 and len(set(paths))==1


def test_image_executor_preserves_context_and_frees_business_threads(store):
    async def run():
        gate=Event();runtime.request_state['image-context']='preserved'
        def blocked():assert runtime.request_state['image-context']=='preserved';gate.wait(2);return True
        tasks=[asyncio.create_task(assets.isolated(blocked)) for _ in range(12)]
        await asyncio.sleep(.04)
        # Other thread-pool work remains available while all image workers wait.
        assert await asyncio.wait_for(asyncio.to_thread(lambda:'business available'),.5)=='business available'
        gate.set();assert all(await asyncio.gather(*tasks))
    asyncio.run(run())


def test_remote_image_http_reuses_vm_file_and_keeps_business_data_uncached(store,monkeypatch):
    from fastapi.testclient import TestClient
    from request_web.api import api
    conn=store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(assets,'connection',same_connection)
    info=repo.named_table(conn,app.CATEGORY_TABLE_NAME);key='http-image-'+uuid4().hex;token=uuid4().hex
    row={'record_id':key,'fields':{'物料品类':'HTTP图片','申领页图片':[{'file_token':token,'name':'image.png','url':'https://example.invalid/image'}]}}
    repo.insert_source_records(conn,info,[row])
    native=Mock();native.get_record.return_value=row;native.download_bitable_attachment.return_value=png()
    monkeypatch.setattr(app,'_native_feishu_bitable_client',lambda *a:native)
    client=TestClient(api);url='/api/live-image/'+app.CATEGORY_TABLE_NAME+'/'+key+'/'+token
    for _ in range(2):
        response=client.get(url)
        assert response.status_code==200 and response.headers['content-type']=='image/webp'
        assert 'private' in response.headers['cache-control'] and 'immutable' in response.headers['cache-control']
    native.download_bitable_attachment.assert_called_once()
    row['fields']['申领页图片']=[];repo.insert_source_records(conn,info,[row])
    response=client.get(url)
    assert response.status_code==404 and 'no-store' in response.headers['cache-control']


def test_image_preparation_starts_with_legacy_readonly_gate(monkeypatch):
    from request_web.api import _pending_inventory_lifespan
    monkeypatch.setattr(runtime,'web_read_only',lambda:True)
    monkeypatch.setattr(runtime,'database_reads',lambda:True)
    start=Mock();stop=Mock();monkeypatch.setattr(assets,'start',start);monkeypatch.setattr(assets,'stop',stop)
    async def check():
        async with _pending_inventory_lifespan(None):
            start.assert_called_once();stop.assert_not_called()
        stop.assert_called_once()
    asyncio.run(check())
