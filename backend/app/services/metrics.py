"""Project metrics for the dashboard: volume, errors, latency percentiles, tokens, cost.

Runs are counted by trace start time; tokens and cost by span start time. Buckets are
UTC hours or days. Latency is trace duration (end - start); unfinished traces are
counted as runs but excluded from latency.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pricing import cost_usd
from app.db.models import Span, Trace

Bucket = Literal["hour", "day"]
STEP = {"hour": timedelta(hours=1), "day": timedelta(days=1)}


@dataclass
class ModelUsage:
    model: str | None
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


@dataclass
class Point:
    start: datetime
    runs: int = 0
    errors: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None
    cost_usd: float = 0.0


@dataclass
class Metrics:
    runs: int
    errors: int
    error_rate: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    input_tokens: int
    output_tokens: int
    # Cost of priced models only; unpriced_models lists the rest.
    cost_usd: float
    unpriced_models: list[str]
    by_model: list[ModelUsage]
    series: list[Point] = field(default_factory=list)


def _duration_ms():
    return func.extract("epoch", Trace.end_time - Trace.start_time) * 1000


def _pct(q: float):
    return func.percentile_cont(q).within_group(_duration_ms())


def _bucket(col, bucket: Bucket):
    # Truncate in UTC regardless of the database session's time zone.
    return func.date_trunc(bucket, func.timezone("UTC", col))


def floor_to(dt: datetime, bucket: Bucket) -> datetime:
    dt = dt.astimezone(UTC)
    dt = dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0) if bucket == "day" else dt


async def project_metrics(
    session: AsyncSession,
    project_id: uuid.UUID,
    start: datetime,
    end: datetime,
    bucket: Bucket,
    prices: dict[str, tuple[float, float]],
) -> Metrics:
    in_traces = (Trace.project_id == project_id, Trace.start_time >= start, Trace.start_time < end)
    in_spans = (Span.project_id == project_id, Span.start_time >= start, Span.start_time < end)
    error_count = func.count().filter(Trace.status == "error")
    finished = Trace.end_time.is_not(None)

    summary = (
        await session.execute(
            select(
                func.count(),
                error_count,
                _pct(0.5).filter(finished),
                _pct(0.95).filter(finished),
                _pct(0.99).filter(finished),
            ).where(*in_traces)
        )
    ).one()

    trace_rows = (
        await session.execute(
            select(
                _bucket(Trace.start_time, bucket).label("b"),
                func.count(),
                error_count,
                _pct(0.5).filter(finished),
                _pct(0.95).filter(finished),
            )
            .where(*in_traces)
            .group_by(literal_column("b"))
        )
    ).all()

    span_rows = (
        await session.execute(
            select(
                _bucket(Span.start_time, bucket).label("b"),
                Span.model,
                func.count().filter(Span.kind == "llm"),
                func.coalesce(func.sum(Span.input_tokens), 0),
                func.coalesce(func.sum(Span.output_tokens), 0),
            )
            .where(*in_spans)
            .where(
                or_(
                    Span.kind == "llm",
                    Span.input_tokens.is_not(None),
                    Span.output_tokens.is_not(None),
                )
            )
            .group_by(literal_column("b"), Span.model)
        )
    ).all()

    # Empty buckets are zero, not missing, so the time axis is continuous.
    points: dict[datetime, Point] = {}
    t = floor_to(start, bucket)
    while t < end:
        points[t] = Point(start=t)
        t += STEP[bucket]
    for b, runs, errors, p50, p95 in trace_rows:
        p = points.setdefault(b.replace(tzinfo=UTC), Point(start=b.replace(tzinfo=UTC)))
        p.runs, p.errors, p.p50_ms, p.p95_ms = runs, int(errors), p50, p95

    usage: dict[str | None, ModelUsage] = {}
    for b, model, calls, tin, tout in span_rows:
        u = usage.setdefault(model, ModelUsage(model, 0, 0, 0, None))
        u.calls += calls
        u.input_tokens += tin
        u.output_tokens += tout
        if (c := cost_usd(prices, model, tin, tout)) is not None:
            u.cost_usd = (u.cost_usd or 0.0) + c
            bucket_start = b.replace(tzinfo=UTC)
            points.setdefault(bucket_start, Point(start=bucket_start)).cost_usd += c

    runs, errors, p50, p95, p99 = summary
    by_model = sorted(usage.values(), key=lambda u: (-(u.cost_usd or 0), -u.input_tokens))
    return Metrics(
        runs=runs,
        errors=int(errors),
        error_rate=errors / runs if runs else None,
        p50_ms=p50,
        p95_ms=p95,
        p99_ms=p99,
        input_tokens=sum(u.input_tokens for u in by_model),
        output_tokens=sum(u.output_tokens for u in by_model),
        cost_usd=sum(u.cost_usd or 0.0 for u in by_model),
        unpriced_models=sorted(
            u.model or "(no model)" for u in by_model if u.cost_usd is None and u.calls
        ),
        by_model=by_model,
        series=sorted(points.values(), key=lambda p: p.start),
    )
