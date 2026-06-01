import asyncio
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fanzadl_webui.dependencies import (
    get_app_state,
    require_api_key,
)
from fanzadl_webui.state import AppState
from fanzadl_webui.store.config import load_config

logger = logging.getLogger(__name__)

_SESSION_TTL_HOURS = 24
_RATE_LIMIT_WINDOW = 60.0
_RATE_LIMIT_MAX = 10
_login_attempts: dict[str, list[float]] = {}
_login_rate_lock = asyncio.Lock()

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
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

    config = await asyncio.to_thread(load_config, app_state.config_path)
    password_hash = config.app_password_hash
    if password_hash is None or not bcrypt.checkpw(
        body.password.encode(), password_hash.encode()
    ):
        async with _login_rate_lock:
            _login_attempts.setdefault(ip, []).append(time.monotonic())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password.",
        )

    async with _login_rate_lock:
        _login_attempts.pop(ip, None)

    session_token = secrets.token_urlsafe(32)
    app_state.sessions[session_token] = datetime.now(UTC) + timedelta(
        hours=_SESSION_TTL_HOURS
    )

    response = JSONResponse(content={"status": "ok"})
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=_SESSION_TTL_HOURS * 3600,
    )
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

    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key="session", httponly=True, samesite="strict")
    return response
