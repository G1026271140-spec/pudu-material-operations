BEGIN;
SET LOCAL ROLE pudu_material_owner;
ALTER TABLE material_ops.outbox ADD COLUMN IF NOT EXISTS ordinal bigint GENERATED ALWAYS AS IDENTITY;
CREATE INDEX IF NOT EXISTS outbox_lane_order_idx ON material_ops.outbox(lane,ordinal)
 WHERE state IN ('pending','retry','processing');
COMMIT;
