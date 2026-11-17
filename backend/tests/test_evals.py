"""Phase 6: datasets, eval runs, scoring (deterministic + judge) and the read API."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.evals import get_queue
from app.main import app
from app.services import evals as evals_service
from app.services.evals import score_contains, score_tools, summarize
from app.services.judge import AnthropicJudge, GeminiJudge, create_judge, parse
from app.workers.main import score_eval_run
from tests.test_ingest_api import new_key

T0 = datetime(2026, 11, 16, 12, tzinfo=UTC)

DATASET = {
    "description": "Support questions",
    "items": [
        {
            "key": "order-a1002",
            "input": {"question": "Where is my order A1002?"},
            "expected": {
                "answer": "Shipped; arrives 2026-11-18.",
                "contains": ["2026-11-18"],
                "tools": ["get_order"],
            },
        },
        {
            "key": "express-total",
            "input": {"question": "Express shipping on $40, total?"},
            "expected": {"answer": "$12, total $52.", "contains": ["$12", "$52"]},
        },
        {"key": "no-expectations", "input": "hello", "expected": {}},
    ],
}


class FakeQueue:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args):
        self.jobs.append((name, *args))


class FakeJudge:
    model = "fake-judge"

    def __init__(self, score=0.9, error=None):
        self.score, self.error, self.calls = score, error, []

    async def grade(self, question, reference, answer):
        self.calls.append((question, reference, answer))
        if self.error:
            raise self.error
        return self.score, "looks right"


@pytest.fixture
def queue():
    q = FakeQueue()
    app.dependency_overrides[get_queue] = lambda: q
    return q


async def trace_with(db_client, key, *, tools, tokens, ms):
    """Ingest a trace with the given tool spans and one gemini llm span; return its id."""
    tid = str(uuid.uuid4())
    end = T0 + timedelta(milliseconds=ms)
    spans = [
        {"id": str(uuid.uuid4()), "trace_id": tid, "name": t, "kind": "tool"}
        | {"start_time": (T0 + timedelta(milliseconds=i + 1)).isoformat()}
        for i, t in enumerate(tools)
    ]
    spans.append(
        {"id": str(uuid.uuid4()), "trace_id": tid, "name": "gemini", "kind": "llm"}
        | {"model": "claude-sonnet-5-5", "input_tokens": tokens[0], "output_tokens": tokens[1]}
        | {"start_time": T0.isoformat()}
    )
    trace = {"id": tid, "name": "support-agent", "start_time": T0.isoformat()}
    trace["end_time"] = end.isoformat()
    resp = await db_client.post("/v1/ingest", json={"traces": [trace], "spans": spans}, headers=key)
    assert resp.status_code == 202
    return tid


async def setup_run(db_client, admin, version="v1"):
    pid, key = await new_key(db_client, admin)
    ds = (await db_client.put("/v1/datasets/support", json=DATASET, headers=key)).json()
    items = {i["key"]: i["id"] for i in ds["items"]}
    run = await db_client.post(
        "/v1/eval-runs",
        json={"dataset_id": ds["id"], "name": "nightly", "agent_version": version},
        headers=key,
    )
    assert run.status_code == 201
    return pid, key, items, run.json()


# ---------- Scorers (pure) ----------


def test_contains_scorer_is_case_insensitive_fraction():
    assert score_contains("Total is $52, ship $12", ["$12", "$52"]) == {
        "score": 1.0,
        "reason": "all expected phrases present",
    }
    s = score_contains("Arrives NOV 18", ["nov 18", "$19.50"])
    assert s["score"] == 0.5 and "missing: $19.50" in s["reason"]


def test_tools_scorer():
    assert score_tools(["search_kb", "calculate"], ["calculate"])["score"] == 1.0
    s = score_tools(["search_kb"], ["get_order", "search_kb"])
    assert s["score"] == 0.5 and "missing: get_order" in s["reason"]


def test_summarize_means_pass_rate_latency_cost():
    rs = [
        SimpleNamespace(
            scores={"a": {"score": 1.0}, "j": {"score": None}},
            score=1.0,
            error=None,
            latency_ms=100.0,
            cost_usd=0.01,
        ),
        SimpleNamespace(
            scores={"a": {"score": 0.5}}, score=0.5, error="boom", latency_ms=300.0, cost_usd=None
        ),
    ]
    s = summarize(rs, dataset_size=3)
    assert s == {
        "items": 3,
        "answered": 2,
        "errors": 1,
        "score": 0.75,
        "pass_rate": 0.5,
        "scorers": {"a": 0.75},
        "avg_latency_ms": 200.0,
        "total_cost_usd": 0.01,
    }


# ---------- Judge clients (fakes, no network) ----------


def test_parse_clamps_score():
    assert parse('{"score": 1.7, "reason": "ok"}') == (1.0, "ok")
    assert parse('{"score": -1, "reason": "x"}')[0] == 0.0
    with pytest.raises(ValueError):
        parse("not json")


async def test_gemini_judge_requests_json_schema():
    seen = {}

    class Models:
        async def generate_content(self, **kw):
            seen.update(kw)
            return SimpleNamespace(text=json.dumps({"score": 0.5, "reason": "missing date"}))

    judge = GeminiJudge(SimpleNamespace(aio=SimpleNamespace(models=Models())), "gemini-x")
    assert await judge.grade("q?", "ref", "ans") == (0.5, "missing date")
    assert seen["model"] == "gemini-x"
    assert "<reference_answer>\nref\n</reference_answer>" in seen["contents"]
    assert seen["config"].response_mime_type == "application/json"
    assert seen["config"].response_json_schema["required"] == ["score", "reason"]


async def test_anthropic_judge_uses_structured_output_and_handles_refusal():
    seen = {}

    def client(stop_reason):
        class Messages:
            async def create(self, **kw):
                seen.update(kw)
                block = SimpleNamespace(type="text", text='{"score": 1, "reason": "same"}')
                return SimpleNamespace(stop_reason=stop_reason, content=[block])

        return SimpleNamespace(messages=Messages())

    judge = AnthropicJudge(client("end_turn"), "claude-opus-5-5")
    assert await judge.grade("q", "r", "a") == (1.0, "same")
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in seen
    with pytest.raises(RuntimeError, match="declined"):
        await AnthropicJudge(client("refusal"), "m").grade("q", "r", "a")


def test_create_judge_needs_a_key():
    from pydantic import SecretStr

    from app.core.config import Settings

    assert create_judge(Settings(_env_file=None, judge_provider="gemini")) is None
    assert create_judge(Settings(_env_file=None, judge_provider="anthropic")) is None
    g = create_judge(Settings(_env_file=None, gemini_api_key=SecretStr("k")))
    assert isinstance(g, GeminiJudge) and g.model == "gemini-3.8-flash"
    a = create_judge(
        Settings(_env_file=None, judge_provider="anthropic", anthropic_api_key=SecretStr("k"))
    )
    assert isinstance(a, AnthropicJudge) and a.model == "claude-opus-5-5"
    with pytest.raises(ValueError):
        create_judge(Settings(_env_file=None, judge_provider="openai"))


# ---------- Full flow against the database ----------


async def test_dataset_upsert_by_key(db_client, admin):
    _, key = await new_key(db_client, admin)
    first = (await db_client.put("/v1/datasets/support", json=DATASET, headers=key)).json()
    changed = {
        "description": "v2",
        "items": [{"key": "order-a1002", "input": {"question": "Order A1002?"}}],
    }
    second = (await db_client.put("/v1/datasets/support", json=changed, headers=key)).json()
    assert second["id"] == first["id"] and second["description"] == "v2"
    assert [i["key"] for i in second["items"]] == [
        "express-total",
        "no-expectations",
        "order-a1002",
    ]
    a1002 = next(i for i in second["items"] if i["key"] == "order-a1002")
    assert a1002["input"] == {"question": "Order A1002?"} and a1002["expected"] == {}
    bad = await db_client.put("/v1/datasets/bad%2Fname", json=DATASET, headers=key)
    assert bad.status_code in (404, 422)
    assert (
        await db_client.put("/v1/datasets/x", json={"items": []}, headers=key)
    ).status_code == 422


async def test_run_flow_scores_every_item(db_client, admin, session_factory, queue):
    pid, key, items, run = await setup_run(db_client, admin)
    t1 = await trace_with(db_client, key, tools=["get_order"], tokens=(1000, 100), ms=1200)
    t2 = await trace_with(db_client, key, tools=["search_kb"], tokens=(2000, 200), ms=800)
    results = [
        (items["order-a1002"], "It shipped and arrives on 2026-11-18.", None, t1),
        (items["express-total"], "Express is $12.", None, t2),
        (items["no-expectations"], None, "StepLimitExceeded: no answer", None),
    ]
    for item_id, output, error, tid in results:
        resp = await db_client.post(
            f"/v1/eval-runs/{run['id']}/results",
            json={"item_id": item_id, "output": output, "error": error, "trace_id": tid},
            headers=key,
        )
        assert resp.status_code == 204, resp.text

    done = await db_client.post(f"/v1/eval-runs/{run['id']}/complete", headers=key)
    assert done.json()["status"] == "scoring"
    assert queue.jobs == [("score_eval_run", run["id"])]

    judge = FakeJudge(score=0.9)
    await score_eval_run({"session_factory": session_factory, "judge": judge}, run["id"])
    detail = (await db_client.get(f"/projects/{pid}/eval-runs/{run['id']}", headers=admin)).json()
    assert detail["status"] == "completed" and detail["dataset_name"] == "support"
    by_key = {r["item"]["key"]: r for r in detail["results"]}

    a = by_key["order-a1002"]
    assert a["scores"]["contains"]["score"] == 1.0
    assert a["scores"]["tools"]["score"] == 1.0
    assert a["scores"]["judge"] == {"score": 0.9, "reason": "looks right"}
    assert a["score"] == pytest.approx((1.0 + 1.0 + 0.9) / 3)
    assert a["latency_ms"] == pytest.approx(1200)
    assert a["cost_usd"] == pytest.approx((1000 * 2 + 100 * 10) / 1e6)  # sonnet 2/10

    b = by_key["express-total"]
    assert b["scores"]["contains"]["score"] == 0.5  # "$52" missing
    assert "tools" not in b["scores"]
    assert b["score"] == pytest.approx((0.5 + 0.9) / 2)

    c = by_key["no-expectations"]
    assert c["error"].startswith("StepLimitExceeded") and c["scores"] == {} and c["score"] is None

    assert (
        "Where is my order A1002?",
        "Shipped; arrives 2026-11-18.",
        "It shipped and arrives on 2026-11-18.",
    ) in judge.calls
    assert len(judge.calls) == 2  # the failed item and the one without a reference aren't judged
    s = detail["summary"]
    assert (s["items"], s["answered"], s["errors"]) == (3, 3, 1)
    assert s["scorers"]["contains"] == pytest.approx(0.75)
    assert s["pass_rate"] == pytest.approx(0.5)  # a passes (0.97), b doesn't (0.7)
    assert s["total_cost_usd"] == pytest.approx(0.003 + 0.006)

    runs = (await db_client.get(f"/projects/{pid}/eval-runs", headers=admin)).json()
    assert [(r["name"], r["dataset_name"], r["status"]) for r in runs] == [
        ("nightly", "support", "completed")
    ]
    status_ = (await db_client.get(f"/v1/eval-runs/{run['id']}", headers=key)).json()
    assert status_["summary"]["items"] == 3


async def test_failed_agent_items_score_zero_and_missing_items_are_listed(
    db_client, admin, session_factory, queue
):
    pid, key, items, run = await setup_run(db_client, admin)
    await db_client.post(
        f"/v1/eval-runs/{run['id']}/results",
        json={"item_id": items["order-a1002"], "error": "503 overloaded"},
        headers=key,
    )
    await db_client.post(f"/v1/eval-runs/{run['id']}/complete", headers=key)
    await score_eval_run({"session_factory": session_factory, "judge": FakeJudge()}, run["id"])
    detail = (await db_client.get(f"/projects/{pid}/eval-runs/{run['id']}", headers=admin)).json()
    by_key = {r["item"]["key"]: r for r in detail["results"]}
    failed = by_key["order-a1002"]
    assert {k: v["score"] for k, v in failed["scores"].items()} == {
        "contains": 0.0,
        "tools": 0.0,
        "judge": 0.0,
    }
    assert "agent failed: 503 overloaded" in failed["scores"]["judge"]["reason"]
    assert by_key["express-total"]["output"] is None and by_key["express-total"]["scores"] is None
    assert detail["summary"]["answered"] == 1 and detail["summary"]["items"] == 3


@pytest.mark.parametrize(
    ("judge", "reason"),
    [(None, "no judge configured"), (FakeJudge(error=TimeoutError("slow")), "judge failed")],
)
async def test_judge_problems_dont_fail_the_run(
    db_client, admin, session_factory, queue, judge, reason
):
    pid, key, items, run = await setup_run(db_client, admin)
    await db_client.post(
        f"/v1/eval-runs/{run['id']}/results",
        json={"item_id": items["express-total"], "output": "$12 and $52"},
        headers=key,
    )
    await db_client.post(f"/v1/eval-runs/{run['id']}/complete", headers=key)
    await score_eval_run({"session_factory": session_factory, "judge": judge}, run["id"])
    detail = (await db_client.get(f"/projects/{pid}/eval-runs/{run['id']}", headers=admin)).json()
    r = next(x for x in detail["results"] if x["item"]["key"] == "express-total")
    assert detail["status"] == "completed"
    assert r["scores"]["judge"]["score"] is None and reason in r["scores"]["judge"]["reason"]
    assert r["score"] == 1.0  # mean of the scorers that produced a number


async def test_state_and_ownership_checks(db_client, admin, queue):
    pid, key, items, run = await setup_run(db_client, admin)
    _, other_key = await new_key(db_client, admin, "other")
    url = f"/v1/eval-runs/{run['id']}"

    other_ds = (await db_client.put("/v1/datasets/other", json=DATASET, headers=other_key)).json()
    foreign_item = other_ds["items"][0]["id"]
    assert (
        await db_client.post(f"{url}/results", json={"item_id": foreign_item}, headers=key)
    ).status_code == 404
    assert (await db_client.get(url, headers=other_key)).status_code == 404
    assert (await db_client.post(f"{url}/complete", headers=other_key)).status_code == 404
    bad_run = {"dataset_id": other_ds["id"], "name": "x", "agent_version": "v1"}
    assert (await db_client.post("/v1/eval-runs", json=bad_run, headers=key)).status_code == 404

    assert (await db_client.post(f"{url}/complete", headers=key)).status_code == 200
    assert (await db_client.post(f"{url}/complete", headers=key)).status_code == 409
    late = {"item_id": items["order-a1002"], "output": "late"}
    assert (await db_client.post(f"{url}/results", json=late, headers=key)).status_code == 409

    assert (await db_client.get(f"/projects/{pid}/eval-runs")).status_code == 401
    missing = await db_client.get(f"/projects/{pid}/eval-runs/{uuid.uuid4()}", headers=admin)
    assert missing.status_code == 404


async def test_score_run_ignores_runs_not_in_scoring(db_client, admin, session_factory, queue):
    _, _, _, run = await setup_run(db_client, admin)
    await evals_service.score_run(session_factory, uuid.UUID(run["id"]), FakeJudge(), {})
    async with session_factory() as s:
        from app.db.models import EvalRun

        assert (await s.get(EvalRun, uuid.UUID(run["id"]))).status == "running"


def test_gemini_judge_client_retries_long_enough_for_rate_limits():
    from pydantic import SecretStr

    from app.core.config import Settings

    judge = create_judge(Settings(_env_file=None, gemini_api_key=SecretStr("k")))
    retry = judge.client._api_client._http_options.retry_options
    assert (retry.attempts, retry.initial_delay) == (8, 2.0)
