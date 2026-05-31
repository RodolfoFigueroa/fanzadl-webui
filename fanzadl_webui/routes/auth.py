import asyncio
import logging
from typing import Annotated

import requests
from fanzadl.exceptions import MalformedEmailError, WrongCredentialsError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from fanzadl_webui.dependencies import (
    IMAGE_CACHE_DIR,
    LIBRARY_DB_PATH,
    TOKEN_STORE_PATH,
    get_app_state,
)
from fanzadl_webui.library_db import delete_all, save_library_db
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes import images
from fanzadl_webui.routes.download import cancel_active_jobs
from fanzadl_webui.state import AppState
from fanzadl_webui.token_store import delete_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.get("/status")
def auth_status(
    app_state: Annotated[AppState, Depends(get_app_state)],
) -> dict[str, bool]:
    return {"authenticated": app_state.manager is not None}


@router.post("/login")
async def login(
    body: LoginRequest,
    app_state: Annotated[AppState, Depends(get_app_state)],
) -> dict[str, str]:
    async with app_state.login_lock:
        if app_state.manager is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Already logged in",
            )

        try:
            manager = await asyncio.to_thread(
                PersistingFanzaDLManager,
                email=body.email,
                password=body.password,
                javstash_api_key=app_state.javstash_api_key,
                save_fn=app_state.save_fn,
                library_db_path=LIBRARY_DB_PATH,
                auto_populate_library=False,
            )
            await asyncio.to_thread(manager.update_library)
        except MalformedEmailError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email address.",
            ) from exc
        except WrongCredentialsError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
            ) from exc
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not connect to the authentication service.",
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error during login: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Authentication failed. Please try again.",
            ) from exc

        app_state.manager = manager
        app_state.save_fn(manager.user_id, manager.refresh_token)

    await asyncio.to_thread(images.purge_stale, manager, IMAGE_CACHE_DIR)

    async def _warm_and_save() -> None:
        await warm_all_details(manager)
        _new_ids = set(manager.library) - manager._ids_restored_from_cache  # noqa: SLF001
        await asyncio.to_thread(
            save_library_db, LIBRARY_DB_PATH, manager.user_id, manager, _new_ids
        )
        manager._ids_restored_from_cache = set()  # noqa: SLF001

    for coro in (
        images.precache_all(manager, app_state.http_client, IMAGE_CACHE_DIR),
        _warm_and_save(),
    ):
        task = asyncio.create_task(coro)
        app_state.background_tasks.add(task)
        task.add_done_callback(app_state.background_tasks.discard)

    return {"status": "ok"}


@router.post("/logout")
async def logout(
    app_state: Annotated[AppState, Depends(get_app_state)],
) -> dict[str, str]:
    for task in list(app_state.background_tasks):
        task.cancel()
    app_state.background_tasks.clear()

    jobs = app_state.jobs
    queues = app_state.queues
    condition = app_state.download_slot_condition

    await cancel_active_jobs(jobs, queues, condition)

    jobs.clear()
    queues.clear()

    delete_tokens(TOKEN_STORE_PATH)
    delete_all(LIBRARY_DB_PATH)
    app_state.manager = None

    return {"status": "ok"}
