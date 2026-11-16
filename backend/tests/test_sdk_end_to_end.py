"""Phase 2 "done when": a script using the SDK produces a correctly nested trace in the DB."""

from collections.abc import AsyncIterator

import pytest
from agentscope_sdk import AgentScope
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.db.models import Span, Trace
from app.db.session import get_session
from app.main import app
from app.services import projects as projects_service


@pytest.fixture
def app_on_test_db(migrated_database, session_factory):
    # The SDK's sender thread drives the app through TestClient on its own event loop,
    # so the app needs connections that aren't tied to this test's loop: NullPool.
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _get_session
    with TestClient(app) as http:
        yield http
    app.dependency_overrides.clear()


async def test_sdk_script_produces_nested_trace(app_on_test_db, session_factory):
    async with session_factory() as s:
        project, _, key = await projects_service.create_project(s, "e2e")

    scope = AgentScope(api_key=key, host="http://testserver", http_client=app_on_test_db)

    # --- what a user's agent script looks like ---
    @scope.observe(kind="tool")
    def search(query: str) -> list[str]:
        return [f"doc about {query}"]

    with scope.trace("answer-question", input={"question": "What is RRF?"}) as run:
        with scope.span("agent"):
            docs = search("RRF")
            with scope.span("llm-call", kind="llm", model="gemini-3.8-flash") as llm:
                llm.update(output="RRF fuses rankings.", input_tokens=42, output_tokens=7)
        run.update(output="RRF fuses rankings.")
    # -----------------------------------------
    assert docs == ["doc about RRF"]
    assert scope.flush(10), "SDK did not deliver its events"

    async with session_factory() as s:
        trace = (await s.execute(select(Trace))).scalar_one()
        spans = {sp.name: sp for sp in (await s.execute(select(Span))).scalars()}

    assert trace.project_id == project.id
    assert (trace.name, trace.input, trace.output) == (
        "answer-question",
        {"question": "What is RRF?"},
        "RRF fuses rankings.",
    )
    tool = spans["test_sdk_script_produces_nested_trace.<locals>.search"]
    agent, llm_span = spans["agent"], spans["llm-call"]
    assert agent.parent_id is None
    assert tool.parent_id == agent.id and llm_span.parent_id == agent.id
    assert all(sp.trace_id == trace.id for sp in spans.values())
    assert (tool.kind, tool.input, tool.output) == ("tool", {"query": "RRF"}, ["doc about RRF"])
    assert (llm_span.model, llm_span.input_tokens, llm_span.output_tokens) == (
        "gemini-3.8-flash",
        42,
        7,
    )
    assert trace.start_time <= agent.start_time <= tool.start_time <= tool.end_time
    assert tool.end_time <= agent.end_time <= trace.end_time
