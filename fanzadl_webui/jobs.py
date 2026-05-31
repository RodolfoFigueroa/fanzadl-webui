import asyncio

import httpx
from fastapi import Request

from fanzadl_webui.dependencies import get_app_state
from fanzadl_webui.models import (
    DownloadJob,
    JobStatus,
    Queues,
)


def get_jobs(request: Request) -> dict[str, DownloadJob]:
    return get_app_state(request).jobs


def get_queues(request: Request) -> Queues:
    return get_app_state(request).queues


def get_http_client(request: Request) -> httpx.AsyncClient:
    return get_app_state(request).http_client


def get_download_slot_condition(request: Request) -> asyncio.Condition:
    return get_app_state(request).download_slot_condition


def get_global_job_queues(
    request: Request,
) -> "list[asyncio.Queue[dict[str, int] | None]]":
    return get_app_state(request).global_job_queues


def get_job_created_queues(
    request: Request,
) -> "list[asyncio.Queue[DownloadJob | None]]":
    return get_app_state(request).job_created_queues


__all__ = [
    "DownloadJob",
    "JobStatus",
    "Queues",
    "get_download_slot_condition",
    "get_global_job_queues",
    "get_http_client",
    "get_job_created_queues",
    "get_jobs",
    "get_queues",
]
