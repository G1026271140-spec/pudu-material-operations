from pathlib import Path
import argparse,json,os,sys,subprocess
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from material_store.pending_followup_schema import NAMES,extend,register_sql


def main():
    parser=argparse.ArgumentParser(description='Preview by default; add text fields or register projections only with explicit flags.')
    parser.add_argument('--apply',action='store_true');parser.add_argument('--register',action='store_true')
    parser.add_argument('--dsn',default='pudu_materials');parser.add_argument('--psql-user',default='postgres')
    args=parser.parse_args()
    path=ROOT/'config/feishu_field_registry.json';snapshot=json.loads(path.read_text())
    table=next(t for t in snapshot['tables'] if t.get('source','primary')=='primary' and t['table_name']=='物料申请单')
    if args.register:
        result,table,fields=extend(snapshot,table['fields'])
        if not args.apply:print(register_sql(table,fields));return
        command=['runuser','-u',args.psql_user,'--','psql','-X','-v','ON_ERROR_STOP=1','-d',args.dsn]
        subprocess.run(command,input=register_sql(table,fields),text=True,check=True,capture_output=True)
        print(json.dumps({'registered':[f['field_name'] for f in fields],'business_records_changed':0},ensure_ascii=False));return
    import app
    from feishu_bitable import FeishuBitableClient,FeishuBitableConfig
    client=FeishuBitableClient(FeishuBitableConfig(app_id=app.feishu_app_id(),app_secret=app.feishu_app_secret(),app_token=app.feishu_bitable_app_token()))
    live=client.list_fields(table['table_id']);missing=[name for name in NAMES if not any(f['field_name']==name for f in live)]
    if not args.apply:print(json.dumps({'add_text_fields':missing},ensure_ascii=False));return
    backup=Path(os.environ['PUDU_SCHEMA_AUDIT_DIR']);backup.mkdir(exist_ok=True,parents=True)
    receipt=backup/'pending-followup-registry-before.json'
    if not receipt.exists():receipt.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2));receipt.chmod(0o600)
    for name in missing:client.create_field(table['table_id'],name,1)
    latest=client.list_fields(table['table_id'])
    old={f['field_id']:(f['field_name'],f['type']) for f in live}
    assert all(any(f['field_id']==key and (f['field_name'],f['type'])==value for f in latest) for key,value in old.items())
    result,_,fields=extend(snapshot,latest)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'fields':[{'name':f['field_name'],'field_id':f['field_id']} for f in fields],'existing_fields_preserved':True,'business_records_changed':0},ensure_ascii=False))


if __name__=='__main__':main()
