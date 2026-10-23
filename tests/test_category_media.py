import importlib
import json
import struct
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
import app
from category_media import category_media_fields
from scripts import submission_worker as worker
from submission_queue import QUEUE_TASK_TYPE_CATEGORY_SYNC, SubmissionTask

web = importlib.import_module("request_web.api")


@pytest.mark.parametrize("media", [{}, {"file_tokens": []}, {"file_tokens": [""]}, {"file_tokens": [1]}, {"file_tokens": ["ok"], "remark": False}])
def test_invalid_media_fails_closed(media):
    with pytest.raises(ValueError): category_media_fields(media)


def test_media_fields_never_write_stock_or_other_business_fields():
    fields=category_media_fields({"file_tokens":["token","token","glb"],"remark":"reference", "当前库存":999})
    assert fields == {"申领页图片":[{"file_token":"token"},{"file_token":"glb"}],"备注":"reference"}


def test_media_retry_keeps_category_write_checkpoint(monkeypatch):
    payload={"sync_args":{},"draft":{},"category_media":{"file_tokens":["glb"]}}
    task=SubmissionTask(record_id="queue",task_id="media",task_type=QUEUE_TASK_TYPE_CATEGORY_SYNC,idempotency_key="media",status="处理中",payload=payload,submitted_at=0,started_at=0,completed_at=0,lease_expires_at=0,retry_count=0,next_retry_at=0,worker_id="test",result={},error="")
    sync=Mock(return_value={"category_record_id":"category-1","target_count":1})
    update=Mock(side_effect=RuntimeError("temporary media failure"))
    monkeypatch.setattr(app,"sync_feishu_category_inventory",sync)
    monkeypatch.setattr(app,"feishu_update_record_fields",update)
    checkpoints=[]
    with pytest.raises(RuntimeError): worker.process_task(task,lambda state:checkpoints.append(deepcopy(state)))
    assert checkpoints[-1]["write_done"] is True
    update.side_effect=None
    retry=SubmissionTask(**{**task.__dict__,"result":checkpoints[-1]})
    result=worker.process_task(retry)
    assert sync.call_count == 1
    assert result["category_record_id"] == "category-1"
    assert update.call_args.args[1] == "category-1"


def test_reviewed_model_requires_category_attachment_and_local_asset(monkeypatch,tmp_path):
    root=tmp_path/"assets/category_models";root.mkdir(parents=True)
    (root/"manifest.json").write_text(json.dumps({"model.glb":{"path":"category_models/model.glb"}}))
    (root/"model.glb").write_bytes(b"test")
    monkeypatch.setattr(web,"ROOT",tmp_path)
    monkeypatch.setattr(web,"_json",lambda _: {"tables":{"物料品类":[
        {"fields":{"物料品类":"积木","申领页图片":[{"name":"model.glb"}]}},
        {"fields":{"物料品类":"不相关品类","申领页图片":[{"name":"unreviewed.glb"}]}}
    ]}})
    assert web._model_index() == {"积木":"/app-assets/category_models/model.glb"}
    (root/"model.glb").unlink()
    assert web._model_index() == {}


def test_generated_glb_is_real_geometry_with_reconstruction_metadata():
    data=(Path(__file__).resolve().parents[1]/"assets/category_models/t300-building-blocks.glb").read_bytes()
    magic,version,size=struct.unpack_from("<III",data)
    assert magic==0x46546C67 and version==2 and size==len(data)
    length,chunk=struct.unpack_from("<II",data,12)
    assert chunk==0x4E4F534A
    model=json.loads(data[20:20+length])
    assert len(model["meshes"])>=10
    assert len(model["materials"])>=10
    assert "images" not in model  # Mesh geometry, not billboards or source photos.
    assert any(scene.get("extras",{}).get("referenceReconstruction") for scene in model["scenes"])
