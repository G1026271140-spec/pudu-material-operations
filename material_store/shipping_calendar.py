"""Verified ordinary requests: local shipping edits and durable Feishu publication."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from urllib.parse import quote
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from . import repository as repo
from .client import DatabaseWriteClient
from .db import connection

TEXT = '发货单号及文字信息'
IMAGES = '发货图片'
SHIPPED = '是否发货'


def source_info(conn):
    import app
    info = repo.named_table(conn, app.REQUEST_TABLE_NAME)
    actual = {field['field_name']: field['type'] for field in info['fields']}
    if any(actual.get(name) != kind for name, kind in ((TEXT, 1), (IMAGES, 17), (SHIPPED, 7))):
        raise ValueError('申请单发货字段定义已变化，请先核对字段注册。')
    return info


def eligible(fields):
    import app
    return (app.feishu_text(fields, '申请类型') == '普通物料申请'
            and app.feishu_text(fields, '库存审查状态') == app.INVENTORY_REVIEW_CONFIRMED
            and app.feishu_text(fields, '审批状态') not in {'已撤回', '已驳回', '已取消', '驳回处理中', '撤回处理中'})


def date_text(value):
    from order_scheduling import as_date
    try:
        day = as_date(value)
        return day.isoformat() if day else ''
    except (TypeError, ValueError, OverflowError, OSError):
        return ''


def image_items(key, fields):
    images = []
    for item in fields.get(IMAGES) or []:
        if not isinstance(item, dict):
            continue
        local, token = item.get('local_media_id'), item.get('file_token')
        if not local and not token:
            continue
        path = '/api/admin/shipping-calendar/' + quote(key, safe='')
        path += '/local-images/' + str(local) if local else '/remote-images/' + quote(token, safe='')
        images.append({**item, 'name': item.get('name') or '发货图片', 'path': path})
    return images


def present(raw, info, lines):
    import app
    fields = repo.feishu_record(info, raw)['fields']
    request = app.load_feishu_request_records([{'record_id': raw['record_id'], 'fields': fields}])
    if not request:
        raise ValueError('申请单缺少申请单号。')
    request = request[0]
    return {
        'request_id': raw['record_id'], 'request_no': request['request_no'],
        'version': raw['version'], 'sync_state': raw['sync_state'],
        'requester': request['requester'], 'department': request['department'],
        'region': app.feishu_text(fields, '所属战区'), 'customer': request['customer_name'],
        'country': request['country'], 'recipient': request['recipient_info'],
        'usage': request['material_usage'], 'reason': request['request_reason'],
        'submitted_at': request['submitted_at'], 'status': request['status'],
        'ship_date': date_text(fields.get('物料发货时间')),
        'arrival_start': date_text(fields.get('要求达到开始日期')),
        'arrival_end': date_text(fields.get('要求到达结束日期')),
        'shipped': fields.get(SHIPPED) is True,
        'shipping_text': app.feishu_text(fields, TEXT),
        'images': image_items(raw['record_id'], fields), 'lines': lines,
        'detail_text': app.feishu_text(fields, '物料明细文字信息'),
    }


def catalog(conn):
    """One SQL snapshot, including unscheduled requests and all detail rows."""
    import app
    info = source_info(conn)
    line_info = repo.named_table(conn, app.REQUEST_LINE_TABLE_NAME)
    rows = repo.rows(conn, line_info)
    materials = repo.rows(conn, repo.named_table(conn, app.MATERIAL_TABLE_NAME))
    categories = repo.rows(conn, repo.named_table(conn, app.CATEGORY_TABLE_NAME))
    parsed = {line['record_id']: line for line in app.load_feishu_request_line_records(rows, materials, categories)}
    by_request, by_number = {}, {}
    for row in rows:
        f = row['fields']; line = parsed.get(row['record_id'], {})
        view = {
            'id': row['record_id'], 'line_no': app.feishu_text(f, '明细编号'),
            'product': line.get('actual_product') or line.get('product') or app.feishu_text_any(f, ['实际发放物料品类', '品类名称', '物料品类', '品类']),
            'model': line.get('actual_model') or line.get('model') or app.feishu_text_any(f, ['实际发放产品型号', '产品型号名称', '产品型号']),
            'language': line.get('actual_language') or line.get('language') or app.feishu_text_any(f, ['实际发放语种', '语种名称', '语种']),
            'quantity': app.feishu_int(f, '申请数量'),
            'approved_quantity': app.feishu_int(f, '审批通过数量'),
            'issued_quantity': app.feishu_int(f, '实际发放数量'),
            'remark': app.feishu_text(f, '备注'),
        }
        for request_id in app.feishu_link_ids_any(f, ['所属申请单', '申请单']):
            by_request.setdefault(request_id, []).append(view)
        number = app.feishu_text(f, '申请单号')
        if number:
            by_number.setdefault(number, []).append(view)
    requests = []
    for key, remote, fields, version, state in conn.execute(sql.SQL(
            'SELECT _record_key,_remote_id,_fields,_local_version,_sync_state FROM material_data.{} WHERE NOT _deleted')
            .format(sql.Identifier(info['sql_table']))):
        raw = {'record_id': key, 'fields': fields, 'version': version, 'sync_state': state}
        named = repo.feishu_record(info, raw)['fields']
        if not eligible(named) or not app.feishu_text(named, '申请单号'):
            continue
        linked = [*by_request.get(key, []), *by_request.get(remote, []), *by_number.get(app.feishu_text(named, '申请单号'), [])]
        linked = list({line['id']: line for line in linked}.values())
        linked.sort(key=lambda line: (line['line_no'], line['id']))
        requests.append(present(raw, info, linked))
    requests.sort(key=lambda r: (r['ship_date'] or '9999', r['arrival_start'] or '9999', r['request_no']))
    return {'requests': requests, 'generated_at': datetime.now().astimezone().isoformat(), 'source': 'postgresql'}


def attachments(conn, incoming, current, actor):
    if not isinstance(incoming, list) or len(incoming) > 12:
        raise ValueError('发货图片最多 12 张。')
    current = current or []
    old_tokens = {item.get('file_token') for item in current if isinstance(item, dict)}
    old_local = {item.get('local_media_id') for item in current if isinstance(item, dict)}
    result, seen = [], set()
    for item in incoming:
        if not isinstance(item, dict):
            raise ValueError('图片格式无效。')
        local, token = item.get('local_media_id'), item.get('file_token')
        if bool(local) == bool(token):
            raise ValueError('图片必须提供一种有效的附件标识。')
        identity = local or token
        if not isinstance(identity, str) or identity in seen:
            raise ValueError('图片标识无效或重复。')
        seen.add(identity)
        if local:
            from .media import load_image
            UUID(local)
            owner = conn.execute('SELECT owner_open_id FROM material_ops.media WHERE id=%s', (local,)).fetchone()
            if not owner or (local not in old_local and owner[0] != actor):
                raise ValueError('请上传自己的图片，或保留此申请单已有图片。')
            image = load_image(local, conn=conn)
            result.append({'local_media_id': local, 'name': image['name']})
        else:
            if token not in old_tokens:
                raise ValueError('只能保留此申请单已有的飞书图片，新增图片请先上传。')
            original = next(image for image in current if image.get('file_token') == token)
            result.append({'file_token': token, 'name': str(original.get('name') or '发货图片')})
    return result


def save(actor, body):
    import backend_runtime as runtime
    runtime.release_database_snapshot()
    allowed = {'request_id', 'expected_version', 'shipping_text', 'shipped', 'images', 'idempotency_key'}
    if not isinstance(body, dict) or set(body) != allowed:
        raise ValueError('请提交完整的发货信息，不能修改其他申请字段。')
    key = body['idempotency_key']
    if not actor or not isinstance(key, str) or not 8 <= len(key) <= 150:
        raise ValueError('缺少操作人或保存标识。')
    if type(body['shipped']) is not bool or type(body['expected_version']) is not int:
        raise ValueError('发货勾选或申请单版本无效。')
    text = body['shipping_text']
    if not isinstance(text, str) or len(text) > 20000:
        raise ValueError('发货单号及文字信息不能超过 20000 字。')
    if not isinstance(body['request_id'], str) or not body['request_id']:
        raise ValueError('申请单标识不能为空。')
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with connection() as conn, conn.transaction(), runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:ordinary',0))")
        prior = conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s', ('shipping-calendar:' + key,)).fetchone()
        if prior:
            if prior[0]['hash'] != digest or prior[0]['actor'] != actor:
                raise repo.VersionConflict('保存标识已用于其他修改。')
            return prior[0]['result']
        info = source_info(conn)
        old = repo.raw_record(conn, info, body['request_id'], lock=True)
        fields = repo.feishu_record(info, old)['fields']
        if not eligible(fields):
            raise ValueError('仅可编辑已核实库存且未撤回、驳回或取消的普通物料申请。')
        if old['version'] != body['expected_version']:
            raise repo.VersionConflict('此申请单已被其他操作修改，请重新载入后再保存。')
        if old['sync_state'] == 'conflict':
            raise repo.VersionConflict('此申请单存在飞书同步冲突，请先在数据库工作台核对。')
        images = attachments(conn, body['images'], fields.get(IMAGES), actor)
        patch = {TEXT: text, SHIPPED: body['shipped'], IMAGES: images}
        runtime.request_state.update(_write_conn=conn, _write_actor=actor, _write_lane='ordinary')
        DatabaseWriteClient(conn).update_record(info['table_id'], old['record_id'], patch)
        current = repo.raw_record(conn, info, old['record_id'])
        result = {'request_id': old['record_id'], 'version': current['version'], 'sync_state': current['sync_state']}
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',
                     ('shipping-calendar:' + key, Jsonb({'hash': digest, 'actor': actor, 'result': result})))
        return result
