from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    import httpx
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from fanzadl_webui.manager import PersistingFanzaDLManager
    from fanzadl_webui.models import DownloadJob, Queues, StreamVariant
    from fanzadl_webui.store.config import LogLevel


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
    auto_download_new_items: bool
    auto_download_missing_parts: bool
    webhook_url: str | None
    webhook_secret: str | None
    webhook_events: list[str]
    history_db_path: Path
    config_path: Path
    save_fn: Callable[[str, str], None]
    save_api_key_fn: Callable[[str], None]
    save_local_api_key_fn: Callable[[str], None]
    javstash_api_key: str | None
    javstash_enabled: bool
    local_api_key: str
    local_api_key_persisted: bool
    auth_disabled: bool
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
    notification_queues: list[asyncio.Queue[str | None]] = field(default_factory=list)
    global_job_queues: list[asyncio.Queue[dict[str, int] | None]] = field(
        default_factory=list
    )
    job_created_queues: list[asyncio.Queue[DownloadJob | None]] = field(
        default_factory=list
    )
    library_event_queues: list[asyncio.Queue[tuple[int, str] | None]] = field(
        default_factory=list
    )
    library_event_buffer: deque[tuple[int, str]] = field(
        default_factory=lambda: deque(maxlen=50)
    )
    library_event_counter: int = 0
    sessions: dict[str, datetime] = field(default_factory=dict)
