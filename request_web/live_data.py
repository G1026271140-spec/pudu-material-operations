"""Live source adapters. Data lasts only for one HTTP request, never on disk.

Within a response we reuse the same source rows to assemble consistent views.
The next request fetches them again. OAuth token reuse is separate from data.
"""
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
import time
import threading
from urllib.parse import quote

import backend_runtime as runtime


class LiveTables(Mapping):
    def __init__(self, source):
        self.source = source

    def __getitem__(self, name):
        if name not in self.source.table_ids():
            raise KeyError(name)
        return self.source.rows(name)

    def __iter__(self):
        import app
        return iter(name for name in app.ALL_PAGE_CACHE_TABLES if name in self.source.table_ids())

    def __len__(self):
        return sum(1 for _ in self)


class LiveReader:
    def __init__(self):
        import app
        self.client = app.feishu_client()
        if self.client is None:
            raise RuntimeError('飞书应用未配置，无法实时读取业务数据。')
        self._ids = None
        self._rows = {}
        self._documents = {}
        self._schema = None
        self._meta_lock = threading.RLock()
        self._row_locks = {}
        self.generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def table_ids(self):
        with self._meta_lock:
            if self._ids is None:
                self._ids = {row['name']:row['table_id'] for row in self.client.list_tables()}
        return self._ids

    def table_id(self, name):
        try:
            return self.table_ids()[name]
        except KeyError as exc:
            raise RuntimeError(f'飞书多维表格缺少数据表：{name}') from exc

    def schema(self):
        if self._schema is None:
            self._schema = {'tables':{name:{'table_id':table_id,'name':name,'fields':{
                field['field_name']:{'field_id':field.get('field_id'),'type':field.get('type')}
                for field in self.client.list_fields(table_id)}} for name,table_id in self.table_ids().items()}}
        return self._schema

    def rows(self, name):
        with self._meta_lock:
            lock = self._row_locks.setdefault(name,threading.RLock())
        with lock:
            return self._load_rows(name)

    def _load_rows(self, name):
        if name not in self._rows:
            import app
            started = time.monotonic()
            if name not in self.table_ids() and name in app.OPTIONAL_PAGE_CACHE_TABLES:
                return []
            rows = self.client.list_records(self.table_id(name))
            if name == app.MATERIAL_TABLE_NAME:
                rows = app.material_rows_with_dimension_model_names(rows, self.rows(app.MODEL_TABLE_NAME))
            self._rows[name] = rows
            logging.info('Live source read: table=%s rows=%d seconds=%.3f',name,len(rows),time.monotonic()-started)
        return self._rows[name]

    def prefetch(self, names, *, contacts=False):
        self.table_ids()
        # Prime authentication before dispatching concurrent source reads.
        self.client.tenant_access_token()
        operations = []
        if contacts and 'contact_departments_cache.json' not in self._documents:
            operations.append(lambda:self.document('contact_departments_cache.json'))
        operations.extend(lambda name=name:self.rows(name) for name in dict.fromkeys(names) if name not in self._rows)
        if not operations:
            return
        with ThreadPoolExecutor(max_workers=min(6,len(operations))) as pool:
            futures = [pool.submit(operation) for operation in operations]
            for future in futures:
                future.result()

    def document(self, name):
        if name not in self._documents:
            import app
            if name == 'page_data_cache.json':
                data = {'schema_version':1,'source':'live_feishu','generated_at':self.generated_at,'tables':LiveTables(self)}
            elif name == 'request_form_cache.json':
                materials = self.rows(app.MATERIAL_TABLE_NAME)
                inventory = app.feishu_inventory_dataframe_from_rows(materials,request_visible_only=True)
                options = app.feishu_options_from_rows(self.rows(app.CATEGORY_TABLE_NAME),inventory,
                    self.rows(app.MODEL_TABLE_NAME),self.rows(app.LANGUAGE_TABLE_NAME),materials,request_visible_only=True)
                data = app.request_form_cache_from_inventory(options,inventory,source='live_feishu')
            elif name == 'contact_departments_cache.json':
                data = app.build_live_contact_department_cache()
            elif name == 'warehouse_location_cache.json':
                data = self.warehouse()
            else:
                raise ValueError(f'Unsupported live source document: {name}')
            self._documents[name] = data
        return self._documents[name]

    def warehouse(self):
        import app
        from scripts.generate_warehouse_location_cache import material_summary
        materials = {app.feishu_record_id(row):material_summary(row) for row in self.rows(app.MATERIAL_TABLE_NAME)}
        locations = {app.feishu_record_id(row):row for row in self.rows('仓库物料位置')}
        shelves = []
        for shelf in self.rows('物料货架'):
            fields = app.feishu_fields(shelf)
            if not app.feishu_text(fields,'货架编号'):
                continue
            rows = []
            for rid in app.feishu_link_ids(fields,'关联货架行'):
                location = locations.get(rid)
                if not location:
                    continue
                f = app.feishu_fields(location)
                rows.append({'row_code':app.feishu_text(f,'货架行'),'description':app.feishu_text(f,'放置物料文字说明'),
                    'images':attachment_images('仓库物料位置',location,'图片'),
                    'materials':[materials[mid] for mid in app.feishu_link_ids(f,'关联物料') if mid in materials]})
            shelves.append({'shelf_id':app.feishu_record_id(shelf),'shelf_code':app.feishu_text(fields,'货架编号'),
                'ground_location':app.feishu_text(fields,'货架地面位置'),'description':app.feishu_text(fields,'放置物料'),
                'images':attachment_images('物料货架',shelf,'货架图片'),'rows':rows,
                'materials':[materials[mid] for mid in app.feishu_link_ids(fields,'关联物料') if mid in materials]})
        return {'schema_version':1,'source':'live_feishu','generated_at':self.generated_at,'shelves':shelves}


def reader():
    if not runtime.in_request_scope():
        return LiveReader()
    if '_live_reader' not in runtime.request_state:
        runtime.request_state['_live_reader'] = LiveReader()
    return runtime.request_state['_live_reader']


def document(name):
    return reader().document(name)


IMAGE_FIELDS = {'物料品类':('申领页图片',),'文化周边编码及库存数量':('图片',),
                '物料货架':('货架图片',),'仓库物料位置':('图片',)}


def attachment_images(table, row, field):
    import app
    result = []
    for attachment in app.feishu_attachment_items(app.feishu_fields(row),field):
        if not attachment['name'].lower().endswith(('.png','.jpg','.jpeg','.webp','.gif','.avif','.bmp')):
            continue
        path = '/api/live-image/' + '/'.join(quote(str(value),safe='') for value in (
            table,app.feishu_record_id(row),attachment['file_token']))
        result.append({'path':path,'name':attachment['name']})
    return result


def image_bytes(table, record_id, file_token):
    import app
    if table not in IMAGE_FIELDS:
        raise KeyError('Unsupported image table')
    source = reader()
    row = source.client.get_record(source.table_id(table),record_id)
    allowed = {a['file_token']:a for field in IMAGE_FIELDS[table]
        for a in app.feishu_attachment_items(app.feishu_fields(row),field)}
    if file_token not in allowed:
        raise KeyError('Image is not attached to this record')
    # Bitable download URLs carry record/field permission context required by
    # some attachments; a bare media-token download can return HTTP 400.
    return source.client.download_bitable_attachment(file_token,allowed[file_token]['url'])
