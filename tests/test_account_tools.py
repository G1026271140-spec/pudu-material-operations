from contextlib import contextmanager
from uuid import uuid4
import json
from unittest.mock import Mock
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient

import app,backend_runtime as runtime
from test_shipping_calendar import store,insert_request
from material_store import portal_records as history,user_permissions as permissions,repository as repo,apparel,jobs,effects,outbox_worker
from material_store.client import DatabaseWriteClient
from request_web.live_data import LiveReader

@pytest.fixture
def account_store(store,monkeypatch):
    conn=store
    @contextmanager
    def same_connection():yield conn
    for module in [history,permissions,apparel,jobs,effects,outbox_worker]:monkeypatch.setattr(module,'connection',same_connection)
    for name in ['FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_BITABLE_APP_TOKEN','FEISHU_CORPORATE_APPAREL_SOURCE_APP_TOKEN']:monkeypatch.setenv(name,'test')
    monkeypatch.setenv('FEISHU_CORPORATE_APPAREL_SOURCE_APP_TOKEN','test-apparel')
    ids={name:'ou_test_'+name+'_'+uuid4().hex for name in ['admin','hr','sales','other','new']}
    users=[{'open_id':identity,'name':'同名员工' if name in ['sales','other'] else name,'department_paths':['测试部门']} for name,identity in ids.items()]
    monkeypatch.setattr(permissions,'directory',lambda conn:(users,'2026-10-28'))
    info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    for name in ['admin','hr','sales','other']:
        repo.insert_source_records(conn,info,[{'record_id':'rec_'+uuid4().hex,'fields':{'用户编号':'test-'+uuid4().hex,'用户账号':[{'id':ids[name]}],'角色':[{'admin':'管理员','hr':'HR'}.get(name,'销售')],'是否启用':'是','T恤-黑色（短袖）申领数量累计':1}}])
    return conn,ids

def request(conn,owner,kind):
    return insert_request(conn,申请人=[{'id':owner,'name':'同名员工'}],申请类型=kind,文化周边处理状态='已发放')

def permission_body(conn,who,**changes):
    row=next(item for item in permissions.catalog(conn)['users'] if item['open_id']==who)
    return {'open_id':who,'roles':row['roles'],'enabled':row['enabled'],'expected_version':row['version'],'idempotency_key':'permission-'+uuid4().hex,**changes}

def test_role_scopes_hr_both_cultural_types_admin_all_and_personal(account_store):
    conn,ids=account_store
    rows={}
    for name in ['sales','other','admin','hr']:
        for kind in history.TYPES:rows[name,kind]=request(conn,ids[name],kind)
    own=history.history(conn,ids['sales'])
    assert {row['id'] for row in own['requests']}=={rid for (name,kind),rid in rows.items() if name=='sales'}
    with pytest.raises(PermissionError):history.history(conn,ids['sales'],'all')
    hr=history.history(conn,ids['hr'],'all')
    assert hr['mode']=='hr' and hr['types']==list(history.TYPES[1:])
    assert {rid for (name,kind),rid in rows.items() if kind in history.TYPES[1:]}<={row['id'] for row in hr['requests']}
    assert not any(row['type']==history.TYPES[0] for row in hr['requests'])
    admin=history.history(conn,ids['admin'],'all')
    assert set(rows.values())<={row['id'] for row in admin['requests']}
    assert {row['id'] for row in history.history(conn,ids['admin'],'mine')['requests']}=={rid for (name,kind),rid in rows.items() if name=='admin'}

def test_history_preserves_deleted_rows_and_never_cross_links_other_owner_details(account_store):
    from psycopg import sql
    conn,ids=account_store;one=request(conn,ids['sales'],history.TYPES[0]);two=request(conn,ids['other'],history.TYPES[0])
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME);line=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)
    number=repo.feishu_record(info,repo.raw_record(conn,info,one))['fields']['申请单号']
    repo.insert_source_records(conn,line,[{'record_id':'rec_'+uuid4().hex,'fields':{'所属申请单':[two],'品类名称':'OTHER-OWNER-SECRET','申请数量':1}}])
    conn.execute(sql.SQL('UPDATE material_data.{} SET _deleted=true WHERE _record_key=%s').format(sql.Identifier(info['sql_table'])),(one,))
    row=next(row for row in history.history(conn,ids['sales'])['requests'] if row['id']==one)
    assert row['deleted'] and row['status']=='已撤回 / 已删除'
    assert not any(line['product']=='OTHER-OWNER-SECRET' for line in row['lines'])

def test_quotas_include_all_styles_and_legacy_counters(account_store):
    conn,ids=account_store
    key='apparel_test_'+uuid4().hex
    repo.insert_source_records(conn,apparel.source_info(conn),[{'record_id':'rec_'+uuid4().hex,'fields':{'物品分类':'文化衫','款式':app.CORPORATE_APPAREL_STYLE_MAP['T恤-黑色（短袖）'],'码数':'M','原始库存数量':5}}])
    repo.insert_source_records(conn,apparel.source_info(conn),[{'record_id':'rec_'+uuid4().hex,'fields':{'物品分类':'文化衫','款式':'文化衫-测试新款-'+key,apparel.KEY:key,apparel.LABEL:'测试新款',apparel.VISIBLE:'是',apparel.LIMIT:3,'码数':'M','原始库存数量':5,'系统兑换数量':2}}])
    parent=request(conn,ids['sales'],history.TYPES[2]);line=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)
    repo.insert_source_records(conn,line,[{'record_id':'rec_'+uuid4().hex,'fields':{'所属申请单':[parent],'明细业务类型':app.CORPORATE_APPAREL_LINE_TYPE,'申请数量':2,'实际发放数量':2,'备注':apparel.STYLE_MARKER+':'+key}}])
    quotas={item['key']:item for item in history.history(conn,ids['sales'])['quotas']}
    assert len(quotas)==2
    assert quotas['T恤-黑色（短袖）']['used']==1
    assert quotas[key]['used']==2 and quotas[key]['remaining']==1 and quotas[key]['limit']==3

def test_permission_update_preserves_quotas_and_rejects_stale_or_unprivileged_edits(account_store):
    conn,ids=account_store
    before=next(row for row in history.permission_rows(conn) if ids['sales'] in app.feishu_person_open_ids(row['fields'],['用户账号']))
    body=permission_body(conn,ids['sales'],roles=['HR','销售'])
    result=permissions.save(ids['admin'],body)
    assert permissions.save(ids['admin'],body)==result
    after=repo.feishu_record(repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME),repo.raw_record(conn,repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME),before['record_id']))['fields']
    assert after['T恤-黑色（短袖）申领数量累计']==before['fields']['T恤-黑色（短袖）申领数量累计']
    assert after['角色']==['HR','销售']
    with pytest.raises(repo.VersionConflict):permissions.save(ids['admin'],{**body,'idempotency_key':'stale-'+uuid4().hex})
    with pytest.raises(PermissionError):permissions.save(ids['other'],permission_body(conn,ids['sales']))
    with pytest.raises(ValueError):permissions.save(ids['admin'],permission_body(conn,ids['sales'],roles=['超级管理员']))

def test_new_directory_person_can_receive_permissions_and_remote_create_deduplicates_by_account(account_store):
    conn,ids=account_store;result=permissions.save(ids['admin'],permission_body(conn,ids['new'],roles=['HR']))
    row=next(row for row in history.permission_rows(conn) if ids['new'] in app.feishu_person_open_ids(row['fields'],['用户账号']))
    assert row['fields']['角色']==['HR']
    info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME);source=Mock()
    fields={'用户账号':[{'id':ids['new']}],'角色':['HR'],'是否启用':'是'}
    source.list_records.return_value=[{'record_id':'rec_remote','fields':fields}]
    assert outbox_worker._find_remote_create(source,info,fields)['record_id']=='rec_remote'
    source.list_records.return_value=[{'record_id':'rec_remote','fields':{**fields,'角色':['管理员']}}]
    with pytest.raises(outbox_worker.SourceConflict):outbox_worker._find_remote_create(source,info,fields)
    with pytest.raises(ValueError):permissions.save(ids['admin'],{**permission_body(conn,ids['new']),'open_id':'ou_unknown'})

def test_last_enabled_administrator_is_protected(account_store):
    conn,ids=account_store;info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    for row in history.permission_rows(conn):
        if ids['admin'] in app.feishu_person_open_ids(row['fields'],['用户账号']):continue
        raw=repo.raw_record(conn,info,row['record_id'])
        repo.replace_values(conn,info,row['record_id'],{**raw['fields'],**repo.source_values(info,{'角色':['销售']})})
    with pytest.raises(ValueError,match='至少一名'):permissions.save(ids['admin'],permission_body(conn,ids['admin'],roles=['销售']))

def test_apparel_history_rejection_restores_once_and_updates_existing_cards_after_outbox(account_store,monkeypatch):
    conn,ids=account_store
    # Construct a real source-backed claim using the same transaction builder.
    draft={'operation':'create','idempotency_key':'style-'+uuid4().hex,'source_style':'文化衫-测试-'+uuid4().hex,'label':'测试款','visible':True,'limit':2,'rows':[{'record_id':'','size':'M','code':'TEST-'+uuid4().hex,'original':5,'correction':0,'remark':''}]}
    style=apparel.save(ids['admin'],draft)['style_key']
    runtime.request_state.update(_write_conn=conn,_write_actor=ids['sales'],_write_lane='cultural',_live_reader=LiveReader())
    payload={'requester':'测试申领人','requester_open_id':ids['sales'],'submitter':'测试申领人','submitter_open_id':ids['sales'],'department':'测试部门','department_id':'','material_usage':'入职','submission_token':'claim-'+uuid4().hex}
    number,_,_=app.submit_feishu_corporate_apparel_request(payload,app.corporate_apparel_request_plan(payload,[{'product':style,'size':'M','quantity':1}]))
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    row=next(row for row in repo.rows(conn,info) if row['fields'].get('申请单号')==number)
    recipients={f'applicant:{ids["sales"]}':'om_existing_applicant'}
    for hr in app.enabled_role_open_ids('HR'):recipients['hr:'+hr]='om_existing_hr_'+hr
    DatabaseWriteClient(conn).update_record(info['table_id'],row['record_id'],{app.CULTURAL_REQUEST_MESSAGE_IDS_FIELD:json.dumps(recipients)})
    result=history.reject_apparel(ids['hr'],{'request_id':row['record_id'],'confirmed':True})
    assert result['rejected']
    assert history.reject_apparel(ids['admin'],{'request_id':row['record_id'],'confirmed':True})['rejected']
    assert apparel.claim_used(ids['sales'],style)==0
    source=next(group for group in apparel.manager_catalog(conn)['styles'] if group['key']==style)
    assert source['rows'][0]['available']==5
    raw=repo.raw_record(conn,info,row['record_id']);fields=repo.feishu_record(info,raw)['fields']
    assert fields['文化周边处理状态']=='已驳回' and fields['文化周边通知状态']=='驳回待通知'
    # Isolate the effect delivery worker from unrelated fixture jobs.
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id<>%s AND state IN ('pending','processing','retry')",(result['job_id'],))
    fake=Mock();fake.update_interactive_message.return_value=None
    assert effects.run_once({'primary':fake}) is None
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state IN ('pending','processing','retry')")
    for _ in recipients:assert effects.run_once({'primary':fake})['state']=='done'
    assert {call.args[0] for call in fake.update_interactive_message.call_args_list}==set(recipients.values())
    assert fake.send_interactive_message.call_count==0
    assert all(call.args[1]['header']['title']['content']=='企业文化衫领取已驳回' for call in fake.update_interactive_message.call_args_list)
    fields=repo.feishu_record(info,repo.raw_record(conn,info,row['record_id']))['fields']
    assert fields['文化周边通知状态']=='驳回已通知'

def test_sales_cannot_reject_and_hr_cannot_reject_ordinary_request(account_store):
    conn,ids=account_store;key=request(conn,ids['sales'],history.TYPES[0])
    with pytest.raises(PermissionError):history.reject_apparel(ids['sales'],{'request_id':key,'confirmed':True})
    with pytest.raises(ValueError,match='仅适用'):history.reject_apparel(ids['hr'],{'request_id':key,'confirmed':True})

def test_history_and_permission_routes_enforce_dependencies_before_data_access():
    from request_web.portal_records_api import register
    def denied():raise HTTPException(403,'Denied')
    api=FastAPI();register(api,denied,denied,denied)
    with TestClient(api) as client:
        for method,path in [('GET','/api/request-history'),('GET','/api/admin/user-permissions'),('POST','/api/admin/user-permissions'),('POST','/api/request-history/reject-apparel')]:
            assert client.request(method,path,json={}).status_code==403

def test_deleted_card_is_replaced_once_with_same_effect_uuid(account_store):
    conn,ids=account_store
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','processing','retry')")
    task,_=jobs.enqueue('测试任务','card-fallback-'+uuid4().hex,{},conn=conn)
    runtime.request_state.update(_write_conn=conn,_job_id=task.task_id,_effect_ordinal=0)
    card={'opaque':'existing card payload'}
    effects.defer('primary','update_interactive_message',['om_deleted',card],{'_fallback_recipient':ids['sales']})
    fake=Mock();fake.update_interactive_message.side_effect=RuntimeError('230031 message deleted')
    fake._request.return_value={'data':{'message_id':'om_replacement'}}
    result=effects.run_once({'primary':fake})
    assert result['state']=='done'
    sent=fake._request.call_args.kwargs['payload']
    assert sent['receive_id']==ids['sales'] and sent['uuid']==result['id']
    assert json.loads(sent['content'])==card
    assert effects.run_once({'primary':fake}) is None


def test_quota_visibility_matches_claim_catalog_and_retains_hidden_history_and_counters(account_store):
    conn,ids=account_store
    source=apparel.source_info(conn);line=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)
    keys=['apparel_visible_'+uuid4().hex,'apparel_hidden_'+uuid4().hex]
    records=['rec_'+uuid4().hex for _ in keys]
    repo.insert_source_records(conn,source,[{'record_id':rid,'fields':{
        '物品分类':'文化衫','款式':'文化衫-'+key,apparel.KEY:key,apparel.LABEL:label,
        apparel.VISIBLE:visible,apparel.LIMIT:3,'码数':'M','原始库存数量':0}}
        for rid,key,label,visible in zip(records,keys,['开放款式','隐藏款式'],['是','否'])])
    parent=request(conn,ids['sales'],history.TYPES[2])
    repo.insert_source_records(conn,line,[{'record_id':'rec_'+uuid4().hex,'fields':{
        '所属申请单':[parent],'品类名称':label,'明细业务类型':app.CORPORATE_APPAREL_LINE_TYPE,
        '申请数量':used,'实际发放数量':used,'备注':apparel.STYLE_MARKER+':'+key}}
        for key,label,used in zip(keys,['开放款式','隐藏款式'],[3,2])])
    def view():return history.history(conn,ids['sales'])
    before=view()
    quota={item['key']:item for item in before['quotas']}
    assert set(quota)=={keys[0]}
    assert quota[keys[0]]['used']==3 and quota[keys[0]]['remaining']==0
    assert set(quota)==set(apparel.catalog([],repo.rows(conn,source))['products'])
    assert any(item['id']==parent and any(detail['product']=='隐藏款式' for detail in item['lines']) for item in before['requests'])
    # Local visibility edits must affect both views immediately, before outbox delivery.
    client=DatabaseWriteClient(conn,'apparel_admin')
    client.update_record(source['table_id'],records[0],{apparel.VISIBLE:'否'})
    client.update_record(source['table_id'],records[1],{apparel.VISIBLE:'是'})
    after=view();quota={item['key']:item for item in after['quotas']}
    assert set(quota)=={keys[1]}==set(apparel.catalog([],repo.rows(conn,source))['products'])
    assert quota[keys[1]]['used']==2 and quota[keys[1]]['remaining']==1
    assert after['requests']==before['requests']
    assert all(repo.raw_record(conn,source,rid)['sync_state']=='pending' for rid in records)
