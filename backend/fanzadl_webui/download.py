import asyncio
import contextlib
import logging
import re
from pathlib import Path
from typing import Any

import m3u8
from fanzadl.constants import USER_AGENT
from fanzadl_webui.filename import rescan_and_store
from fanzadl_webui.history_db import insert_history
from fanzadl_webui.models import DownloadJob, JobStatus, Queues
from fanzadl_webui.routes._utils import _fire_background
from fanzadl_webui.state import AppState
from fanzadl_webui.webhook import fire_webhook

logger = logging.getLogger(__name__)

_processes: dict[str, asyncio.subprocess.Process] = {}

_PCT_RE = re.compile(r"(\d+)/(\d+)\s+([\d.]+)%")
_SPEED_RE = re.compile(r"[\d.]+\s*[KMGT]?Bps")
_SIZE_RE = re.compile(r"([\d.]+[KMGT]?B)/([\d.]+[KMGT]?B)")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
_RAW_SIZE_RE = re.compile(r"^([\d.]+)([KMGT]?)B$")

_SIZE_MULTIPLIERS: dict[str, int] = {
    "": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
}


def _try_put(q: asyncio.Queue[Any], item: Any) -> None:  # noqa: ANN401
    """Put item onto q, evicting the oldest entry if the queue is full."""
    if q.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            q.get_nowait()
    with contextlib.suppress(asyncio.QueueFull):
        q.put_nowait(item)


def _parse_size_str(s: str) -> int | None:
    """Parse a formatted byte string into a raw integer byte count.

    Args:
        s: A size string such as ``"500.0MB"`` or ``"1.2GB"``.

    Returns:
        The size in bytes as an integer, or ``None`` if the string cannot be
        parsed.
    """
    m = _RAW_SIZE_RE.match(s)
    if not m:
        return None
    multiplier = _SIZE_MULTIPLIERS.get(m.group(2))
    if multiplier is None:
        return None
    return int(float(m.group(1)) * multiplier)


def _compute_active_counts(jobs: dict[str, DownloadJob]) -> dict[str, int]:
    """Compute a mapping of content_id to count of pending/running jobs.

    Args:
        jobs: Current job registry.

    Returns:
        Dict mapping each content_id to the number of its active jobs.
    """
    counts: dict[str, int] = {}
    for job in jobs.values():
        if job.content_id and job.status in (JobStatus.pending, JobStatus.running):
            counts[job.content_id] = counts.get(job.content_id, 0) + 1
    return counts


def _publish_global(
    counts: dict[str, int],
    global_job_queues: list[asyncio.Queue[dict[str, int] | None]] | None,
) -> None:
    """Broadcast active-count snapshot to all global SSE subscribers.

    Args:
        counts: Mapping of content_id to active job count.
        global_job_queues: List of subscriber queues to broadcast to.
    """
    if global_job_queues is None:
        return
    for q in global_job_queues:
        _try_put(q, counts)


def _publish_job_created(
    job: DownloadJob,
    job_created_queues: list[asyncio.Queue["DownloadJob | None"]] | None,
) -> None:
    """Broadcast a newly created job snapshot to all created-events subscribers.

    Args:
        job: The newly created job to broadcast.
        job_created_queues: List of subscriber queues to broadcast to.
    """
    if job_created_queues is None:
        return
    snapshot = job.model_copy()
    for q in job_created_queues:
        _try_put(q, snapshot)


def register_job(job: DownloadJob, app_state: AppState) -> None:
    """Register a new job and notify all SSE and webhook subscribers.

    Inserts the job into the job registry and queues, publishes a job-created
    SSE event, updates global active counts, and fires the job_created webhook.

    Args:
        job: The newly created job to register.
        app_state: Application state holding the job registry and subscriber lists.
    """
    app_state.jobs[job.job_id] = job
    app_state.queues[job.job_id] = []
    _publish_job_created(job, app_state.job_created_queues)
    _publish_global(_compute_active_counts(app_state.jobs), app_state.global_job_queues)
    _fire_background(
        app_state.background_tasks,
        fire_webhook(
            app_state,
            "job_created",
            {
                "job_id": job.job_id,
                "output_name": job.output_name,
                "content_id": job.content_id,
                "source": job.source,
            },
        ),
    )


def _publish(job: DownloadJob, queues: Queues) -> None:
    """Enqueue a snapshot of job to all SSE subscriber queues for that job.

    Args:
        job: The job whose current state will be copied and broadcast.
        queues: Mapping of job IDs to lists of subscriber queues.
    """
    snapshot = job.model_copy()
    for q in queues.get(job.job_id, []):
        _try_put(q, snapshot)


def _close_streams(job_id: str, queues: Queues) -> None:
    """Send a None sentinel to every subscriber queue for job_id.

    Signals stream completion to each connected SSE client.

    Args:
        job_id: Identifier of the job whose streams should be closed.
        queues: Mapping of job IDs to lists of subscriber queues.
    """
    for q in queues.get(job_id, []):
        _try_put(q, None)


def _cancel_job(job: DownloadJob, queues: Queues, app_state: AppState | None) -> None:
    """Mark a single job cancelled, terminate its process, and notify subscribers.

    Terminates the subprocess if one is running, publishes the cancelled state to
    SSE subscribers, closes streams, and fires the job_cancelled webhook.
    The caller is responsible for notifying the concurrency condition afterwards.

    Args:
        job: The job to cancel.
        queues: SSE subscriber queues, keyed by job ID.
        app_state: Application state for firing the webhook. If None, the webhook
            is skipped.
    """
    job.status = JobStatus.cancelled
    proc = _processes.get(job.job_id)
    if proc is not None:
        proc.terminate()
    _publish(job, queues)
    _close_streams(job.job_id, queues)
    if app_state is not None:
        _fire_background(
            app_state.background_tasks,
            fire_webhook(
                app_state,
                "job_cancelled",
                {
                    "job_id": job.job_id,
                    "output_name": job.output_name,
                    "content_id": job.content_id,
                },
            ),
        )


async def cancel_active_jobs(app_state: AppState) -> None:
    """Cancel all running or pending jobs and notify the concurrency condition.

    For each running or pending job: marks it cancelled, terminates its subprocess
    if one exists, publishes the updated state to subscribers, and closes its SSE
    streams. Then notifies all waiters on the condition variable.

    Args:
        app_state: Application state providing jobs, queues, and the condition.
    """
    for job in list(app_state.jobs.values()):
        if job.status in (JobStatus.running, JobStatus.pending):
            _cancel_job(job, app_state.queues, app_state)
    async with app_state.download_slot_condition:
        app_state.download_slot_condition.notify_all()


async def _acquire_slot(job: DownloadJob, app_state: AppState) -> bool:
    """Wait for a concurrency slot and transition the job to running.

    Blocks until the number of currently running jobs falls below the configured
    maximum, or until the job is externally cancelled. The job status is set to
    ``running`` before returning ``True``.

    Args:
        job: The pending job waiting to acquire a download slot.
        app_state: Application state providing the condition variable, job
            registry, and ``max_concurrent_downloads`` setting.

    Returns:
        True if a slot was acquired and the job is now running.
        False if the job was cancelled while waiting.
    """
    async with app_state.download_slot_condition:
        while (
            sum(1 for j in app_state.jobs.values() if j.status == JobStatus.running)
            >= app_state.max_concurrent_downloads
            and job.status != JobStatus.cancelled
        ):
            await app_state.download_slot_condition.wait()
        if job.status == JobStatus.cancelled:
            return False
        job.status = JobStatus.running
        return True


async def _resolve_media_url(
    video_id: int,
    part: int,
    stream_index: int,
    app_state: AppState,
) -> tuple[str, float | None]:
    """Resolve the direct media URL for a video part and stream index.

    Args:
        video_id: Library video identifier.
        part: Part index passed to the quality object's URL resolver.
        stream_index: Index into the m3u8 playlist variants.
        app_state: Application state providing the library and HTTP client.

    Returns:
        A tuple of ``(url, bandwidth_mbps)`` where ``bandwidth_mbps`` is the
        stream bandwidth in Mbps or ``None`` if unavailable.

    Raises:
        ValueError: If the video or a downloadable quality is not found.
        Exception: On HTTP or m3u8 parsing errors.
    """
    manager = app_state.manager
    if manager is None:
        msg = "No active session"
        raise ValueError(msg)
    item = manager.library.get(video_id)
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
    playlist = parsed.playlists[stream_index]
    bandwidth = getattr(playlist.stream_info, "bandwidth", None)
    bandwidth_mbps = bandwidth / 1_000_000 if bandwidth is not None else None
    return playlist.absolute_uri, bandwidth_mbps


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
        job.bytes_downloaded_raw = _parse_size_str(size_m.group(1))
        job.bytes_total_raw = _parse_size_str(size_m.group(2))
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


def _fail_job(
    job: DownloadJob,
    error_msg: str,
    queues: Queues,
    app_state: AppState,
) -> None:
    """Set a job to error state and schedule side effects as background tasks.

    Sets job error and status, publishes the update to SSE subscribers, closes
    streams, and schedules the job_failed webhook and history insertion.

    Args:
        job: The job to mark as failed.
        error_msg: Error message to set on the job.
        queues: SSE subscriber queues for the job.
        app_state: Application state providing the job registry and background tasks.
    """
    job.error = error_msg
    job.status = JobStatus.error
    _publish(job, queues)
    _publish_global(_compute_active_counts(app_state.jobs), app_state.global_job_queues)
    _close_streams(job.job_id, queues)
    _fire_background(
        app_state.background_tasks,
        fire_webhook(
            app_state,
            "job_failed",
            {
                "job_id": job.job_id,
                "output_name": job.output_name,
                "content_id": job.content_id,
                "error": job.error,
            },
        ),
    )
    _fire_background(
        app_state.background_tasks,
        asyncio.to_thread(
            insert_history,
            app_state.history_db_path,
            job.job_id,
            "error",
            job.output_name,
            job.content_id,
            job.source,
            None,
            None,
            job.error,
            job.bandwidth_mbps,
        ),
    )


def _handle_terminal_job(
    job: DownloadJob,
    app_state: AppState,
) -> None:
    """Schedule side effects for a job that reached a terminal state after process exit.

    Fires rescan, webhook delivery, and history insertion based on job status.

    Args:
        job: The finalized job.
        app_state: Application state providing background tasks and history path.
    """
    if job.status == JobStatus.done:
        _fire_background(app_state.background_tasks, rescan_and_store(app_state))
        _fire_background(
            app_state.background_tasks,
            fire_webhook(
                app_state,
                "job_completed",
                {
                    "job_id": job.job_id,
                    "output_name": job.output_name,
                    "content_id": job.content_id,
                    "file_size": job.file_size,
                    "output_path": job.output_path,
                },
            ),
        )
    elif job.status == JobStatus.error:
        _fire_background(
            app_state.background_tasks,
            fire_webhook(
                app_state,
                "job_failed",
                {
                    "job_id": job.job_id,
                    "output_name": job.output_name,
                    "content_id": job.content_id,
                    "error": job.error,
                },
            ),
        )
    if job.status in (JobStatus.done, JobStatus.error):
        _fire_background(
            app_state.background_tasks,
            asyncio.to_thread(
                insert_history,
                app_state.history_db_path,
                job.job_id,
                job.status,
                job.output_name,
                job.content_id,
                job.source,
                job.file_size,
                job.output_path,
                job.error,
                job.bandwidth_mbps,
            ),
        )


async def _run_download(  # noqa: PLR0913
    job: DownloadJob,
    video_id: int,
    part: int,
    stream_index: int,
    save_dir: str,
    save_name: str,
    queues: Queues,
    app_state: AppState,
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
        queues: SSE subscriber queues, keyed by job ID.
        app_state: Application state providing all runtime context.
    """
    if not await _acquire_slot(job, app_state):
        _publish_global(
            _compute_active_counts(app_state.jobs), app_state.global_job_queues
        )
        return

    _publish_global(_compute_active_counts(app_state.jobs), app_state.global_job_queues)

    try:
        try:
            media_url, bandwidth_mbps = await _resolve_media_url(
                video_id, part, stream_index, app_state
            )
            job.bandwidth_mbps = bandwidth_mbps
        except Exception as exc:  # noqa: BLE001
            _fail_job(job, f"Failed to resolve media URL: {exc}", queues, app_state)
            return

        _publish(job, queues)
        try:
            proc = await _launch_process(
                media_url,
                save_dir,
                save_name,
                app_state.download_thread_count,
            )
            output_lines = await _stream_output(proc, job, queues)
        except Exception as exc:  # noqa: BLE001
            _fail_job(job, str(exc), queues, app_state)
            return

        _finalize_job(job, proc.returncode, output_lines, save_dir, save_name, queues)
        _publish_global(
            _compute_active_counts(app_state.jobs), app_state.global_job_queues
        )
        _handle_terminal_job(job, app_state)
    finally:
        async with app_state.download_slot_condition:
            app_state.download_slot_condition.notify_all()


def dispatch_download(  # noqa: PLR0913
    job: DownloadJob,
    video_id: int,
    part: int,
    stream_index: int,
    save_dir: str,
    save_name: str,
    app_state: AppState,
) -> None:
    """Schedule a download job as a background task.

    Fires ``_run_download`` via ``_fire_background`` using
    ``app_state.background_tasks``.  Callers should have already registered
    the job with :func:`register_job` before calling this.

    Args:
        job: The registered download job to execute.
        video_id: Library video identifier to look up.
        part: Part index to resolve.
        stream_index: Index into the m3u8 playlist variants.
        save_dir: Directory path where the output file will be written.
        save_name: Output filename stem (without extension).
        app_state: Application state providing all runtime context.
    """
    _fire_background(
        app_state.background_tasks,
        _run_download(
            job,
            video_id,
            part,
            stream_index,
            save_dir,
            save_name,
            app_state.queues,
            app_state,
        ),
    )
