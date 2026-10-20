import pytest


@pytest.fixture(autouse=True)
def isolate_submission_receipts(tmp_path, monkeypatch):
    import submission_receipts

    monkeypatch.setenv("PUDU_SUBMISSION_RECEIPTS_DB", str(tmp_path / "receipts.sqlite3"))
    # Tests drive deliveries explicitly, never send fake applicants live messages.
    monkeypatch.setattr(submission_receipts, "start", lambda: None)
    monkeypatch.setattr(submission_receipts, "stop", lambda: None)
