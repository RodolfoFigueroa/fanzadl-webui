import asyncio
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

import requests
from fanzadl.exceptions import MalformedEmailError, WrongCredentialsError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    LIBRARY_DB_PATH,
    TOKEN_STORE_PATH,
    get_app_state,
    require_api_key,
)
from fanzadl_webui.library_db import delete_all, save_library_db
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes import images
from fanzadl_webui.routes.download import cancel_active_jobs
from fanzadl_webui.state import AppState
from fanzadl_webui.store.token import delete_tokens

logger = logging.getLogger(__name__)

_SESSION_TTL_HOURS = 24
_RATE_LIMIT_WINDOW = 60.0
_RATE_LIMIT_MAX = 10
_login_attempts: dict[str, list[float]] = {}
_login_rate_lock = asyncio.Lock()

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(
    request: Request,
    body: LoginRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    async with _login_rate_lock:
        now = time.monotonic()
        window_start = now - _RATE_LIMIT_WINDOW
        recent = [t for t in _login_attempts.get(ip, []) if t > window_start]
        if len(recent) >= _RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please try again later.",
            )
        _login_attempts[ip] = recent

    async with app_state.login_lock:
        if app_state.manager is not None:
            session_cookie = request.cookies.get("session")
            expiry = app_state.sessions.get(session_cookie) if session_cookie else None
            if expiry is not None and datetime.now(UTC) < expiry:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Already logged in",
                )
            # Manager was restored from disk but session was lost (e.g. restart).
            # Clear the manager so a fresh authentication can proceed.
            app_state.manager = None

        try:
            manager = await asyncio.to_thread(
                PersistingFanzaDLManager,
                email=body.email,
                password=body.password,
                javstash_api_key=app_state.javstash_api_key,
                save_fn=app_state.save_fn,
                library_db_path=LIBRARY_DB_PATH,
                auto_populate_library=False,
            )
            await asyncio.to_thread(manager.update_library)
        except MalformedEmailError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email address.",
            ) from exc
        except WrongCredentialsError as exc:
            async with _login_rate_lock:
                _login_attempts.setdefault(ip, []).append(time.monotonic())
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
            ) from exc
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not connect to the authentication service.",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Authentication failed. Please try again.",
            ) from exc

        app_state.manager = manager
        app_state.save_fn(manager.user_id, manager.refresh_token)

    async with _login_rate_lock:
        _login_attempts.pop(ip, None)

    session_token = secrets.token_urlsafe(32)
    app_state.sessions[session_token] = datetime.now(UTC) + timedelta(
        hours=_SESSION_TTL_HOURS
    )
    app_state.save_sessions_fn(app_state.sessions)

    response = JSONResponse(content={"status": "ok"})
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=_SESSION_TTL_HOURS * 3600,
    )

    await asyncio.to_thread(images.purge_stale, manager, IMAGE_CACHE_DIR)

    async def _warm_and_save() -> None:
        await warm_all_details(manager)
        _new_ids = set(manager.library) - manager._ids_restored_from_cache  # noqa: SLF001
        await asyncio.to_thread(
            save_library_db, LIBRARY_DB_PATH, manager.user_id, manager, _new_ids
        )
        manager._ids_restored_from_cache = set()  # noqa: SLF001

    for coro in (
        images.precache_all(manager, app_state.http_client, IMAGE_CACHE_DIR),
        _warm_and_save(),
    ):
        task = asyncio.create_task(coro)
        app_state.background_tasks.add(task)
        task.add_done_callback(app_state.background_tasks.discard)

    return response


@router.post("/logout")
async def logout(
    request: Request,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> JSONResponse:
    session_token = request.cookies.get("session")
    if session_token:
        app_state.sessions.pop(session_token, None)
        app_state.save_sessions_fn(app_state.sessions)

    for task in list(app_state.background_tasks):
        task.cancel()
    app_state.background_tasks.clear()

    jobs = app_state.jobs
    queues = app_state.queues

    await cancel_active_jobs(app_state)

    jobs.clear()
    queues.clear()

    delete_tokens(TOKEN_STORE_PATH)
    delete_all(LIBRARY_DB_PATH)
    app_state.manager = None

    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key="session", httponly=True, samesite="strict")
    return response
