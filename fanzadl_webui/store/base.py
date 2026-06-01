import contextlib
import os
from pathlib import Path


def try_write(
    data: bytes,
    *,
    descriptor: int,
    temp_path: os.PathLike | str,
    orig_path: os.PathLike | str,
    set_chmod: bool = False,
) -> None:
    temp_path_f = Path(temp_path)
    orig_path_f = Path(orig_path)

    try:
        with os.fdopen(descriptor, "wb") as f:
            f.write(data)

        if set_chmod:
            temp_path_f.chmod(0o600)

        temp_path_f.replace(orig_path_f)
    except Exception:
        with contextlib.suppress(OSError):
            temp_path_f.unlink()
        raise
