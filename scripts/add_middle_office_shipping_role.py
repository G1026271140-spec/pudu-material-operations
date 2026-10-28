"""Add 中台 to the existing Feishu permission field without changing user grants.

Dry run by default. With --apply, preserve source options, update the one local
field definition and the tracked schema snapshot. Uses the VM application identity.
"""
from pathlib import Path
import argparse,copy,json,os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

TABLE='tblytA4DHQVbJiIJ'
ROLE='中台'

def migrate(client,conn,registry,apply=False,update_local=True):
    from psycopg.types.json import Jsonb
    current=next(f for f in client.list_fields(TABLE) if f['field_name']=='角色')
    assert current['type']==4,'Role field must remain multiple-select'
    local=conn.execute('SELECT definition FROM material_meta.fields WHERE table_id=%s AND field_id=%s',(TABLE,current['field_id'])).fetchone()
    assert local and local[0]['field_name']=='角色' and local[0]['type']==4
    before=copy.deepcopy(current.get('property') or {})
    options=before['options']
    assert {'管理员','销售','区域市场经理','HR'} <= {o['name'] for o in options}
    snapshot=json.loads(registry.read_text())
    table=next(t for t in snapshot['tables'] if t['table_id']==TABLE)
    field=next(f for f in table['fields'] if f['field_id']==current['field_id'])
    assert field['type']==4 and field['field_name']=='角色'
    result={'table_id':TABLE,'field_id':current['field_id'],'roles_before':[o['name'] for o in options],'role':ROLE,'apply':apply}
    if not apply:return result
    if ROLE not in {o['name'] for o in options}:
        prop=copy.deepcopy(before);prop['options'].append({'name':ROLE,'color':4})
        payload={'field_name':current['field_name'],'type':current['type'],'property':prop}
        if current.get('description') is not None:payload['description']=current['description']
        client._request('PUT',f'/bitable/v1/apps/{client._quoted_app_token()}/tables/{TABLE}/fields/{current["field_id"]}',payload=payload)
    after=next(f for f in client.list_fields(TABLE) if f['field_id']==current['field_id'])
    assert after['type']==4 and after['field_name']=='角色'
    assert after['property']['options'][:len(options)]==options,'Existing options changed'
    assert ROLE in {o['name'] for o in after['property']['options']}
    updated=copy.deepcopy(field);updated.update(after)
    if update_local:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-reconciliation',0))")
            conn.execute('UPDATE material_meta.fields SET definition=%s WHERE table_id=%s AND field_id=%s',(Jsonb(updated),TABLE,current['field_id']))
    field.clear();field.update(updated)
    temporary=registry.with_suffix('.json.next')
    temporary.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(registry)
    result['roles_after']=[o['name'] for o in after['property']['options']]
    result['existing_options_preserved']=True
    result['user_grants_changed']=False
    result['local_metadata_updated']=update_local
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--source-only',action='store_true',help='Register local metadata separately as the schema owner')
    parser.add_argument('--dsn',default=os.environ.get('PUDU_DATABASE_DSN','dbname=pudu_materials'))
    parser.add_argument('--registry',type=Path,default=Path(__file__).resolve().parents[1]/'config/feishu_field_registry.json')
    args=parser.parse_args()
    import app,psycopg
    client=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    with psycopg.connect(args.dsn,autocommit=True) as conn:
        print(json.dumps(migrate(client,conn,args.registry,args.apply,not args.source_only),ensure_ascii=False))

if __name__=='__main__':main()
