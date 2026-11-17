"""The agent loop against a scripted Gemini client, with traces captured from the SDK."""

import json
import threading

import httpx
import pytest
from agentscope_sdk import AgentScope
from google.genai import types

from agentscope_evals.agent import DEFAULT_MODEL, StepLimitExceeded, SupportAgent


def reply(*, text=None, calls=(), prompt=100, out=10, thoughts=0):
    parts = [types.Part(text=text)] if text else []
    parts += [
        types.Part(function_call=types.FunctionCall(id=f"c{i}", name=n, args=a))
        for i, (n, a) in enumerate(calls)
    ]
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts
        ),
    )


class FakeGemini:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[list[types.Content]] = []
        outer = self

        class _Models:
            def generate_content(self, *, model, contents, config):
                outer.requests.append(list(contents))
                outer.config = config
                return outer.replies.pop(0)

        self.models = _Models()


class Recorder:
    def __init__(self):
        self.payloads, self.lock = [], threading.Lock()

    def __call__(self, request):
        with self.lock:
            self.payloads.append(json.loads(request.content))
        return httpx.Response(202, json={})

    def items(self, kind):
        return [i for p in self.payloads for i in p[kind]]


@pytest.fixture
def traced():
    rec = Recorder()
    scope = AgentScope(
        api_key="ask_test",
        host="http://x",
        http_client=httpx.Client(transport=httpx.MockTransport(rec)),
    )
    return scope, rec


def test_tool_loop_answers_and_traces_every_step(traced):
    scope, rec = traced
    gemini = FakeGemini(
        [
            reply(calls=[("get_order", {"order_id": "A1002"})], prompt=300, out=20, thoughts=40),
            reply(text="Your charger shipped and should arrive on 2026-11-18.", prompt=420, out=18),
        ]
    )
    agent = SupportAgent(gemini, scope, version="v7")
    result = agent.run("Where is my order A1002?")
    assert scope.flush(5)

    assert result.answer == "Your charger shipped and should arrive on 2026-11-18."
    assert (result.steps, result.tool_calls) == (2, ["get_order"])

    # Second request carried the model's turn and our tool result back.
    second = gemini.requests[1]
    assert second[1].parts[0].function_call.name == "get_order"
    fr = second[2].parts[0].function_response
    assert (fr.id, fr.name) == ("c0", "get_order")
    assert fr.response["result"]["eta"] == "2026-11-18"
    assert gemini.config.automatic_function_calling.disable is True

    (trace,) = rec.items("traces")
    assert trace["id"] == result.trace_id
    assert trace["metadata"] == {"agent_version": "v7", "model": DEFAULT_MODEL}
    assert trace["output"] == result.answer
    spans = rec.items("spans")
    assert [(s["name"], s["kind"]) for s in sorted(spans, key=lambda s: s["start_time"])] == [
        ("gemini", "llm"),
        ("get_order", "tool"),
        ("gemini", "llm"),
    ]
    llm = [s for s in spans if s["kind"] == "llm"]
    assert [(s["input_tokens"], s["output_tokens"]) for s in llm] == [(300, 60), (420, 18)]
    assert all(s["model"] == DEFAULT_MODEL for s in llm)
    tool = next(s for s in spans if s["kind"] == "tool")
    assert tool["input"] == {"order_id": "A1002"}
    assert tool["output"]["result"]["status"] == "shipped"


def test_tool_errors_reach_the_model_and_the_trace(traced):
    scope, rec = traced
    gemini = FakeGemini(
        [
            reply(calls=[("get_order", {"order_id": "Z9"}), ("calculate", {"expression": "2+"})]),
            reply(calls=[("nope", {})]),
            reply(text="I couldn't find order Z9; please check the id."),
        ]
    )
    result = SupportAgent(gemini, scope).run("Order Z9?")
    scope.flush(5)
    assert result.tool_calls == ["get_order", "calculate", "nope"]
    responses = [p.function_response.response for p in gemini.requests[1][2].parts]
    assert "No order" in responses[0]["error"] and "Cannot calculate" in responses[1]["error"]
    tools = [s for s in rec.items("spans") if s["kind"] == "tool"]
    assert {s["name"]: s["status"] for s in tools} == {
        "get_order": "error",
        "calculate": "error",
        "nope": "error",
    }
    assert rec.items("traces")[0].get("status", "ok") == "ok"  # recovered; ok is the default


def test_step_limit_marks_trace_failed(traced):
    scope, rec = traced
    looping = [reply(calls=[("search_kb", {"query": "returns"})]) for _ in range(3)]
    with pytest.raises(StepLimitExceeded):
        SupportAgent(FakeGemini(looping), scope, max_steps=3).run("?")
    scope.flush(5)
    (trace,) = rec.items("traces")
    assert trace["status"] == "error" and "StepLimitExceeded" in trace["error"]


def test_model_errors_mark_trace_failed(traced):
    scope, rec = traced

    class Broken:
        class models:  # noqa: N801
            @staticmethod
            def generate_content(**_):
                raise RuntimeError("503 overloaded")

    with pytest.raises(RuntimeError):
        SupportAgent(Broken(), scope).run("hi")
    scope.flush(5)
    (llm,) = rec.items("spans")
    assert llm["status"] == "error" and "503" in llm["error"]
    assert rec.items("traces")[0]["status"] == "error"


def test_gemini_client_retries_long_enough_for_rate_limits(monkeypatch):
    from agentscope_evals.agent import gemini_client

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    retry = gemini_client()._api_client._http_options.retry_options
    assert (retry.attempts, retry.initial_delay) == (8, 2.0)
