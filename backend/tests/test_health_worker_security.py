from unittest.mock import AsyncMock

from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import Worker
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import display_prefix, generate_api_key, hash_api_key
from app.db.session import get_session
from app.main import app
from app.services.health import check_redis
from app.workers.main import WorkerSettings, ping


def test_api_keys_are_random_and_hash_stably():
    a, b = generate_api_key(), generate_api_key()
    assert a != b and a.startswith("ask_")
    assert hash_api_key(a) == hash_api_key(a) != hash_api_key(b)
    assert len(hash_api_key(a)) == 64
    assert display_prefix(a) == a[:12]


async def test_health_ok(db_client):
    resp = await db_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "database": "ok", "redis": "ok"}


async def test_health_reports_each_failure(client):
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = ConnectionRefusedError

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session
    # test_settings points Redis at a closed port when TEST_REDIS_URL is unset; force it here.
    from app.core.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(redis_url="redis://127.0.0.1:1/0")
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unhealthy", "database": "error", "redis": "error"}


async def test_check_redis_real(redis_url):
    assert await check_redis(redis_url) is True


async def test_worker_runs_queued_job(redis_url):
    """Enqueue on real Redis and run one burst of the ARQ worker."""
    flush = Redis.from_url(redis_url)
    await flush.flushdb()
    await flush.aclose()

    settings = RedisSettings.from_dsn(redis_url)
    pool = await create_pool(settings)
    job = await pool.enqueue_job("ping")
    worker = Worker(functions=WorkerSettings.functions, redis_settings=settings, burst=True)
    await worker.main()
    assert await job.result(timeout=5) == "pong"
    await worker.close()
    await pool.aclose()


async def test_ping_job():
    assert await ping({}) == "pong"
