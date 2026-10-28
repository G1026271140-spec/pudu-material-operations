from unittest.mock import Mock
import copy,json
import pytest
from material_store import outbox_worker as worker
from material_store.task_result_card import card

def info():return {'source':'primary','name':'申请物料变更记录表','table_id':'tbl_audit',
    'fields':[{'field_id':'fld_'+name,'field_name':name,'type':kind} for name,kind in [('文本',1),('申请单号',1),('变更版本',2),('变更说明',1)]]}

def test_request_change_log_create_can_find_same_version_after_unknown_result():
    fields={'文本':'REQ-ISOLATED-V1','申请单号':'REQ-ISOLATED','变更版本':1,'变更说明':'整组配货'}
    source=Mock();source.list_records.return_value=[]
    assert worker._find_remote_create(source,info(),fields) is None
    existing={'record_id':'rec_audit','fields':copy.deepcopy(fields)}
    source.list_records.return_value=[existing]
    assert worker._find_remote_create(source,info(),fields)==existing
    source.batch_create_records.assert_not_called()
    different={**fields,'变更说明':'另一次修改'}
    with pytest.raises(worker.SourceConflict):worker._find_remote_create(source,info(),different)

def test_duplicate_change_log_versions_are_rejected():
    fields={'文本':'REQ-ISOLATED-V1','申请单号':'REQ-ISOLATED','变更版本':1}
    source=Mock();source.list_records.return_value=[{'record_id':key,'fields':fields} for key in ['one','two']]
    with pytest.raises(worker.SourceConflict):worker._find_remote_create(source,info(),fields)

def test_administrator_result_card_is_compact_and_has_no_internal_diagnostics():
    receipt=card('申请物料库存驳回','测试操作人','申请单：REQ-ISOLATED',True)
    assert receipt['schema']=='2.0' and receipt['header']['title']['content']=='物料申请已驳回'
    assert len(receipt['body']['elements'])==3
    encoded=json.dumps(receipt,ensure_ascii=False)
    assert 'REQ-ISOLATED' in encoded and '测试操作人' in encoded
    assert not any(term in encoded for term in ['JSON','任务编号','local_','deleted_line_count'])
    assert card('发货信息同步','人','申请单：REQ',False)['header']['title']['content']=='发货任务需核对'
