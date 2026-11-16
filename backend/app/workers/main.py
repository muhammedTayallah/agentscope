"""ARQ worker. Run: uv run arq app.workers.main.WorkerSettings"""

from arq.connections import RedisSettings

from app.core.config import get_settings


async def ping(ctx: dict) -> str:
    """Smoke-test job: proves the queue round-trip works. Real jobs arrive in later phases."""
    return "pong"


class WorkerSettings:
    functions = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
