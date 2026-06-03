import asyncio
import json
from datetime import date, datetime
from typing import Annotated, Literal

from fanzadl import FanzaDLManager
from fanzadl.models.video import LibraryItemContentsModel
from fanzadl_webui.dependencies import (
    LIBRARY_DB_PATH,
    get_app_state,
    get_manager,
    require_api_key,
    require_dev_mode,
)
from fanzadl_webui.library_db import (
    delete_unavailable_item,
    get_unavailable_items,
    mark_item_unavailable,
)
from fanzadl_webui.routes.library.refresh import (
    run_post_update,
)
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/library", tags=["Library"])


class LibraryItemResponse(BaseModel):
    """A single item from the user's Fanza library."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mylibrary_id": 123456,
                "content_id": "myvi00001",
                "title": "My Video Title",
                "content_type": "video",
                "package_image_url": "/api/images/myvi00001",
                "parts": 2,
                "purchase_date": "2025-01-15T10:00:00+00:00",
                "expire": "2026-01-15",
                "trans_type": "download",
                "javstash_id": "1a2b3c4d-5e6f-47a8-9b9c-0d1e2f3a4b5c",
                "javstash_studio_code": "MYVI-001",
            }
        }
    )

    mylibrary_id: int = Field(description="Fanza numeric library ID for this item.")
    content_id: str = Field(description="Fanza content ID string (e.g. 'myvi00001').")
    title: str = Field(description="Title of the video as shown in the Fanza library.")
    content_type: Literal["video", "vr"] = Field(
        description="Whether this is a standard video or a VR video."
    )
    package_image_url: str = Field(
        description="URL of the cover image. Points to the local image cache endpoint."
    )
    parts: int = Field(
        description="Number of downloadable/streamable parts for this item."
    )
    purchase_date: datetime = Field(description="Date and time the item was purchased.")
    expire: date = Field(description="Date on which access to this item expires.")
    trans_type: Literal["download", "stream"] = Field(
        description="Whether the item is available for download or streaming only."
    )
    javstash_id: str | None = Field(
        default=None,
        description="JAVStash ID for this item (e.g. '1a2b3c4d-5e6f-47a8-9b9c-0d1e2f3a4b5c'), if available.",
    )
    javstash_studio_code: str | None = Field(
        default=None,
        description="JAVStash studio code (e.g. 'MYVI-001'), if available.",
    )


class _DevExpireBody(BaseModel):
    mylibrary_id: int


def _serialize(item: LibraryItemContentsModel) -> LibraryItemResponse:
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


@router.post(
    "/refresh/",
    responses={502: {"description": "Failed to fetch the library from Fanza."}},
)
async def refresh_library(
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict[str, str]:
    """Fetch the latest library state from Fanza and update local data.

    Takes a snapshot of the current library before updating, then compares it
    with the new state to detect newly added items. After updating:

    - The stream cache is cleared.
    - Stale cover-image cache entries are purged.
    - Filename data is rescanned and stored.
    - Background tasks warm item details and pre-cache cover images.
    - If ``auto_download_new_items`` or ``auto_download_missing_parts`` is
      enabled, newly discovered items are enqueued for download.

    Returns:
        ``{"status": "ok"}`` once the synchronous refresh completes (background
        tasks may still be running).

    Raises:
        HTTPException: 502 if the Fanza API call fails.
    """
    old_snapshot: dict[int, str] = {
        vid_id: item.content_id for vid_id, item in manager.library.items()
    }
    try:
        await asyncio.to_thread(manager.update_library)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to refresh library: {exc}",
        ) from exc
    await run_post_update(manager, app_state, old_snapshot=old_snapshot, enqueue=True)
    return {"status": "ok"}


@router.post(
    "/expire/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_dev_mode)],
    responses={404: {"description": "Item not found in the current library."}},
)
def dev_expire_item(
    body: _DevExpireBody,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    _: Annotated[None, Depends(require_api_key)],
) -> None:
    """Mark a library item as expired (development/testing only).

    Moves the item to the unavailable-items database table so it shows up
    in the expired-items list. This endpoint is only accessible when the
    application is running in dev mode.

    Raises:
        HTTPException: 404 if the mylibrary_id is not in the current library.
    """
    if manager.library.get(body.mylibrary_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in library"
        )
    mark_item_unavailable(LIBRARY_DB_PATH, body.mylibrary_id)


@router.get("/expired/")
def get_expired_library(
    _: Annotated[None, Depends(require_api_key)],
) -> list[LibraryItemResponse]:
    """Return library items whose access has expired.

    These are items that were previously in the library but are no longer
    accessible (e.g. their licence has lapsed). They remain in the local
    database for reference.

    Returns:
        A list of LibraryItemResponse entries for unavailable items.
    """
    rows = get_unavailable_items(LIBRARY_DB_PATH)
    return [
        LibraryItemResponse(
            mylibrary_id=row["mylibrary_id"],
            content_id=row["content_id"],
            title=row["title"],
            content_type=row["content_type"],
            package_image_url=f"/api/images/{row['content_id']}",
            parts=row["parts"],
            purchase_date=row["purchase_date"],
            expire=row["expire"],
            trans_type=row["trans_type"],
            **(
                json.loads(row["javstash_info_json"])
                if row.get("javstash_info_json")
                else {}
            ),
        )
        for row in rows
    ]


@router.delete(
    "/expired/{mylibrary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "No expired item with the given mylibrary_id."}},
)
def delete_expired_item(
    mylibrary_id: int,
    _: Annotated[None, Depends(require_api_key)],
) -> None:
    """Remove an expired item from the local unavailable-items database.

    Args:
        mylibrary_id: The Fanza mylibrary ID of the expired item to remove.

    Raises:
        HTTPException: 404 if no expired item with that ID exists.
    """
    if not delete_unavailable_item(LIBRARY_DB_PATH, mylibrary_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Expired item not found"
        )


@router.get("/download-counts/")
def get_download_counts(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict[str, int]:
    """Return the number of downloaded parts for each library item.

    Args:
        app_state: Injected application state providing download counts.

    Returns:
        A dict mapping ``content_id`` to the count of downloaded ``.mp4`` files.
    """
    return app_state.download_counts


@router.get(
    "/{video_id}",
    responses={404: {"description": "No library item with the given video_id."}},
)
def get_item(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    _: Annotated[None, Depends(require_api_key)],
) -> LibraryItemResponse:
    """Return a single library item by its mylibrary_id.

    Args:
        video_id: The Fanza ``mylibrary_id`` of the item to retrieve.

    Returns:
        The matching LibraryItemResponse.

    Raises:
        HTTPException: 404 if no item with that ID is in the library.
    """
    item = manager.library.get(video_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )
    return _serialize(item)


@router.get("/")
def get_library(
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict[int, LibraryItemResponse]:
    """Return all items in the user's Fanza library.

    Returns:
        A dict mapping each item's ``mylibrary_id`` (int) to its
        LibraryItemResponse. Returns an empty dict if no account is connected.
    """
    return {k: _serialize(v) for k, v in manager.library.items()}
