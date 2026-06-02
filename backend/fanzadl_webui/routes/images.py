import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Annotated

import httpx
from fanzadl import FanzaDLManager
from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    LIBRARY_DB_PATH,
    get_app_state,
    get_manager,
    require_api_key,
)
from fanzadl_webui.library_db import get_unavailable_items
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["Images"])


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
    all_items = list(manager.library.values())
    for item in all_items:
        dest = _cache_path(cache_dir, item.content_id)
        if dest.exists():
            continue

        with contextlib.suppress(Exception):
            await _fetch_and_cache(http_client, str(item.package_image_url), dest)


def purge_stale(manager: FanzaDLManager, cache_dir: Path) -> None:
    known = {item.content_id for item in manager.library.values()} | {
        row["content_id"] for row in get_unavailable_items(LIBRARY_DB_PATH)
    }
    for cached in cache_dir.glob("*.jpg"):
        if cached.stem not in known:
            cached.unlink()


@router.get(
    "/{content_id}",
    responses={
        400: {
            "description": "Invalid content ID (contains path-traversal characters)."
        },
        404: {"description": "No library item found with the given content ID."},
        502: {"description": "Failed to fetch the image from the upstream CDN."},
    },
)
async def get_image(
    content_id: str,
    app_state: Annotated[AppState, Depends(get_app_state)],
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    _: Annotated[None, Depends(require_api_key)],
) -> FileResponse:
    """Return the cover image for a library item, fetching and caching it on first request.

    Images are cached locally as ``{content_id}.jpg``. If the cached file does not
    exist yet the image is fetched from the upstream CDN and saved before being
    served. Subsequent requests are served directly from the local cache.

    Args:
        content_id: The Fanza content ID whose cover image to return.

    Returns:
        A JPEG image response.

    Raises:
        HTTPException: 400 if content_id contains ``/``, ``\\``, or ``..``.
        HTTPException: 404 if no library item with that content_id is found.
    """
    if "/" in content_id or "\\" in content_id or ".." in content_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid content ID",
        )
    dest = _cache_path(IMAGE_CACHE_DIR, content_id)

    if not dest.exists():
        item = next(
            (i for i in manager.library.values() if i.content_id == content_id), None
        )
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
