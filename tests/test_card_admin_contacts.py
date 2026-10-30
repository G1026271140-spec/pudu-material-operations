from copy import deepcopy
import json
from uuid import uuid4
from unittest.mock import Mock
import pytest
import app,backend_runtime as runtime
from test_shipping_calendar import store
from test_account_tools import account_store,permission_body
from material_store import card_admin_contacts as contacts,effects,jobs,user_permissions as permissions,repository as repo


@pytest.mark.parametrize('text',[
 '您的（文化周边）需求已提交，请找<at id=ou_old></at> <at id=ou_old2></at>进行申领。',
 '如有疑问或其他需求，请联系<at id=ou_old></at>',
 'If you have any questions or other requests, please contact <at id=ou_old></at>',
 '您的文化周边申领已驳回。如有疑问，请联系<at id=ou_old></at>。',
 '您的（文化周边）需求已提交，请找已启用的管理员进行申领。',
])
def test_contact_refresh_preserves_card_and_other_mentions(text):
 card={'body':{'elements':[{'tag':'markdown','content':text},{'tag':'markdown','content':'申请人 <at id=ou_applicant></at>'},{'tag':'button','value':{'action':'reject','request_no':'KEEP'}}]}}
 before=deepcopy(card);updated,found=contacts.refresh(card,['ou_new','ou_new','ou_second'])
 assert found and card==before
 contact=updated['body']['elements'][0]['content']
 assert '<at id=ou_new></at> <at id=ou_second></at>' in contact and 'ou_old' not in contact
 assert updated['body']['elements'][1:]==card['body']['elements'][1:]
 assert contacts.refresh(updated,[])[0]['body']['elements'][0]['content']


def enqueue(conn,card,method='send_interactive_message',attempts=0):
 conn.execute("UPDATE material_ops.effects SET state='done' WHERE state IN ('pending','processing','retry')")
 task,_=jobs.enqueue('测试管理员联系人','card-contact-'+uuid4().hex,{},conn=conn)
 with runtime.request_scope():
  runtime.request_state.update(_write_conn=conn,_job_id=task.task_id)
  effects.defer('primary',method,['ou_applicant' if method=='send_interactive_message' else 'om_original',card],{})
 eid=conn.execute('SELECT id FROM material_ops.effects WHERE job_id=%s',(task.task_id,)).fetchone()[0]
 if attempts:conn.execute("UPDATE material_ops.effects SET attempts=%s,first_attempt_at=now(),state='retry' WHERE id=%s",(attempts,eid))
 return eid


def switch(conn,ids):
 permissions.save(ids['admin'],permission_body(conn,ids['sales'],roles=['管理员','销售']))
 permissions.save(ids['sales'],permission_body(conn,ids['admin'],enabled=False))
 assert ids['sales'] in contacts.enabled_admins(conn) and ids['admin'] not in contacts.enabled_admins(conn)


def card(old):return app._cultural_request_card('TEST','测试申请人',[],applicant=True,admin_open_ids=[old])


def test_queued_send_uses_updated_enabled_admins_without_waiting_for_feishu(account_store):
 conn,ids=account_store;eid=enqueue(conn,card(ids['admin']));switch(conn,ids)
 native=Mock();native._request.return_value={'data':{'message_id':'om_new'}}
 assert effects.run_once({'primary':native})['state']=='done'
 payload=native._request.call_args.kwargs['payload'];sent=json.loads(payload['content'])
 assert ids['sales'] in json.dumps(sent) and ids['admin'] not in json.dumps(sent)
 assert payload['receive_id']=='ou_applicant' and payload['uuid']==str(eid)
 assert conn.execute('SELECT args->1 FROM material_ops.effects WHERE id=%s',(eid,)).fetchone()[0]==sent
 native.update_interactive_message.assert_not_called()


def test_business_update_patches_same_message_with_new_contacts(account_store):
 conn,ids=account_store;enqueue(conn,card(ids['admin']),'update_interactive_message');switch(conn,ids)
 native=Mock();native.update_interactive_message.return_value=None
 assert effects.run_once({'primary':native})['state']=='done'
 message,updated=native.update_interactive_message.call_args.args
 assert message=='om_original' and ids['sales'] in json.dumps(updated) and ids['admin'] not in json.dumps(updated)
 native._request.assert_not_called()


def test_send_unknown_result_reuses_uuid_and_body_then_updates_original_only(account_store):
 conn,ids=account_store;original=card(ids['admin']);eid=enqueue(conn,original,attempts=1);switch(conn,ids)
 native=Mock();native._request.return_value={'data':{'message_id':'om_already_delivered'}}
 native.update_interactive_message.side_effect=[RuntimeError('network'),None]
 assert effects.run_once({'primary':native})['state']=='retry'
 sent=native._request.call_args.kwargs['payload'];assert json.loads(sent['content'])==original and sent['uuid']==str(eid)
 assert conn.execute('SELECT remote_id FROM material_ops.effects WHERE id=%s',(eid,)).fetchone()[0]=='om_already_delivered'
 conn.execute('UPDATE material_ops.effects SET available_at=now() WHERE id=%s',(eid,))
 assert effects.run_once({'primary':native})['state']=='done'
 assert native._request.call_count==1
 assert all(call.args[0]=='om_already_delivered' for call in native.update_interactive_message.call_args_list)
 assert ids['sales'] in json.dumps(native.update_interactive_message.call_args.args[1])


def test_duplicate_enabled_roles_union_and_no_historical_backfill(account_store):
 conn,ids=account_store;info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
 for enabled in ['是','否']:
  repo.insert_source_records(conn,info,[{'record_id':'rec_'+uuid4().hex,'fields':{'用户账号':[{'id':ids['other']}],'角色':['管理员'],'是否启用':enabled}}])
 assert contacts.enabled_admins(conn).count(ids['other'])==1
 eid=enqueue(conn,card(ids['admin']));conn.execute("UPDATE material_ops.effects SET state='done',remote_id='om_history' WHERE id=%s",(eid,));switch(conn,ids)
 native=Mock();assert effects.run_once({'primary':native}) is None
 assert conn.execute('SELECT args->1 FROM material_ops.effects WHERE id=%s',(eid,)).fetchone()[0]==card(ids['admin'])
 native._request.assert_not_called();native.update_interactive_message.assert_not_called()
