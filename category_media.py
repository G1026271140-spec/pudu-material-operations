"""Optional category media writes, executed as a checkpointed queue step."""
from __future__ import annotations


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

    app.feishu_update_record_fields(app.CATEGORY_TABLE_NAME, record_id, category_media_fields(media))
