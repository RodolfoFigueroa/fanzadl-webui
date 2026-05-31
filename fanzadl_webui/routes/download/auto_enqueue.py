import asyncio
import logging
from pathlib import Path
from typing import Any

import m3u8

from fanzadl_webui.dependencies import DOWNLOAD_DIR
from fanzadl_webui.filename import render_template
from fanzadl_webui.jobs import DownloadJob
from fanzadl_webui.routes.download.runner import _ConcurrencyContext, _run_download
from fanzadl_webui.state import AppState

logger = logging.getLogger(__name__)


def _item_parts_list(item: Any) -> list[int]:
    """Return the list of part indices to enqueue for a library item."""
    if item.parts <= 1:
        return [item.parts]  # 0 or 1
    return list(range(1, item.parts + 1))


def _item_fields(item: Any) -> dict[str, str | int | None]:
    """Return the template field dict for a library item."""
    return {
        "mylibrary_id": item.mylibrary_id,
        "content_id": item.content_id,
        "title": item.title,
        "content_type": item.content_type,
        "parts": item.parts,
        "javstash_id": getattr(item, "javstash_id", None),
        "javstash_studio_code": getattr(item, "javstash_studio_code", None),
    }


async def _enqueue_part(
    video_id: int,
    item: Any,
    part: int,
    output_name: str,
    app_state: AppState,
) -> None:
    """Fetch the best-bandwidth stream for one part and fire a download task.

    Raises any exception so the caller can log-and-skip as appropriate.
    """
    playlist_url = item.highest.get_url(part)
    response = await app_state.http_client.get(playlist_url, follow_redirects=True)
    response.raise_for_status()
    parsed = m3u8.loads(response.text, uri=playlist_url)
    if not parsed.is_variant or not parsed.playlists:
        logger.warning(
            "auto-download: no variant streams for video %s part %s; skipping",
            video_id,
            part,
        )
        return

    stream_index, selected_playlist = max(
        enumerate(parsed.playlists),
        key=lambda x: x[1].stream_info.bandwidth,
    )
    bandwidth_mbps = selected_playlist.stream_info.bandwidth // 1_000_000

    output_name_path = Path(output_name)
    resolved = (DOWNLOAD_DIR / output_name).resolve()
    if not resolved.is_relative_to(DOWNLOAD_DIR.resolve()):
        logger.warning(
            "auto-download: resolved path escapes download dir"
            " for video %s part %s; skipping",
            video_id,
            part,
        )
        return
    save_dir_path = DOWNLOAD_DIR / output_name_path.parent
    save_dir_path.mkdir(parents=True, exist_ok=True)

    job = DownloadJob.create(output_name=output_name)
    app_state.jobs[job.job_id] = job
    app_state.queues[job.job_id] = []
    concurrency = _ConcurrencyContext(
        jobs=app_state.jobs,
        condition=app_state.download_slot_condition,
        app_state=app_state,
    )
    task = asyncio.create_task(
        _run_download(
            job,
            video_id,
            part,
            stream_index,
            str(save_dir_path),
            output_name_path.name,
            app_state.queues,
            concurrency,
        )
    )
    app_state.background_tasks.add(task)
    task.add_done_callback(app_state.background_tasks.discard)
    logger.info(
        "auto-download: enqueued job for video %s (Part %s) (%s mbps)",
        item.content_id,
        part,
        bandwidth_mbps,
        extra={"notify": True},
    )


async def auto_enqueue_new_items(new_ids: set[int], app_state: AppState) -> None:
    """Enqueue download jobs for newly discovered library items.

    For each item ID in ``new_ids``, fetches the m3u8 playlist for every part,
    selects the highest-bandwidth stream variant, and fires a background
    ``_run_download`` task.  Per-item errors are logged and skipped so that a
    single failure does not abort the rest of the batch.

    Args:
        new_ids: Set of library video IDs that were not present before the
            most recent library refresh.
        app_state: Application state providing the manager, HTTP client,
            job registry, and settings.
    """
    manager = app_state.manager
    if manager is None:
        return

    for video_id in new_ids:
        item = manager.library.get(video_id)
        if item is None or item.highest is None:
            continue

        parts_list = _item_parts_list(item)
        template = (
            app_state.multi_part_filename_template
            if item.parts > 1
            else app_state.single_part_filename_template
        )
        fields = _item_fields(item)

        for part in parts_list:
            output_name = render_template(template, fields, part)
            try:
                await _enqueue_part(video_id, item, part, output_name, app_state)
            except Exception:
                logger.exception(
                    "auto-download: failed to enqueue video %s part %s; skipping",
                    video_id,
                    part,
                )


async def auto_enqueue_missing_parts(
    excluded_ids: set[int], app_state: AppState
) -> None:
    """Enqueue download jobs for parts that are absent from the download directory.

    Iterates over all items currently in the library (excluding ``excluded_ids``
    to avoid double-queuing with :func:`auto_enqueue_new_items`).  For each
    item a fast pre-check against ``app_state.download_counts`` skips fully
    downloaded items without hitting the filesystem.  Each individual part is
    then checked for the presence of its rendered ``.mp4`` file; only absent
    parts are enqueued.  Per-item errors are logged and skipped.

    Args:
        excluded_ids: Video IDs to skip (typically items already handled by
            :func:`auto_enqueue_new_items` in the same refresh cycle).
        app_state: Application state providing the manager, HTTP client,
            job registry, and settings.
    """
    manager = app_state.manager
    if manager is None:
        return

    for video_id, item in manager.library.items():
        if video_id in excluded_ids or item.highest is None:
            continue

        is_multi = item.parts > 1
        expected_count = item.parts if is_multi else 1
        if app_state.download_counts.get(item.content_id, 0) >= expected_count:
            continue

        parts_list = _item_parts_list(item)
        template = (
            app_state.multi_part_filename_template
            if is_multi
            else app_state.single_part_filename_template
        )
        fields = _item_fields(item)

        for part in parts_list:
            output_name = render_template(template, fields, part)
            if (DOWNLOAD_DIR / f"{output_name}.mp4").exists():
                continue
            try:
                await _enqueue_part(video_id, item, part, output_name, app_state)
            except Exception:
                logger.exception(
                    "auto-download missing: failed to enqueue"
                    " video %s part %s; skipping",
                    video_id,
                    part,
                )
