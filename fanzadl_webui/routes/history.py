import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from fanzadl_webui.dependencies import get_app_state, require_api_key
from fanzadl_webui.history_db import (
    delete_all_history,
    delete_history_by_ids,
    get_history,
)
from fanzadl_webui.state import AppState

router = APIRouter()


class HistoryItem(BaseModel):
    id: int
    job_id: str
    status: Literal["done", "error"]
    output_name: str
    content_id: str | None
    source: Literal["manual", "auto"]
    file_size: int | None
    output_path: str | None
    error: str | None
    bandwidth_mbps: float | None
    completed_at: str


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int


class HistoryDeleteRequest(BaseModel):
    ids: list[int] | None = None
    all: bool = False


@router.get(
    "/history/",
    response_model=HistoryPage,
    dependencies=[Depends(require_api_key)],
)
async def list_history(
    app_state: Annotated[AppState, Depends(get_app_state)],
    status: Annotated[Literal["all", "done", "error"], Query()] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HistoryPage:
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
    if body.all:
        await asyncio.to_thread(delete_all_history, app_state.history_db_path)
    elif body.ids:
        await asyncio.to_thread(
            delete_history_by_ids, app_state.history_db_path, body.ids
        )
