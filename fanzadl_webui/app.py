import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fanzadl.exceptions import AuthExpiredError
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from fanzadl_webui.api_key_store import load_api_key, save_api_key
from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    JAVSTASH_KEY_PATH,
    LIBRARY_CACHE_PATH,
    TOKEN_STORE_PATH,
)
from fanzadl_webui.library_cache import save_library_cache
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes import (
    auth,
    download,
    images,
    library,
    refresh_library,
    settings,
    streams,
    url,
)
from fanzadl_webui.token_store import delete_tokens, load_tokens, save_tokens

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _default_log_level = os.environ.get("DEFAULT_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=_default_log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    async with httpx.AsyncClient() as client:
        app.state.http_client = client
        app.state.manager = None
        app.state.jobs: dict = {}
        app.state.queues: dict = {}
        app.state.max_concurrent_downloads: int = 3
        app.state.log_level: str = _default_log_level
        app.state.download_slot_condition = asyncio.Condition()
        app.state.background_tasks: set[asyncio.Task] = set()
        app.state.login_lock = asyncio.Lock()
        app.state.stream_cache: dict = {}
        _enc_key_str = os.environ.get("TOKEN_ENCRYPTION_KEY")
        if _enc_key_str:
            _enc_key = _enc_key_str.encode()

            def save_fn(user_id: str, refresh_token: str) -> None:
                save_tokens(TOKEN_STORE_PATH, _enc_key, user_id, refresh_token)

            def save_api_key_fn(api_key: str) -> None:
                save_api_key(JAVSTASH_KEY_PATH, _enc_key, api_key)

            _javstash_api_key = load_api_key(JAVSTASH_KEY_PATH, _enc_key)
        else:

            def save_fn(user_id: str, refresh_token: str) -> None:  # type: ignore[misc]
                pass

            def save_api_key_fn(api_key: str) -> None:  # type: ignore[misc]
                pass

            _javstash_api_key = None

        app.state.save_fn = save_fn
        app.state.save_api_key_fn = save_api_key_fn
        app.state.javstash_api_key: str | None = _javstash_api_key
        app.state.javstash_enabled: bool = _javstash_api_key is not None

        if _enc_key_str:
            tokens = load_tokens(TOKEN_STORE_PATH, _enc_key)
            if tokens is not None:
                _user_id, _refresh_token = tokens
                try:
                    _manager = await asyncio.to_thread(
                        PersistingFanzaDLManager,
                        user_id=_user_id,
                        refresh_token=_refresh_token,
                        save_fn=save_fn,
                        javstash_api_key=_javstash_api_key,
                        library_cache_path=LIBRARY_CACHE_PATH,
                        auto_populate_library=False,
                    )
                    await asyncio.to_thread(_manager.update_library)
                    app.state.manager = _manager
                    await asyncio.to_thread(
                        images.purge_stale, _manager, IMAGE_CACHE_DIR
                    )

                    async def _warm_and_save() -> None:
                        _restored = _manager._ids_restored_from_cache  # noqa: SLF001
                        _new_ids = set(_manager.library) - _restored
                        await warm_all_details(_manager, item_ids=_new_ids)
                        await asyncio.to_thread(
                            save_library_cache,
                            LIBRARY_CACHE_PATH,
                            _manager.user_id,
                            _manager,
                        )
                        _manager._ids_restored_from_cache = set()  # noqa: SLF001

                    for _coro in (
                        images.precache_all(_manager, client, IMAGE_CACHE_DIR),
                        _warm_and_save(),
                    ):
                        _task = asyncio.create_task(_coro)
                        app.state.background_tasks.add(_task)
                        _task.add_done_callback(app.state.background_tasks.discard)
                    logger.info("Session restored from token store")
                except AuthExpiredError:
                    logger.warning("Stored tokens are expired; deleting token store")
                    delete_tokens(TOKEN_STORE_PATH)
                except Exception:
                    logger.exception(
                        "Failed to restore session from token store; deleting token store"
                    )
                    delete_tokens(TOKEN_STORE_PATH)

        yield


app = FastAPI(lifespan=lifespan)

app.include_router(auth.router, prefix="/api")
app.include_router(library.router, prefix="/api")
app.include_router(refresh_library.router, prefix="/api")
app.include_router(url.router, prefix="/api")
app.include_router(streams.router, prefix="/api")
app.include_router(download.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(images.router, prefix="/api")

_dist = Path(__file__).parent.parent / "frontend" / "dist"
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
