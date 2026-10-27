"""Create stable-ID projections from an application-identity schema export.

DDL runs as the migration owner, never as the web application's database role.
Original JSON values are retained alongside typed columns for round-trip fidelity.
"""
from __future__ import annotations

from psycopg import sql
from psycopg.types.json import Jsonb

from .field_registry import edit_mode, postgres_type, table_column_names


def register_schema(conn, snapshot: dict) -> dict:
    counts = {"tables": 0, "fields": 0}
    with conn.transaction():
        conn.execute("SET LOCAL ROLE pudu_material_owner")
        for table in snapshot["tables"]:
            table_id = table["table_id"]
            table_sql, _ = table_column_names(table_id, "fldIdentity")
            conn.execute("""INSERT INTO material_meta.tables(source_key,table_id,table_name,sql_table)
                VALUES (%s,%s,%s,%s) ON CONFLICT(table_id) DO UPDATE SET
                source_key=excluded.source_key,table_name=excluded.table_name,discovered_at=now()""",
                (table.get("source", "primary"), table_id, table["table_name"], table_sql))
            conn.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS material_data.{} (
                _record_key text PRIMARY KEY, _remote_id text UNIQUE,
                _fields jsonb NOT NULL DEFAULT '{{}}', _baseline jsonb NOT NULL DEFAULT '{{}}',
                _local_version bigint NOT NULL DEFAULT 0, _synced_version bigint NOT NULL DEFAULT 0,
                _sync_state text NOT NULL DEFAULT 'synced'
                    CHECK(_sync_state IN ('synced','pending','conflict')),
                _deleted boolean NOT NULL DEFAULT false,
                _created_at timestamptz NOT NULL DEFAULT now(),
                _updated_at timestamptz NOT NULL DEFAULT now(), _source_seen_at timestamptz
            )""").format(sql.Identifier(table_sql)))
            for ordinal, field in enumerate(table["fields"]):
                _, column = table_column_names(table_id, field["field_id"])
                kind = postgres_type(int(field["type"]))
                prior = conn.execute("SELECT sql_type FROM material_meta.fields WHERE table_id=%s AND field_id=%s",
                                     (table_id, field["field_id"])).fetchone()
                if prior and prior[0] != kind:
                    raise ValueError(f"Field type changed; explicit conversion required: {table_id}/{field['field_id']}")
                conn.execute(sql.SQL("ALTER TABLE material_data.{} ADD COLUMN IF NOT EXISTS {} {}")
                             .format(sql.Identifier(table_sql), sql.Identifier(column), sql.SQL(kind)))
                conn.execute("""INSERT INTO material_meta.fields
                    (table_id,field_id,field_name,field_type,sql_column,sql_type,edit_mode,definition,ordinal)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(table_id,field_id) DO UPDATE SET field_name=excluded.field_name,field_type=excluded.field_type,
                    edit_mode=excluded.edit_mode,definition=excluded.definition,ordinal=excluded.ordinal""",
                    (table_id, field["field_id"], field["field_name"], int(field["type"]), column,
                     kind, edit_mode(field), Jsonb(field), ordinal))
                counts["fields"] += 1
            counts["tables"] += 1
    return counts


def metadata(conn, table_id: str):
    row = conn.execute("SELECT sql_table FROM material_meta.tables WHERE table_id=%s", (table_id,)).fetchone()
    if not row:
        raise ValueError("Unregistered source table")
    fields = conn.execute("SELECT definition FROM material_meta.fields WHERE table_id=%s ORDER BY ordinal,field_id",
                          (table_id,)).fetchall()
    return row[0], [field[0] for field in fields]
