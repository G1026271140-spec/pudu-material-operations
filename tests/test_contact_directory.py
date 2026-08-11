import unittest
from unittest.mock import Mock, patch

import app
from feishu_bitable import FeishuBitableClient, FeishuBitableConfig


class ContactDirectoryTests(unittest.TestCase):
    def test_department_cache_builds_full_paths(self) -> None:
        cache = app.contact_department_cache_from_rows(
            [
                {
                    "open_department_id": "od-parent",
                    "name": "营销中心",
                    "parent_department_id": "0",
                },
                {
                    "open_department_id": "od-child",
                    "name": "海外销售部",
                    "parent_department_id": "od-parent",
                },
            ],
            source="test",
        )

        paths = {
            item["department_id"]: item["path"]
            for item in cache["departments"]
        }
        self.assertEqual(paths["od-child"], "营销中心 / 海外销售部")

    def test_directory_cache_merges_users_and_keeps_department_labels(self) -> None:
        cache = app.contact_department_cache_from_rows(
            [
                {
                    "open_department_id": "od-sales",
                    "name": "销售部",
                    "parent_department_id": "0",
                },
                {
                    "open_department_id": "od-marketing",
                    "name": "市场部",
                    "parent_department_id": "0",
                },
            ],
            source="test",
            department_users={
                "od-sales": [{"open_id": "ou-example", "name": "张三"}],
                "od-marketing": [{"open_id": "ou-example", "name": "张三"}],
            },
        )

        self.assertEqual(cache["user_count"], 1)
        self.assertEqual(
            cache["users"][0]["department_ids"],
            ["od-marketing", "od-sales"],
        )
        self.assertEqual(
            cache["users"][0]["department_paths"],
            ["市场部", "销售部"],
        )

    def test_selecting_applicant_autofills_department(self) -> None:
        session_state = {
            "request_requester_open_id": "ou-example",
            "request_department_id": None,
            app.REQUEST_CONTACT_USER_LOOKUP_KEY: {
                "ou-example": {
                    "department_ids": ["od-sales"],
                }
            },
        }

        with patch.object(app.st, "session_state", session_state):
            app.sync_request_department_from_selected_applicant()

        self.assertEqual(session_state["request_department_id"], "od-sales")
        self.assertTrue(session_state["request_form_cache_locked"])

    def test_clearing_applicant_clears_previous_department(self) -> None:
        session_state = {
            "request_requester_open_id": None,
            "request_department_id": "od-sales",
            app.REQUEST_CONTACT_USER_LOOKUP_KEY: {},
        }

        with patch.object(app.st, "session_state", session_state):
            app.sync_request_department_from_selected_applicant()

        self.assertIsNone(session_state["request_department_id"])
        self.assertTrue(session_state["request_form_cache_locked"])

    def test_applicant_without_department_clears_previous_department(self) -> None:
        session_state = {
            "request_requester_open_id": "ou-example",
            "request_department_id": "od-sales",
            app.REQUEST_CONTACT_USER_LOOKUP_KEY: {
                "ou-example": {
                    "department_ids": [],
                }
            },
        }

        with patch.object(app.st, "session_state", session_state):
            app.sync_request_department_from_selected_applicant()

        self.assertIsNone(session_state["request_department_id"])

    def test_live_directory_retries_transient_department_timeout(self) -> None:
        client = Mock()
        client.list_contact_departments.return_value = [
            {
                "open_department_id": "od-sales",
                "name": "销售部",
                "parent_department_id": "0",
            }
        ]
        client.list_department_users.side_effect = [
            TimeoutError("temporary timeout"),
            [{"open_id": "ou-example", "name": "张三"}],
        ]

        with (
            patch.object(app, "feishu_client", return_value=client),
            patch.object(app.time, "sleep"),
        ):
            cache = app.build_live_contact_department_cache()

        self.assertEqual(cache["user_count"], 1)
        self.assertEqual(client.list_department_users.call_count, 2)

    def test_contact_client_keeps_query_params_across_pages(self) -> None:
        client = FeishuBitableClient(FeishuBitableConfig("app", "secret", "token"))
        client._request = Mock(
            side_effect=[
                {
                    "data": {
                        "items": [{"open_department_id": "od-1"}],
                        "has_more": True,
                        "page_token": "next",
                    }
                },
                {
                    "data": {
                        "items": [{"open_department_id": "od-2"}],
                        "has_more": False,
                    }
                },
            ]
        )

        result = client.list_contact_departments()

        self.assertEqual(len(result), 2)
        second_params = client._request.call_args_list[1].kwargs["params"]
        self.assertEqual(second_params["parent_department_id"], "0")
        self.assertEqual(second_params["page_token"], "next")

    def test_contact_client_loads_users_for_selected_department(self) -> None:
        client = FeishuBitableClient(FeishuBitableConfig("app", "secret", "token"))
        client._request = Mock(
            return_value={
                "data": {
                    "items": [{"open_id": "ou-example", "name": "张三"}],
                    "has_more": False,
                }
            }
        )

        result = client.list_department_users("od-example")

        self.assertEqual(result[0]["open_id"], "ou-example")
        call = client._request.call_args
        self.assertEqual(call.args[:2], ("GET", "/contact/v3/users/find_by_department"))
        self.assertEqual(call.kwargs["params"]["department_id"], "od-example")
        self.assertEqual(call.kwargs["params"]["user_id_type"], "open_id")

    def test_person_field_uses_open_id_structure(self) -> None:
        fields: dict[str, object] = {}
        with (
            patch.object(app, "feishu_has_field", return_value=True),
            patch.object(app, "feishu_field_type", return_value=11),
        ):
            app.set_first_person_or_plain_field(
                app.REQUEST_TABLE_NAME,
                fields,
                ["申请人"],
                "张三",
                "ou-example",
            )

        self.assertEqual(fields["申请人"], [{"id": "ou-example"}])


if __name__ == "__main__":
    unittest.main()
