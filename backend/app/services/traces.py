"""Read side for the dashboard: runs list and run detail."""

import uuid
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Span, Trace


async def list_traces(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    q: str | None = None,
    status: Literal["ok", "error"] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Row], int]:
    """Newest runs first, with span count and token totals. Returns (rows, total)."""
    filters = [Trace.project_id == project_id]
    if q:
        # Escape LIKE wildcards so the search is a plain substring match.
        pattern = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Trace.name.ilike(f"%{pattern}%", escape="\\"))
    if status:
        filters.append(Trace.status == status)

    totals = (
        select(
            Span.trace_id,
            func.count().label("span_count"),
            func.coalesce(func.sum(Span.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(Span.output_tokens), 0).label("output_tokens"),
        )
        # shortcut: aggregates the whole project's spans per request; fine at demo scale,
        # revisit (per-page lateral join or stored counters) if the Phase 7 load test says so.
        .where(Span.project_id == project_id)
        .group_by(Span.trace_id)
        .subquery()
    )
    # shortcut: offset paging gets slow deep into large tables; switch to keyset paging
    # on (start_time, id) if Phase 7 shows it matters.
    stmt = (
        select(
            Trace,
            func.coalesce(totals.c.span_count, 0).label("span_count"),
            func.coalesce(totals.c.input_tokens, 0).label("input_tokens"),
            func.coalesce(totals.c.output_tokens, 0).label("output_tokens"),
        )
        .outerjoin(totals, totals.c.trace_id == Trace.id)
        .where(*filters)
        .order_by(Trace.start_time.desc(), Trace.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    total = (
        await session.execute(select(func.count()).select_from(Trace).where(*filters))
    ).scalar_one()
    return rows, total


async def get_trace(
    session: AsyncSession, project_id: uuid.UUID, trace_id: uuid.UUID
) -> tuple[Trace, Sequence[Span]] | None:
    trace = await session.get(Trace, trace_id)
    if trace is None or trace.project_id != project_id:
        return None
    spans = (
        (
            await session.execute(
                select(Span)
                .where(Span.trace_id == trace_id, Span.project_id == project_id)
                .order_by(Span.start_time, Span.id)
            )
        )
        .scalars()
        .all()
    )
    return trace, spans
