import os
from datetime import date, datetime
from typing import Annotated, Literal

from fanzadl import FanzaDLManager
from fanzadl.models.video import (
    UnavailableLibraryItemContentsModel,
    VideoLibraryItemContentsModel,
    VRLibraryItemContentsModel,
)
from fanzadl.models.video.unavailable import (
    UnavailableVideoItemContentsModel,
    UnavailableVRItemContentsModel,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from fanzadl_webui.dependencies import get_manager

LibraryItem = VideoLibraryItemContentsModel | VRLibraryItemContentsModel


class LibraryItemResponse(BaseModel):
    mylibrary_id: int
    content_id: str
    title: str
    content_type: Literal["video", "vr"]
    package_image_url: str
    parts: int
    purchase_date: datetime
    expire: date
    trans_type: Literal["download", "stream"]
    javstash_id: str | None = None
    javstash_studio_code: str | None = None


class ExpiredLibraryItemResponse(BaseModel):
    mylibrary_id: int
    content_id: str
    title: str
    content_type: Literal["video", "vr"]
    package_image_url: str
    purchase_date: datetime
    expire: date
    trans_type: Literal["download", "stream"]
    javstash_id: str | None = None
    javstash_studio_code: str | None = None


router = APIRouter(prefix="/library")


def _require_dev_mode() -> None:
    if os.environ.get("FANZADL_DEV") != "1":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


class _DevExpireBody(BaseModel):
    mylibrary_id: int


def _serialize(item: LibraryItem) -> LibraryItemResponse:
    return LibraryItemResponse(
        mylibrary_id=item.mylibrary_id,
        content_id=item.content_id,
        title=item.title,
        content_type=item.content_type,
        package_image_url=f"/api/images/{item.content_id}",
        parts=item.parts,
        purchase_date=item.purchase_date,
        expire=item.expire,
        trans_type=item.trans_type,
        javstash_id=getattr(item, "javstash_id", None),
        javstash_studio_code=getattr(item, "javstash_studio_code", None),
    )


def _serialize_expired(
    item: UnavailableLibraryItemContentsModel,
) -> ExpiredLibraryItemResponse:
    return ExpiredLibraryItemResponse(
        mylibrary_id=item.mylibrary_id,
        content_id=item.content_id,
        title=item.title,
        content_type=item.content_type,
        package_image_url=f"/api/images/{item.content_id}",
        purchase_date=item.purchase_date,
        expire=item.expire,
        trans_type=item.trans_type,
        javstash_id=getattr(item, "javstash_id", None),
        javstash_studio_code=getattr(item, "javstash_studio_code", None),
    )


@router.post(
    "/expire/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_require_dev_mode)],
)
def dev_expire_item(
    body: _DevExpireBody,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> None:
    item = manager.library.get(body.mylibrary_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in library"
        )

    if item.content_type == "video":
        unavailable_item = UnavailableVideoItemContentsModel.from_contents_model(item)
    else:
        unavailable_item = UnavailableVRItemContentsModel.from_contents_model(item)

    dummy_id = -body.mylibrary_id
    unavailable_item.mylibrary_id = dummy_id
    manager.expired_library[dummy_id] = unavailable_item


@router.get("/expired/")
def get_expired_library(
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> dict[int, ExpiredLibraryItemResponse]:
    return {k: _serialize_expired(v) for k, v in manager.expired_library.items()}


@router.delete("/expired/{mylibrary_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expired_item(
    mylibrary_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> None:
    if manager.expired_library.pop(mylibrary_id, None) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Expired item not found"
        )


@router.get("/download-counts/")
def get_download_counts(
    request: Request,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],  # noqa: ARG001
) -> dict[str, int]:
    """Return the number of downloaded parts for each library item.

    Args:
        request: Incoming FastAPI request providing app state.
        manager: Injected manager (used only to enforce authentication).

    Returns:
        A dict mapping ``content_id`` to the count of downloaded ``.mp4`` files.
    """
    return request.app.state.download_counts


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
