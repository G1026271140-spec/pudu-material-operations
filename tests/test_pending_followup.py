from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
import pytest
from psycopg import sql
import app
from material_store import pending_followup as follow,repository as repo,outbox_worker as worker
from material_store.client import DatabaseWriteClient
from test_approval_sync import graph
from test_shipping_calendar import store


@pytest.fixture
def pending(graph,monkeypatch):
    conn,info,lines,key,number,source=graph
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(follow,'connection',same)
    monkeypatch.setenv('PUDU_BUSINESS_WRITES_ENABLED','1');monkeypatch.setenv('PUDU_DATABASE_WORKFLOWS_ENABLED','1')
    fields=deepcopy(source.rows[info['table_id']][key]['fields'])
    fields.update({'申请类型':'普通物料申请','审批状态':app.REQUEST_STATUS_PENDING,'库存审查状态':'待核实库存','备注':'申请人原备注'})
    repo.insert_source_records(conn,info,[{'record_id':key,'fields':fields}]);source.rows[info['table_id']][key]={'record_id':key,'fields':fields}
    return graph


def body(conn,info,key,**kwargs):
    return {'label':'暂缓评估','note':'等待展会预算确认','expected_version':repo.raw_record(conn,info,key)['version'],'idempotency_key':uuid4().hex,**kwargs}


def named(data):
    conn,info,_,key,_,_=data
    return repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']


def test_label_local_commit_and_only_two_source_fields_no_workflow_effects(pending):
    conn,info,_,key,_,source=pending;before=deepcopy(named(pending))
    effect_count=conn.execute('SELECT count(*) FROM material_ops.effects').fetchone()[0]
    payload=body(conn,info,key);result=follow.save('ou_admin',key,payload)
    assert result['local_saved'] and result['changed'] and len(result['outbox_ids'])==1
    current=named(pending)
    assert current[follow.LABEL]=='暂缓评估' and current[follow.NOTE]=='等待展会预算确认'
    assert {k:v for k,v in current.items() if k not in [follow.LABEL,follow.NOTE]}==before
    assert follow.LABEL not in source.rows[info['table_id']][key]['fields']
    task=worker.claim('admin','isolated-followup')
    assert task and task['record_key']==key
    assert set(task['patch'])=={f['field_id'] for f in info['fields'] if f['field_name'] in [follow.LABEL,follow.NOTE]}
    worker.finish(task,worker.publish(task,source))
    assert source.rows[info['table_id']][key]['fields'][follow.LABEL]=='暂缓评估'
    assert conn.execute('SELECT count(*) FROM material_ops.effects').fetchone()[0]==effect_count
    assert follow.save('ou_admin',key,payload)==result
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE job_id=%s',(result['taskId'],)).fetchone()[0]==1


def test_clear_and_pending_summaries_use_local_fields_and_version(pending):
    conn,info,_,key,_,source=pending
    follow.save('ou_admin',key,body(conn,info,key))
    requests=app.pending_inventory_review_summaries(repo.rows(conn,info))
    row=next(r for r in follow.decorate(conn,requests) if r['requestId']==key)
    assert row['reviewLabel']=='暂缓评估' and row['reviewNote']=='等待展会预算确认' and row['recordVersion']>=1
    cleared=follow.save('ou_admin',key,body(conn,info,key,label='',note=''))
    assert cleared['request']['reviewLabel']=='' and cleared['request']['reviewNote']==''
    assert named(pending)['备注']=='申请人原备注'


@pytest.mark.parametrize('changes',[{'label':'x'*41},{'note':'x'*1001},{'label':[]},{'expected_version':999999},{'shipped':True}])
def test_invalid_inputs_rollback_job_and_all_business_data(pending,changes):
    conn,info,_,key,_,_=pending;before=deepcopy(named(pending))
    count=conn.execute('SELECT count(*) FROM material_ops.jobs').fetchone()[0]
    with pytest.raises((ValueError,repo.VersionConflict)):
        follow.save('ou_admin',key,body(conn,info,key,**changes))
    assert named(pending)==before
    assert conn.execute('SELECT count(*) FROM material_ops.jobs').fetchone()[0]==count


def test_completed_review_and_other_request_types_cannot_be_labeled(pending):
    conn,info,_,key,_,_=pending
    for update in [{'库存审查状态':app.INVENTORY_REVIEW_CONFIRMED},{'库存审查状态':'待核实库存','申请类型':'文化周边申请'}]:
        DatabaseWriteClient(conn).update_record(info['table_id'],key,update)
        with pytest.raises(ValueError,match='不属于待核实'):follow.save('ou_admin',key,body(conn,info,key))


def test_last_commit_policy_and_strict_version_checks_are_both_preserved(pending,monkeypatch):
    conn,info,_,key,_,_=pending
    first=body(conn,info,key);second={**first,'label':'后提交标签','idempotency_key':uuid4().hex}
    follow.save('ou_first_admin',key,first)
    with pytest.raises(repo.VersionConflict):follow.save('ou_second_admin',key,second)
    monkeypatch.setenv('PUDU_CONCURRENT_EDIT_POLICY','last_commit_wins')
    follow.save('ou_second_admin',key,second)
    assert named(pending)[follow.LABEL]=='后提交标签'
    with pytest.raises(ValueError,match='不同的业务数据'):
        follow.save('ou_second_admin',key,{**second,'note':'changed retry'})


def test_followup_endpoint_enforces_existing_admin_dependency(monkeypatch):
    from fastapi import FastAPI,HTTPException
    from fastapi.testclient import TestClient
    from request_web.pending_followup_api import register
    application=FastAPI()
    def denied():raise HTTPException(403,'admin only')
    register(application,denied)
    monkeypatch.setattr(follow,'save',lambda *a:(_ for _ in ()).throw(AssertionError('must not reach business code')))
    assert TestClient(application).post('/api/admin/allocation/request/follow-up',json={}).status_code==403


def test_schema_extension_is_additive_and_refuses_wrong_source_types():
    from material_store.pending_followup_schema import extend,register_sql
    snapshot={'tables':[{'table_id':'tblTest','table_name':'物料申请单','fields':[{'field_id':'fldOld','field_name':'备注','type':1}]}]}
    live=[{'field_id':'fldLabel','field_name':follow.LABEL,'type':1},{'field_id':'fldNote','field_name':follow.NOTE,'type':1}]
    result,table,added=extend(snapshot,live)
    assert snapshot['tables'][0]['fields']==[{'field_id':'fldOld','field_name':'备注','type':1}]
    assert len(table['fields'])==3 and extend(result,live)[0]==result
    statement=register_sql(table,added)
    assert 'ADD COLUMN IF NOT EXISTS' in statement and 'DROP' not in statement and 'DELETE' not in statement
    with pytest.raises(ValueError):extend(snapshot,[{**r,'type':2} for r in live])
