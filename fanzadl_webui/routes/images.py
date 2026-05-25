import asyncio
import logging
from pathlib import Path
from typing import Annotated

import httpx
from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, get_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images")


def _cache_path(cache_dir: Path, mylibrary_id: int) -> Path:
    return cache_dir / f"{mylibrary_id}.jpg"


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
    for mylibrary_id, item in manager.library.items():
        dest = _cache_path(cache_dir, mylibrary_id)
        if dest.exists():
            continue
        try:
            await _fetch_and_cache(http_client, str(item.package_image_url), dest)
        except Exception:
            pass  # best-effort; missing images will be fetched on demand


def purge_stale(manager: FanzaDLManager, cache_dir: Path) -> None:
    for cached in cache_dir.glob("*.jpg"):
        try:
            mylibrary_id = int(cached.stem)
        except ValueError:
            cached.unlink()
            continue
        if mylibrary_id not in manager.library:
            cached.unlink()


@router.get("/{mylibrary_id}")
async def get_image(
    mylibrary_id: int,
    request: Request,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
) -> FileResponse:
    dest = _cache_path(IMAGE_CACHE_DIR, mylibrary_id)

    if not dest.exists():
        item = manager.library.get(mylibrary_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found",
            )
        await _fetch_and_cache(
            request.app.state.http_client,
            str(item.package_image_url),
            dest,
        )

    return FileResponse(dest, media_type="image/jpeg")
