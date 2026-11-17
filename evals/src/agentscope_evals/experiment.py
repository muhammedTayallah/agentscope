"""Run the support agent over an AgentScope dataset and score it.

    uv run python -m agentscope_evals.experiment --version v1
    uv run python -m agentscope_evals.experiment --version v2-concise

Syncs datasets/support.json to the server, opens an eval run, answers every item with
the agent (each answer is a normal trace), uploads the outputs, then waits while the
server's worker scores them. Compare runs in the dashboard under Evals.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from agentscope_sdk import AgentScope

from agentscope_evals.__main__ import load_env
from agentscope_evals.agent import DEFAULT_MODEL, VERSIONS, SupportAgent, gemini_client

DATASET = Path(__file__).resolve().parents[2] / "datasets" / "support.json"

# (question) -> (answer or None, error or None, trace id or None)
RunFn = Callable[[str], tuple[str | None, str | None, str | None]]


def run_experiment(
    api: httpx.Client,
    dataset: dict,
    version: str,
    name: str,
    answer: RunFn,
    *,
    poll_seconds: float = 2.0,
    timeout: float = 600.0,
    log: Callable[[str], None] = print,
) -> dict:
    """Returns the finished eval run (with summary)."""
    ds = (
        api.put(
            f"/v1/datasets/{dataset['name']}",
            json={"description": dataset.get("description"), "items": dataset["items"]},
        )
        .raise_for_status()
        .json()
    )
    run = (
        api.post(
            "/v1/eval-runs", json={"dataset_id": ds["id"], "name": name, "agent_version": version}
        )
        .raise_for_status()
        .json()
    )
    log(f"eval run {run['id']}: {len(ds['items'])} items, agent {version}")

    wanted = {i["key"] for i in dataset["items"]}
    for item in [i for i in ds["items"] if i["key"] in wanted]:
        question = item["input"]["question"] if isinstance(item["input"], dict) else item["input"]
        output, error, trace_id = answer(question)
        api.post(
            f"/v1/eval-runs/{run['id']}/results",
            json={"item_id": item["id"], "output": output, "error": error, "trace_id": trace_id},
        ).raise_for_status()
        log(f"  {item['key']:<26} {'ERROR ' + error[:60] if error else (output or '')[:70]}")

    run = api.post(f"/v1/eval-runs/{run['id']}/complete").raise_for_status().json()
    log("scoring on the server...")
    deadline = time.monotonic() + timeout
    while run["status"] == "scoring":
        if time.monotonic() > deadline:
            raise TimeoutError("Scoring did not finish in time; is the ARQ worker running?")
        time.sleep(poll_seconds)
        run = api.get(f"/v1/eval-runs/{run['id']}").raise_for_status().json()
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the support agent over an eval dataset.")
    parser.add_argument("--version", default="v1", choices=sorted(VERSIONS))
    parser.add_argument("--model", default=os.environ.get("AGENT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--name", help="Eval run name (default: '<version> on <model>')")
    args = parser.parse_args()

    load_env(Path(__file__).resolve().parents[3] / ".env")
    for var in ("GEMINI_API_KEY", "AGENTSCOPE_API_KEY"):
        if not os.environ.get(var):
            print(f"Set {var} (in .env or the shell).", file=sys.stderr)
            return 2

    scope = AgentScope()
    agent = SupportAgent(
        gemini_client(),
        scope,
        model=args.model,
        version=args.version,
        system_prompt=VERSIONS[args.version],
    )

    def answer(question: str):
        try:
            result = agent.run(question)
            return result.answer, None, result.trace_id
        except Exception as exc:  # the failed run is traced; record it as the item's error
            return None, f"{type(exc).__name__}: {exc}"[:1000], None
        finally:
            scope.flush()

    host = os.environ.get("AGENTSCOPE_HOST", "http://localhost:8000").rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['AGENTSCOPE_API_KEY']}"}
    with httpx.Client(base_url=host, headers=headers, timeout=30) as api:
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        run = run_experiment(
            api, dataset, args.version, args.name or f"{args.version} on {args.model}", answer
        )

    s = run.get("summary") or {}
    if run["status"] != "completed":
        print(f"Eval run {run['status']}: {run.get('error')}", file=sys.stderr)
        return 1
    fmt = lambda v, pct=False: "-" if v is None else (f"{v:.0%}" if pct else f"{v:.2f}")  # noqa: E731
    print(
        f"\nscore {fmt(s['score'])} | pass rate {fmt(s['pass_rate'], True)} | "
        f"errors {s['errors']}/{s['items']} | "
        + " | ".join(f"{k} {fmt(v)}" for k, v in s["scorers"].items())
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
