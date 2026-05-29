import asyncio

import requests
from fanzadl.exceptions import MalformedEmailError, WrongCredentialsError
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from fanzadl_webui.dependencies import IMAGE_CACHE_DIR, TOKEN_STORE_PATH
from fanzadl_webui.manager import PersistingFanzaDLManager, warm_all_details
from fanzadl_webui.routes import images
from fanzadl_webui.routes.download import cancel_active_jobs
from fanzadl_webui.token_store import delete_tokens

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.get("/status")
def auth_status(request: Request) -> dict[str, bool]:
    return {"authenticated": request.app.state.manager is not None}


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> dict[str, str]:
    async with request.app.state.login_lock:
        if request.app.state.manager is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Already logged in",
            )

        try:
            manager = await asyncio.to_thread(
                PersistingFanzaDLManager,
                email=body.email,
                password=body.password,
                javstash_api_key=request.app.state.javstash_api_key,
                save_fn=request.app.state.save_fn,
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
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Authentication failed. Please try again.",
            ) from exc

        request.app.state.manager = manager
        request.app.state.save_fn(manager.user_id, manager.refresh_token)

    await asyncio.to_thread(images.purge_stale, manager, IMAGE_CACHE_DIR)
    for coro in (
        images.precache_all(manager, request.app.state.http_client, IMAGE_CACHE_DIR),
        warm_all_details(manager),
    ):
        task = asyncio.create_task(coro)
        request.app.state.background_tasks.add(task)
        task.add_done_callback(request.app.state.background_tasks.discard)

    return {"status": "ok"}


@router.post("/logout")
async def logout(request: Request) -> dict[str, str]:
    for task in list(request.app.state.background_tasks):
        task.cancel()
    request.app.state.background_tasks.clear()

    jobs = request.app.state.jobs
    queues = request.app.state.queues
    condition = request.app.state.download_slot_condition

    await cancel_active_jobs(jobs, queues, condition)

    jobs.clear()
    queues.clear()

    delete_tokens(TOKEN_STORE_PATH)
    request.app.state.manager = None

    return {"status": "ok"}
