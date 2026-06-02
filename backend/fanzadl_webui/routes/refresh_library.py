import asyncio
from typing import Annotated

from fanzadl import FanzaDLManager
from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    LIBRARY_DB_PATH,
    get_app_state,
    get_manager,
    require_api_key,
)
from fanzadl_webui.events import publish_library_event
from fanzadl_webui.filename import rescan_and_store
from fanzadl_webui.library_db import save_library_db
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.models import LibraryEvent
from fanzadl_webui.routes.download import (
    auto_enqueue_missing_parts,
    auto_enqueue_new_items,
)
from fanzadl_webui.routes.images import precache_all, purge_stale
from fanzadl_webui.state import AppState
from fanzadl_webui.webhook import fire_webhook
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter()

_background_tasks: set[asyncio.Task] = set()


async def _publish_library_diff(
    old_snapshot: dict[int, str],
    manager: FanzaDLManager,
    app_state: AppState,
) -> None:
    current_ids = set(manager.library)
    old_ids_set = set(old_snapshot)
    for vid_id in current_ids - old_ids_set:
        item = manager.library.get(vid_id)
        if item is not None:
            publish_library_event(
                app_state,
                LibraryEvent(
                    type="item_added",
                    content_id=item.content_id,
                    title=getattr(item, "title", None),
                    mylibrary_id=vid_id,
                ),
            )
            _wh_task = asyncio.create_task(
                fire_webhook(
                    app_state,
                    "item_added",
                    {
                        "content_id": item.content_id,
                        "title": getattr(item, "title", None),
                        "mylibrary_id": vid_id,
                    },
                )
            )
            app_state.background_tasks.add(_wh_task)
            _wh_task.add_done_callback(app_state.background_tasks.discard)
    for vid_id in old_ids_set - current_ids:
        publish_library_event(
            app_state,
            LibraryEvent(
                type="item_expired",
                content_id=old_snapshot[vid_id],
                mylibrary_id=vid_id,
            ),
        )
        _wh_task = asyncio.create_task(
            fire_webhook(
                app_state,
                "item_expired",
                {
                    "content_id": old_snapshot[vid_id],
                    "mylibrary_id": vid_id,
                },
            )
        )
        app_state.background_tasks.add(_wh_task)
        _wh_task.add_done_callback(app_state.background_tasks.discard)


async def _warm_save_and_enqueue(
    manager: FanzaDLManager,
    app_state: AppState,
    old_snapshot: dict[int, str],
) -> None:
    new_ids: set[int] | None = None
    if isinstance(manager, PersistingFanzaDLManager):
        new_ids = set(manager.library) - manager._ids_restored_from_cache  # noqa: SLF001
    await warm_all_details(manager, item_ids=new_ids)
    if isinstance(manager, PersistingFanzaDLManager):
        await asyncio.to_thread(
            save_library_db,
            LIBRARY_DB_PATH,
            manager.user_id,
            manager,
            new_ids or set(),
        )
        manager._ids_restored_from_cache = set()  # noqa: SLF001
    await _publish_library_diff(old_snapshot, manager, app_state)
    auto_new_ids = (new_ids or set()) if app_state.auto_download_new_items else set()
    if app_state.auto_download_new_items and new_ids:
        await auto_enqueue_new_items(new_ids, app_state)
    if app_state.auto_download_missing_parts:
        await auto_enqueue_missing_parts(auto_new_ids, app_state)


@router.post("/refresh_library/")
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
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    return {"status": "ok"}
