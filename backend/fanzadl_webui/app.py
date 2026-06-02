import asyncio
import logging
import os
import secrets
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import bcrypt
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fanzadl.exceptions import AuthExpiredError
from fanzadl_webui.dependencies import (
    CONFIG_PATH,
    HISTORY_DB_PATH,
    IMAGE_CACHE_DIR,
    JAVSTASH_KEY_PATH,
    LIBRARY_DB_PATH,
    LOCAL_API_KEY_PATH,
    TOKEN_STORE_PATH,
)
from fanzadl_webui.filename import rescan_and_store
from fanzadl_webui.history_db import init_history_db
from fanzadl_webui.library_db import save_library_db
from fanzadl_webui.log_handler import NotificationHandler
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes import (
    auth,
    download,
    history,
    images,
    library,
    notifications,
    refresh_library,
    settings,
    streams,
    url,
)
from fanzadl_webui.scheduler import schedule_library_refresh
from fanzadl_webui.state import AppState
from fanzadl_webui.store.api_key import load_api_key, save_api_key
from fanzadl_webui.store.config import AppConfig, load_config, save_config
from fanzadl_webui.store.token import delete_tokens, load_tokens, save_tokens
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Scope

_MAX_BODY_BYTES = 64 * 1024  # 64 KB

logger = logging.getLogger(__name__)


def _setup_logging(default_log_level: str, config: AppConfig) -> None:
    logging.basicConfig(
        level=default_log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger().setLevel(config.log_level)


def _load_or_create_config(default_log_level: str) -> AppConfig:
    config_exists = CONFIG_PATH.exists()
    config = load_config(CONFIG_PATH)
    if not config_exists:
        config = config.model_copy(update={"log_level": default_log_level})
        save_config(CONFIG_PATH, config)
    return config


def _make_persistence_handlers(
    enc_key_str: str | None,
) -> tuple[
    Callable[[str, str], None],
    Callable[[str], None],
    Callable[[str], None],
    str | None,
    str,
    bool,
]:
    if enc_key_str:
        enc_key = enc_key_str.encode()

        def save_fn(user_id: str, refresh_token: str) -> None:
            save_tokens(TOKEN_STORE_PATH, enc_key, user_id, refresh_token)

        def save_api_key_fn(api_key: str) -> None:
            save_api_key(JAVSTASH_KEY_PATH, enc_key, api_key)

        def save_local_api_key_fn(api_key: str) -> None:
            save_api_key(LOCAL_API_KEY_PATH, enc_key, api_key)

        javstash_api_key = load_api_key(JAVSTASH_KEY_PATH, enc_key)
        local_api_key = load_api_key(LOCAL_API_KEY_PATH, enc_key)
        if local_api_key is None:
            local_api_key = secrets.token_urlsafe(32)
            save_local_api_key_fn(local_api_key)
        local_api_key_persisted = True
    else:

        def save_fn(user_id: str, refresh_token: str) -> None:
            pass

        def save_api_key_fn(api_key: str) -> None:
            pass

        def save_local_api_key_fn(api_key: str) -> None:
            pass

        javstash_api_key = None
        local_api_key = secrets.token_urlsafe(32)
        local_api_key_persisted = False

    return (
        save_fn,
        save_api_key_fn,
        save_local_api_key_fn,
        javstash_api_key,
        local_api_key,
        local_api_key_persisted,
    )


def _init_app_state(  # noqa: PLR0913
    app: FastAPI,
    config: AppConfig,
    client: httpx.AsyncClient,
    save_fn: Callable[[str, str], None],
    save_api_key_fn: Callable[[str], None],
    save_local_api_key_fn: Callable[[str], None],
    javstash_api_key: str | None,
    local_api_key: str,
    local_api_key_persisted: bool,  # noqa: FBT001
    scheduler: AsyncIOScheduler,
) -> None:
    app.state.app_state = AppState(
        http_client=client,
        manager=None,
        max_concurrent_downloads=config.max_concurrent_downloads,
        log_level=config.log_level,
        download_thread_count=config.download_thread_count,
        single_part_filename_template=config.single_part_filename_template,
        multi_part_filename_template=config.multi_part_filename_template,
        library_refresh_enabled=config.library_refresh_enabled,
        library_refresh_cron=config.library_refresh_cron,
        auto_download_new_items=config.auto_download_new_items,
        auto_download_missing_parts=config.auto_download_missing_parts,
        webhook_url=config.webhook_url,
        webhook_secret=config.webhook_secret,
        webhook_events=config.webhook_events,
        history_db_path=HISTORY_DB_PATH,
        config_path=CONFIG_PATH,
        save_fn=save_fn,
        save_api_key_fn=save_api_key_fn,
        save_local_api_key_fn=save_local_api_key_fn,
        javstash_api_key=javstash_api_key,
        javstash_enabled=javstash_api_key is not None,
        local_api_key=local_api_key,
        local_api_key_persisted=local_api_key_persisted,
        scheduler=scheduler,
    )


async def _warm_and_save(manager: PersistingFanzaDLManager) -> None:
    restored = manager._ids_restored_from_cache  # noqa: SLF001
    new_ids = set(manager.library) - restored
    await warm_all_details(manager, item_ids=new_ids)
    await asyncio.to_thread(
        save_library_db,
        LIBRARY_DB_PATH,
        manager.user_id,
        manager,
        new_ids,
    )
    manager._ids_restored_from_cache = set()  # noqa: SLF001


async def _try_restore_session(
    app: FastAPI,
    enc_key: bytes,
    save_fn: Callable[[str, str], None],
    javstash_api_key: str | None,
    client: httpx.AsyncClient,
) -> None:
    tokens = load_tokens(TOKEN_STORE_PATH, enc_key)
    if tokens is None:
        return
    user_id, refresh_token = tokens
    try:
        manager = await asyncio.to_thread(
            PersistingFanzaDLManager,
            user_id=user_id,
            refresh_token=refresh_token,
            save_fn=save_fn,
            javstash_api_key=javstash_api_key,
            library_db_path=LIBRARY_DB_PATH,
            auto_populate_library=False,
        )
        await asyncio.to_thread(manager.update_library)
        state = app.state.app_state
        state.manager = manager
        await asyncio.to_thread(images.purge_stale, manager, IMAGE_CACHE_DIR)
        await rescan_and_store(state)
        for coro in (
            images.precache_all(manager, client, IMAGE_CACHE_DIR),
            _warm_and_save(manager),
        ):
            task = asyncio.create_task(coro)
            state.background_tasks.add(task)
            task.add_done_callback(state.background_tasks.discard)
        logger.info("Session restored from token store")
    except AuthExpiredError:
        logger.warning("Stored tokens are expired; deleting token store")
        delete_tokens(TOKEN_STORE_PATH)
    except Exception:
        logger.exception(
            "Failed to restore session from token store; deleting token store"
        )
        delete_tokens(TOKEN_STORE_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    default_log_level = os.environ.get("DEFAULT_LOG_LEVEL", "INFO").upper()
    config = _load_or_create_config(default_log_level)
    if config.app_password_hash is None:
        plaintext = secrets.token_urlsafe(12)
        hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
        config = config.model_copy(update={"app_password_hash": hashed})
        save_config(CONFIG_PATH, config)
        logger.warning("App password generated: %s", plaintext)
    _setup_logging(default_log_level, config)
    enc_key_str = os.environ.get("TOKEN_ENCRYPTION_KEY")
    notification_handler: NotificationHandler | None = None
    (
        save_fn,
        save_api_key_fn,
        save_local_api_key_fn,
        javstash_api_key,
        local_api_key,
        local_api_key_persisted,
    ) = _make_persistence_handlers(enc_key_str)
    scheduler = AsyncIOScheduler()
    scheduler.start()
    await asyncio.to_thread(init_history_db, HISTORY_DB_PATH)
    async with httpx.AsyncClient() as client:
        _init_app_state(
            app,
            config,
            client,
            save_fn,
            save_api_key_fn,
            save_local_api_key_fn,
            javstash_api_key,
            local_api_key,
            local_api_key_persisted,
            scheduler,
        )
        loop = asyncio.get_running_loop()
        notification_handler = NotificationHandler(
            app.state.app_state.notification_queues, loop
        )
        logging.getLogger().addHandler(notification_handler)
        if enc_key_str:
            await _try_restore_session(
                app, enc_key_str.encode(), save_fn, javstash_api_key, client
            )
        if config.library_refresh_enabled:
            schedule_library_refresh(app, config.library_refresh_cron)
        if not enc_key_str:
            logger.warning(
                "TOKEN_ENCRYPTION_KEY is not set — token and API key persistence is "
                "disabled. The local API key will be regenerated on every restart."
            )
        if os.environ.get("FANZADL_DEV") == "1":
            logger.warning(
                "FANZADL_DEV is enabled — developer mutation routes are active. "
                "Do not use this setting in a production environment."
            )
        try:
            yield
        finally:
            if notification_handler is not None:
                logging.getLogger().removeHandler(notification_handler)
            scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def _max_body_size_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                return Response(content="Request body too large", status_code=413)
        except ValueError:
            pass
    return await call_next(request)


@app.middleware("http")
async def _security_headers_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'"
    )
    return response


app.include_router(auth.router, prefix="/api")
app.include_router(library.router, prefix="/api")
app.include_router(refresh_library.router, prefix="/api")
app.include_router(url.router, prefix="/api")
app.include_router(streams.router, prefix="/api")
app.include_router(download.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(images.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(history.router, prefix="/api")

_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.is_dir():

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope: Scope) -> Response:
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    app.mount("/", SPAStaticFiles(directory=str(_dist), html=True), name="spa")
