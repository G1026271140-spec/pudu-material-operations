BEGIN;
SET LOCAL ROLE pudu_material_owner;
ALTER TABLE material_meta.fields ADD COLUMN IF NOT EXISTS ordinal integer NOT NULL DEFAULT 0;
ALTER TABLE material_ops.audit ADD COLUMN IF NOT EXISTS actor_open_id text;
ALTER TABLE material_ops.outbox ADD COLUMN IF NOT EXISTS request_hash text;
ALTER TABLE material_ops.outbox ADD COLUMN IF NOT EXISTS operation text NOT NULL DEFAULT 'update'
 CHECK(operation IN ('update','create'));
CREATE TABLE IF NOT EXISTS material_ops.documents (
 name text PRIMARY KEY, payload jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS material_ops.import_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), started_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz, state text NOT NULL CHECK(state IN ('running','done','failed')),
 summary jsonb NOT NULL DEFAULT '{}'
);
GRANT SELECT,INSERT,UPDATE,DELETE ON material_ops.documents,material_ops.import_runs TO gaohongyuan1;
COMMIT;
