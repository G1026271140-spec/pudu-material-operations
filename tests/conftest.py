import pytest
import socket


@pytest.fixture(autouse=True)
def close_database_pool_when_clearing_test_cache(monkeypatch):
    """cache_clear alone leaves psycopg pool threads and sockets alive."""
    from material_store.db import pool
    clear=pool.cache_clear
    def close_and_clear():
        if pool.cache_info().currsize:pool().close()
        clear()
    close_and_clear()
    monkeypatch.setattr(pool,'cache_clear',close_and_clear)
    yield
    close_and_clear()


@pytest.fixture(autouse=True)
def unit_tests_never_contact_external_services(monkeypatch):
    """Unmocked I/O fails immediately, not against a real company API."""
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1', 'localhost'}:
            raise AssertionError('External networking is forbidden in unit tests; mock the source client')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)


@pytest.fixture(autouse=True)
def isolate_catalog_deletions(tmp_path, monkeypatch):
    monkeypatch.setenv("PUDU_CATALOG_DELETIONS_DB", str(tmp_path / "catalog-deletions.sqlite3"))


@pytest.fixture(autouse=True)
def isolate_submission_receipts(tmp_path, monkeypatch):
    import submission_receipts

    monkeypatch.setenv("PUDU_SUBMISSION_RECEIPTS_DB", str(tmp_path / "receipts.sqlite3"))
    # Tests drive deliveries explicitly, never send fake applicants live messages.
    monkeypatch.setattr(submission_receipts, "start", lambda: None)
    monkeypatch.setattr(submission_receipts, "stop", lambda: None)


@pytest.fixture(autouse=True)
def isolate_task_failure_notices(tmp_path, monkeypatch):
    import task_failure_notices

    monkeypatch.setenv("PUDU_TASK_FAILURE_NOTICES_DB", str(tmp_path / "task_failure_notices.sqlite3"))
    monkeypatch.setattr(task_failure_notices, "start", lambda: None)
    monkeypatch.setattr(task_failure_notices, "stop", lambda: None)
    task_failure_notices._stop.clear()
