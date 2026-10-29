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
        path = '/api/shipping-calendar/' + quote(key, safe='')
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


def catalog(conn, *, owner=None):
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
        if owner is not None and owner not in app.feishu_person_open_ids(named, ['申请人']):
            continue
        if not eligible(named) or not app.feishu_text(named, '申请单号'):
            continue
        linked = [*by_request.get(key, []), *by_request.get(remote, []), *by_number.get(app.feishu_text(named, '申请单号'), [])]
        linked = list({line['id']: line for line in linked}.values())
        linked.sort(key=lambda line: (line['line_no'], line['id']))
        requests.append(present(raw, info, linked))
    statuses = notification_states(conn)
    from .auto_shipping import enabled,document
    automatic=enabled(conn)
    visible=[]
    for request in requests:
        request['notification'] = statuses.get(request['request_id'])
        native=(document(conn,request['request_id']).get('native') or {}) if automatic else {}
        row=repo.raw_record(conn,info,request['request_id'])
        if native.get('code')!=app.feishu_text(repo.feishu_record(info,row)['fields'],'审批实例Code'):native={}
        request['approval_status']=native.get('status')
        if native.get('status') not in {'REJECTED','CANCELED','DELETED'}:visible.append(request)
    requests=visible
    requests.sort(key=lambda r: (r['ship_date'] or '9999', r['arrival_start'] or '9999', r['request_no']))
    from .auto_shipping import enabled
    return {'requests': requests, 'generated_at': datetime.now().astimezone().isoformat(), 'source': 'postgresql', 'automatic_shipping': enabled(conn)}


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


def validate_native_approval(conn,key,fields):
    from .auto_shipping import enabled,document
    import app
    if enabled(conn):
        native=document(conn,key).get('native') or {}
        if native.get('code')==app.feishu_text(fields,'审批实例Code') and native.get('status') in {'REJECTED','CANCELED','DELETED'}:
            raise ValueError('此申请的飞书审批已驳回或撤回，不能编辑发货。')


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
        validate_native_approval(conn,old['record_id'],fields)
        from .concurrency import check_version
        check_version(body['expected_version'],old['version'],'申请单版本无效，请重新载入后再保存。')
        if old['sync_state'] == 'conflict':
            raise repo.VersionConflict('此申请单存在飞书同步冲突，请先在虚拟数据库核对。')
        images = attachments(conn, body['images'], fields.get(IMAGES), actor)
        patch = {TEXT: text, SHIPPED: body['shipped'], IMAGES: images}
        runtime.request_state.update(_write_conn=conn, _write_actor=actor, _write_lane='ordinary')
        DatabaseWriteClient(conn).update_record(info['table_id'], old['record_id'], patch)
        current = repo.raw_record(conn, info, old['record_id'])
        result = {'request_id': old['record_id'], 'version': current['version'], 'sync_state': current['sync_state']}
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',
                     ('shipping-calendar:' + key, Jsonb({'hash': digest, 'actor': actor, 'result': result})))
        return result


def schedule_outbox_dependencies(conn, request_id):
    import app
    from order_scheduling import BATCH_TABLE, DETAIL_TABLE
    line_info = repo.named_table(conn, app.REQUEST_LINE_TABLE_NAME)
    detail_info = repo.named_table(conn, DETAIL_TABLE)
    batch_info = repo.named_table(conn, BATCH_TABLE)
    lines = [row['record_id'] for row in repo.rows(conn, line_info) if request_id in app.feishu_link_ids_any(row['fields'], ['所属申请单', '申请单'])]
    details = [row for row in repo.rows(conn, detail_info) if request_id in app.feishu_link_ids(row['fields'], '来源申请单')]
    batches = {key for row in details for key in app.feishu_link_ids(row['fields'], '所属下单批次')}
    result = []
    for info, keys in [(line_info, lines), (detail_info, [row['record_id'] for row in details]), (batch_info, list(batches))]:
        if keys:
            result += [str(row[0]) for row in conn.execute("SELECT id FROM material_ops.outbox WHERE table_id=%s AND record_key=ANY(%s) AND state IN ('pending','processing','retry')", (info['table_id'], keys))]
    return result


def save_batch(actor, body):
    """Confirm all drafts atomically; publish fields before applicant messages."""
    import app
    import backend_runtime as runtime
    from . import effects, jobs
    runtime.release_database_snapshot()
    if not isinstance(body, dict) or set(body) != {'idempotency_key', 'changes', 'confirmed'} or body['confirmed'] is not True:
        raise ValueError('请先确认：发货信息即将同步给申请人，请确定提交')
    key = body['idempotency_key']
    changes = body['changes']
    if not actor or not isinstance(key, str) or not 8 <= len(key) <= 150:
        raise ValueError('缺少操作人或批量提交标识。')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 200:
        raise ValueError('一次可提交 1 至 200 张申请单。')
    allowed = {'request_id', 'expected_version', 'shipping_text', 'shipped', 'images'}
    ids = []
    for item in changes:
        if not isinstance(item, dict) or set(item) not in (allowed, allowed | {'ship_date'}):
            raise ValueError('只能提交申请单的三个发货字段。')
        if not isinstance(item['request_id'], str) or not item['request_id'] or item['request_id'] in ids:
            raise ValueError('申请单标识不能为空或重复。')
        ids.append(item['request_id'])
        if type(item['shipped']) is not bool or type(item['expected_version']) is not int:
            raise ValueError('发货勾选或申请单版本无效。')
        if not isinstance(item['shipping_text'], str) or len(item['shipping_text']) > 20000:
            raise ValueError('发货单号及文字信息不能超过 20000 字。')
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with connection() as conn, conn.transaction(), runtime.request_scope():
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('pudu-reconciliation',0))")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('business-lane:ordinary',0))")
        prior = conn.execute('SELECT payload FROM material_ops.documents WHERE name=%s', ('shipping-batch:' + key,)).fetchone()
        if prior:
            if prior[0]['hash'] != digest or prior[0]['actor'] != actor:
                raise repo.VersionConflict('提交标识已用于其他修改。')
            return prior[0]['result']
        info = source_info(conn)
        prepared = []
        # Validate the entire batch before changing any record.
        for item in sorted(changes, key=lambda item: item['request_id']):
            old = repo.raw_record(conn, info, item['request_id'], lock=True)
            fields = repo.feishu_record(info, old)['fields']
            number = app.feishu_text(fields, '申请单号')
            if not eligible(fields):
                raise ValueError(number + ' 已不符合发货编辑条件，请刷新核对。')
            validate_native_approval(conn,old['record_id'],fields)
            from .concurrency import check_version
            check_version(item['expected_version'],old['version'],number + ' 版本无效，本批尚未保存。')
            if old['sync_state'] == 'conflict':
                raise repo.VersionConflict(number + ' 已被修改或存在同步冲突，本批尚未保存，请核对后重新提交。')
            images = attachments(conn, item['images'], fields.get(IMAGES), actor)
            next_date = item.get('ship_date', date_text(fields.get('物料发货时间')))
            if not isinstance(next_date, str) or (next_date and (len(next_date) != 10 or date_text(next_date) != next_date)):
                raise ValueError(number + ' 的发货日期无效，请选择有效日期。')
            if not next_date and date_text(fields.get('物料发货时间')):
                raise ValueError(number + ' 的发货日期不能为空，请选择新日期。')
            date_changed = next_date != date_text(fields.get('物料发货时间'))
            from .auto_shipping import enabled as automatic_enabled
            from .shipping_defaults import real_text,real_images
            logistics=bool(real_text(item['shipping_text']) or real_images(conn,images))
            patch = {TEXT: item['shipping_text'], SHIPPED: ((fields.get(SHIPPED) is True) or logistics) if automatic_enabled(conn) else item['shipped'], IMAGES: images}
            def image_keys(values):
                return [v.get('local_media_id') or v.get('file_token') for v in values or []]
            if (app.feishu_text(fields, TEXT) == patch[TEXT] and (fields.get(SHIPPED) is True) == patch[SHIPPED]
                    and image_keys(fields.get(IMAGES)) == image_keys(images) and not date_changed):
                continue
            recipients = app.feishu_person_open_ids(fields, ['申请人'])
            if len(recipients) != 1 or not recipients[0].startswith('ou_'):
                raise ValueError(number + ' 缺少有效申请人账号，无法同步通知，请先核对申请人字段。')
            if date_changed:
                from order_scheduling import date_ms
                patch['物料发货时间'] = date_ms(next_date)
            prepared.append((old, fields, patch, recipients[0], number, next_date, date_changed))
        task, _ = jobs.enqueue('发货信息同步', 'shipping-batch:' + key, {'actor': actor, 'hash': digest}, conn=conn)
        conn.execute("SELECT set_config('pudu.job_id',%s,true)", (task.task_id,))
        runtime.request_state.update(_write_conn=conn, _write_actor=actor, _write_lane='ordinary', _job_id=task.task_id, _effect_ordinal=0)
        if any(item[-1] for item in prepared):
            from request_web.live_data import LiveReader
            runtime.request_state['_live_reader'] = LiveReader()
        entries = []
        for old, fields, patch, recipient, number, next_date, date_changed in prepared:
            before_ids = {str(row[0]) for row in conn.execute('SELECT id FROM material_ops.outbox WHERE job_id=%s', (task.task_id,))}
            DatabaseWriteClient(conn).update_record(info['table_id'], old['record_id'], patch)
            if date_changed:
                app.sync_request_ship_date_to_schedule(old['record_id'], next_date)
            current = repo.raw_record(conn, info, old['record_id'])
            dependencies = [str(row[0]) for row in conn.execute("SELECT id FROM material_ops.outbox WHERE table_id=%s AND record_key=%s AND local_version<=%s AND state IN ('pending','processing','retry') ORDER BY ordinal", (info['table_id'], old['record_id'], current['version']))]
            related = [str(row[0]) for row in conn.execute('SELECT id FROM material_ops.outbox WHERE job_id=%s', (task.task_id,)) if str(row[0]) not in before_ids]
            dependencies = list(dict.fromkeys([*dependencies, *related, *(schedule_outbox_dependencies(conn, old['record_id']) if date_changed else [])]))
            if not dependencies:
                raise RuntimeError('发货字段尚未生成同步任务，本批修改已回滚。')
            from .auto_shipping import enabled as automatic_enabled,stage
            if automatic_enabled(conn):
                stage(conn,old['record_id'],version=current['version'],fields={**fields,**patch})
                entries.append({'request_id':old['record_id'],'request_no':number,'version':current['version'],
                                'outbox_ids':dependencies,'effect_id':None,'automatic':True})
                continue
            import os
            from .shipping_card import card as shipment_card
            origin=os.environ.get('PUDU_PUBLIC_ORIGIN','https://materials.pudu.work')
            if date_changed:
                from .shipping_card import date_change_card
                message=date_change_card(number,old['record_id'],date_text(fields.get('物料发货时间')),next_date,patch[SHIPPED],origin)
            else:
                message = shipment_card(number, old['record_id'], patch[SHIPPED], next_date,
                    date_text(fields.get('要求达到开始日期')), patch[TEXT], len(patch[IMAGES]), origin)
            # Supersede an older, never-attempted notification for this same
            # request. Its outbox still publishes in version order.
            conn.execute("UPDATE material_ops.effects SET state='failed',last_error='已被更新的发货提交替代，未发送旧通知' WHERE kwargs->>'_shipping_request'=%s AND state IN ('pending','retry') AND first_attempt_at IS NULL", (old['record_id'],))
            alias = effects.defer('primary', 'send_interactive_message', [recipient, message], {
                'receive_id_type': 'open_id', '_outbox_ids': dependencies, '_shipping_request': old['record_id'], '_shipping_version': current['version'], **({'_shipping_date_change':True,'_shipping_date_before':date_text(fields.get('物料发货时间')),'_shipping_date_after':next_date} if date_changed else {})})
            entries.append({'request_id': old['record_id'], 'request_no': number, 'version': current['version'],
                            'outbox_ids': dependencies, 'effect_id': alias[len(effects.PREFIX):]})
        result = {'batch_id': task.task_id, 'changed': len(entries), 'unchanged': len(changes) - len(entries), 'entries': entries}
        if entries:
            from .admin_completion import register as register_completion
            register_completion(conn,task.task_id,'发货信息同步',{'actor':actor},result,actor)
        conn.execute("UPDATE material_ops.jobs SET state='done',completed_at=now(),result=%s WHERE id=%s", (Jsonb(result), task.task_id))
        conn.execute('INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)',
                     ('shipping-batch:' + key, Jsonb({'actor': actor, 'hash': digest, 'result': result})))
        return result


def notification_states(conn):
    rows = conn.execute("""SELECT DISTINCT ON (kwargs->>'_shipping_request') kwargs->>'_shipping_request',state,last_error,kwargs->'_outbox_ids'
        FROM material_ops.effects WHERE kwargs ? '_shipping_request'
        ORDER BY kwargs->>'_shipping_request',COALESCE((kwargs->>'_shipping_version')::bigint,0) DESC,created_at DESC,id DESC""").fetchall()
    result = {}
    for key, state, error, dependencies in rows:
        if state in {'pending', 'retry'} and dependencies:
            blocked = conn.execute("SELECT EXISTS(SELECT 1 FROM material_ops.outbox WHERE id::text=ANY(%s) AND state IN ('conflict','cancelled'))", (dependencies,)).fetchone()[0]
            if blocked:
                state, error = 'blocked', '飞书字段同步需核对，尚未通知申请人。'
        result[key] = {'state': state, 'error': error or ''}
    from .auto_shipping import enabled,PREFIX
    if enabled(conn):
        for name,state in conn.execute("SELECT name,payload FROM material_ops.documents WHERE name LIKE %s",(PREFIX+'%',)):
            key=name[len(PREFIX):]
            if state.get('dirty') or state.get('state') in {'waiting_approval','waiting_information','blocked'} or (state.get('state')=='pending' and key not in result):
                result[key]={'state':state.get('state','pending'),'error':state.get('error','')}
    return result
