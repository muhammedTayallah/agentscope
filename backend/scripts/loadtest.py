"""Open-loop load test for POST /v1/ingest.

    uv run python scripts/loadtest.py --rate 200 --duration 60 --label baseline

Each request is one SDK-shaped batch: 1 trace + 9 spans (a root agent span with llm
and tool children). Requests are fired on a fixed schedule whatever the server does
(open loop), and latency is measured from each request's *scheduled* time, so queueing
delay counts (no coordinated omission). Creates its own project via the admin API.
Writes a JSON result to docs/loadtest/.
"""

import argparse
import asyncio
import json
import multiprocessing
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.core.config import get_settings

OUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "loadtest"


def batch() -> dict:
    now = datetime.now(UTC)
    tid, root = str(uuid.uuid4()), str(uuid.uuid4())

    def t(ms: int) -> str:
        return (now + timedelta(milliseconds=ms)).isoformat()

    spans = [{"id": root, "trace_id": tid, "name": "agent", "start_time": t(0), "end_time": t(900)}]
    for i in range(8):
        llm = i % 2 == 0
        spans.append(
            {
                "id": str(uuid.uuid4()),
                "trace_id": tid,
                "parent_id": root,
                "name": "gemini" if llm else "search_kb",
                "kind": "llm" if llm else "tool",
                "start_time": t(i * 100),
                "end_time": t(i * 100 + 90),
                "input": {"messages": 3, "last": ["Where is my order A1002?"]},
                "output": "Your order shipped and arrives on 2026-11-18."
                if llm
                else [{"topic": "x"}],
            }
            | (
                {"model": "gemini-3.5-flash-lite", "input_tokens": 300, "output_tokens": 40}
                if llm
                else {}
            )
        )
    trace = {
        "id": tid,
        "name": "support-agent",
        "start_time": t(0),
        "end_time": t(950),
        "input": {"question": "Where is my order A1002?"},
        "output": "Your order shipped and arrives on 2026-11-18.",
        "metadata": {"agent_version": "loadtest"},
    }
    return {"traces": [trace], "spans": spans}


def pct(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    i = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[i]


async def run(
    base: str,
    key: str,
    rate: float,
    duration: float,
    max_inflight: int,
    t0: float,
    slot: int,
    slots: int,
) -> tuple[list[float], dict[str, int], int]:
    """Send this process's share of the schedule: requests slot, slot+slots, ... of the whole
    run (request i is due at t0 + i/rate, wall clock, so processes interleave)."""
    latencies: list[float] = []
    errors: dict[str, int] = {}
    limits = httpx.Limits(max_connections=max_inflight, max_keepalive_connections=max_inflight)
    sem = asyncio.Semaphore(max_inflight)
    async with httpx.AsyncClient(base_url=base, limits=limits, timeout=30) as client:
        headers = {"Authorization": f"Bearer {key}"}

        async def one(scheduled: float, body: dict) -> None:
            async with sem:
                try:
                    r = await client.post("/v1/ingest", json=body, headers=headers)
                    if r.status_code != 202:
                        errors[str(r.status_code)] = errors.get(str(r.status_code), 0) + 1
                        return
                except httpx.HTTPError as exc:
                    errors[type(exc).__name__] = errors.get(type(exc).__name__, 0) + 1
                    return
            latencies.append((time.time() - scheduled) * 1000)

        mine = range(slot, int(rate * duration), slots)
        tasks = []
        for i in mine:
            scheduled = t0 + i / rate
            delay = scheduled - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(one(scheduled, batch())))
        await asyncio.gather(*tasks)
    return latencies, errors, len(mine)


def _process(job: tuple) -> tuple[list[float], dict[str, int], int]:
    return asyncio.run(run(*job))


def summarize(parts: list[tuple], elapsed: float) -> dict:
    lat = sorted(x for latencies, _, _ in parts for x in latencies)
    errors: dict[str, int] = {}
    for _, errs, _ in parts:
        for k, v in errs.items():
            errors[k] = errors.get(k, 0) + v
    return {
        "requests": sum(n for _, _, n in parts),
        "ok": len(lat),
        "errors": errors,
        "elapsed_s": round(elapsed, 2),
        "achieved_rps": round(len(lat) / elapsed, 1),
        "spans_per_s": round(len(lat) * 9 / elapsed, 1),
        "latency_ms": {
            "p50": round(pct(lat, 0.50), 1),
            "p95": round(pct(lat, 0.95), 1),
            "p99": round(pct(lat, 0.99), 1),
            "max": round(lat[-1], 1) if lat else None,
            "mean": round(statistics.fmean(lat), 1) if lat else None,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--rate", type=float, default=200, help="requests per second")
    p.add_argument("--duration", type=float, default=60, help="seconds")
    p.add_argument("--max-inflight", type=int, default=500)
    p.add_argument("--label", default="run", help="name of the result file")
    p.add_argument("--target-p95", type=float, default=200.0)
    p.add_argument(
        "--processes", type=int, default=4, help="generator processes (one can't send ~170+ req/s)"
    )
    args = p.parse_args()

    admin = {"Authorization": f"Bearer {get_settings().admin_token.get_secret_value()}"}
    name = f"loadtest {datetime.now(UTC):%Y-%m-%d %H:%M:%S}"
    created = httpx.post(f"{args.base}/projects", json={"name": name}, headers=admin)
    key = created.raise_for_status().json()["api_key"]["key"]

    n = args.processes
    t0 = time.time() + 2.0  # common start once every process is up
    jobs = [
        (args.base, key, args.rate, args.duration, args.max_inflight // n, t0, i, n)
        for i in range(n)
    ]
    with multiprocessing.Pool(n) as pool:
        parts = pool.map(_process, jobs)
    result = summarize(parts, time.time() - t0)
    passed = (
        not result["errors"]
        and result["achieved_rps"] >= args.rate * 0.98
        and result["latency_ms"]["p95"] < args.target_p95
    )
    result |= {
        "label": args.label,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": {"rps": args.rate, "p95_ms": args.target_p95, "errors": 0},
        "passed": passed,
        "batch": "1 trace + 9 spans",
        "generator_processes": n,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.label}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
