from contextlib import contextmanager
import importlib,json
from uuid import uuid4,UUID
from unittest.mock import Mock
import pytest
from starlette.requests import Request
from test_account_tools import account_store
from test_shipping_calendar import store
from material_store import contacts,inbound,jobs,repository as repo,user_permissions as permissions,portal_records as history
import app

def duplicate(conn,actor,roles,enabled='是',used=7):
    info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME);key='rec_duplicate_'+uuid4().hex
    repo.insert_source_records(conn,info,[{'record_id':key,'fields':{'用户账号':[{'id':actor}],'角色':roles,'是否启用':enabled,'T恤-黑色（短袖）申领数量累计':used}}])
    return key

def body(conn,actor,**changes):
    row=next(row for row in permissions.catalog(conn)['users'] if row['open_id']==actor)
    return {'open_id':actor,'roles':row['roles'],'enabled':row['enabled'],'expected_version':row['version'],
            'expected_versions':row['versions'],'idempotency_key':'union-'+uuid4().hex,**changes}

def test_duplicate_roles_union_matches_effective_access_and_keeps_disabled_roles_disabled(account_store):
    conn,ids=account_store
    duplicate(conn,ids['sales'],['HR']);duplicate(conn,ids['sales'],['管理员'],'否')
    item=next(row for row in permissions.catalog(conn)['users'] if row['open_id']==ids['sales'])
    assert set(item['roles'])=={'销售','HR'}
    assert item['enabled'] and item['record_count']==3 and len(item['versions'])==3
    assert history.roles_for(conn,ids['sales'])=={'销售','HR'}

def test_all_duplicate_permission_rows_saved_and_quota_counters_unchanged(account_store):
    conn,ids=account_store;duplicate(conn,ids['sales'],['HR'],used=7)
    info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    before={row['record_id']:row['fields']['T恤-黑色（短袖）申领数量累计'] for row in history.permission_rows(conn) if ids['sales'] in app.feishu_person_open_ids(row['fields'],['用户账号'])}
    draft=body(conn,ids['sales'],roles=['区域市场经理','销售'])
    result=permissions.save(ids['admin'],draft)
    assert result['updated_records']==2 and permissions.save(ids['admin'],draft)==result
    for key,used in before.items():
        fields=repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']
        assert fields['角色']==['区域市场经理','销售'] and fields['T恤-黑色（短袖）申领数量累计']==used
        tasks=conn.execute('SELECT patch FROM material_ops.outbox WHERE record_key=%s',(key,)).fetchall()
        role_id=next(f['field_id'] for f in info['fields'] if f['field_name']=='角色')
        assert tasks and set(tasks[-1][0])=={role_id}
    assert history.roles_for(conn,ids['sales'])=={'区域市场经理','销售'}
    with pytest.raises(repo.VersionConflict):permissions.save(ids['admin'],{**draft,'idempotency_key':'stale-'+uuid4().hex})

def test_added_duplicate_after_preview_rejects_all_writes(account_store):
    conn,ids=account_store;draft=body(conn,ids['sales'],roles=['HR'])
    duplicate(conn,ids['sales'],['销售'])
    with pytest.raises(repo.VersionConflict):permissions.save(ids['admin'],draft)
    assert history.roles_for(conn,ids['sales'])=={'销售'}

def test_login_identity_uses_union_of_enabled_duplicate_records(monkeypatch):
    web=importlib.import_module('request_web.api')
    from request_web import feishu_auth
    actor='ou_union_identity'
    monkeypatch.setattr(feishu_auth,'session_identity',lambda *a:{'open_id':actor,'name':'员工','avatar_url':''})
    monkeypatch.setattr(feishu_auth,'own_tenant_key',lambda:'tenant')
    monkeypatch.setattr(web.backend_runtime,'realtime_reads',lambda:True)
    rows=[{'fields':{'用户账号':[{'id':actor}],'角色':roles,'是否启用':enabled}} for roles,enabled in [(['销售'],'是'),(['HR'],'是'),(['管理员'],'否')]]
    monkeypatch.setattr(web,'_json',lambda name:{'tables':{'用户权限表':rows}})
    result=web.current_feishu_user(Request({'type':'http','headers':[]}))
    data=json.loads(result.body)
    assert set(data['roles'])=={'销售','HR'} and data['permission_status']=='enabled'

def test_directory_refresh_is_durable_coalesced_and_published_by_worker(account_store,monkeypatch):
    conn,ids=account_store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(contacts,'connection',same_connection);monkeypatch.setattr(inbound,'connection',same_connection)
    payload={'users':[{'open_id':'ou_new_directory_person','name':'新同事'}],'departments':[{'department_id':'dep','name':'部门'}]}
    fetch=Mock(return_value=payload);monkeypatch.setattr(app,'build_live_contact_department_cache',fetch)
    task=contacts.enqueue_refresh(ids['admin']);same=contacts.enqueue_refresh(ids['admin'])
    assert task==same and fetch.call_count==0
    assert jobs.run_one(job_id=task['job_id'])['state']=='done'
    assert fetch.call_count==1
    result=contacts.refresh_status(UUID(task['job_id']))
    assert result['state']=='done' and result['result']['users']==1
    saved=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',(contacts.NAME,)).fetchone()[0]
    assert saved['users'][0]['name']=='新同事'
    with pytest.raises(PermissionError):contacts.enqueue_refresh(ids['sales'])

def test_partial_directory_fetch_fails_without_replacing_last_good_directory(account_store,monkeypatch):
    conn,ids=account_store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(contacts,'connection',same_connection);monkeypatch.setattr(inbound,'connection',same_connection)
    original={'users':[{'open_id':'ou_old','name':'原同事'}],'departments':[{'name':'原部门'}]}
    contacts.publish(conn,original)
    monkeypatch.setattr(app,'build_live_contact_department_cache',lambda:{'users':[{'name':'不完整'}],'departments':[]})
    task=contacts.enqueue_refresh(ids['admin'])
    assert jobs.run_one(job_id=task['job_id'])['state']=='failed'
    assert contacts.refresh_status(UUID(task['job_id']))['state']=='failed'
    saved=conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',(contacts.NAME,)).fetchone()[0]
    assert saved==original
