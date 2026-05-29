import asyncio
import logging
import threading
from collections.abc import Callable

from fanzadl import FanzaDLManager
from fanzadl.models.video import LibraryItemContentsModel

logger = logging.getLogger(__name__)


async def warm_all_details(manager: FanzaDLManager) -> None:
    """Fetch and cache `.details` and `._javstash_info` for all library items.

    Fetches are run in parallel, capped at 5 concurrent items.

    Args:
        manager: The manager whose library items will be warmed.
    """
    semaphore = asyncio.Semaphore(5)

    async def _warm_item(item: LibraryItemContentsModel) -> None:
        async with semaphore:
            try:
                logger.debug("Warming details for library item %s", item.mylibrary_id)
                await asyncio.to_thread(lambda: (item.details, item.javstash_id))
                logger.debug("Warmed details for library item %s", item.mylibrary_id)
            except Exception:
                logger.exception(
                    "Failed to warm details for library item %s",
                    item.mylibrary_id,
                )

    await asyncio.gather(*[_warm_item(item) for item in manager.library.values()])


class PersistingFanzaDLManager(FanzaDLManager):
    def __init__(self, *args, save_fn: Callable[[str, str], None], **kwargs) -> None:
        self._save_fn = save_fn
        self._rotation_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def rotate_tokens(self) -> None:
        token_before = self.refresh_token
        with self._rotation_lock:
            if self.refresh_token != token_before:
                # Another thread already rotated while we waited for the lock
                return
            super().rotate_tokens()
            try:
                self._save_fn(self.user_id, self.refresh_token)
            except Exception:
                logger.exception("Failed to persist tokens after rotation")
