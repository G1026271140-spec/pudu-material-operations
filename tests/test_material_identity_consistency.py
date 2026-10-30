from uuid import uuid4
from unittest.mock import Mock
import pytest
import app,backend_runtime as runtime
from test_shipping_calendar import store
from test_account_tools import account_store
from material_store import repository as repo,submissions


@pytest.mark.parametrize('role',['管理员','区域市场经理'])
def test_hidden_spec_available_to_both_authorized_full_catalog_roles(account_store,monkeypatch,role):
    conn,ids=account_store
    from contextlib import contextmanager
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(submissions,'connection',same)
    category=repo.named_table(conn,app.CATEGORY_TABLE_NAME);stock=repo.named_table(conn,app.MATERIAL_TABLE_NAME)
    name='冰箱贴隔离'+uuid4().hex
    repo.insert_source_records(conn,category,[{'record_id':'rec_'+uuid4().hex,'fields':{'物料品类':name+'( Fridge Magnet)',app.REQUEST_PAGE_VISIBILITY_FIELD:'是','启用状态':'启用'}}])
    mid='rec_'+uuid4().hex
    repo.insert_source_records(conn,stock,[{'record_id':mid,'fields':{'物料编码':'MAT-test-'+uuid4().hex,'物料品类':name+'( Fridge Magnet)','产品型号':'ET1','语种':'无需语种','当前库存':150,app.REQUEST_PAGE_VISIBILITY_FIELD:'否','启用状态':'启用'}}])
    payload={'requester':'隔离申请人','requester_open_id':ids['admin'],'submitter':'隔离提交人','submitter_open_id':ids['admin'],
             'department':'测试部门','material_usage':'隔离验收','submission_token':'combo-'+uuid4().hex,'accepted_roles':[role]}
    lines=[{'product':name+'（Fridge Magnet）','model':'ET1','language':'无需语种','quantity':1}]
    result=submissions.submit_groups((payload,lines))
    assert result[0]['created'] and result[0]['line_count']==1
    assert not submissions.submit_groups((payload,lines))[0]['created']
    lineinfo=repo.named_table(conn,app.REQUEST_LINE_TABLE_NAME)
    saved=next(r for r in repo.rows(conn,lineinfo) if r['fields'].get('明细编号')==result[0]['request_no']+'-01')
    assert any(mid in repo.link_ids(v) for v in saved['fields'].values())
    assert repo.feishu_record(stock,repo.raw_record(conn,stock,mid))['fields']['当前库存']==150
    # A genuinely unauthorized sales request stays blocked with an accurate reason.
    with pytest.raises(RuntimeError,match='仅对已启用的管理员或区域市场经理开放'):
        submissions.submit_groups(({**payload,'submission_token':'blocked-'+uuid4().hex,'accepted_roles':['销售']},lines))


def test_legacy_stock_lookup_normalizes_category_but_preserves_model_language(monkeypatch):
    rows=[{'record_id':'rec_magnet','fields':{'物料品类':'冰箱贴( Fridge Magnet)','产品型号':'ET1','语种':'无需语种','当前库存':150}}]
    monkeypatch.setattr(app,'feishu_rows',lambda table:rows)
    assert app.find_feishu_material_record('冰箱贴（Fridge Magnet）','ET1','无需语种')['record_id']=='rec_magnet'
    assert app.find_feishu_material_record('冰箱贴(Fridge Magnet)','ET1','英语(English)') is None
    assert app.find_feishu_material_record('冰箱贴(Fridge Magnet)','ET2','无需语种') is None
    rows.append({'record_id':'rec_duplicate','fields':dict(rows[0]['fields'])})
    with pytest.raises(RuntimeError,match='重复物料规格'):app.feishu_inventory_index()


def test_catalog_permission_union_does_not_drop_enabled_admin_on_later_sales_row(monkeypatch):
    import importlib
    web=importlib.import_module('request_web.api')
    rows=[{'fields':{'用户账号':[{'id':'ou_duplicate'}],'角色':roles,'是否启用':enabled}}
          for roles,enabled in [(['管理员'],'是'),(['销售'],'是'),(['HR'],'否')]]
    monkeypatch.setattr(runtime,'realtime_reads',lambda:False)
    monkeypatch.setattr(web,'_json',lambda name:{'products':[],'inventory_rows':[]} if name=='request_form_cache.json' else {'users':[],'departments':[]} if name=='contact_departments_cache.json' else {'tables':{app.USER_PERMISSION_TABLE_NAME:rows}})
    monkeypatch.setattr(web,'_image_index',lambda:{})
    monkeypatch.setattr(web,'_model_index',lambda:{})
    assert set(web.build_catalog()['rolesByUser']['ou_duplicate'])=={'管理员','销售'}


def test_requester_role_checks_union_of_all_enabled_records(monkeypatch):
    rows=[{'fields':{'用户账号':[{'id':'ou_duplicate'}],'角色':roles,'是否启用':enabled}}
          for roles,enabled in [(['销售'],'是'),(['管理员'],'是'),(['HR'],'否')]]
    monkeypatch.setattr(app,'fresh_feishu_rows',lambda table:rows)
    assert app.requester_has_enabled_role('ou_duplicate','管理员')
    assert not app.requester_has_enabled_role('ou_duplicate','HR')
