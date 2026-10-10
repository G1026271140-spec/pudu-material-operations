from scripts import reconcile_corporate_apparel_quotas as quotas


class FakeClient:
    def __init__(self, exchange_rows, permission_rows):
        self.rows = {
            quotas.EXCHANGE_TABLE: exchange_rows,
            quotas.PERMISSION_TABLE: permission_rows,
            quotas.REQUEST_TABLE: [],
            quotas.REQUEST_LINE_TABLE: [],
            quotas.QUEUE_TABLE: [],
        }

    def discover_schema(self):
        return {"tables": {name: {"table_id": name} for name in self.rows}}

    def list_records(self, table_id):
        return self.rows[table_id]


def exchange(record_id, person_id, style, quantity):
    return {
        "record_id": record_id,
        "fields": {
            "兑换人": [{"id": person_id, "name": person_id}],
            "款式": style,
            "数量": quantity,
        },
    }


def permission(record_id, person_id, quantity, number="1"):
    return {
        "record_id": record_id,
        "fields": {
            "用户编号": number,
            "用户账号": [{"id": person_id}],
            "POLO申领数量累计": quantity,
        },
    }


def test_new_exchange_row_updates_quota_once():
    client = FakeClient(
        [exchange("exchange-1", "ou-existing", "文化衫-休闲商务POLO-黑色（短袖）", 1)],
        [permission("permission-1", "ou-existing", 1)],
    )
    assert quotas.build_plan(client)["updates"] == []

    client.rows[quotas.EXCHANGE_TABLE].append(
        exchange("exchange-2", "ou-existing", "文化衫-休闲商务POLO-黑色（短袖）", 1)
    )
    plan = quotas.build_plan(client)
    assert plan["updates"] == [
        {"record_id": "permission-1", "fields": {"POLO申领数量累计": 2}}
    ]

    client.rows[quotas.PERMISSION_TABLE][0]["fields"]["POLO申领数量累计"] = 2
    assert quotas.build_plan(client)["updates"] == []


def test_new_exchange_person_creates_sales_permission():
    client = FakeClient(
        [exchange("exchange-new", "ou-new", "文化衫-休闲商务夹克-黑色（长袖）", 1)],
        [permission("permission-1", "ou-existing", 1, number="12")],
    )
    plan = quotas.build_plan(client)
    assert plan["creates"] == [
        {
            "用户编号": "13",
            "用户账号": [{"id": "ou-new"}],
            "角色": ["销售"],
            "是否启用": "是",
            "文化夹克申领数量累计": 1,
        }
    ]


def test_authoritative_source_rows_override_stale_mirror():
    client = FakeClient([], [permission("permission-1", "ou-existing", 1)])

    class SourceClient:
        def list_tables(self):
            return [{"name": quotas.EXCHANGE_SOURCE_TABLE, "table_id": quotas.EXCHANGE_SOURCE_TABLE_ID}]

        def list_records(self, table_id):
            assert table_id == quotas.EXCHANGE_SOURCE_TABLE_ID
            return [exchange("source-1", "ou-existing", "文化衫-休闲商务POLO-黑色（短袖）", 2)]

    assert quotas.build_plan(client, SourceClient())["updates"] == [
        {"record_id": "permission-1", "fields": {"POLO申领数量累计": 2}}
    ]
