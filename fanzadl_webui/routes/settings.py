import asyncio
import logging
from typing import Literal

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, SecretStr

from fanzadl_webui.api_key_store import delete_api_key
from fanzadl_webui.config_store import AppConfig, save_config
from fanzadl_webui.dependencies import (
    JAVSTASH_KEY_PATH,
    LIBRARY_CACHE_PATH,
)
from fanzadl_webui.library_cache import save_library_cache
from fanzadl_webui.manager import warm_all_details
from fanzadl_webui.scheduler import schedule_library_refresh, unschedule_library_refresh

router = APIRouter()

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_background_tasks: set[asyncio.Task] = set()


class AppSettings(BaseModel):
    max_concurrent_downloads: int
    log_level: LogLevel
    download_thread_count: int
    javstash_enabled: bool
    single_part_filename_template: str
    multi_part_filename_template: str
    library_refresh_enabled: bool
    library_refresh_cron: str


class AppSettingsPatch(BaseModel):
    max_concurrent_downloads: int | None = Field(default=None, ge=1)
    log_level: LogLevel | None = None
    download_thread_count: int | None = Field(default=None, ge=1, le=32)
    javstash_api_key: str | None = None
    single_part_filename_template: str | None = None
    multi_part_filename_template: str | None = None
    library_refresh_enabled: bool | None = None
    library_refresh_cron: str | None = None


@router.get("/settings/")
def get_settings(request: Request) -> AppSettings:
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
        log_level=request.app.state.log_level,
        download_thread_count=request.app.state.download_thread_count,
        javstash_enabled=request.app.state.javstash_enabled,
        single_part_filename_template=request.app.state.single_part_filename_template,
        multi_part_filename_template=request.app.state.multi_part_filename_template,
        library_refresh_enabled=request.app.state.library_refresh_enabled,
        library_refresh_cron=request.app.state.library_refresh_cron,
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
    if body.single_part_filename_template is not None:
        request.app.state.single_part_filename_template = (
            body.single_part_filename_template
        )
    if body.multi_part_filename_template is not None:
        request.app.state.multi_part_filename_template = (
            body.multi_part_filename_template
        )
    if "javstash_api_key" in body.model_fields_set:
        manager = request.app.state.manager
        if body.javstash_api_key:
            request.app.state.javstash_api_key = body.javstash_api_key
            request.app.state.javstash_enabled = True
            request.app.state.save_api_key_fn(body.javstash_api_key)
            if manager is not None:
                manager.javstash_api_key = body.javstash_api_key
                # Propagate the key to every existing item and evict any
                # None-cached _javstash_info so the cached_property re-fetches.
                _secret = SecretStr(body.javstash_api_key)
                for _item in manager.library.values():
                    _item._javstash_api_key = _secret
                    if _item.__dict__.get("_javstash_info") is None:
                        _item.__dict__.pop("_javstash_info", None)

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
    if body.library_refresh_cron is not None:
        try:
            CronTrigger.from_crontab(body.library_refresh_cron)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid cron expression: {exc}",
            ) from exc
        request.app.state.library_refresh_cron = body.library_refresh_cron
    if body.library_refresh_enabled is not None:
        request.app.state.library_refresh_enabled = body.library_refresh_enabled
    _refresh_enabled = request.app.state.library_refresh_enabled
    _refresh_cron = request.app.state.library_refresh_cron
    if _refresh_enabled:
        schedule_library_refresh(request.app, _refresh_cron)
    else:
        unschedule_library_refresh(request.app)
    await asyncio.to_thread(
        save_config,
        request.app.state.config_path,
        AppConfig(
            max_concurrent_downloads=request.app.state.max_concurrent_downloads,
            log_level=request.app.state.log_level,
            download_thread_count=request.app.state.download_thread_count,
            single_part_filename_template=request.app.state.single_part_filename_template,
            multi_part_filename_template=request.app.state.multi_part_filename_template,
            library_refresh_enabled=request.app.state.library_refresh_enabled,
            library_refresh_cron=request.app.state.library_refresh_cron,
        ),
    )
    return AppSettings(
        max_concurrent_downloads=request.app.state.max_concurrent_downloads,
        log_level=request.app.state.log_level,
        download_thread_count=request.app.state.download_thread_count,
        javstash_enabled=request.app.state.javstash_enabled,
        single_part_filename_template=request.app.state.single_part_filename_template,
        multi_part_filename_template=request.app.state.multi_part_filename_template,
        library_refresh_enabled=request.app.state.library_refresh_enabled,
        library_refresh_cron=request.app.state.library_refresh_cron,
    )
