from pathlib import Path
from typing import TYPE_CHECKING

from fanzadl import FanzaDLManager
from fastapi import HTTPException, Request, status

if TYPE_CHECKING:
    from fanzadl_webui.state import AppState

DOWNLOAD_DIR = Path("/download")
IMAGE_CACHE_DIR = Path("/data/image_cache")
TOKEN_STORE_PATH = Path("/data/tokens.enc")
LIBRARY_DB_PATH = Path("/data/library.db")
JAVSTASH_KEY_PATH = Path("/data/javstash_api_key.enc")
CONFIG_PATH = Path("/data/config.json")


def get_app_state(request: Request) -> "AppState":
    return request.app.state.app_state  # type: ignore[no-any-return]


def get_manager(request: Request) -> FanzaDLManager:
    app_state = get_app_state(request)
    if app_state.manager is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return app_state.manager
