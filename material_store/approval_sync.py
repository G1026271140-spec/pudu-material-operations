"""Publish the inventory-confirmation trigger only after its full line snapshot."""
from psycopg import sql
from . import repository as repo


def is_confirmation(info, patch):
    if info['source'] != 'primary' or info['name'] != '物料申请单':
        return False
    field = next((f for f in info['fields'] if f['field_name'] == '库存审查状态'), None)
    return bool(field and repo.scalar_text(patch.get(field['field_id'])) == '已核实库存')


def line_snapshot(conn, info, row, task):
    """Read dependency state without holding a SQL transaction across Feishu HTTP.

    Reciprocal local links cover edits from other jobs and lanes. The same-job
    check also covers removed lines whose remote delete must finish first.
    """
    if not is_confirmation(info, task['patch']):
        return None
    from .outbox_worker import DependencyPending, SourceConflict
    if task['operation'] == 'create':
        raise SourceConflict('新建申请不能同时触发库存核实审批，请先发布申请和明细。')
    link = next((f for f in info['fields'] if f['field_name'] == '申请明细' and f['type'] in {18, 21}), None)
    if link is None:
        raise SourceConflict('申请明细关联字段未注册，不能触发审批。')
    lines = repo.table(conn, link['property']['table_id'])
    linked = repo.link_ids(row['fields'].get(link['field_id']))
    records = conn.execute(sql.SQL('SELECT _record_key,_remote_id,_deleted FROM material_data.{} '
        'WHERE _record_key=ANY(%s) OR _remote_id=ANY(%s)').format(sql.Identifier(lines['sql_table'])),
        (linked, linked)).fetchall() if linked else []
    keys = [r[0] for r in records]
    states = [r[0] for r in conn.execute("""SELECT state FROM material_ops.outbox
        WHERE table_id=%s AND (record_key=ANY(%s) OR (job_id=%s AND job_id IS NOT NULL))
          AND state NOT IN ('done','cancelled')""", (lines['table_id'], keys, task.get('job_id')))]
    if 'conflict' in states:
        raise SourceConflict('申请明细存在同步冲突，不能提前触发审批。')
    if states or any(not remote for _, remote, deleted in records if not deleted):
        raise DependencyPending('申请明细尚未全部同步，等待后再触发审批。')
    known = {key for key, _, _ in records} | {remote for _, remote, _ in records if remote}
    if set(linked) - known:
        raise SourceConflict('申请关联明细不存在，不能触发审批。')
    return link['field_name'], {remote for _, remote, deleted in records if not deleted}


def check_remote_links(snapshot, remote):
    if snapshot is None:
        return
    from .outbox_worker import DependencyPending
    name, expected = snapshot
    if not expected.issubset(set(repo.link_ids((remote.get('fields') or {}).get(name)))):
        raise DependencyPending('飞书申请单的明细回链尚未完整可见，等待后再触发审批。')
