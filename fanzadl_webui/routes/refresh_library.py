import asyncio

from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, Request

from fanzadl_webui.dependencies import get_manager, settings, verify_api_key
from fanzadl_webui.routes.images import precache_all

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.post("/refresh_library/")
async def refresh_library(
    request: Request,
    manager: FanzaDLManager = Depends(get_manager),
) -> dict[str, str]:
    manager.update_library()
    asyncio.create_task(
        precache_all(manager, request.app.state.http_client, settings.image_cache_dir)
    )
    return {"status": "ok"}
