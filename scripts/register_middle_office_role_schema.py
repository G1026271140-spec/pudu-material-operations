"""Register the reviewed middle-office role definition as the database schema owner."""
from pathlib import Path
import argparse,json,re,subprocess

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsn',required=True)
    parser.add_argument('--psql-user',help='Run psql as the local schema owner via runuser')
    parser.add_argument('--registry',type=Path,default=Path(__file__).resolve().parents[1]/'config/feishu_field_registry.json')
    args=parser.parse_args()
    data=json.loads(args.registry.read_text())
    table=next(t for t in data['tables'] if t['table_id']=='tblytA4DHQVbJiIJ')
    field=next(f for f in table['fields'] if f['field_name']=='角色')
    assert field['type']==4 and '中台' in {o['name'] for o in field['property']['options']}
    assert re.fullmatch('fld[A-Za-z0-9]+',field['field_id'])
    command=(['runuser','-u',args.psql_user,'--'] if args.psql_user else [])+['psql','-XAt','-v','ON_ERROR_STOP=1','-d',args.dsn]
    where="table_id='tblytA4DHQVbJiIJ' AND field_id='"+field['field_id']+"'"
    old=json.loads(subprocess.check_output(command+['-c','SELECT definition FROM material_meta.fields WHERE '+where],text=True))
    assert old['type']==4 and old['field_name']=='角色'
    assert all(option in field['property']['options'] for option in old['property']['options']),'Existing options cannot be removed or changed'
    def literal(value):return "'"+json.dumps(value,ensure_ascii=False).replace("'","''")+"'::jsonb"
    statement="BEGIN; SELECT pg_advisory_xact_lock(hashtextextended('pudu-reconciliation',0)); UPDATE material_meta.fields SET definition="+literal(field)+" WHERE "+where+" AND definition="+literal(old)+" RETURNING field_id; COMMIT;"
    output=subprocess.check_output(command,input=statement,text=True)
    assert field['field_id'] in output,'Metadata changed concurrently; retry after inspection'
    print(json.dumps({'registered':'中台','existing_options_preserved':True,'user_grants_changed':False},ensure_ascii=False))

if __name__=='__main__':main()
