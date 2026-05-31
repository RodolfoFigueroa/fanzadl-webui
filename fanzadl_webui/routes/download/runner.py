import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import m3u8
from fanzadl.constants import USER_AGENT

from fanzadl_webui.filename import rescan_and_store
from fanzadl_webui.jobs import DownloadJob, JobStatus, Queues
from fanzadl_webui.state import AppState

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()
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


@dataclass
class _ConcurrencyContext:
    jobs: dict[str, DownloadJob]
    condition: asyncio.Condition
    app_state: AppState
    global_job_queues: "list[asyncio.Queue[dict[str, int] | None]]" = None  # type: ignore[assignment]


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
    global_job_queues: "list[asyncio.Queue[dict[str, int] | None]]",
) -> None:
    """Broadcast active-count snapshot to all global SSE subscribers.

    Args:
        counts: Mapping of content_id to active job count.
        global_job_queues: List of subscriber queues to broadcast to.
    """
    for q in global_job_queues:
        q.put_nowait(counts)


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
    app_state: AppState,
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


def _finalize_and_broadcast(  # noqa: PLR0913
    job: DownloadJob,
    returncode: int | None,
    output_lines: list[str],
    save_dir: str,
    save_name: str,
    queues: Queues,
    ctx: "_ConcurrencyContext",
) -> None:
    """Finalize job and broadcast updated active counts to global subscribers.

    Args:
        job: Job to finalize.
        returncode: Process exit code.
        output_lines: All stdout lines collected during the download.
        save_dir: Directory where the output file was written.
        save_name: Output filename stem (without extension).
        queues: SSE subscriber queues for the job.
        ctx: Concurrency context for broadcasting global counts.
    """
    _finalize_job(job, returncode, output_lines, save_dir, save_name, queues)
    _publish_global(_compute_active_counts(ctx.jobs), ctx.global_job_queues)


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
        queues: SSE subscriber queues, keyed by job ID.
        concurrency: Context providing the condition variable, job registry,
            and app state.
    """
    if not await _acquire_slot(job, concurrency):
        _publish_global(
            _compute_active_counts(concurrency.jobs), concurrency.global_job_queues
        )
        return

    _publish_global(
        _compute_active_counts(concurrency.jobs), concurrency.global_job_queues
    )

    try:
        media_url = await _resolve_media_url(
            video_id, part, stream_index, concurrency.app_state
        )
    except Exception as exc:  # noqa: BLE001
        job.error = f"Failed to resolve media URL: {exc}"
        job.status = JobStatus.error
        _publish(job, queues)
        _publish_global(
            _compute_active_counts(concurrency.jobs), concurrency.global_job_queues
        )
        _close_streams(job.job_id, queues)
        return

    _publish(job, queues)
    try:
        try:
            proc = await _launch_process(
                media_url,
                save_dir,
                save_name,
                concurrency.app_state.download_thread_count,
            )
            output_lines = await _stream_output(proc, job, queues)
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            job.status = JobStatus.error
            _publish(job, queues)
            _publish_global(
                _compute_active_counts(concurrency.jobs), concurrency.global_job_queues
            )
            _close_streams(job.job_id, queues)
            return
        _finalize_and_broadcast(
            job, proc.returncode, output_lines, save_dir, save_name, queues, concurrency
        )
        if job.status == JobStatus.done:
            _task = asyncio.create_task(rescan_and_store(concurrency.app_state))
            _background_tasks.add(_task)
            _task.add_done_callback(_background_tasks.discard)
    finally:
        async with concurrency.condition:
            concurrency.condition.notify_all()
