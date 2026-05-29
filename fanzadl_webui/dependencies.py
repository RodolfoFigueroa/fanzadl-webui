from pathlib import Path

from fanzadl import FanzaDLManager
from fastapi import HTTPException, Request, status

DOWNLOAD_DIR = Path("/download")
IMAGE_CACHE_DIR = Path("/image_cache")
TOKEN_STORE_PATH = Path("/data/tokens.enc")
LIBRARY_CACHE_PATH = Path("/data/library_cache.json")


def get_manager(request: Request) -> FanzaDLManager:
    if request.app.state.manager is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return request.app.state.manager
