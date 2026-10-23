"""Shared local invalidation journal for successfully deleted catalog records.

Workers and the web checkout share this journal on the deployment host. Record
IDs, not model names or status flags, prevent an older published snapshot from
resurrecting deleted options. Recreating a combination creates a new record ID.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from project_config import get_setting


def database_path() -> Path:
    configured = os.getenv("PUDU_CATALOG_DELETIONS_DB", "").strip()
    if configured:
        return Path(configured)
    local = os.getenv("LOCALAPPDATA")
    directory = Path(local) / "PuduMaterialOperations" if local else Path.home() / ".pudu-material-operations"
    project = str(get_setting("project.github_repository", "pudu-material-operations"))
    scope = hashlib.sha256(project.encode()).hexdigest()[:16]
    return directory / f"catalog-deletions-{scope}.sqlite3"


def record_deleted(table: str, record_ids: list[str]) -> None:
    ids = sorted({str(value).strip() for value in record_ids if str(value).strip()})
    if not ids:
        return
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as connection:
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS deleted_records (
                table_name TEXT NOT NULL, record_id TEXT NOT NULL,
                UNIQUE(table_name, record_id))""")
            connection.executemany(
                "INSERT OR IGNORE INTO deleted_records VALUES (?, ?)",
                [(table, record_id) for record_id in ids],
            )


def deleted_records() -> dict[str, set[str]]:
    path = database_path()
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path, timeout=10)) as connection:
        try:
            rows = connection.execute("SELECT table_name, record_id FROM deleted_records").fetchall()
        except sqlite3.OperationalError as error:
            # A reader may see the first newly created file just before the
            # writer creates its table. The next revision check observes it.
            if "no such table" not in str(error):
                raise
            return {}
    result: dict[str, set[str]] = {}
    for table, record_id in rows:
        result.setdefault(table, set()).add(record_id)
    return result


def revision() -> str:
    rows = deleted_records()
    return hashlib.sha256(repr(sorted((table, sorted(ids)) for table, ids in rows.items())).encode()).hexdigest()


def filter_page_snapshot(page: dict) -> dict:
    deleted = deleted_records()
    if not deleted:
        return page
    tables = dict(page.get("tables", {}))
    for table, ids in deleted.items():
        if table in tables:
            tables[table] = [row for row in tables[table]
                             if str(row.get("record_id") or row.get("id") or "") not in ids]
    return {**page, "tables": tables,
            "row_counts": {**page.get("row_counts", {}),
                           **{table: len(tables[table]) for table in deleted if table in tables}}}
