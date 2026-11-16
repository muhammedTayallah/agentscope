from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.api.deps import SessionDep, SettingsDep
from app.services.health import check_database, check_redis

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    database: Literal["ok", "error"]
    redis: Literal["ok", "error"]


@router.get("/health", response_model=HealthResponse)
async def health(response: Response, session: SessionDep, settings: SettingsDep) -> HealthResponse:
    db_ok = await check_database(session)
    redis_ok = await check_redis(settings.redis_url)
    if not (db_ok and redis_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="healthy" if db_ok and redis_ok else "unhealthy",
        database="ok" if db_ok else "error",
        redis="ok" if redis_ok else "error",
    )
