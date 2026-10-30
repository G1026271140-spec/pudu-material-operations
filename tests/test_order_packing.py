from contextlib import contextmanager
from io import BytesIO
from uuid import uuid4
from unittest.mock import Mock
import json
import pytest
from openpyxl import load_workbook
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from test_shipping_calendar import store,insert_request
from test_account_tools import account_store
import app
from material_store import order_packing as exports,order_packing_xlsx as xlsx,repository as repo,inbound,jobs


@pytest.fixture
def export_store(account_store,monkeypatch,tmp_path):
    conn,ids=account_store
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(exports,'connection',same);monkeypatch.setattr(inbound,'connection',same)
    monkeypatch.setenv('PUDU_ORDER_PACKING_EXPORT_ROOT',str(tmp_path/'exports'))
    return conn,ids


def material(conn,definition='印刷物料',**patch):
    category=repo.named_table(conn,app.CATEGORY_TABLE_NAME);cid='rec_'+uuid4().hex;name='隔离印刷'+uuid4().hex
    repo.insert_source_records(conn,category,[{'record_id':cid,'fields':{'物料品类':name,'品类定义':definition,'中文页面名称':'测试印刷','是否在申领页显示':'否'}}])
    stock=repo.named_table(conn,app.MATERIAL_TABLE_NAME);mid='rec_'+uuid4().hex
    repo.insert_source_records(conn,stock,[{'record_id':mid,'fields':{'物料编码':'MAT-'+uuid4().hex,'物料品类':name,'品类关联':[cid],'产品型号':'ET1','语种':'英语(English)','当前库存':0,**patch}}])
    return mid,name


def request(conn,mid,amount=10,**patch):
    rid=insert_request(conn,物料用途='隔离活动',**patch);info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    no=repo.feishu_record(info,repo.raw_record(conn,info,rid))['fields']['申请单号']
    lines=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME);lid='rec_'+uuid4().hex
    repo.insert_source_records(conn,lines,[{'record_id':lid,'fields':{'明细编号':no+'-01','所属申请单':[rid],'物料编码':[mid],'申请数量':999,'审批通过数量':amount,'实际发放数量':amount,'明细状态':'已发放'}}])
    return rid,lid


def extra(mid='',**patch):
    return {'id':str(uuid4()),'source':'catalog' if mid else 'custom','material_id':mid,'category':'自定义海报','model':'特别版','language':'法语','quantity':3,'usage':'额外备货','remark':'',**patch}


def body(conn,ids=None,extras=None):
    requests=exports.read_source(conn)[0]['requests'];ids=ids or []
    return {'request_ids':ids,'fingerprints':{r['request_id']:r['fingerprint'] for r in requests if r['request_id'] in ids},'extras':extras or [],'generation_date':'2026-11-02'}


def submission(conn,payload):return {**payload,'preview_hash':exports.digest(exports.prepare(conn,payload)),'idempotency_key':str(uuid4())}


def test_eligibility_print_definition_aliases_and_latest_allocated_quantity(export_store):
    from psycopg import sql
    conn,_=export_store;mid,_=material(conn);rid,lid=request(conn,mid,7)
    nonprint,_=material(conn,'周边礼品');excluded,_=request(conn,nonprint,9)
    waiting,_=request(conn,mid,11,库存审查状态='待核实库存')
    rejected,_=request(conn,mid,11,审批状态='已驳回')
    info=repo.named_table(conn,app.MATERIAL_TABLE_NAME);alias='local_'+uuid4().hex
    conn.execute(sql.SQL('UPDATE material_data.{} SET _record_key=%s WHERE _record_key=%s').format(sql.Identifier(info['sql_table'])),(alias,mid))
    data,stock=exports.read_source(conn);catalog={r['request_id']:r for r in data['requests']}
    assert rid in catalog and waiting not in catalog and rejected not in catalog
    assert catalog[rid]['quantity']==7 and catalog[rid]['lines'][0]['material_id']==alias
    assert not catalog[excluded]['selectable'] and catalog[excluded]['lines']==[]
    assert stock[mid]['material_id']==alias


def test_multiple_requests_catalog_and_custom_extras_merge_and_reconcile(export_store):
    conn,_=export_store;mid,_=material(conn);first,_=request(conn,mid,10);second,_=request(conn,mid,20)
    snapshot=exports.prepare(conn,body(conn,[first,second],[extra(mid,quantity=5),extra(quantity=4)]));view=exports.views(snapshot)
    assert view['quantity']==39 and view['request_count']==2 and view['extra_count']==2
    assert sorted(r['quantity'] for r in view['orders'])==[4,35]
    assert sum(r['quantity'] for g in view['packing'] for r in g['rows'])==39
    assert len(view['packing'])==3
    content=xlsx.workbook(view);wb=load_workbook(BytesIO(content))
    assert wb.sheetnames==['下单表','分装表']
    for ws in wb:
        assert tuple(c.value for c in ws[1])==xlsx.HEADERS
        assert sum(c.value for row in ws.iter_rows(min_row=2) for c in row if c.column==4 and isinstance(c.value,int))==39
        assert ws.freeze_panes==('A2' if ws.title=='分装表' else None) and ws.print_title_rows is None
    assert {row[4].value for row in list(wb['分装表'].rows)[1:] if row[4].value}=={g['label'] for g in view['packing']}
    assert all('999' not in r['usage'] for r in view['orders'])


def test_frozen_export_job_has_no_business_writes_and_redownload_uses_same_bytes(export_store):
    from material_store.client import DatabaseWriteClient
    conn,ids=export_store;mid,_=material(conn);rid,lid=request(conn,mid,10)
    payload=submission(conn,body(conn,[rid],[extra(mid)]))
    counts={t:conn.execute('SELECT count(*) FROM material_ops.'+t).fetchone()[0] for t in ['outbox','effects','audit']}
    task=exports.enqueue(ids['admin'],payload)
    assert exports.enqueue(ids['admin'],payload)['task_id']==task['task_id']
    with pytest.raises(repo.VersionConflict):exports.enqueue(ids['admin'],{**payload,'generation_date':'2026-11-03'})
    info=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)
    # A later live change must not rewrite the already frozen export.
    old=repo.raw_record(conn,info,lid);fid=next(f['field_id'] for f in info['fields'] if f['field_name']=='实际发放数量')
    repo.replace_values(conn,info,lid,{**old['fields'],fid:1},version=old['version']+1)
    assert inbound.run_one(job_id=task['task_id'])['state']=='done'
    path,name=exports.download(conn,task['task_id']);first=path.read_bytes()
    assert name=='11月2日营销物料下单与分装.xlsx' and first.startswith(b'PK')
    assert exports.download(conn,task['task_id'])[0].read_bytes()==first
    entry=next(r for r in exports.history(conn) if r['id']==task['task_id'])
    assert entry['result']['quantity']==13 and entry['state']=='done'
    assert all(conn.execute('SELECT count(*) FROM material_ops.'+t).fetchone()[0]==n for t,n in counts.items())
    path.write_bytes(b'corrupt')
    with pytest.raises(LookupError,match='校验失败'):exports.download(conn,task['task_id'])


def test_changed_preview_role_scope_and_invalid_source_are_rejected(export_store):
    conn,ids=export_store;mid,_=material(conn);rid,lid=request(conn,mid)
    payload=submission(conn,body(conn,[rid]))
    with pytest.raises(PermissionError):exports.enqueue(ids['sales'],payload)
    wrong=submission(conn,body(conn,extras=[extra()]));wrong['preview_hash']='changed'
    with pytest.raises(repo.VersionConflict,match='预览内容'):exports.enqueue(ids['admin'],wrong)
    lines=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME);row=repo.raw_record(conn,lines,lid)
    repo.replace_values(conn,lines,lid,row['fields'],version=row['version']+1)
    with pytest.raises(repo.VersionConflict,match='发生变化'):exports.prepare(conn,{k:v for k,v in payload.items() if k not in {'idempotency_key','preview_hash'}})
    nonprint,_=material(conn,'文化周边')
    with pytest.raises(repo.VersionConflict,match='不属于印刷物料'):exports.prepare(conn,body(conn,extras=[extra(nonprint)]))


@pytest.mark.parametrize('change',[{'quantity':True},{'quantity':0},{'quantity':1.5},{'quantity':1000001},{'category':''},{'usage':''},{'category':'bad\x00'},{'source':'forged'}])
def test_invalid_custom_items_are_not_persisted(export_store,change):
    conn,_=export_store
    with pytest.raises((ValueError,TypeError)):exports.prepare(conn,body(conn,extras=[extra(**change)]))


def test_formula_like_text_is_literal_in_both_sheets_and_remarks_are_retained(export_store):
    conn,_=export_store
    snapshot=exports.prepare(conn,body(conn,extras=[extra(category='=1+1',model='@SUM(A1)',usage='=HYPERLINK("http://example.invalid","x")',remark='+cmd')]))
    wb=load_workbook(BytesIO(xlsx.workbook(exports.views(snapshot))))
    for ws in wb:
        assert all(c.data_type!='f' for row in ws for c in row)
        assert ws['A2'].value=='=1+1' and ws['B2'].value.startswith('@SUM(A1)')
        assert '+cmd' in str(ws['E2'].value)+str(ws['B2'].value)


def test_many_requests_select_and_export_all_without_quantity_loss(export_store):
    conn,_=export_store;mid,_=material(conn);selected=[request(conn,mid,2)[0] for _ in range(150)]
    snapshot=exports.prepare(conn,body(conn,selected));view=exports.views(snapshot)
    assert view['request_count']==150 and view['quantity']==300 and view['specifications']==1 and len(view['packing'])==150
    wb=load_workbook(BytesIO(xlsx.workbook(view)));assert sum(r[3].value for r in list(wb['下单表'].rows)[1:])==300
    assert sum(c.value for row in wb['分装表'].iter_rows(min_row=2) for c in row if c.column==4 and isinstance(c.value,int))==300


def test_generation_failure_is_recorded_without_stock_or_notifications(export_store,monkeypatch):
    conn,ids=export_store;task=exports.enqueue(ids['admin'],submission(conn,body(conn,extras=[extra()])))
    monkeypatch.setattr(xlsx,'workbook',Mock(side_effect=ValueError('invalid worksheet')))
    assert inbound.run_one(job_id=task['task_id'])['state']=='failed'
    assert inbound.run_one(job_id=task['task_id']) is None
    with pytest.raises(LookupError):exports.download(conn,task['task_id'])
    assert next(r for r in exports.history(conn) if r['id']==task['task_id'])['error'].startswith('ValueError')


def test_api_all_routes_require_admin_before_source_or_files():
    from request_web.order_packing_api import register
    def deny():raise HTTPException(403,'仅管理员')
    api=FastAPI();register(api,deny)
    with TestClient(api) as client:
        for method,path in [('GET','catalog'),('GET','history'),('POST','preview'),('POST','generate'),('GET',str(uuid4())+'/download')]:
            assert client.request(method,'/api/admin/order-packing/'+path,json={}).status_code==403


def test_business_worker_never_claims_export_job(export_store,monkeypatch):
    conn,ids=export_store;task=exports.enqueue(ids['admin'],submission(conn,body(conn,extras=[extra()])))
    monkeypatch.setattr(jobs,'_run',lambda *a:pytest.fail('Export entered a business transaction'))
    monkeypatch.setenv('PUDU_CONCURRENT_EDIT_POLICY','last_commit_wins')
    assert jobs.run_one('admin') is None
