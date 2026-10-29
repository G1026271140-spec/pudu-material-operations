"""Add only two source text fields and their stable PostgreSQL projections."""
from copy import deepcopy
import json,re,subprocess
from .field_registry import table_column_names

NAMES=('待核实标签','待核实备注')


def extend(snapshot,live_fields):
    result=deepcopy(snapshot)
    candidates=[t for t in result['tables'] if t.get('source','primary')=='primary' and t['table_name']=='物料申请单']
    if len(candidates)!=1:raise ValueError('申请单注册必须唯一。')
    table=candidates[0];added=[]
    for name in NAMES:
        matches=[f for f in live_fields if f['field_name']==name]
        if len(matches)!=1 or matches[0]['type']!=1:raise ValueError('来源缺少唯一的文本字段：'+name)
        field=matches[0];table_column_names(table['table_id'],field['field_id'])
        prior=[f for f in table['fields'] if f['field_id']==field['field_id'] or f['field_name']==name]
        if prior and (len(prior)!=1 or prior[0]['field_id']!=field['field_id'] or prior[0]['type']!=1):raise ValueError('稳定字段定义不一致：'+name)
        if not prior:table['fields'].append(deepcopy(field))
        added.append(field)
    return result,table,added


def register_sql(table,added):
    table_sql,_=table_column_names(table['table_id'],added[0]['field_id'])
    def literal(v):return "'"+str(v).replace("'","''")+"'"
    statements=["BEGIN;SET LOCAL ROLE pudu_material_owner;SELECT pg_advisory_xact_lock(hashtextextended('pudu-reconciliation',0));"]
    for field in added:
        _,column=table_column_names(table['table_id'],field['field_id'])
        ordinal=next(i for i,f in enumerate(table['fields']) if f['field_id']==field['field_id'])
        statements.append('ALTER TABLE material_data."'+table_sql+'" ADD COLUMN IF NOT EXISTS "'+column+'" text;')
        statements.append('INSERT INTO material_meta.fields(table_id,field_id,field_name,field_type,sql_column,sql_type,edit_mode,definition,ordinal) VALUES ('+
            ','.join([literal(table['table_id']),literal(field['field_id']),literal(field['field_name']),'1',literal(column),"'text'","'直接编辑'",literal(json.dumps(field,ensure_ascii=False))+'::jsonb',str(ordinal)])+
            ') ON CONFLICT(table_id,field_id) DO NOTHING;')
    statements.append('COMMIT;')
    return '\n'.join(statements)
