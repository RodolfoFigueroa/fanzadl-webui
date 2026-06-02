import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS download_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT    NOT NULL,
    status         TEXT    NOT NULL CHECK(status IN ('done', 'error')),
    output_name    TEXT    NOT NULL,
    content_id     TEXT,
    source         TEXT    NOT NULL CHECK(source IN ('manual', 'auto')),
    file_size      INTEGER,
    output_path    TEXT,
    error          TEXT,
    bandwidth_mbps REAL,
    completed_at   TEXT    NOT NULL
)
"""


@dataclass
class HistoryEntry:
    id: int
    job_id: str
    status: Literal["done", "error"]
    output_name: str
    content_id: str | None
    source: Literal["manual", "auto"]
    file_size: int | None
    output_path: str | None
    error: str | None
    bandwidth_mbps: float | None
    completed_at: str


def _get_conn(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def init_history_db(path: Path) -> None:
    """Create the download_history table if it does not already exist.

    Args:
        path: Path to the SQLite database file.
    """
    conn = _get_conn(path)
    conn.close()


def insert_history(
    path: Path,
    job_id: str,
    status: str,
    output_name: str,
    content_id: str | None,
    source: str,
    file_size: int | None,
    output_path: str | None,
    error: str | None,
    bandwidth_mbps: float | None,
) -> None:
    """Insert a completed download record into the history table.

    Args:
        path: Path to the SQLite database file.
        job_id: UUID of the download job.
        status: Terminal status, either ``"done"`` or ``"error"``.
        output_name: Relative output path used as the job name.
        content_id: Content identifier from the library, or ``None``.
        source: ``"manual"`` or ``"auto"``.
        file_size: Final file size in bytes, or ``None`` for errored downloads.
        output_path: Absolute output file path, or ``None`` for errored downloads.
        error: Error message, or ``None`` for successful downloads.
        bandwidth_mbps: Stream bandwidth in Mbps, or ``None`` if unknown.
    """
    completed_at = datetime.now(UTC).isoformat()
    conn = _get_conn(path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO download_history
                    (job_id, status, output_name, content_id, source,
                     file_size, output_path, error, bandwidth_mbps, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    status,
                    output_name,
                    content_id,
                    source,
                    file_size,
                    output_path,
                    error,
                    bandwidth_mbps,
                    completed_at,
                ),
            )
    finally:
        conn.close()


def get_history(
    path: Path,
    status_filter: str,
    offset: int,
    limit: int,
) -> tuple[list[HistoryEntry], int]:
    """Fetch a page of history entries with an optional status filter.

    Args:
        path: Path to the SQLite database file.
        status_filter: One of ``"all"``, ``"done"``, or ``"error"``.
        offset: Number of rows to skip (0-based).
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(entries, total)`` where ``total`` is the unfiltered row
        count matching the status filter.
    """
    conn = _get_conn(path)
    try:
        if status_filter == "all":
            where = ""
            params: tuple = ()
        else:
            where = "WHERE status = ?"
            params = (status_filter,)

        total: int = conn.execute(
            f"SELECT COUNT(*) FROM download_history {where}",
            params,
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM download_history {where} ORDER BY id DESC LIMIT ? OFFSET ?",  # noqa: S608
            (*params, limit, offset),
        ).fetchall()

        entries = [
            HistoryEntry(
                id=row["id"],
                job_id=row["job_id"],
                status=row["status"],
                output_name=row["output_name"],
                content_id=row["content_id"],
                source=row["source"],
                file_size=row["file_size"],
                output_path=row["output_path"],
                error=row["error"],
                bandwidth_mbps=row["bandwidth_mbps"],
                completed_at=row["completed_at"],
            )
            for row in rows
        ]
        return entries, total
    finally:
        conn.close()


def delete_history_by_ids(path: Path, ids: list[int]) -> None:
    """Delete specific history rows by their primary key IDs.

    Args:
        path: Path to the SQLite database file.
        ids: List of row IDs to delete.
    """
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    conn = _get_conn(path)
    try:
        with conn:
            conn.execute(
                f"DELETE FROM download_history WHERE id IN ({placeholders})",  # noqa: S608
                ids,
            )
    finally:
        conn.close()


def delete_all_history(path: Path) -> None:
    """Delete every row from the download_history table.

    Args:
        path: Path to the SQLite database file.
    """
    conn = _get_conn(path)
    try:
        with conn:
            conn.execute("DELETE FROM download_history")
    finally:
        conn.close()
