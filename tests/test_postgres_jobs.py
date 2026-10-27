import os
from uuid import uuid4
from unittest.mock import Mock
import pytest
psycopg=pytest.importorskip('psycopg')
from psycopg import sql
from material_store import jobs,repository as repo,db,effects
from material_store.client import DatabaseWriteClient
import backend_runtime as runtime
DSN=os.environ.get('PUDU_TEST_DATABASE_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='Requires isolated PostgreSQL test database')

@pytest.fixture
def conn(monkeypatch):
 monkeypatch.setenv('PUDU_DATABASE_DSN',DSN)
 monkeypatch.setenv('PUDU_DATA_SOURCE','postgresql')
 for name in ('FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_BITABLE_APP_TOKEN'):monkeypatch.setenv(name,'test')
 db.pool.cache_clear()
 with psycopg.connect(DSN,autocommit=True) as c:
  assert c.execute('SELECT current_database()').fetchone()[0]=='pudu_materials_test'
  yield c
 db.pool().close();db.pool.cache_clear()

def test_idempotency_refuses_changed_payload_and_rolls_back(conn):
 key='test-'+uuid4().hex
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction():
   task,created=jobs.enqueue('测试任务',key,{'draft':{'amount':1}},conn=conn)
   assert created
   again,created=jobs.enqueue('测试任务',key,{'draft':{'amount':1}},conn=conn)
   assert not created and task.task_id==again.task_id
   with pytest.raises(ValueError):jobs.enqueue('测试任务',key,{'draft':{'amount':2}},conn=conn)
   raise RuntimeError('rollback')
 assert conn.execute('SELECT count(*) FROM material_ops.jobs WHERE idempotency_key=%s',(key,)).fetchone()[0]==0

def test_business_writes_effects_and_job_result_are_one_transaction(conn,monkeypatch):
 def dispatch(task,checkpoint):
  c=runtime.request_state['_write_conn'];client=DatabaseWriteClient(c)
  info=repo.named_table(c,'物料语种')
  row=client.batch_create_records(info['table_id'],[{'语言种类':'PG事务测试-'+uuid4().hex}])[0]
  message=client.send_text_message('ou_test','notification')
  client.update_record(info['table_id'],row['record_id'],{'语言种类':message})
  return {'record':row['record_id'],'message':message}
 monkeypatch.setattr(jobs,'dispatch',dispatch)
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   task,_=jobs.enqueue('测试任务','atomic-'+uuid4().hex,{},conn=conn)
   row=conn.execute('SELECT id,task_type,idempotency_key,payload,state,result FROM material_ops.jobs WHERE id=%s',(task.task_id,)).fetchone()
   result=jobs._run(conn,row)
   assert result['message'].startswith(effects.PREFIX)
   assert conn.execute('SELECT count(*) FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchone()[0]==1
   assert conn.execute('SELECT count(*) FROM material_ops.outbox WHERE job_id=%s',(task.task_id,)).fetchone()[0]==1
   assert conn.execute('SELECT state FROM material_ops.jobs WHERE id=%s',(task.task_id,)).fetchone()[0]=='done'
   raise RuntimeError('rollback')

def test_deleted_remote_record_is_hidden_and_outbox_can_still_read_it(conn):
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   runtime.request_state['_write_conn']=conn
   info=repo.named_table(conn,'物料语种');key='delete-'+uuid4().hex
   repo.insert_source_records(conn,info,[{'record_id':key,'fields':{'语言种类':'删除测试'}}])
   DatabaseWriteClient(conn).delete_record(info['table_id'],key)
   with pytest.raises(ValueError):repo.raw_record(conn,info,key)
   assert repo.raw_record(conn,info,key,include_deleted=True)['remote_id']==key
   assert conn.execute("SELECT operation FROM material_ops.outbox WHERE record_key=%s",(key,)).fetchone()==('delete',)
   raise RuntimeError('rollback')

def test_adapter_forbids_network_inside_transaction(conn):
 with runtime.request_scope():
  client=DatabaseWriteClient(conn)
  with pytest.raises(RuntimeError,match='禁止'):client._request('GET','/im/v1/messages')
  with pytest.raises(RuntimeError,match='不允许'):client.upload_media('a',b'b','text/plain')

def test_outbox_waits_for_notification_alias_and_alias_replace_preserves_other_fields(conn):
 from material_store.outbox_worker import DependencyPending
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   task,_=jobs.enqueue('测试任务','alias-'+uuid4().hex,{},conn=conn)
   runtime.request_state.update({'_write_conn':conn,'_job_id':task.task_id})
   token=DatabaseWriteClient(conn).send_text_message('ou_test','text')
   with pytest.raises(DependencyPending):effects.resolve(conn,{'message':token})
   info=repo.named_table(conn,'物料语种')
   created=DatabaseWriteClient(conn).batch_create_records(info['table_id'],[{'语言种类':token}])[0]
   effects._replace_alias(conn,token,'om_actual')
   assert repo.feishu_record(info,repo.raw_record(conn,info,created['record_id']))['fields']['语言种类']=='om_actual'
   assert conn.execute('SELECT patch FROM material_ops.outbox WHERE record_key=%s',(created['record_id'],)).fetchone()[0][next(f['field_id'] for f in info['fields'] if f['field_name']=='语言种类')]=='om_actual'
   raise RuntimeError('rollback')


def test_delete_publisher_refuses_manual_source_changes(conn,monkeypatch):
 from contextlib import contextmanager
 from material_store import outbox_worker
 @contextmanager
 def same_connection():yield conn
 monkeypatch.setattr(outbox_worker,'connection',same_connection)
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   info=repo.named_table(conn,'物料语种');key='remote-delete-'+uuid4().hex
   repo.insert_source_records(conn,info,[{'record_id':key,'fields':{'语言种类':'原始'}}])
   DatabaseWriteClient(conn).delete_record(info['table_id'],key)
   task={'table_id':info['table_id'],'record_key':key,'patch':{},'operation':'delete'}
   remote=Mock();remote.get_record.return_value={'record_id':key,'fields':{'语言种类':'人工修改'}}
   with pytest.raises(outbox_worker.SourceConflict):outbox_worker.publish(task,remote)
   remote.delete_record.assert_not_called()
   remote.get_record.return_value={'record_id':key,'fields':{'语言种类':'原始'}}
   assert outbox_worker.publish(task,remote)==key
   remote.delete_record.assert_called_once_with(info['table_id'],key)
   raise RuntimeError('rollback')

def test_inbound_refresh_adopts_external_change_but_preserves_unsynced_local_write(conn,monkeypatch):
 from contextlib import contextmanager
 from material_store import inbound
 @contextmanager
 def same_connection():yield conn
 monkeypatch.setattr(inbound,'connection',same_connection)
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   info=repo.named_table(conn,'物料语种');key='inbound-'+uuid4().hex
   repo.insert_source_records(conn,info,[{'record_id':key,'fields':{'语言种类':'原始'}}])
   client=Mock();client.list_records.return_value=[{'record_id':key,'fields':{'语言种类':'外部审批变更'}}]
   stats=inbound.refresh(['物料语种'],{'primary':client})
   assert stats['changed']==1
   assert repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']['语言种类']=='外部审批变更'
   DatabaseWriteClient(conn).update_record(info['table_id'],key,{'语言种类':'尚未同步的本地变更'})
   client.list_records.return_value=[{'record_id':key,'fields':{'语言种类':'另一个外部变更'}}]
   stats=inbound.refresh(['物料语种'],{'primary':client})
   assert stats['skipped']==1
   assert repo.feishu_record(info,repo.raw_record(conn,info,key))['fields']['语言种类']=='尚未同步的本地变更'
   raise RuntimeError('rollback')


def test_failed_duplicate_submission_is_not_reported_as_saved(conn,monkeypatch):
 from types import SimpleNamespace
 monkeypatch.setattr(jobs,'enqueue',lambda *a,**k:(SimpleNamespace(status='失败'),False))
 with pytest.raises(ValueError,match='此前未能保存'):jobs.submit('测试任务','failed-key',{})


def test_image_download_resolves_stable_local_key_to_feishu_record_id(conn,monkeypatch):
 from types import SimpleNamespace
 from request_web import live_data
 from material_store.client import DatabaseReadClient
 import app
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   info=repo.named_table(conn,app.CATEGORY_TABLE_NAME)
   remote_id='rec-image-'+uuid4().hex;local_id='local_'+uuid4().hex
   fields={'物料品类':'图片别名测试','申领页图片':[{'file_token':'fake-image-token','name':'image.png','url':'https://example.invalid/attachment'}]}
   repo.insert_source_records(conn,info,[{'record_id':remote_id,'fields':fields}])
   conn.execute(sql.SQL('UPDATE material_data.{} SET _record_key=%s WHERE _record_key=%s').format(sql.Identifier(info['sql_table'])),(local_id,remote_id))
   native=Mock();native.get_record.return_value={'record_id':remote_id,'fields':fields}
   native.download_bitable_attachment.return_value=b'image-bytes'
   reader=SimpleNamespace(client=DatabaseReadClient(remote=native,conn=conn),table_id=lambda name:info['table_id'])
   monkeypatch.setattr(live_data,'reader',lambda:reader)
   assert live_data.image_bytes(app.CATEGORY_TABLE_NAME,local_id,'fake-image-token')==b'image-bytes'
   native.get_record.assert_called_once_with(info['table_id'],remote_id)
   raise RuntimeError('rollback')


def test_directory_refresh_rejects_incomplete_result_before_replacing_data(conn):
 from material_store.contacts import publish,NAME
 from psycopg.types.json import Jsonb
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction():
   old={'users':[{'open_id':'ou_preserved'}],'departments':[{'department_id':'old'}]}
   conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload',(NAME,Jsonb(old)))
   with pytest.raises(ValueError):publish(conn,{'users':[],'departments':[]})
   assert conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',(NAME,)).fetchone()[0]==old
   new={'users':[{'open_id':'ou_updated'}],'departments':[{'department_id':'new'}]}
   assert publish(conn,new)=={'users':1,'departments':1}
   assert conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s',(NAME,)).fetchone()[0]==new
   raise RuntimeError('rollback')


def test_submission_resolves_renamed_linked_model_like_the_page_without_rewriting_stock(conn,monkeypatch):
 import app
 from feishu_bitable import FeishuBitableClient
 monkeypatch.setattr(FeishuBitableClient,'_request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unexpected HTTP')))
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   runtime.request_state['_write_conn']=conn
   models=repo.named_table(conn,app.MODEL_TABLE_NAME)
   categories=repo.named_table(conn,app.CATEGORY_TABLE_NAME)
   materials=repo.named_table(conn,app.MATERIAL_TABLE_NAME)
   model_id='model-'+uuid4().hex;category_id='category-'+uuid4().hex;material_id='material-'+uuid4().hex
   product='产品折页(Single Product Brochure)'
   repo.insert_source_records(conn,models,[{'record_id':model_id,'fields':{'产品型号':'GT系列三折页','启用状态':'启用'}}])
   repo.insert_source_records(conn,categories,[{'record_id':category_id,'fields':{'物料品类':product,'启用状态':'启用'}}])
   repo.insert_source_records(conn,materials,[{'record_id':material_id,'fields':{
    '物料编码':'regression-'+uuid4().hex,'物料品类':product,'产品型号':'GT系列3折页','语种':'日语(Japanese)','当前库存':7,
    '型号关联':[{'text':'X049','type':'text','table_id':models['table_id'],'record_ids':[model_id]}]}}])
   key=app.request_material_match_key(product,'GT系列三折页','日语(Japanese)')
   category_rows=repo.rows(conn,categories)
   assert key not in app.build_request_material_index(repo.rows(conn,materials),category_rows,include_all_for_admin=True)
   source=app.fresh_feishu_rows(app.MATERIAL_TABLE_NAME)
   matched=app.build_request_material_index(source,category_rows,include_all_for_admin=True)[key]
   assert matched['record_id']==material_id
   assert matched['fields']['当前库存']==7
   stored=repo.feishu_record(materials,repo.raw_record(conn,materials,material_id))
   assert stored['fields']['产品型号']=='GT系列3折页'
   assert stored['fields']['当前库存']==7
   raise RuntimeError('rollback')


@pytest.mark.parametrize('stock_name,link_name,label_name,target_name',[
 ('物料主数据','品类关联','物料品类','物料品类'),
 ('物料主数据','型号关联','产品型号','产品型号'),
 ('物料主数据','语种关联','语种','语言种类'),
 ('文化周边管理库存','物料品类关联','物料品类','物料品类'),
 ('文化周边管理库存','产品型号关联','产品型号','产品型号'),
 ('文化周边管理库存','战区关联','战区管理','战区名称'),
])
def test_every_catalog_dimension_uses_stable_link_in_reads_and_writes(conn,stock_name,link_name,label_name,target_name):
 from material_store.client import DatabaseReadClient
 import app
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   runtime.request_state['_write_conn']=conn
   info=repo.named_table(conn,stock_name)
   link=next(f for f in info['fields'] if f['field_name']==link_name)
   target=repo.table(conn,link['property']['table_id'])
   target_id='rec-test-'+uuid4().hex;local_id='local_'+uuid4().hex;stock_id='stock-'+uuid4().hex
   repo.insert_source_records(conn,target,[{'record_id':target_id,'fields':{target_name:'新名称-'+uuid4().hex}}])
   conn.execute(sql.SQL('UPDATE material_data.{} SET _record_key=%s WHERE _record_key=%s').format(sql.Identifier(target['sql_table'])),(local_id,target_id))
   repo.insert_source_records(conn,info,[{'record_id':stock_id,'fields':{label_name:'旧名称',link_name:[{'record_ids':[target_id],'text':'历史编号'}]}}])
   read=DatabaseReadClient(conn=conn).get_record(info['table_id'],stock_id)
   write=DatabaseWriteClient(conn).get_record(info['table_id'],stock_id)
   fresh=next(row for row in app.fresh_feishu_rows(stock_name) if row['record_id']==stock_id)
   assert read==write==fresh
   assert read['fields'][label_name].startswith('新名称-')
   assert repo.feishu_record(info,repo.raw_record(conn,info,stock_id))['fields'][label_name]=='旧名称'
   filtered=next(row for row in DatabaseReadClient(conn=conn).list_records(info['table_id'],field_names=[label_name]) if row['record_id']==stock_id)
   assert filtered['fields']=={label_name:read['fields'][label_name]}
   orphan={'record_id':'orphan','fields':{label_name:'保留旧名称',link_name:['rec-missing']}}
   assert repo.business_rows(conn,info,[orphan])==[orphan]
   raise RuntimeError('rollback')


def test_withdrawal_allows_automatic_fields_and_deleted_parent_but_guards_manual_changes(conn,monkeypatch):
 from contextlib import contextmanager
 from material_store import outbox_worker
 @contextmanager
 def same_connection():yield conn
 monkeypatch.setattr(outbox_worker,'connection',same_connection)
 with pytest.raises(RuntimeError,match='rollback'):
  with conn.transaction(),runtime.request_scope():
   parent=repo.named_table(conn,'物料申请单');lines=repo.named_table(conn,'申请明细')
   pid='rec-parent-'+uuid4().hex;lid='rec-line-'+uuid4().hex
   repo.insert_source_records(conn,parent,[{'record_id':pid,'fields':{'申请单号':'withdraw-test-'+uuid4().hex,'备注':'原备注'}}])
   repo.insert_source_records(conn,lines,[{'record_id':lid,'fields':{'所属申请单':[pid],'申请数量':1}}])
   client=DatabaseWriteClient(conn)
   client.delete_record(lines['table_id'],lid);client.delete_record(parent['table_id'],pid)
   source=Mock()
   source.get_record.return_value={'record_id':lid,'fields':{'所属申请单':[pid],'申请数量':1}}
   task={'table_id':lines['table_id'],'record_key':lid,'patch':{},'operation':'delete'}
   assert outbox_worker.publish(task,source)==lid
   source.get_record.return_value={'record_id':lid,'fields':{'所属申请单':[],'申请数量':1}}
   assert outbox_worker.publish(task,source)==lid
   row=repo.raw_record(conn,parent,pid,include_deleted=True)
   auto={'fields':{'申请单号':repo.feishu_record(parent,row)['fields']['申请单号'],'备注':'原备注',
     '申请人.部门':['部门自动回填'],'申请明细':[lid],'物料明细':['rec-auto-material']}}
   assert outbox_worker.delete_conflicts(conn,parent,row,auto,source)==[]
   auto['fields']['备注']='飞书人工修改'
   assert '备注' in outbox_worker.delete_conflicts(conn,parent,row,auto,source)
   auto['fields']['备注']='原备注'
   empty_text=next(f for f in parent['fields'] if f['type']==1 and f['field_id'] not in row['baseline'])
   auto['fields'][empty_text['field_name']]='飞书新填写的内容'
   assert empty_text['field_name'] in outbox_worker.delete_conflicts(conn,parent,row,auto,source)
   raise RuntimeError('rollback')
