import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from fanzadl_webui.dependencies import DOWNLOAD_DIR, get_app_state
from fanzadl_webui.jobs import (
    DownloadJob,
    JobStatus,
    Queues,
    get_download_slot_condition,
    get_global_job_queues,
    get_jobs,
    get_queues,
)
from fanzadl_webui.routes.download.runner import (
    _background_tasks,
    _close_streams,
    _compute_active_counts,
    _ConcurrencyContext,
    _processes,
    _publish,
    _publish_global,
    _run_download,
    cancel_active_jobs,
)
from fanzadl_webui.state import AppState

router = APIRouter()


class DownloadRequest(BaseModel):
    output_name: str
    video_id: int
    part: int
    stream_index: int
    content_id: str | None = None


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
    body: DownloadRequest,
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    queues: Annotated[Queues, Depends(get_queues)],
    condition: Annotated[asyncio.Condition, Depends(get_download_slot_condition)],
    app_state: Annotated[AppState, Depends(get_app_state)],
    global_job_queues: Annotated[list, Depends(get_global_job_queues)],
) -> dict[str, str]:
    """Create a download job and dispatch it as a background task.

    Validates that the resolved output path stays within the download directory
    (path-traversal guard), creates any required subdirectories, registers a new
    DownloadJob, and fires off ``_run_download`` as an asyncio background task.

    Args:
        body: Download parameters including video ID, part, stream index, and
            output name.
        jobs: Injected mapping of active download jobs keyed by job ID.
        queues: Injected SSE subscriber queues keyed by job ID.
        condition: Injected concurrency condition for download slot management.
        app_state: Injected application state.

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

    job = DownloadJob.create(output_name=body.output_name, content_id=body.content_id)
    jobs[job.job_id] = job
    queues[job.job_id] = []
    concurrency = _ConcurrencyContext(
        jobs=jobs,
        condition=condition,
        app_state=app_state,
        global_job_queues=global_job_queues,
    )
    _publish_global(_compute_active_counts(jobs), global_job_queues)
    task = asyncio.create_task(
        _run_download(
            job,
            body.video_id,
            body.part,
            body.stream_index,
            save_dir,
            save_name,
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


@router.get("/jobs/active-counts/")
def get_active_counts(
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
) -> dict[str, int]:
    """Return a snapshot of pending/running job counts grouped by content_id.

    Args:
        jobs: Injected mapping of active download jobs keyed by job ID.

    Returns:
        A dict mapping content_id to the number of active jobs for that item.
    """
    return _compute_active_counts(jobs)


@router.get("/jobs/global-events")
async def global_job_events(
    jobs: Annotated[dict[str, DownloadJob], Depends(get_jobs)],
    global_job_queues: Annotated[list, Depends(get_global_job_queues)],
) -> EventSourceResponse:
    """Stream SSE events with active job counts grouped by content_id.

    Sends an initial snapshot immediately, then broadcasts updated counts
    whenever any job transitions to or from an active state. Cleans up the
    subscriber queue when the client disconnects.

    Args:
        jobs: Injected mapping of active download jobs keyed by job ID.
        global_job_queues: Injected list of subscriber queues for global events.

    Returns:
        An EventSourceResponse that streams serialized count dicts as JSON.
    """

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        """Yield active-count snapshots until the client disconnects."""
        q: asyncio.Queue[dict[str, int] | None] = asyncio.Queue()
        global_job_queues.append(q)
        try:
            yield {"data": json.dumps(_compute_active_counts(jobs))}
            while True:
                counts = await q.get()
                if counts is None:
                    break
                yield {"data": json.dumps(counts)}
        finally:
            if q in global_job_queues:
                global_job_queues.remove(q)

    return EventSourceResponse(event_generator())
