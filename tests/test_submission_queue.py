from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import app
import submission_queue as queue


class FakeQueueClient:
    def __init__(self) -> None:
        self.tables: list[dict] = []
        self.fields: dict[str, list[dict]] = {}
        self.records: dict[str, list[dict]] = {}
        self.updates: list[tuple[str, str, dict]] = []
        self.list_tables_count = 0

    def list_tables(self) -> list[dict]:
        self.list_tables_count += 1
        return list(self.tables)

    def create_table(
        self,
        table_name: str,
        fields: list[dict],
        *,
        default_view_name: str,
    ) -> dict:
        table_id = "tbl-queue"
        self.tables.append({"table_id": table_id, "name": table_name})
        self.fields[table_id] = [
            {"field_name": field["field_name"], "type": field["type"]}
            for field in fields
        ]
        self.records[table_id] = []
        return {"table_id": table_id}

    def list_fields(self, table_id: str) -> list[dict]:
        return list(self.fields.get(table_id, []))

    def create_field(self, table_id: str, field_name: str, field_type: int) -> dict:
        field = {"field_name": field_name, "type": field_type}
        self.fields.setdefault(table_id, []).append(field)
        return field

    def list_records(self, table_id: str, page_size: int = 500) -> list[dict]:
        return [
            {"record_id": record["record_id"], "fields": dict(record["fields"])}
            for record in self.records.get(table_id, [])
        ]

    def batch_create_records(self, table_id: str, records: list[dict]) -> list[dict]:
        created: list[dict] = []
        for fields in records:
            record = {
                "record_id": f"rec-{len(self.records.setdefault(table_id, [])) + 1}",
                "fields": dict(fields),
            }
            self.records[table_id].append(record)
            created.append({"record_id": record["record_id"]})
        return created

    def update_record(self, table_id: str, record_id: str, fields: dict) -> dict:
        self.updates.append((table_id, record_id, dict(fields)))
        record = next(
            record
            for record in self.records[table_id]
            if record["record_id"] == record_id
        )
        for key, value in fields.items():
            if value is None:
                record["fields"].pop(key, None)
            else:
                record["fields"][key] = value
        return {"record_id": record_id, "fields": dict(record["fields"])}


class SubmissionQueueTests(unittest.TestCase):
    def test_queue_table_is_created_with_recovery_fields(self) -> None:
        client = FakeQueueClient()

        table_id = queue.ensure_submission_queue_table(client)

        self.assertEqual(table_id, "tbl-queue")
        self.assertEqual(client.tables[0]["name"], queue.QUEUE_TABLE_NAME)
        field_names = {field["field_name"] for field in client.fields[table_id]}
        self.assertEqual(field_names, {name for name, _ in queue.QUEUE_FIELDS})

        self.assertEqual(queue.ensure_submission_queue_table(client), table_id)
        self.assertEqual(client.list_tables_count, 1)

    def test_enqueue_is_idempotent_when_create_returns_only_record_id(self) -> None:
        client = FakeQueueClient()

        first, first_created = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_MATERIAL_REQUEST,
            "token-1",
            {"version": 1},
        )
        second, second_created = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_MATERIAL_REQUEST,
            "token-1",
            {"version": 1},
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.task_id, second.task_id)
        self.assertEqual(len(client.records["tbl-queue"]), 1)

    def test_claim_retries_and_completes_with_persistent_state(self) -> None:
        client = FakeQueueClient()
        queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_MATERIAL_REQUEST,
            "token-2",
            {"version": 1},
        )

        claimed = queue.claim_next_submission_task(
            client,
            "worker-a",
            lease_seconds=60,
            now_ms=1_000_000,
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.status, queue.QUEUE_STATUS_PROCESSING)
        self.assertEqual(claimed.lease_expires_at, 1_060_000)

        status = queue.fail_submission_task(
            client,
            claimed,
            RuntimeError("temporary"),
            now_ms=1_000_000,
        )
        self.assertEqual(status, queue.QUEUE_STATUS_RETRY)
        retry_task = queue.list_submission_tasks(client)[0]
        self.assertEqual(retry_task.retry_count, 1)
        self.assertEqual(retry_task.next_retry_at, 1_005_000)

        reclaimed = queue.claim_next_submission_task(
            client,
            "worker-b",
            now_ms=1_005_000,
        )
        assert reclaimed is not None
        queue.complete_submission_task(
            client,
            reclaimed,
            {"request_no": "REQ-1"},
            completed_at=1_006_000,
        )
        completed = queue.list_submission_tasks(client)[0]
        self.assertEqual(completed.status, queue.QUEUE_STATUS_COMPLETED)
        self.assertEqual(completed.result["request_no"], "REQ-1")

    def test_checkpoint_persists_recovery_progress(self) -> None:
        client = FakeQueueClient()
        task, _ = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_MATERIAL_REQUEST,
            "token-checkpoint",
            {"version": 1},
        )

        updated = queue.checkpoint_submission_task(
            client,
            task,
            {"request_no": "REQ-2", "admin_notification_done": True},
        )

        self.assertEqual(updated.result["request_no"], "REQ-2")
        persisted = queue.list_submission_tasks(client)[0]
        self.assertTrue(persisted.result["admin_notification_done"])

    def test_queued_request_uploads_files_once_and_removes_binary_content(self) -> None:
        client = MagicMock()
        client.upload_media.return_value = "file-token-1"
        request_payload = {
            "submission_token": "token-3",
            "requester": "销售甲",
            "attachments": [
                {
                    "name": "address.pdf",
                    "content": b"binary",
                    "content_type": "application/pdf",
                }
            ],
        }

        with patch.object(app, "feishu_client", return_value=client):
            payload = app.queued_material_request_payload(
                request_payload,
                [
                    {
                        "product": "产品单页",
                        "model": "BellaBot",
                        "language": "英语",
                        "quantity": 2,
                        "remark": "",
                    }
                ],
            )

        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("binary", serialized)
        request = dict(payload["request_payload"])
        attachment = list(request["attachments"])[0]
        self.assertEqual(attachment["file_token"], "file-token-1")
        client.upload_media.assert_called_once()


if __name__ == "__main__":
    unittest.main()
