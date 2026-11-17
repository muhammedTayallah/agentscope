"""Production mode: UI at /, API under /api, SPA fallback, in-process worker, DB URL forms."""

import asyncio
import uuid

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_server


def test_host_database_urls_get_the_asyncpg_driver():
    for url in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        s = Settings(_env_file=None, database_url=url)
        assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"
    kept = "postgresql+asyncpg://u:p@h/db?ssl=disable"
    assert Settings(_env_file=None, database_url=kept).database_url == kept


@pytest.fixture
def ui(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>AgentScope</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


async def test_serves_ui_and_api_under_api(ui):
    settings = Settings(_env_file=None, static_dir=str(ui), redis_url="redis://127.0.0.1:1/0")
    server = create_server(settings)
    async with AsyncClient(transport=ASGITransport(app=server), base_url="http://t") as c:
        assert "AgentScope" in (await c.get("/")).text
        assert (await c.get("/assets/app.js")).text == "console.log(1)"
        deep = await c.get("/p/123/runs/456")  # client-side route: falls back to the UI
        assert deep.status_code == 200 and "<title>AgentScope</title>" in deep.text
        assert (await c.get("/api/v1/project")).status_code == 401  # API answers under /api
        assert (await c.get("/api/projects")).status_code in (401, 503)
        assert "<title>AgentScope</title>" in (await c.get("/docs")).text  # no API docs at /


async def test_without_static_dir_the_api_stays_at_root():
    server = create_server(Settings(_env_file=None))
    async with AsyncClient(transport=ASGITransport(app=server), base_url="http://t") as c:
        assert (await c.get("/v1/project")).status_code == 401  # API at /
        assert (await c.get("/api/v1/project")).status_code == 404  # no /api prefix in dev


async def _noop(ctx):
    return None


async def test_in_process_worker_runs_jobs(redis_url, monkeypatch):
    """RUN_WORKER=true: the web process's lifespan starts the ARQ worker."""
    import app.workers.main as worker_main
    from app.main import lifespan

    settings = RedisSettings.from_dsn(redis_url)
    monkeypatch.setattr(worker_main.WorkerSettings, "redis_settings", settings)
    monkeypatch.setattr(worker_main, "startup", _noop)
    monkeypatch.setattr(worker_main, "shutdown", _noop)
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(_env_file=None, run_worker=True, admin_token=SecretStr("x")),
    )
    pool = await create_pool(settings)
    await pool.flushdb()
    async with lifespan(None):
        job = await pool.enqueue_job("ping", _job_id=str(uuid.uuid4()))
        assert await asyncio.wait_for(job.result(poll_delay=0.1), timeout=10) == "pong"
    await pool.aclose()
