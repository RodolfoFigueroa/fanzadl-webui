from typing import Annotated, Literal

import httpx
import m3u8
from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from fanzadl_webui.dependencies import get_manager
from fanzadl_webui.jobs import get_http_client
from fanzadl_webui.routes._utils import get_quality_obj


class StreamVariant(BaseModel):
    index: int
    bandwidth: int
    resolution: str | None
    codecs: str | None
    uri: str


router = APIRouter(prefix="/streams")


@router.get("/")
async def get_streams(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    part: int | None = None,
    quality: Literal["highest"] = "highest",  # noqa: ARG001
) -> list[StreamVariant]:
    quality_obj = get_quality_obj(video_id, manager)
    playlist_url = (
        quality_obj.get_url(part) if part is not None else quality_obj.get_url(1)
    )
    try:
        response = await http_client.get(playlist_url, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch playlist: {e.response.status_code}",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to reach playlist URL: {e}",
        ) from e

    parsed = m3u8.loads(response.text, uri=playlist_url)

    if not parsed.is_variant:
        return []

    return [
        StreamVariant(
            index=i,
            bandwidth=p.stream_info.bandwidth,
            resolution=(
                f"{p.stream_info.resolution[0]}x{p.stream_info.resolution[1]}"
                if p.stream_info.resolution
                else None
            ),
            codecs=p.stream_info.codecs,
            uri=p.absolute_uri,
        )
        for i, p in enumerate(parsed.playlists)
    ]
