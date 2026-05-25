from typing import Annotated, Literal

from fanzadl import FanzaDLManager
from fastapi import APIRouter, Depends

from fanzadl_webui.dependencies import get_manager
from fanzadl_webui.routes._utils import get_quality_obj

router = APIRouter(prefix="/url")


@router.get("/")
def get_url(
    video_id: int,
    manager: Annotated[FanzaDLManager, Depends(get_manager)],
    part: int | None = None,
    quality: Literal["highest"] = "highest",  # noqa: ARG001
) -> str | list[str]:
    quality_obj = get_quality_obj(video_id, manager)
    if part is not None:
        return quality_obj.get_url(part)
    return quality_obj.get_all_urls()
