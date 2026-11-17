"""Eval API: the evals CLI uses /v1 (project API key); the dashboard reads with the admin token."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import ApiKeyProjectDep, SessionDep, SettingsDep, require_admin
from app.db.models import Dataset
from app.services import evals as evals_service
from app.services import projects as projects_service
from app.services.evals import DatasetIn

sdk_router = APIRouter(prefix="/v1", tags=["evals"])
admin_router = APIRouter(tags=["evals"], dependencies=[Depends(require_admin)])

NameParam = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[\w.\- ]+$")]


async def get_queue(request: Request, settings: SettingsDep):
    """ARQ pool, created once per app and reused."""
    pool = getattr(request.app.state, "arq", None)
    if pool is None:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        request.app.state.arq = pool
    return pool


QueueDep = Annotated[Any, Depends(get_queue)]


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    key: str
    input: Any
    expected: dict


class DatasetOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    items: list[ItemOut]


class RunIn(BaseModel):
    dataset_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    agent_version: str = Field(min_length=1, max_length=100)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    agent_version: str
    status: str
    summary: dict | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class RunListItem(RunOut):
    dataset_name: str


class ResultIn(BaseModel):
    item_id: uuid.UUID
    output: str | None = Field(default=None, max_length=50_000)
    error: str | None = Field(default=None, max_length=10_000)
    trace_id: uuid.UUID | None = None


class ResultOut(BaseModel):
    item: ItemOut
    trace_id: uuid.UUID | None
    output: str | None
    error: str | None
    scores: dict | None
    score: float | None
    latency_ms: float | None
    cost_usd: float | None


class RunDetail(RunOut):
    dataset_name: str
    results: list[ResultOut]


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


# ---------- SDK / CLI side (project API key) ----------


@sdk_router.put("/datasets/{name}", response_model=DatasetOut)
async def upsert_dataset(
    name: NameParam, body: DatasetIn, project: ApiKeyProjectDep, session: SessionDep
) -> DatasetOut:
    dataset, items = await evals_service.upsert_dataset(session, project.id, name, body)
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        items=[ItemOut.model_validate(i) for i in items],
    )


@sdk_router.post("/eval-runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(body: RunIn, project: ApiKeyProjectDep, session: SessionDep) -> RunOut:
    try:
        run = await evals_service.create_run(
            session, project.id, body.dataset_id, body.name, body.agent_version
        )
    except LookupError as exc:
        raise _not_found(exc) from exc
    return RunOut.model_validate(run)


@sdk_router.post("/eval-runs/{run_id}/results", status_code=status.HTTP_204_NO_CONTENT)
async def add_result(
    run_id: uuid.UUID, body: ResultIn, project: ApiKeyProjectDep, session: SessionDep
) -> None:
    try:
        run = await evals_service.get_run(session, project.id, run_id)
        await evals_service.add_result(
            session, run, body.item_id, body.output, body.error, body.trace_id
        )
    except LookupError as exc:
        raise _not_found(exc) from exc
    except evals_service.EvalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@sdk_router.post("/eval-runs/{run_id}/complete", response_model=RunOut)
async def complete_run(
    run_id: uuid.UUID, project: ApiKeyProjectDep, session: SessionDep, queue: QueueDep
) -> RunOut:
    """Stop accepting results and queue the run for scoring on the worker."""
    try:
        run = await evals_service.get_run(session, project.id, run_id)
        await evals_service.mark_scoring(session, run)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except evals_service.EvalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await queue.enqueue_job("score_eval_run", str(run.id))
    return RunOut.model_validate(run)


@sdk_router.get("/eval-runs/{run_id}", response_model=RunOut)
async def get_run_status(
    run_id: uuid.UUID, project: ApiKeyProjectDep, session: SessionDep
) -> RunOut:
    try:
        return RunOut.model_validate(await evals_service.get_run(session, project.id, run_id))
    except LookupError as exc:
        raise _not_found(exc) from exc


# ---------- Dashboard (admin token) ----------


async def _project_or_404(session, project_id: uuid.UUID) -> None:
    if await projects_service.get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")


@admin_router.get("/projects/{project_id}/eval-runs", response_model=list[RunListItem])
async def list_runs(project_id: uuid.UUID, session: SessionDep) -> list[RunListItem]:
    await _project_or_404(session, project_id)
    rows = await evals_service.list_runs(session, project_id)
    return [
        RunListItem(**RunOut.model_validate(run).model_dump(), dataset_name=name)
        for run, name in rows
    ]


@admin_router.get("/projects/{project_id}/eval-runs/{run_id}", response_model=RunDetail)
async def get_run(project_id: uuid.UUID, run_id: uuid.UUID, session: SessionDep) -> RunDetail:
    try:
        run = await evals_service.get_run(session, project_id, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    rows = await evals_service.run_results(session, run_id)
    dataset = await session.get(Dataset, run.dataset_id)
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        dataset_name=dataset.name,
        results=[
            ResultOut(
                item=ItemOut.model_validate(item),
                trace_id=r.trace_id if r else None,
                output=r.output if r else None,
                error=r.error if r else None,
                scores=r.scores if r else None,
                score=r.score if r else None,
                latency_ms=r.latency_ms if r else None,
                cost_usd=r.cost_usd if r else None,
            )
            for item, r in rows
        ],
    )
