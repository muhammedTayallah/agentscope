import json
from pathlib import Path

import httpx
import pytest

from agentscope_evals.agent import VERSIONS
from agentscope_evals.experiment import DATASET, run_experiment


class FakeServer:
    """Just enough of the eval API to drive run_experiment."""

    def __init__(self, scoring_polls=1):
        self.calls, self.results = [], []
        self.polls_left = scoring_polls

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        self.calls.append((req.method, req.url.path))
        path = req.url.path
        if req.method == "PUT" and path.startswith("/v1/datasets/"):
            items = [{"id": f"id-{i['key']}", **i} for i in body["items"]]
            items.append({"id": "id-old", "key": "old-item", "input": "x", "expected": {}})
            return httpx.Response(200, json={"id": "ds1", "items": items})
        if path == "/v1/eval-runs":
            return httpx.Response(201, json={"id": "run1", "status": "running", **body})
        if path.endswith("/results"):
            self.results.append(body)
            return httpx.Response(204)
        if path.endswith("/complete"):
            return httpx.Response(200, json={"id": "run1", "status": "scoring"})
        if req.method == "GET":
            self.polls_left -= 1
            status = "scoring" if self.polls_left > 0 else "completed"
            return httpx.Response(
                200, json={"id": "run1", "status": status, "summary": {"score": 1}}
            )
        return httpx.Response(404)


def test_runs_every_dataset_item_and_waits_for_scores():
    server = FakeServer(scoring_polls=2)
    api = httpx.Client(base_url="http://x", transport=httpx.MockTransport(server))
    dataset = {
        "name": "mini",
        "items": [
            {"key": "a", "input": {"question": "Q1?"}, "expected": {}},
            {"key": "b", "input": "Q2?", "expected": {}},
        ],
    }

    def answer(q):
        return (None, "RuntimeError: boom", None) if q == "Q2?" else ("A1", None, "t-1")

    run = run_experiment(api, dataset, "v1", "nightly", answer, poll_seconds=0, log=lambda _: None)
    assert run["status"] == "completed"
    assert server.results == [
        {"item_id": "id-a", "output": "A1", "error": None, "trace_id": "t-1"},
        {"item_id": "id-b", "output": None, "error": "RuntimeError: boom", "trace_id": None},
    ]  # "old-item" from an earlier upload of the dataset isn't run
    assert [c for c in server.calls if c[0] == "GET"] == [("GET", "/v1/eval-runs/run1")] * 2


def test_times_out_when_no_worker_scores():
    server = FakeServer(scoring_polls=10**9)
    api = httpx.Client(base_url="http://x", transport=httpx.MockTransport(server))
    dataset = {"name": "m", "items": [{"key": "a", "input": "Q", "expected": {}}]}
    with pytest.raises(TimeoutError, match="worker"):
        run_experiment(
            api,
            dataset,
            "v1",
            "n",
            lambda q: ("A", None, None),
            poll_seconds=0,
            timeout=0.01,
            log=lambda _: None,
        )


def test_shipped_dataset_is_valid():
    data = json.loads(Path(DATASET).read_text(encoding="utf-8"))
    keys = [i["key"] for i in data["items"]]
    assert len(keys) == len(set(keys)) == 10
    tools = {"search_kb", "get_order", "calculate"}
    for item in data["items"]:
        assert item["input"]["question"] and item["expected"]["answer"]
        assert set(item["expected"].get("tools", [])) <= tools


def test_versions_differ_only_in_answer_style():
    assert set(VERSIONS) == {"v1", "v2-concise"}
    assert "one short sentence" in VERSIONS["v2-concise"]
    assert "one short sentence" not in VERSIONS["v1"]
