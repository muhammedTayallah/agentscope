"""Batch ingestion of traces and spans sent by the SDK.

Everything is an upsert keyed by the SDK-generated id, so a retried batch is harmless
and a trace can be sent again when it finishes. Spans may arrive before their trace
(children finish first); the trace then gets a placeholder row that the real trace
data later fills in.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Span, Trace

MAX_BATCH = 500
PENDING_TRACE_NAME = "(pending)"


class _Item(BaseModel):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    start_time: AwareDatetime
    end_time: AwareDatetime | None = None
    status: Literal["ok", "error"] = "ok"
    error: str | None = Field(default=None, max_length=10_000)
    input: Any = None
    output: Any = None
    metadata: dict[str, Any] | None = None


class TraceIn(_Item):
    pass


class SpanIn(_Item):
    trace_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    kind: Literal["span", "llm", "tool"] = "span"
    model: str | None = Field(default=None, max_length=100)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class IngestBatch(BaseModel):
    traces: list[TraceIn] = Field(default_factory=list, max_length=MAX_BATCH)
    spans: list[SpanIn] = Field(default_factory=list, max_length=MAX_BATCH)


class ForeignIdError(Exception):
    """An id in the batch already belongs to another project."""


def _dedupe[T: _Item](items: Iterable[T]) -> list[T]:
    # Postgres can't upsert the same row twice in one statement; the last copy wins.
    return list({i.id: i for i in items}.values())


def _row(item: _Item, project_id: uuid.UUID, exclude: set[str] = frozenset()) -> dict:
    data = item.model_dump(exclude={"metadata", *exclude})
    return {**data, "meta": item.metadata, "project_id": project_id}


async def _owned_elsewhere(
    session: AsyncSession, model: type[Trace] | type[Span], ids: set[uuid.UUID], project_id
) -> bool:
    if not ids:
        return False
    stmt = select(model.id).where(model.id.in_(ids), model.project_id != project_id).limit(1)
    return (await session.execute(stmt)).first() is not None


async def ingest(session: AsyncSession, project_id: uuid.UUID, batch: IngestBatch) -> None:
    traces, spans = _dedupe(batch.traces), _dedupe(batch.spans)
    trace_ids = {t.id for t in traces} | {s.trace_id for s in spans}

    # Clients choose ids, so refuse ids another project already uses.
    if await _owned_elsewhere(session, Trace, trace_ids, project_id) or await _owned_elsewhere(
        session, Span, {s.id for s in spans}, project_id
    ):
        raise ForeignIdError

    if traces:
        stmt = insert(Trace).values([_row(t, project_id) for t in traces])
        cols = ["name", "start_time", "end_time", "status", "error", "input", "output", "metadata"]
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Trace.id],
                set_={c: stmt.excluded[c] for c in cols},
                where=Trace.project_id == stmt.excluded.project_id,
            )
        )

    # Placeholder rows for traces that only their spans have mentioned so far.
    first_start: dict[uuid.UUID, datetime] = {}
    for s in spans:
        first_start[s.trace_id] = min(first_start.get(s.trace_id, s.start_time), s.start_time)
    sent = {t.id for t in traces}
    placeholders = [
        {"id": tid, "project_id": project_id, "name": PENDING_TRACE_NAME, "start_time": start}
        | {"status": "ok"}
        for tid, start in first_start.items()
        if tid not in sent
    ]
    if placeholders:
        await session.execute(insert(Trace).values(placeholders).on_conflict_do_nothing())

    if spans:
        stmt = insert(Span).values([_row(s, project_id) for s in spans])
        cols = [c.name for c in Span.__table__.columns if c.name not in ("id", "project_id")]
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Span.id],
                set_={c: stmt.excluded[c] for c in cols},
                where=Span.project_id == stmt.excluded.project_id,
            )
        )

    await session.commit()
