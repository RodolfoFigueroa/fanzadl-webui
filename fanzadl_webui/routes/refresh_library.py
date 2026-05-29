import asyncio
from typing import Annotated

from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, Request, status

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, get_manager
from fanzadl_webui.manager import warm_all_details
from fanzadl_webui.routes.images import precache_all, purge_stale

router = APIRouter()

_background_tasks: set[asyncio.Task] = set()


@router.post("/refresh_library/")
async def refresh_library(
    request: Request,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> dict[str, str]:
    try:
        manager.update_library()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to refresh library: {exc}",
        ) from exc
    request.app.state.stream_cache = {}
    await asyncio.to_thread(purge_stale, manager, IMAGE_CACHE_DIR)
    for coro in (
        precache_all(manager, request.app.state.http_client, IMAGE_CACHE_DIR),
        warm_all_details(manager),
    ):
        task = asyncio.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    return {"status": "ok"}
