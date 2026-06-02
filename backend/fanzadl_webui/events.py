from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fanzadl_webui.models import LibraryEvent
    from fanzadl_webui.state import AppState


def publish_library_event(app_state: AppState, event: LibraryEvent) -> None:
    """Fan out a library domain event to all subscribed SSE clients.

    The serialized event is appended to the ring buffer (for reconnect
    catch-up) and then put onto every per-client queue.  If a queue is
    already full, the oldest item is evicted to make room so slow clients
    always receive the most recent events rather than silently missing them.

    Args:
        app_state: Application state holding the queue list and ring buffer.
        event: The library event to publish.
    """
    app_state.library_event_counter += 1
    event_id = app_state.library_event_counter
    payload = event.model_dump_json()
    entry: tuple[int, str] = (event_id, payload)
    app_state.library_event_buffer.append(entry)
    for q in list(app_state.library_event_queues):
        if q.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                q.get_nowait()

        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(entry)
