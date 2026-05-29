import asyncio
from typing import Annotated

from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, Request, status

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, LIBRARY_CACHE_PATH, get_manager
from fanzadl_webui.library_cache import save_library_cache
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes.images import precache_all, purge_stale

router = APIRouter()

_background_tasks: set[asyncio.Task] = set()


@router.post("/refresh_library/")
async def refresh_library(
    request: Request,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> dict[str, str]:
    try:
        await asyncio.to_thread(manager.update_library)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to refresh library: {exc}",
        ) from exc
    request.app.state.stream_cache = {}
    await asyncio.to_thread(purge_stale, manager, IMAGE_CACHE_DIR)

    async def _warm_and_save() -> None:
        new_ids: set[int] | None = None
        if isinstance(manager, PersistingFanzaDLManager):
            new_ids = set(manager.library) - manager._ids_restored_from_cache  # noqa: SLF001
        await warm_all_details(manager, item_ids=new_ids)
        if isinstance(manager, PersistingFanzaDLManager):
            await asyncio.to_thread(
                save_library_cache, LIBRARY_CACHE_PATH, manager.user_id, manager
            )
            manager._ids_restored_from_cache = set()  # noqa: SLF001

    for coro in (
        precache_all(manager, request.app.state.http_client, IMAGE_CACHE_DIR),
        _warm_and_save(),
    ):
        task = asyncio.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    return {"status": "ok"}
