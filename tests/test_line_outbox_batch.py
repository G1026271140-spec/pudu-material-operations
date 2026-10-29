from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
import json,os
import psycopg
import pytest
import app,backend_runtime as runtime
from material_store import line_outbox_batch as bulk,outbox_worker as worker,repository as repo,jobs
from material_store.client import DatabaseWriteClient
from test_approval_sync import graph,Remote,add_lines,confirm
from test_shipping_calendar import store


class BatchRemote(Remote):
    def __init__(self,old):
        self.__dict__.update(deepcopy(old.__dict__))
        self.calls=Counter();self.bodies=[];self.missing=set();self.partial_once=None;self.timeout_once=False;self.omit_response=False
    def list_records(self,tid):
        self.calls['list']+=1;return super().list_records(tid)
    def batch_get_records(self,tid,ids):
        self.calls['batch_get']+=1
        return [deepcopy(self.rows[tid][key]) for key in reversed(ids) if key not in self.missing and key in self.rows[tid]]
    def batch_create_records(self,tid,records):
        self.calls['batch_create']+=1;self.bodies.append(('create',len(records)))
        created=super().batch_create_records(tid,records)
        if self.timeout_once:self.timeout_once=False;raise TimeoutError('unknown create outcome')
        return [] if self.omit_response else list(reversed(created))
    def batch_update_records(self,tid,records):
        self.calls['batch_update']+=1;self.bodies.append(('update',len(records)))
        chosen=records if self.partial_once is None else records[:self.partial_once]
        self.partial_once=None
        for row in chosen:super().update_record(tid,row['record_id'],row['fields'])
        if self.timeout_once:self.timeout_once=False;raise TimeoutError('unknown update outcome')
        return [] if self.omit_response else [deepcopy(self.rows[tid][row['record_id']]) for row in reversed(chosen)]


@pytest.fixture
def batched(graph,monkeypatch):
    conn,info,lines,key,number,old=graph
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(bulk,'connection',same)
    runtime.request_state['_job_id']=None
    conn.execute("SELECT set_config('pudu.job_id','',true)")
    return conn,info,lines,key,number,BatchRemote(old)


def edit_lines(data,count=10,lane='ordinary',value=4):
    conn,info,lines,key,number,source=data
    runtime.request_state['_write_lane']=lane
    ids=list(source.rows[lines['table_id']])[:count]
    for rid in ids:DatabaseWriteClient(conn).update_record(lines['table_id'],rid,{'申请数量':value})
    return ids


def retry_now(conn):
    conn.execute("UPDATE material_ops.outbox SET available_at=now() WHERE state='retry'")


def test_ten_updates_are_one_batch_read_and_one_write_with_each_result_audited(batched):
    conn,info,lines,key,number,source=batched;ids=edit_lines(batched)
    result=worker.run_once('ordinary',source)
    assert result['state']=='done' and result['records']==result['done']==10
    assert source.calls=={'batch_get':1,'batch_update':1} and source.reads==0
    assert all(source.rows[lines['table_id']][rid]['fields']['申请数量']==4 for rid in ids)
    states=conn.execute('SELECT state FROM material_ops.outbox WHERE record_key=ANY(%s)',(ids,)).fetchall()
    assert all(s[0]=='done' for s in states)
    assert conn.execute("SELECT count(*) FROM material_ops.audit WHERE after_value->>'batch_id'=%s",(result['batch_id'],)).fetchone()[0]==10


def test_creates_match_by_business_identity_despite_reordered_response_and_unknown_timeout(batched):
    conn,info,lines,key,number,source=batched
    created=add_lines(batched,7,lane='ordinary');source.timeout_once=True
    assert worker.run_once('ordinary',source)['state']=='retry'
    assert source.calls=={'list':1,'batch_create':1}
    retry_now(conn)
    result=worker.run_once('ordinary',source)
    assert result['done']==7 and source.calls=={'list':2,'batch_create':1}
    for item in created:
        stored=repo.raw_record(conn,lines,item['record_id'])
        assert source.rows[lines['table_id']][stored['remote_id']]['fields']['明细编号']==item['fields']['明细编号']
    assert len(source.rows[lines['table_id']])==17


@pytest.mark.parametrize('omitted',[False,True])
def test_normal_create_batch_posts_once_and_never_assumes_response_position(batched,omitted):
    conn,info,lines,key,number,source=batched;created=add_lines(batched,7,lane='ordinary');source.omit_response=omitted
    assert worker.run_once('ordinary',source)['done']==7
    assert source.calls=={'list':2 if omitted else 1,'batch_create':1}
    for item in created:
        remote=repo.raw_record(conn,lines,item['record_id'])['remote_id']
        assert source.rows[lines['table_id']][remote]['fields']['明细编号']==item['fields']['明细编号']


def test_approval_still_waits_for_every_create_and_update(batched):
    conn,info,lines,key,number,source=batched
    add_lines(batched,7,lane='admin');edit_lines(batched,1,lane='admin')
    main=confirm(batched)
    with pytest.raises(worker.DependencyPending):worker.publish(main,source)
    worker.fail(main,worker.DependencyPending('wait'))
    assert worker.run_once('admin',source)['done']==7
    assert not source.approvals
    # Keep the trigger backoff while the remaining update is published.
    conn.execute("UPDATE material_ops.outbox SET available_at=now()+interval '1 minute' WHERE id=%s",(main['id'],))
    assert worker.run_once('admin',source)['done']==1 and not source.approvals
    conn.execute('UPDATE material_ops.outbox SET available_at=now() WHERE id=%s',(main['id'],))
    assert worker.run_once('admin',source)['state']=='done'
    assert len(source.approvals)==1 and len(source.approvals[0])==17


def test_manual_conflict_isolated_without_losing_other_nine_updates(batched):
    conn,info,lines,key,number,source=batched;ids=edit_lines(batched)
    source.rows[lines['table_id']][ids[0]]['fields']['申请数量']=99
    result=worker.run_once('ordinary',source)
    assert result['state']=='conflict' and result['done']==9 and result['conflict']==1
    assert source.bodies==[('update',9)] and source.rows[lines['table_id']][ids[0]]['fields']['申请数量']==99


@pytest.mark.parametrize('timeout',[False,True])
def test_partial_or_unknown_update_outcome_retries_only_unconfirmed_rows(batched,timeout):
    conn,info,lines,key,number,source=batched;edit_lines(batched)
    source.partial_once=2;source.timeout_once=timeout
    first=worker.run_once('ordinary',source)
    assert first['state']=='retry' and first['done']==(0 if timeout else 2)
    retry_now(conn);result=worker.run_once('ordinary',source)
    assert result['state']=='done' and source.bodies==[('update',10),('update',8)]
    assert all(r['fields']['申请数量']==4 for r in source.rows[lines['table_id']].values())


def test_incomplete_success_response_requires_one_batched_readback(batched):
    conn,info,lines,key,number,source=batched;edit_lines(batched);source.omit_response=True
    assert worker.run_once('ordinary',source)['done']==10
    assert source.calls=={'batch_get':2,'batch_update':1}


def test_missing_remote_record_never_marked_done_but_other_records_progress(batched):
    conn,info,lines,key,number,source=batched;ids=edit_lines(batched);source.missing.add(ids[0])
    result=worker.run_once('ordinary',source)
    assert result['done']==9 and result['retry']==1 and source.bodies==[('update',9)]
    assert conn.execute('SELECT state FROM material_ops.outbox WHERE record_key=%s',(ids[0],)).fetchone()[0]=='retry'


def test_create_identity_content_conflict_never_adopts_different_source_line(batched):
    conn,info,lines,key,number,source=batched;created=add_lines(batched,3,lane='ordinary')
    fields=deepcopy(created[0]['fields']);fields['申请数量']=99
    source.rows[lines['table_id']]['rec_manual']={'record_id':'rec_manual','fields':fields}
    result=worker.run_once('ordinary',source)
    assert result['done']==2 and result['conflict']==1 and source.bodies==[('create',2)]
    assert repo.raw_record(conn,lines,created[0]['record_id'])['remote_id'] is None
    assert source.rows[lines['table_id']]['rec_manual']['fields']['申请数量']==99


def test_same_record_versions_keep_order_and_latest_local_value(batched):
    conn,info,lines,key,number,source=batched;ids=edit_lines(batched,1,value=2)
    DatabaseWriteClient(conn).update_record(lines['table_id'],ids[0],{'申请数量':3})
    assert worker.run_once('ordinary',source)['done']==1
    row=repo.raw_record(conn,lines,ids[0])
    assert source.rows[lines['table_id']][ids[0]]['fields']['申请数量']==2
    assert repo.feishu_record(lines,row)['fields']['申请数量']==3 and row['sync_state']=='pending'
    assert worker.run_once('ordinary',source)['done']==1
    assert repo.raw_record(conn,lines,ids[0])['sync_state']=='synced' and source.rows[lines['table_id']][ids[0]]['fields']['申请数量']==3


def test_record_lock_contention_skips_only_the_locked_record(batched):
    conn,info,lines,key,number,source=batched;ids=edit_lines(batched)
    with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as other:
        other.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',('outbox-record:'+lines['table_id']+':'+ids[-1],))
        result=worker.run_once('ordinary',source)
        assert result['done']==9 and result['retry']==1
        state,attempts=conn.execute('SELECT state,attempts FROM material_ops.outbox WHERE record_key=%s',(ids[-1],)).fetchone()
        assert state=='retry' and attempts==0
    retry_now(conn);assert worker.run_once('ordinary',source)['done']==1


def test_lane_and_job_boundaries_are_preserved(batched):
    conn,info,lines,key,number,source=batched;ids=list(source.rows[lines['table_id']])
    for i,lane in enumerate(['ordinary','admin','ordinary']):
        runtime.request_state['_write_lane']=lane
        if lane=='ordinary':
            task,_=jobs.enqueue('batch-test',uuid4().hex,{'request_id':key},conn=conn)
            conn.execute("SELECT set_config('pudu.job_id',%s,true)",(task.task_id,))
        else:conn.execute("SELECT set_config('pudu.job_id','',true)")
        DatabaseWriteClient(conn).update_record(lines['table_id'],ids[i],{'申请数量':4})
    assert worker.run_once('ordinary',source)['records']==1
    assert worker.run_once('ordinary',source)['records']==1
    assert conn.execute("SELECT state FROM material_ops.outbox WHERE lane='admin' AND record_key=%s",(ids[1],)).fetchone()[0]=='pending'
    assert worker.run_once('admin',source)['records']==1


def test_batch_is_bounded_to_fifty_and_preserves_every_id(batched):
    conn,info,lines,key,number,source=batched;created=add_lines(batched,55,lane='ordinary')
    assert worker.run_once('ordinary',source)['done']==50
    assert worker.run_once('ordinary',source)['done']==5
    assert source.bodies==[('create',50),('create',5)]
    assert all(repo.raw_record(conn,lines,r['record_id'])['remote_id'] for r in created)


def test_unscoped_jobs_never_mix_lines_from_different_requests(batched):
    conn,info,lines,key,number,source=batched
    other='rec_other_'+uuid4().hex;line='rec_other_line_'+uuid4().hex
    head={'record_id':other,'fields':{'申请单号':'OTHER','申请类型':'普通物料申请','审批状态':'待审批','申请明细':[line]}}
    child={'record_id':line,'fields':{'明细编号':'OTHER-01','所属申请单':[other],'申请数量':1}}
    repo.insert_source_records(conn,info,[head]);repo.insert_source_records(conn,lines,[child])
    source.rows[info['table_id']][other]=deepcopy(head);source.rows[lines['table_id']][line]=deepcopy(child)
    edit_lines(batched,1)
    DatabaseWriteClient(conn).update_record(lines['table_id'],line,{'申请数量':5})
    assert worker.run_once('ordinary',source)['records']==1
    assert source.rows[lines['table_id']][line]['fields']['申请数量']==1
    assert worker.run_once('ordinary',source)['records']==1
    assert source.rows[lines['table_id']][line]['fields']['申请数量']==5


def test_stale_claim_token_never_writes_source_or_completes_newer_lease(batched):
    conn,info,lines,key,number,source=batched;edit_lines(batched,1)
    task=worker.claim('ordinary','stale-worker');new_token=uuid4()
    conn.execute('UPDATE material_ops.outbox SET claim_token=%s WHERE id=%s',(new_token,task['id']))
    with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as guard:
        guard.execute("SELECT pg_advisory_lock_shared(hashtextextended('pudu-reconciliation',0))")
        guard.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',('outbox-record:'+task['table_id']+':'+task['record_key'],))
        assert bulk.run_claimed(task,'ordinary',source,'stale-worker',guard)['state']=='retry'
    assert not source.calls
    assert conn.execute('SELECT state,claim_token FROM material_ops.outbox WHERE id=%s',(task['id'],)).fetchone()==('processing',new_token)


def test_batch_read_native_protocol_uses_ids_and_open_identity(monkeypatch):
    from feishu_bitable import FeishuBitableClient,FeishuBitableConfig
    client=FeishuBitableClient(FeishuBitableConfig(app_id='test',app_secret='test',app_token='test'))
    calls=[]
    def request(method,path,**kwargs):calls.append((method,path,kwargs));return {'data':{'records':[{'record_id':'rec_ok'}],'absent_record_ids':['rec_missing']}}
    monkeypatch.setattr(client,'_request',request)
    assert client.batch_get_records('tblTest',['rec_ok','rec_missing'])==[{'record_id':'rec_ok'}]
    assert calls[0][0]=='POST' and calls[0][1].endswith('/records/batch_get')
    assert calls[0][2]['payload']=={'record_ids':['rec_ok','rec_missing'],'user_id_type':'open_id','automatic_fields':False}
    for ids in [[],['a','a'],['a']*101]:
        with pytest.raises(ValueError):client.batch_get_records('tblTest',ids)
