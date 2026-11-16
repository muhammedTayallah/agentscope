import asyncio
import json
import threading
import time

import httpx
import pytest

from agentscope_sdk import AgentScope
from agentscope_sdk.client import MAX_FIELD_CHARS


class Recorder:
    """httpx transport that records ingest payloads and returns a scripted status."""

    def __init__(self, statuses=(202,)):
        self.payloads: list[dict] = []
        self.statuses = list(statuses)
        self.lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.payloads.append(json.loads(request.content))
            self.auth = request.headers["authorization"]
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return httpx.Response(status, json={})

    @property
    def spans(self):
        return [s for p in self.payloads for s in p["spans"]]

    @property
    def traces(self):
        return [t for p in self.payloads for t in p["traces"]]


def make(recorder: Recorder, **kw) -> AgentScope:
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    return AgentScope(api_key="ask_test", host="http://x", http_client=client, **kw)


def by_name(items):
    return {i["name"]: i for i in items}


def test_nested_spans_form_a_tree():
    rec = Recorder()
    scope = make(rec)
    with scope.trace("run", input={"q": "hi"}) as t:
        with scope.span("agent") as agent:
            with scope.span("llm", kind="llm", model="gemini") as llm:
                llm.update(output="hello", input_tokens=3, output_tokens=2)
            with scope.span("search", kind="tool"):
                pass
        t.update(output="done")
    assert scope.flush(2)

    (trace,) = rec.traces
    spans = by_name(rec.spans)
    assert rec.auth == "Bearer ask_test"
    assert (trace["name"], trace["input"], trace["output"]) == ("run", {"q": "hi"}, "done")
    assert all(s["trace_id"] == trace["id"] for s in spans.values())
    assert spans["agent"]["parent_id"] is None
    assert spans["llm"]["parent_id"] == agent.id == spans["search"]["parent_id"]
    assert (spans["llm"]["kind"], spans["llm"]["model"], spans["llm"]["output_tokens"]) == (
        "llm",
        "gemini",
        2,
    )
    assert spans["llm"]["end_time"] >= spans["llm"]["start_time"]


def test_span_without_trace_opens_one():
    rec = Recorder()
    scope = make(rec)
    with scope.span("lonely", kind="tool"):
        pass
    scope.flush(2)
    (trace,) = rec.traces
    (span,) = rec.spans
    assert trace["name"] == "lonely" and span["trace_id"] == trace["id"]


def test_errors_are_recorded_and_reraised():
    rec = Recorder()
    scope = make(rec)
    with pytest.raises(ValueError, match="bad input"):
        with scope.trace("run"):
            with scope.span("step"):
                raise ValueError("bad input")
    scope.flush(2)
    for item in rec.spans + rec.traces:
        assert item["status"] == "error"
        assert item["error"] == "ValueError: bad input"


def test_observe_sync_and_async_capture_args_and_result():
    rec = Recorder()
    scope = make(rec)

    @scope.observe(kind="tool")
    def add(a, b=1):
        return a + b

    @scope.observe(name="fetch")
    async def fetch(url):
        await asyncio.sleep(0)
        return {"url": url}

    with scope.trace("run"):
        assert add(2, b=3) == 5
        assert asyncio.run(fetch("u")) == {"url": "u"}
    scope.flush(2)
    spans = by_name(rec.spans)
    assert spans["test_observe_sync_and_async_capture_args_and_result.<locals>.add"]["input"] == {
        "a": 2,
        "b": 3,
    }
    assert spans["fetch"]["output"] == {"url": "u"}
    assert len({s["trace_id"] for s in spans.values()}) == 1


async def test_concurrent_tasks_keep_separate_parents():
    rec = Recorder()
    scope = make(rec)

    async def worker(name):
        with scope.span(name) as outer:
            await asyncio.sleep(0.01)
            with scope.span(f"{name}-child"):
                await asyncio.sleep(0.01)
        return outer.id

    with scope.trace("run"):
        a_id, b_id = await asyncio.gather(worker("a"), worker("b"))
    scope.flush(2)
    spans = by_name(rec.spans)
    assert spans["a-child"]["parent_id"] == a_id
    assert spans["b-child"]["parent_id"] == b_id


def test_unserializable_and_huge_values_are_safe():
    rec = Recorder()
    scope = make(rec)
    loop: list = []
    loop.append(loop)
    with scope.span("s", input={"obj": object(), "loop": loop}) as s:
        s.update(output="x" * (MAX_FIELD_CHARS + 10))
    scope.flush(2)
    (span,) = rec.spans
    assert isinstance(span["input"], str | dict)
    assert span["output"]["truncated"] is True


def test_retries_server_errors_then_succeeds():
    rec = Recorder(statuses=[503, 202])
    scope = make(rec)
    with scope.span("s"):
        pass
    assert scope.flush(5)
    assert len(rec.payloads) == 2  # first attempt failed, retry delivered


def test_client_errors_are_not_retried():
    rec = Recorder(statuses=[401])
    scope = make(rec)
    with scope.span("s"):
        pass
    assert scope.flush(2)
    assert len(rec.payloads) == 1


def test_unreachable_server_never_breaks_the_app():
    # Port 1 on localhost: connection refused immediately.
    scope = AgentScope(api_key="ask_test", host="http://127.0.0.1:1", max_retries=1)

    @scope.observe()
    def work(x):
        return x * 2

    start = time.monotonic()
    with scope.trace("run"):
        assert work(21) == 42
    assert time.monotonic() - start < 0.5  # sending happens in the background
    scope.flush(5)  # retries, then drops; must not raise
    scope.shutdown(0.1)


def test_full_queue_drops_instead_of_blocking():
    rec = Recorder()
    scope = make(rec, max_queue=1)
    scope._ensure_thread = lambda: None  # no sender: the queue stays full
    for _ in range(5):
        with scope.span("s"):
            pass
    assert scope._queue.qsize() == 1


def test_no_api_key_disables_tracing(monkeypatch):
    monkeypatch.delenv("AGENTSCOPE_API_KEY", raising=False)
    rec = Recorder()
    scope = AgentScope(http_client=httpx.Client(transport=httpx.MockTransport(rec)))
    with scope.trace("run") as t:
        t.update(output="ok")
    assert scope.flush(1) and rec.payloads == []
