from contextlib import contextmanager
from uuid import uuid4
import copy
import pytest
import app
from test_shipping_calendar import store
from test_account_tools import account_store
from material_store import company_permissions as company,permission_outbox_batch as bulk,user_permissions as permissions,portal_records as history,outbox_worker as worker,repository as repo

@pytest.fixture
def directory_store(account_store,monkeypatch):
    conn,ids=account_store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(company,'connection',same_connection);monkeypatch.setattr(bulk,'connection',same_connection)
    users,stamp=permissions.directory(conn);users.append({'open_id':'ou_provision_'+uuid4().hex,'name':'第二位未配置人员'})
    monkeypatch.setattr(permissions,'directory',lambda conn:(users,stamp))
    duplicate='rec_duplicate_'+uuid4().hex
    repo.insert_source_records(conn,repo.table(conn,company.TABLE),[{'record_id':duplicate,'fields':{'用户编号':'123','用户账号':[{'id':ids['sales']}],'角色':['HR'],'是否启用':'是','T恤-黑色（短袖）申领数量累计':1}}])
    return conn,ids

class Fake:
    def __init__(self,rows):self.records={r['record_id']:copy.deepcopy(r) for r in rows};self.created=0;self.timeout_once=False
    def list_records(self,tid):assert tid==company.TABLE;return list(self.records.values())
    def get_record(self,tid,key):return self.records[key]
    def batch_create_records(self,tid,records):
        result=[]
        for fields in records:
            key='rec_created_'+uuid4().hex;self.created+=1
            assert '用户编号' not in fields
            row={'record_id':key,'fields':{**copy.deepcopy(fields),'用户编号':str(2000+self.created)}}
            self.records[key]=row;result.append(row)
            if self.timeout_once:self.timeout_once=False;raise TimeoutError('Simulated partial batch and unknown result')
        return list(reversed(result))
    def update_record(self,tid,key,fields):self.records[key]['fields'].update(copy.deepcopy(fields))
    def delete_record(self,tid,key):del self.records[key]

def test_directory_backfill_merges_roles_without_double_counting_and_updates_both_stores(directory_store):
    conn,ids=directory_store;source=Fake(repo.rows(conn,repo.table(conn,company.TABLE)))
    draft=company.plan(conn);assert draft['summary']['new_sales_accounts']==2 and draft['summary']['duplicate_accounts']==1
    result=company.apply(draft);assert company.apply(draft)==result
    catalog=permissions.catalog(conn)
    assert all(p['configured'] and p['record_count']==1 for p in catalog['users'])
    person=next(p for p in catalog['users'] if p['open_id']==ids['sales'])
    assert set(person['roles'])=={'HR','销售'}
    before_count=source.created
    assert bulk.run_once(source)['records']==2
    assert source.created-before_count==2
    # The fixture owns a rollback transaction, including deletion's advisory
    # lock; publish on that connection instead of acquiring it from a second one.
    while task:=worker.claim('admin','isolated-company-test'):
        worker.finish(task,worker.publish(task,source))
    assert len(source.records)==len(catalog['users'])
    for row in repo.rows(conn,repo.table(conn,company.TABLE)):
        actor=app.feishu_person_open_ids(row['fields'],['用户账号'])[0]
        raw=repo.raw_record(conn,repo.table(conn,company.TABLE),row['record_id'])
        assert raw['sync_state']=='synced'
        assert app.feishu_person_open_ids(source.records[raw['remote_id']]['fields'],['用户账号'])==[actor]
        if actor==ids['sales']:assert app.feishu_int(row['fields'],'T恤-黑色（短袖）申领数量累计')==1
        if actor==ids['new']:assert row['fields']['角色']==['销售']
    assert company.plan(conn)['summary']=={'new_sales_accounts':0,'duplicate_accounts':0,'duplicate_records_removed':0,'links_remapped':0}

def test_partial_batch_retry_reuses_created_accounts_and_does_not_duplicate(directory_store):
    conn,ids=directory_store;source=Fake(repo.rows(conn,repo.table(conn,company.TABLE)))
    company.apply(company.plan(conn));source.timeout_once=True
    assert bulk.run_once(source)['state']=='retry'
    conn.execute("UPDATE material_ops.outbox SET available_at=now() WHERE state='retry'")
    assert bulk.run_once(source)['state']=='done'
    assert source.created==2
    assert len([r for r in source.records.values() if ids['new'] in app.feishu_person_open_ids(r['fields'],['用户账号'])])==1

def test_stale_directory_plan_rejects_all_changes(directory_store,monkeypatch):
    conn,ids=directory_store;draft=company.plan(conn)
    users,stamp=permissions.directory(conn)
    monkeypatch.setattr(permissions,'directory',lambda conn:(users+[{'open_id':'ou_stale_new','name':'Changed'}],stamp))
    with pytest.raises(repo.VersionConflict):company.apply(draft)
    assert conn.execute('SELECT count(*) FROM material_ops.outbox').fetchone()[0]==0

def test_disabled_duplicate_role_never_grants_admin_and_disabled_account_stays_disabled(directory_store):
    conn,ids=directory_store;info=repo.table(conn,company.TABLE)
    row=next(r for r in history.permission_rows(conn) if ids['other'] in app.feishu_person_open_ids(r['fields'],['用户账号']))
    row['fields']['是否启用']='否';repo.insert_source_records(conn,info,[row])
    repo.insert_source_records(conn,info,[{'record_id':'rec_disabled_'+uuid4().hex,'fields':{'用户账号':[{'id':ids['sales']}],'角色':['管理员'],'是否启用':'否','T恤-黑色（短袖）申领数量累计':1}}])
    company.apply(company.plan(conn))
    assert '管理员' not in history.roles_for(conn,ids['sales'])
    other=next(p for p in permissions.catalog(conn)['users'] if p['open_id']==ids['other'])
    assert not other['enabled']
