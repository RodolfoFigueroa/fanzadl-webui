import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, Literal

from fanzadl_webui.dependencies import get_app_state, require_api_key
from fanzadl_webui.download import (
    _cancel_job,
    _compute_active_counts,
    cancel_active_jobs,
)
from fanzadl_webui.models import DownloadJob, JobStatus
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/jobs", tags=["Downloads"])


@router.get("/")
def list_jobs(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> list[DownloadJob]:
    """Return all current download jobs.

    Returns:
        A list of all DownloadJob entries.
    """
    return list(app_state.jobs.values())


@router.get("/active-counts/")
def get_active_counts(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict[str, int]:
    """Return a snapshot of pending/running job counts grouped by content_id.

    Returns:
        A dict mapping content_id to the number of active jobs for that item.
    """
    return _compute_active_counts(app_state.jobs)


@router.get("/global-events")
async def global_job_events(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> EventSourceResponse:
    """Stream SSE events with active job counts grouped by content_id.

    Sends an initial snapshot immediately, then broadcasts updated counts
    whenever any job transitions to or from an active state. Cleans up the
    subscriber queue when the client disconnects.

    Returns:
        An EventSourceResponse that streams serialized count dicts as JSON.
    """

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        """Yield active-count snapshots until the client disconnects."""
        q: asyncio.Queue[dict[str, int] | None] = asyncio.Queue(maxsize=50)
        app_state.global_job_queues.append(q)
        try:
            yield {"data": json.dumps(_compute_active_counts(app_state.jobs))}
            while True:
                counts = await q.get()
                if counts is None:
                    break
                yield {"data": json.dumps(counts)}
        finally:
            if q in app_state.global_job_queues:
                app_state.global_job_queues.remove(q)

    return EventSourceResponse(event_generator())


@router.get("/created-events")
async def job_created_events(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> EventSourceResponse:
    """Stream SSE events whenever a new download job is registered.

    Sends a DownloadJob JSON snapshot each time a job is created, whether
    triggered by a user request or by auto-enqueue. Cleans up the subscriber
    queue when the client disconnects.

    Returns:
        An EventSourceResponse that streams serialized DownloadJob snapshots.
    """

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        """Yield new job snapshots until the client disconnects."""
        q: asyncio.Queue[DownloadJob | None] = asyncio.Queue(maxsize=50)
        app_state.job_created_queues.append(q)
        try:
            while True:
                job = await q.get()
                if job is None:
                    break
                yield {"data": job.model_dump_json()}
        finally:
            if q in app_state.job_created_queues:
                app_state.job_created_queues.remove(q)

    return EventSourceResponse(event_generator())


@router.get("/{job_id}")
def get_job(
    job_id: str,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> DownloadJob:
    """Return a single download job by ID.

    Args:
        job_id: UUID string identifying the requested job.

    Returns:
        The DownloadJob matching job_id.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
    job = app_state.jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    return job


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
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
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> None:
    """Bulk-cancel or delete jobs matching job_filter.

    The ``job_filter`` query parameter controls which jobs are targeted:

    - ``active``: cancel all running and pending jobs.
    - ``done``: remove only successfully completed jobs.
    - ``errored``: remove only error and cancelled jobs.
    - ``finished``: remove all terminal jobs (done, error, and cancelled).

    Args:
        job_filter: Selection criterion for which jobs to act on.
        app_state: Injected application state.
    """
    if job_filter == "active":
        await cancel_active_jobs(app_state)
        return

    if job_filter == "done":
        target_statuses = {JobStatus.done}
    elif job_filter == "errored":
        target_statuses = {JobStatus.error, JobStatus.cancelled}
    else:  # finished
        target_statuses = {JobStatus.done, JobStatus.error, JobStatus.cancelled}

    to_delete = [
        jid for jid, j in app_state.jobs.items() if j.status in target_statuses
    ]
    for jid in to_delete:
        del app_state.jobs[jid]
        app_state.queues.pop(jid, None)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_or_delete_job(
    job_id: str,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> None:
    """Cancel an active job or delete a finished one by ID.

    If the job is in a terminal state (done, error, or cancelled) it is removed
    immediately. If it is running or pending, it is marked cancelled, its
    subprocess is terminated, subscribers are notified, SSE streams are closed,
    and the concurrency condition is signalled.

    Args:
        job_id: UUID string identifying the job to act on.
        app_state: Injected application state.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
    job = app_state.jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    if job.status in (JobStatus.done, JobStatus.error, JobStatus.cancelled):
        del app_state.jobs[job_id]
        app_state.queues.pop(job_id, None)
        return
    _cancel_job(job, app_state.queues, app_state)
    async with app_state.download_slot_condition:
        app_state.download_slot_condition.notify_all()


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> EventSourceResponse:
    """Stream SSE events for a job until it finishes or the client disconnects.

    Returns an EventSourceResponse backed by an async generator. If the job is
    already in a terminal state (done or error) the current snapshot is yielded
    immediately. Otherwise, job snapshots are streamed as they are published until
    a None sentinel signals completion.

    Args:
        job_id: UUID string identifying the job to observe.

    Returns:
        An EventSourceResponse that streams serialized DownloadJob snapshots.

    Raises:
        HTTPException: 404 if no job with the given ID exists.
    """
    job = app_state.jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        """Yield serialized job snapshots until a None sentinel is received."""
        q: asyncio.Queue[DownloadJob | None] = asyncio.Queue(maxsize=100)
        app_state.queues.setdefault(job_id, []).append(q)
        try:
            # Check after appending to avoid a race between job completion
            # and queue registration.
            if job.status in (JobStatus.done, JobStatus.error, JobStatus.cancelled):
                yield {"data": job.model_dump_json()}
                return
            while True:
                snapshot = await q.get()
                if snapshot is None:
                    break
                yield {"data": snapshot.model_dump_json()}
        finally:
            job_queues = app_state.queues.get(job_id, [])
            if q in job_queues:
                job_queues.remove(q)
            if not job_queues:
                app_state.queues.pop(job_id, None)

    return EventSourceResponse(event_generator())
