import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime, BaseModel

from app.api.deps import SessionDep, SettingsDep, require_admin
from app.services import metrics as metrics_service
from app.services import projects as projects_service

router = APIRouter(tags=["metrics"], dependencies=[Depends(require_admin)])

MAX_BUCKETS = 1000


class ModelUsageOut(BaseModel):
    model: str | None
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class PointOut(BaseModel):
    start: datetime
    runs: int
    errors: int
    p50_ms: float | None
    p95_ms: float | None
    cost_usd: float


class MetricsOut(BaseModel):
    start: datetime
    end: datetime
    bucket: Literal["hour", "day"]
    runs: int
    errors: int
    error_rate: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    unpriced_models: list[str]
    by_model: list[ModelUsageOut]
    series: list[PointOut]


@router.get("/projects/{project_id}/metrics", response_model=MetricsOut)
async def get_metrics(
    project_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    start: Annotated[AwareDatetime | None, Query(description="Default: end - 7 days")] = None,
    end: Annotated[AwareDatetime | None, Query(description="Default: now")] = None,
    bucket: Annotated[
        Literal["hour", "day"] | None,
        Query(description="Default: hour for windows up to 2 days, else day"),
    ] = None,
) -> MetricsOut:
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=7)
    if start >= end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start must be before end.")
    bucket = bucket or ("hour" if end - start <= timedelta(days=2) else "day")
    if (end - start) / metrics_service.STEP[bucket] > MAX_BUCKETS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Too many buckets; use a larger bucket."
        )
    if await projects_service.get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")

    m = await metrics_service.project_metrics(
        session, project_id, start, end, bucket, settings.all_prices()
    )
    return MetricsOut(start=start, end=end, bucket=bucket, **asdict(m))
