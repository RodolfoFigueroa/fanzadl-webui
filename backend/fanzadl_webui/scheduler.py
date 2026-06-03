from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from fastapi import FastAPI

from fanzadl_webui.routes.library.refresh import run_post_update

logger = logging.getLogger(__name__)

_JOB_ID = "library_refresh"


async def do_library_refresh(app: FastAPI) -> None:
    """Run a full library refresh cycle.

    Args:
        app: The FastAPI application instance whose state holds the manager
            and other shared resources.
    """
    state = app.state.app_state
    manager = state.manager
    if manager is None:
        logger.warning("Scheduled library refresh skipped: no active session")
        return

    logger.info("Scheduled library refresh starting")
    try:
        await asyncio.to_thread(manager.update_library)
    except Exception:
        logger.exception("Scheduled library refresh: update_library failed")
        return

    await run_post_update(manager, state, enqueue=True)
    logger.info("Scheduled library refresh complete")


def schedule_library_refresh(app: FastAPI, cron_expr: str) -> None:
    """Register (or replace) the periodic library-refresh job.

    Args:
        app: The FastAPI application instance.
        cron_expr: A standard 5-field cron expression (e.g. ``"0 12 * * 1"``).
    """
    scheduler: AsyncIOScheduler = app.state.app_state.scheduler
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
    scheduler: AsyncIOScheduler = app.state.app_state.scheduler
    if scheduler.get_job(_JOB_ID) is not None:
        scheduler.remove_job(_JOB_ID)
        logger.info("Library refresh schedule removed")
