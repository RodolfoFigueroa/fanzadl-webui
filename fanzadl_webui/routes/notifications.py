import asyncio
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from fanzadl_webui.dependencies import get_app_state
from fanzadl_webui.state import AppState

router = APIRouter(prefix="/notifications")


@router.get("/errors")
async def error_events(
    app_state: Annotated[AppState, Depends(get_app_state)],
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
