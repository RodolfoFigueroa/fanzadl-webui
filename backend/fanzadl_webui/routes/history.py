import asyncio
from typing import Annotated, Literal

from fanzadl_webui.dependencies import get_app_state, require_api_key
from fanzadl_webui.history_db import (
    delete_all_history,
    delete_history_by_ids,
    get_history,
)
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(tags=["History"])


class HistoryItem(BaseModel):
    """A single completed or failed download recorded in history."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "status": "done",
                "output_name": "MyVideo/MyVideo_part1",
                "content_id": "mide00001",
                "source": "manual",
                "file_size": 1181116006,
                "output_path": "/downloads/MyVideo/MyVideo_part1.mp4",
                "error": None,
                "bandwidth_mbps": 12.4,
                "completed_at": "2026-06-01T10:30:00+00:00",
            }
        }
    )

    id: int = Field(description="Auto-incremented primary key in the history database.")
    job_id: str = Field(description="UUID of the originating download job.")
    status: Literal["done", "error"] = Field(
        description="Final outcome of the download."
    )
    output_name: str = Field(
        description="Relative output path (without extension) inside the download directory."
    )
    content_id: str | None = Field(
        default=None, description="Fanza content ID of the downloaded item, if known."
    )
    source: Literal["manual", "auto"] = Field(
        description="Whether the download was triggered manually or by auto-enqueue."
    )
    file_size: int | None = Field(
        default=None, description="Final on-disk file size in bytes."
    )
    output_path: str | None = Field(
        default=None, description="Absolute path to the completed output file."
    )
    error: str | None = Field(
        default=None, description="Error message if the download failed."
    )
    bandwidth_mbps: float | None = Field(
        default=None, description="Average download bandwidth in Mbit/s."
    )
    completed_at: str = Field(
        description="ISO 8601 timestamp when the download finished."
    )


class HistoryPage(BaseModel):
    """A paginated slice of the download history."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [],
                "total": 42,
                "page": 1,
                "page_size": 50,
            }
        }
    )

    items: list[HistoryItem] = Field(description="The history entries on this page.")
    total: int = Field(description="Total number of matching history records.")
    page: int = Field(description="Current page number (1-based).")
    page_size: int = Field(description="Maximum number of items returned per page.")


class HistoryDeleteRequest(BaseModel):
    """Request body for deleting history records."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"ids": [1, 2, 3], "all": False}}
    )

    ids: list[int] | None = Field(
        default=None,
        description="Explicit list of history record IDs to delete. Ignored when ``all`` is true.",
    )
    all: bool = Field(
        default=False,
        description="When true, delete every history record regardless of ``ids``.",
    )


@router.get(
    "/history/",
    dependencies=[Depends(require_api_key)],
)
async def list_history(
    app_state: Annotated[AppState, Depends(get_app_state)],
    status: Annotated[Literal["all", "done", "error"], Query()] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryPage:
    """Return a paginated list of completed download history entries.

    Args:
        status: Filter by outcome — ``all`` returns every entry, ``done``
            returns only successful downloads, ``error`` returns only failed ones.
        page: 1-based page number.
        page_size: Number of records per page (1–200, default 50).

    Returns:
        A HistoryPage containing the matching entries and pagination metadata.
    """
    offset = (page - 1) * page_size
    entries, total = await asyncio.to_thread(
        get_history,
        app_state.history_db_path,
        status,
        offset,
        page_size,
    )
    return HistoryPage(
        items=[
            HistoryItem(
                id=e.id,
                job_id=e.job_id,
                status=e.status,
                output_name=e.output_name,
                content_id=e.content_id,
                source=e.source,
                file_size=e.file_size,
                output_path=e.output_path,
                error=e.error,
                bandwidth_mbps=e.bandwidth_mbps,
                completed_at=e.completed_at,
            )
            for e in entries
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/history/",
    status_code=204,
    dependencies=[Depends(require_api_key)],
)
async def delete_history(
    body: HistoryDeleteRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
) -> None:
    """Delete history records selectively or in bulk.

    If ``body.all`` is true, every record is deleted regardless of ``body.ids``.
    If ``body.ids`` is provided and ``body.all`` is false, only those specific
    records are removed. Supplying neither field is a no-op.

    Args:
        body: Deletion parameters — either a list of IDs or a flag to clear all.
    """
    if body.all:
        await asyncio.to_thread(delete_all_history, app_state.history_db_path)
    elif body.ids:
        await asyncio.to_thread(
            delete_history_by_ids, app_state.history_db_path, body.ids
        )
