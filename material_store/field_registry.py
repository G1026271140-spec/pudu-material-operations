"""Lossless Feishu identity mapping, typed local projections and edit contracts."""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
import re

READ_ONLY_TYPES = {19,20,1001,1002,1003,1004,1005}
JSON_TYPES = {4,11,15,17,18,19,20,21,22,23,1003,1004}
DATETIME_TYPES = {5,1001,1002}
TYPE_NAMES = {1:'文本',2:'数字',3:'单选',4:'多选',5:'日期时间',7:'复选框',11:'人员',13:'电话',15:'链接',
    17:'附件',18:'单向关联',19:'查找引用',20:'公式',21:'双向关联',22:'地理位置',23:'群组',
    1001:'创建时间',1002:'最后更新时间',1003:'创建人',1004:'修改人',1005:'自动编号'}


def sql_identifier(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,62}',value):
        raise ValueError('Invalid SQL identifier')
    return '"'+value+'"'


def table_column_names(table_id: str,field_id: str) -> tuple[str,str]:
    if not re.fullmatch(r'tbl[A-Za-z0-9]+',table_id) or not re.fullmatch(r'fld[A-Za-z0-9]+',field_id):
        raise ValueError('Expected stable Feishu table and field identifiers')
    return 't_'+table_id,'f_'+field_id


def postgres_type(field_type: int) -> str:
    if field_type in JSON_TYPES:return 'jsonb'
    if field_type in DATETIME_TYPES:return 'timestamptz'
    if field_type==2:return 'numeric'
    if field_type==7:return 'boolean'
    return 'text'


def scalar_text(value):
    if value is None:return None
    if isinstance(value,list):
        return ''.join(str(item.get('text') or item.get('name') or '') if isinstance(item,dict) else str(item) for item in value)
    if isinstance(value,dict):return str(value.get('text') or value.get('name') or value.get('value') or '')
    return str(value)


def typed_value(field_type,value):
    if value is None:return None
    if field_type in JSON_TYPES:return value
    if field_type in DATETIME_TYPES:
        if value=='':return None
        return datetime.fromtimestamp(float(value)/1000,timezone.utc)
    if field_type==2:
        if value=='':return None
        result = Decimal(scalar_text(value))
        if not result.is_finite():raise ValueError('Number must be finite')
        return result
    if field_type==7:
        if not isinstance(value,bool):raise ValueError('Checkbox must be a boolean')
        return value
    return scalar_text(value)


def edit_mode(field):
    kind=int(field['type'])
    if kind in {19,20}:return '修改源字段后计算'
    if kind in {1001,1002,1003,1004,1005}:return '系统生成'
    if kind==17:return '附件新增替换移除'
    if kind in {18,21}:return '选择关联记录'
    return '直接编辑'


def validate_patch(fields,patch):
    """Patches use stable field IDs; all validation precedes the DB transaction."""
    by_id={f['field_id']:f for f in fields}
    for field_id,value in patch.items():
        if field_id not in by_id:raise ValueError('Unknown field ID: '+field_id)
        field=by_id[field_id]
        kind=int(field['type'])
        if kind in READ_ONLY_TYPES or kind==19:raise ValueError('Computed/system fields require source-field editing: '+field_id)
        typed_value(kind,value)
        if kind in {3,4} and value is not None:
            choices={x['name'] for x in (field.get('property') or {}).get('options',[])}
            selected=value if isinstance(value,list) else [value]
            if kind==3 and len(selected)!=1:raise ValueError('Single-select accepts one value')
            if not all(isinstance(x,str) and x in choices for x in selected):raise ValueError('Unknown selection option')
        if kind in {4,11,17,18,21} and value is not None and not isinstance(value,list):
            raise ValueError('Expected a list for multi-value field')
        if kind in {18,21} and value is not None:
            if not all(isinstance(item,str) and item for item in value):raise ValueError('Link values require record IDs')
            if (field.get('property') or {}).get('multiple') is False and len(value)>1:
                raise ValueError('This link field accepts at most one record')
        if kind==17 and value is not None:
            if not all(isinstance(x,dict) and (x.get('file_token') or x.get('local_media_id')) for x in value):
                raise ValueError('Attachment requires an existing token or local media identity')
    return True
