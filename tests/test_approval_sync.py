"""Real PG regression: a native approval must see the whole allocation snapshot."""
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
import pytest
import app
import backend_runtime as runtime
from material_store import repository as repo, outbox_worker as worker
from material_store.client import DatabaseWriteClient
from test_shipping_calendar import store


class Remote:
    def __init__(self, request_info, line_info, request, lines):
        self.request_info=request_info;self.line_info=line_info
        self.rows={request_info['table_id']:{request['record_id']:deepcopy(request)},
                   line_info['table_id']:{r['record_id']:deepcopy(r) for r in lines}}
        self.approvals=[];self.updates=[];self.reads=0
    def get_record(self, tid, key):
        self.reads+=1;return deepcopy(self.rows[tid][key])
    def list_records(self,tid):return list(deepcopy(self.rows[tid]).values())
    def batch_create_records(self,tid,records):
        rows=[]
        for fields in records:
            key='rec_remote_'+uuid4().hex;row={'record_id':key,'fields':deepcopy(fields)}
            self.rows[tid][key]=row;rows.append(deepcopy(row))
            if tid==self.line_info['table_id']:
                for parent in repo.link_ids(fields.get('所属申请单')):
                    self.rows[self.request_info['table_id']][parent]['fields'].setdefault('申请明细',[]).append(key)
        return rows
    def update_record(self,tid,key,fields):
        self.updates.append((tid,key,deepcopy(fields)));self.rows[tid][key]['fields'].update(deepcopy(fields))
        if tid==self.request_info['table_id'] and fields.get('库存审查状态')=='已核实库存':
            self.approvals.append(deepcopy(self.rows[tid][key]['fields'].get('申请明细',[])))


@pytest.fixture
def graph(store,monkeypatch):
    conn=store
    @contextmanager
    def same_connection():yield conn
    monkeypatch.setattr(worker,'connection',same_connection)
    # The fixture is an isolated rollback transaction, never a production DSN.
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state NOT IN ('done','cancelled')")
    runtime.request_state.update({'_write_conn':conn,'_write_lane':'admin','_write_actor':'ou_test'})
    request_info=repo.named_table(conn,app.REQUEST_TABLE_NAME);line_info=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)
    key='rec_request_'+uuid4().hex;number='SYNC-'+uuid4().hex
    lines=[{'record_id':'rec_existing_'+uuid4().hex,'fields':{'明细编号':number+f'-{i:02d}',
            '所属申请单':[key],'申请数量':1,'审批通过数量':1,'明细状态':'待审批'}} for i in range(1,11)]
    parent={'record_id':key,'fields':{'申请单号':number,'申请类型':'普通物料申请','审批状态':'待审批',
            '库存审查状态':'待核实库存','申请明细':[r['record_id'] for r in lines]}}
    repo.insert_source_records(conn,request_info,[parent]);repo.insert_source_records(conn,line_info,lines)
    return conn,request_info,line_info,key,number,Remote(request_info,line_info,parent,lines)


def add_lines(graph,count=7,lane='admin'):
    conn,info,lines,key,number,remote=graph
    runtime.request_state['_write_lane']=lane
    created=DatabaseWriteClient(conn).batch_create_records(lines['table_id'],[
        {'明细编号':number+f'-{i:02d}','所属申请单':[key],'申请数量':2,'审批通过数量':2,'明细状态':'待审批'}
        for i in range(11,11+count)])
    runtime.request_state['_write_lane']='admin'
    return created


def confirm(graph):
    conn,info,lines,key,number,remote=graph
    DatabaseWriteClient(conn).update_record(info['table_id'],key,{'库存审查状态':'已核实库存'})
    task=worker.claim('admin','test-approval-order')
    assert task['table_id']==info['table_id']
    return task


def test_confirmation_is_published_after_all_seventeen_lines(graph):
    conn,info,lines,key,number,remote=graph
    add_lines(graph)
    existing=next(iter(remote.rows[lines['table_id']]))
    DatabaseWriteClient(conn).update_record(lines['table_id'],existing,{'申请数量':3})
    main=confirm(graph)
    with pytest.raises(worker.DependencyPending):worker.publish(main,remote)
    assert remote.reads==0 and not remote.approvals
    worker.fail(main,worker.DependencyPending('wait'))
    for _ in range(8):
        task=worker.claim('admin','test-approval-order')
        assert task['table_id']==lines['table_id']
        worker.finish(task,worker.publish(task,remote))
    conn.execute('UPDATE material_ops.outbox SET available_at=now() WHERE id=%s',(main['id'],))
    task=worker.claim('admin','test-approval-order')
    assert task['id']==main['id'] and task['attempts']==1
    worker.finish(task,worker.publish(task,remote))
    assert len(remote.approvals)==1 and len(remote.approvals[0])==17
    assert all(row['fields']['明细编号'].startswith(number) for row in remote.rows[lines['table_id']].values())


@pytest.mark.parametrize('state',['retry','processing','conflict'])
def test_other_lane_line_dependencies_block_confirmation(graph,state):
    conn,info,lines,key,number,remote=graph
    add_lines(graph,1,lane='ordinary')
    conn.execute('UPDATE material_ops.outbox SET state=%s WHERE table_id=%s AND state=%s',(state,lines['table_id'],'pending'))
    main=confirm(graph)
    error=worker.SourceConflict if state=='conflict' else worker.DependencyPending
    with pytest.raises(error):worker.publish(main,remote)
    assert not remote.updates and not remote.reads


def test_waits_for_feishu_reciprocal_links_even_after_line_write_is_done(graph):
    conn,info,lines,key,number,remote=graph
    created=add_lines(graph,1)[0]
    main=confirm(graph)
    # Marking the create as done without a visible remote backlink reproduces
    # the source's asynchronous reciprocal-link propagation.
    from psycopg import sql
    conn.execute(sql.SQL('UPDATE material_data.{} SET _remote_id=%s WHERE _record_key=%s').format(sql.Identifier(lines['sql_table'])),('rec_delayed',created['record_id']))
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE record_key=%s",(created['record_id'],))
    with pytest.raises(worker.DependencyPending,match='回链'):worker.publish(main,remote)
    assert not remote.updates
    remote.rows[info['table_id']][key]['fields']['申请明细'].append('rec_delayed')
    worker.publish(main,remote)
    assert len(remote.approvals)==1 and len(remote.approvals[0])==11


def test_non_trigger_parent_edits_are_not_blocked(graph):
    conn,info,lines,key,number,remote=graph
    add_lines(graph,1)
    DatabaseWriteClient(conn).update_record(info['table_id'],key,{'发货单号及文字信息':'unchanged workflow'})
    task=worker.claim('admin','test-other-edit');worker.publish(task,remote)
    assert remote.updates[-1][2]=={'发货单号及文字信息':'unchanged workflow'}
    assert not remote.approvals


def test_unrelated_request_line_does_not_block_another_confirmation(graph):
    conn,info,lines,key,number,remote=graph
    add_lines(graph,1)
    other='rec_other_'+uuid4().hex
    row={'record_id':other,'fields':{'申请单号':'OTHER-'+uuid4().hex,'申请类型':'普通物料申请',
         '审批状态':'待审批','库存审查状态':'待核实库存','申请明细':[]}}
    repo.insert_source_records(conn,info,[row]);remote.rows[info['table_id']][other]=deepcopy(row)
    DatabaseWriteClient(conn).update_record(info['table_id'],other,{'库存审查状态':'已核实库存'})
    task=worker.claim('admin','unrelated-request')
    assert task['record_key']==other
    worker.publish(task,remote)
    assert remote.approvals==[[]]


def test_same_job_deleted_lines_must_finish_before_confirmation(graph):
    conn,info,lines,key,number,remote=graph
    job='job-'+uuid4().hex
    conn.execute("SELECT set_config('pudu.job_id',%s,true)",(job,))
    old=next(iter(remote.rows[lines['table_id']]))
    DatabaseWriteClient(conn).delete_record(lines['table_id'],old)
    main=confirm(graph)
    assert main['job_id']==job
    with pytest.raises(worker.DependencyPending):worker.publish(main,remote)
    assert not remote.updates


def test_early_confirmation_is_not_folded_into_unpublished_create(graph):
    conn,info,lines,key,number,remote=graph;client=DatabaseWriteClient(conn)
    parent=client.batch_create_records(info['table_id'],[{'申请单号':'NEW-'+uuid4().hex,'申请类型':'普通物料申请','库存审查状态':'待核实库存'}])[0]
    client.update_record(info['table_id'],parent['record_id'],{'库存审查状态':'已核实库存'})
    client.update_record(info['table_id'],parent['record_id'],{'备注':'later edit must remain after confirmation'})
    queued=conn.execute('SELECT operation,local_version,patch FROM material_ops.outbox WHERE table_id=%s AND record_key=%s ORDER BY local_version',(info['table_id'],parent['record_id'])).fetchall()
    review=next(f['field_id'] for f in info['fields'] if f['field_name']=='库存审查状态')
    assert [(r[0],r[1]) for r in queued]==[('create',1),('update',2),('update',3)]
    assert queued[0][2][review]=='待核实库存' and queued[1][2][review]=='已核实库存'
    assert review not in queued[2][2]


def test_dependency_waits_do_not_consume_failure_backoff(graph):
    conn,info,lines,key,number,remote=graph;add_lines(graph,1);task=confirm(graph)
    for _ in range(4):
        worker.fail(task,worker.DependencyPending('wait'))
        attempts,soon=conn.execute("SELECT attempts,available_at<=now()+interval '2 seconds' FROM material_ops.outbox WHERE id=%s",(task['id'],)).fetchone()
        assert attempts==0 and soon
        conn.execute('UPDATE material_ops.outbox SET available_at=now() WHERE id=%s',(task['id'],))
        task=worker.claim('admin','test-wait');assert task['attempts']==1
