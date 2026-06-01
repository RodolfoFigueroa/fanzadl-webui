import json
import logging
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from fanzadl_webui.store.base import try_write

logger = logging.getLogger(__name__)

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class AppConfig(BaseModel):
    max_concurrent_downloads: int = Field(default=3, ge=1)
    log_level: LogLevel = "INFO"
    download_thread_count: int = Field(default=4, ge=1, le=32)
    single_part_filename_template: str = "{content_id}"
    multi_part_filename_template: str = "{content_id}/{content_id}_{part:02}"
    library_refresh_enabled: bool = False
    library_refresh_cron: str = "0 0 * * *"
    auto_download_new_items: bool = False
    auto_download_missing_parts: bool = False
    webhook_url: str | None = None
    webhook_secret: str | None = None
    webhook_events: list[str] = Field(
        default_factory=lambda: [
            "job_created",
            "job_completed",
            "job_failed",
            "job_cancelled",
            "item_added",
            "item_expired",
        ]
    )
    app_password_hash: str | None = None


def save_config(path: Path, config: AppConfig) -> None:
    """Persist app configuration to disk atomically.

    Args:
        path: Destination path for the config file.
        config: The configuration to serialize.
    """
    data = config.model_dump_json().encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)

    try_write(data, descriptor=fd, temp_path=tmp_path, orig_path=path)


def load_config(path: Path) -> AppConfig:
    """Load app configuration from disk, returning defaults if unavailable.

    Args:
        path: Path to the config file.

    Returns:
        Loaded AppConfig, or an AppConfig with defaults if the file is missing
        or corrupt.
    """
    try:
        data = json.loads(path.read_bytes())
        return AppConfig.model_validate(data)
    except FileNotFoundError:
        return AppConfig()
    except Exception:  # noqa: BLE001
        logger.warning(
            "Config file at %s is corrupt or unreadable; using defaults", path
        )
        return AppConfig()
