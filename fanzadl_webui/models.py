import asyncio
import uuid
from enum import StrEnum

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
    content_id: str | None = None
    speed: str | None = None
    percent_done: float | None = None
    segments_done: int | None = None
    segments_total: int | None = None
    bytes_downloaded: str | None = None
    bytes_total: str | None = None
    file_size: int | None = None
    output_path: str | None = None
    error: str | None = None

    @classmethod
    def create(cls, output_name: str, content_id: str | None = None) -> "DownloadJob":
        return cls(
            job_id=str(uuid.uuid4()),
            status=JobStatus.pending,
            output_name=output_name,
            content_id=content_id,
        )


type Queues = dict[str, list[asyncio.Queue[DownloadJob | None]]]


class StreamVariant(BaseModel):
    index: int
    bandwidth: int
    codecs: str | None
    uri: str | None = None
