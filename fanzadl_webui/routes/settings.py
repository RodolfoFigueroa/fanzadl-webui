import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class AppSettings(BaseModel):
    max_concurrent_downloads: int


class AppSettingsPatch(BaseModel):
    max_concurrent_downloads: int = Field(ge=1)


@router.get("/settings/")
def get_settings(request: Request) -> AppSettings:
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
    )


@router.patch("/settings/")
async def update_settings(body: AppSettingsPatch, request: Request) -> AppSettings:
    request.app.state.max_concurrent_downloads = body.max_concurrent_downloads
    condition: asyncio.Condition = request.app.state.download_slot_condition
    async with condition:
        condition.notify_all()
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
    )
