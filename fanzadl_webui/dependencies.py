from pathlib import Path

from fanzadl import FanzaDLManager
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic_settings import BaseSettings, SettingsConfigDict

DOWNLOAD_DIR = Path("/download")
IMAGE_CACHE_DIR = Path("/image_cache")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    fanza_email: str
    fanza_password: str
    fanzadl_webui_api_key: str


settings = Settings()  # ty:ignore[missing-argument]

api_key_header = APIKeyHeader(name="X-API-Key")


def verify_api_key(key: str = Security(api_key_header)) -> None:
    if key != settings.fanzadl_webui_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )


def get_manager(request: Request) -> FanzaDLManager:
    return request.app.state.manager
