"""Small process-local pool; the VM database is reached through its Unix socket."""
from contextlib import contextmanager
from functools import lru_cache
import os


@lru_cache(maxsize=1)
def pool():
    from psycopg_pool import ConnectionPool
    dsn = os.environ.get("PUDU_DATABASE_DSN", "")
    if not dsn:
        raise RuntimeError("本地业务数据库尚未启用。")
    return ConnectionPool(dsn, min_size=0, max_size=5, timeout=10,
                          kwargs={"autocommit": True}, open=True)


@contextmanager
def connection():
    with pool().connection() as conn:
        yield conn
