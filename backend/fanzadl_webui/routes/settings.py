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
from fanzadl_webui.models import StatusResponse
from fanzadl_webui.routes._utils import _fire_background
from fanzadl_webui.routes.download import cancel_active_jobs
from fanzadl_webui.routes.library.refresh import run_post_update
from fanzadl_webui.scheduler import schedule_library_refresh, unschedule_library_refresh
from fanzadl_webui.state import AppState
from fanzadl_webui.store.api_key import delete_api_key
from fanzadl_webui.store.config import AppConfig, LogLevel, load_config, save_config
from fanzadl_webui.store.token import delete_tokens
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

router = APIRouter(prefix="/settings", tags=["Settings"])


class ApiKeyInfo(BaseModel):
    """Current API key state returned to the client."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "api_key": None,
                "api_key_preview": "abcd1234...",
                "persisted": True,
            }
        }
    )

    api_key: str | None = Field(
        description="Full API key value — only populated immediately after a rotate operation; ``null`` otherwise."
    )
    api_key_preview: str = Field(
        description="First 8 characters of the current API key followed by ``...`` for identification without exposure."
    )
    persisted: bool = Field(
        description="Whether the API key has been saved to disk and will survive a restart."
    )


class AppSettings(BaseModel):
    """All current application settings, as read from state."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "max_concurrent_downloads": 3,
                "log_level": "INFO",
                "download_thread_count": 4,
                "javstash_enabled": False,
                "single_part_filename_template": "{title}",
                "multi_part_filename_template": "{title}/{title}_part{part}",
                "library_refresh_enabled": True,
                "library_refresh_cron": "0 * * * *",
                "auto_download_new_items": False,
                "auto_download_missing_parts": False,
                "webhook_url": None,
                "webhook_secret_configured": False,
                "webhook_events": ["download_done"],
                "fanza_connected": True,
                "fanza_user_id": "user@example.com",
                "auth_disabled": False,
            }
        }
    )

    max_concurrent_downloads: int = Field(
        description="Maximum number of download jobs that run in parallel."
    )
    log_level: LogLevel = Field(description="Active Python logging level.")
    download_thread_count: int = Field(
        description="Number of threads used per download worker."
    )
    javstash_enabled: bool = Field(
        description="Whether the JAVStash integration is active."
    )
    single_part_filename_template: str = Field(
        description="Filename template applied to single-part downloads."
    )
    multi_part_filename_template: str = Field(
        description="Filename template applied to multi-part downloads."
    )
    library_refresh_enabled: bool = Field(
        description="Whether automatic scheduled library refresh is enabled."
    )
    library_refresh_cron: str = Field(
        description="Cron expression controlling the library refresh schedule."
    )
    auto_download_new_items: bool = Field(
        description="Whether newly discovered library items are queued for download automatically."
    )
    auto_download_missing_parts: bool = Field(
        description="Whether parts missing from disk are re-queued automatically after a library refresh."
    )
    webhook_url: str | None = Field(
        description="URL to which webhook events are posted, or ``null`` if not configured."
    )
    webhook_secret_configured: bool = Field(
        description="Whether an HMAC signing secret for webhooks is configured."
    )
    webhook_events: list[str] = Field(
        description="List of event types that trigger a webhook call."
    )
    fanza_connected: bool = Field(
        description="Whether a Fanza account is currently authenticated."
    )
    fanza_user_id: str | None = Field(
        description="Fanza user ID of the connected account, or ``null`` if not connected."
    )
    auth_disabled: bool = Field(
        description="Whether the application password requirement is disabled."
    )

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
            auth_disabled=app_state.auth_disabled,
        )


class AppSettingsPatch(BaseModel):
    """Partial update body for application settings. Only supplied fields are applied."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "max_concurrent_downloads": 3,
                "library_refresh_enabled": True,
                "library_refresh_cron": "0 * * * *",
            }
        }
    )

    max_concurrent_downloads: int | None = Field(
        default=None, ge=1, description="New parallel download limit."
    )
    log_level: LogLevel | None = Field(default=None, description="New logging level.")
    download_thread_count: int | None = Field(
        default=None, ge=1, le=32, description="New download thread count (1–32)."
    )
    javstash_api_key: str | None = Field(
        default=None,
        description="JAVStash API key to store; set to ``null`` to remove it.",
    )
    single_part_filename_template: str | None = Field(
        default=None, description="New filename template for single-part items."
    )
    multi_part_filename_template: str | None = Field(
        default=None, description="New filename template for multi-part items."
    )
    library_refresh_enabled: bool | None = Field(
        default=None, description="Enable or disable the scheduled library refresh."
    )
    library_refresh_cron: str | None = Field(
        default=None,
        description="New cron expression for the library refresh schedule.",
    )
    auto_download_new_items: bool | None = Field(
        default=None,
        description="Enable or disable auto-download of new library items.",
    )
    auto_download_missing_parts: bool | None = Field(
        default=None, description="Enable or disable auto-download of missing parts."
    )
    webhook_url: AnyHttpUrl | None = Field(
        default=None, description="New webhook target URL."
    )
    webhook_secret: str | None = Field(
        default=None, description="HMAC signing secret for webhook payloads."
    )
    webhook_events: list[str] | None = Field(
        default=None, description="Event types that should trigger webhook calls."
    )
    auth_disabled: bool | None = Field(
        default=None,
        description="Enable or disable the application password requirement.",
    )


class WebhookTestResult(BaseModel):
    """Outcome of a webhook test delivery attempt."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"status_code": 200, "ok": True, "error": None}}
    )

    status_code: int | None = Field(
        default=None, description="HTTP status code returned by the webhook endpoint."
    )
    ok: bool | None = Field(
        default=None,
        description="True if the endpoint responded with a 2xx status code.",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the request could not be delivered at all.",
    )


class WebhookTestRequest(BaseModel):
    """Request body for the webhook test endpoint."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"url": "https://my-server.example.com/hook"}}
    )

    url: AnyHttpUrl = Field(description="URL to send the test webhook event to.")


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
            auth_disabled=app_state.auth_disabled,
        ),
    )


@router.get("/")
def get_settings(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> AppSettings:
    """Return all current application settings.

    Returns:
        An AppSettings snapshot reflecting the live application state.
    """
    return AppSettings.from_state(app_state)


@router.patch(
    "/",
    responses={
        422: {"description": "Invalid cron expression in library_refresh_cron."}
    },
)
async def update_settings(  # noqa: C901, PLR0912
    body: AppSettingsPatch,
    request: Request,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> AppSettings:
    """Update one or more application settings.

    Only the fields explicitly supplied in the request body are applied; omitted
    fields are left unchanged. Side-effects include:

    - Adjusting the concurrency condition when ``max_concurrent_downloads`` changes.
    - Propagating the JAVStash API key to all cached library items and triggering
      a background detail-warm if the key changes.
    - Rescheduling or cancelling the library-refresh APScheduler job when
      ``library_refresh_enabled`` or ``library_refresh_cron`` changes.
    - Persisting the updated config to disk.

    Args:
        body: Partial settings update. All fields are optional.

    Returns:
        The full AppSettings reflecting the new state.

    Raises:
        HTTPException: 422 if ``library_refresh_cron`` is not a valid cron expression.
    """
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
    if body.auth_disabled is not None:
        app_state.auth_disabled = body.auth_disabled
    _refresh_enabled = app_state.library_refresh_enabled
    _refresh_cron = app_state.library_refresh_cron
    if _refresh_enabled:
        schedule_library_refresh(request.app, _refresh_cron)
    else:
        unschedule_library_refresh(request.app)
    await _save_config(app_state)
    return AppSettings.from_state(app_state)


@router.post("/webhook/test")
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


@router.get("/api-key")
def get_api_key(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> ApiKeyInfo:
    """Return a preview of the current API key.

    The full key value is never returned here — use ``POST /api-key/rotate``
    to receive a new key value.

    Returns:
        An ApiKeyInfo with ``api_key`` set to ``null``.
    """
    key = app_state.local_api_key
    return ApiKeyInfo(
        api_key=None,
        api_key_preview=key[:8] + "...",
        persisted=app_state.local_api_key_persisted,
    )


@router.post("/api-key/rotate")
def rotate_api_key(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> ApiKeyInfo:
    """Generate and activate a new random API key.

    The old key is immediately invalidated. If the key was previously persisted
    to disk, the new key is also saved. The full new key is returned once in
    the ``api_key`` field.

    Returns:
        An ApiKeyInfo with the new key value in ``api_key``.
    """
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
    """Fanza account credentials for the connect endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "user@example.com", "password": "mypassword"}
        }
    )

    email: str = Field(description="Fanza account email address.")
    password: str = Field(description="Fanza account password.")


@router.post(
    "/fanza/connect",
    response_model=StatusResponse,
    responses={
        401: {"description": "Incorrect Fanza email or password."},
        422: {"description": "Malformed email address."},
        429: {"description": "Too many connect attempts from this IP."},
    },
)
async def connect_fanza(
    request: Request,
    body: FanzaConnectRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> StatusResponse:
    """Authenticate with Fanza and load the user's library.

    Attempts to create a new authenticated FanzaDL session using the supplied
    credentials. On success, the library is fetched and a set of background
    tasks warm item details and pre-cache cover images. Connection attempts per
    IP are rate-limited to 10 per 60-second window.

    Returns:
        ``{"status": "ok"}`` once the session is established and the library
        has been fetched.

    Raises:
        HTTPException: 401 if the credentials are incorrect.
        HTTPException: 422 if the email address is malformed.
        HTTPException: 429 if the rate limit for the requesting IP is exceeded.
    """
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
    await run_post_update(manager, app_state)

    return StatusResponse(status="ok")


class AppPasswordChangeRequest(BaseModel):
    """Request body for changing the application login password."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "current_password": "oldpassword",
                "new_password": "newpassword",
            }
        }
    )

    current_password: str = Field(
        description="The currently configured application password."
    )
    new_password: str = Field(description="The new password to set.")


@router.patch(
    "/app-password",
    response_model=StatusResponse,
    responses={401: {"description": "Current password is incorrect."}},
)
async def change_app_password(
    body: AppPasswordChangeRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> StatusResponse:
    """Change the application login password.

    Verifies the current password before applying the change. The new password
    is hashed with bcrypt and persisted to the config file.

    Returns:
        ``{"status": "ok"}`` on success.

    Raises:
        HTTPException: 401 if the current password does not match.
    """
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
    return StatusResponse(status="ok")


@router.delete("/fanza/disconnect", response_model=StatusResponse)
async def disconnect_fanza(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> StatusResponse:
    """Disconnect the Fanza account and wipe all local state.

    Cancels all background tasks and active download jobs, clears the in-memory
    job queue, deletes stored authentication tokens, and removes the local
    library database. The application returns to an unauthenticated state.

    Returns:
        ``{"status": "ok"}`` once the account has been disconnected.
    """
    for task in list(app_state.background_tasks):
        task.cancel()
    app_state.background_tasks.clear()

    await cancel_active_jobs(app_state)

    app_state.jobs.clear()
    app_state.queues.clear()

    delete_tokens(TOKEN_STORE_PATH)
    delete_all(LIBRARY_DB_PATH)
    app_state.manager = None

    return StatusResponse(status="ok")
