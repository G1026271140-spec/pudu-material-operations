"""Visible execution markers outside atomic business transactions; local only."""
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
from uuid import uuid4

from psycopg.types.json import Jsonb

PREFIX = 'task-activity:'
LOG = logging.getLogger(__name__)


def _write(query, params):
    # A dedicated short connection avoids exhausting the business pool while
    # all of its workers hold their atomic transactions. No Feishu client here.
    import psycopg
    dsn = os.environ.get('PUDU_DATABASE_DSN')
    if not dsn:
        return
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as visible:
        visible.execute("SET statement_timeout='1500ms'")
        visible.execute(query, params)


@contextmanager
def track(conn, job_id):
    token = uuid4().hex
    try:
        pid, start = conn.execute('SELECT pid,backend_start FROM pg_stat_activity WHERE pid=pg_backend_pid()').fetchone()
        payload = {'job_id': str(job_id), 'token': token, 'pid': pid,
                   'backend_start': start.isoformat(), 'started_at': datetime.now(timezone.utc).isoformat()}
        _write('''INSERT INTO material_ops.documents(name,payload) VALUES (%s,%s)
            ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=clock_timestamp()''',
               (PREFIX + str(job_id), Jsonb(payload)))
    except Exception:
        LOG.warning('Could not publish local task activity', exc_info=True)
    try:
        yield
    finally:
        try:
            _write("DELETE FROM material_ops.documents WHERE name=%s AND payload->>'token'=%s", (PREFIX + str(job_id), token))
        except Exception:
            # Readers also check the PostgreSQL backend identity, so a crashed
            # worker or stale marker cannot create a false running task.
            LOG.warning('Could not clear local task activity', exc_info=True)


def progress(job_id, value):
    try:
        _write("UPDATE material_ops.documents SET payload=payload || %s,updated_at=clock_timestamp() WHERE name=%s",
               (Jsonb({'progress': value}), PREFIX + str(job_id)))
    except Exception:
        LOG.warning('Could not publish local task progress', exc_info=True)
