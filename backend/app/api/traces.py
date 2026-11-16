"""Dashboard read API for runs (traces) and their spans. Admin token required."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import SessionDep, require_admin
from app.services import projects as projects_service
from app.services import traces as traces_service

router = APIRouter(
    prefix="/projects/{project_id}/traces", tags=["traces"], dependencies=[Depends(require_admin)]
)


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    name: str
    status: str
    error: str | None
    start_time: datetime
    end_time: datetime | None


class TraceSummary(_Base):
    span_count: int
    input_tokens: int
    output_tokens: int


class TracePage(BaseModel):
    items: list[TraceSummary]
    total: int


class SpanOut(_Base):
    parent_id: uuid.UUID | None
    kind: str
    input: Any
    output: Any
    metadata: dict | None = Field(validation_alias="meta")
    model: str | None
    input_tokens: int | None
    output_tokens: int | None


class TraceDetail(_Base):
    input: Any
    output: Any
    metadata: dict | None = Field(validation_alias="meta")
    spans: list[SpanOut]


async def _require_project(session, project_id: uuid.UUID) -> None:
    if await projects_service.get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")


@router.get("", response_model=TracePage)
async def list_traces(
    project_id: uuid.UUID,
    session: SessionDep,
    q: str | None = Query(None, max_length=200, description="Name contains (case-insensitive)"),
    status_: Literal["ok", "error"] | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TracePage:
    await _require_project(session, project_id)
    rows, total = await traces_service.list_traces(
        session, project_id, q=q, status=status_, limit=limit, offset=offset
    )
    items = [
        TraceSummary(
            **_Base.model_validate(trace).model_dump(),
            span_count=span_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        for trace, span_count, input_tokens, output_tokens in rows
    ]
    return TracePage(items=items, total=total)


@router.get("/{trace_id}", response_model=TraceDetail)
async def get_trace(project_id: uuid.UUID, trace_id: uuid.UUID, session: SessionDep) -> TraceDetail:
    found = await traces_service.get_trace(session, project_id, trace_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found.")
    trace, spans = found
    return TraceDetail(
        **_Base.model_validate(trace).model_dump(),
        input=trace.input,
        output=trace.output,
        metadata=trace.meta,
        spans=[SpanOut.model_validate(s) for s in spans],
    )
