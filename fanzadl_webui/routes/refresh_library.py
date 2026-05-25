import asyncio
from typing import Annotated

from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, Request, status

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, get_manager
from fanzadl_webui.routes.images import precache_all

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
    task = asyncio.create_task(
        precache_all(manager, request.app.state.http_client, IMAGE_CACHE_DIR)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "ok"}
