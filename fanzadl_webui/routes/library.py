from datetime import datetime
from typing import Annotated, Literal

from fanzadl import FanzaDLManager
from fanzadl.models.video import (
    VideoLibraryItemContentsModel,
    VRLibraryItemContentsModel,
)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from fanzadl_webui.dependencies import get_manager, verify_api_key

LibraryItem = VideoLibraryItemContentsModel | VRLibraryItemContentsModel


class LibraryItemResponse(BaseModel):
    mylibrary_id: int
    product_id: str
    title: str
    content_type: Literal["video", "vr"]
    package_image_url: str
    parts: int
    purchase_date: datetime
    trans_type: Literal["download", "stream"]


router = APIRouter(prefix="/library", dependencies=[Depends(verify_api_key)])


def _serialize(item: LibraryItem) -> LibraryItemResponse:
    return LibraryItemResponse(
        mylibrary_id=item.mylibrary_id,
        product_id=item.product_id,
        title=item.title,
        content_type=item.content_type,
        package_image_url=f"/api/images/{item.product_id}",
        parts=item.parts,
        purchase_date=item.purchase_date,
        trans_type=item.trans_type,
    )


@router.get("/")
def get_library(
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> dict[int, LibraryItemResponse]:
    return {k: _serialize(v) for k, v in manager.library.items()}


@router.get("/{video_id}")
def get_item(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> LibraryItemResponse:
    item = manager.library.get(video_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )
    return _serialize(item)
