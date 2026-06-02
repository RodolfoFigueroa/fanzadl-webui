import asyncio
import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    error = "error"
    cancelled = "cancelled"


class StatusResponse(BaseModel):
    """Generic status acknowledgement returned by action endpoints."""

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok"}})

    status: str = Field(description="Outcome of the operation, typically 'ok'.")


class DownloadJob(BaseModel):
    """A single file-download task tracked by the job queue."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "status": "running",
                "output_name": "MyVideo/MyVideo_part1",
                "content_id": "mide00001",
                "speed": "12.4 MB/s",
                "percent_done": 42.5,
                "segments_done": 340,
                "segments_total": 800,
                "bytes_downloaded": "450 MB",
                "bytes_total": "1.1 GB",
                "bytes_downloaded_raw": 471859200,
                "bytes_total_raw": 1181116006,
                "file_size": None,
                "output_path": None,
                "error": None,
                "source": "manual",
                "bandwidth_mbps": 12.4,
            }
        }
    )

    job_id: str = Field(description="UUID identifying this download job.")
    status: JobStatus = Field(description="Current lifecycle state of the job.")
    output_name: str = Field(
        description="Relative output path (without extension) inside the download directory."
    )
    content_id: str | None = Field(
        default=None, description="Fanza content ID associated with this job, if known."
    )
    speed: str | None = Field(
        default=None,
        description="Human-readable current download speed (e.g. '12.4 MB/s').",
    )
    percent_done: float | None = Field(
        default=None, description="Download progress as a percentage (0–100)."
    )
    segments_done: int | None = Field(
        default=None, description="Number of HLS segments downloaded so far."
    )
    segments_total: int | None = Field(
        default=None, description="Total number of HLS segments to download."
    )
    bytes_downloaded: str | None = Field(
        default=None, description="Human-readable bytes downloaded (e.g. '450 MB')."
    )
    bytes_total: str | None = Field(
        default=None, description="Human-readable total file size (e.g. '1.1 GB')."
    )
    bytes_downloaded_raw: int | None = Field(
        default=None, description="Bytes downloaded as a raw integer."
    )
    bytes_total_raw: int | None = Field(
        default=None, description="Total expected bytes as a raw integer."
    )
    file_size: int | None = Field(
        default=None,
        description="Final on-disk file size in bytes, set after the job completes.",
    )
    output_path: str | None = Field(
        default=None, description="Absolute path to the completed output file."
    )
    error: str | None = Field(
        default=None, description="Error message if the job ended in an error state."
    )
    source: Literal["manual", "auto"] = Field(
        default="manual",
        description="Whether the job was triggered manually by a user or automatically by auto-enqueue.",
    )
    bandwidth_mbps: float | None = Field(
        default=None,
        description="Average download bandwidth in Mbit/s recorded on completion.",
    )

    @classmethod
    def create(
        cls,
        output_name: str,
        content_id: str | None = None,
        source: Literal["manual", "auto"] = "manual",
    ) -> "DownloadJob":
        return cls(
            job_id=str(uuid.uuid4()),
            status=JobStatus.pending,
            output_name=output_name,
            content_id=content_id,
            source=source,
        )


type Queues = dict[str, list[asyncio.Queue[DownloadJob | None]]]


class StreamVariant(BaseModel):
    """One quality variant from an HLS master playlist."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "index": 0,
                "bandwidth": 4000000,
                "codecs": "avc1.640028,mp4a.40.2",
                "uri": "https://example.cdn.net/stream/4000k/index.m3u8",
            }
        }
    )

    index: int = Field(
        description="Zero-based position of this variant in the master playlist."
    )
    bandwidth: int = Field(
        description="Peak bandwidth of this variant in bits per second."
    )
    codecs: str | None = Field(
        description="Codec string from the EXT-X-STREAM-INF tag (e.g. 'avc1.640028,mp4a.40.2')."
    )
    uri: str | None = Field(
        default=None, description="Absolute URL of the variant's media playlist."
    )


class LibraryEvent(BaseModel):
    """A domain event emitted when the library changes."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "item_added",
                "content_id": "mide00001",
                "title": "My Video Title",
                "part": 1,
                "mylibrary_id": 123456,
            }
        }
    )

    type: Literal["item_added", "item_expired", "auto_queued"] = Field(
        description="The kind of library change that occurred."
    )
    content_id: str = Field(
        description="Fanza content ID of the affected library item."
    )
    title: str | None = Field(
        default=None, description="Title of the affected library item."
    )
    part: int | None = Field(
        default=None,
        description="Part number relevant to the event (present for 'auto_queued' events).",
    )
    mylibrary_id: int | None = Field(
        default=None, description="Fanza mylibrary numeric ID of the affected item."
    )
