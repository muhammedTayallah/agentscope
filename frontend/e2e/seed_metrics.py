"""Seed the Phase 4 metrics dataset into a new project and print its id. Run from backend/:

    uv run python ../frontend/e2e/seed_metrics.py "<project name>"

Same rows as backend/tests/test_metrics_api.py (minus the out-of-window trace), placed
3 and 2 days ago so they fall inside "Last 7 days". Hand-computed totals, checked by
e2e/metrics.mjs:
  runs 6, failed 2 (33%), p50 300 ms, p95 880 ms, p99 976 ms
  tokens 6,500 in / 1,800 out, cost $0.035 (sonnet $0.023 + opus $0.012), gemini unpriced
  day A: 3 runs, 1 failed, p50 200 ms, p95 290 ms, $0.023
  day B: 3 runs, 1 failed, p50 700 ms, p95 970 ms, $0.012
"""

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import get_settings

API = os.environ.get("API_URL", "http://localhost:8000")
admin = {"Authorization": f"Bearer {get_settings().admin_token.get_secret_value()}"}
name = sys.argv[1] if len(sys.argv) > 1 else "Metrics demo"

created = httpx.post(f"{API}/projects", json={"name": name}, headers=admin).raise_for_status()
project_id = created.json()["project"]["id"]
key = {"Authorization": f"Bearer {created.json()['api_key']['key']}"}

today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
d0 = today - timedelta(days=3)
rows = [
    (0, 10, 100, "ok", ("claude-sonnet-5-5", 1000, 500)),
    (0, 11, 200, "ok", ("claude-sonnet-5-5", 3000, 1000)),
    (0, 12, 300, "error", None),
    (1, 9, 400, "ok", ("claude-opus-5-5", 2000, 200)),
    (1, 9.5, 1000, "error", ("gemini-3.8-flash", 500, 100)),
    (1, 10, None, "ok", None),
]
traces, spans = [], []
for day, hour, ms, status, llm in rows:
    start = d0 + timedelta(days=day, hours=hour)
    tid = str(uuid.uuid4())
    end = start + timedelta(milliseconds=ms) if ms is not None else None
    traces.append(
        {
            "id": tid,
            "name": f"seeded-{day}-{hour}",
            "status": status,
            "start_time": start.isoformat(),
            "end_time": end.isoformat() if end else None,
        }
    )
    if llm:
        model, tin, tout = llm
        spans.append(
            {
                "id": str(uuid.uuid4()),
                "trace_id": tid,
                "name": "llm",
                "kind": "llm",
                "model": model,
                "input_tokens": tin,
                "output_tokens": tout,
                "start_time": start.isoformat(),
                "end_time": (end or start).isoformat(),
            }
        )
httpx.post(f"{API}/v1/ingest", json={"traces": traces, "spans": spans}, headers=key).raise_for_status()
print(project_id)
