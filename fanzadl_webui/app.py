import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fanzadl import FanzaDLManager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from .dependencies import IMAGE_CACHE_DIR, settings
from .routes import download, images, library, refresh_library, streams, url


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        app.state.http_client = client
        app.state.jobs: dict = {}
        app.state.queues: dict = {}
        app.state.manager = FanzaDLManager(
            settings.fanza_email, settings.fanza_password
        )
        asyncio.create_task(
            images.precache_all(app.state.manager, client, IMAGE_CACHE_DIR)
        )
        yield


app = FastAPI(lifespan=lifespan)

app.include_router(library.router, prefix="/api")
app.include_router(refresh_library.router, prefix="/api")
app.include_router(url.router, prefix="/api")
app.include_router(streams.router, prefix="/api")
app.include_router(download.router, prefix="/api")
app.include_router(images.router, prefix="/api")

_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _dist.is_dir():

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope: Scope) -> Response:
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    app.mount("/", SPAStaticFiles(directory=str(_dist), html=True), name="spa")
