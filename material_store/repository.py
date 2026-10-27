"""PostgreSQL record access. Stable field IDs are canonical; SQL columns are projections."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import uuid4

from psycopg import sql
from psycopg.types.json import Jsonb

from .field_registry import JSON_TYPES, READ_ONLY_TYPES, scalar_text, typed_value, validate_patch


class VersionConflict(ValueError):
    pass


def table(conn, table_id):
    row = conn.execute("SELECT source_key,table_name,sql_table FROM material_meta.tables WHERE table_id=%s", (table_id,)).fetchone()
    if not row:
        raise ValueError("数据表不存在。")
    definitions = conn.execute("SELECT definition FROM material_meta.fields WHERE table_id=%s ORDER BY ordinal,field_id", (table_id,)).fetchall()
    return {"table_id": table_id, "source": row[0], "name": row[1], "sql_table": row[2],
            "fields": [r[0] for r in definitions]}


def named_table(conn, name, source="primary"):
    row = conn.execute("SELECT table_id FROM material_meta.tables WHERE source_key=%s AND table_name=%s", (source, name)).fetchone()
    if not row:
        raise ValueError("来源缺少数据表：" + name)
    return table(conn, row[0])


def raw_record(conn, info, record_key, *, lock=False):
    row = conn.execute(sql.SQL("SELECT _record_key,_remote_id,_fields,_local_version,_sync_state,_baseline FROM material_data.{} WHERE (_record_key=%s OR _remote_id=%s) AND NOT _deleted {}")
        .format(sql.Identifier(info["sql_table"]), sql.SQL("FOR UPDATE" if lock else "")), (record_key, record_key)).fetchone()
    if not row:
        raise ValueError("记录不存在，请刷新数据表。")
    return {"record_id": row[0], "remote_id": row[1], "fields": row[2], "version": row[3], "sync_state": row[4], "baseline": row[5]}


def feishu_record(info, row):
    return {"record_id": row["record_id"], "fields": {f["field_name"]: row["fields"][f["field_id"]]
        for f in info["fields"] if f["field_id"] in row["fields"]}}


def rows(conn, info):
    result = conn.execute(sql.SQL("SELECT _record_key,_fields FROM material_data.{} WHERE NOT _deleted ORDER BY _record_key")
                          .format(sql.Identifier(info["sql_table"]))).fetchall()
    return [feishu_record(info, {"record_id": row[0], "fields": row[1]}) for row in result]


def source_values(info, fields):
    by_name = {f["field_name"]: f["field_id"] for f in info["fields"]}
    unknown = set(fields) - set(by_name)
    if unknown:
        raise ValueError("飞书字段定义已变化，需先刷新字段注册。表：" + info["name"])
    return {by_name[name]: value for name, value in fields.items()}


def projections(info, values):
    columns, params = [], []
    for field in info["fields"]:
        value = typed_value(int(field["type"]), values.get(field["field_id"]))
        columns.append(sql.Identifier("f_" + field["field_id"]))
        params.append(Jsonb(value) if int(field["type"]) in JSON_TYPES and value is not None else value)
    return columns, params


def replace_values(conn, info, key, values, *, version=None, state=None):
    columns, params = projections(info, values)
    assignments = [sql.SQL("{}=%s").format(c) for c in columns]
    assignments.extend([sql.SQL("_fields=%s"), sql.SQL("_updated_at=now()")])
    params.append(Jsonb(values))
    if version is not None:
        assignments.append(sql.SQL("_local_version=%s")); params.append(version)
    if state:
        assignments.append(sql.SQL("_sync_state=%s")); params.append(state)
    conn.execute(sql.SQL("UPDATE material_data.{} SET {} WHERE _record_key=%s").format(
        sql.Identifier(info["sql_table"]), sql.SQL(",").join(assignments)), params + [key])


def insert_source_records(conn, info, records):
    for record in records:
        key = record.get("record_id") or record.get("id")
        if not key:
            raise ValueError("来源记录缺少稳定 ID。")
        values = source_values(info, record.get("fields") or {})
        columns, params = projections(info, values)
        conn.execute(sql.SQL("INSERT INTO material_data.{} ({}) VALUES ({}) ON CONFLICT(_record_key) DO UPDATE SET {} WHERE {}._sync_state='synced'")
            .format(sql.Identifier(info["sql_table"]),
                    sql.SQL(",").join([sql.Identifier("_record_key"), sql.Identifier("_remote_id"), sql.Identifier("_fields"), sql.Identifier("_baseline"), sql.Identifier("_source_seen_at")] + columns),
                    sql.SQL(",").join([sql.Placeholder()] * 4 + [sql.SQL("now()")] + [sql.Placeholder()] * len(params)),
                    sql.SQL(",").join([sql.SQL("{}=excluded.{}").format(c,c) for c in columns] + [sql.SQL("_fields=excluded._fields,_baseline=excluded._baseline,_source_seen_at=now()")]),
                    sql.Identifier(info["sql_table"])), [key, key, Jsonb(values), Jsonb(values)] + params)


def link_ids(value):
    if not isinstance(value, list):
        return []
    return [item if isinstance(item, str) else str(item.get("record_id") or item.get("id") or "") for item in value if isinstance(item, (str, dict))]


def number(value):
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, list):
        value = value[0] if value else 0
    try:
        result = Decimal(str(value or 0))
        if not result.is_finite():
            raise ValueError("数字必须为有限值。")
        return result
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("数字格式无效。") from exc


def recalculate(info, values):
    """Evaluate only registered arithmetic formulas; never eval arbitrary Feishu code."""
    def arithmetic(node):
        if isinstance(node, ast.Expression):return arithmetic(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int,float):return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd,ast.USub)):
            return arithmetic(node.operand) * (-1 if isinstance(node.op,ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            left, right = arithmetic(node.left), arithmetic(node.right)
            if isinstance(node.op,ast.Add):return left+right
            if isinstance(node.op,ast.Sub):return left-right
            if isinstance(node.op,ast.Mult):return left*right
            if isinstance(node.op,ast.Div):return left/right
        raise ValueError("Unsupported formula")
    result = dict(values)
    for field in info["fields"]:
        if int(field["type"]) != 20:continue
        expression = (field.get("property") or {}).get("formula_expression", "")
        pattern = r"bitable::\$table\[(tbl\w+)\]\.\$field\[(fld\w+)\]"
        refs = re.findall(pattern, expression)
        if not refs or any(t != info["table_id"] for t,_ in refs):continue
        replaced = re.sub(pattern, lambda m: "(" + str(number(result.get(m[2]))) + ")", expression)
        try:
            calculated = float(arithmetic(ast.parse(replaced, mode="eval")))
        except (ValueError,SyntaxError,ZeroDivisionError,InvalidOperation):continue
        previous = result.get(field["field_id"])
        if isinstance(previous,dict) and "value" in previous:
            result[field["field_id"]] = {**previous, "value": [calculated] if isinstance(previous["value"],list) else calculated}
        else:
            result[field["field_id"]] = calculated
    return result


WORKFLOW_TABLES = {"后台任务队列","后台任务载荷","后台任务节点列表","库存流水","申请物料变更记录表","文化周边兑换","物料下单批次","物料下单批次明细"}


def identity_source(info, field):
    names={'物料主数据':{'物料品类':'品类关联','产品型号':'型号关联','语种':'语种关联'},
           '文化周边管理库存':{'物料品类':'物料品类关联','产品型号':'产品型号关联','战区管理':'战区关联'}}
    target=names.get(info['name'],{}).get(field['field_name'])
    return next((f['field_id'] for f in info['fields'] if f['field_name']==target),None) if target else None


def edit_reason(info, field):
    name, kind = field["field_name"], int(field["type"])
    if kind in READ_ONLY_TYPES:return "公式/引用需修改来源字段；编号及系统字段自动生成。"
    if identity_source(info,field):return "请选择对应的关联字段，系统会同步更新物料维度名称。"
    if info["name"] in WORKFLOW_TABLES:return "由业务流程及任务程序维护，避免破坏处理状态与审计。"
    if info["name"] in {"物料申请单","申请明细"} and name not in {"标题","备注"}:
        return "通过申请、审批或配货流程修改此字段。"
    if info["name"] == "用户权限表" and name not in {"角色","是否启用"}:
        return "账号与额度累计通过身份及申领流程维护。"
    if info["name"] == "文化周边编码及库存数量" and info["source"] == "primary":
        return "同步副本；请切换到行政源表编辑。"
    if name in {"物料编码","文化周边编码","SourceID","创建时间","库存行数","产品型号数量","语种数量"}:
        return "稳定业务标识或系统维护字段。"
    if kind in {18,21} and (field.get('property') or {}).get('table_name') in WORKFLOW_TABLES|{'物料申请单','申请明细'}:
        return "由申请或库存流程自动建立关联，避免破坏历史记录。"
    if name.startswith('父记录'):return "系统层级关系，请在来源表中维护。"
    if kind == 17 and not (info["name"] == "物料品类" and name == "申领页图片"):
        return "附件可查看；此入口目前仅支持品类图片编辑。"
    if kind not in {1,2,3,4,5,7,11,13,15,17,18,21}:return "请通过对应业务入口维护此类型。"
    return ""


def list_tables(conn):
    result = []
    for table_id, source, name, table_sql in conn.execute("SELECT table_id,source_key,table_name,sql_table FROM material_meta.tables ORDER BY source_key,discovered_at,table_id"):
        count = conn.execute(sql.SQL("SELECT count(*) FROM material_data.{} WHERE NOT _deleted").format(sql.Identifier(table_sql))).fetchone()[0]
        result.append({"table_id":table_id,"source":source,"name":name,
                       "label":name + (" · 行政源表" if source=="apparel_admin" else ""),"count":count})
    return result


def browse(conn, table_id, *, page=0, limit=50, query="", sort_field=None, descending=False):
    info = table(conn, table_id)
    limit = max(1,min(100,int(limit)));page = max(0,int(page))
    where, params = "NOT _deleted", []
    if query:
        where += " AND _fields::text ILIKE %s"; params.append("%" + query[:300].replace("\\", "\\\\").replace("%",r"\%").replace("_",r"\_") + "%")
    order = sql.Identifier("_record_key")
    if sort_field:
        field = next((f for f in info["fields"] if f["field_id"]==sort_field),None)
        if not field:raise ValueError("排序字段不存在。")
        order = sql.Identifier("f_"+sort_field)
    count = conn.execute(sql.SQL("SELECT count(*) FROM material_data.{} WHERE {}").format(sql.Identifier(info["sql_table"]),sql.SQL(where)), params).fetchone()[0]
    result = conn.execute(sql.SQL("SELECT _record_key,_fields,_local_version,_sync_state FROM material_data.{} WHERE {} ORDER BY {} {} NULLS LAST,_record_key LIMIT %s OFFSET %s")
        .format(sql.Identifier(info["sql_table"]),sql.SQL(where),order,sql.SQL("DESC" if descending else "ASC")),params+[limit,page*limit]).fetchall()
    return {"table":{k:info[k] for k in ("table_id","source","name")},
        "fields":[{**f,"editable":not edit_reason(info,f),"read_only_reason":edit_reason(info,f),'edit_via':identity_source(info,f)} for f in info["fields"]],
        "records":[{"record_id":r[0],"fields":r[1],"version":r[2],"sync_state":r[3]} for r in result],
        "count":count,"page":page,"limit":limit}


def _save_change(conn, info, old, patch, actor, key, lane="admin"):
    request_hash=hashlib.sha256(json.dumps(patch,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    identity_links={
        '物料主数据':{'品类关联':('物料品类','物料品类'),'型号关联':('产品型号','产品型号'),'语种关联':('语种','语言种类')},
        '文化周边管理库存':{'物料品类关联':('物料品类','物料品类'),'产品型号关联':('产品型号','产品型号'),'战区关联':('战区管理','战区名称')},
    }
    patch=dict(patch)
    by_name={f['field_name']:f for f in info['fields']}
    for link_name,(label_name,target_name) in identity_links.get(info['name'],{}).items():
        link=by_name.get(link_name)
        if not link or link['field_id'] not in patch:continue
        selected=link_ids(patch[link['field_id']])
        if len(selected)>1:raise ValueError('一个物料组合只能选择一个品类、型号、语种或战区。')
        if selected:
            target=table(conn,link['property']['table_id'])
            target_row=raw_record(conn,target,selected[0])
            target_fid=next(f['field_id'] for f in target['fields'] if f['field_name']==target_name)
            patch[by_name[label_name]['field_id']]=scalar_text(target_row['fields'].get(target_fid))
    patch = {fid:value for fid,value in patch.items() if old["fields"].get(fid) != value}
    if not patch:return old
    version = old["version"]+1
    values = recalculate(info,{**old["fields"],**patch})
    replace_values(conn,info,old["record_id"],values,version=version,state="pending")
    conn.execute("INSERT INTO material_ops.outbox(idempotency_key,lane,table_id,record_key,local_version,patch,request_hash) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (key,lane,info["table_id"],old["record_id"],version,Jsonb(patch),request_hash))
    for fid,value in values.items():
        if old["fields"].get(fid) != value:
            conn.execute("INSERT INTO material_ops.audit(table_id,record_key,field_id,source,before_value,after_value,local_version,actor_open_id) VALUES (%s,%s,%s,'frontend',%s,%s,%s,%s)",
                         (info["table_id"],old["record_id"],fid,Jsonb(old["fields"].get(fid)),Jsonb(value),version,actor))
    return {**old,"fields":values,"version":version,"sync_state":"pending"}


def patch_record(conn, table_id, record_key, patch, expected_version, idempotency_key, actor):
    if not isinstance(patch,dict) or len(patch)!=1:raise ValueError("每次保存一个单元格。")
    if not actor or not isinstance(idempotency_key,str) or not 8<=len(idempotency_key)<=150:
        raise ValueError("缺少操作人或保存标识。")
    with conn.transaction():
        # Human admin edits serialize briefly; no network call occurs inside this transaction.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('pudu-database-editor',0))")
        info = table(conn,table_id)
        old = raw_record(conn,info,record_key,lock=True)
        prior = conn.execute("SELECT table_id,record_key,patch,request_hash FROM material_ops.outbox WHERE idempotency_key=%s", (idempotency_key,)).fetchone()
        if prior:
            request_hash=hashlib.sha256(json.dumps(patch,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if prior[0]!=table_id or prior[1]!=old["record_id"] or (prior[3]!=request_hash if prior[3] else prior[2]!=patch):
                raise VersionConflict("保存标识已用于其他修改。")
            return {k:old[k] for k in ("record_id","fields","version","sync_state")}
        if old["version"]!=expected_version:raise VersionConflict("此记录已被其他操作修改，请刷新后重试。")
        validate_patch(info["fields"],patch)
        field = next(f for f in info["fields"] if f["field_id"] in patch)
        reason = edit_reason(info,field)
        if reason:raise ValueError(reason)
        name, value = field["field_name"], next(iter(patch.values()))
        if int(field["type"]) in {1,13} and value is not None and (not isinstance(value,str) or len(value)>20000):raise ValueError("文本过长或格式无效。")
        if int(field["type"])==2:
            amount=number(value)
            if name in {"当前库存","在途库存","原始库存数量"} and value is None:raise ValueError("库存不能为空，请填写 0 或正整数。")
            if name in {"当前库存","在途库存","原始库存数量","系统兑换数量"} and (amount<0 or amount!=int(amount)):
                raise ValueError("库存须为非负整数。")
            if "单价" in name and amount<0:raise ValueError("单价不能为负数。")
        if int(field["type"])==11:
            directory=conn.execute("SELECT payload FROM material_ops.documents WHERE name='contact_departments_cache.json'").fetchone()
            allowed={u['open_id'] for u in (directory[0].get('users',[]) if directory else [])}
            if value is not None and not all(isinstance(v,dict) and v.get('id') in allowed for v in value):raise ValueError("请选择通讯录中的人员。")
        if int(field["type"])==17:
            existing={x.get('file_token') for x in old['fields'].get(field['field_id']) or [] if isinstance(x,dict)}
            if sum(1 for x in value or [] if isinstance(x,dict) and (x.get('local_media_id') or re.search(r'\.(png|jpe?g|webp|gif|avif|bmp)$',str(x.get('name','')),re.I)))>12:
                raise ValueError('品类图片最多 12 张。')
            from .media import load_image
            for item in value or []:
                if item.get('local_media_id'):load_image(item['local_media_id'],conn=conn)
                elif item.get('file_token') not in existing:raise ValueError("附件不属于当前记录。")
        changes = [(info,old,patch,idempotency_key)]
        # Keep reciprocal associations coherent in the same local transaction.
        if int(field["type"]) in {18,21}:
            target = table(conn,(field.get("property") or {}).get("table_id"))
            for rid in link_ids(value):raw_record(conn,target,rid)
            back = (field.get("property") or {}).get("back_field_id")
            if back:
                if not any(f["field_id"]==back for f in target["fields"]):raise ValueError("关联反向字段未注册。")
                before, after = set(link_ids(old["fields"].get(field["field_id"]))), set(link_ids(value))
                for rid in sorted(before ^ after):
                    target_old=raw_record(conn,target,rid,lock=True)
                    links=link_ids(target_old["fields"].get(back))
                    links=[x for x in links if x!=old["record_id"]]
                    if rid in after:links.append(old["record_id"])
                    changes.append((target,target_old,{back:links},idempotency_key+":"+rid))
        # Name edits update current stock labels; historical request snapshots stay intact.
        rename_rules={"物料品类":("物料品类",["物料主数据","文化周边管理库存"]),"产品型号":("产品型号",["物料主数据","文化周边管理库存"]),
                      "物料语种":("语种",["物料主数据"]),"战区管理":("战区管理",["文化周边管理库存"])}
        primary_name={"物料品类":"物料品类","产品型号":"产品型号","物料语种":"语言种类","战区管理":"战区名称"}
        if info["source"]=="primary" and name==primary_name.get(info["name"]):
            if not isinstance(value,str) or not value.strip():raise ValueError("名称不能为空。")
            for row in rows(conn,info):
                if row["record_id"]!=old["record_id"] and scalar_text(row["fields"].get(name))==value:raise ValueError("名称已经存在。")
            label, targets=rename_rules[info["name"]]
            for target_name in targets:
                target=named_table(conn,target_name)
                fid=next(f["field_id"] for f in target["fields"] if f["field_name"]==label)
                for row in rows(conn,target):
                    if scalar_text(row["fields"].get(label))==scalar_text(old["fields"].get(field["field_id"])):
                        target_old=raw_record(conn,target,row["record_id"],lock=True)
                        changes.append((target,target_old,{fid:value},idempotency_key+":"+row["record_id"]))
        if info["name"]=="用户权限表":
            candidates=[]
            for row in rows(conn,info):
                values=source_values(info,row["fields"])
                if row["record_id"]==old["record_id"]:values.update(patch)
                candidates.append({f["field_name"]:values.get(f["field_id"]) for f in info["fields"]})
            if not any("管理员" in (r.get("角色") or []) and r.get("是否启用")=="是" for r in candidates):
                raise ValueError("至少保留一位启用的管理员。")
        result=None
        for target,target_old,delta,key in changes:
            changed=_save_change(conn,target,target_old,delta,actor,key)
            if result is None:result=changed
        if info["name"] in {"物料主数据","文化周边管理库存"} and name=="当前库存" and old["fields"].get(field["field_id"])!=value:
            create_adjustment_ledger(conn,info,old,result,actor,idempotency_key)
        if info["name"]=="物料品类" and name=="申领页图片":
            attachments=old["fields"].get(field["field_id"]) or []
            old_other=[x.get("file_token") for x in attachments if isinstance(x,dict) and not str(x.get("type","")).startswith("image/") and not re.search(r"\.(png|jpe?g|webp|gif|avif|bmp)$",str(x.get("name","")),re.I)]
            if not set(old_other).issubset({x.get("file_token") for x in value or [] if isinstance(x,dict)}):raise ValueError("图片编辑不能移除 GLB/HTML 等其他附件。")
        return {k:result[k] for k in ("record_id","fields","version","sync_state")}


def create_adjustment_ledger(conn, info, old, updated, actor, key):
    ledger=named_table(conn,"库存流水")
    names={f["field_name"]:f for f in info["fields"]}
    before=number(old["fields"].get(names["当前库存"]["field_id"]))
    after=number(updated["fields"].get(names["当前库存"]["field_id"]))
    standard=info["name"]=="物料主数据"
    fields={"原Supabase ID":"db-adjust-"+uuid4().hex,"流水类型":"数据库库存调整","发生时间":int(datetime.now(timezone.utc).timestamp()*1000),
        "物料编码" if standard else "文化周边物料":[old["record_id"]],"物料品类":scalar_text(old["fields"].get(names["物料品类"]["field_id"])),
        "产品型号":scalar_text(old["fields"].get(names["产品型号"]["field_id"])),"数量":float(abs(after-before)),"变更前数量":float(before),
        "变更后数量":float(after),"库存变化":float(after-before),"幂等键":key+":stock-ledger","操作人":[{"id":actor}],"备注":"数据库工作台库存调整"}
    # Only existing schema names are written. Source-specific enum labels are taken from metadata.
    for f in ledger["fields"]:
        if f["field_name"]=="流水业务类型":
            options=[x["name"] for x in (f.get("property") or {}).get("options",[])]
            label=next((x for x in options if ("文化" in x)==(not standard)),None)
            if label:fields[f["field_name"]]=label
    values=source_values(ledger,fields)
    rid="local_"+uuid4().hex
    conn.execute(sql.SQL("INSERT INTO material_data.{} (_record_key,_fields,_local_version,_sync_state) VALUES (%s,%s,1,'pending')").format(sql.Identifier(ledger["sql_table"])),(rid,Jsonb(values)))
    replace_values(conn,ledger,rid,values)
    conn.execute("INSERT INTO material_ops.outbox(idempotency_key,lane,table_id,record_key,local_version,patch,operation) VALUES (%s,'admin',%s,%s,1,%s,'create')",(key+":stock-ledger",ledger["table_id"],rid,Jsonb(values)))
    conn.execute("INSERT INTO material_ops.audit(table_id,record_key,source,after_value,local_version,actor_open_id) VALUES (%s,%s,'frontend',%s,1,%s)",(ledger["table_id"],rid,Jsonb(values),actor))
