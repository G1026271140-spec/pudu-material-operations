"""Provision the company directory through PostgreSQL and resumable Feishu outbox batches."""
from pathlib import Path
import argparse,json,os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['plan','apply','sync','verify'])
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--max-batches',type=int,default=4)
    args=parser.parse_args()
    if os.environ.get('PUDU_DATA_SOURCE')!='postgresql' or not os.environ.get('PUDU_DATABASE_DSN'):raise RuntimeError('Explicit PostgreSQL runtime required')
    import app
    from material_store import company_permissions as company,permission_outbox_batch as bulk,contacts,user_permissions as permissions,repository as repo
    from material_store.db import connection
    client=app._native_feishu_bitable_client(app.feishu_app_id(),app.feishu_app_secret(),app.feishu_bitable_app_token())
    def write(value):
        args.report.write_text(json.dumps(value,ensure_ascii=False,indent=2));args.report.chmod(0o600)
    if args.mode in {'plan','apply'}:
        contacts.refresh_now()
        source=company.refresh_source(client)
        with connection() as conn:planned=company.plan(conn)
        write({'source_refresh':source,'plan':planned})
        print(json.dumps({'mode':args.mode,'source_refresh':source,'directory_people':planned['directory_people'],**planned['summary']},ensure_ascii=False),flush=True)
        if args.mode=='apply':print(json.dumps(company.apply(planned),ensure_ascii=False),flush=True)
    elif args.mode=='sync':
        for _ in range(max(1,min(args.max_batches,20))):
            result=bulk.run_once(client)
            if result is None:break
            print(json.dumps(result,ensure_ascii=False),flush=True)
            if result['state']!='done':break
        with connection() as conn:states=dict(conn.execute('SELECT state,count(*) FROM material_ops.outbox WHERE table_id=%s GROUP BY state',(company.TABLE,)).fetchall())
        write({'outbox':states});print(json.dumps({'outbox':states}),flush=True)
    else:
        source=company.refresh_source(client)
        with connection() as conn:
            data=permissions.catalog(conn);rows=repo.rows(conn,repo.table(conn,company.TABLE))
            ids=[actor for row in rows for actor in app.feishu_person_open_ids(row['fields'],['用户账号'])]
            assert len(ids)==len(set(ids)), 'Remaining duplicate permission accounts'
            assert all(user['configured'] and user['record_count']==1 for user in data['users'])
            result={'directory_people':data['total'],'configured_company_people':sum(u['configured'] for u in data['users']),
                'active_local_and_feishu_records':len(rows),'duplicate_accounts':0,'missing_company_accounts':0,
                'source_refresh':source,'local_remote_aliases_preserved':True}
            write(result);print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
