import asyncio
import logging
from typing import Annotated, Literal

import httpx
import m3u8
from fanzadl import FanzaDLManager
from fanzadl_webui.dependencies import get_app_state, get_manager, require_api_key
from fanzadl_webui.models import StreamVariant
from fanzadl_webui.routes._utils import get_quality_obj
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, HTTPException, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streams", tags=["Streams"])


@router.get(
    "/",
    responses={
        404: {
            "description": "Video not found in the library or has no streamable quality."
        },
        502: {"description": "Failed to fetch the HLS master playlist from upstream."},
    },
)
async def get_streams(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
    part: int | None = None,
    quality: Literal["highest"] = "highest",  # noqa: ARG001
) -> list[StreamVariant]:
    """Return the available HLS stream variants for a library item.

    Fetches the master playlist for the requested video and part, parses the
    variant entries, and returns them sorted by their position in the playlist.
    Results are cached in memory for the lifetime of the process to avoid
    redundant upstream requests.

    If the playlist URL returns a transient error (404, 429, 503), one retry
    is attempted after a short delay.

    Args:
        video_id: The ``mylibrary_id`` of the library item.
        part: The 1-based part number. Defaults to part 1 when omitted.
        quality: Quality selection strategy — currently only ``"highest"`` is supported.

    Returns:
        A list of StreamVariant objects. Returns an empty list if the playlist
        is not a master (variant) playlist.

    Raises:
        HTTPException: 404 if the video is not found or has no streamable quality.
        HTTPException: 502 if the upstream playlist request fails.
    """
    cache_key = (video_id, part)
    cached: list[StreamVariant] | None = app_state.stream_cache.get(cache_key)
    if cached is not None:
        return cached

    quality_obj = get_quality_obj(video_id, manager)
    playlist_url = (
        quality_obj.get_url(part) if part is not None else quality_obj.get_url(1)
    )
    for attempt in range(2):
        try:
            response = await app_state.http_client.get(
                playlist_url, follow_redirects=True
            )
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
        app_state.stream_cache[cache_key] = []
        return []

    variants = [
        StreamVariant(
            index=i,
            bandwidth=p.stream_info.bandwidth,
            codecs=p.stream_info.codecs,
            uri=p.absolute_uri,
        )
        for i, p in enumerate(parsed.playlists)
    ]
    app_state.stream_cache[cache_key] = variants
    return variants
