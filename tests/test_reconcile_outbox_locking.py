"""A queued full reconciliation must not deadlock a publishing worker's guard."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import os,time
import psycopg
import pytest
from test_line_outbox_batch import batched,edit_lines
from test_approval_sync import graph
from test_shipping_calendar import store
from material_store import outbox_worker as worker,line_outbox_batch as bulk


@pytest.mark.parametrize('batch_size',[1,10])
def test_active_publisher_finishes_while_reconcile_waits_then_exclusive_lock_runs(batched,monkeypatch,batch_size):
    conn,info,lines,key,number,source=batched
    edit_lines(batched,count=batch_size)
    queued=Event();acquired=Event();writer_pid=[]
    original=worker.claim
    def reconcile_wait():
        with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as other:
            other.execute("SET lock_timeout='3s'")
            writer_pid.append(other.info.backend_pid);queued.set()
            other.execute("SELECT pg_advisory_lock(hashtextextended('pudu-reconciliation',0))")
            acquired.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures=[]
        def claim(lane,identity,*,reconciliation_guard=None):
            assert reconciliation_guard is not None
            futures.append(pool.submit(reconcile_wait));assert queued.wait(1)
            until=time.monotonic()+1
            while time.monotonic()<until:
                waiting=conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' AND mode='ExclusiveLock' AND NOT granted)",(writer_pid[0],)).fetchone()[0]
                if waiting:break
                time.sleep(.005)
            assert waiting and not acquired.is_set()
            # A regression must fail quickly, not hang the isolated test run.
            conn.execute("SET LOCAL statement_timeout='500ms'")
            return original(lane,identity,reconciliation_guard=reconciliation_guard)
        monkeypatch.setattr(worker,'claim',claim)
        result=worker.run_once('ordinary',source)
        assert result['state']=='done' and result['done']==batch_size
        for f in futures:f.result(timeout=2)
        assert acquired.is_set()


def test_standalone_claim_still_obeys_reconciliation_lock(batched):
    conn,info,lines,key,number,source=batched;edit_lines(batched,count=1)
    # Standalone claim has no session guard and must retain transaction locking.
    with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as guard:
        guard.execute("SELECT pg_advisory_lock(hashtextextended('pudu-reconciliation',0))")
        with pytest.raises(psycopg.errors.QueryCanceled):
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='150ms'")
                worker.claim('ordinary','standalone')
