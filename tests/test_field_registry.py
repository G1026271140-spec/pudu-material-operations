from datetime import timezone
from decimal import Decimal
import pytest
from material_store.field_registry import table_column_names,postgres_type,typed_value,validate_patch,edit_mode


def test_identity_mapping_survives_field_renames_and_rejects_sql_injection():
    assert table_column_names('tblAb12','fldCd34')==('t_tblAb12','f_fldCd34')
    with pytest.raises(ValueError):table_column_names('tblAb;DROP TABLE x','fldCd34')


def test_typed_projection_keeps_source_precision_and_timestamp():
    assert typed_value(2,'1.2500')==Decimal('1.2500')
    assert typed_value(5,0).tzinfo==timezone.utc
    assert typed_value(1,[{'text':'第一行'},{'text':'第二行'}])=='第一行第二行'
    assert postgres_type(17)=='jsonb'


def test_formula_is_edited_through_sources_and_attachments_can_be_cleared():
    fields=[{'field_id':'fld1','type':20},{'field_id':'fld2','type':17}]
    assert edit_mode(fields[0])=='修改源字段后计算'
    with pytest.raises(ValueError):validate_patch(fields,{'fld1':10})
    assert validate_patch(fields,{'fld2':[]})
    assert validate_patch(fields,{'fld2':[{'local_media_id':'image-1'}]})


def test_unknown_options_and_wrong_checkbox_types_are_rejected_before_writes():
    fields=[{'field_id':'fld1','type':3,'property':{'options':[{'name':'启用'}]}}, {'field_id':'fld2','type':7}]
    with pytest.raises(ValueError):validate_patch(fields,{'fld1':'新选项'})
    with pytest.raises(ValueError):validate_patch(fields,{'fld2':'是'})


def test_single_and_duplex_links_are_editable_but_lookup_is_not():
    fields=[{'field_id':'fld1','type':18,'property':{'multiple':False}},
            {'field_id':'fld2','type':21}, {'field_id':'fld3','type':19}]
    assert validate_patch(fields,{'fld1':['recA'],'fld2':['recA','recB']})
    assert edit_mode(fields[0])=='选择关联记录'
    with pytest.raises(ValueError):validate_patch(fields,{'fld1':['recA','recB']})
    with pytest.raises(ValueError):validate_patch(fields,{'fld3':[]})
