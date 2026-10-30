"""Culture jacket eligibility is based on verified directory department IDs."""
from .db import connection

DEPARTMENTS=frozenset({'市场营销部','dream组'})
PRODUCTS=frozenset({'文化夹克','休闲商务夹克-黑色（长袖）'})


def restricted(product):return str(product or '').strip() in PRODUCTS


def eligible_people(directory):
    departments={str(d.get('department_id') or '') for d in (directory or {}).get('departments',[])
                 if str(d.get('name') or '').strip().casefold() in DEPARTMENTS}
    departments.discard('')
    return {u['open_id'] for u in (directory or {}).get('users',[]) if u.get('open_id')
            and departments.intersection(str(d) for d in u.get('department_ids') or [])}


def filter_catalog(catalog,directory,viewer):
    if viewer in eligible_people(directory):return catalog
    return {**catalog,'products':[p for p in catalog['products'] if not restricted(p)],
            'category_labels':{p:v for p,v in catalog['category_labels'].items() if not restricted(p)},
            'category_ids':{p:v for p,v in catalog['category_ids'].items() if not restricted(p)},
            'combinations':{key:row for key,row in catalog['combinations'].items() if not restricted(row['product'])}}


def validate(payload,lines,*,conn=None,directory=None):
    if not any(restricted(line.get('product')) and int(line.get('quantity') or 0)>0 for line in lines):return
    if directory is None:
        if conn is None:
            with connection() as opened:return validate(payload,lines,conn=opened)
        row=conn.execute("SELECT payload FROM material_ops.documents WHERE name='contact_departments_cache.json'").fetchone()
        directory=row[0] if row else {}
    allowed=eligible_people(directory)
    requester=payload.get('requester_open_id')
    submitter=payload.get('submitter_open_id') or requester
    if not requester or requester not in allowed or submitter not in allowed:
        raise ValueError('文化夹克仅限飞书通讯录部门为市场营销部或Dream组的人员申领。')
