import asyncio
import json
from datetime import date, datetime
from typing import Annotated, Literal

from fanzadl import FanzaDLManager
from fanzadl.models.video import LibraryItemContentsModel
from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    LIBRARY_DB_PATH,
    get_app_state,
    get_manager,
    require_api_key,
    require_dev_mode,
)
from fanzadl_webui.filename import rescan_and_store
from fanzadl_webui.library_db import (
    delete_unavailable_item,
    get_unavailable_items,
    mark_item_unavailable,
)
from fanzadl_webui.routes.images import precache_all, purge_stale
from fanzadl_webui.routes.library.refresh import (
    _warm_save_and_enqueue,
)
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/library", tags=["Library"])


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


@router.post("/refresh/")
async def refresh_library(
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict[str, str]:
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
    app_state.stream_cache = {}
    await asyncio.to_thread(purge_stale, manager, IMAGE_CACHE_DIR)
    await rescan_and_store(app_state)
    for coro in (
        precache_all(manager, app_state.http_client, IMAGE_CACHE_DIR),
        _warm_save_and_enqueue(manager, app_state, old_snapshot),
    ):
        task = asyncio.create_task(coro)
        app_state.background_tasks.add(task)
        task.add_done_callback(app_state.background_tasks.discard)
    return {"status": "ok"}


@router.post(
    "/expire/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_dev_mode)],
)
def dev_expire_item(
    body: _DevExpireBody,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    _: Annotated[None, Depends(require_api_key)],
) -> None:
    if manager.library.get(body.mylibrary_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in library"
        )
    mark_item_unavailable(LIBRARY_DB_PATH, body.mylibrary_id)


@router.get("/expired/")
def get_expired_library(
    _: Annotated[None, Depends(require_api_key)],
) -> list[LibraryItemResponse]:
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


@router.delete("/expired/{mylibrary_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expired_item(
    mylibrary_id: int,
    _: Annotated[None, Depends(require_api_key)],
) -> None:
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


@router.get("/{video_id}")
def get_item(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    _: Annotated[None, Depends(require_api_key)],
) -> LibraryItemResponse:
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
    return {k: _serialize(v) for k, v in manager.library.items()}
