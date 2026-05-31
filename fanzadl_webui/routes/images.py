import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Annotated

import httpx
from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, get_app_state, get_manager
from fanzadl_webui.state import AppState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images")


def _cache_path(cache_dir: Path, content_id: str) -> Path:
    return cache_dir / f"{content_id}.jpg"


async def _fetch_and_cache(
    http_client: httpx.AsyncClient,
    url: str,
    dest: Path,
) -> None:
    response = await http_client.get(url, follow_redirects=True)
    response.raise_for_status()
    await asyncio.to_thread(dest.write_bytes, response.content)


async def precache_all(
    manager: FanzaDLManager,
    http_client: httpx.AsyncClient,
    cache_dir: Path,
) -> None:
    all_items = list(manager.library.values()) + list(manager.expired_library.values())
    for item in all_items:
        dest = _cache_path(cache_dir, item.content_id)
        if dest.exists():
            continue

        with contextlib.suppress(Exception):
            await _fetch_and_cache(http_client, str(item.package_image_url), dest)


def purge_stale(manager: FanzaDLManager, cache_dir: Path) -> None:
    known = {item.content_id for item in manager.library.values()} | {
        item.content_id for item in manager.expired_library.values()
    }
    for cached in cache_dir.glob("*.jpg"):
        if cached.stem not in known:
            cached.unlink()


@router.get("/{content_id}")
async def get_image(
    content_id: str,
    app_state: Annotated[AppState, Depends(get_app_state)],
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> FileResponse:
    dest = _cache_path(IMAGE_CACHE_DIR, content_id)

    if not dest.exists():
        all_items = list(manager.library.values()) + list(
            manager.expired_library.values()
        )
        item = next((i for i in all_items if i.content_id == content_id), None)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found",
            )
        await _fetch_and_cache(
            app_state.http_client,
            str(item.package_image_url),
            dest,
        )

    return FileResponse(dest, media_type="image/jpeg")
