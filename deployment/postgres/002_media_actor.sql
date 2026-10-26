BEGIN;
SET LOCAL ROLE pudu_material_owner;
ALTER TABLE material_ops.media ADD COLUMN IF NOT EXISTS owner_open_id text;
COMMIT;
