from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
import importlib
import pytest
from fastapi.testclient import TestClient
from material_store import cultural_access as access


@pytest.fixture
def directory():
    return {'departments':[{'department_id':'od_market','name':'市场营销部'},
            {'department_id':'od_dream','name':'Dream组'},{'department_id':'od_brand','name':'品牌部'},{'department_id':'od_sales','name':'销售部'},
            {'department_id':'od_fake','name':'市场营销部支持组'}],
            'users':[{'open_id':'ou_market','department_ids':['od_market']},
            {'open_id':'ou_dream','department_ids':['od_sales','od_dream']},{'open_id':'ou_brand','department_ids':['od_brand']},
            {'open_id':'ou_sales','department_ids':['od_sales'],'department_paths':['市场营销部']},
            {'open_id':'ou_fake','department_ids':['od_fake']}]}


def test_only_exact_department_membership_allows_jacket(directory):
    assert access.eligible_people(directory)=={'ou_market','ou_dream','ou_brand'}
    for actor in ('ou_market','ou_dream','ou_brand'):
        access.validate({'requester_open_id':actor,'submitter_open_id':actor},[{'product':'文化夹克','quantity':1}],directory=directory)
    for actor in ('ou_sales','ou_fake','ou_missing',''):
        with pytest.raises(ValueError,match='市场营销部、Dream组或品牌部'):
            access.validate({'requester_open_id':actor,'submitter_open_id':actor,'department':'市场营销部','roles':['管理员']},[{'product':'文化夹克','quantity':1}],directory=directory)


def test_both_actual_submitter_and_applicant_must_be_eligible_and_other_items_unchanged(directory):
    for requester,submitter in [('ou_sales','ou_market'),('ou_market','ou_sales')]:
        with pytest.raises(ValueError):access.validate({'requester_open_id':requester,'submitter_open_id':submitter},[{'product':'休闲商务夹克-黑色（长袖）','quantity':1}],directory=directory)
    access.validate({'requester_open_id':'ou_sales'},[{'product':'文化POLO衫','quantity':1}],directory={})


@pytest.mark.parametrize('viewer,visible',[('ou_market',True),('ou_dream',True),('ou_brand',True),('ou_sales',False),('',False)])
def test_catalog_hides_cards_metadata_and_images_from_other_departments(monkeypatch,directory,viewer,visible):
    web=importlib.import_module('request_web.api')
    page={'tables':{'物料品类':[{'record_id':p,'fields':{'物料品类':p,'品类定义':'文化周边','是否在申领页显示':'是'}} for p in ['文化夹克','文化POLO衫']],
          '产品型号':[],'文化周边管理库存':[{'record_id':p+'-item','fields':{'物料品类':p,'产品型号':'M','战区管理':'总部','当前库存':5,'是否可以申领':'是'}} for p in ['文化夹克','文化POLO衫']]}}
    monkeypatch.setattr(web,'_json',lambda name:directory if name=='contact_departments_cache.json' else page)
    monkeypatch.setattr(web,'_image_index',lambda:{'文化夹克':['jacket-image'],'文化POLO衫':['polo-image']})
    monkeypatch.setattr(web,'_authenticated_submitter',lambda request:('test',viewer))
    data=TestClient(web.api).get('/api/cultural-catalog',cookies={'pudu_feishu':'isolated-cookie'}).json()
    assert ('文化夹克' in [r['product'] for r in data['combinations']]) is visible
    assert ('文化夹克' in data['categoryLabels']) is visible and ('文化夹克' in data['images']) is visible
    assert any(r['product']=='文化POLO衫' for r in data['combinations'])


def test_forged_http_submit_is_rejected_before_queue_or_stock_write(monkeypatch,directory):
    web=importlib.import_module('request_web.api')
    monkeypatch.setattr(web,'_authenticated_submitter',lambda request:('test','ou_sales'))
    monkeypatch.setattr(web,'_json',lambda name:directory)
    monkeypatch.setattr(web,'_enqueue_fast',lambda *a:pytest.fail('Ineligible jacket entered queue'))
    from material_store import submissions
    monkeypatch.setattr(submissions,'submit_groups',lambda **kw:pytest.fail('Ineligible jacket reached business writer'))
    body={'requester':'test','requester_open_id':'ou_market','department':'市场营销部','department_id':'od_market',
          'submission_token':uuid4().hex,'material_usage':'test','lines':[{'product':'文化夹克','model':'M','region':'总部','quantity':1}]}
    response=TestClient(web.api).post('/api/cultural-submit',json=body)
    assert response.status_code==403 and 'Dream组' in response.json()['detail']


def test_postgres_writer_revalidates_directory_before_stock_or_quota(conn,monkeypatch,directory):
    import app,backend_runtime as runtime
    from psycopg.types.json import Jsonb
    from material_store import submissions
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(submissions,'connection',same)
    monkeypatch.setattr(app,'find_completed_submission',lambda token:None)
    monkeypatch.setattr(app,'cultural_request_quota_snapshot',lambda *a:pytest.fail('Ineligible jacket reached quota writer'))
    with pytest.raises(RuntimeError,match='rollback'):
      with conn.transaction(),runtime.request_scope():
          conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES ('contact_departments_cache.json',%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",(Jsonb(directory),))
          before=conn.execute('SELECT count(*) FROM material_ops.outbox').fetchone()[0]
          with pytest.raises(ValueError,match='市场营销部、Dream组或品牌部'):
              submissions.submit_groups(cultural=({'submission_token':uuid4().hex,'requester_open_id':'ou_sales','submitter_open_id':'ou_sales'},[{'product':'文化夹克','model':'M','region':'总部','quantity':1}]))
          assert conn.execute('SELECT count(*) FROM material_ops.outbox').fetchone()[0]==before
          raise RuntimeError('rollback')


from test_postgres_jobs import conn
