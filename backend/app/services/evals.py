"""Datasets and eval runs.

Flow: a client (evals CLI) upserts a dataset, opens an eval run, runs its agent on
every item locally (traced as usual) and posts each output with its trace id, then
completes the run. Completing enqueues `score_run` on the ARQ worker, which scores
every result and writes a summary.
"""

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.pricing import cost_usd
from app.db.models import Dataset, DatasetItem, EvalResult, EvalRun, Span, Trace
from app.services.judge import Judge

logger = logging.getLogger(__name__)

PASS_SCORE = 0.8  # an item "passes" when its mean score reaches this


class ItemIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    input: Any
    expected: dict[str, Any] = Field(default_factory=dict)


class DatasetIn(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    items: list[ItemIn] = Field(min_length=1, max_length=1000)


class EvalError(Exception):
    """A request that conflicts with the run's state; message is safe to show."""


# ---------- Datasets and runs ----------


async def upsert_dataset(
    session: AsyncSession, project_id: uuid.UUID, name: str, body: DatasetIn
) -> tuple[Dataset, list[DatasetItem]]:
    """Create or update a dataset; items are upserted by key (never deleted, so old
    results keep their item)."""
    stmt = insert(Dataset).values(
        id=uuid.uuid4(), project_id=project_id, name=name, description=body.description
    )
    dataset_id = (
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_datasets_project_name",
                set_={"description": stmt.excluded.description},
            ).returning(Dataset.id)
        )
    ).scalar_one()
    items = {i.key: i for i in body.items}  # last copy of a duplicate key wins
    stmt = insert(DatasetItem).values(
        [
            {"id": uuid.uuid4(), "dataset_id": dataset_id, "key": k, "input": i.input}
            | {"expected": i.expected}
            for k, i in items.items()
        ]
    )
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_dataset_items_key",
            set_={"input": stmt.excluded.input, "expected": stmt.excluded.expected},
        )
    )
    await session.commit()
    dataset = await session.get(Dataset, dataset_id)
    return dataset, await dataset_items(session, dataset_id)


async def dataset_items(session: AsyncSession, dataset_id: uuid.UUID) -> list[DatasetItem]:
    rows = await session.execute(
        select(DatasetItem).where(DatasetItem.dataset_id == dataset_id).order_by(DatasetItem.key)
    )
    return list(rows.scalars())


async def create_run(
    session: AsyncSession, project_id: uuid.UUID, dataset_id: uuid.UUID, name: str, version: str
) -> EvalRun:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None or dataset.project_id != project_id:
        raise LookupError("Dataset not found.")
    run = EvalRun(project_id=project_id, dataset_id=dataset_id, name=name, agent_version=version)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID) -> EvalRun:
    run = await session.get(EvalRun, run_id)
    if run is None or run.project_id != project_id:
        raise LookupError("Eval run not found.")
    return run


async def add_result(
    session: AsyncSession,
    run: EvalRun,
    item_id: uuid.UUID,
    output: str | None,
    error: str | None,
    trace_id: uuid.UUID | None,
) -> None:
    if run.status != "running":
        raise EvalError(f"Eval run is {run.status}; results can no longer be added.")
    item = await session.get(DatasetItem, item_id)
    if item is None or item.dataset_id != run.dataset_id:
        raise LookupError("Item is not in this run's dataset.")
    stmt = insert(EvalResult).values(
        id=uuid.uuid4(),
        eval_run_id=run.id,
        item_id=item_id,
        output=output,
        error=error,
        trace_id=trace_id,
    )
    await session.execute(
        stmt.on_conflict_do_update(  # re-posting an item replaces its result
            constraint="uq_eval_results_item",
            set_={c: stmt.excluded[c] for c in ("output", "error", "trace_id")},
        )
    )
    await session.commit()


async def mark_scoring(session: AsyncSession, run: EvalRun) -> None:
    if run.status != "running":
        raise EvalError(f"Eval run is already {run.status}.")
    run.status = "scoring"
    await session.commit()


async def list_runs(session: AsyncSession, project_id: uuid.UUID) -> Sequence[tuple]:
    rows = await session.execute(
        select(EvalRun, Dataset.name)
        .join(Dataset, Dataset.id == EvalRun.dataset_id)
        .where(EvalRun.project_id == project_id)
        .order_by(EvalRun.created_at.desc())
        .limit(200)
    )
    return rows.all()


async def run_results(session: AsyncSession, run_id: uuid.UUID) -> Sequence[tuple]:
    """(item, result or None) for every item of the run's dataset, by item key."""
    run = await session.get(EvalRun, run_id)
    rows = await session.execute(
        select(DatasetItem, EvalResult)
        .outerjoin(
            EvalResult,
            (EvalResult.item_id == DatasetItem.id) & (EvalResult.eval_run_id == run_id),
        )
        .where(DatasetItem.dataset_id == run.dataset_id)
        .order_by(DatasetItem.key)
    )
    return rows.all()


# ---------- Scoring (runs on the ARQ worker) ----------


def score_contains(output: str, phrases: list[str]) -> dict:
    missing = [p for p in phrases if p.lower() not in output.lower()]
    found = len(phrases) - len(missing)
    reason = "all expected phrases present" if not missing else f"missing: {', '.join(missing)}"
    return {"score": found / len(phrases), "reason": reason}


def score_tools(called: list[str], expected: list[str]) -> dict:
    missing = [t for t in expected if t not in called]
    reason = f"called: {', '.join(called) or 'none'}" + (
        f"; missing: {', '.join(missing)}" if missing else ""
    )
    return {"score": (len(expected) - len(missing)) / len(expected), "reason": reason}


def question_text(item_input: Any) -> str:
    if isinstance(item_input, dict) and isinstance(item_input.get("question"), str):
        return item_input["question"]
    return item_input if isinstance(item_input, str) else json.dumps(item_input)


async def _trace_facts(
    session: AsyncSession, project_id: uuid.UUID, trace_id: uuid.UUID | None, prices
) -> tuple[list[str], float | None, float | None]:
    """Tools called (in order), trace latency and priced cost, from the item's trace."""
    if trace_id is None:
        return [], None, None
    trace = await session.get(Trace, trace_id)
    if trace is None or trace.project_id != project_id:
        return [], None, None
    spans = (
        (
            await session.execute(
                select(Span)
                .where(Span.trace_id == trace_id, Span.project_id == project_id)
                .order_by(Span.start_time)
            )
        )
        .scalars()
        .all()
    )
    tools = [s.name for s in spans if s.kind == "tool"]
    latency = (trace.end_time - trace.start_time).total_seconds() * 1000 if trace.end_time else None
    costs = [
        cost_usd(prices, s.model, s.input_tokens or 0, s.output_tokens or 0)
        for s in spans
        if s.kind == "llm"
    ]
    cost = sum(c for c in costs if c is not None) if any(c is not None for c in costs) else None
    return tools, latency, cost


async def _judge(judge: Judge | None, q: str, ref: str, out: str) -> dict:
    if judge is None:
        return {"score": None, "reason": "no judge configured (missing API key)"}
    try:
        score, reason = await judge.grade(q, ref, out)
        return {"score": score, "reason": reason}
    except Exception as exc:  # one failed grade must not sink the whole run
        logger.warning("Judge failed: %s", exc)
        return {"score": None, "reason": f"judge failed: {type(exc).__name__}: {exc}"[:300]}


async def score_run(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    judge: Judge | None,
    prices: dict[str, tuple[float, float]],
) -> None:
    async with factory() as session:
        run = await session.get(EvalRun, run_id)
        if run is None or run.status != "scoring":
            return
        try:
            rows = [(i, r) for i, r in await run_results(session, run_id) if r is not None]

            async def score_one(item: DatasetItem, result: EvalResult) -> None:
                exp = item.expected or {}
                tools, latency, cost = await _trace_facts(
                    session, run.project_id, result.trace_id, prices
                )
                result.latency_ms, result.cost_usd = latency, cost
                scores: dict[str, dict] = {}
                if result.error or result.output is None:
                    reason = f"agent failed: {result.error or 'no output'}"[:300]
                    for name in ("contains", "tools", "judge"):
                        if name == "judge" and "answer" not in exp:
                            continue
                        if name != "judge" and not exp.get(name):
                            continue
                        scores[name] = {"score": 0.0, "reason": reason}
                else:
                    if exp.get("contains"):
                        scores["contains"] = score_contains(result.output, exp["contains"])
                    if exp.get("tools"):
                        scores["tools"] = score_tools(tools, exp["tools"])
                    if exp.get("answer"):
                        scores["judge"] = await _judge(
                            judge, question_text(item.input), exp["answer"], result.output
                        )
                result.scores = scores
                numbers = [s["score"] for s in scores.values() if s["score"] is not None]
                result.score = mean(numbers) if numbers else None

            for item, result in rows:
                await score_one(item, result)
            run.summary = summarize([r for _, r in rows], await _item_count(session, run))
            run.status = "completed"
        except Exception as exc:
            logger.exception("Scoring failed for eval run %s", run_id)
            await session.rollback()
            run = await session.get(EvalRun, run_id)
            run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"[:1000]
        run.completed_at = datetime.now(UTC)
        await session.commit()


async def _item_count(session: AsyncSession, run: EvalRun) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(DatasetItem)
            .where(DatasetItem.dataset_id == run.dataset_id)
        )
    ).scalar_one()


def summarize(results: list[EvalResult], dataset_size: int) -> dict:
    per_scorer: dict[str, list[float]] = {}
    for r in results:
        for name, s in (r.scores or {}).items():
            if s["score"] is not None:
                per_scorer.setdefault(name, []).append(s["score"])
    scored = [r.score for r in results if r.score is not None]
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    return {
        "items": dataset_size,
        "answered": len(results),
        "errors": sum(1 for r in results if r.error),
        "score": mean(scored) if scored else None,
        "pass_rate": sum(s >= PASS_SCORE for s in scored) / len(scored) if scored else None,
        "scorers": {k: mean(v) for k, v in sorted(per_scorer.items())},
        "avg_latency_ms": mean(latencies) if latencies else None,
        "total_cost_usd": sum(costs) if costs else None,
    }
