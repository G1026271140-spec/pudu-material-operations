"""Lock contention must leave durable evidence without reading remote tables."""
import os
from contextlib import contextmanager
import pytest
import psycopg
from test_postgres_jobs import conn
from material_store import reconcile


def test_lock_timeout_recorded_before_wait_and_session_setting_restored(conn,monkeypatch):
    @contextmanager
    def same():yield conn
    monkeypatch.setattr(reconcile,'connection',same)
    before_timeout=conn.execute('SHOW lock_timeout').fetchone()[0]
    created=[]
    def progress(value):
        if value['stage']=='waiting_lock':
            created.append(value['run_id'])
            assert conn.execute('SELECT state FROM material_ops.reconcile_runs WHERE id=%s',(value['run_id'],)).fetchone()==('running',)
    with psycopg.connect(os.environ['PUDU_TEST_DATABASE_DSN'],autocommit=True) as blocker:
        blocker.execute("SELECT pg_advisory_lock_shared(hashtextextended('pudu-reconciliation',0))")
        try:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                reconcile.run({},progress=progress,lock_timeout_ms=50)
        finally:blocker.execute("SELECT pg_advisory_unlock_shared(hashtextextended('pudu-reconciliation',0))")
    try:
        assert len(created)==1
        state,summary,completed=conn.execute('SELECT state,summary,completed_at FROM material_ops.reconcile_runs WHERE id=%s',(created[0],)).fetchone()
        assert state=='failed' and completed and summary['stage']=='waiting_lock' and summary['reason']=='lock_timeout'
        assert summary['fetched']==0 and summary['duration_ms']>=40
        assert conn.execute('SHOW lock_timeout').fetchone()[0]==before_timeout
        assert not conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory')").fetchone()[0]
    finally:conn.execute('DELETE FROM material_ops.reconcile_runs WHERE id=%s',(created[0],))
