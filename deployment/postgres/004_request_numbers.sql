BEGIN;
SET LOCAL ROLE pudu_material_owner;
CREATE TABLE IF NOT EXISTS material_ops.request_numbers (
  day char(8) PRIMARY KEY,
  last_number integer NOT NULL CHECK(last_number>0)
);
GRANT SELECT,INSERT,UPDATE ON material_ops.request_numbers TO gaohongyuan1;
COMMIT;
