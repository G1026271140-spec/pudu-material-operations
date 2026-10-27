BEGIN;
SET LOCAL ROLE pudu_material_owner;
CREATE TABLE IF NOT EXISTS material_ops.jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), idempotency_key text NOT NULL UNIQUE,
 task_type text NOT NULL, lane text NOT NULL CHECK(lane IN ('ordinary','cultural','admin','card')),
 payload jsonb NOT NULL, result jsonb NOT NULL DEFAULT '{}',
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','done','retry','failed')),
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, last_error text
);
CREATE INDEX IF NOT EXISTS jobs_ready ON material_ops.jobs(lane,available_at,created_at)
 WHERE state IN ('pending','retry');
CREATE TABLE IF NOT EXISTS material_ops.effects (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL REFERENCES material_ops.jobs(id),
 ordinal integer NOT NULL, source_key text NOT NULL, method text NOT NULL, args jsonb NOT NULL, kwargs jsonb NOT NULL,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','processing','done','retry','failed')),
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 first_attempt_at timestamptz,
 claim_token uuid, lease_until timestamptz, remote_id text,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, last_error text,
 UNIQUE(job_id,ordinal)
);
ALTER TABLE material_ops.effects ADD COLUMN IF NOT EXISTS first_attempt_at timestamptz;
CREATE INDEX IF NOT EXISTS effects_ready ON material_ops.effects(available_at,created_at)
 WHERE state IN ('pending','retry','processing');
ALTER TABLE material_ops.outbox DROP CONSTRAINT IF EXISTS outbox_state_check;
ALTER TABLE material_ops.outbox ADD CONSTRAINT outbox_state_check CHECK(state IN ('pending','processing','done','retry','conflict','cancelled'));
ALTER TABLE material_ops.outbox DROP CONSTRAINT IF EXISTS outbox_operation_check;
ALTER TABLE material_ops.outbox ADD CONSTRAINT outbox_operation_check CHECK(operation IN ('create','update','delete'));
ALTER TABLE material_ops.outbox ADD COLUMN IF NOT EXISTS job_id text
 DEFAULT NULLIF(current_setting('pudu.job_id',true),'');
GRANT SELECT,INSERT,UPDATE,DELETE ON material_ops.jobs,material_ops.effects TO gaohongyuan1;
COMMIT;
