import asyncio
import contextlib
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import m3u8
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
_SIZE_RE = re.compile(r"([\d.]+[KMGT]?B)/([\d.]+[KMGT]?B)")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")


@dataclass
class _ConcurrencyContext:
    jobs: dict[str, DownloadJob]
    condition: asyncio.Condition
    app_state: State


class DownloadRequest(BaseModel):
    output_name: str
    video_id: int
    part: int
    stream_index: int
    thread_count: int = Field(default=4, ge=1, le=32)


def _publish(job: DownloadJob, queues: Queues) -> None:
    """Enqueue a snapshot of job to all SSE subscriber queues for that job.

    Args:
        job: The job whose current state will be copied and broadcast.
        queues: Mapping of job IDs to lists of subscriber queues.
    """
    snapshot = job.model_copy()
    for q in queues.get(job.job_id, []):
        q.put_nowait(snapshot)


def _close_streams(job_id: str, queues: Queues) -> None:
    """Send a None sentinel to every subscriber queue for job_id.

    Signals stream completion to each connected SSE client.

    Args:
        job_id: Identifier of the job whose streams should be closed.
        queues: Mapping of job IDs to lists of subscriber queues.
    """
    for q in queues.get(job_id, []):
        q.put_nowait(None)


async def cancel_active_jobs(
    jobs: dict[str, DownloadJob],
    queues: Queues,
    condition: asyncio.Condition,
) -> None:
    """Cancel all running or pending jobs and notify the concurrency condition.

    For each running or pending job: marks it cancelled, terminates its subprocess
    if one exists, publishes the updated state to subscribers, and closes its SSE
    streams. Then notifies all waiters on the condition variable.

    Args:
        jobs: Mapping of job IDs to active download jobs.
        queues: SSE subscriber queues, keyed by job ID.
        condition: Concurrency condition to notify after cancellation.
    """
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
    """Wait for a concurrency slot and transition the job to running.

    Blocks until the number of currently running jobs falls below the configured
    maximum, or until the job is externally cancelled. The job status is set to
    ``running`` before returning ``True``.

    Args:
        job: The pending job waiting to acquire a download slot.
        ctx: Concurrency context providing the condition variable, job registry,
            and app state with the ``max_concurrent_downloads`` setting.

    Returns:
        True if a slot was acquired and the job is now running.
        False if the job was cancelled while waiting.
    """
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


async def _resolve_media_url(
    video_id: int,
    part: int,
    stream_index: int,
    app_state: State,
) -> str:
    """Resolve the direct media URL for a video part and stream index.

    Args:
        video_id: Library video identifier.
        part: Part index passed to the quality object's URL resolver.
        stream_index: Index into the m3u8 playlist variants.
        app_state: Application state providing the library and HTTP client.

    Returns:
        The absolute URI of the selected media stream.

    Raises:
        ValueError: If the video or a downloadable quality is not found.
        Exception: On HTTP or m3u8 parsing errors.
    """
    item = app_state.manager.library.get(video_id)
    if item is None:
        msg = f"Video {video_id} not found in library"
        raise ValueError(msg)
    quality_obj = item.highest
    if quality_obj is None:
        msg = f"No downloadable quality found for video {video_id}"
        raise ValueError(msg)
    playlist_url = quality_obj.get_url(part)
    response = await app_state.http_client.get(playlist_url, follow_redirects=True)
    response.raise_for_status()
    parsed = m3u8.loads(response.text, uri=playlist_url)
    return parsed.playlists[stream_index].absolute_uri


async def _launch_process(
    media_url: str,
    save_dir: str,
    save_name: str,
    thread_count: int,
) -> asyncio.subprocess.Process:
    """Spawn the N_m3u8DL-RE subprocess for the given media URL.

    Args:
        media_url: Direct stream URL to pass to N_m3u8DL-RE.
        save_dir: Directory where the output file will be written.
        save_name: Output filename stem (without extension).
        thread_count: Number of download threads for N_m3u8DL-RE.

    Returns:
        The running subprocess with stdout piped.

    Raises:
        RuntimeError: If the subprocess stdout stream is unavailable.
    """
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
    return proc


def _parse_progress_line(line: str, job: DownloadJob) -> bool:
    """Parse a single output line and update job progress fields in place.

    Args:
        line: A single ANSI-stripped line from the downloader's stdout.
        job: The job whose fields will be mutated if progress data is found.

    Returns:
        True if a progress match was found, False otherwise.
    """
    pct_m = _PCT_RE.search(line)
    if not pct_m:
        return False
    job.segments_done = int(pct_m.group(1))
    job.segments_total = int(pct_m.group(2))
    job.percent_done = float(pct_m.group(3))
    speed_m = _SPEED_RE.search(line)
    if speed_m:
        job.speed = speed_m.group(0)
    size_m = _SIZE_RE.search(line)
    if size_m:
        job.bytes_downloaded = size_m.group(1)
        job.bytes_total = size_m.group(2)
    return True


async def _stream_output(
    proc: asyncio.subprocess.Process,
    job: DownloadJob,
    queues: Queues,
) -> list[str]:
    """Read stdout from the downloader process and publish progress updates.

    Args:
        proc: Running subprocess whose stdout will be consumed.
        job: Job to update with progress and to publish to subscribers.
        queues: SSE subscriber queues for the job.

    Returns:
        All non-empty output lines produced by the process.

    Raises:
        RuntimeError: If ``proc.stdout`` is ``None`` (should not occur when
            called after ``_launch_process``).
    """
    if proc.stdout is None:  # guaranteed non-None by _launch_process
        msg = "N_m3u8DL-RE process streams unavailable"
        raise RuntimeError(msg)
    output_lines: list[str] = []
    _processes[job.job_id] = proc
    try:
        async for raw_line in proc.stdout:
            line = _ANSI_RE.sub("", raw_line.decode(errors="replace")).strip()
            if not line:
                continue
            output_lines.append(line)
            if _parse_progress_line(line, job):
                _publish(job, queues)
        await proc.wait()
    finally:
        _processes.pop(job.job_id, None)
    return output_lines


def _finalize_job(  # noqa: PLR0913
    job: DownloadJob,
    returncode: int | None,
    output_lines: list[str],
    save_dir: str,
    save_name: str,
    queues: Queues,
) -> None:
    """Set the terminal job status after the process exits and notify subscribers.

    Args:
        job: Job to finalize.
        returncode: Process exit code from the completed subprocess.
        output_lines: All stdout lines collected during the download.
        save_dir: Directory where the output file was written.
        save_name: Output filename stem (without extension).
        queues: SSE subscriber queues for the job.
    """
    if returncode != 0 and job.status != JobStatus.cancelled:
        job.error = "\n".join(output_lines)
        job.status = JobStatus.error
    elif job.status != JobStatus.cancelled:
        output_file = Path(save_dir) / f"{save_name}.mp4"
        job.output_path = str(output_file)
        with contextlib.suppress(OSError):
            job.file_size = output_file.stat().st_size
        job.status = JobStatus.done
    _publish(job, queues)
    _close_streams(job.job_id, queues)


async def _run_download(  # noqa: PLR0913
    job: DownloadJob,
    video_id: int,
    part: int,
    stream_index: int,
    save_dir: str,
    save_name: str,
    thread_count: int,
    queues: Queues,
    concurrency: _ConcurrencyContext,
) -> None:
    """Orchestrate a full download: acquire slot, resolve URL, run process, finalize.

    Acquires a concurrency slot, resolves the direct media stream URL, publishes
    the running state, spawns and streams the N_m3u8DL-RE process, then finalizes
    the job with its terminal status. Always notifies the concurrency condition on
    exit to unblock other pending jobs.

    Args:
        job: The download job to execute.
        video_id: Library video identifier to look up.
        part: Part index to resolve from the video's quality object.
        stream_index: Index into the m3u8 playlist variants.
        save_dir: Directory path where the output file will be written.
        save_name: Output filename stem (without extension).
        thread_count: Number of download threads for N_m3u8DL-RE.
        queues: SSE subscriber queues, keyed by job ID.
        concurrency: Context providing the condition variable, job registry,
            and app state.
    """
    if not await _acquire_slot(job, concurrency):
        return

    try:
        media_url = await _resolve_media_url(
            video_id, part, stream_index, concurrency.app_state
        )
    except Exception as exc:  # noqa: BLE001
        job.error = f"Failed to resolve media URL: {exc}"
        job.status = JobStatus.error
        _publish(job, queues)
        _close_streams(job.job_id, queues)
        return

    _publish(job, queues)
    try:
        try:
            proc = await _launch_process(media_url, save_dir, save_name, thread_count)
            output_lines = await _stream_output(proc, job, queues)
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            job.status = JobStatus.error
            _publish(job, queues)
            _close_streams(job.job_id, queues)
            return
        _finalize_job(job, proc.returncode, output_lines, save_dir, save_name, queues)
    finally:
        async with concurrency.condition:
            concurrency.condition.notify_all()


class FilenameCheckResponse(BaseModel):
    file_exists: bool


@router.get("/download/check-filename")
def check_filename(name: str = Query(..., min_length=1)) -> FilenameCheckResponse:
    """Check whether an output file with the given name already exists.

    Args:
        name: Filename stem (without extension) to check inside the download
            directory. Must be at least one character.

    Returns:
        A FilenameCheckResponse indicating whether ``{name}.mp4`` exists.
    """
    return FilenameCheckResponse(file_exists=(DOWNLOAD_DIR / f"{name}.mp4").exists())


@router.post("/download/")
async def start_download(
    request: Request,
    body: DownloadRequest,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
    condition: Annotated[asyncio.Condition, Depends(get_download_slot_condition)],
) -> dict[str, str]:
    """Create a download job and dispatch it as a background task.

    Validates that the resolved output path stays within the download directory
    (path-traversal guard), creates any required subdirectories, registers a new
    DownloadJob, and fires off ``_run_download`` as an asyncio background task.

    Args:
        request: Incoming FastAPI request providing app state.
        body: Download parameters including video ID, part, stream index, output
            name, and thread count.
        jobs: Injected mapping of active download jobs keyed by job ID.
        queues: Injected SSE subscriber queues keyed by job ID.
        condition: Injected concurrency condition for download slot management.

    Returns:
        A dict containing the ``job_id`` of the newly created job.

    Raises:
        HTTPException: 400 if the resolved output path escapes the download
            directory.
    """
    output_name_path = Path(body.output_name)
    resolved = (DOWNLOAD_DIR / body.output_name).resolve()
    if not resolved.is_relative_to(DOWNLOAD_DIR.resolve()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid output path"
        )
    save_dir_path = DOWNLOAD_DIR / output_name_path.parent
    save_dir_path.mkdir(parents=True, exist_ok=True)
    save_dir = str(save_dir_path)
    save_name = output_name_path.name

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
            body.video_id,
            body.part,
            body.stream_index,
            save_dir,
            save_name,
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
    """Return all current download jobs.

    Args:
        jobs: Injected mapping of active download jobs keyed by job ID.

    Returns:
        A list of all DownloadJob entries.
    """
    return list(jobs.values())


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
) -> DownloadJob:
    """Return a single download job by ID.

    Args:
        job_id: UUID string identifying the requested job.
        jobs: Injected mapping of active download jobs keyed by job ID.

    Returns:
        The DownloadJob matching job_id.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
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
    """Bulk-cancel or delete jobs matching job_filter.

    The ``job_filter`` query parameter controls which jobs are targeted:

    - ``active``: cancel all running and pending jobs.
    - ``done``: remove only successfully completed jobs.
    - ``errored``: remove only error and cancelled jobs.
    - ``finished``: remove all terminal jobs (done, error, and cancelled).

    Args:
        job_filter: Selection criterion for which jobs to act on.
        jobs: Injected mapping of active download jobs keyed by job ID.
        queues: Injected SSE subscriber queues keyed by job ID.
        condition: Injected concurrency condition used when cancelling active
            jobs.
    """
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
    """Cancel an active job or delete a finished one by ID.

    If the job is in a terminal state (done, error, or cancelled) it is removed
    immediately. If it is running or pending, it is marked cancelled, its
    subprocess is terminated, subscribers are notified, SSE streams are closed,
    and the concurrency condition is signalled.

    Args:
        job_id: UUID string identifying the job to act on.
        jobs: Injected mapping of active download jobs keyed by job ID.
        queues: Injected SSE subscriber queues keyed by job ID.
        condition: Injected concurrency condition to notify after cancellation.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
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
    """Stream SSE events for a job until it finishes or the client disconnects.

    Returns an EventSourceResponse backed by an async generator. If the job is
    already in a terminal state (done or error) the current snapshot is yielded
    immediately. Otherwise, job snapshots are streamed as they are published until
    a None sentinel signals completion.

    Args:
        job_id: UUID string identifying the job to observe.
        jobs: Injected mapping of active download jobs keyed by job ID.
        queues: Injected SSE subscriber queues keyed by job ID.

    Returns:
        An EventSourceResponse that streams serialized DownloadJob snapshots.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        """Yield serialized job snapshots until a None sentinel is received."""
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
