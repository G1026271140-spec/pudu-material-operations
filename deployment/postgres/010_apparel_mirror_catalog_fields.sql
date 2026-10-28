-- Additive registration of the four synced apparel catalog fields.
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('pudu-reconciliation',0));
SET LOCAL ROLE pudu_material_owner;
ALTER TABLE material_data."t_tblOUvklAihp8g34" ADD COLUMN IF NOT EXISTS "f_fldscalEfH" text;
INSERT INTO material_meta.fields (table_id,field_id,field_name,field_type,sql_column,sql_type,edit_mode,definition,ordinal) VALUES ('tblOUvklAihp8g34','fldscalEfH','申领款式编号',1,'f_fldscalEfH','text','直接编辑','{"field_id": "fldscalEfH", "field_name": "申领款式编号", "is_extend": false, "is_primary": false, "is_synced": true, "property": null, "type": 1, "ui_type": "Text"}'::jsonb,17) ON CONFLICT(table_id,field_id) DO NOTHING;
ALTER TABLE material_data."t_tblOUvklAihp8g34" ADD COLUMN IF NOT EXISTS "f_fldafrogkF" text;
INSERT INTO material_meta.fields (table_id,field_id,field_name,field_type,sql_column,sql_type,edit_mode,definition,ordinal) VALUES ('tblOUvklAihp8g34','fldafrogkF','申领显示名称',1,'f_fldafrogkF','text','直接编辑','{"field_id": "fldafrogkF", "field_name": "申领显示名称", "is_extend": false, "is_primary": false, "is_synced": true, "property": null, "type": 1, "ui_type": "Text"}'::jsonb,18) ON CONFLICT(table_id,field_id) DO NOTHING;
ALTER TABLE material_data."t_tblOUvklAihp8g34" ADD COLUMN IF NOT EXISTS "f_fld8ykP0ku" text;
INSERT INTO material_meta.fields (table_id,field_id,field_name,field_type,sql_column,sql_type,edit_mode,definition,ordinal) VALUES ('tblOUvklAihp8g34','fld8ykP0ku','申领页显示',3,'f_fld8ykP0ku','text','直接编辑','{"field_id": "fld8ykP0ku", "field_name": "申领页显示", "is_extend": false, "is_primary": false, "is_synced": true, "property": {"options": [{"color": 0, "id": "opteGD58rD", "name": "是"}, {"color": 1, "id": "optUMna4aR", "name": "否"}]}, "type": 3, "ui_type": "SingleSelect"}'::jsonb,19) ON CONFLICT(table_id,field_id) DO NOTHING;
ALTER TABLE material_data."t_tblOUvklAihp8g34" ADD COLUMN IF NOT EXISTS "f_fldtQW0HM8" numeric;
INSERT INTO material_meta.fields (table_id,field_id,field_name,field_type,sql_column,sql_type,edit_mode,definition,ordinal) VALUES ('tblOUvklAihp8g34','fldtQW0HM8','每人累计领取上限',2,'f_fldtQW0HM8','numeric','直接编辑','{"field_id": "fldtQW0HM8", "field_name": "每人累计领取上限", "is_extend": false, "is_primary": false, "is_synced": true, "property": {"formatter": "0"}, "type": 2, "ui_type": "Number"}'::jsonb,20) ON CONFLICT(table_id,field_id) DO NOTHING;
COMMIT;
