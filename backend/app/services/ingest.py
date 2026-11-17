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
from sqlalchemy import text
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


def _row(item: _Item, project_id: uuid.UUID) -> dict:
    # Core-table keys: the JSON column is named "metadata" (the ORM attribute is `meta`).
    return item.model_dump() | {"project_id": project_id}


# Built once so SQLAlchemy compiles them once; rows go in as executemany parameters,
# which it batches into one multi-row INSERT. (Putting rows into .values([...]) made
# every request compile a fresh ~150-parameter statement: the main CPU cost under load.)
_TRACES = Trace.__table__
_SPANS = Span.__table__
_trace_insert = insert(_TRACES)
UPSERT_TRACES = _trace_insert.on_conflict_do_update(
    index_elements=[_TRACES.c.id],
    set_={
        c: _trace_insert.excluded[c]
        for c in (
            "name",
            "start_time",
            "end_time",
            "status",
            "error",
            "input",
            "output",
            "metadata",
        )
    },
    where=_TRACES.c.project_id == _trace_insert.excluded.project_id,
)
INSERT_PLACEHOLDER_TRACES = insert(_TRACES).on_conflict_do_nothing()
_span_insert = insert(_SPANS)
UPSERT_SPANS = _span_insert.on_conflict_do_update(
    index_elements=[_SPANS.c.id],
    set_={
        c.name: _span_insert.excluded[c.name]
        for c in _SPANS.c
        if c.name not in ("id", "project_id")
    },
    where=_SPANS.c.project_id == _span_insert.excluded.project_id,
)
# One round trip for both ownership checks.
OWNED_ELSEWHERE = text(
    "SELECT EXISTS (SELECT 1 FROM traces WHERE id = ANY(:trace_ids) AND project_id <> :project_id)"
    " OR EXISTS (SELECT 1 FROM spans WHERE id = ANY(:span_ids) AND project_id <> :project_id)"
)


async def ingest(session: AsyncSession, project_id: uuid.UUID, batch: IngestBatch) -> None:
    # Telemetry trade-off: do not wait for the WAL flush. A Postgres crash can lose the last
    # moments of acknowledged ingests (never corrupt anything); the commit stops costing a
    # disk flush (~200 ms on WSL). Only this transaction; other writes stay fully durable.
    await session.execute(text("SET LOCAL synchronous_commit = off"))
    traces, spans = _dedupe(batch.traces), _dedupe(batch.spans)
    trace_ids = {t.id for t in traces} | {s.trace_id for s in spans}

    # Clients choose ids, so refuse ids another project already uses.
    params = {
        "trace_ids": list(trace_ids),
        "span_ids": [s.id for s in spans],
        "project_id": project_id,
    }
    if (await session.execute(OWNED_ELSEWHERE, params)).scalar_one():
        raise ForeignIdError

    if traces:
        await session.execute(UPSERT_TRACES, [_row(t, project_id) for t in traces])

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
        await session.execute(INSERT_PLACEHOLDER_TRACES, placeholders)

    if spans:
        await session.execute(UPSERT_SPANS, [_row(s, project_id) for s in spans])

    await session.commit()
