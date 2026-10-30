"""Refresh only system-authored administrator contact text at publication time.

No historical scan, recipient changes, or new messages are created here.
"""
from copy import deepcopy
import re

AT=r'<at\s+id=(?:"ou_[\w-]+"|\'ou_[\w-]+\'|ou_[\w-]+)>\s*</at>'
CONTACTS=(
    ('您的（文化周边）需求已提交，请找','进行申领。','已启用的管理员'),
    ('如有疑问或其他需求，请联系','','物料管理员。'),
    ('If you have any questions or other requests, please contact ','','the material administrator.'),
    ('如有疑问，请联系','。','已启用的管理员'),
)
PATTERNS=[(re.compile(re.escape(prefix)+r'(?P<contacts>(?:'+AT+r')(?:\s*'+AT+r')*|'+re.escape(fallback)+')'+re.escape(suffix)),fallback)
          for prefix,suffix,fallback in CONTACTS]


def enabled_admins(conn):
    """Committed PG permissions are authoritative, including duplicate-row union."""
    import app
    from . import repository as repo
    info=repo.named_table(conn,app.USER_PERMISSION_TABLE_NAME)
    return sorted({identity for row in repo.rows(conn,info) if app.feishu_permission_enabled(row['fields'])
                   and '管理员' in app.feishu_choice_values(row['fields'],'角色')
                   for identity in app.feishu_person_open_ids(row['fields'],['用户账号','用户','成员'])})


def refresh(card,administrators):
    result=deepcopy(card);found=False
    mentions=' '.join(f'<at id={identity}></at>' for identity in sorted(set(administrators)))
    def visit(node):
        nonlocal found
        if isinstance(node,list):
            for item in node:visit(item)
        elif isinstance(node,dict):
            if node.get('tag') in {'markdown','lark_md'} and isinstance(node.get('content'),str):
                content=node['content']
                for pattern,fallback in PATTERNS:
                    def replace(match):
                        nonlocal found
                        found=True;start,end=match.span('contacts');relative=start-match.start()
                        return match.group(0)[:relative]+(mentions or fallback)+match.group(0)[end-match.start():]
                    content=pattern.sub(replace,content)
                node['content']=content
            for value in node.values():
                if isinstance(value,(dict,list)):visit(value)
    visit(result)
    return result,found
