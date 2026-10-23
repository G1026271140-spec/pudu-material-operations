from event_translation_sync import selected_source, source_hash, translate_fixed


def test_selects_only_configured_regions():
    records = [
        {"record_id": "a", "战区 | Region": ["美洲战区"]},
        {"record_id": "b", "战区 | Region": ["欧洲战区"]},
        {"record_id": "c", "战区 | Region": "拉美战队"},
    ]
    assert [row["record_id"] for row in selected_source(records)] == ["a", "c"]


def test_hash_changes_when_mapped_field_changes():
    before = {"活动名称 | Event Name": "A"}
    after = {"活动名称 | Event Name": "B"}
    assert source_hash(before) != source_hash(after)


def test_fixed_translation_preserves_models_and_maps_known_values():
    assert translate_fixed(["CR", "新项目"]) == ["CR", "New Project"]
    assert translate_fixed("澳新战队") == "Australia & New Zealand Region"
    assert translate_fixed(1794844800000) == 1794844800000
    assert translate_fixed({"text": "美国Promat", "type": "text"}) == "美国Promat"
