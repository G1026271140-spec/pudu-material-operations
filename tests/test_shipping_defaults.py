from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4
from unittest.mock import Mock
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

import app,backend_runtime as runtime
from material_store import shipping_defaults as defaults,repository as repo,media,auto_shipping as auto,task_monitor
from material_store.client import DatabaseWriteClient
from test_shipping_calendar import store
from test_auto_shipping import auto_store,drain,fields
from test_approval_sync import graph
from material_store import effects


def test_new_ordinary_requests_save_defaults_atomically_in_the_same_outbox(store):
    conn=store;info=repo.named_table(conn,app.REQUEST_TABLE_NAME)
    client=DatabaseWriteClient(conn)
    one=client.batch_create_records(info['table_id'],[{'申请单号':'PLACEHOLDER-'+uuid4().hex,'申请类型':'普通物料申请'}])[0]
    two=client.batch_create_records(info['table_id'],[{'申请单号':'PLACEHOLDER-'+uuid4().hex,'申请类型':'普通物料申请'}])[0]
    for row in [one,two]:
        assert row['fields'][defaults.TEXT]=='待补充'
        image=row['fields'][defaults.IMAGES][0]
        assert image['name']==defaults.FILENAME and image['local_media_id']==defaults.asset()[2]
        assert media.load_image(image['local_media_id'],conn=conn)['path'].is_file()
        patch=conn.execute("SELECT patch FROM material_ops.outbox WHERE record_key=%s AND operation='create'",(row['record_id'],)).fetchone()[0]
        named=repo.feishu_record(info,{'record_id':row['record_id'],'fields':patch})['fields']
        assert named[defaults.TEXT]=='待补充' and named[defaults.IMAGES]==row['fields'][defaults.IMAGES]
    assert conn.execute('SELECT count(*) FROM material_ops.media WHERE id=%s',(defaults.asset()[2],)).fetchone()[0]==1
    before=conn.execute('SELECT count(*) FROM material_ops.outbox').fetchone()[0]
    with pytest.raises(RuntimeError,match='rollback'):
        with conn.transaction():
            client.batch_create_records(info['table_id'],[{'申请单号':'ROLLBACK-'+uuid4().hex,'申请类型':'普通物料申请'}])
            raise RuntimeError('rollback')
    assert conn.execute('SELECT count(*) FROM material_ops.outbox').fetchone()[0]==before


def test_existing_real_fields_and_other_request_types_are_preserved(store):
    conn=store;info=repo.named_table(conn,app.REQUEST_TABLE_NAME);client=DatabaseWriteClient(conn)
    real={defaults.TEXT:'DHL 123',defaults.IMAGES:[{'file_token':'real_photo','name':'实际发货.jpg'}]}
    row=client.batch_create_records(info['table_id'],[{'申请单号':uuid4().hex,'申请类型':'普通物料申请',**real}])[0]
    assert all(row['fields'][key]==value for key,value in real.items())
    row=client.batch_create_records(info['table_id'],[{'申请单号':uuid4().hex,'申请类型':'文化周边申请'}])[0]
    assert defaults.TEXT not in row['fields'] and defaults.IMAGES not in row['fields']


def test_shared_sample_uploads_once_and_remains_excluded_after_feishu_token_roundtrip(store,monkeypatch):
    conn=store
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(media,'connection',same)
    image=defaults.ensure_image(conn);remote=Mock();remote.upload_media.return_value='placeholder_token'
    assert media.remote_token(image['local_media_id'],remote)=='placeholder_token'
    assert media.remote_token(image['local_media_id'],remote)=='placeholder_token'
    remote.upload_media.assert_called_once()
    assert auto.image_keys(conn,[image])==[]
    assert auto.image_keys(conn,[{'file_token':'placeholder_token','name':'name_changed_by_feishu'}])==[]
    assert auto.image_keys(conn,[{'file_token':'actual_photo'},{'file_token':'placeholder_token'}])==['actual_photo']


def test_placeholders_do_not_notify_but_real_logistics_still_does(auto_store):
    conn,info,_,key,number,remote=auto_store
    image=defaults.ensure_image(conn)
    conn.execute('UPDATE material_ops.media SET feishu_file_token=%s WHERE id=%s',('placeholder_token',image['local_media_id']))
    source=deepcopy(remote.rows[info['table_id']][key])
    source['fields'].update({defaults.TEXT:'待补充',defaults.IMAGES:[{'file_token':'placeholder_token','name':defaults.FILENAME}]})
    remote.rows[info['table_id']][key]=source;repo.insert_source_records(conn,info,[source]);auto.stage(conn,key)
    first=auto.process_one(key,remote)
    assert first['state']=='waiting_information'
    assert fields(auto_store)['是否发货'] is True
    assert auto.document(conn,key)['effect_id'] is None
    drain(remote)
    assert effects.run_once({'primary':remote}) is None and remote.sent==[]
    # Replace only the placeholder text; a real tracking note is sufficient.
    source=deepcopy(remote.rows[info['table_id']][key]);source['fields'][defaults.TEXT]='DHL 123456'
    remote.rows[info['table_id']][key]=source;repo.insert_source_records(conn,info,[source]);auto.stage(conn,key)
    assert auto.process_one(key,remote)['state']=='queued'
    drain(remote)
    assert effects.run_once({'primary':remote})['state']=='done' and len(remote.sent)==1


def test_scheduled_contacts_do_not_use_continuous_worker_expiry(store):
    conn=store
    for name in ['worker:contacts','worker:business:ordinary']:
        conn.execute("INSERT INTO material_ops.documents(name,payload,updated_at) VALUES (%s,%s,now()-interval '1 day') ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",(name,Jsonb({'version':'V4.0.3'})))
    workers={row['name']:row for row in task_monitor.list_tasks(conn)['workers']}
    assert workers['worker:contacts']['mode']=='scheduled' and workers['worker:contacts']['healthy'] is None
    assert workers['worker:business:ordinary']['mode']=='continuous' and workers['worker:business:ordinary']['healthy'] is False
