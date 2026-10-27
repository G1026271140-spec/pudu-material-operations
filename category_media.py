"""Optional category media writes, executed as a checkpointed queue step."""
from __future__ import annotations

from uuid import UUID


def is_image(attachment: dict) -> bool:
    return str(attachment.get("name") or "").lower().endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp"))


def validate_image_selection(media: dict) -> None:
    images = media.get("images")
    expected = media.get("expected_image_tokens")
    if not isinstance(images, list) or len(images) > 12:
        raise ValueError("品类图片最多为 12 张，可全部移除。")
    if not isinstance(expected, list) or not all(isinstance(x, str) and x for x in expected):
        raise ValueError("缺少原图片版本，请刷新品类后重试。")
    for item in images:
        if not isinstance(item, dict) or bool(item.get("file_token")) == bool(item.get("local_media_id")):
            raise ValueError("图片须指定现有附件或已上传的本地图片。")
        if item.get("file_token"):
            if item["file_token"] not in expected:
                raise ValueError("所选图片不属于当前品类。")
        else:
            try:
                UUID(item["local_media_id"])
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("本地图片标识无效。") from exc


def category_media_fields(media: dict) -> dict:
    tokens = media.get("file_tokens")
    if not isinstance(tokens, list) or not tokens or len(tokens) > 12:
        raise ValueError("品类媒体必须包含 1 至 12 个已上传附件。")
    if any(not isinstance(token, str) or not token.strip() or len(token) > 256 for token in tokens):
        raise ValueError("品类媒体附件标识无效。")
    fields = {"申领页图片": [{"file_token": token} for token in dict.fromkeys(tokens)]}
    if "remark" in media:
        if not isinstance(media["remark"], str):
            raise ValueError("品类备注必须为文本。")
        fields["备注"] = media["remark"]
    return fields


def apply_category_media(record_id: str, media: dict) -> None:
    if not record_id:
        raise ValueError("未取得品类记录，不能写入媒体。")
    import app

    if "images" not in media:
        app.feishu_update_record_fields(app.CATEGORY_TABLE_NAME, record_id, category_media_fields(media))
        return
    validate_image_selection(media)
    import backend_runtime as runtime
    if runtime.database_reads():
        client=app.feishu_client()
        row=client.get_record(app.feishu_table_id(app.CATEGORY_TABLE_NAME),record_id)
        attachments=list(app.feishu_fields(row).get('申领页图片') or [])
        identity=lambda item:item.get('file_token') or item.get('local_media_id')
        current=[identity(item) for item in attachments if is_image(item) or item.get('local_media_id')]
        desired=[identity(item) for item in media['images']]
        if current!=media['expected_image_tokens'] and current!=desired:
            raise ValueError('品类图片已发生变化，请刷新后重新编辑。')
        from material_store.media import load_image
        images=[]
        for item in media['images']:
            if item.get('local_media_id'):
                local=load_image(item['local_media_id'],conn=runtime.request_state['_write_conn'])
                images.append({**item,'name':local['name'],'type':local['type']})
            else:
                images.append(next(a for a in attachments if a.get('file_token')==item['file_token']))
        app.feishu_update_record_fields(app.CATEGORY_TABLE_NAME,record_id,
            {'申领页图片':[a for a in attachments if not is_image(a) and not a.get('local_media_id')]+images})
        return
    from material_store.media import remote_token
    client = app.feishu_client()
    row = client.get_record(app.feishu_table_id(app.CATEGORY_TABLE_NAME), record_id)
    attachments = app.feishu_attachment_items(app.feishu_fields(row), "申领页图片")
    current = [item["file_token"] for item in attachments if is_image(item)]
    # Resolve new images once and retain upload tokens across task retries.
    desired = list(dict.fromkeys(item.get("file_token") or remote_token(item["local_media_id"], client)
                                 for item in media["images"]))
    if current != media["expected_image_tokens"] and current != desired:
        raise ValueError("品类图片已发生变化，请刷新后重新编辑，避免覆盖其他修改。")
    other = [item["file_token"] for item in attachments if not is_image(item)]
    fields = {"申领页图片": [{"file_token": token} for token in other + desired]}
    app.feishu_update_record_fields(app.CATEGORY_TABLE_NAME, record_id, fields)
