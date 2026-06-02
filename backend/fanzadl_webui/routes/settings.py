import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Annotated

import bcrypt
import httpx
from apscheduler.triggers.cron import CronTrigger
from fanzadl.exceptions import MalformedEmailError, WrongCredentialsError
from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    JAVSTASH_KEY_PATH,
    LIBRARY_DB_PATH,
    TOKEN_STORE_PATH,
    get_app_state,
    require_api_key,
)
from fanzadl_webui.library_db import (
    delete_all,
    save_library_db,
    update_javstash_info_db,
)
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes import images
from fanzadl_webui.routes._utils import _fire_background
from fanzadl_webui.routes.download import cancel_active_jobs
from fanzadl_webui.scheduler import schedule_library_refresh, unschedule_library_refresh
from fanzadl_webui.state import AppState
from fanzadl_webui.store.api_key import delete_api_key
from fanzadl_webui.store.config import AppConfig, LogLevel, load_config, save_config
from fanzadl_webui.store.token import delete_tokens
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr

router = APIRouter()


class ApiKeyInfo(BaseModel):
    api_key: str | None
    api_key_preview: str
    persisted: bool


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
    fanza_connected: bool
    fanza_user_id: str | None

    @classmethod
    def from_state(cls, app_state: AppState) -> "AppSettings":
        return cls(
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
            fanza_connected=app_state.manager is not None,
            fanza_user_id=app_state.manager.user_id
            if app_state.manager is not None
            else None,
        )


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


class WebhookTestResult(BaseModel):
    status_code: int | None = None
    ok: bool | None = None
    error: str | None = None


class WebhookTestRequest(BaseModel):
    url: AnyHttpUrl


async def _apply_javstash_key(api_key: str | None, app_state: AppState) -> None:
    manager = app_state.manager
    if api_key:
        app_state.javstash_api_key = api_key
        app_state.javstash_enabled = True
        app_state.save_api_key_fn(api_key)
        if manager is not None:
            manager.javstash_api_key = api_key
            # Propagate the key to every existing item and evict any
            # None-cached _javstash_info so the cached_property re-fetches.
            _secret = SecretStr(api_key)
            for _item in manager.library.values():
                _item._javstash_api_key = _secret  # noqa: SLF001
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

            _fire_background(app_state.background_tasks, _warm_and_save())
    else:
        app_state.javstash_api_key = None
        app_state.javstash_enabled = False
        delete_api_key(JAVSTASH_KEY_PATH)
        if manager is not None:
            manager.javstash_api_key = None


async def _save_config(app_state: AppState) -> None:
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


@router.get("/settings/")
def get_settings(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> AppSettings:
    return AppSettings.from_state(app_state)


@router.patch("/settings/")
async def update_settings(  # noqa: C901, PLR0912
    body: AppSettingsPatch,
    request: Request,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> AppSettings:
    if body.library_refresh_cron is not None:
        try:
            CronTrigger.from_crontab(body.library_refresh_cron)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid cron expression: {exc}",
            ) from exc
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
        await _apply_javstash_key(body.javstash_api_key, app_state)
    if body.library_refresh_cron is not None:
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
    await _save_config(app_state)
    return AppSettings.from_state(app_state)


@router.post("/settings/webhook/test")
async def run_test_webhook(
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

    envelope_enc = json.dumps(envelope).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = app_state.webhook_secret
    if secret:
        sig = hmac.new(secret.encode(), envelope_enc, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={sig}"
    try:
        response = await app_state.http_client.post(
            url,
            content=envelope_enc,
            headers=headers,
            timeout=httpx.Timeout(5.0),
        )
        return WebhookTestResult(
            status_code=response.status_code, ok=response.is_success
        )
    except Exception as exc:  # noqa: BLE001
        return WebhookTestResult(error=str(exc))


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


_FANZA_RATE_LIMIT_WINDOW = 60.0
_FANZA_RATE_LIMIT_MAX = 10
_fanza_attempts: dict[str, list[float]] = {}
_fanza_rate_lock = asyncio.Lock()


class FanzaConnectRequest(BaseModel):
    email: str
    password: str


@router.post("/settings/fanza/connect")
async def connect_fanza(
    request: Request,
    body: FanzaConnectRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict:
    ip = request.client.host if request.client else "unknown"
    async with _fanza_rate_lock:
        now = time.monotonic()
        window_start = now - _FANZA_RATE_LIMIT_WINDOW
        recent = [t for t in _fanza_attempts.get(ip, []) if t > window_start]
        if len(recent) >= _FANZA_RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many connect attempts. Please try again later.",
            )
        _fanza_attempts[ip] = recent

    try:
        manager = await asyncio.to_thread(
            PersistingFanzaDLManager,
            email=body.email,
            password=body.password,
            save_fn=app_state.save_fn,
            javstash_api_key=app_state.javstash_api_key,
            library_db_path=LIBRARY_DB_PATH,
            auto_populate_library=False,
        )
        await asyncio.to_thread(manager.update_library)
    except WrongCredentialsError as exc:
        async with _fanza_rate_lock:
            _fanza_attempts.setdefault(ip, []).append(time.monotonic())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect Fanza email or password.",
        ) from exc
    except MalformedEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Malformed email address.",
        ) from exc

    async with _fanza_rate_lock:
        _fanza_attempts.pop(ip, None)

    app_state.save_fn(manager.user_id, manager.refresh_token)
    app_state.manager = manager
    await asyncio.to_thread(images.purge_stale, manager, IMAGE_CACHE_DIR)

    async def _warm_and_save(m: PersistingFanzaDLManager) -> None:
        restored = m._ids_restored_from_cache  # noqa: SLF001
        new_ids = set(m.library) - restored
        await warm_all_details(m, item_ids=new_ids)
        await asyncio.to_thread(
            save_library_db,
            LIBRARY_DB_PATH,
            m.user_id,
            m,
            new_ids,
        )
        m._ids_restored_from_cache = set()  # noqa: SLF001

    for coro in (
        images.precache_all(manager, app_state.http_client, IMAGE_CACHE_DIR),
        _warm_and_save(manager),
    ):
        task = asyncio.create_task(coro)
        app_state.background_tasks.add(task)
        task.add_done_callback(app_state.background_tasks.discard)

    return {"status": "ok"}


class AppPasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.patch("/settings/app-password")
async def change_app_password(
    body: AppPasswordChangeRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict:
    config = await asyncio.to_thread(load_config, app_state.config_path)
    if config.app_password_hash is None or not bcrypt.checkpw(
        body.current_password.encode(), config.app_password_hash.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )
    new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    updated = config.model_copy(update={"app_password_hash": new_hash})
    await asyncio.to_thread(save_config, app_state.config_path, updated)
    return {"status": "ok"}


@router.delete("/settings/fanza/disconnect")
async def disconnect_fanza(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict:
    for task in list(app_state.background_tasks):
        task.cancel()
    app_state.background_tasks.clear()

    await cancel_active_jobs(app_state)

    app_state.jobs.clear()
    app_state.queues.clear()

    delete_tokens(TOKEN_STORE_PATH)
    delete_all(LIBRARY_DB_PATH)
    app_state.manager = None

    return {"status": "ok"}
