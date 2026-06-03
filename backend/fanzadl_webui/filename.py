import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fanzadl_webui.state import AppState
from collections.abc import Callable

from fanzadl_webui.dependencies import LIBRARY_DB_PATH
from fanzadl_webui.library_db import get_all_items

_PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::([^}]*))?\}")
_ILLEGAL_CHARS_RE = re.compile(r'[\\:*?"<>|]')

_FORMAT_FUNC_MAP: dict[str, Callable[[str], str]] = {
    "U": str.upper,
    "L": str.lower,
    "C": lambda s: (s[0].upper() + s[1:].lower()) if s else s,
    "T": lambda s: re.sub(r"\b\w", lambda m: m.group(0).upper(), s),
}


def _apply_spec(value: str | int | None, spec: str) -> str:
    """Apply a format spec to a resolved field value.

    Supported string specs: ``U`` (uppercase), ``L`` (lowercase),
    ``C`` (capitalize first letter), ``T`` (title case).
    Supported number specs: zero-pad notation, e.g. ``02`` pads to 2 digits.

    Args:
        value: The raw field value to format.
        spec: The format specifier string (the part after ``:``).

    Returns:
        The formatted string.
    """
    if isinstance(value, int):
        m = re.fullmatch(r"0(\d+)", spec)
        if m:
            return str(value).zfill(int(m.group(1)))
        return str(value)

    s = "" if value is None else str(value)
    if spec in _FORMAT_FUNC_MAP:
        return _FORMAT_FUNC_MAP[spec](s)
    return s


def _sanitize_value(value: str) -> str:
    """Strip characters illegal in file/path component names and trim whitespace.

    Forward slashes are preserved because they come from the template structure.

    Args:
        value: The substituted value to sanitize.

    Returns:
        The sanitized string.
    """
    return _ILLEGAL_CHARS_RE.sub("", value).strip()


def render_template(
    template: str,
    fields: dict[str, str | int | None],
    part: int,
) -> str:
    """Render a filename template by substituting ``{field}`` tokens.

    Mirrors the TypeScript ``renderFilenameTemplate`` function in
    ``frontend/src/lib/filename.ts``.

    Available fields come from ``fields`` plus a synthetic ``part`` key.
    Unknown field names are left unchanged in the output.

    Args:
        template: The filename template string.
        fields: Mapping of field names to their values (all ``LibraryItem``
            properties).
        part: The part number to inject as the ``part`` field.

    Returns:
        The rendered filename string.
    """
    all_fields: dict[str, str | int | None] = {**fields, "part": part}

    def _replace(m: re.Match[str]) -> str:
        name = m.group(1)
        spec = m.group(2)
        if name not in all_fields:
            return m.group(0)
        raw = all_fields[name]
        if spec is not None:
            resolved = _apply_spec(raw, spec)
        elif raw is None:
            resolved = ""
        else:
            resolved = str(raw)
        return _sanitize_value(resolved)

    return _PLACEHOLDER_RE.sub(_replace, template)


def _item_value(item: object, field: str) -> str | int | None:
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field)


def scan_download_counts(
    library_items: dict,
    single_template: str,
    multi_template: str,
    download_dir: Path,
) -> dict[str, int]:
    """Count how many parts have already been downloaded for each library item.

    For each item, the appropriate filename template is rendered for every part
    and the resulting ``.mp4`` file path is checked for existence inside
    ``download_dir``.

    Args:
        library_items: Mapping of ``mylibrary_id`` to library item objects
            (from ``manager.library``).
        single_template: Filename template for single-part items.
        multi_template: Filename template for multi-part items.
        download_dir: Root directory where downloaded files are stored.

    Returns:
        A ``dict`` mapping ``content_id`` to the count of downloaded parts.
    """
    counts: dict[str, int] = {}
    for item in library_items.values():
        # Build fields dict matching LibraryItemResponse fields
        fields: dict[str, str | int | None] = {
            "mylibrary_id": _item_value(item, "mylibrary_id"),
            "content_id": _item_value(item, "content_id"),
            "title": _item_value(item, "title"),
            "content_type": _item_value(item, "content_type"),
            "parts": _item_value(item, "parts"),
            "javstash_id": _item_value(item, "javstash_id"),
            "javstash_studio_code": _item_value(item, "javstash_studio_code"),
        }
        content_id = str(fields["content_id"])
        parts = int(fields["parts"] or 0)

        # parts==0 is treated as a single part accessed via part index 0,
        # matching the DownloadModal convention.
        if parts == 0:
            rendered = render_template(single_template, fields, 0)
            counts[content_id] = int((download_dir / f"{rendered}.mp4").exists())
        elif parts == 1:
            rendered = render_template(single_template, fields, 1)
            counts[content_id] = int((download_dir / f"{rendered}.mp4").exists())
        else:
            total = parts
            found = sum(
                1
                for p in range(1, total + 1)
                if (
                    download_dir / f"{render_template(multi_template, fields, p)}.mp4"
                ).exists()
            )
            counts[content_id] = found

    return counts


async def rescan_and_store(app_state: "AppState") -> None:
    """Rescan the download directory and update ``app_state.download_counts``.

    No-op if no manager is authenticated. Runs the filesystem scan in a thread
    pool to avoid blocking the event loop.

    Args:
        app_state: The FastAPI ``app.state`` object. Must expose ``manager``,
            ``single_part_filename_template``, ``multi_part_filename_template``,
            and ``download_counts`` attributes.
    """
    from fanzadl_webui.dependencies import (  # noqa: PLC0415 - avoid circular import
        DOWNLOAD_DIR,
    )

    manager = app_state.manager
    if manager is None:
        return

    library_items: dict[int, object] = dict(get_all_items(LIBRARY_DB_PATH))
    library_items.update(manager.library)

    counts = await asyncio.to_thread(
        scan_download_counts,
        library_items,
        app_state.single_part_filename_template,
        app_state.multi_part_filename_template,
        DOWNLOAD_DIR,
    )
    app_state.download_counts = counts
