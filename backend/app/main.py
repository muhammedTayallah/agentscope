from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.projects import router as projects_router
from app.api.projects import sdk_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="AgentScope")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(sdk_router)
    app.include_router(ingest_router)
    return app


app = create_app()
