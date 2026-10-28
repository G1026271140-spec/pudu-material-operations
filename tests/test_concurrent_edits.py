"""Last-commit policy uses real isolated PG, without employee messages."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from threading import Event
from uuid import uuid4
import pytest
from psycopg import sql
import psycopg
from material_store import concurrency, repository as repo, shipping_calendar as shipping, apparel, user_permissions as permissions
from test_shipping_calendar import store, insert_request, draft as shipping_draft
from test_account_tools import account_store, permission_body
from test_apparel_management import draft as apparel_draft
from test_postgres_jobs import conn as jobs_conn

@pytest.fixture(autouse=True)
def policy(monkeypatch):
    monkeypatch.setenv('PUDU_CONCURRENT_EDIT_POLICY','last_commit_wins')

@pytest.mark.parametrize('expected',[True,-1,3,'0',None])
def test_invalid_or_future_versions_still_rejected(expected):
    with pytest.raises(repo.VersionConflict):concurrency.check_version(expected,2,'invalid')

def test_old_shipping_editor_wins_but_old_retry_does_not_overwrite(store):
    conn=store;key=insert_request(conn)
    old=shipping_draft(conn,key,shipping_text='first administrator')
    later={**old,'idempotency_key':'second-'+uuid4().hex,'shipping_text':'last administrator'}
    one=shipping.save('ou_one',old);two=shipping.save('ou_two',later)
    assert two['version']>one['version']
    assert shipping.save('ou_one',old)==one
    fields=repo.feishu_record(shipping.source_info(conn),repo.raw_record(conn,shipping.source_info(conn),key))['fields']
    assert fields[shipping.TEXT]=='last administrator' and fields['备注']=='申请人：隔离发货验收'
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE record_key=%s',(key,)).fetchone()[0]==2

def test_old_batch_editor_applies_latest_explicit_fields_atomically(account_store):
    conn,ids=account_store;key=insert_request(conn,申请人=[{'id':ids['sales']}])
    item=shipping_draft(conn,key);item.pop('idempotency_key')
    body={'changes':[item],'confirmed':True,'idempotency_key':'batch-'+uuid4().hex}
    shipping.save_batch(ids['admin'],body)
    shipping.save_batch(ids['admin'],{**body,'idempotency_key':'batch-later-'+uuid4().hex,'changes':[{**item,'shipping_text':'second batch'}]})
    fields=repo.feishu_record(shipping.source_info(conn),repo.raw_record(conn,shipping.source_info(conn),key))['fields']
    assert fields[shipping.TEXT]=='second batch'

def test_permission_later_roles_win_and_counters_survive(account_store):
    conn,ids=account_store
    body=permission_body(conn,ids['sales'],roles=['HR'])
    permissions.save(ids['admin'],body)
    permissions.save(ids['admin'],{**body,'roles':['销售','区域市场经理'],'idempotency_key':'later-'+uuid4().hex})
    person=next(p for p in permissions.catalog(conn)['users'] if p['open_id']==ids['sales'])
    assert set(person['roles'])=={'销售','区域市场经理'}
    info=repo.named_table(conn,'用户权限表')
    fields=repo.feishu_record(info,repo.raw_record(conn,info,person['record_id']))['fields']
    assert fields['T恤-黑色（短袖）申领数量累计']==1

def test_apparel_later_edit_uses_current_inventory_counters(account_store):
    conn,ids=account_store;body=apparel_draft();created=apparel.save(ids['admin'],body)
    style=next(s for s in apparel.manager_catalog(conn)['styles'] if s['key']==created['style_key'])
    old={**body,'operation':'edit','style_key':created['style_key'],'rows':style['rows'],'expected_versions':style['expected_versions']}
    apparel.save(ids['admin'],{**old,'label':'First-'+uuid4().hex,'idempotency_key':'edit-one-'+uuid4().hex})
    name='Last-'+uuid4().hex
    apparel.save(ids['admin'],{**old,'label':name,'idempotency_key':'edit-two-'+uuid4().hex})
    current=next(s for s in apparel.manager_catalog(conn)['styles'] if s['key']==created['style_key'])
    assert current['label']==name and current['rows'][0]['original']==7

def test_two_connections_serialize_same_cell_and_audit_both_commits(monkeypatch):
    dsn=os.environ.get('PUDU_TEST_DATABASE_DSN')
    if not dsn:pytest.skip('Requires isolated PostgreSQL')
    key='rec_concurrent_'+uuid4().hex
    with psycopg.connect(dsn,autocommit=True) as conn:
        assert conn.execute('SELECT current_database()').fetchone()[0]=='pudu_materials_test'
        info=repo.named_table(conn,'物料语种')
        fid=next(f['field_id'] for f in info['fields'] if f['field_name']=='语言种类')
        repo.insert_source_records(conn,info,[{'record_id':key,'fields':{'语言种类':'initial'}}])
        version=repo.raw_record(conn,info,key)['version']
    locked,release,second_started=Event(),Event(),Event()
    def first():
        with psycopg.connect(dsn,autocommit=True) as conn,conn.transaction():
            result=repo.patch_record(conn,info['table_id'],key,{fid:'first'},version,'first-'+uuid4().hex,'ou_first')
            locked.set();assert release.wait(10)
            return result
    def second():
        assert locked.wait(10);second_started.set()
        with psycopg.connect(dsn,autocommit=True) as conn:
            return repo.patch_record(conn,info['table_id'],key,{fid:'last'},version,'second-'+uuid4().hex,'ou_second')
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            one=executor.submit(first);two=executor.submit(second)
            try:assert second_started.wait(10)
            finally:release.set()
            a,b=one.result(15),two.result(15)
        assert b['version']==a['version']+1
        with psycopg.connect(dsn,autocommit=True) as conn:
            assert repo.raw_record(conn,info,key)['fields'][fid]=='last'
            assert conn.execute("SELECT actor_open_id FROM material_ops.audit WHERE record_key=%s AND field_id=%s ORDER BY local_version",(key,fid)).fetchall()==[('ou_first',),('ou_second',)]
            versions=conn.execute('SELECT local_version FROM material_ops.outbox WHERE record_key=%s ORDER BY local_version',(key,)).fetchall()
            assert versions==[(a['version'],),(b['version'],)]
    finally:
        with psycopg.connect(dsn,autocommit=True) as conn,conn.transaction():
            conn.execute('DELETE FROM material_ops.outbox WHERE record_key=%s',(key,))
            conn.execute('DELETE FROM material_ops.audit WHERE record_key=%s',(key,))
            conn.execute(sql.SQL('DELETE FROM material_data.{} WHERE _record_key=%s').format(sql.Identifier(info['sql_table'])),(key,))

def test_cross_lane_outbox_waits_for_old_version_and_publishes_last_value(store,monkeypatch):
    from unittest.mock import Mock
    from material_store import outbox_worker as outbox
    conn=store;info=repo.named_table(conn,'物料语种');key='rec_order_'+uuid4().hex
    repo.insert_source_records(conn,info,[{'record_id':key,'fields':{'语言种类':'initial'}}])
    fid=next(f['field_id'] for f in info['fields'] if f['field_name']=='语言种类')
    old=repo.raw_record(conn,info,key,lock=True)
    one=repo._save_change(conn,info,old,{fid:'first'},'ou_a','order-a-'+uuid4().hex,'admin')
    repo._save_change(conn,info,one,{fid:'last'},'ou_b','order-b-'+uuid4().hex,'ordinary')
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(outbox,'connection',same)
    assert outbox.claim('ordinary','second') is None
    first=outbox.claim('admin','first')
    assert first['record_key']==key and first['version']==one['version']
    assert outbox.claim('ordinary','second') is None
    outbox.finish(first,key)
    second=outbox.claim('ordinary','second')
    client=Mock();client.get_record.return_value={'record_id':key,'fields':{'语言种类':'first'}}
    assert outbox.publish(second,client)==key
    client.update_record.assert_called_once_with(info['table_id'],key,{'语言种类':'last'})
    outbox.finish(second,key)
    row=repo.raw_record(conn,info,key)
    assert row['fields'][fid]=='last' and row['sync_state']=='synced'

def test_later_http_job_drains_old_intent_first_and_cannot_bypass_retry(jobs_conn,monkeypatch):
    from material_store import jobs
    conn=jobs_conn;identities=[];seen=[]
    monkeypatch.setattr(jobs,'dispatch',lambda task,checkpoint:seen.append(task.payload['value']) or {})
    try:
        first,_=jobs.enqueue('测试并发顺序','queue-a-'+uuid4().hex,{'value':'first'})
        later,_=jobs.enqueue('测试并发顺序','queue-b-'+uuid4().hex,{'value':'last'})
        identities=[first.task_id,later.task_id]
        conn.execute("UPDATE material_ops.jobs SET state='retry',available_at=now()+interval '1 hour' WHERE id=%s",(first.task_id,))
        assert jobs.run_one(job_id=later.task_id) is None
        assert seen==[]
        conn.execute('UPDATE material_ops.jobs SET available_at=now() WHERE id=%s',(first.task_id,))
        assert jobs.run_one(job_id=later.task_id,raise_errors=True)['id']==first.task_id
        assert jobs.run_one(job_id=later.task_id,raise_errors=True)['id']==later.task_id
        assert seen==['first','last']
    finally:
        conn.execute('DELETE FROM material_ops.jobs WHERE id::text=ANY(%s)',(identities,))
