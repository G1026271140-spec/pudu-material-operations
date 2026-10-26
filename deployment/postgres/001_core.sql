BEGIN;
CREATE SCHEMA IF NOT EXISTS material_meta AUTHORIZATION pudu_material_owner;
CREATE SCHEMA IF NOT EXISTS material_data AUTHORIZATION pudu_material_owner;
CREATE SCHEMA IF NOT EXISTS material_ops AUTHORIZATION pudu_material_owner;
SET LOCAL ROLE pudu_material_owner;
CREATE TABLE IF NOT EXISTS material_meta.tables (
 source_key text NOT NULL DEFAULT 'primary', table_id text PRIMARY KEY, table_name text NOT NULL,
 sql_table text UNIQUE NOT NULL, discovered_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS material_meta.fields (
 table_id text NOT NULL REFERENCES material_meta.tables(table_id), field_id text NOT NULL,
 field_name text NOT NULL, field_type integer NOT NULL, sql_column text NOT NULL,
 sql_type text NOT NULL, edit_mode text NOT NULL, definition jsonb NOT NULL,
 PRIMARY KEY(table_id,field_id), UNIQUE(table_id,sql_column)
);
CREATE TABLE IF NOT EXISTS material_ops.outbox (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 idempotency_key text UNIQUE NOT NULL,
 lane text NOT NULL CHECK(lane IN ('ordinary','cultural','admin','notification')),
 table_id text NOT NULL REFERENCES material_meta.tables(table_id), record_key text NOT NULL,
 local_version bigint NOT NULL CHECK(local_version>0), patch jsonb NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','processing','retry','done','conflict')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 claim_token uuid, claimed_by text, lease_until timestamptz,
 available_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz, last_error text,
 UNIQUE(table_id,record_key,local_version)
);
CREATE INDEX IF NOT EXISTS outbox_claim_idx ON material_ops.outbox(lane,available_at,created_at)
 WHERE state IN ('pending','retry');
CREATE INDEX IF NOT EXISTS outbox_record_idx ON material_ops.outbox(table_id,record_key);
CREATE INDEX IF NOT EXISTS outbox_processing_idx ON material_ops.outbox(lease_until) WHERE state='processing';
CREATE TABLE IF NOT EXISTS material_ops.reconcile_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), started_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz, state text NOT NULL CHECK(state IN ('running','done','failed')),
 source_authority text NOT NULL DEFAULT 'feishu' CHECK(source_authority='feishu'),
 summary jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS material_ops.audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 table_id text NOT NULL, record_key text NOT NULL, field_id text,
 source text NOT NULL CHECK(source IN ('frontend','feishu_daily','feishu_event','worker')),
 before_value jsonb, after_value jsonb, local_version bigint,
 reconcile_run uuid REFERENCES material_ops.reconcile_runs(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_record_idx ON material_ops.audit(table_id,record_key,created_at);
CREATE INDEX IF NOT EXISTS audit_run_idx ON material_ops.audit(reconcile_run);
CREATE TABLE IF NOT EXISTS material_ops.media (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), sha256 text NOT NULL, mime_type text NOT NULL,
 filename text NOT NULL, byte_size bigint NOT NULL CHECK(byte_size>0), storage_path text NOT NULL,
 feishu_file_token text, created_at timestamptz NOT NULL DEFAULT now()
);
GRANT USAGE ON SCHEMA material_meta,material_data,material_ops TO gaohongyuan1;
GRANT SELECT ON ALL TABLES IN SCHEMA material_meta TO gaohongyuan1;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA material_data,material_ops TO gaohongyuan1;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA material_ops TO gaohongyuan1;
ALTER DEFAULT PRIVILEGES FOR ROLE pudu_material_owner IN SCHEMA material_data
 GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO gaohongyuan1;
COMMIT;
