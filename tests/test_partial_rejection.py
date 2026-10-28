import json
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import Mock
import pytest
from psycopg import sql
import app,backend_runtime as runtime
from test_account_tools import account_store
from test_shipping_calendar import store
from material_store import apparel,portal_records as history,repository as repo,effects,jobs
from material_store.client import DatabaseWriteClient
from request_web.live_data import LiveReader

def scope(conn,actor):
    runtime.request_state.update(_write_conn=conn,_write_actor=actor,_write_lane='cultural',_live_reader=LiveReader())

def fixture_request(conn,ids,kind):
    scope(conn,ids['sales'])
    number='PARTIAL-'+uuid4().hex;request_id='rec_req_'+uuid4().hex
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    recipients={f'applicant:{ids["sales"]}':'om_applicant_'+uuid4().hex}
    audience=app.enabled_role_open_ids('HR') if kind=='apparel' else app.enabled_admin_open_ids()
    for actor in audience:recipients[('hr:' if kind=='apparel' else 'admin:')+actor]='om_'+uuid4().hex
    request_fields={'申请单号':number,'申请类型':app.CORPORATE_APPAREL_REQUEST_TYPE if kind=='apparel' else '文化周边申请',
        '业务类型':app.CORPORATE_APPAREL_REQUEST_TYPE if kind=='apparel' else '文化周边申领','申请人':[{'id':ids['sales']}],
        '文化周边处理状态':'已发放','文化周边通知状态':'已发送',app.CULTURAL_REQUEST_MESSAGE_IDS_FIELD:json.dumps(recipients)}
    repo.insert_source_records(conn,info,[{'record_id':request_id,'fields':request_fields}])
    line_info=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME);lines=[];sources=[]
    products=['T恤-黑色（短袖）','休闲商务夹克-黑色（长袖）'] if kind=='apparel' else ['文化衫','文化夹克']
    for index,product in enumerate(products):
        quantity=1 if kind=='apparel' or index else 2
        source_id='rec_stock_'+uuid4().hex;line_id='rec_line_'+uuid4().hex
        if kind=='apparel':
            source=apparel.source_info(conn)
            fields={'物品分类':'文化衫','款式':app.CORPORATE_APPAREL_STYLE_MAP[product],'码数':'M','编码':'TEST-'+uuid4().hex,
                '原始库存数量':10,'系统兑换数量':quantity,apparel.KEY:product,apparel.LABEL:product,apparel.VISIBLE:'是',apparel.LIMIT:2}
            marker=f'{app.CORPORATE_APPAREL_LINE_MARKER}:{source_id}\n企业文化衫行政源记录ID:{source_id}\n企业文化衫款式编号:{product}'
        else:
            source=repo.named_table(conn,app.CULTURAL_MATERIAL_TABLE_NAME)
            fields={'物料品类':product,'产品型号':'M','战区管理':'隔离战区',**app.cultural_stock_fields(10-quantity)};marker=''
        repo.insert_source_records(conn,source,[{'record_id':source_id,'fields':fields}])
        line_fields={'明细编号':number+'-'+str(index),'申请单号':number,'所属申请单':[request_id],
            '品类名称':product,'产品型号名称':'M','文化周边战区':'隔离战区','申请数量':quantity,'审批通过数量':quantity,
            '实际发放数量':quantity,'明细状态':'已发放','明细业务类型':app.CORPORATE_APPAREL_LINE_TYPE if kind=='apparel' else '文化周边','备注':marker}
        if kind=='culture':line_fields['文化周边物料']=[source_id]
        names={field['field_name'] for field in line_info['fields']}
        assert {'所属申请单','品类名称','申请数量','实际发放数量','明细状态','明细业务类型'}<=names
        repo.insert_source_records(conn,line_info,[{'record_id':line_id,'fields':{name:value for name,value in line_fields.items() if name in names}}])
        lines.append(line_id);sources.append((source,source_id))
    permission=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    person=next(row for row in repo.rows(conn,permission) if ids['sales'] in app.feishu_person_open_ids(row['fields'],['用户账号']))
    DatabaseWriteClient(conn).update_record(permission['table_id'],person['record_id'],{
        'T恤-黑色（短袖）申领数量累计':1,'POLO申领数量累计':0 if kind=='apparel' else 2,'文化夹克申领数量累计':1})
    return request_id,number,lines,sources,recipients,person['record_id']

def reject(kind,actor,request_id,line_ids):
    method=history.reject_apparel if kind=='apparel' else history.reject_cultural
    return method(actor,{'request_id':request_id,'confirmed':True,'line_ids':line_ids})

@pytest.mark.parametrize('kind',['apparel','culture'])
def test_partial_then_overlapping_rejection_refunds_each_line_once_and_updates_original_cards(account_store,kind):
    conn,ids=account_store;request_id,number,lines,sources,recipients,person=fixture_request(conn,ids,kind)
    one=reject(kind,ids['hr'],request_id,[lines[0]])
    assert one['rejected'] and one['partial_rejected']
    again=reject(kind,ids['admin'],request_id,[lines[0]])
    assert again['job_id']==one['job_id']
    item=next(item for item in history.history(conn,ids['hr'],'all')['requests'] if item['id']==request_id)
    assert item['status']=='部分驳回' and item['can_reject']
    assert [line['can_reject'] for line in item['lines']].count(True)==1
    assert next(line for line in item['lines'] if line['id']==lines[0])['issued']==0
    source,source_id=sources[0];first=repo.feishu_record(source,repo.raw_record(conn,source,source_id))['fields']
    source,source_id=sources[1];other=repo.feishu_record(source,repo.raw_record(conn,source,source_id))['fields']
    assert first['系统兑换数量' if kind=='apparel' else '当前库存']==(0 if kind=='apparel' else 10)
    assert other['系统兑换数量' if kind=='apparel' else '当前库存']==(1 if kind=='apparel' else 9)
    permission=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    fields=repo.feishu_record(permission,repo.raw_record(conn,permission,person))['fields']
    assert fields['T恤-黑色（短袖）申领数量累计' if kind=='apparel' else 'POLO申领数量累计']==0
    assert fields['文化夹克申领数量累计']==1
    # Applicant cards cannot be delivered before their source writes complete.
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id<>%s AND state IN ('pending','retry','processing')",(one['job_id'],))
    fake=Mock();fake.update_interactive_message.return_value=None
    assert effects.run_once({'primary':fake}) is None
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state IN ('pending','retry','processing')")
    for _ in recipients:assert effects.run_once({'primary':fake})['state']=='done'
    assert {call.args[0] for call in fake.update_interactive_message.call_args_list}==set(recipients.values())
    assert fake.send_interactive_message.call_count==0
    assert all('部分驳回' in call.args[1]['header']['title']['content'] for call in fake.update_interactive_message.call_args_list)
    body=json.dumps(fake.update_interactive_message.call_args_list[0].args[1],ensure_ascii=False)
    assert '保留明细' in body and '已驳回明细' in body
    request_info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    assert repo.feishu_record(request_info,repo.raw_record(conn,request_info,request_id))['fields']['文化周边通知状态']=='驳回已通知'
    two=reject(kind,ids['admin'],request_id,list(reversed(lines)))
    assert two['rejected'] and not two['partial_rejected']
    item=next(item for item in history.history(conn,ids['hr'],'all')['requests'] if item['id']==request_id)
    assert item['status']=='已驳回' and not item['can_reject'] and all(line['issued']==0 for line in item['lines'])
    fields=repo.feishu_record(permission,repo.raw_record(conn,permission,person))['fields']
    assert fields['文化夹克申领数量累计']==0
    source,source_id=sources[0];first=repo.feishu_record(source,repo.raw_record(conn,source,source_id))['fields']
    assert first['系统兑换数量' if kind=='apparel' else '当前库存']==(0 if kind=='apparel' else 10)
    if kind=='culture':
        ledger=repo.named_table(conn,app.LEDGER_TABLE_NAME)
        reversal=[row for row in repo.rows(conn,ledger) if str(row['fields'].get('幂等键','')).startswith('cultural-reject:'+number+':')]
        assert len(reversal)==2

@pytest.mark.parametrize('kind',['apparel','culture'])
@pytest.mark.parametrize('selection',['empty','duplicate','foreign'])
def test_invalid_line_selection_never_changes_stock_or_quota(account_store,kind,selection):
    conn,ids=account_store;request_id,number,lines,sources,recipients,person=fixture_request(conn,ids,kind)
    bad=[] if selection=='empty' else [lines[0],lines[0]] if selection=='duplicate' else [lines[0],'foreign_line']
    before=[repo.raw_record(conn,source,key) for source,key in sources]
    with pytest.raises(ValueError):reject(kind,ids['hr'],request_id,bad)
    assert [repo.raw_record(conn,source,key) for source,key in sources]==before

@pytest.mark.parametrize('kind',['apparel','culture'])
def test_sales_cannot_reject_cultural_items(account_store,kind):
    conn,ids=account_store;request_id,_,lines,*_=fixture_request(conn,ids,kind)
    with pytest.raises(PermissionError):reject(kind,ids['sales'],request_id,[lines[0]])

@pytest.mark.parametrize('kind',['apparel','culture'])
def test_effect_failure_rolls_back_selected_stock_and_quota(account_store,monkeypatch,kind):
    conn,ids=account_store;request_id,_,lines,sources,_,person=fixture_request(conn,ids,kind)
    before=[repo.raw_record(conn,source,key) for source,key in sources]
    monkeypatch.setattr(effects,'defer',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('isolated rollback')))
    with pytest.raises(RuntimeError,match='isolated rollback'):reject(kind,ids['hr'],request_id,[lines[0]])
    assert [repo.raw_record(conn,source,key) for source,key in sources]==before

def test_date_only_shipping_change_has_card_old_and_new_dates_and_outbox_gate(store,monkeypatch):
    from test_shipping_batch import request,change,batch
    from material_store import shipping_calendar as shipping
    conn=store
    for name in ['FEISHU_APP_ID','FEISHU_APP_SECRET','FEISHU_BITABLE_APP_TOKEN']:monkeypatch.setenv(name,'isolated-test')
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(effects,'connection',same)
    key=request(conn)
    result=shipping.save_batch('ou_admin',batch([change(conn,key,shipping_text='原说明',shipped=False,ship_date='2026-10-29')]))
    args,kwargs=conn.execute('SELECT args,kwargs FROM material_ops.effects WHERE job_id=%s',(result['batch_id'],)).fetchone()
    assert args[1]['header']['title']['content']=='物料发货时间变更通知'
    text=json.dumps(args[1],ensure_ascii=False)
    assert '2026-10-28' in text and '2026-10-29' in text and 'shipping_view=readonly' in text
    assert kwargs['_shipping_date_change'] and kwargs['_shipping_date_before']=='2026-10-28' and kwargs['_shipping_date_after']=='2026-10-29'
    assert effects.run_once({'primary':Mock()}) is None

@pytest.mark.parametrize('kind',['apparel','culture'])
def test_later_rejection_cards_wait_for_earlier_retry_and_latest_batch_acknowledges(account_store,kind):
    conn,ids=account_store;request_id,_,lines,_,recipients,_=fixture_request(conn,ids,kind)
    one=reject(kind,ids['hr'],request_id,[lines[0]])
    two=reject(kind,ids['admin'],request_id,[lines[1]])
    conn.execute("UPDATE material_ops.effects SET state='done' WHERE job_id::text<>ALL(%s) AND state IN ('pending','retry','processing')",([one['job_id'],two['job_id']],))
    conn.execute("UPDATE material_ops.outbox SET state='done' WHERE state IN ('pending','retry','processing')")
    conn.execute("UPDATE material_ops.effects SET state='retry',available_at=now()+interval '1 hour' WHERE job_id=%s AND ordinal=1",(one['job_id'],))
    fake=Mock();fake.update_interactive_message.return_value=None
    assert effects.run_once({'primary':fake}) is None
    assert fake.update_interactive_message.call_count==0
    conn.execute("UPDATE material_ops.effects SET available_at=now() WHERE job_id=%s",(one['job_id'],))
    info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    for _ in recipients:assert effects.run_once({'primary':fake})['state']=='done'
    assert repo.feishu_record(info,repo.raw_record(conn,info,request_id))['fields']['文化周边通知状态']=='驳回待通知'
    for _ in recipients:assert effects.run_once({'primary':fake})['state']=='done'
    calls=fake.update_interactive_message.call_args_list
    assert all('部分驳回' in call.args[1]['header']['title']['content'] for call in calls[:len(recipients)])
    assert all('已驳回' in call.args[1]['header']['title']['content'] for call in calls[len(recipients):])
    assert repo.feishu_record(info,repo.raw_record(conn,info,request_id))['fields']['文化周边通知状态']=='驳回已通知'
