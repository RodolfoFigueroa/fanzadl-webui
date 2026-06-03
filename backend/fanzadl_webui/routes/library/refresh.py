import asyncio
import logging

from fanzadl import FanzaDLManager
from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    LIBRARY_DB_PATH,
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

logger = logging.getLogger(__name__)


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
            logger.info(
                "Library item added: mylibrary_id=%s content_id=%s title=%s",
                vid_id,
                item.content_id,
                getattr(item, "title", None),
            )
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
        logger.info(
            "Library item expired: mylibrary_id=%s content_id=%s",
            vid_id,
            old_snapshot[vid_id],
        )
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
    *,
    old_snapshot: dict[int, str] | None = None,
    enqueue: bool = False,
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
    if old_snapshot is not None:
        await _publish_library_diff(old_snapshot, manager, app_state)
    if enqueue:
        auto_new_ids = (
            (new_ids or set()) if app_state.auto_download_new_items else set()
        )
        if app_state.auto_download_new_items and new_ids:
            await auto_enqueue_new_items(new_ids, app_state)
        if app_state.auto_download_missing_parts:
            await auto_enqueue_missing_parts(auto_new_ids, app_state)


async def run_post_update(
    manager: FanzaDLManager,
    app_state: AppState,
    *,
    old_snapshot: dict[int, str] | None = None,
    enqueue: bool = False,
) -> None:
    """Run all post-library-update tasks.

    Synchronously clears the stream cache, purges stale image-cache entries,
    and rescans filename data.  Then fires background tasks to pre-cache cover
    images and warm/persist item details.

    Args:
        manager: The manager whose updated library will be processed.
        app_state: Shared application state.
        old_snapshot: Mapping of ``mylibrary_id`` to ``content_id`` captured
            *before* ``update_library()`` was called.  When provided, library
            diff events (``item_added`` / ``item_expired``) are published.
        enqueue: If ``True``, newly discovered items are enqueued for
            auto-download according to the current auto-download settings.
    """
    app_state.stream_cache = {}
    await asyncio.to_thread(purge_stale, IMAGE_CACHE_DIR)
    await rescan_and_store(app_state)

    async def _bg() -> None:
        await asyncio.gather(
            precache_all(manager, app_state.http_client, IMAGE_CACHE_DIR),
            _warm_save_and_enqueue(
                manager,
                app_state,
                old_snapshot=old_snapshot,
                enqueue=enqueue,
            ),
        )

    task = asyncio.create_task(_bg())
    app_state.background_tasks.add(task)
    task.add_done_callback(app_state.background_tasks.discard)
