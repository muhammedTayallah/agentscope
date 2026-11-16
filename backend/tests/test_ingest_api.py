import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Span, Trace

T0 = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def iso(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


async def new_key(db_client, admin, name="P") -> tuple[str, dict]:
    created = (await db_client.post("/projects", json={"name": name}, headers=admin)).json()
    return created["project"]["id"], {"Authorization": f"Bearer {created['api_key']['key']}"}


def trace(tid, **kw):
    return {"id": str(tid), "name": "run", "start_time": iso(0), "end_time": iso(3)} | kw


def span(sid, tid, parent=None, **kw):
    return {
        "id": str(sid),
        "trace_id": str(tid),
        "parent_id": str(parent) if parent else None,
        "name": "step",
        "start_time": iso(1),
        "end_time": iso(2),
    } | kw


async def test_ingest_requires_api_key(db_client):
    assert (await db_client.post("/v1/ingest", json={})).status_code == 401
    bad = {"Authorization": "Bearer ask_nope"}
    assert (await db_client.post("/v1/ingest", json={}, headers=bad)).status_code == 401


async def test_ingest_stores_nested_trace(db_client, admin, session_factory):
    pid, key = await new_key(db_client, admin)
    tid, root, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    batch = {
        "traces": [trace(tid, input={"q": "hi"}, output="bye", metadata={"v": "1"})],
        "spans": [
            span(root, tid, name="agent"),
            span(
                child,
                tid,
                parent=root,
                name="llm",
                kind="llm",
                model="gemini-3.8-flash",
                input_tokens=12,
                output_tokens=5,
                status="error",
                error="boom",
            ),
        ],
    }
    resp = await db_client.post("/v1/ingest", json=batch, headers=key)
    assert resp.status_code == 202
    assert resp.json() == {"traces": 1, "spans": 2}

    async with session_factory() as s:
        t = await s.get(Trace, tid)
        spans = {sp.id: sp for sp in (await s.execute(select(Span))).scalars()}
    assert str(t.project_id) == pid
    assert (t.input, t.output, t.meta) == ({"q": "hi"}, "bye", {"v": "1"})
    assert spans[root].parent_id is None
    c = spans[child]
    assert (c.parent_id, c.kind, c.model, c.input_tokens, c.output_tokens) == (
        root,
        "llm",
        "gemini-3.8-flash",
        12,
        5,
    )
    assert (c.status, c.error) == ("error", "boom")


async def test_spans_before_trace_then_trace_fills_placeholder(db_client, admin, session_factory):
    _, key = await new_key(db_client, admin)
    tid, sid = uuid.uuid4(), uuid.uuid4()
    await db_client.post("/v1/ingest", json={"spans": [span(sid, tid)]}, headers=key)
    async with session_factory() as s:
        placeholder = await s.get(Trace, tid)
    assert placeholder.name == "(pending)" and placeholder.start_time == T0 + timedelta(seconds=1)

    await db_client.post("/v1/ingest", json={"traces": [trace(tid, name="real")]}, headers=key)
    async with session_factory() as s:
        t = await s.get(Trace, tid)
    assert (t.name, t.start_time, t.end_time) == ("real", T0, T0 + timedelta(seconds=3))


async def test_retries_and_duplicates_are_idempotent(db_client, admin, session_factory):
    _, key = await new_key(db_client, admin)
    tid, sid = uuid.uuid4(), uuid.uuid4()
    batch = {
        "traces": [trace(tid)],
        "spans": [span(sid, tid, name="first"), span(sid, tid, name="second")],
    }
    for _ in range(2):
        assert (await db_client.post("/v1/ingest", json=batch, headers=key)).status_code == 202
    async with session_factory() as s:
        rows = (await s.execute(select(Span))).scalars().all()
    assert [r.name for r in rows] == ["second"]


async def test_ids_of_other_project_are_rejected(db_client, admin, session_factory):
    _, key_a = await new_key(db_client, admin, "A")
    _, key_b = await new_key(db_client, admin, "B")
    tid, sid = uuid.uuid4(), uuid.uuid4()
    await db_client.post(
        "/v1/ingest", json={"traces": [trace(tid)], "spans": [span(sid, tid)]}, headers=key_a
    )
    for hijack in [
        {"traces": [trace(tid, name="stolen")]},
        {"spans": [span(uuid.uuid4(), tid)]},
        {"spans": [span(sid, uuid.uuid4())]},
    ]:
        assert (await db_client.post("/v1/ingest", json=hijack, headers=key_b)).status_code == 409
    async with session_factory() as s:
        assert (await s.get(Trace, tid)).name == "run"
        assert len((await s.execute(select(Span))).scalars().all()) == 1


async def test_validation(db_client, admin):
    _, key = await new_key(db_client, admin)
    tid = uuid.uuid4()
    bad_batches = [
        {"traces": [trace(tid, start_time="2026-11-16T12:00:00")]},  # no timezone
        {"spans": [span(uuid.uuid4(), tid, kind="other")]},
        {"spans": [span(uuid.uuid4(), tid, input_tokens=-1)]},
        {"traces": [trace(tid, name="")]},
        {"spans": [span(uuid.uuid4(), tid) for _ in range(501)]},
    ]
    for b in bad_batches:
        assert (await db_client.post("/v1/ingest", json=b, headers=key)).status_code == 422
