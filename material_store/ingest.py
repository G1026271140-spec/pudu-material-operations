"""Initial application-identity import. No business records leave the VM."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import time

from psycopg import sql
from psycopg.types.json import Jsonb

from . import repository as repo


def checksum(records):
    value = sorted(records, key=lambda r:r["record_id"])
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode()).hexdigest()


def initial_import(conn, clients, directory_loader, *, progress=None):
    metadata = [repo.table(conn, row[0]) for row in conn.execute("SELECT table_id FROM material_meta.tables ORDER BY source_key,table_id")]
    started = time.monotonic()
    run_id = conn.execute("INSERT INTO material_ops.import_runs(state) VALUES ('running') RETURNING id").fetchone()[0]
    def fetch(info):
        client = clients[info["source"]]
        fields = client.list_fields(info["table_id"])
        expected = {(f["field_id"],f["field_name"],int(f["type"])) for f in info["fields"]}
        actual = {(f["field_id"],f["field_name"],int(f["type"])) for f in fields}
        if expected != actual:
            raise ValueError("来源字段已变化，需先更新映射：" + info["name"])
        result=client.list_records(info["table_id"])
        if len({r.get("record_id") or r.get("id") for r in result})!=len(result):
            raise ValueError("来源返回重复记录 ID：" + info["name"])
        if progress:progress({"table_id":info["table_id"],"records":len(result),"stage":"fetched"})
        return info,result
    try:
        # Fetch fully before opening the import transaction. Pagination failures
        # cannot become a successful partial snapshot.
        with ThreadPoolExecutor(max_workers=3) as workers:
            future = workers.submit(directory_loader)
            fetched = list(workers.map(fetch, metadata))
            directory = future.result()
        summary={"tables":[],"records":0,"users":len(directory.get("users",[])),"departments":len(directory.get("departments",[]))}
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-initial-import',0))")
            for info, records in fetched:
                if conn.execute(sql.SQL("SELECT EXISTS(SELECT 1 FROM material_data.{} WHERE _sync_state<>'synced' OR _local_version<>_synced_version)")
                                .format(sql.Identifier(info["sql_table"]))).fetchone()[0]:
                    raise ValueError("本地存在未同步修改，初始导入拒绝覆盖。")
                repo.insert_source_records(conn,info,records)
                actual=repo.rows(conn,info)
                # Source records may contain server metadata outside 'fields'.
                canonical=[{"record_id":r.get("record_id") or r.get("id"),"fields":r.get("fields") or {}} for r in records]
                source_hash=checksum(canonical)
                if len(actual)!=len(records) or checksum(actual)!=source_hash:
                    raise ValueError("数据库记录数量或内容校验失败：" + info["name"])
                summary["tables"].append({"table_id":info["table_id"],"source":info["source"],"name":info["name"],"count":len(records),"sha256":source_hash})
                summary["records"]+=len(records)
            # Record any pre-existing dangling references without deleting history.
            known={info["table_id"]:{r.get("record_id") or r.get("id") for r in records} for info,records in fetched}
            orphaned=[]
            for info,records in fetched:
                for field in info["fields"]:
                    target=(field.get("property") or {}).get("table_id")
                    if int(field["type"]) not in {18,21} or target not in known:continue
                    missing=sum(1 for r in records for rid in repo.link_ids((r.get("fields") or {}).get(field["field_name"])) if rid and rid not in known[target])
                    if missing:orphaned.append({"table_id":info["table_id"],"field_id":field["field_id"],"missing_references":missing})
            summary["historical_missing_links"]=orphaned
            summary["seconds"]=round(time.monotonic()-started,3)
            conn.execute("INSERT INTO material_ops.documents(name,payload) VALUES ('contact_departments_cache.json',%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=now()",(Jsonb(directory),))
            conn.execute("UPDATE material_ops.import_runs SET state='done',completed_at=now(),summary=%s WHERE id=%s",(Jsonb(summary),run_id))
        return summary
    except Exception as exc:
        conn.execute("UPDATE material_ops.import_runs SET state='failed',completed_at=now(),summary=%s WHERE id=%s",(Jsonb({"error_type":type(exc).__name__}),run_id))
        raise
