import pytest


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
