from unittest.mock import Mock
import pytest
import app

@pytest.mark.parametrize('sources,reason',[
    (['line-a','line-other'],'相同品类'),
    (['line-a','missing'],'来源明细'),
    (['line-a','line-a'],'来源明细'),
])
def test_entire_category_split_rejects_cross_category_missing_or_duplicate_sources(monkeypatch,sources,reason):
    context={'request':{'request_no':'REQ-ISOLATED','inventory_review_version':0},'lines':[
        {'record_id':'line-a','product':'折页','material_record_id':'a','quantity':10},
        {'record_id':'line-b','product':'折页','material_record_id':'b','quantity':20},
        {'record_id':'line-other','product':'礼品','material_record_id':'other','quantity':3}],
        'material_rows':[{'record_id':'c','fields':{'物料品类':'折页','产品型号':'新型号','语种':'英语','当前库存':100}}]}
    monkeypatch.setattr(app,'request_inventory_review_context',lambda **k:context)
    writer=Mock();monkeypatch.setattr(app,'feishu_batch_update_record_fields',writer)
    with pytest.raises(RuntimeError,match=reason):app.execute_request_inventory_edit({'request_id':'REQ','expected_version':0,'change_note':'品类整组分装',
        'lines':[{'material_record_id':'c','quantity':30,'split_source_line_id':'line-a','split_source_line_ids':sources}]})
    writer.assert_not_called()
