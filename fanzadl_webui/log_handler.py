import asyncio
import json
import logging
import time


class NotificationHandler(logging.Handler):
    """Logging handler that pushes log records to SSE subscriber queues.

    Records at ERROR level or above are always forwarded. Records below ERROR
    are forwarded only when ``extra={"notify": True}`` is passed to the logger
    call. A rate-limit prevents flooding clients during error bursts.

    Thread-safe: uses call_soon_threadsafe so emit() can be called from
    asyncio.to_thread worker threads.

    Args:
        queues: Shared list of per-client asyncio queues. Items are appended
            and removed by the SSE endpoint as clients connect/disconnect.
        loop: The running event loop to schedule queue writes onto.
        min_interval: Minimum seconds between emitted notifications.
    """

    def __init__(
        self,
        queues: list[asyncio.Queue[str | None]],
        loop: asyncio.AbstractEventLoop,
        min_interval: float = 1.0,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self._queues = queues
        self._loop = loop
        self._min_interval = min_interval
        self._last_emit: float = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR and not getattr(record, "notify", False):
            return
        now = time.monotonic()
        if now - self._last_emit < self._min_interval:
            return
        self._last_emit = now
        payload = json.dumps(
            {"message": record.getMessage(), "level": record.levelname}
        )
        for q in list(self._queues):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, payload)
            except asyncio.QueueFull:
                pass
