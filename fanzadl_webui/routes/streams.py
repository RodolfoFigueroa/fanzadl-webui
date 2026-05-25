import asyncio
import logging
from typing import Annotated, Literal

import httpx
import m3u8
from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from fanzadl_webui.dependencies import get_manager
from fanzadl_webui.jobs import get_http_client
from fanzadl_webui.routes._utils import get_quality_obj


class StreamVariant(BaseModel):
    index: int
    bandwidth: int
    codecs: str | None
    uri: str | None = None


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streams")


@router.get("/")
async def get_streams(  # noqa: PLR0913
    request: Request,
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    part: int | None = None,
    quality: Literal["highest"] = "highest",  # noqa: ARG001
) -> list[StreamVariant]:
    cache_key = (video_id, part)
    cached: list[StreamVariant] | None = request.app.state.stream_cache.get(cache_key)
    if cached is not None:
        return cached

    quality_obj = get_quality_obj(video_id, manager)
    playlist_url = (
        quality_obj.get_url(part) if part is not None else quality_obj.get_url(1)
    )
    for attempt in range(2):
        try:
            response = await http_client.get(playlist_url, follow_redirects=True)
            response.raise_for_status()
            break
        except httpx.HTTPStatusError as e:
            if attempt == 0 and e.response.status_code in (404, 429, 503):
                logger.warning(
                    "Transient %s fetching playlist for video %s part %s, retrying",
                    e.response.status_code,
                    video_id,
                    part,
                )
                await asyncio.sleep(1.0)
                playlist_url = (
                    quality_obj.get_url(part)
                    if part is not None
                    else quality_obj.get_url(1)
                )
                continue
            logger.exception(
                "Failed to fetch playlist for video %s: HTTP %s",
                video_id,
                e.response.status_code,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch playlist: {e.response.status_code}",
            ) from e
        except httpx.RequestError as e:
            logger.exception(
                "Failed to reach playlist URL for video %s",
                video_id,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to reach playlist URL: {e}",
            ) from e

    parsed = m3u8.loads(response.text, uri=playlist_url)

    if not parsed.is_variant:
        request.app.state.stream_cache[cache_key] = []
        return []

    variants = [
        StreamVariant(
            index=i,
            bandwidth=p.stream_info.bandwidth,
            codecs=p.stream_info.codecs,
        )
        for i, p in enumerate(parsed.playlists)
    ]
    request.app.state.stream_cache[cache_key] = variants
    return variants
