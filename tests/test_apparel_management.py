import os,importlib
from contextlib import contextmanager
from uuid import uuid4
import pytest
psycopg=pytest.importorskip('psycopg')
from starlette.requests import Request
from fastapi import HTTPException
import app,backend_runtime as runtime
from material_store import apparel,repository as repo,db
from request_web.live_data import LiveReader

DSN=os.environ.get('PUDU_TEST_DATABASE_DSN')

@pytest.mark.parametrize('roles,enabled,allowed',[
 (['HR'],'是',True),(['管理员'],'是',True),(['HR','销售'],'是',True),
 (['销售'],'是',False),([],'是',False),(['HR'],'否',False),(['管理员'],'否',False)])
def test_only_enabled_hr_or_admin_passes_apparel_permission(monkeypatch,roles,enabled,allowed):
 web=importlib.import_module('request_web.api')
 from request_web import feishu_auth
 monkeypatch.setattr(feishu_auth,'session_identity',lambda *a:{'open_id':'ou_permission_test'})
 monkeypatch.setattr(feishu_auth,'own_tenant_key',lambda:'test-tenant')
 monkeypatch.setattr(web,'_json',lambda name:{'tables':{'用户权限表':[{'fields':{'用户账号':[{'id':'ou_permission_test'}],'角色':roles,'是否启用':enabled}}]}})
 request=Request({'type':'http','headers':[(b'cookie',b'pudu_feishu=fake')]})
 if allowed:assert web.require_hr(request)=='ou_permission_test'
 else:
  with pytest.raises(HTTPException) as error:web.require_hr(request)
  assert error.value.status_code==403

@pytest.fixture
def store(monkeypatch):
 if not DSN:pytest.skip('Requires isolated PostgreSQL database')
 for name,value in {'PUDU_DATA_SOURCE':'postgresql','PUDU_DATABASE_DSN':DSN,'FEISHU_APP_ID':'test','FEISHU_APP_SECRET':'test','FEISHU_BITABLE_APP_TOKEN':'test','FEISHU_CORPORATE_APPAREL_SOURCE_APP_TOKEN':'test-apparel'}.items():monkeypatch.setenv(name,value)
 from feishu_bitable import FeishuBitableClient
 monkeypatch.setattr(FeishuBitableClient,'_request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unexpected Feishu HTTP')))
 db.pool.cache_clear()
 with psycopg.connect(DSN,autocommit=True) as conn:
  assert conn.execute('SELECT current_database()').fetchone()[0]=='pudu_materials_test'
  @contextmanager
  def same_connection():yield conn
  monkeypatch.setattr(apparel,'connection',same_connection)
  with pytest.raises(RuntimeError,match='rollback'):
   with conn.transaction(),runtime.request_scope():
    actor='ou_apparel_'+uuid4().hex
    info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    fields={'用户编号':'hr-test-'+uuid4().hex,'用户账号':[{'id':actor}],'角色':['HR','管理员','销售'],'是否启用':'是'}
    for field in info['fields']:
     if '累计' in field['field_name']:fields[field['field_name']]=0
    repo.insert_source_records(conn,info,[{'record_id':'rec-'+uuid4().hex,'fields':fields}])
    yield conn,actor
    raise RuntimeError('rollback')
 if db.pool.cache_info().currsize:db.pool().close();db.pool.cache_clear()

def draft():
 suffix=uuid4().hex
 return {'operation':'create','idempotency_key':'apparel-'+suffix,'source_style':'文化衫-新款-'+suffix,'label':'新款-'+suffix,
  'visible':True,'limit':2,'rows':[{'record_id':'','size':'M','code':'CF-'+suffix,'original':7,'correction':0,'remark':'隔离验证'}]}

def write_scope(conn):
 runtime.request_state['_write_conn']=conn
 runtime.request_state['_live_reader']=LiveReader()

def test_new_style_claim_rename_quota_and_rejection_are_source_backed(store):
 conn,actor=store;body=draft();result=apparel.save(actor,body);key=result['style_key']
 assert apparel.save(actor,body)==result
 write_scope(conn)
 catalog=app.corporate_apparel_catalog([])
 item=next(item for item in catalog['items'] if item['product']==key)
 assert item['available']==7 and item['record_id']==item['source_record_id']
 assert catalog['productLabels'][key]==body['label'] and catalog['productLimits'][key]==2
 payload={'requester':'隔离 HR','requester_open_id':actor,'submitter':'隔离 HR','submitter_open_id':actor,'department':'测试','department_id':'','material_usage':'入职','submission_token':'claim-'+uuid4().hex}
 plan=app.corporate_apparel_request_plan(payload,[{'product':key,'size':'M','quantity':1}])
 assert plan['quota_allowed']
 number,_,created=app.submit_feishu_corporate_apparel_request(payload,plan)
 assert created
 assert apparel.claim_used(actor,key)==1
 assert not app.corporate_apparel_request_plan(payload,[{'product':key,'size':'M','quantity':2}])['quota_allowed']
 style=next(style for style in apparel.manager_catalog(conn)['styles'] if style['key']==key)
 edit={**body,'operation':'edit','style_key':key,'label':'改名后-'+uuid4().hex,'expected_versions':style['expected_versions'],'rows':style['rows'],'idempotency_key':'rename-'+uuid4().hex}
 apparel.save(actor,edit);write_scope(conn)
 assert not app.corporate_apparel_request_plan(payload,[{'product':key,'size':'M','quantity':2}])['quota_allowed']
 rejected=app.corporate_apparel_rejection_plan(number,actor)
 app.execute_corporate_apparel_rejection(rejected)
 assert apparel.claim_used(actor,key)==0
 assert app.corporate_apparel_request_plan(payload,[{'product':key,'size':'M','quantity':2}])['quota_allowed']
 style=next(style for style in apparel.manager_catalog(conn)['styles'] if style['key']==key)
 with pytest.raises(ValueError,match='领用历史'):
  apparel.save(actor,{'operation':'delete','style_key':key,'expected_versions':style['expected_versions'],'confirm_delete':style['label'],'idempotency_key':'delete-'+uuid4().hex})
 assert style['rows'][0]['available']==7

def test_unused_new_style_can_be_deleted_and_stale_edits_rejected(store):
 conn,actor=store;body=draft();result=apparel.save(actor,body);key=result['style_key']
 style=next(style for style in apparel.manager_catalog(conn)['styles'] if style['key']==key)
 edit={**body,'operation':'edit','style_key':key,'expected_versions':style['expected_versions'],'rows':style['rows'],'label':body['label']+'-改名','idempotency_key':'edit-'+uuid4().hex}
 apparel.save(actor,edit)
 # Two HR editors cannot overwrite each other even before the first
 # asynchronous create has reached Feishu.
 with pytest.raises(repo.VersionConflict):apparel.save(actor,{**edit,'idempotency_key':'stale-content-'+uuid4().hex,'label':'另一个值'})
 with pytest.raises(repo.VersionConflict):apparel.save(actor,{**edit,'label':'另一个值'})
 stale={**edit,'idempotency_key':'stale-'+uuid4().hex,'expected_versions':{'wrong':0}}
 with pytest.raises(repo.VersionConflict):apparel.save(actor,stale)
 current=next(style for style in apparel.manager_catalog(conn)['styles'] if style['key']==key)
 apparel.save(actor,{'operation':'delete','style_key':key,'expected_versions':current['expected_versions'],'confirm_delete':current['label'],'idempotency_key':'remove-'+uuid4().hex})
 assert key not in {style['key'] for style in apparel.manager_catalog(conn)['styles']}

def test_style_visibility_and_duplicate_size_validation(store):
 conn,actor=store;body=draft();result=apparel.save(actor,body);key=result['style_key']
 style=next(style for style in apparel.manager_catalog(conn)['styles'] if style['key']==key)
 apparel.save(actor,{**body,'operation':'edit','style_key':key,'visible':False,'expected_versions':style['expected_versions'],'rows':style['rows'],'idempotency_key':'hide-'+uuid4().hex})
 write_scope(conn)
 assert key not in app.corporate_apparel_catalog([])['products']
 invalid=draft();invalid['rows']*=2
 with pytest.raises(ValueError,match='重复'):apparel.save(actor,invalid)


def test_administrative_source_create_uses_unique_sku_code_for_retry_dedup(store):
 from unittest.mock import Mock
 from material_store.outbox_worker import _find_remote_create,SourceConflict
 conn,_=store;info=apparel.source_info(conn);client=Mock()
 row={'record_id':'rec_existing','fields':{'编码':'CF-UNIQUE'}}
 client.list_records.return_value=[row]
 assert _find_remote_create(client,info,{'编码':'CF-UNIQUE','款式':'新款式'})==row
 client.list_records.return_value=[row,{**row,'record_id':'rec_duplicate'}]
 with pytest.raises(SourceConflict):_find_remote_create(client,info,{'编码':'CF-UNIQUE'})
