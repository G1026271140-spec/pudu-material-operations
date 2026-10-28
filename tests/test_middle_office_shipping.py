from contextlib import contextmanager
from io import BytesIO
import importlib
from unittest.mock import Mock

import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from PIL import Image

import app
from test_shipping_calendar import store,insert_request
from test_account_tools import account_store,permission_body
from test_shipping_access import SnapshotTestConnection
from test_shipping_batch import change,batch
from material_store import shipping_calendar as shipping,repository as repo,outbox_worker,effects,jobs


def identity(monkeypatch,roles,enabled='是'):
    web=importlib.import_module('request_web.api')
    from request_web import feishu_auth
    monkeypatch.setattr(feishu_auth,'own_tenant_key',lambda:'test-tenant')
    monkeypatch.setattr(feishu_auth,'session_identity',lambda *a:{'open_id':'ou_middle','name':'隔离中台'})
    monkeypatch.setattr(web,'_json',lambda name:{'tables':{'用户权限表':[{'fields':{'用户账号':[{'id':'ou_middle'}],'角色':roles,'是否启用':enabled}}]}})
    return web


@pytest.mark.parametrize('roles,enabled,allowed',[
    (['中台'],'是',True),(['销售','中台'],'是',True),(['管理员'],'是',True),
    (['中台'],'否',False),(['HR'],'是',False),(['销售'],'是',False),([], '是',False),
])
def test_shipping_role_gate_preserves_enabled_role_boundary(monkeypatch,roles,enabled,allowed):
    web=identity(monkeypatch,roles,enabled)
    request=Request({'type':'http','headers':[(b'cookie',b'pudu_feishu=isolated')]})
    if allowed:assert web.require_shipping_editor(request)=='ou_middle'
    else:
        with pytest.raises(HTTPException) as error:web.require_shipping_editor(request)
        assert error.value.status_code==403
    if roles==['中台'] and enabled=='是':
        for gate in [web.require_admin,web.require_hr]:
            with pytest.raises(HTTPException) as error:gate(request)
            assert error.value.status_code==403
        monkeypatch.setattr(app,'valid_request_review_access_token',lambda *a:False)
        with pytest.raises(HTTPException) as error:web._allocation_actor(request,'rec_any')
        assert error.value.status_code==403
        assert web._signed_admin_open_id(request)==''


def test_middle_office_shipping_edit_upload_publish_and_notification_order(store,monkeypatch):
    conn=store;web=identity(monkeypatch,['中台'])
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','retry','processing')")
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state IN ('pending','retry','processing')")
    api_module=importlib.import_module('request_web.shipping_calendar_api')
    @contextmanager
    def same_connection():yield conn
    @contextmanager
    def snapshot_connection():yield SnapshotTestConnection(conn)
    monkeypatch.setattr(api_module,'connection',snapshot_connection)
    for module in [effects,jobs,outbox_worker]:monkeypatch.setattr(module,'connection',same_connection)
    for name in ['FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_BITABLE_APP_TOKEN']:monkeypatch.setenv(name,'test')
    key=insert_request(conn,申请人=[{'id':'ou_other_owner'}])
    second=insert_request(conn,申请人=[{'id':'ou_another_owner'}])
    api=FastAPI()
    api_module.register(api,web.require_shipping_editor,lambda:'ou_middle',web._signed_shipping_editor_open_id)
    headers={'Cookie':'pudu_feishu=isolated'}
    with TestClient(api) as client:
        data=client.get('/api/shipping-calendar',headers=headers).json()
        assert data['can_edit'] is True and {key,second}<={r['request_id'] for r in data['requests']}
        assert client.get('/api/admin/shipping-calendar',headers=headers).status_code==200
        image=BytesIO();Image.new('RGB',(4,4),'green').save(image,'PNG')
        photo=client.post('/api/admin/shipping-calendar/images',headers={**headers,'X-File-Name':'test.png'},content=image.getvalue())
        assert photo.status_code==200,photo.text
        photo=photo.json();assert client.get(photo['path'],headers=headers).status_code==200
        draft=change(conn,key,shipping_text='中台隔离测试',shipped=True,ship_date='2026-11-06',images=[{'local_media_id':photo['local_media_id']}])
        payload=batch([draft])
        response=client.post('/api/admin/shipping-calendar/batch',headers=headers,json=payload)
        assert response.status_code==200,response.text
        result=response.json();assert result['changed']==1
        assert client.post('/api/admin/shipping-calendar/batch',headers=headers,json=payload).json()==result
        raw=repo.raw_record(conn,shipping.source_info(conn),key)
        fields=repo.feishu_record(shipping.source_info(conn),raw)['fields']
        assert fields[shipping.TEXT]=='中台隔离测试' and fields[shipping.SHIPPED] is True
        assert shipping.date_text(fields['物料发货时间'])=='2026-11-06'
        assert fields[shipping.IMAGES][0]['local_media_id']==photo['local_media_id']
        assert raw['sync_state']=='pending'
        fake=Mock()
        fake.get_record.return_value=repo.feishu_record(shipping.source_info(conn),{'record_id':key,'fields':raw['baseline']})
        fake.upload_media.return_value='fake_middle_photo'
        assert effects.run_once({'primary':fake}) is None
        fake._request.assert_not_called()
        assert outbox_worker.run_once('ordinary',{'primary':fake})['state']=='done'
        fake.update_record.assert_called_once()
        sent=fake.update_record.call_args.args[2]
        assert sent[shipping.TEXT]=='中台隔离测试' and sent[shipping.SHIPPED] is True
        assert sent[shipping.IMAGES][0]['file_token']=='fake_middle_photo'
        fake._request.return_value={'data':{'message_id':'isolated'}}
        assert effects.run_once({'primary':fake})['state']=='done'
        assert fake._request.call_args.kwargs['payload']['receive_id']=='ou_other_owner'
        assert conn.execute('SELECT count(*) FROM material_ops.effects WHERE job_id=%s',(result['batch_id'],)).fetchone()[0]==1
        # Removing the role immediately denies writes and broad read access.
        identity(monkeypatch,['销售'])
        assert client.post('/api/admin/shipping-calendar/batch',headers=headers,json=payload).status_code==403
        own=client.get('/api/shipping-calendar',headers=headers).json()
        assert own['can_edit'] is False and not any(r['request_id'] in {key,second} for r in own['requests'])


def test_additive_role_migration_and_grant_round_trip_preserves_existing_roles_and_quotas(account_store,tmp_path):
    import copy,json
    from scripts.add_middle_office_shipping_role import migrate,TABLE,ROLE
    from material_store import user_permissions as permissions,portal_records as history
    conn,ids=account_store
    local=next(f for f in repo.table(conn,TABLE)['fields'] if f['field_name']=='角色')
    local=copy.deepcopy(local)
    local['property']['options']=[o for o in local['property']['options'] if o['name']!=ROLE]
    before=copy.deepcopy(local['property']['options'])
    registry=tmp_path/'registry.json'
    registry.write_text(json.dumps({'tables':[{'table_id':TABLE,'fields':[local]}]}))
    class Source:
        def __init__(self):self.field=copy.deepcopy(local);self.writes=0
        def list_fields(self,table):assert table==TABLE;return [copy.deepcopy(self.field)]
        def _quoted_app_token(self):return 'test'
        def _request(self,method,path,*,payload):
            assert method=='PUT' and path.endswith('/'+self.field['field_id'])
            self.writes+=1;self.field.update(copy.deepcopy(payload))
            self.field['property']['options'][-1]['id']='opt_middle_isolated'
    source=Source()
    assert migrate(source,conn,registry)['apply'] is False and source.writes==0
    assert migrate(source,conn,registry,True,False)['existing_options_preserved']
    assert migrate(source,conn,registry,True,False)['roles_after']==[o['name'] for o in before]+[ROLE]
    assert source.writes==1 and source.field['property']['options'][:-1]==before
    assert ROLE in permissions.catalog(conn)['roles']
    info=repo.table(conn,TABLE)
    old=next(row for row in history.permission_rows(conn) if ids['sales'] in app.feishu_person_open_ids(row['fields'],['用户账号']))
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state IN ('pending','retry','processing')")
    result=permissions.save(ids['admin'],permission_body(conn,ids['sales'],roles=[ROLE]))
    assert result['saved'] and history.roles_for(conn,ids['sales'])=={ROLE}
    with pytest.raises(PermissionError):history.history(conn,ids['sales'],'all')
    raw=repo.raw_record(conn,info,old['record_id'])
    fake=Mock();fake.get_record.return_value=repo.feishu_record(info,{'record_id':old['record_id'],'fields':raw['baseline']})
    assert outbox_worker.run_once('admin',{'primary':fake})['state']=='done'
    assert fake.update_record.call_args.args[2]=={'角色':[ROLE]}
    current=repo.feishu_record(info,repo.raw_record(conn,info,old['record_id']))['fields']
    assert current['T恤-黑色（短袖）申领数量累计']==old['fields']['T恤-黑色（短袖）申领数量累计']
