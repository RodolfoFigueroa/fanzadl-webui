import logging
from pathlib import Path

import m3u8
from fanzadl.models.video import LibraryItemContentsModel

from fanzadl_webui.dependencies import DOWNLOAD_DIR
from fanzadl_webui.events import publish_library_event
from fanzadl_webui.filename import render_template
from fanzadl_webui.models import DownloadJob, JobStatus, LibraryEvent
from fanzadl_webui.routes.download.runner import (
    dispatch_download,
    register_job,
)
from fanzadl_webui.state import AppState

logger = logging.getLogger(__name__)


def _item_parts_list(item: LibraryItemContentsModel) -> list[int]:
    """Return the list of part indices to enqueue for a library item."""
    if item.parts <= 1:
        return [item.parts]  # 0 or 1
    return list(range(1, item.parts + 1))


def _item_fields(item: LibraryItemContentsModel) -> dict[str, str | int | None]:
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
    item: LibraryItemContentsModel,
    part: int,
    output_name: str,
    app_state: AppState,
) -> None:
    """Fetch the best-bandwidth stream for one part and fire a download task.

    Raises any exception so the caller can log-and-skip as appropriate.
    """
    active = {JobStatus.pending, JobStatus.running}
    if any(
        j.output_name == output_name and j.status in active
        for j in app_state.jobs.values()
    ):
        logger.debug(
            "auto-download: job already active for video %s part %s; skipping",
            video_id,
            part,
        )
        return

    highest = item.highest
    if highest is None:
        err = f"item {video_id} has no highest-quality stream; cannot auto-enqueue"
        raise ValueError(err)

    playlist_url = highest.get_url(part)
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

    job = DownloadJob.create(
        output_name=output_name, content_id=item.content_id, source="auto"
    )
    job.bandwidth_mbps = float(bandwidth_mbps)
    register_job(job, app_state)
    dispatch_download(
        job,
        video_id,
        part,
        stream_index,
        str(save_dir_path),
        output_name_path.name,
        app_state,
    )
    logger.info(
        "auto-download: enqueued job for video %s (Part %s) (%s mbps)",
        item.content_id,
        part,
        bandwidth_mbps,
        extra={"notify": True},
    )
    publish_library_event(
        app_state,
        LibraryEvent(
            type="auto_queued",
            content_id=item.content_id,
            title=getattr(item, "title", None),
            part=part,
            mylibrary_id=getattr(item, "mylibrary_id", None),
        ),
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
