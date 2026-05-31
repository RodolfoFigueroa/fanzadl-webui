from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from fastapi import FastAPI

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, LIBRARY_DB_PATH
from fanzadl_webui.filename import rescan_and_store
from fanzadl_webui.library_db import save_library_db
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes.images import precache_all, purge_stale

logger = logging.getLogger(__name__)

_JOB_ID = "library_refresh"


async def do_library_refresh(app: FastAPI) -> None:
    """Run a full library refresh cycle.

    Args:
        app: The FastAPI application instance whose state holds the manager
            and other shared resources.
    """
    manager = app.state.manager
    if manager is None:
        logger.warning("Scheduled library refresh skipped: no active session")
        return

    logger.info("Scheduled library refresh starting")
    try:
        await asyncio.to_thread(manager.update_library)
    except Exception:
        logger.exception("Scheduled library refresh: update_library failed")
        return

    app.state.stream_cache = {}
    await asyncio.to_thread(purge_stale, manager, IMAGE_CACHE_DIR)
    await rescan_and_store(app.state)

    async def _warm_and_save() -> None:
        new_ids: set[int] | None = None
        if isinstance(manager, PersistingFanzaDLManager):
            new_ids = set(manager.library) - manager._ids_restored_from_cache  # noqa: SLF001
        await warm_all_details(manager, item_ids=new_ids)
        if isinstance(manager, PersistingFanzaDLManager):
            await asyncio.to_thread(
                save_library_db,
                LIBRARY_DB_PATH,
                manager.user_id,
                manager,
                new_ids or set(),
            )
            manager._ids_restored_from_cache = set()  # noqa: SLF001

    await asyncio.gather(
        precache_all(manager, app.state.http_client, IMAGE_CACHE_DIR),
        _warm_and_save(),
    )
    logger.info("Scheduled library refresh complete")


def schedule_library_refresh(app: FastAPI, cron_expr: str) -> None:
    """Register (or replace) the periodic library-refresh job.

    Args:
        app: The FastAPI application instance.
        cron_expr: A standard 5-field cron expression (e.g. ``"0 12 * * 1"``).
    """
    scheduler: AsyncIOScheduler = app.state.scheduler
    if scheduler.get_job(_JOB_ID) is not None:
        scheduler.remove_job(_JOB_ID)
    trigger = CronTrigger.from_crontab(cron_expr)
    scheduler.add_job(
        do_library_refresh,
        trigger=trigger,
        id=_JOB_ID,
        args=[app],
        misfire_grace_time=3600,
    )
    logger.info("Library refresh scheduled with cron: %s", cron_expr)


def unschedule_library_refresh(app: FastAPI) -> None:
    """Remove the periodic library-refresh job if it exists.

    Args:
        app: The FastAPI application instance.
    """
    scheduler: AsyncIOScheduler = app.state.scheduler
    if scheduler.get_job(_JOB_ID) is not None:
        scheduler.remove_job(_JOB_ID)
        logger.info("Library refresh schedule removed")
