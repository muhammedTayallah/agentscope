from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException  # what StaticFiles raises (FastAPI's is a subclass)

from app.api.evals import admin_router as evals_admin_router
from app.api.evals import sdk_router as evals_sdk_router
from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.metrics import router as metrics_router
from app.api.projects import router as projects_router
from app.api.projects import sdk_router
from app.api.traces import router as traces_router
from app.core.config import Settings, get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """With RUN_WORKER=true the ARQ worker runs inside this process (hosts without a
    separate worker service, e.g. Render's free tier). Otherwise run it on its own."""
    if not get_settings().run_worker:
        yield
        return
    from app.workers.main import start_in_process

    stop = await start_in_process()
    try:
        yield
    finally:
        await stop()


def create_app() -> FastAPI:
    """The API alone (development, tests, and what production mounts at /api)."""
    app = FastAPI(title="AgentScope", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        health_router,
        projects_router,
        sdk_router,
        ingest_router,
        traces_router,
        metrics_router,
        evals_sdk_router,
        evals_admin_router,
    ):
        app.include_router(router)
    return app


class SpaFiles(StaticFiles):
    """Static files, falling back to index.html so client-side routes survive a reload."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def create_server(settings: Settings) -> FastAPI:
    """Production (STATIC_DIR set): the API under /api, as the UI calls it, and the built
    UI at /. Without STATIC_DIR: just the API at /, as in development."""
    api = create_app()
    if not settings.static_dir:
        return api
    root = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    root.mount("/api", api)
    root.mount("/", SpaFiles(directory=settings.static_dir, html=True))
    return root


app = create_server(get_settings())
