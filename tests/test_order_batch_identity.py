from unittest.mock import Mock
import pytest
from material_store.outbox_worker import _find_remote_create,SourceConflict

@pytest.fixture(params=[('物料下单批次','下单批次号'),('物料下单批次明细','批次明细编号')])
def table(request):
    name,key=request.param
    return {'source':'primary','name':name,'table_id':'test_order_table','fields':[{'field_id':'id_'+field,'field_name':field,'type':1} for field in [key,'批次备注','物料品类']]},key

def test_new_batch_identity_does_not_match_another_batch_same_category(table):
    info,key=table;client=Mock()
    client.list_records.return_value=[{'record_id':'old','fields':{key:'old-key','物料品类':'same'}}]
    assert _find_remote_create(client,info,{key:'new-key','物料品类':'same'}) is None

def test_retry_finds_existing_exact_record(table):
    info,key=table;client=Mock();row={'record_id':'existing','fields':{key:'stable-key','批次备注':'same'}}
    client.list_records.return_value=[row]
    assert _find_remote_create(client,info,{key:'stable-key','批次备注':'same'})==row

def test_duplicate_or_changed_batch_not_silently_reused(table):
    info,key=table;client=Mock();row={'record_id':'existing','fields':{key:'stable-key','批次备注':'manual'}}
    client.list_records.return_value=[row]
    with pytest.raises(SourceConflict,match='不同内容'):_find_remote_create(client,info,{key:'stable-key','批次备注':'local'})
    client.list_records.return_value=[row,{**row,'record_id':'duplicate'}]
    with pytest.raises(SourceConflict,match='重复'):_find_remote_create(client,info,{key:'stable-key'})

def test_batch_requires_its_own_stable_identifier(table):
    info,key=table
    with pytest.raises(SourceConflict,match='唯一'):_find_remote_create(Mock(),info,{'物料品类':'not-an-identity'})
