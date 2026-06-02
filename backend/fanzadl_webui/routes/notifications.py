import asyncio
from collections.abc import AsyncGenerator
from typing import Annotated

from fanzadl_webui.dependencies import get_app_state, require_api_key
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/errors")
async def error_events(
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> EventSourceResponse:
    """Stream backend ERROR+ log messages as SSE events.

    Each event data field contains the plain log message string. The stream
    remains open indefinitely until the client disconnects.

    Args:
        app_state: Injected application state containing the shared
            notification_queues list.

    Returns:
        An EventSourceResponse that streams error notification messages.
    """

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=20)
        app_state.notification_queues.append(q)
        try:
            while True:
                msg = await q.get()
                if msg is None:
                    break
                yield {"data": msg}
        finally:
            if q in app_state.notification_queues:
                app_state.notification_queues.remove(q)

    return EventSourceResponse(event_generator())


@router.get("/library")
async def library_events(
    request: Request,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> EventSourceResponse:
    """Stream library domain events as SSE.

    Authenticated via the ``X-API-Key`` request header or a ``session``
    cookie.  On connect, buffered events (up to the last 50) are replayed,
    filtered by ``Last-Event-ID`` if provided so reconnecting clients only
    receive events they have not yet seen.  The stream remains open
    indefinitely until the client disconnects.

    Args:
        request: The incoming HTTP request (used to read ``Last-Event-ID``).
        app_state: Injected application state.
        _: Authentication dependency (raises 401 on failure).

    Returns:
        An EventSourceResponse streaming ``LibraryEvent`` JSON payloads.
    """
    raw_last_id = request.headers.get("last-event-id")
    last_event_id: int | None = None
    if raw_last_id is not None:
        try:
            last_event_id = int(raw_last_id)
        except ValueError:
            last_event_id = None

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        buffered = list(app_state.library_event_buffer)
        max_buffered_id = buffered[-1][0] if buffered else 0
        # If last_event_id is >= max buffered ID the client is up-to-date or
        # the ID is stale from a previous server session — replay everything.
        if last_event_id is not None and last_event_id < max_buffered_id:
            to_replay = [(eid, p) for eid, p in buffered if eid > last_event_id]
        else:
            to_replay = buffered if last_event_id is None else []

        q: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue(maxsize=50)
        app_state.library_event_queues.append(q)
        try:
            for event_id, payload in to_replay:
                yield {"id": str(event_id), "data": payload}
            while True:
                entry = await q.get()
                if entry is None:
                    break
                event_id, payload = entry
                yield {"id": str(event_id), "data": payload}
        finally:
            if q in app_state.library_event_queues:
                app_state.library_event_queues.remove(q)

    return EventSourceResponse(event_generator())
