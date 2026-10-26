"""Real PostgreSQL checks; only the explicitly named test database is allowed."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from PIL import Image

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.types.json import Jsonb

from material_store.field_registry import JSON_TYPES, DATETIME_TYPES

DSN = os.environ.get("PUDU_TEST_DATABASE_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="Requires the isolated VM PostgreSQL test database")


@pytest.fixture
def conn():
    with psycopg.connect(DSN, autocommit=True) as opened:
        assert opened.execute("SELECT current_database()").fetchone()[0] == "pudu_materials_test"
        yield opened


def test_all_registered_fields_round_trip_typed_values_without_changing_source_json(conn):
    count = 0
    with pytest.raises(RuntimeError, match="rollback_projection_test"):
        # A nested explicit rollback sentinel leaves no business-like test rows.
        with conn.transaction():
            tables = conn.execute("SELECT table_id,sql_table FROM material_meta.tables").fetchall()
            for table_id, table_name in tables:
                fields = conn.execute("SELECT field_id,field_type,sql_column FROM material_meta.fields WHERE table_id=%s ORDER BY field_id",
                                      (table_id,)).fetchall()
                columns, values, raw = [], [], {}
                for field_id, kind, column in fields:
                    if kind in JSON_TYPES:
                        original = [{"id": "test-id", "text": "多值原文"}]
                        value = Jsonb(original)
                    elif kind in DATETIME_TYPES:
                        original = 1792987200123
                        value = datetime.fromtimestamp(original / 1000, timezone.utc)
                    elif kind == 2:
                        original, value = "123.456700", Decimal("123.456700")
                    elif kind == 7:
                        original = value = False
                    else:
                        original = value = "字段原文与单引号'保留"
                    columns.append(sql.Identifier(column))
                    values.append(value)
                    raw[field_id] = original
                key = "field-roundtrip-" + uuid4().hex
                query = sql.SQL("INSERT INTO material_data.{} ({}) VALUES ({})").format(
                    sql.Identifier(table_name), sql.SQL(",").join([sql.Identifier("_record_key"), sql.Identifier("_fields")] + columns),
                    sql.SQL(",").join(sql.Placeholder() for _ in range(len(values) + 2)))
                conn.execute(query, [key, Jsonb(raw)] + values)
                result = conn.execute(sql.SQL("SELECT _fields,{} FROM material_data.{} WHERE _record_key=%s")
                                      .format(sql.SQL(",").join(columns), sql.Identifier(table_name)), (key,)).fetchone()
                assert result[0] == raw
                for expected, actual in zip(values, result[1:]):
                    assert actual == (expected.obj if isinstance(expected, Jsonb) else expected)
                count += len(fields)
            assert count == 358
            raise RuntimeError("rollback_projection_test")


def test_application_role_cannot_modify_schema_or_metadata(conn):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("CREATE TABLE material_data.should_not_exist(id integer)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE material_meta.fields SET field_name='wrong' WHERE false")
    links = conn.execute("SELECT DISTINCT edit_mode FROM material_meta.fields WHERE field_type=18").fetchall()
    assert links == [("选择关联记录",)]


def test_local_image_and_six_concurrent_worker_retries_upload_once(conn, monkeypatch, tmp_path):
    from material_store import db, media
    monkeypatch.setenv("PUDU_DATABASE_DSN", DSN)
    monkeypatch.setenv("PUDU_MEDIA_ROOT", str(tmp_path))
    db.pool.cache_clear()
    stream = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(stream, "PNG")
    result = media.save_image(stream.getvalue(), "本地图片.png", "isolated-test")
    client = Mock()
    client.upload_media.return_value = "test-remote-token"
    try:
        with ThreadPoolExecutor(max_workers=6) as workers:
            tokens = list(workers.map(lambda _: media.remote_token(result["local_media_id"], client), range(6)))
        assert tokens == ["test-remote-token"] * 6
        assert client.upload_media.call_count == 1
        assert media.load_image(result["local_media_id"])["file_token"] == "test-remote-token"
    finally:
        conn.execute("DELETE FROM material_ops.media WHERE id=%s", (result["local_media_id"],))
        db.pool().close()
        db.pool.cache_clear()
