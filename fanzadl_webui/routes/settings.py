import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated

import httpx
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr

from fanzadl_webui.dependencies import (
    JAVSTASH_KEY_PATH,
    LIBRARY_DB_PATH,
    get_app_state,
    require_api_key,
)
from fanzadl_webui.library_db import save_library_db, update_javstash_info_db
from fanzadl_webui.manager import warm_all_details
from fanzadl_webui.scheduler import schedule_library_refresh, unschedule_library_refresh
from fanzadl_webui.state import AppState
from fanzadl_webui.store.api_key import delete_api_key
from fanzadl_webui.store.config import AppConfig, LogLevel, save_config

router = APIRouter()

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
    auto_download_new_items: bool
    auto_download_missing_parts: bool
    webhook_url: str | None
    webhook_secret_configured: bool
    webhook_events: list[str]


class AppSettingsPatch(BaseModel):
    max_concurrent_downloads: int | None = Field(default=None, ge=1)
    log_level: LogLevel | None = None
    download_thread_count: int | None = Field(default=None, ge=1, le=32)
    javstash_api_key: str | None = None
    single_part_filename_template: str | None = None
    multi_part_filename_template: str | None = None
    library_refresh_enabled: bool | None = None
    library_refresh_cron: str | None = None
    auto_download_new_items: bool | None = None
    auto_download_missing_parts: bool | None = None
    webhook_url: AnyHttpUrl | None = None
    webhook_secret: str | None = None
    webhook_events: list[str] | None = None


@router.get("/settings/")
def get_settings(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> AppSettings:
    return AppSettings(
        max_concurrent_downloads=app_state.max_concurrent_downloads,
        log_level=app_state.log_level,
        download_thread_count=app_state.download_thread_count,
        javstash_enabled=app_state.javstash_enabled,
        single_part_filename_template=app_state.single_part_filename_template,
        multi_part_filename_template=app_state.multi_part_filename_template,
        library_refresh_enabled=app_state.library_refresh_enabled,
        library_refresh_cron=app_state.library_refresh_cron,
        auto_download_new_items=app_state.auto_download_new_items,
        auto_download_missing_parts=app_state.auto_download_missing_parts,
        webhook_url=app_state.webhook_url,
        webhook_secret_configured=app_state.webhook_secret is not None,
        webhook_events=app_state.webhook_events,
    )


@router.patch("/settings/")
async def update_settings(
    body: AppSettingsPatch,
    request: Request,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> AppSettings:
    if body.max_concurrent_downloads is not None:
        app_state.max_concurrent_downloads = body.max_concurrent_downloads
        condition = app_state.download_slot_condition
        async with condition:
            condition.notify_all()
    if body.log_level is not None:
        app_state.log_level = body.log_level
        logging.getLogger().setLevel(body.log_level)
    if body.download_thread_count is not None:
        app_state.download_thread_count = body.download_thread_count
    if body.single_part_filename_template is not None:
        app_state.single_part_filename_template = body.single_part_filename_template
    if body.multi_part_filename_template is not None:
        app_state.multi_part_filename_template = body.multi_part_filename_template
    if "javstash_api_key" in body.model_fields_set:
        manager = app_state.manager
        if body.javstash_api_key:
            app_state.javstash_api_key = body.javstash_api_key
            app_state.javstash_enabled = True
            app_state.save_api_key_fn(body.javstash_api_key)
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
                    _new_ids = set(manager.library) - manager._ids_restored_from_cache  # noqa: SLF001
                    await asyncio.to_thread(
                        save_library_db,
                        LIBRARY_DB_PATH,
                        manager.user_id,
                        manager,
                        _new_ids,
                    )
                    await asyncio.to_thread(
                        update_javstash_info_db, LIBRARY_DB_PATH, manager
                    )

                _task = asyncio.create_task(_warm_and_save())
                _background_tasks.add(_task)
                _task.add_done_callback(_background_tasks.discard)
        else:
            app_state.javstash_api_key = None
            app_state.javstash_enabled = False
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
        app_state.library_refresh_cron = body.library_refresh_cron
    if body.library_refresh_enabled is not None:
        app_state.library_refresh_enabled = body.library_refresh_enabled
    if body.auto_download_new_items is not None:
        app_state.auto_download_new_items = body.auto_download_new_items
    if body.auto_download_missing_parts is not None:
        app_state.auto_download_missing_parts = body.auto_download_missing_parts
    if "webhook_url" in body.model_fields_set:
        app_state.webhook_url = str(body.webhook_url) if body.webhook_url else None
    if "webhook_secret" in body.model_fields_set:
        app_state.webhook_secret = body.webhook_secret or None
    if body.webhook_events is not None:
        app_state.webhook_events = body.webhook_events
    _refresh_enabled = app_state.library_refresh_enabled
    _refresh_cron = app_state.library_refresh_cron
    if _refresh_enabled:
        schedule_library_refresh(request.app, _refresh_cron)
    else:
        unschedule_library_refresh(request.app)
    await asyncio.to_thread(
        save_config,
        app_state.config_path,
        AppConfig(
            max_concurrent_downloads=app_state.max_concurrent_downloads,
            log_level=app_state.log_level,
            download_thread_count=app_state.download_thread_count,
            single_part_filename_template=app_state.single_part_filename_template,
            multi_part_filename_template=app_state.multi_part_filename_template,
            library_refresh_enabled=app_state.library_refresh_enabled,
            library_refresh_cron=app_state.library_refresh_cron,
            auto_download_new_items=app_state.auto_download_new_items,
            auto_download_missing_parts=app_state.auto_download_missing_parts,
            webhook_url=app_state.webhook_url,
            webhook_secret=app_state.webhook_secret,
            webhook_events=app_state.webhook_events,
        ),
    )
    return AppSettings(
        max_concurrent_downloads=app_state.max_concurrent_downloads,
        log_level=app_state.log_level,
        download_thread_count=app_state.download_thread_count,
        javstash_enabled=app_state.javstash_enabled,
        single_part_filename_template=app_state.single_part_filename_template,
        multi_part_filename_template=app_state.multi_part_filename_template,
        library_refresh_enabled=app_state.library_refresh_enabled,
        library_refresh_cron=app_state.library_refresh_cron,
        auto_download_new_items=app_state.auto_download_new_items,
        auto_download_missing_parts=app_state.auto_download_missing_parts,
        webhook_url=app_state.webhook_url,
        webhook_secret_configured=app_state.webhook_secret is not None,
        webhook_events=app_state.webhook_events,
    )


class WebhookTestResult(BaseModel):
    status_code: int | None = None
    ok: bool | None = None
    error: str | None = None


class WebhookTestRequest(BaseModel):
    url: AnyHttpUrl


@router.post("/settings/webhook/test")
async def test_webhook(
    body: WebhookTestRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> WebhookTestResult:
    """Send a test event to the configured webhook URL.

    Returns the HTTP status code received, or an error message if the
    request could not be delivered.

    Raises:
        HTTPException: 400 if no webhook URL is configured.
    """
    url = str(body.url)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No webhook URL configured",
        )
    envelope = {
        "event": "test",
        "timestamp": datetime.now(UTC).isoformat(),
        "data": {},
    }
    body = json.dumps(envelope).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = app_state.webhook_secret
    if secret:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={sig}"
    try:
        response = await app_state.http_client.post(
            url,
            content=body,
            headers=headers,
            timeout=httpx.Timeout(5.0),
        )
        return WebhookTestResult(
            status_code=response.status_code, ok=response.is_success
        )
    except Exception as exc:  # noqa: BLE001
        return WebhookTestResult(error=str(exc))


class ApiKeyInfo(BaseModel):
    api_key: str | None
    api_key_preview: str
    persisted: bool


@router.get("/settings/api-key")
def get_api_key(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> ApiKeyInfo:
    key = app_state.local_api_key
    return ApiKeyInfo(
        api_key=None,
        api_key_preview=key[:8] + "...",
        persisted=app_state.local_api_key_persisted,
    )


@router.post("/settings/api-key/rotate")
def rotate_api_key(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> ApiKeyInfo:
    new_key = secrets.token_urlsafe(32)
    app_state.local_api_key = new_key
    if app_state.local_api_key_persisted:
        app_state.save_local_api_key_fn(new_key)
    return ApiKeyInfo(
        api_key=new_key,
        api_key_preview=new_key[:8] + "...",
        persisted=app_state.local_api_key_persisted,
    )
