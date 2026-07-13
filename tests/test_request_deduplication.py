from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import app


REQUEST_NO = "\u7533\u8bf7\u5355\u53f7"
SUBMISSION_TOKEN = "\u63d0\u4ea4\u5e42\u7b49\u952e"


def request_row(record_id: str, request_no: str, token: str, submitted_at: int) -> dict:
    return {
        "record_id": record_id,
        "fields": {
            REQUEST_NO: request_no,
            SUBMISSION_TOKEN: token,
            "\u63d0\u4ea4\u65f6\u95f4": submitted_at,
        },
    }


class RequestDeduplicationTests(unittest.TestCase):
    def test_request_lines_prefer_relation_over_same_request_number(self) -> None:
        request = {"record_id": "request-a", "request_no": "REQ-1"}
        lines = [
            {"record_id": "line-a", "request_ids": ["request-a"], "request_no": "REQ-1"},
            {"record_id": "line-b", "request_ids": ["request-b"], "request_no": "REQ-1"},
            {"record_id": "line-legacy", "request_ids": [], "request_no": "REQ-1"},
        ]

        result = app.request_lines_for_request(request, lines)

        self.assertEqual([line["record_id"] for line in result], ["line-a", "line-legacy"])

    def test_next_request_number_reads_fresh_rows(self) -> None:
        today = datetime.now().strftime("%Y%m%d")
        rows = [request_row("request-a", f"REQ-{today}-003", "", 1)]

        with patch.object(app, "fresh_feishu_rows", return_value=rows) as fresh_rows:
            result = app.next_request_no()

        self.assertEqual(result, f"REQ-{today}-004")
        fresh_rows.assert_called_once_with(app.REQUEST_TABLE_NAME)

    def test_completed_submission_reuses_existing_request(self) -> None:
        row = request_row("request-a", "REQ-1", "token-1", 1)
        with (
            patch.object(app, "submission_token_rows", return_value=[row]),
            patch.object(app, "request_line_rows_by_request_id", return_value=([], {"request-a": [{}, {}]})),
        ):
            result = app.find_completed_submission("token-1")

        self.assertEqual(result, (row, 2))

    def test_concurrent_distinct_submission_gets_new_request_number(self) -> None:
        client = Mock()
        rows = [
            request_row("request-a", "REQ-1", "token-a", 1),
            request_row("request-b", "REQ-1", "token-b", 2),
        ]
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "fresh_feishu_rows", return_value=rows),
            patch.object(app, "next_request_no", return_value="REQ-2"),
            patch.object(app, "feishu_table_id", return_value="request-table"),
        ):
            result = app.ensure_unique_request_no("request-b", "REQ-1", "token-b")

        self.assertEqual(result, "REQ-2")
        client.update_record.assert_called_once_with(
            "request-table",
            "request-b",
            {REQUEST_NO: "REQ-2"},
        )

    def test_same_submission_keeps_earliest_completed_request(self) -> None:
        client = Mock()
        rows = [
            request_row("request-a", "REQ-1", "token-1", 1),
            request_row("request-b", "REQ-1", "token-1", 2),
        ]
        lines_by_request = {
            "request-a": [{"record_id": "line-a"}],
            "request-b": [{"record_id": "line-b-1"}, {"record_id": "line-b-2"}],
        }
        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app, "submission_token_rows", return_value=rows),
            patch.object(app, "request_line_rows_by_request_id", return_value=([], lines_by_request)),
            patch.object(app, "feishu_table_id", side_effect=lambda name: name),
        ):
            canonical, removed_count = app.reconcile_submission_duplicates("token-1", "request-b")

        self.assertEqual(app.feishu_record_id(canonical or {}), "request-a")
        self.assertEqual(removed_count, 1)
        client.delete_record.assert_any_call(app.REQUEST_LINE_TABLE_NAME, "line-b-1")
        client.delete_record.assert_any_call(app.REQUEST_LINE_TABLE_NAME, "line-b-2")
        client.delete_record.assert_any_call(app.REQUEST_TABLE_NAME, "request-b")
        self.assertEqual(client.delete_record.call_count, 3)


if __name__ == "__main__":
    unittest.main()
