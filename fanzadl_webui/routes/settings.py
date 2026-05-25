import logging
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import asyncio

router = APIRouter()

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class AppSettings(BaseModel):
    max_concurrent_downloads: int
    log_level: LogLevel


class AppSettingsPatch(BaseModel):
    max_concurrent_downloads: int | None = Field(default=None, ge=1)
    log_level: LogLevel | None = None


@router.get("/settings/")
def get_settings(request: Request) -> AppSettings:
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
        log_level=request.app.state.log_level,
    )


@router.patch("/settings/")
async def update_settings(body: AppSettingsPatch, request: Request) -> AppSettings:
    if body.max_concurrent_downloads is not None:
        request.app.state.max_concurrent_downloads = body.max_concurrent_downloads
        condition: asyncio.Condition = request.app.state.download_slot_condition
        async with condition:
            condition.notify_all()
    if body.log_level is not None:
        request.app.state.log_level = body.log_level
        logging.getLogger().setLevel(body.log_level)
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
        log_level=request.app.state.log_level,
    )
