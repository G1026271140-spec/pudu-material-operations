from contextlib import contextmanager
from datetime import datetime, timezone, date
import importlib
import os
from uuid import uuid4

import pytest
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import app
import backend_runtime as runtime
from material_store import repository as repo, task_monitor as monitor, task_activity as activity, db
from request_web.task_monitor_api import register


@pytest.fixture
def fixture(monkeypatch):
    dsn=os.environ.get('PUDU_TEST_DATABASE_DSN')
    if not dsn:pytest.skip('Requires isolated test database')
    monkeypatch.setenv('PUDU_DATABASE_DSN',dsn);monkeypatch.setenv('PUDU_DATA_SOURCE','postgresql')
    with psycopg.connect(dsn,autocommit=True) as conn:
        assert conn.execute('SELECT current_database()').fetchone()[0]=='pudu_materials_test'
        key='monitor_'+uuid4().hex;info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
        rid='rec_'+key;number='REQ-'+key
        repo.insert_source_records(conn,info,[{'record_id':rid,'fields':{'申请单号':number}}])
        jobs=[];outbox=[];effects=[];runs=[]
        for n,state in enumerate(['pending','done','failed']):
            job=str(conn.execute("INSERT INTO material_ops.jobs(idempotency_key,task_type,lane,payload,state,last_error,created_at) VALUES (%s,%s,'admin',%s,%s,%s,'2026-10-29 12:00:00+08') RETURNING id",
                (key+str(n),'配货测试',Jsonb({'draft':{'request_id':rid,'secret':'never-expose','submission_token':'private'}}),state,'app_secret=hidden-value' if state=='failed' else None)).fetchone()[0]);jobs.append(job)
            outbox.append(str(conn.execute("INSERT INTO material_ops.outbox(idempotency_key,lane,table_id,record_key,local_version,patch,operation,state,job_id,created_at) VALUES (%s,'admin',%s,%s,%s,%s,'update',%s,%s,'2026-10-29 12:00:00+08') RETURNING id",
                (key+str(n),info['table_id'],rid,n+1,Jsonb({}),['pending','retry','conflict'][n],job)).fetchone()[0]))
            effects.append(str(conn.execute("INSERT INTO material_ops.effects(job_id,ordinal,source_key,method,args,kwargs,state,created_at) VALUES (%s,1,'primary','send_interactive_message',%s,%s,%s,'2026-10-29 12:00:00+08') RETURNING id",
                (job,Jsonb(['ou_test',{'header':{'title':{'content':'test'}}}]),Jsonb({'_outbox_ids':[outbox[-1]],'authorization':'hidden-auth'}),['pending','processing','done'][n])).fetchone()[0]))
        for table in ['reconcile_runs','import_runs']:
            runs.append((table,str(conn.execute(sql.SQL("INSERT INTO material_ops.{}(state,summary,started_at) VALUES ('running',%s,'2026-10-29 12:00:00+08') RETURNING id").format(sql.Identifier(table)),(Jsonb({'scope':key}),)).fetchone()[0])))
        @contextmanager
        def connection():yield conn
        monkeypatch.setattr(db,'connection',connection)
        yield conn,key,rid,number,jobs,outbox,effects,runs
        conn.execute('DELETE FROM material_ops.effects WHERE job_id::text=ANY(%s)',(jobs,))
        conn.execute('DELETE FROM material_ops.outbox WHERE job_id=ANY(%s)',(jobs,))
        conn.execute('DELETE FROM material_ops.jobs WHERE id::text=ANY(%s)',(jobs,))
        conn.execute("DELETE FROM material_ops.documents WHERE name=ANY(%s)",(['task-activity:'+job for job in jobs],))
        conn.execute(sql.SQL('DELETE FROM material_data.{} WHERE _record_key=%s').format(sql.Identifier(info['sql_table'])),(rid,))
        for table,identity in runs:conn.execute(sql.SQL('DELETE FROM material_ops.{} WHERE id=%s').format(sql.Identifier(table)),(identity,))


def test_readonly_list_search_filter_and_all_five_types(fixture):
    conn,key,rid,number,jobs,outbox,effects,runs=fixture
    with conn.transaction():
        conn.execute('SET TRANSACTION READ ONLY')
        all_items=monitor.list_tasks(conn,state='all',q=key)
        assert all_items['total']==9
        assert {row['kind'] for row in all_items['entries']}=={'jobs','outbox','effects'}
        active=monitor.list_tasks(conn,q=number)
        assert active['total']==5
        assert all(row['state'] in ['pending','retry','processing'] for row in active['entries'])
        assert monitor.list_tasks(conn,kind='outbox',state='problem',q=key)['total']==1
        for kind,table in [('reconcile','reconcile_runs'),('import','import_runs')]:
            found=monitor.list_tasks(conn,kind=kind,state='processing')
            assert runs[[t for t,_ in runs].index(table)][1] in {row['id'] for row in found['entries']}
        assert monitor.list_tasks(conn,state='all',q=key,since=date(2026,10,30))['total']==0
        assert monitor.list_tasks(conn,state='all',q=key,since=date(2026,10,29),until=date(2026,10,29))['total']==9


def test_cursor_pagination_has_no_omissions_or_duplicates_at_equal_timestamps(fixture):
    conn,key,*_=fixture;cursor='';seen=[]
    while True:
        page=monitor.list_tasks(conn,state='all',q=key,cursor=cursor,limit=2)
        seen.extend((row['kind'],row['id']) for row in page['entries'])
        cursor=page['next_cursor']
        if not cursor:break
    assert len(seen)==len(set(seen))==9
    with pytest.raises(ValueError):monitor.list_tasks(conn,cursor='not a cursor')
    with pytest.raises(ValueError):monitor.list_tasks(conn,kind='jobs;DROP TABLE x')
    assert monitor.list_tasks(conn,q="' OR 1=1 --")['total']==0
    with pytest.raises(ValueError):monitor.list_tasks(conn,since=date(2026,10,30),until=date(2026,10,29))


def test_details_include_related_states_dependencies_and_redaction(fixture):
    conn,key,rid,number,jobs,outbox,effects,runs=fixture
    item=monitor.detail(conn,'jobs',jobs[2])
    assert item['data']['payload']['draft']['secret']=='[已隐藏]'
    assert item['data']['payload']['draft']['submission_token']=='[已隐藏]'
    assert 'hidden-value' not in item['task']['last_error']
    assert len(item['related'])==3
    assert {row['state'] for row in item['related']}=={'failed','conflict','done'}
    effect=monitor.detail(conn,'effects',effects[0])
    assert effect['data']['dependencies'][0]['state']=='pending'
    assert effect['data']['kwargs']['authorization']=='[已隐藏]'
    with pytest.raises(LookupError):monitor.detail(conn,'jobs',str(uuid4()))


def test_next_poll_observes_completed_task_and_new_records(fixture):
    conn,key,rid,number,jobs,*_=fixture
    before=monitor.list_tasks(conn,kind='jobs',q=key)['entries'];assert len(before)==1
    conn.execute("UPDATE material_ops.jobs SET state='done',completed_at=now() WHERE id=%s",(jobs[0],))
    assert monitor.list_tasks(conn,kind='jobs',q=key)['total']==0
    assert monitor.detail(conn,'jobs',jobs[0])['task']['state']=='done'


def test_execution_marker_and_progress_visible_before_business_commit_and_cleared_after(fixture):
    conn,key,rid,number,jobs,*_=fixture
    with conn.transaction(), activity.track(conn,jobs[0]):
        conn.execute('UPDATE material_ops.jobs SET result=%s WHERE id=%s',(Jsonb({'invisible_uncommitted':True}),jobs[0]))
        activity.progress(jobs[0],{'stage':'核对库存'})
        with psycopg.connect(os.environ['PUDU_TEST_DATABASE_DSN'],autocommit=True) as observer:
            result=monitor.list_tasks(observer,kind='jobs',state='processing',q=key)
            assert len(result['entries'])==1 and result['entries'][0]['id']==jobs[0]
            assert monitor.detail(observer,'jobs',jobs[0])['data']['progress']=={'stage':'核对库存'}
            assert observer.execute('SELECT result FROM material_ops.jobs WHERE id=%s',(jobs[0],)).fetchone()[0]=={}
    assert conn.execute('SELECT 1 FROM material_ops.documents WHERE name=%s',('task-activity:'+jobs[0],)).fetchone() is None
    with pytest.raises(RuntimeError), activity.track(conn,jobs[0]):raise RuntimeError('test abort')
    assert conn.execute('SELECT 1 FROM material_ops.documents WHERE name=%s',('task-activity:'+jobs[0],)).fetchone() is None


def test_dead_or_reused_backend_markers_do_not_report_running(fixture):
    conn,key,rid,number,jobs,*_=fixture
    for pid in [2147483647,conn.execute('SELECT pg_backend_pid()').fetchone()[0]]:
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload',
            ('task-activity:'+jobs[0],Jsonb({'job_id':jobs[0],'pid':pid,'backend_start':'2000-01-01T00:00:00+00:00','started_at':datetime.now(timezone.utc).isoformat()})))
        assert monitor.list_tasks(conn,kind='jobs',state='processing',q=key)['total']==0


def test_api_admin_required_readonly_no_store_and_no_write_routes(fixture):
    conn,key,rid,number,jobs,*_=fixture
    test_api=FastAPI();allowed=False
    def require_admin():
        if not allowed:raise HTTPException(403,'Only administrators')
        return 'ou_test_admin'
    register(test_api,require_admin);client=TestClient(test_api)
    assert client.get('/api/admin/tasks').status_code==403
    assert client.get('/api/admin/tasks/jobs/'+jobs[0]).status_code==403
    allowed=True
    before=[conn.execute('SELECT count(*) FROM material_ops.'+table).fetchone()[0] for table in ['jobs','outbox','effects','documents']]
    response=client.get('/api/admin/tasks',params={'q':key})
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.json()['total']==5
    assert client.get('/api/admin/tasks/jobs/'+jobs[0]).status_code==200
    assert client.post('/api/admin/tasks',json={}).status_code==405
    assert client.get('/api/admin/tasks/jobs/bad-id').status_code==422
    after=[conn.execute('SELECT count(*) FROM material_ops.'+table).fetchone()[0] for table in ['jobs','outbox','effects','documents']]
    assert before==after
    web=importlib.import_module('request_web.api')
    for path in ['/api/admin/tasks','/api/admin/tasks/{kind}/{identity}']:
        route=next(route for route in web.api.routes if getattr(route,'path','')==path)
        assert any(dep.call is web.require_admin for dep in route.dependant.dependencies)
