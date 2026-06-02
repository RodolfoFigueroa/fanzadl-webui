import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fanzadl import FanzaDLManager
from fanzadl_webui.state import AppState
from fastapi import Cookie, Header, HTTPException, Request, status

DOWNLOAD_DIR = Path("/download")
IMAGE_CACHE_DIR = Path("/data/image_cache")
TOKEN_STORE_PATH = Path("/data/tokens.enc")
LIBRARY_DB_PATH = Path("/data/library.db")
HISTORY_DB_PATH = Path("/data/history.db")
JAVSTASH_KEY_PATH = Path("/data/javstash_api_key.enc")
LOCAL_API_KEY_PATH = Path("/data/local_api_key.enc")
CONFIG_PATH = Path("/data/config.json")


def get_app_state(request: Request) -> AppState:
    return request.app.state.app_state


def get_manager(request: Request) -> FanzaDLManager:
    app_state = get_app_state(request)
    if app_state.manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="fanza_not_connected",
        )
    return app_state.manager


def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    session: Annotated[str | None, Cookie()] = None,
) -> None:
    app_state = get_app_state(request)
    key = app_state.local_api_key
    if x_api_key is not None and secrets.compare_digest(x_api_key, key):
        return
    if session is not None:
        expiry = app_state.sessions.get(session)
        if expiry is not None and datetime.now(UTC) < expiry:
            # Sliding expiry: reset the TTL if less than 12 hours remain.
            if expiry - datetime.now(UTC) < timedelta(hours=12):
                app_state.sessions[session] = datetime.now(UTC) + timedelta(hours=24)
            return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )
