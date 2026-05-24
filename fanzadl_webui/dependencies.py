from pathlib import Path

from fanzadl import FanzaDLManager
from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict

DOWNLOAD_DIR = Path("/download")
IMAGE_CACHE_DIR = Path("/image_cache")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    fanza_email: str
    fanza_password: str


settings = Settings()  # ty:ignore[missing-argument]


def get_manager(request: Request) -> FanzaDLManager:
    return request.app.state.manager
