import asyncio
from collections.abc import Coroutine
from typing import Any

from fanzadl import FanzaDLManager
from fanzadl.models.video.video import VideoQualityModel
from fanzadl.models.video.vr import VRQualityModel
from fastapi import HTTPException, status


def get_quality_obj(
    video_id: int,
    manager: FanzaDLManager,
) -> VideoQualityModel | VRQualityModel:
    """Return the highest-quality download/stream object for a library item.

    Args:
        video_id: The mylibrary ID of the item to look up.
        manager: The FanzaDLManager instance holding the library.

    Returns:
        The quality object exposing ``get_url`` / ``get_all_urls``.

    Raises:
        HTTPException: 404 if the video_id is not in the library.
    """
    item = manager.library.get(video_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )

    out = item.highest
    if out is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No downloadable/streamable qualities found for this video",
        )
    return out


def _fire_background(
    tasks: set[asyncio.Task[Any]], coro: Coroutine[object, object, object]
) -> None:
    task = asyncio.create_task(coro)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
