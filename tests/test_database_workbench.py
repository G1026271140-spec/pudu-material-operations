"""Real PostgreSQL tests isolated from production and Feishu."""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
psycopg=pytest.importorskip('psycopg')
from psycopg import sql
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

import app
import backend_runtime as runtime
from material_store import db,repository as repo
from material_store.client import DatabaseReadClient
from material_store.ingest import initial_import
from request_web.live_data import reader

web=importlib.import_module('request_web.api')
DSN=os.environ.get('PUDU_TEST_DATABASE_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='Requires the isolated VM test database')


@pytest.fixture
def store(monkeypatch):
    prefix='testdb_'+uuid4().hex
    monkeypatch.setenv('PUDU_DATABASE_DSN',DSN)
    monkeypatch.setenv('PUDU_DATA_SOURCE','postgresql')
    monkeypatch.setenv('PUDU_DB_EDITOR_ENABLED','1')
    monkeypatch.setenv('PUDU_WEB_READ_ONLY','1')
    db.pool.cache_clear()
    conn=psycopg.connect(DSN,autocommit=True)
    assert conn.execute('SELECT current_database()').fetchone()[0]=='pudu_materials_test'
    original=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',('contact_departments_cache.json',)).fetchone()
    runs={r[0] for r in conn.execute('SELECT id FROM material_ops.import_runs')}
    actor='ou_'+prefix
    directory={'users':[{'open_id':actor,'name':'隔离测试管理员','department_ids':[],'department_paths':[]}],'departments':[]}
    conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES ('contact_departments_cache.json',%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",(Jsonb(directory),))
    conn.execute("INSERT INTO material_ops.import_runs(state,completed_at,summary) VALUES ('done',now(),%s)",(Jsonb({'isolated_test':True}),))
    monkeypatch.setattr(app,'feishu_client',lambda:DatabaseReadClient())
    def seed(name,fields,source='primary',suffix=None):
        info=repo.named_table(conn,name,source)
        rid=prefix+'_'+(suffix or uuid4().hex[:6])
        repo.insert_source_records(conn,info,[{'record_id':rid,'fields':fields}])
        return info,rid
    def field(info,name):return next(f['field_id'] for f in info['fields'] if f['field_name']==name)
    result=SimpleNamespace(conn=conn,prefix=prefix,actor=actor,directory=directory,seed=seed,field=field)
    yield result
    for r in runtime.request_state._mapping().values():
        if hasattr(r,'close'):r.close()
    keys=[r[0] for r in conn.execute("SELECT record_key FROM material_ops.outbox WHERE idempotency_key LIKE %s",(prefix+'%',))]
    conn.execute('DELETE FROM material_ops.outbox WHERE idempotency_key LIKE %s',(prefix+'%',))
    conn.execute('DELETE FROM material_ops.audit WHERE actor_open_id=%s OR record_key LIKE %s',(actor,prefix+'%'))
    conn.execute('DELETE FROM material_ops.media WHERE owner_open_id=%s',(actor,))
    for name, in conn.execute('SELECT sql_table FROM material_meta.tables'):
        conn.execute(sql.SQL('DELETE FROM material_data.{} WHERE _record_key LIKE %s OR _record_key=ANY(%s)').format(sql.Identifier(name)),(prefix+'%',keys))
    conn.execute('DELETE FROM material_ops.import_runs WHERE NOT(id=ANY(%s))',(list(runs),))
    if original:conn.execute("UPDATE material_ops.documents SET payload=%s WHERE name='contact_departments_cache.json'",(Jsonb(original[0]),))
    else:conn.execute("DELETE FROM material_ops.documents WHERE name='contact_departments_cache.json'")
    conn.close()
    if db.pool.cache_info().currsize:db.pool().close()
    db.pool.cache_clear()


def category(s):
    return s.seed('物料品类',{'物料品类':'数据库测试品类','单价（美元）':2,'单价（人民币）':13.54,'备注':'原备注'})


def change(s,info,rid,name,value,version=0,key=None):
    return repo.patch_record(s.conn,info['table_id'],rid,{s.field(info,name):value},version,key or s.prefix+uuid4().hex,s.actor)


def test_cell_save_is_atomic_audited_idempotent_and_detects_stale_versions(store):
    s=store;info,rid=category(s);fid=s.field(info,'备注');key=s.prefix+'stable'
    result=change(s,info,rid,'备注','新备注',key=key)
    assert result['fields'][fid]=='新备注' and result['version']==1 and result['sync_state']=='pending'
    change(s,info,rid,'备注','新备注',key=key)
    assert s.conn.execute('SELECT count(*) FROM material_ops.outbox WHERE idempotency_key=%s',(key,)).fetchone()[0]==1
    assert s.conn.execute('SELECT actor_open_id FROM material_ops.audit WHERE record_key=%s',(rid,)).fetchone()[0]==s.actor
    with pytest.raises(repo.VersionConflict):change(s,info,rid,'备注','过期覆盖',0)
    with pytest.raises(repo.VersionConflict):change(s,info,rid,'备注','另一次内容',1,key=key)


def test_formula_updates_immediately_and_cannot_be_directly_overwritten(store):
    s=store;info,rid=category(s)
    result=change(s,info,rid,'单价（美元）',3)
    assert result['fields'][s.field(info,'单价（人民币）')]==pytest.approx(20.31)
    with pytest.raises(ValueError):change(s,info,rid,'单价（人民币）',999,1)
    assert s.conn.execute('SELECT count(*) FROM material_ops.outbox WHERE record_key=%s',(rid,)).fetchone()[0]==1


def test_stock_adjustment_writes_ledger_and_outbox_in_one_transaction(store):
    s=store
    info,rid=s.seed('物料主数据',{'物料编码':'TEST-000','物料品类':'数据库测试品类','产品型号':'测试型号','语种':'英文','当前库存':10})
    result=change(s,info,rid,'当前库存',12)
    assert result['fields'][s.field(info,'当前库存')]==12
    jobs=s.conn.execute('SELECT operation,table_id,patch FROM material_ops.outbox WHERE idempotency_key LIKE %s',(s.prefix+'%',)).fetchall()
    assert len(jobs)==2 and {j[0] for j in jobs}=={'update','create'}
    ledger=repo.named_table(s.conn,'库存流水')
    patch=next(j[2] for j in jobs if j[0]=='create')
    assert patch[s.field(ledger,'变更前数量')]==10
    assert patch[s.field(ledger,'变更后数量')]==12
    with pytest.raises(ValueError):change(s,info,rid,'当前库存',-1,1)
    assert repo.raw_record(s.conn,info,rid)['fields'][s.field(info,'当前库存')]==12


def test_category_rename_updates_stock_labels_without_rewriting_history(store):
    s=store;info,rid=category(s)
    stock,sid=s.seed('物料主数据',{'物料编码':'TEST-001','物料品类':'数据库测试品类','当前库存':1})
    history,hid=s.seed('申请明细',{'品类名称':'数据库测试品类','申请数量':1})
    change(s,info,rid,'物料品类','数据库测试新名称')
    assert repo.raw_record(s.conn,stock,sid)['fields'][s.field(stock,'物料品类')]=='数据库测试新名称'
    assert repo.raw_record(s.conn,history,hid)['fields'][s.field(history,'品类名称')]=='数据库测试品类'


def test_reciprocal_links_are_updated_and_invalid_targets_rollback(store):
    s=store;cat,cid=category(s)
    stock,sid=s.seed('物料主数据',{'物料编码':'TEST-002','物料品类':'数据库测试品类','当前库存':1})
    link=next(f for f in stock['fields'] if f['field_name']=='品类关联')
    result=change(s,stock,sid,'品类关联',[cid])
    back=link['property']['back_field_id']
    assert sid in repo.raw_record(s.conn,cat,cid)['fields'][back]
    with pytest.raises(ValueError):change(s,stock,sid,'品类关联',[s.prefix+'missing'],result['version'])
    assert repo.raw_record(s.conn,stock,sid)['fields'][link['field_id']]==[cid]


def test_link_selection_updates_display_label_and_remains_idempotent(store):
    s=store;cat,cid=s.seed('物料品类',{'物料品类':'关联目标品类'})
    stock,sid=s.seed('物料主数据',{'物料编码':'TEST-003','物料品类':'原品类','当前库存':1})
    key=s.prefix+'association'
    result=change(s,stock,sid,'品类关联',[cid],key=key)
    assert result['fields'][s.field(stock,'物料品类')]=='关联目标品类'
    assert change(s,stock,sid,'品类关联',[cid],key=key)['version']==1
    page=repo.browse(s.conn,stock['table_id'])
    label=next(f for f in page['fields'] if f['field_name']=='物料品类')
    assert not label['editable'] and label['edit_via']==s.field(stock,'品类关联')


def test_category_picture_clear_keeps_non_image_files_and_rolls_back_bad_patch(store):
    s=store
    glb={'file_token':'test-model','name':'model.glb'}
    image={'file_token':'test-image','name':'image.png'}
    cat,cid=s.seed('物料品类',{'物料品类':'图片测试品类','申领页图片':[glb,image]})
    with pytest.raises(ValueError,match='GLB'):change(s,cat,cid,'申领页图片',[])
    assert repo.raw_record(s.conn,cat,cid)['version']==0
    result=change(s,cat,cid,'申领页图片',[glb])
    assert result['fields'][s.field(cat,'申领页图片')]==[glb]


def test_uploaded_local_picture_is_visible_after_cell_save_before_feishu_sync(store,monkeypatch,tmp_path):
    from material_store import media
    from PIL import Image
    from io import BytesIO
    s=store;cat,cid=category(s)
    monkeypatch.setenv('PUDU_MEDIA_ROOT',str(tmp_path))
    output=BytesIO();Image.new('RGB',(8,8),'green').save(output,'PNG')
    image=media.save_image(output.getvalue(),'category.png',s.actor)
    result=change(s,cat,cid,'申领页图片',[image])
    monkeypatch.setattr(web,'_signed_admin_open_id',lambda _:s.actor)
    client=TestClient(web.api)
    response=client.get('/api/database-image/'+image['local_media_id'])
    assert response.status_code==200 and response.content==output.getvalue()
    assert result['sync_state']=='pending'
    assert client.get('/api/database-image/'+str(uuid4())).status_code==404


def test_import_reads_every_page_via_client_and_checks_source_against_database(store):
    s=store
    metadata=[repo.table(s.conn,r[0]) for r in s.conn.execute('SELECT table_id FROM material_meta.tables')]
    data={m['table_id']:[] for m in metadata}
    cat=repo.named_table(s.conn,'物料品类')
    data[cat['table_id']]=[{'record_id':s.prefix+'_import','fields':{'物料品类':'导入测试','备注':'完整原值'}}]
    def client(source):
        return SimpleNamespace(list_fields=lambda tid:deepcopy(next(m['fields'] for m in metadata if m['table_id']==tid)),list_records=lambda tid:deepcopy(data[tid]))
    summary=initial_import(s.conn,{key:client(key) for key in ['primary','apparel_admin']},lambda:s.directory)
    assert len(summary['tables'])==23 and summary['records']==1
    assert repo.rows(s.conn,cat)[0]['fields']['备注']=='完整原值'
    change(s,cat,s.prefix+'_import','备注','本地修改')
    with pytest.raises(ValueError,match='未同步修改'):initial_import(s.conn,{key:client(key) for key in ['primary','apparel_admin']},lambda:s.directory)
    assert repo.raw_record(s.conn,cat,s.prefix+'_import')['fields'][s.field(cat,'备注')]=='本地修改'


def test_schema_drift_cannot_publish_a_partial_import(store):
    s=store
    client=SimpleNamespace(list_fields=lambda tid:[],list_records=lambda tid:pytest.fail('Must verify schema before reading rows'))
    with pytest.raises(ValueError,match='字段已变化'):initial_import(s.conn,{'primary':client,'apparel_admin':client},lambda:s.directory)


def test_next_http_request_reads_latest_database_values_without_business_cache(store):
    s=store;info,rid=category(s)
    @contextmanager
    def scope():
        with runtime.request_scope():
            try:yield reader()
            finally:reader().close()
    with scope() as first:
        assert next(r for r in first.rows('物料品类') if r['record_id']==rid)['fields']['备注']=='原备注'
        change(s,info,rid,'备注','即时值')
        assert next(r for r in first.rows('物料品类') if r['record_id']==rid)['fields']['备注']=='原备注'
    with scope() as second:
        assert next(r for r in second.rows('物料品类') if r['record_id']==rid)['fields']['备注']=='即时值'


def test_allocation_detail_uses_the_same_database_request_snapshot(store):
    s=store
    info,rid=s.seed('物料申请单',{'申请单号':'TEST-CONTEXT','标题':'隔离配货读取测试'})
    with runtime.request_scope():
        try:
            context=app.request_inventory_review_context(request_id=rid)
            assert context['request']['request_no']=='TEST-CONTEXT'
        finally:
            runtime.release_database_snapshot()


def test_database_api_requires_admin_and_only_opens_its_own_write_route(store,monkeypatch):
    s=store;info,rid=category(s)
    client=TestClient(web.api)
    monkeypatch.setattr(web,'_signed_admin_open_id',lambda _: '')
    assert client.get('/api/admin/database/tables').status_code==403
    monkeypatch.setattr(web,'_signed_admin_open_id',lambda _:s.actor)
    result=client.patch(f"/api/admin/database/tables/{info['table_id']}/records/{rid}",json={'expected_version':0,'idempotency_key':s.prefix+'api','patch':{s.field(info,'备注'):'API保存'}})
    assert result.status_code==200 and result.json()['record']['version']==1
    assert client.post('/api/submit',json={}).status_code==409
    page=client.get(f"/api/admin/database/tables/{info['table_id']}/records?q=API保存")
    assert page.status_code==200 and page.json()['count']==1
    assert next(f for f in page.json()['fields'] if f['field_name']=='单价（人民币）')['editable'] is False


def test_workflow_fields_and_last_admin_protection(store):
    s=store
    info,rid=s.seed('用户权限表',{'用户账号':[{'id':s.actor}],'角色':['管理员'],'是否启用':'是'})
    with pytest.raises(ValueError,match='保留一位'):change(s,info,rid,'角色',[])
    assert repo.raw_record(s.conn,info,rid)['version']==0
    requests,req=s.seed('物料申请单',{'申请单号':'TEST-REQ','审批状态':'待审批'})
    with pytest.raises(ValueError,match='审批'):change(s,requests,req,'审批状态','已通过')


@pytest.mark.parametrize('write',[False,True])
def test_five_concurrent_authorized_requests_do_not_exhaust_the_small_pool(store,monkeypatch,write):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    s=store
    targets=[s.seed('物料品类',{'物料品类':f'并发测试-{i}','备注':'原值'}) for i in range(5)]
    barrier=Barrier(5,timeout=8)
    def authorize(_):
        reader().rows('用户权限表')
        barrier.wait()
        return s.actor
    monkeypatch.setattr(web,'_signed_admin_open_id',authorize)
    client=TestClient(web.api)
    def request(index):
        info,rid=targets[index]
        if write:
            return client.patch(f"/api/admin/database/tables/{info['table_id']}/records/{rid}",json={
                'expected_version':0,'idempotency_key':s.prefix+f'parallel-{index}',
                'patch':{s.field(info,'备注'):f'并发保存-{index}'}}).status_code
        return client.get('/api/admin/database/tables').status_code
    with ThreadPoolExecutor(max_workers=5) as workers:
        assert list(workers.map(request,range(5)))==[200]*5
