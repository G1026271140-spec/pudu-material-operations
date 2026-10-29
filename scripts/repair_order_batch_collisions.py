"""Run from the VM release after tests. Default is preview; --apply repairs only verified local collisions."""
import argparse,os,sys,json
from pathlib import Path
from datetime import datetime,timezone
root=Path('/home/gaohongyuan1/pudu-materials-operation')
sys.path.insert(0,str(root/'source'))
os.environ.update(PUDU_DATA_SOURCE='postgresql',PUDU_DATABASE_DSN='dbname=pudu_materials',PUDU_SECRETS_FILE=str(root/'shared/config/secrets.toml'))
import psycopg,app
from feishu_bitable import FeishuBitableClient,FeishuBitableConfig
from material_store import repository as repo,order_recovery as recovery

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    client=FeishuBitableClient(FeishuBitableConfig(app_id=app.feishu_app_id(),app_secret=app.feishu_app_secret(),app_token=app.feishu_bitable_app_token()))
    with psycopg.connect('dbname=pudu_materials',autocommit=True) as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            info=repo.named_table(conn,'物料下单批次')
        remote=client.list_records(info['table_id'])
        with conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            plans=recovery.plan(conn,remote)
            backup=[{'row':repo.raw_record(conn,info,p['record_key'],include_deleted=True),
                'outbox':conn.execute('SELECT to_jsonb(o) FROM material_ops.outbox o WHERE id=%s',(p['outbox_id'],)).fetchone()[0]} for p in plans]
        receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'release':app.APP_VERSION,'plans':plans,'before':backup,'applied':False}
        path=root/'shared/audits'/('order-recovery-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
        path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2,default=str));path.chmod(0o600)
        if args.apply:
            assert app.APP_VERSION!='V4.0.5','Deploy the tested fix first'
            count=recovery.apply(conn,plans);receipt.update(applied=True,count=count)
            path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2,default=str))
        print(json.dumps({'version':app.APP_VERSION,'applied':receipt['applied'],'planned_batches':len(plans),'changes':[{'old':p['old_number'],'new':p['new_number']} for p in plans],'receipt':str(path)},ensure_ascii=False))

if __name__=='__main__':main()
