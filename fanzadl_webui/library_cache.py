import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path

from fanzadl import FanzaDLManager

logger = logging.getLogger(__name__)


def save_library_cache(path: Path, user_id: str, manager: FanzaDLManager) -> None:
    """Serialize the manager's library to disk atomically.

    Only declared model fields are serialized (excludes computed fields and private
    attributes such as auth callbacks). The ``_javstash_info`` cached property value
    is captured separately when it has already been fetched.

    Args:
        path: Destination path for the cache file.
        user_id: The authenticated user's ID, stored to detect account changes.
        manager: The manager whose library will be serialized.
    """
    items: dict[str, dict] = {}
    for item_id, item in manager.library.items():
        item_data = item.model_dump(mode="json", include=set(item.model_fields))
        if item.video_list is not None:
            # Serialize video_list by alias so hyphenated device names (e.g.
            # "vita-tv") round-trip correctly. Computed fields in the nested
            # delivery-info models are handled by extra="ignore" on
            # _BaseRatePatternModel / _BaseDeliveryInfoModel.
            item_data["video_list"] = item.video_list.model_dump(
                mode="json", by_alias=True
            )
        items[str(item_id)] = {
            "model": item_data,
            "javstash_info": item.__dict__.get("_javstash_info"),
        }

    data = json.dumps({"user_id": user_id, "items": items}).encode()

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def load_library_cache(path: Path, user_id: str) -> dict[int, dict]:
    """Load the library cache from disk.

    Returns an empty dict if the file does not exist, is corrupt, or belongs to a
    different user.

    Args:
        path: Path to the cache file.
        user_id: The authenticated user's ID; must match the stored value.

    Returns:
        A dict mapping ``mylibrary_id`` to ``{"model": ..., "javstash_info": ...}``.
    """
    try:
        payload = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, ValueError):
        logger.warning("Library cache is corrupt; ignoring")
        return {}

    if payload.get("user_id") != user_id:
        logger.warning("Library cache belongs to a different user; ignoring")
        return {}

    try:
        return {int(k): v for k, v in payload["items"].items()}
    except (KeyError, ValueError):
        logger.warning("Library cache has unexpected structure; ignoring")
        return {}


def delete_library_cache(path: Path) -> None:
    """Delete the library cache file if it exists.

    Args:
        path: Path to the cache file.
    """
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
