import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class AppConfig(BaseModel):
    max_concurrent_downloads: int = Field(default=3, ge=1)
    log_level: LogLevel = "INFO"
    download_thread_count: int = Field(default=4, ge=1, le=32)


def save_config(path: Path, config: AppConfig) -> None:
    """Persist app configuration to disk atomically.

    Args:
        path: Destination path for the config file.
        config: The configuration to serialize.
    """
    data = config.model_dump_json().encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


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
    except Exception:
        logger.warning(
            "Config file at %s is corrupt or unreadable; using defaults", path
        )
        return AppConfig()
