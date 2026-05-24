import asyncio
import uuid
from enum import StrEnum

import httpx
from fastapi import Request
from pydantic import BaseModel


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    error = "error"
    cancelled = "cancelled"


class DownloadJob(BaseModel):
    job_id: str
    status: JobStatus
    output_name: str
    bytes_downloaded: int | None = None
    out_time: str | None = None
    speed: str | None = None
    percent_done: float | None = None
    segments_done: int | None = None
    segments_total: int | None = None
    output_path: str | None = None
    error: str | None = None

    @classmethod
    def create(cls, output_name: str) -> "DownloadJob":
        return cls(
            job_id=str(uuid.uuid4()),
            status=JobStatus.pending,
            output_name=output_name,
        )


def get_jobs(request: Request) -> dict[str, DownloadJob]:
    return request.app.state.jobs


type Queues = dict[str, list[asyncio.Queue[DownloadJob | None]]]


def get_queues(request: Request) -> Queues:
    return request.app.state.queues


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client
