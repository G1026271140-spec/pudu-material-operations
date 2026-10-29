"""Isolated PostgreSQL reconciliation; no production data or external HTTP."""
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from test_postgres_jobs import conn
from material_store import manual_reconcile as manual,reconcile,inbound,repository as repo


@pytest.fixture
def isolated(conn,monkeypatch):
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(manual,'connection',same)
    monkeypatch.setattr(inbound,'connection',same)
    monkeypatch.setattr(reconcile,'connection',same)
    before=[r[0] for r in conn.execute('SELECT id FROM material_ops.jobs')]
    yield conn
    conn.execute('DELETE FROM material_ops.jobs WHERE NOT(id=ANY(%s::uuid[]))',(before,))


def body():return {'confirmed':True,'idempotency_key':str(uuid4())}


def test_enqueues_once_reuses_active_run_and_requires_confirmation(isolated):
    conn=isolated;payload=body()
    with pytest.raises(ValueError,match='确认'):manual.request('ou_admin',{**payload,'confirmed':False})
    first=manual.request('ou_admin',payload)
    assert not first['reused'] and first['manual']['state']=='pending'
    assert manual.request('ou_admin',payload)['task_id']==first['task_id']
    assert manual.request('ou_another_admin',body())['task_id']==first['task_id']
    with pytest.raises(ValueError,match='其他管理员'):manual.request('ou_another_admin',payload)
    assert conn.execute('SELECT count(*) FROM material_ops.jobs WHERE task_type=%s',(manual.TASK,)).fetchone()[0]==1


def test_existing_daily_exclusive_lock_blocks_request(isolated):
    import psycopg,os
    with psycopg.connect(os.environ['PUDU_TEST_DATABASE_DSN'],autocommit=True) as guard:
        guard.execute("SELECT pg_advisory_lock(hashtextextended('pudu-reconciliation',0))")
        try:
            with pytest.raises(ValueError,match='正在进行'):manual.request('ou_admin',body())
        finally:guard.execute("SELECT pg_advisory_unlock(hashtextextended('pudu-reconciliation',0))")


def test_inbound_worker_executes_outside_business_transaction_and_records_failure(isolated,monkeypatch):
    conn=isolated
    task=manual.request('ou_admin',body())
    observed=[]
    def run(clients,**kwargs):
        assert conn.info.transaction_status.name=='IDLE'
        observed.append(kwargs);kwargs['progress']({'stage':'source_fetch','fetched':2,'total':23})
        raise ValueError('飞书字段定义与数据库注册不一致：隔离表')
    monkeypatch.setattr(reconcile,'clients',lambda:{'primary':'fake'})
    monkeypatch.setattr(reconcile,'run',run)
    assert inbound.run_one(job_id=task['task_id'])['state']=='failed'
    status=manual.status(conn)['manual']
    assert status['state']=='failed' and status['progress']['fetched']==2
    assert observed[0]['trigger']=='manual' and observed[0]['actor']=='ou_admin'
    assert inbound.run_one(job_id=task['task_id']) is None


def test_full_manual_run_applies_only_after_all_tables_and_preserves_new_local_rows(isolated,monkeypatch):
    from material_store.client import DatabaseWriteClient
    from psycopg import sql
    import backend_runtime as runtime
    conn=isolated;infos=[repo.table(conn,r[0]) for r in conn.execute('SELECT table_id FROM material_meta.tables ORDER BY source_key,table_id')]
    with pytest.raises(RuntimeError,match='rollback'):
      with conn.transaction(),runtime.request_scope():
        info=repo.named_table(conn,'物料品类');key='test_manual_'+uuid4().hex
        repo.insert_source_records(conn,info,[{'record_id':key,'fields':{'物料品类':'飞书名称'}}])
        raw=repo.raw_record(conn,info,key)
        sources={i['table_id']:deepcopy(repo.rows(conn,i)) for i in infos}
        # Seed unsynced local data through the ordinary database writer.
        runtime.request_state.update(_write_conn=conn,_write_actor='ou_test',_write_lane='admin')
        DatabaseWriteClient(conn).update_record(info['table_id'],key,{'物料品类':'旧本地待同步名称'})
        new=DatabaseWriteClient(conn).batch_create_records(info['table_id'],[{'物料品类':'尚未同步的新建品类'}])[0]
        class Remote:
            def list_fields(self,tid):return next(i['fields'] for i in infos if i['table_id']==tid)
            def list_records(self,tid):return sources[tid]
        events=[]
        result=reconcile.run({'primary':Remote(),'apparel_admin':Remote()},progress=events.append,trigger='manual',actor='ou_test')
        assert result['tables']==len(infos) and result['trigger']=='manual' and result['conflicts']>=1
        assert repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']['物料品类']=='飞书名称'
        assert repo.raw_record(conn,info,new['record_id'])
        assert events[-1]['stage']=='done' and any(e.get('fetched')==len(infos) for e in events)
        assert conn.execute('SELECT state FROM material_ops.outbox WHERE table_id=%s AND record_key=%s',(info['table_id'],key)).fetchone()[0]=='conflict'
        raise RuntimeError('rollback')


def test_admin_api_rejects_other_roles_without_queueing(isolated,monkeypatch):
    import backend_runtime
    from request_web.database_api import register_database_api
    api=FastAPI()
    def deny():raise HTTPException(403,'仅管理员')
    register_database_api(api,deny)
    with TestClient(api) as client:
        assert client.get('/api/admin/database/reconcile').status_code==403
        assert client.post('/api/admin/database/reconcile',json=body()).status_code==403


def test_business_worker_cannot_claim_manual_reconciliation(isolated,monkeypatch):
    from material_store import jobs
    import backend_runtime
    conn=isolated
    task=manual.request('ou_admin',body())
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(jobs,'connection',same)
    monkeypatch.setattr(jobs,'_run',lambda *a:pytest.fail('Manual reconciliation entered a business transaction'))
    monkeypatch.setenv('PUDU_CONCURRENT_EDIT_POLICY','last_commit_wins')
    assert jobs.run_one('admin') is None
    assert conn.execute('SELECT state FROM material_ops.jobs WHERE id=%s',(task['task_id'],)).fetchone()[0]=='pending'
