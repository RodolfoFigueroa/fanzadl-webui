import asyncio
import re
from collections.abc import AsyncGenerator
from typing import Annotated

from fanzadl.constants import USER_AGENT
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from fanzadl_webui.dependencies import DOWNLOAD_DIR
from fanzadl_webui.jobs import (
    DownloadJob,
    JobStatus,
    Queues,
    get_jobs,
    get_queues,
)

router = APIRouter()
_background_tasks: set[asyncio.Task] = set()
_processes: dict[str, asyncio.subprocess.Process] = {}

_PCT_RE = re.compile(r"(\d+)/(\d+)\s+([\d.]+)%")
_SPEED_RE = re.compile(r"[\d.]+\s*[KMGT]?Bps")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")


class DownloadRequest(BaseModel):
    output_name: str
    media_url: str
    thread_count: int = Field(default=4, ge=1, le=32)


def _publish(job: DownloadJob, queues: Queues) -> None:
    snapshot = job.model_copy()
    for q in queues.get(job.job_id, []):
        q.put_nowait(snapshot)


def _close_streams(job_id: str, queues: Queues) -> None:
    for q in queues.get(job_id, []):
        q.put_nowait(None)


async def _run_download(
    job: DownloadJob,
    media_url: str,
    save_dir: str,
    save_name: str,
    thread_count: int,
    queues: Queues,
) -> None:
    job.status = JobStatus.running
    _publish(job, queues)
    output_lines: list[str] = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "N_m3u8DL-RE",
            media_url,
            "--save-dir",
            save_dir,
            "--save-name",
            save_name,
            "--thread-count",
            str(thread_count),
            "-M",
            "format=mp4",
            "--no-log",
            "--header",
            f"User-Agent: {USER_AGENT}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if proc.stdout is None:
            msg = "N_m3u8DL-RE process streams unavailable"
            raise RuntimeError(msg)  # noqa: TRY301

        _processes[job.job_id] = proc
        try:
            async for raw_line in proc.stdout:
                line = _ANSI_RE.sub("", raw_line.decode(errors="replace")).strip()
                if not line:
                    continue
                output_lines.append(line)
                pct_m = _PCT_RE.search(line)
                if pct_m:
                    job.segments_done = int(pct_m.group(1))
                    job.segments_total = int(pct_m.group(2))
                    job.percent_done = float(pct_m.group(3))
                    speed_m = _SPEED_RE.search(line)
                    if speed_m:
                        job.speed = speed_m.group(0)
                    _publish(job, queues)
            await proc.wait()
        finally:
            _processes.pop(job.job_id, None)
    except Exception as exc:  # noqa: BLE001
        job.error = str(exc)
        job.status = JobStatus.error
        _publish(job, queues)
        _close_streams(job.job_id, queues)
        return

    if proc.returncode != 0 and job.status != JobStatus.cancelled:
        job.error = "\n".join(output_lines)
        job.status = JobStatus.error
    elif job.status != JobStatus.cancelled:
        job.output_path = str(DOWNLOAD_DIR / f"{save_name}.mp4")
        job.status = JobStatus.done
    _publish(job, queues)
    _close_streams(job.job_id, queues)


@router.post("/download/")
async def start_download(
    body: DownloadRequest,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
) -> dict[str, str]:
    save_dir = str(DOWNLOAD_DIR)

    job = DownloadJob.create(output_name=body.output_name)
    jobs[job.job_id] = job
    queues[job.job_id] = []
    task = asyncio.create_task(
        _run_download(
            job, body.media_url, save_dir, body.output_name, body.thread_count, queues
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"job_id": job.job_id}


@router.get("/jobs/")
def list_jobs(
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
) -> list[DownloadJob]:
    return list(jobs.values())


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
) -> DownloadJob:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    return job


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: str,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
) -> None:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    if job.status in (JobStatus.done, JobStatus.error, JobStatus.cancelled):
        return
    job.status = JobStatus.cancelled
    proc = _processes.get(job_id)
    if proc is not None:
        proc.terminate()
    _publish(job, queues)
    _close_streams(job_id, queues)


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
) -> EventSourceResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        q: asyncio.Queue[DownloadJob | None] = asyncio.Queue()
        queues.setdefault(job_id, []).append(q)
        try:
            # Check after appending to avoid a race between job completion
            # and queue registration.
            if job.status in (JobStatus.done, JobStatus.error):
                yield {"data": job.model_dump_json()}
                return
            while True:
                snapshot = await q.get()
                if snapshot is None:
                    break
                yield {"data": snapshot.model_dump_json()}
        finally:
            job_queues = queues.get(job_id, [])
            if q in job_queues:
                job_queues.remove(q)
            if not job_queues:
                queues.pop(job_id, None)

    return EventSourceResponse(event_generator())
