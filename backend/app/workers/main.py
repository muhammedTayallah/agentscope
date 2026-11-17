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


async def start_in_process():
    """Run the worker as a task in the current event loop; returns an async stop()."""
    import asyncio
    import logging

    from arq.worker import Worker

    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings,
        on_startup=startup,
        on_shutdown=shutdown,
        job_timeout=WorkerSettings.job_timeout,
        handle_signals=False,  # the web server owns signals
    )
    task = asyncio.create_task(worker.async_run())
    # uvicorn prints this logger; arq's own startup line goes to a logger it doesn't show.
    logging.getLogger("uvicorn.error").info("ARQ worker started in-process")

    async def stop() -> None:
        # Worker.close() signals itself with SIGUSR1 (missing on Windows); do its steps directly.
        # shortcut: a job still running at shutdown is cancelled and its eval run stays
        # "scoring"; re-enqueue stuck runs on startup if that ever bites in production.
        for t in (task, *worker.tasks.values()):
            t.cancel()
        await asyncio.gather(task, *worker.tasks.values(), return_exceptions=True)
        if worker.ctx.get("engine"):
            await shutdown(worker.ctx)
        await worker.pool.close(close_connection_pool=True)

    return stop


class WorkerSettings:
    functions = [ping, score_eval_run]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 600  # judging a large dataset takes a while
