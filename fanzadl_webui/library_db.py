import contextlib
import json
import logging
import sqlite3
from pathlib import Path

from fanzadl import FanzaDLManager

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS library (
    mylibrary_id       INTEGER PRIMARY KEY,
    user_id            TEXT    NOT NULL,
    content_id         TEXT    NOT NULL,
    title              TEXT    NOT NULL,
    content_type       TEXT    NOT NULL,
    purchase_date      TEXT    NOT NULL,
    expire             TEXT    NOT NULL,
    trans_type         TEXT    NOT NULL,
    parts              INTEGER NOT NULL,
    available          INTEGER NOT NULL DEFAULT 1,
    video_list_json    TEXT,
    javstash_info_json TEXT
)
"""


def _get_conn(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def save_library_db(
    path: Path,
    user_id: str,
    manager: FanzaDLManager,
    new_item_ids: set[int],
) -> None:
    """Persist new library items to the DB and mark removed items unavailable.

    Only items in ``new_item_ids`` are written; items already present in the DB
    (restored from cache) are left untouched. Items that were previously
    available but are no longer in the manager's library are set to
    ``available=0`` and their ``video_list_json`` is cleared.

    Args:
        path: Path to the SQLite database file.
        user_id: The authenticated user's ID.
        manager: The manager whose library will be persisted.
        new_item_ids: IDs of items not restored from cache (i.e. newly fetched).
    """
    conn = _get_conn(path)
    try:
        with conn:
            for item_id, item in manager.library.items():
                if item_id not in new_item_ids:
                    continue
                video_list_json: str | None = None
                if item.video_list is not None:
                    video_list_json = json.dumps(
                        item.video_list.model_dump(mode="json", by_alias=True)
                    )
                javstash_info_json: str | None = None
                raw_javstash = item.__dict__.get("_javstash_info")
                if raw_javstash is not None:
                    javstash_info_json = json.dumps(raw_javstash)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO library (
                        mylibrary_id, user_id, content_id, title, content_type,
                        purchase_date, expire, trans_type, parts, available,
                        video_list_json, javstash_info_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        item_id,
                        user_id,
                        item.content_id,
                        item.title,
                        item.content_type,
                        item.purchase_date.isoformat(),
                        item.expire.isoformat(),
                        item.trans_type,
                        item.parts,
                        video_list_json,
                        javstash_info_json,
                    ),
                )

            current_ids = list(manager.library.keys())
            if current_ids:
                placeholders = ",".join("?" * len(current_ids))
                conn.execute(
                    f"""
                    UPDATE library
                    SET available = 0, video_list_json = NULL
                    WHERE available = 1
                    AND mylibrary_id NOT IN ({placeholders})
                    """,  # noqa: S608
                    current_ids,
                )
            else:
                conn.execute(
                    "UPDATE library SET available = 0, video_list_json = NULL WHERE available = 1"
                )
    finally:
        conn.close()


def load_available_items(path: Path, user_id: str) -> dict[int, dict]:
    """Load available library items from the DB.

    If the DB contains rows belonging to a different user, all rows are deleted
    and an empty dict is returned.

    Args:
        path: Path to the SQLite database file.
        user_id: The authenticated user's ID.

    Returns:
        A dict mapping ``mylibrary_id`` to
        ``{"model": {...}, "javstash_info": ...}``.
    """
    try:
        conn = _get_conn(path)
    except Exception:
        logger.warning("Failed to open library DB; treating as empty", exc_info=True)
        return {}
    try:
        first = conn.execute("SELECT user_id FROM library LIMIT 1").fetchone()
        if first is not None and first["user_id"] != user_id:
            logger.warning("Library DB belongs to a different user; clearing")
            with conn:
                conn.execute("DELETE FROM library")
            return {}

        rows = conn.execute("SELECT * FROM library WHERE available = 1").fetchall()
    finally:
        conn.close()

    result: dict[int, dict] = {}
    for row in rows:
        video_list = None
        if row["video_list_json"] is not None:
            try:
                video_list = json.loads(row["video_list_json"])
            except (json.JSONDecodeError, ValueError):
                logger.warning(
                    "Corrupt video_list_json for item %s; skipping cache entry",
                    row["mylibrary_id"],
                )
                continue

        javstash_info = None
        if row["javstash_info_json"] is not None:
            with contextlib.suppress(json.JSONDecodeError, ValueError):
                javstash_info = json.loads(row["javstash_info_json"])

        model = {
            "mylibrary_id": row["mylibrary_id"],
            "content_id": row["content_id"],
            "title": row["title"],
            "content_type": row["content_type"],
            "purchase_date": row["purchase_date"],
            "expire": row["expire"],
            "trans_type": row["trans_type"],
            "parts": row["parts"],
            "video_list": video_list,
        }
        result[row["mylibrary_id"]] = {"model": model, "javstash_info": javstash_info}

    return result


def delete_all(path: Path) -> None:
    """Delete all rows from the library DB.

    Args:
        path: Path to the SQLite database file.
    """
    try:
        conn = _get_conn(path)
    except Exception:  # noqa: BLE001
        return
    try:
        with conn:
            conn.execute("DELETE FROM library")
    finally:
        conn.close()


def get_unavailable_items(path: Path) -> list[dict]:
    """Return all unavailable (expired) library items.

    Args:
        path: Path to the SQLite database file.

    Returns:
        A list of dicts with item metadata including ``parts``.
    """
    try:
        conn = _get_conn(path)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to open library DB", exc_info=True)
        return []
    try:
        rows = conn.execute(
            """
            SELECT mylibrary_id, content_id, title, content_type,
                   purchase_date, expire, trans_type, parts, javstash_info_json
            FROM library
            WHERE available = 0
            """
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def delete_unavailable_item(path: Path, mylibrary_id: int) -> bool:
    """Delete a specific unavailable item from the DB.

    Args:
        path: Path to the SQLite database file.
        mylibrary_id: The ID of the item to delete.

    Returns:
        ``True`` if a row was deleted, ``False`` if it did not exist.
    """
    try:
        conn = _get_conn(path)
    except Exception:  # noqa: BLE001
        return False
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM library WHERE mylibrary_id = ? AND available = 0",
                (mylibrary_id,),
            )
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_item_unavailable(path: Path, mylibrary_id: int) -> None:
    """Mark a library item as unavailable.

    Args:
        path: Path to the SQLite database file.
        mylibrary_id: The ID of the item to mark unavailable.
    """
    try:
        conn = _get_conn(path)
    except Exception:  # noqa: BLE001
        return
    try:
        with conn:
            conn.execute(
                "UPDATE library SET available = 0, video_list_json = NULL WHERE mylibrary_id = ?",  # noqa: E501
                (mylibrary_id,),
            )
    finally:
        conn.close()


def update_javstash_info_db(path: Path, manager: FanzaDLManager) -> None:
    """Update ``javstash_info_json`` for all items currently in the manager's library.

    Only writes rows where ``_javstash_info`` has been fetched (i.e. is present
    in the item's ``__dict__``). Rows whose ``_javstash_info`` is still ``None``
    are left untouched so that a successful previous fetch is not overwritten.

    Args:
        path: Path to the SQLite database file.
        manager: The manager whose library items will be inspected.
    """
    try:
        conn = _get_conn(path)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to open library DB for javstash update", exc_info=True)
        return
    try:
        with conn:
            for item_id, item in manager.library.items():
                raw = item.__dict__.get("_javstash_info")
                if raw is None:
                    continue
                conn.execute(
                    "UPDATE library SET javstash_info_json = ? WHERE mylibrary_id = ?",
                    (json.dumps(raw), item_id),
                )
    finally:
        conn.close()
