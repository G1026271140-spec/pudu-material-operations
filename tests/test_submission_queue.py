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
        self.list_records_count = 0
        self.search_records_count = 0
        self.get_record_count = 0

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
        table_id = {
            queue.QUEUE_TABLE_NAME: "tbl-queue",
            queue.QUEUE_PAYLOAD_TABLE_NAME: "tbl-payload",
            queue.WORKER_REGISTRY_TABLE_NAME: "tbl-workers",
        }[table_name]
        self.tables.append({"table_id": table_id, "name": table_name})
        self.fields[table_id] = [
            dict(field)
            for field in fields
        ]
        self.records[table_id] = []
        return {"table_id": table_id}

    def list_fields(self, table_id: str) -> list[dict]:
        return list(self.fields.get(table_id, []))

    def create_field(
        self,
        table_id: str,
        field_name: str,
        field_type: int,
        property: dict | None = None,
    ) -> dict:
        field = {"field_name": field_name, "type": field_type}
        if property is not None:
            field["property"] = property
        self.fields.setdefault(table_id, []).append(field)
        return field

    def list_records(self, table_id: str, page_size: int = 500) -> list[dict]:
        self.list_records_count += 1
        return [
            {"record_id": record["record_id"], "fields": dict(record["fields"])}
            for record in self.records.get(table_id, [])
        ]

    def get_record(self, table_id: str, record_id: str) -> dict:
        self.get_record_count += 1
        record = next(
            record
            for record in self.records.get(table_id, [])
            if record["record_id"] == record_id
        )
        return {"record_id": record["record_id"], "fields": dict(record["fields"])}

    def search_records(
        self,
        table_id: str,
        field_name: str,
        value: str,
        *,
        page_size: int = 100,
    ) -> list[dict]:
        del page_size
        self.search_records_count += 1
        return [
            {"record_id": record["record_id"], "fields": dict(record["fields"])}
            for record in self.records.get(table_id, [])
            if str(record["fields"].get(field_name) or "") == value
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

    def create_record(self, table_id: str, fields: dict) -> dict:
        return self.batch_create_records(table_id, [fields])[0]

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

    def batch_update_records(self, table_id: str, records: list[dict]) -> list[dict]:
        return [
            self.update_record(table_id, str(record["record_id"]), dict(record["fields"]))
            for record in records
        ]


class SubmissionQueueTests(unittest.TestCase):
    def test_enqueue_retries_when_feishu_data_is_not_ready(self) -> None:
        client = FakeQueueClient()
        original_get_record = client.get_record
        record_reads = 0

        def get_record(table_id: str, record_id: str) -> dict:
            nonlocal record_reads
            record_reads += 1
            if record_reads == 1:
                raise RuntimeError("Feishu HTTP 400: code=1254607 Data not ready, please try again later")
            return original_get_record(table_id, record_id)

        client.get_record = get_record  # type: ignore[method-assign]
        with patch.object(queue.time, "sleep") as sleep:
            task, created = queue.enqueue_submission_task(
                client,
                queue.QUEUE_TASK_TYPE_DIMENSION_MANAGEMENT,
                "dimension-delete-token",
                {"draft": {"operation": "delete"}},
            )

        self.assertTrue(created)
        self.assertTrue(task.task_id)
        sleep.assert_called_once_with(0.5)

    def test_queue_table_is_created_with_recovery_fields(self) -> None:
        client = FakeQueueClient()

        table_id = queue.ensure_submission_queue_table(client)

        self.assertEqual(table_id, "tbl-queue")
        self.assertEqual(client.tables[0]["name"], queue.QUEUE_TABLE_NAME)
        field_names = {field["field_name"] for field in client.fields[table_id]}
        self.assertEqual(field_names, {name for name, _ in queue.QUEUE_FIELDS})
        self.assertEqual(client.tables[1]["name"], queue.QUEUE_PAYLOAD_TABLE_NAME)
        self.assertEqual(client.tables[2]["name"], queue.WORKER_REGISTRY_TABLE_NAME)
        completion_field = next(
            field
            for field in client.fields[table_id]
            if field["field_name"] == queue.QUEUE_FIELD_COMPLETION_STATUS
        )
        self.assertEqual(completion_field["type"], 3)
        self.assertEqual(
            [item["name"] for item in completion_field["property"]["options"]],
            [queue.QUEUE_COMPLETION_UNFINISHED, queue.QUEUE_COMPLETION_COMPLETED],
        )
        worker_fields = {
            field["field_name"]: field for field in client.fields["tbl-workers"]
        }
        self.assertEqual(worker_fields[queue.WORKER_FIELD_STATUS]["type"], 3)
        self.assertEqual(worker_fields[queue.WORKER_FIELD_ENABLED]["type"], 3)

        self.assertEqual(queue.ensure_submission_queue_table(client), table_id)
        self.assertEqual(client.list_tables_count, 3)

    def test_worker_registry_selects_lowest_priority_healthy_node(self) -> None:
        client = FakeQueueClient()
        queue.ensure_submission_queue_table(client)

        first_is_leader, _ = queue.update_worker_heartbeat(
            client, "primary", "PC-1", 1, "V1.2.0", now_ms=100_000
        )
        second_is_leader, leader_id = queue.update_worker_heartbeat(
            client, "standby", "PC-2", 100, "V1.2.0", now_ms=100_100
        )

        self.assertTrue(first_is_leader)
        self.assertFalse(second_is_leader)
        self.assertEqual(leader_id, "primary")

    def test_worker_registry_fails_over_after_primary_heartbeat_expires(self) -> None:
        client = FakeQueueClient()
        queue.ensure_submission_queue_table(client)
        queue.update_worker_heartbeat(
            client, "primary", "PC-1", 1, "V1.2.0", now_ms=100_000
        )

        is_leader, leader_id = queue.update_worker_heartbeat(
            client,
            "standby",
            "PC-2",
            100,
            "V1.2.0",
            now_ms=200_000,
            heartbeat_timeout_seconds=90,
        )

        self.assertTrue(is_leader)
        self.assertEqual(leader_id, "standby")

    def test_large_payload_is_chunked_and_read_back_exactly(self) -> None:
        client = FakeQueueClient()
        payload = {"sync_args": {"rows": ["物料数据" * 1000 for _ in range(20)]}}

        task, created = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_CATEGORY_SYNC,
            "large-token",
            payload,
        )

        self.assertTrue(created)
        self.assertEqual(task.payload, payload)
        self.assertGreater(len(client.records["tbl-payload"]), 1)
        persisted = queue.list_submission_tasks(client)[0]
        self.assertEqual(persisted.payload, payload)

    def test_enqueue_fast_path_avoids_full_table_reads(self) -> None:
        client = FakeQueueClient()

        task, created = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_MATERIAL_REQUEST,
            "fast-token",
            {"version": 1},
        )

        self.assertTrue(created)
        self.assertEqual(task.payload, {"version": 1})
        self.assertEqual(client.list_records_count, 0)
        self.assertEqual(client.get_record_count, 1)
        self.assertEqual(client.search_records_count, 2)

    def test_payload_verification_uses_json_normalized_collections(self) -> None:
        client = FakeQueueClient()
        payload = {"sync_args": {"selection": ("型号", "中文")}}

        task, created = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_CATEGORY_SYNC,
            "tuple-token",
            payload,
        )

        self.assertTrue(created)
        self.assertEqual(task.payload["sync_args"]["selection"], ["型号", "中文"])

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
        self.assertEqual(
            claimed.completion_status,
            queue.QUEUE_COMPLETION_UNFINISHED,
        )
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
        self.assertEqual(
            completed.completion_status,
            queue.QUEUE_COMPLETION_COMPLETED,
        )
        self.assertEqual(completed.result["request_no"], "REQ-1")

    def test_completed_marker_prevents_reclaim_even_if_technical_status_is_pending(self) -> None:
        client = FakeQueueClient()
        task, _ = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_MATERIAL_REQUEST,
            "marker-token",
            {"version": 1},
        )
        client.update_record(
            "tbl-queue",
            task.record_id,
            {
                queue.QUEUE_FIELD_STATUS: queue.QUEUE_STATUS_PENDING,
                queue.QUEUE_FIELD_COMPLETION_STATUS: queue.QUEUE_COMPLETION_COMPLETED,
            },
        )

        self.assertIsNone(queue.claim_next_submission_task(client, "worker-a"))

    def test_claim_refuses_task_when_another_worker_owns_verified_lease(self) -> None:
        client = FakeQueueClient()
        queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_CULTURAL_REQUEST,
            "parallel-token",
            {"version": 1},
        )
        original_get_record = client.get_record

        def get_record(table_id: str, record_id: str) -> dict:
            record = original_get_record(table_id, record_id)
            if record["fields"].get(queue.QUEUE_FIELD_STATUS) == queue.QUEUE_STATUS_PROCESSING:
                record["fields"][queue.QUEUE_FIELD_WORKER_ID] = "worker-b"
            return record

        client.get_record = get_record  # type: ignore[method-assign]

        self.assertIsNone(
            queue.claim_next_submission_task(
                client,
                "worker-a",
                lease_seconds=60,
                now_ms=1_000_000,
            )
        )

    def test_fifo_order_is_stable_for_simultaneous_submissions(self) -> None:
        client = FakeQueueClient()
        first, _ = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_MATERIAL_REQUEST,
            "material-token",
            {"version": 1},
        )
        second, _ = queue.enqueue_submission_task(
            client,
            queue.QUEUE_TASK_TYPE_CULTURAL_REQUEST,
            "culture-token",
            {"version": 1},
        )
        for row in client.records["tbl-queue"]:
            row["fields"][queue.QUEUE_FIELD_SUBMITTED_AT] = 1_000_000

        expected = min((first, second), key=lambda item: item.task_id)
        claimed = queue.claim_next_submission_task(
            client,
            "worker-a",
            now_ms=1_000_001,
        )

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.task_id, expected.task_id)

    def test_legacy_queue_rows_receive_completion_marker(self) -> None:
        client = FakeQueueClient()
        queue.ensure_submission_queue_table(client)
        client.records["tbl-queue"] = [
            {
                "record_id": "rec-done",
                "fields": {
                    queue.QUEUE_FIELD_TASK_ID: "done",
                    queue.QUEUE_FIELD_STATUS: queue.QUEUE_STATUS_COMPLETED,
                    queue.QUEUE_FIELD_PAYLOAD: "{}",
                },
            },
            {
                "record_id": "rec-pending",
                "fields": {
                    queue.QUEUE_FIELD_TASK_ID: "pending",
                    queue.QUEUE_FIELD_STATUS: queue.QUEUE_STATUS_PENDING,
                    queue.QUEUE_FIELD_PAYLOAD: "{}",
                },
            },
        ]

        count = queue.backfill_submission_completion_status(client)

        self.assertEqual(count, 2)
        values = {
            row["record_id"]: row["fields"][queue.QUEUE_FIELD_COMPLETION_STATUS]
            for row in client.records["tbl-queue"]
        }
        self.assertEqual(values["rec-done"], queue.QUEUE_COMPLETION_COMPLETED)
        self.assertEqual(values["rec-pending"], queue.QUEUE_COMPLETION_UNFINISHED)

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

    def test_queued_request_ignores_legacy_attachment_content(self) -> None:
        client = MagicMock()
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
        self.assertNotIn("attachments", request)
        client.upload_media.assert_not_called()


if __name__ == "__main__":
    unittest.main()
