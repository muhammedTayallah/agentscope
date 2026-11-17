from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]
ADMIN_TOKEN = "test-admin-token-0123456789"


@pytest.fixture(scope="session")
def env() -> Settings:
    """Settings from .env; integration tests use its TEST_* URLs."""
    return Settings()


@pytest.fixture
def test_settings(env: Settings) -> Settings:
    return Settings(
        _env_file=None,  # .env values (e.g. MODEL_PRICES) must not leak into test settings
        admin_token=SecretStr(ADMIN_TOKEN),
        redis_url=env.test_redis_url or "redis://127.0.0.1:1/0",
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings] = lambda: test_settings
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


# ---------- Real Postgres (skipped unless TEST_DATABASE_URL is set) ----------


@pytest.fixture(scope="session")
def migrated_database(env: Settings) -> Iterator[str]:
    """Migrate the test DB from scratch once per session (also tests the migrations)."""
    if not env.test_database_url:
        pytest.skip("TEST_DATABASE_URL not set")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", env.test_database_url)
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield env.test_database_url


@pytest.fixture
async def session_factory(
    migrated_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_database)
    async with engine.begin() as conn:
        tables = (
            "projects, api_keys, traces, spans, datasets, dataset_items, eval_runs, eval_results"
        )
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db_client(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncClient:
    async def _get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _get_session
    return client


@pytest.fixture
def redis_url(env: Settings) -> str:
    if not env.test_redis_url:
        pytest.skip("TEST_REDIS_URL not set")
    return env.test_redis_url
