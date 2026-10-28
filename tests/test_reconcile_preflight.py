from contextlib import contextmanager
from unittest.mock import Mock
import pytest
from test_postgres_jobs import conn
from material_store import reconcile

def test_failed_schema_preflight_is_recorded_without_changing_business_data(conn,monkeypatch):
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(reconcile,'connection',same)
    before={row[0] for row in conn.execute('SELECT id FROM material_ops.reconcile_runs')}
    from material_store.backup import fingerprint
    data_before={name:value for name,value in fingerprint(conn).items() if name.startswith('material_data.')}
    client=Mock();client.list_fields.return_value=[]
    try:
        with pytest.raises(ValueError,match='字段定义'):reconcile.run({'primary':client,'apparel_admin':client})
        after=[row for row in conn.execute('SELECT id,state,summary FROM material_ops.reconcile_runs') if row[0] not in before]
        assert len(after)==1 and after[0][1]=='failed'
        assert after[0][2]['stage']=='source_fetch' and after[0][2]['reason']=='schema_mismatch'
        assert {name:value for name,value in fingerprint(conn).items() if name.startswith('material_data.')}==data_before
        client.list_records.assert_not_called()
    finally:
        for row in conn.execute('SELECT id FROM material_ops.reconcile_runs').fetchall():
            if row[0] not in before:conn.execute('DELETE FROM material_ops.reconcile_runs WHERE id=%s',(row[0],))
