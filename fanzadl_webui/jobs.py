import asyncio

import httpx
from fastapi import Request

from fanzadl_webui.models import (
    DownloadJob,
    JobStatus,
    Queues,
)

__all__ = [
    "DownloadJob",
    "JobStatus",
    "Queues",
    "get_download_slot_condition",
    "get_http_client",
    "get_jobs",
    "get_queues",
]


def get_jobs(request: Request) -> dict[str, DownloadJob]:
    from fanzadl_webui.dependencies import get_app_state

    return get_app_state(request).jobs


def get_queues(request: Request) -> Queues:
    from fanzadl_webui.dependencies import get_app_state

    return get_app_state(request).queues


def get_http_client(request: Request) -> httpx.AsyncClient:
    from fanzadl_webui.dependencies import get_app_state

    return get_app_state(request).http_client


def get_download_slot_condition(request: Request) -> asyncio.Condition:
    from fanzadl_webui.dependencies import get_app_state

    return get_app_state(request).download_slot_condition
