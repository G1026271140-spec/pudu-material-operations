from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

import backend_runtime as runtime


def test_request_context_never_leaks_between_people():
    def person(identity):
        with runtime.request_scope({'lang':'en'}):
            assert not runtime.request_state
            runtime.request_state['identity']=identity
            return runtime.request_state['identity'], dict(runtime.request_query)
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(person,['a','b','c'])) == [(x,{'lang':'en'}) for x in ['a','b','c']]


def test_nested_scopes_cleanup_on_error():
    with runtime.request_scope():
        runtime.request_state['outer']=1
        try:
            with runtime.request_scope():
                runtime.request_state['inner']=1
                raise ValueError('test')
        except ValueError: pass
        assert dict(runtime.request_state)=={'outer':1}
    with runtime.request_scope(): assert not runtime.request_state


def test_data_cache_copies_and_clears(monkeypatch):
    monkeypatch.delenv('PUDU_REALTIME_READS',raising=False)
    calls=[]
    @runtime.cache_data(ttl=30)
    def data(x): calls.append(x);return {'value':[x]}
    data(1)['value'].append(2)
    assert data(1)=={'value':[1]}
    assert calls==[1]
    data.clear();data(1)
    assert calls==[1,1]


def test_realtime_disables_data_cache_not_resource_identity(monkeypatch):
    monkeypatch.setenv('PUDU_REALTIME_READS','1')
    calls=[]
    @runtime.cache_data
    def data(): calls.append(1);return len(calls)
    @runtime.cache_resource
    def client(): return object()
    assert data()==1 and data()==2
    assert client() is client()


def test_cache_errors_are_not_saved(monkeypatch):
    monkeypatch.delenv('PUDU_REALTIME_READS',raising=False)
    calls=[]
    @runtime.cache_data
    def data():
        calls.append(1)
        if len(calls)==1: raise ValueError('test')
        return 2
    try: data()
    except ValueError: pass
    assert data()==2


def test_api_and_worker_import_without_retired_framework():
    code='''
import importlib.abc,sys
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] == 'streamlit': raise AssertionError('Removed UI dependency imported')
sys.meta_path.insert(0,Deny())
import app,request_web.api,shipping_page
from scripts import submission_worker,feishu_card_worker
assert 'streamlit' not in sys.modules
'''
    subprocess.run([sys.executable,'-c',code],check=True,capture_output=True,text=True,timeout=30)
