"""Inventory corrections in an isolated restored PG database, never Feishu HTTP."""
from contextlib import contextmanager
from uuid import uuid4
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test_shipping_calendar import store
from material_store import stock_workbench as stock, repository as repo
from material_store.client import DatabaseWriteClient
import app


@pytest.fixture
def inventory(store, monkeypatch):
    conn=store
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(stock,'connection',same)
    monkeypatch.setenv('PUDU_CONCURRENT_EDIT_POLICY','last_commit_wins')
    actor='ou_stock_'+uuid4().hex
    permission=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    repo.insert_source_records(conn,permission,[{'record_id':'rec_'+uuid4().hex,'fields':{
        '用户账号':[{'id':actor}],'角色':['管理员'],'是否启用':'是'}}])
    return conn,actor


def seed(conn,kind,**patch):
    info=stock.info_for(conn,kind);key='rec_stock_'+uuid4().hex
    if kind=='apparel':
        fields={'物品分类':'文化衫','款式':'库存隔离验收','申领显示名称':'库存隔离验收','码数':'M','编码':key,
                '原始库存数量':100,'入库/纠正':5,'表格兑换数量':10,'系统兑换数量':15,'最新库存':80}
    else:
        fields={'物料品类':'库存隔离验收','产品型号':'型号A','当前库存':80,
                ('物料编码' if kind=='ordinary' else '文化周边编码'):key}
        if kind=='ordinary':fields['语种']='英语(English)'
        if kind=='cultural':fields.update(战区管理='欧洲',是否可以申领='否')
    repo.insert_source_records(conn,info,[{'record_id':key,'fields':{**fields,**patch}}])
    return info,key


def draft(conn,kind,key,**patch):
    return {'kind':kind,'record_id':key,'expected_version':repo.raw_record(conn,stock.info_for(conn,kind),key)['version'],
            'quantity':93,'note':'隔离库存修正','idempotency_key':str(uuid4()),**patch}


@pytest.mark.parametrize('kind',['ordinary','cultural','apparel'])
def test_atomic_local_stock_ledger_audit_outbox_and_idempotency(inventory,kind):
    conn,actor=inventory;info,key=seed(conn,kind);body=draft(conn,kind,key)
    before=repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']
    result=stock.save(actor,body)
    assert (result['before'],result['after'],result['delta'])==(80,93,13)
    assert stock.save(actor,body)==result
    raw=repo.raw_record(conn,info,key);fields=repo.feishu_record(info,raw)['fields']
    assert stock.quantity(fields,kind)==93 and raw['sync_state']=='pending'
    changed={k for k in before.keys()|fields.keys() if before.get(k)!=fields.get(k)}
    # The existing repository also refreshes derived price/back-link fields.
    assert changed<=({'入库/纠正','最新库存'} if kind=='apparel' else {'当前库存','库存流水','单价（人民币）'})
    if kind=='apparel':assert fields['系统兑换数量']==15 and fields['表格兑换数量']==10 and fields['入库/纠正']==18
    if kind=='cultural':assert fields['是否可以申领']=='否'
    tasks=conn.execute('SELECT table_id,record_key,patch,operation,lane FROM material_ops.outbox WHERE job_id=%s',(result['task_id'],)).fetchall()
    assert len(tasks)==2
    update=next(r for r in tasks if r[1]==key)
    wanted='入库/纠正' if kind=='apparel' else '当前库存'
    fid=next(f['field_id'] for f in info['fields'] if f['field_name']==wanted)
    assert update[2]=={fid:18 if kind=='apparel' else 93} and update[3]=='update'
    assert update[4]==('ordinary' if kind=='ordinary' else 'cultural')
    ledger=repo.named_table(conn,'库存流水')
    entry=repo.feishu_record(ledger,repo.raw_record(conn,ledger,result['ledger_id']))['fields']
    assert (entry['变更前数量'],entry['变更后数量'],entry['库存变化'])==(80,93,13)
    assert entry['流水类型']=='库存修正' and info['table_id'] in entry['备注']
    assert conn.execute('SELECT state FROM material_ops.jobs WHERE id=%s',(result['task_id'],)).fetchone()==('done',)
    assert conn.execute('SELECT count(*) FROM material_ops.effects WHERE job_id=%s',(result['task_id'],)).fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM material_ops.audit WHERE record_key=%s AND actor_open_id=%s',(key,actor)).fetchone()[0]>=1
    with pytest.raises(repo.VersionConflict):stock.save(actor,{**body,'quantity':94})


def test_stale_editor_uses_latest_locked_stock_for_delta(inventory):
    conn,actor=inventory;info,key=seed(conn,'apparel');old=draft(conn,'apparel',key,quantity=90)
    stock.save(actor,old)
    latest=stock.save(actor,{**old,'quantity':75,'idempotency_key':str(uuid4())})
    assert (latest['before'],latest['after'],latest['delta'])==(90,75,-15)
    fields=repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']
    assert fields['入库/纠正']==0 and fields['系统兑换数量']==15


def test_ledger_failure_rolls_back_stock_job_and_outbox(inventory,monkeypatch):
    conn,actor=inventory;info,key=seed(conn,'ordinary');before=repo.raw_record(conn,info,key);body=draft(conn,'ordinary',key)
    monkeypatch.setattr(DatabaseWriteClient,'batch_create_records',lambda *a,**kw:(_ for _ in ()).throw(ValueError('ledger failure')))
    with pytest.raises(ValueError,match='ledger failure'):stock.save(actor,body)
    assert repo.raw_record(conn,info,key)==before
    assert conn.execute('SELECT count(*) FROM material_ops.jobs WHERE idempotency_key=%s',('stock-adjust:'+body['idempotency_key'],)).fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE record_key=%s',(key,)).fetchone()[0]==0


@pytest.mark.parametrize('target',[None,True,1.2,'123',1000000001])
def test_invalid_quantities_cannot_write(inventory,target):
    conn,actor=inventory;info,key=seed(conn,'ordinary');before=repo.raw_record(conn,info,key)
    with pytest.raises((ValueError,ArithmeticError)):stock.save(actor,draft(conn,'ordinary',key,quantity=target))
    assert repo.raw_record(conn,info,key)==before


def test_disabled_or_foreign_admin_and_future_versions_refused(inventory):
    conn,actor=inventory;info,key=seed(conn,'ordinary');body=draft(conn,'ordinary',key)
    with pytest.raises(PermissionError):stock.save('ou_other',body)
    with pytest.raises(repo.VersionConflict):stock.save(actor,{**body,'expected_version':body['expected_version']+100})
    assert stock.save(actor,{**body,'quantity':80})['changed'] is False


def test_nonpositive_cultural_stock_updates_claimability_without_notification(inventory):
    conn,actor=inventory;info,key=seed(conn,'cultural',是否可以申领='是')
    result=stock.save(actor,draft(conn,'cultural',key,quantity=-2))
    assert result['after']==-2
    fields=repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']
    assert fields['是否可以申领']==app.cultural_stock_fields(-2)['是否可以申领']
    permission=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME);other='ou_disabled_'+uuid4().hex
    repo.insert_source_records(conn,permission,[{'record_id':'rec_'+uuid4().hex,'fields':{'用户账号':[{'id':other}],'角色':['管理员'],'是否启用':'否'}}])
    with pytest.raises(PermissionError):stock.save(other,draft(conn,'cultural',key))


def test_read_only_web_middleware_allows_authorized_stock_editor_route(monkeypatch):
    import asyncio,importlib
    import backend_runtime as runtime
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    web=importlib.import_module('request_web.api')
    monkeypatch.setattr(runtime,'web_read_only',lambda:True)
    monkeypatch.setattr(runtime,'database_editor_enabled',lambda:True)
    monkeypatch.setattr(runtime,'database_business_writes_enabled',lambda:True)
    monkeypatch.setattr(runtime,'database_workflow_writes_enabled',lambda:False)
    async def next_handler(request):return JSONResponse({'reached_authorization':True})
    request=Request({'type':'http','method':'POST','path':'/api/admin/database/stock','headers':[]})
    response=asyncio.run(web.frontend_cache_policy(request,next_handler))
    assert response.status_code==200


def test_filters_all_four_dimensions_and_apparel_header_exclusion(inventory):
    conn,_=inventory
    region=repo.named_table(conn,app.REGION_TABLE_NAME);rid='rec_zone_'+uuid4().hex
    repo.insert_source_records(conn,region,[{'record_id':rid,'fields':{'战区名称':'隔离战区'}}])
    info,key=seed(conn,'ordinary',战区管理=[rid])
    seed(conn,'ordinary',产品型号='型号B',语种='日语(Japanese)')
    seed(conn,'apparel',码数='')
    result=stock.catalog(conn,kind='ordinary',category='库存隔离验收',model='型号A',language='英语(English)',region='隔离战区')
    assert [r['record_id'] for r in result['records']]==[key]
    assert result['facets']['region']==['隔离战区']
    assert stock.catalog(conn,kind='all',q=key)['count']==1
    assert not any(r['category']=='库存隔离验收' for r in stock.catalog(conn,kind='apparel',q='库存隔离验收')['records'])


def test_stock_api_requires_admin_and_valid_filters(inventory,monkeypatch):
    from request_web.database_api import register_database_api
    import backend_runtime as runtime
    conn,actor=inventory;_,key=seed(conn,'ordinary')
    for name in ('database_reads','database_editor_enabled','database_business_writes_enabled'):monkeypatch.setattr(runtime,name,lambda:True)
    from material_store import db
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(db,'connection',same)
    api=FastAPI();register_database_api(api,lambda:actor)
    with TestClient(api) as client:
        assert client.get('/api/admin/database/stock',params={'kind':'ordinary','q':key}).json()['count']==1
        assert client.get('/api/admin/database/stock?kind=bad').status_code==422
        assert client.get('/api/admin/database/stock?page=-1').status_code==422
        assert client.post('/api/admin/database/stock',json=draft(conn,'ordinary',key,quantity=81)).status_code==200
    def deny():raise HTTPException(403,'仅管理员')
    denied=FastAPI();register_database_api(denied,deny)
    with TestClient(denied) as client:
        assert client.get('/api/admin/database/stock').status_code==403
        assert client.post('/api/admin/database/stock',json={}).status_code==403
