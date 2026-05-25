from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from fanzadl import FanzaDLManager
    from fanzadl.models import VideoLibraryItemContentsModel, VRLibraryItemContentsModel


def get_quality_obj(
    video_id: int,
    manager: "FanzaDLManager",
) -> "VideoLibraryItemContentsModel | VRLibraryItemContentsModel":
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
    return item.download_highest or item.stream_highest
