import asyncio
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated, Literal

from fanzadl.constants import USER_AGENT
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from starlette.datastructures import State

from fanzadl_webui.dependencies import DOWNLOAD_DIR
from fanzadl_webui.jobs import (
    DownloadJob,
    JobStatus,
    Queues,
    get_download_slot_condition,
    get_jobs,
    get_queues,
)

router = APIRouter()
_background_tasks: set[asyncio.Task] = set()
_processes: dict[str, asyncio.subprocess.Process] = {}

_PCT_RE = re.compile(r"(\d+)/(\d+)\s+([\d.]+)%")
_SPEED_RE = re.compile(r"[\d.]+\s*[KMGT]?Bps")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")


@dataclass
class _ConcurrencyContext:
    jobs: dict[str, DownloadJob]
    condition: asyncio.Condition
    app_state: State


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


async def cancel_active_jobs(
    jobs: dict[str, DownloadJob],
    queues: Queues,
    condition: asyncio.Condition,
) -> None:
    for job in list(jobs.values()):
        if job.status in (JobStatus.running, JobStatus.pending):
            job.status = JobStatus.cancelled
            proc = _processes.get(job.job_id)
            if proc is not None:
                proc.terminate()
            _publish(job, queues)
            _close_streams(job.job_id, queues)
    async with condition:
        condition.notify_all()


async def _acquire_slot(job: DownloadJob, ctx: _ConcurrencyContext) -> bool:
    """Wait for a concurrency slot. Returns False if cancelled while waiting."""
    async with ctx.condition:
        while (
            sum(1 for j in ctx.jobs.values() if j.status == JobStatus.running)
            >= ctx.app_state.max_concurrent_downloads
            and job.status != JobStatus.cancelled
        ):
            await ctx.condition.wait()
        if job.status == JobStatus.cancelled:
            return False
        job.status = JobStatus.running
        return True


async def _run_download(  # noqa: PLR0913
    job: DownloadJob,
    media_url: str,
    save_dir: str,
    save_name: str,
    thread_count: int,
    queues: Queues,
    concurrency: _ConcurrencyContext,
) -> None:
    if not await _acquire_slot(job, concurrency):
        return
    _publish(job, queues)
    output_lines: list[str] = []
    try:
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
                raise RuntimeError(msg)

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
    finally:
        async with concurrency.condition:
            concurrency.condition.notify_all()


@router.post("/download/")
async def start_download(
    request: Request,
    body: DownloadRequest,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
    condition: Annotated[asyncio.Condition, Depends(get_download_slot_condition)],
) -> dict[str, str]:
    save_dir = str(DOWNLOAD_DIR)

    job = DownloadJob.create(output_name=body.output_name)
    jobs[job.job_id] = job
    queues[job.job_id] = []
    concurrency = _ConcurrencyContext(
        jobs=jobs,
        condition=condition,
        app_state=request.app.state,
    )
    task = asyncio.create_task(
        _run_download(
            job,
            body.media_url,
            save_dir,
            body.output_name,
            body.thread_count,
            queues,
            concurrency,
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


@router.delete("/jobs/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_jobs(
    job_filter: Annotated[
        Literal["finished", "done", "errored", "active"],
        Query(
            description=(
                "Which jobs to act on: finished=all finished, done=successful only, "
                "errored=error+cancelled, active=cancel all running/pending"
            )
        ),
    ],
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
    condition: Annotated[asyncio.Condition, Depends(get_download_slot_condition)],
) -> None:
    if job_filter == "active":
        await cancel_active_jobs(jobs, queues, condition)
        return

    if job_filter == "done":
        target_statuses = {JobStatus.done}
    elif job_filter == "errored":
        target_statuses = {JobStatus.error, JobStatus.cancelled}
    else:  # finished
        target_statuses = {JobStatus.done, JobStatus.error, JobStatus.cancelled}

    to_delete = [jid for jid, j in jobs.items() if j.status in target_statuses]
    for jid in to_delete:
        del jobs[jid]
        queues.pop(jid, None)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_or_delete_job(
    job_id: str,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
    condition: Annotated[asyncio.Condition, Depends(get_download_slot_condition)],
) -> None:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    if job.status in (JobStatus.done, JobStatus.error, JobStatus.cancelled):
        del jobs[job_id]
        queues.pop(job_id, None)
        return
    job.status = JobStatus.cancelled
    proc = _processes.get(job_id)
    if proc is not None:
        proc.terminate()
    _publish(job, queues)
    _close_streams(job_id, queues)
    async with condition:
        condition.notify_all()


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
