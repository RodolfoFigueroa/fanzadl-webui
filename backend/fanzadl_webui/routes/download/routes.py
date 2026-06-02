from pathlib import Path
from typing import Annotated

from fanzadl_webui.dependencies import DOWNLOAD_DIR, get_app_state, require_api_key
from fanzadl_webui.download import (
    dispatch_download,
    register_job,
)
from fanzadl_webui.models import DownloadJob
from fanzadl_webui.state import AppState
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

router = APIRouter(prefix="/download", tags=["Downloads"])


class DownloadRequest(BaseModel):
    output_name: str
    video_id: int
    part: int
    stream_index: int
    content_id: str | None = None


class FilenameCheckResponse(BaseModel):
    file_exists: bool


@router.get("/check-filename/")
def check_filename(
    _: Annotated[None, Depends(require_api_key)],
    name: Annotated[str, Query(..., min_length=1)],
) -> FilenameCheckResponse:
    """Check whether an output file with the given name already exists.

    Args:
        name: Filename stem (without extension) to check inside the download
            directory. Must be at least one character.

    Returns:
        A FilenameCheckResponse indicating whether ``{name}.mp4`` exists.
    """
    path = DOWNLOAD_DIR / f"{name}.mp4"
    if not path.is_relative_to(DOWNLOAD_DIR):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename",
        )
    return FilenameCheckResponse(file_exists=path.exists())


@router.post("/")
async def start_download(
    body: DownloadRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict[str, str]:
    """Create a download job and dispatch it as a background task.

    Validates that the resolved output path stays within the download directory
    (path-traversal guard), creates any required subdirectories, registers a new
    DownloadJob, and fires off ``_run_download`` as an asyncio background task.

    Args:
        body: Download parameters including video ID, part, stream index, and
            output name.
        app_state: Injected application state.

    Returns:
        A dict containing the ``job_id`` of the newly created job.

    Raises:
        HTTPException: 400 if the resolved output path escapes the download
            directory.
    """
    output_name_path = Path(body.output_name)
    resolved = (DOWNLOAD_DIR / body.output_name).resolve()
    if not resolved.is_relative_to(DOWNLOAD_DIR.resolve()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid output path"
        )
    save_dir_path = DOWNLOAD_DIR / output_name_path.parent
    save_dir_path.mkdir(parents=True, exist_ok=True)
    save_dir = str(save_dir_path)
    save_name = output_name_path.name

    job = DownloadJob.create(output_name=body.output_name, content_id=body.content_id)
    register_job(job, app_state)
    dispatch_download(
        job,
        body.video_id,
        body.part,
        body.stream_index,
        save_dir,
        save_name,
        app_state,
    )

    return {"job_id": job.job_id}
