import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from fanzadl_webui.api_key_store import delete_api_key
from fanzadl_webui.config_store import AppConfig, save_config
from fanzadl_webui.dependencies import (
    JAVSTASH_KEY_PATH,
    LIBRARY_CACHE_PATH,
)
from fanzadl_webui.library_cache import save_library_cache
from fanzadl_webui.manager import warm_all_details

router = APIRouter()

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_background_tasks: set[asyncio.Task] = set()


class AppSettings(BaseModel):
    max_concurrent_downloads: int
    log_level: LogLevel
    download_thread_count: int
    javstash_enabled: bool


class AppSettingsPatch(BaseModel):
    max_concurrent_downloads: int | None = Field(default=None, ge=1)
    log_level: LogLevel | None = None
    download_thread_count: int | None = Field(default=None, ge=1, le=32)
    javstash_api_key: str | None = None


@router.get("/settings/")
def get_settings(request: Request) -> AppSettings:
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
        log_level=request.app.state.log_level,
        download_thread_count=request.app.state.download_thread_count,
        javstash_enabled=request.app.state.javstash_enabled,
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
    if body.download_thread_count is not None:
        request.app.state.download_thread_count = body.download_thread_count
    if "javstash_api_key" in body.model_fields_set:
        manager = request.app.state.manager
        if body.javstash_api_key:
            request.app.state.javstash_api_key = body.javstash_api_key
            request.app.state.javstash_enabled = True
            request.app.state.save_api_key_fn(body.javstash_api_key)
            if manager is not None:
                manager.javstash_api_key = body.javstash_api_key

                async def _warm_and_save() -> None:
                    await warm_all_details(manager)
                    await asyncio.to_thread(
                        save_library_cache,
                        LIBRARY_CACHE_PATH,
                        manager.user_id,
                        manager,
                    )

                _task = asyncio.create_task(_warm_and_save())
                _background_tasks.add(_task)
                _task.add_done_callback(_background_tasks.discard)
        else:
            request.app.state.javstash_api_key = None
            request.app.state.javstash_enabled = False
            delete_api_key(JAVSTASH_KEY_PATH)
            if manager is not None:
                manager.javstash_api_key = None
    await asyncio.to_thread(
        save_config,
        request.app.state.config_path,
        AppConfig(
            max_concurrent_downloads=request.app.state.max_concurrent_downloads,
            log_level=request.app.state.log_level,
            download_thread_count=request.app.state.download_thread_count,
        ),
    )
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
        log_level=request.app.state.log_level,
        download_thread_count=request.app.state.download_thread_count,
        javstash_enabled=request.app.state.javstash_enabled,
    )
