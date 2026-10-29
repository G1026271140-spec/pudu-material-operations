from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from uuid import uuid4
from unittest.mock import Mock
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

import app
import backend_runtime as runtime
import order_scheduling as rules
from material_store import repository as repo, order_recovery as recovery, outbox_worker as worker, effects, jobs
from material_store.client import DatabaseWriteClient
from test_shipping_calendar import store
from test_order_scheduling import svc,generation_payload


def test_batch_numbers_use_the_entire_generation_key_and_service_is_idempotent(svc):
    keys=['allocation:request-A:0','allocation:request-B:0','allocation:request-A:1']
    values=[rules.batch_number(key,day=date(2026,10,29)) for key in keys]
    assert len(set(values))==3
    assert values[0]==rules.batch_number(keys[0],day=date(2026,10,29))
    with pytest.raises(ValueError):rules.batch_number('')
    payload=generation_payload(svc);payload['generation_key']=keys[0]
    svc.record_schedule(payload,{},lambda value:None)
    assert svc.app.data[rules.BATCH_TABLE][0]['fields']['下单批次号']==rules.batch_number(keys[0])
    svc.record_schedule(payload,{},lambda value:None)
    assert len(svc.app.data[rules.BATCH_TABLE])==1


def test_source_batch_identity_uses_generation_key_despite_duplicate_display_numbers():
    fields={'下单批次号':'PO-20261029-ALLOCATION','生成幂等键':'allocation:right:0','批次状态':'已生成'}
    info={'source':'primary','name':rules.BATCH_TABLE,'table_id':'batch','fields':[{'field_id':name,'field_name':name,'type':1} for name in fields]}
    other={'record_id':'rec_other','fields':{**fields,'生成幂等键':'allocation:other:0'}}
    correct={'record_id':'rec_correct','fields':deepcopy(fields)}
    remote=Mock();remote.list_records.return_value=[other,correct]
    assert worker._find_remote_create(remote,info,fields)['record_id']=='rec_correct'
    remote.list_records.return_value=[other]
    assert worker._find_remote_create(remote,info,fields) is None
    remote.list_records.return_value=[other,{**correct,'fields':{**fields,'批次状态':'已作废'}}]
    with pytest.raises(worker.SourceConflict):worker._find_remote_create(remote,info,fields)
    remote.list_records.return_value=[correct,correct]
    with pytest.raises(worker.SourceConflict):worker._find_remote_create(remote,info,fields)


@pytest.fixture
def collision(store,monkeypatch):
    conn=store
    @contextmanager
    def same():yield conn
    for module in [worker,effects]:monkeypatch.setattr(module,'connection',same)
    # Isolated transaction only: pre-existing test tasks cannot affect selection.
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state NOT IN ('done','cancelled')")
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','retry','processing')")
    task,_=jobs.enqueue('隔离下单恢复验证','collision-'+uuid4().hex,{},conn=conn)
    conn.execute("SELECT set_config('pudu.job_id',%s,true)",(task.task_id,))
    runtime.request_state.update(_write_conn=conn,_job_id=task.task_id,_write_lane='admin',_effect_ordinal=0)
    client=DatabaseWriteClient(conn);batch=repo.named_table(conn,rules.BATCH_TABLE);detail=repo.named_table(conn,rules.DETAIL_TABLE)
    generation='allocation:'+uuid4().hex+':0'
    fields={'下单批次号':'PO-20261029-ALLOCATION','生成幂等键':generation,'批次状态':'已生成','启用自动补库':False}
    parent=client.batch_create_records(batch['table_id'],[fields])[0]['record_id']
    children=client.batch_create_records(detail['table_id'],[{'批次明细编号':'order:'+generation+':'+str(n),'所属下单批次':[parent],'下单数量':amount} for n,amount in enumerate([10,20])])
    oid=str(conn.execute("SELECT id FROM material_ops.outbox WHERE record_key=%s",(parent,)).fetchone()[0])
    conn.execute("UPDATE material_ops.outbox SET state='conflict',last_error=%s WHERE id=%s",('SourceConflict: 飞书已有该下单编号的不同内容，等待核对。',oid))
    conn.execute(sql.SQL("UPDATE material_data.{} SET _sync_state='conflict' WHERE _record_key=%s").format(sql.Identifier(batch['sql_table'])),(parent,))
    dependencies=[str(row[0]) for row in conn.execute('SELECT id FROM material_ops.outbox WHERE job_id=%s',(task.task_id,))]
    for identity in ['om_original_one','om_original_two']:
        effects.defer('primary','update_interactive_message',[identity,{'schema':'2.0','header':{'title':{'content':'库存已核实'}}}],{'_outbox_ids':dependencies,'_inventory_request':'isolated_request'})
    conn.execute("UPDATE material_ops.jobs SET state='done' WHERE id=%s",(task.task_id,))
    class Source:
        def __init__(self):
            self.rows={batch['table_id']:[{'record_id':'rec_unrelated','fields':{**fields,'生成幂等键':'allocation:unrelated:0'}}],detail['table_id']:[]}
            self.created=[];self.updated_cards=[];self._request=Mock(side_effect=AssertionError('No replacement message'))
        def list_records(self,table):return deepcopy(self.rows[table])
        def batch_create_records(self,table,values):
            result=[{'record_id':'rec_created_'+str(len(self.created)+n),'fields':deepcopy(f)} for n,f in enumerate(values)]
            self.created.extend(result);self.rows[table].extend(result);return deepcopy(result)
        def update_interactive_message(self,identity,card):self.updated_cards.append(identity)
    remote=Source()
    return conn,batch,detail,parent,children,oid,dependencies,remote


def test_audited_collision_repair_retains_quantity_ids_and_unblocks_original_cards(collision):
    conn,batch,detail,parent,children,oid,dependencies,remote=collision
    assert effects.run_once({'primary':remote}) is None
    plans=recovery.plan(conn,remote.list_records(batch['table_id']))
    assert len(plans)==1 and plans[0]['outbox_id']==oid
    assert recovery.apply(conn,plans)==1
    # The fixture keeps an outer rollback transaction, freezing now(). In
    # production the repair commits before the next Worker claim starts.
    conn.execute('UPDATE material_ops.outbox SET available_at=now() WHERE id=%s',(oid,))
    assert conn.execute('SELECT id::text FROM material_ops.outbox WHERE record_key=%s',(parent,)).fetchone()[0]==oid
    assert [repo.feishu_record(detail,repo.raw_record(conn,detail,c['record_id']))['fields']['下单数量'] for c in children]==[10,20]
    assert effects.run_once({'primary':remote}) is None
    for _ in range(6):
        task=worker.claim('admin','isolated-recovery')
        if not task:break
        worker.finish(task,worker.publish(task,remote))
    assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE id::text=ANY(%s) AND state<>\'done\'',(dependencies,)).fetchone()[0]==0
    for _ in range(2):assert effects.run_once({'primary':remote})['state']=='done'
    assert remote.updated_cards==['om_original_one','om_original_two']
    remote._request.assert_not_called()
    assert len(remote.rows[batch['table_id']])==2
    assert remote.rows[batch['table_id']][0]['record_id']=='rec_unrelated'
    new_id=repo.raw_record(conn,batch,parent)['remote_id']
    assert all(r['fields']['所属下单批次']==[new_id] for r in remote.rows[detail['table_id']])
    assert sum(r['fields']['下单数量'] for r in remote.rows[detail['table_id']])==30
    assert conn.execute("SELECT count(*) FROM material_ops.audit WHERE record_key=%s AND actor_open_id='worker:order-batch-recovery'",(parent,)).fetchone()[0]==1
    assert recovery.plan(conn,remote.list_records(batch['table_id']))==[]


def test_repair_refuses_source_with_same_generation_key_or_stale_local_version(collision):
    conn,batch,detail,parent,children,oid,dependencies,remote=collision
    fields=repo.feishu_record(batch,repo.raw_record(conn,batch,parent))['fields']
    with pytest.raises(ValueError,match='相同生成幂等键'):recovery.plan(conn,[{'record_id':'rec_already_created','fields':fields}])
    plans=recovery.plan(conn,remote.list_records(batch['table_id']))
    conn.execute(sql.SQL('UPDATE material_data.{} SET _local_version=_local_version+1 WHERE _record_key=%s').format(sql.Identifier(batch['sql_table'])),(parent,))
    with pytest.raises(ValueError,match='已变化'):recovery.apply(conn,plans)
    assert conn.execute('SELECT state FROM material_ops.outbox WHERE id=%s',(oid,)).fetchone()[0]=='conflict'


def test_retry_after_remote_create_recovers_same_batch_without_duplicate(collision):
    conn,batch,detail,parent,children,oid,dependencies,remote=collision
    recovery.apply(conn,recovery.plan(conn,remote.list_records(batch['table_id'])))
    conn.execute('UPDATE material_ops.outbox SET available_at=now() WHERE id=%s',(oid,))
    task=worker.claim('admin','isolated-recovery')
    assert task['record_key']==parent
    first=worker.publish(task,remote)  # Simulate process loss after remote success.
    second=worker.publish(task,remote)
    assert first==second and len(remote.rows[batch['table_id']])==2
    worker.finish(task,second)
