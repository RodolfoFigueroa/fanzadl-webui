import asyncio

from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, Request

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, get_manager
from fanzadl_webui.routes.images import precache_all

router = APIRouter()


@router.post("/refresh_library/")
async def refresh_library(
    request: Request,
    manager: FanzaDLManager = Depends(get_manager),
) -> dict[str, str]:
    manager.update_library()
    asyncio.create_task(
        precache_all(manager, request.app.state.http_client, IMAGE_CACHE_DIR)
    )
    return {"status": "ok"}
