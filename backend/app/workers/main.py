"""ARQ worker. Run: uv run arq app.workers.main.WorkerSettings"""

import uuid

from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.services.evals import score_run
from app.services.judge import create_judge


async def ping(ctx: dict) -> str:
    """Smoke-test job: proves the queue round-trip works."""
    return "pong"


async def score_eval_run(ctx: dict, run_id: str) -> None:
    """Score every result of a completed eval run (deterministic scorers + LLM judge)."""
    settings = get_settings()
    await score_run(ctx["session_factory"], uuid.UUID(run_id), ctx["judge"], settings.all_prices())


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["engine"] = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["session_factory"] = async_sessionmaker(ctx["engine"], expire_on_commit=False)
    ctx["judge"] = create_judge(settings)


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [ping, score_eval_run]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 600  # judging a large dataset takes a while
