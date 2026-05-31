from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fanzadl_webui.config_store import LogLevel
from fanzadl_webui.manager import PersistingFanzaDLManager
from fanzadl_webui.models import DownloadJob, Queues, StreamVariant


@dataclass(kw_only=True)
class AppState:
    http_client: httpx.AsyncClient
    manager: PersistingFanzaDLManager | None
    max_concurrent_downloads: int
    log_level: LogLevel
    download_thread_count: int
    single_part_filename_template: str
    multi_part_filename_template: str
    library_refresh_enabled: bool
    library_refresh_cron: str
    config_path: Path
    save_fn: Callable[[str, str], None]
    save_api_key_fn: Callable[[str], None]
    javstash_api_key: str | None
    javstash_enabled: bool
    scheduler: AsyncIOScheduler
    jobs: dict[str, DownloadJob] = field(default_factory=dict)
    queues: Queues = field(default_factory=dict)
    download_slot_condition: asyncio.Condition = field(
        default_factory=asyncio.Condition
    )
    background_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    login_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stream_cache: dict[tuple[int, int | None], list[StreamVariant]] = field(
        default_factory=dict
    )
    download_counts: dict[str, int] = field(default_factory=dict)
