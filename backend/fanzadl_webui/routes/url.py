from typing import Annotated, Literal

from fanzadl import FanzaDLManager
from fanzadl_webui.dependencies import get_manager, require_api_key
from fanzadl_webui.routes._utils import get_quality_obj
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/url", tags=["URL"])


@router.get(
    "/",
    responses={
        404: {
            "description": "Video not found in the library or has no downloadable quality."
        }
    },
)
def get_url(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    _: Annotated[None, Depends(require_api_key)],
    part: int | None = None,
    quality: Literal["highest"] = "highest",  # noqa: ARG001
) -> str | list[str]:
    """Return the download URL(s) for a library item.

    When ``part`` is specified, returns the single URL string for that part.
    When ``part`` is omitted, returns a list of URLs for all parts of the item.

    Args:
        video_id: The ``mylibrary_id`` of the library item.
        part: The 1-based part number to retrieve a URL for. Omit to get all parts.
        quality: Quality selection strategy — currently only ``"highest"`` is supported.

    Returns:
        A single URL string when ``part`` is given, or a list of URL strings
        for all parts when ``part`` is omitted.

    Raises:
        HTTPException: 404 if the video is not found or has no downloadable quality.
    """
    quality_obj = get_quality_obj(video_id, manager)
    if part is not None:
        return quality_obj.get_url(part)
    return quality_obj.get_all_urls()
