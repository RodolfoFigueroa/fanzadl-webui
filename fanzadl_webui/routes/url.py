from typing import Annotated, Literal

from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, status

from fanzadl_webui.dependencies import get_manager, verify_api_key

router = APIRouter(prefix="/url", dependencies=[Depends(verify_api_key)])


@router.get("/")
def get_url(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    part: int | None = None,
    quality: Literal["highest"] = "highest",  # noqa: ARG001
) -> str | list[str]:
    item = manager.library.get(video_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )
    quality_obj = item.download_highest or item.stream_highest
    if part is not None:
        return quality_obj.get_url(part)
    return quality_obj.get_all_urls()
