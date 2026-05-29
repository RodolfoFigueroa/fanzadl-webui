import asyncio
import logging
import threading
from collections.abc import Callable, Generator
from pathlib import Path

from fanzadl import FanzaDLManager
from fanzadl.models.library import LibraryDataModel
from fanzadl.models.video import LibraryItemContentsModel

from fanzadl_webui.library_cache import delete_library_cache, load_library_cache

logger = logging.getLogger(__name__)


async def warm_all_details(
    manager: FanzaDLManager,
    item_ids: set[int] | None = None,
) -> None:
    """Fetch and cache `.details` and `._javstash_info` for library items.

    Fetches are run in parallel, capped at 5 concurrent items.

    Args:
        manager: The manager whose library items will be warmed.
        item_ids: If given, only items whose ``mylibrary_id`` is in this set are
            warmed. If ``None``, all items are warmed.
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

    items = (
        item
        for item in manager.library.values()
        if item_ids is None or item.mylibrary_id in item_ids
    )
    await asyncio.gather(*[_warm_item(item) for item in items])


class PersistingFanzaDLManager(FanzaDLManager):
    def __init__(
        self,
        *args,
        save_fn: Callable[[str, str], None],
        library_cache_path: Path | None = None,
        **kwargs,
    ) -> None:
        self._save_fn = save_fn
        self._library_cache_path = library_cache_path
        self._library_cache: dict[int, dict] = {}
        self._ids_restored_from_cache: set[int] = set()
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

    def _user_library_generator(self) -> Generator[LibraryDataModel]:
        for page in super()._user_library_generator():
            for elem in page.list_:
                item_id = int(elem.contents["mylibrary_id"])
                cached = self._library_cache.get(item_id)
                if cached is not None:
                    cached_vl = cached["model"]["video_list"]
                    target_key = (
                        "vr_rate_pattern"
                        if "vr_rate_pattern" in elem.contents
                        else "video_list"
                    )
                    elem.contents[target_key] = cached_vl
            yield page

    def update_library(self) -> None:
        self._ids_restored_from_cache = set()
        if self._library_cache_path is not None:
            self._library_cache = load_library_cache(
                self._library_cache_path, self.user_id
            )
        try:
            super().update_library()
        except Exception as exc:
            if self._library_cache:
                msg = f"Library update failed with cache loaded. Exception:\n{exc}"
                logger.warning(msg)

                assert self._library_cache_path is not None  # noqa: S101
                delete_library_cache(self._library_cache_path)
                self._library_cache = {}
                super().update_library()
            else:
                raise
        for item_id, item in self.library.items():
            cached = self._library_cache.get(item_id)
            if cached is None:
                continue
            javstash_info = cached.get("javstash_info")
            if javstash_info is not None:
                item.__dict__["_javstash_info"] = javstash_info
            self._ids_restored_from_cache.add(item_id)

            msg = f"Restored library item {item_id} from cache"
            logger.info(msg)
        self._library_cache = {}
