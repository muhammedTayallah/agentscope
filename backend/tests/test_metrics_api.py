"""Phase 4 "done when": metrics match totals computed by hand for a seeded dataset.

Window: 2026-11-10 00:00 to 2026-11-12 00:00 UTC, two day buckets.

  trace  start (UTC)    duration  status   llm span (model, in, out)
  T1     11-10 10:00     100 ms   ok       sonnet-5-5   1000 / 500
  T2     11-10 11:00     200 ms   ok       sonnet-5-5   3000 / 1000
  T3     11-10 12:00     300 ms   error    -
  T4     11-11 09:00     400 ms   ok       opus-5-5     2000 / 200
  T5     11-11 09:30    1000 ms   error    gemini-3.8   500 / 100
  T6     11-11 10:00   (running)  ok       -
  outside: T7 at 11-12 00:00 (end is exclusive) and T8 in another project.

Hand-computed (percentile_cont = linear interpolation between ranks):
  runs 6, errors 2, error rate 1/3
  latency over [100,200,300,400,1000]: p50 300; p95 rank 3.8 -> 400 + .8*600 = 880;
                                       p99 rank 3.96 -> 400 + .96*600 = 976
  day 11-10: runs 3, errors 1, [100,200,300] -> p50 200, p95 rank 1.9 -> 290
  day 11-11: runs 3, errors 1, [400,1000]    -> p50 700, p95 400 + .95*600 = 970
  cost ($/1M tokens: sonnet 2/10, opus 4/20):
    sonnet (1000*2 + 500*10 + 3000*2 + 1000*10)/1e6 = 0.023
    opus   (2000*4 + 200*20)/1e6                     = 0.012
    gemini unpriced by default; with 0.5/3.0: (500*.5 + 100*3)/1e6 = 0.00055
  tokens in 6500, out 1800
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.main import app
from tests.conftest import ADMIN_TOKEN
from tests.test_ingest_api import new_key

D0 = datetime(2026, 11, 10, tzinfo=UTC)
WINDOW = {"start": D0.isoformat(), "end": (D0 + timedelta(days=2)).isoformat()}


def at(day: int, hour: float) -> datetime:
    return D0 + timedelta(days=day, hours=hour)


async def seed(db_client, key, other_key):
    rows = [
        # (start, duration_ms or None, status, (model, in, out) or None)
        (at(0, 10), 100, "ok", ("claude-sonnet-5-5", 1000, 500)),
        (at(0, 11), 200, "ok", ("claude-sonnet-5-5", 3000, 1000)),
        (at(0, 12), 300, "error", None),
        (at(1, 9), 400, "ok", ("claude-opus-5-5", 2000, 200)),
        (at(1, 9.5), 1000, "error", ("gemini-3.8-flash", 500, 100)),
        (at(1, 10), None, "ok", None),
        (at(2, 0), 50, "ok", ("claude-opus-5-5", 9999, 9999)),  # outside the window
    ]
    traces, spans = [], []
    for start, ms, status_, llm in rows:
        tid = uuid.uuid4()
        end = start + timedelta(milliseconds=ms) if ms is not None else None
        traces.append(
            {
                "id": str(tid),
                "name": "run",
                "status": status_,
                "start_time": start.isoformat(),
                "end_time": end.isoformat() if end else None,
            }
        )
        base = {"trace_id": str(tid), "start_time": start.isoformat()}
        spans.append({"id": str(uuid.uuid4()), "name": "search", "kind": "tool"} | base)
        if llm:
            model, tin, tout = llm
            spans.append(
                {"id": str(uuid.uuid4()), "name": "llm", "kind": "llm", "model": model}
                | {"input_tokens": tin, "output_tokens": tout}
                | base
            )
    resp = await db_client.post("/v1/ingest", json={"traces": traces, "spans": spans}, headers=key)
    assert resp.status_code == 202
    # Another project's data must not leak into the numbers.
    other = {
        "id": str(uuid.uuid4()),
        "name": "x",
        "status": "error",
        "start_time": at(0, 10).isoformat(),
        "end_time": at(0, 11).isoformat(),
    }
    await db_client.post("/v1/ingest", json={"traces": [other]}, headers=other_key)


@pytest.fixture
async def seeded(db_client, admin):
    pid, key = await new_key(db_client, admin, "metrics")
    _, other_key = await new_key(db_client, admin, "other")
    await seed(db_client, key, other_key)
    return pid


async def test_metrics_match_hand_computed_totals(db_client, admin, seeded):
    m = (
        await db_client.get(
            f"/projects/{seeded}/metrics", params=WINDOW | {"bucket": "day"}, headers=admin
        )
    ).json()

    assert (m["runs"], m["errors"]) == (6, 2)
    assert m["error_rate"] == pytest.approx(1 / 3)
    assert (m["p50_ms"], m["p95_ms"], m["p99_ms"]) == pytest.approx((300, 880, 976))
    assert (m["input_tokens"], m["output_tokens"]) == (6500, 1800)
    assert m["cost_usd"] == pytest.approx(0.035)
    assert m["unpriced_models"] == ["gemini-3.8-flash"]

    by_model = {u["model"]: u for u in m["by_model"]}
    assert set(by_model) == {"claude-sonnet-5-5", "claude-opus-5-5", "gemini-3.8-flash"}
    sonnet, opus, gemini = (
        by_model["claude-sonnet-5-5"],
        by_model["claude-opus-5-5"],
        by_model["gemini-3.8-flash"],
    )
    assert (sonnet["calls"], sonnet["input_tokens"], sonnet["output_tokens"]) == (2, 4000, 1500)
    assert sonnet["cost_usd"] == pytest.approx(0.023)
    assert opus["cost_usd"] == pytest.approx(0.012)
    assert gemini["cost_usd"] is None
    assert [u["model"] for u in m["by_model"]][:2] == ["claude-sonnet-5-5", "claude-opus-5-5"]

    day1, day2 = m["series"]
    assert day1["start"].startswith("2026-11-10T00:00:00") and day2["start"].startswith(
        "2026-11-11T00:00:00"
    )
    assert (day1["runs"], day1["errors"], day1["p50_ms"], day1["p95_ms"]) == pytest.approx(
        (3, 1, 200, 290)
    )
    assert (day2["runs"], day2["errors"], day2["p50_ms"], day2["p95_ms"]) == pytest.approx(
        (3, 1, 700, 970)
    )
    assert (day1["cost_usd"], day2["cost_usd"]) == pytest.approx((0.023, 0.012))


async def test_configured_price_makes_model_priced(db_client, admin, seeded):
    app.dependency_overrides[get_settings] = lambda: Settings(
        admin_token=SecretStr(ADMIN_TOKEN), model_prices={"gemini-3.8-flash": (0.5, 3.0)}
    )
    m = (await db_client.get(f"/projects/{seeded}/metrics", params=WINDOW, headers=admin)).json()
    assert m["unpriced_models"] == []
    assert m["cost_usd"] == pytest.approx(0.035 + 0.00055)


async def test_hour_buckets_are_continuous(db_client, admin, seeded):
    m = (
        await db_client.get(
            f"/projects/{seeded}/metrics", params=WINDOW | {"bucket": "hour"}, headers=admin
        )
    ).json()
    assert len(m["series"]) == 48  # empty hours are zero rows, not gaps
    by_start = {p["start"][:13]: p for p in m["series"]}
    assert by_start["2026-11-11T09"]["runs"] == 2
    assert by_start["2026-11-11T09"]["p50_ms"] == pytest.approx(700)
    assert by_start["2026-11-10T03"] == by_start["2026-11-10T03"] | {"runs": 0, "p50_ms": None}
    assert sum(p["runs"] for p in m["series"]) == 6


async def test_default_window_and_bucket(db_client, admin, seeded):
    m = (await db_client.get(f"/projects/{seeded}/metrics", headers=admin)).json()
    assert m["bucket"] == "day" and len(m["series"]) in (7, 8)
    short = {"start": D0.isoformat(), "end": (D0 + timedelta(hours=6)).isoformat()}
    m = (await db_client.get(f"/projects/{seeded}/metrics", params=short, headers=admin)).json()
    assert m["bucket"] == "hour" and len(m["series"]) == 6


async def test_empty_project_and_validation(db_client, admin):
    pid, _ = await new_key(db_client, admin, "empty")
    m = (await db_client.get(f"/projects/{pid}/metrics", params=WINDOW, headers=admin)).json()
    assert (m["runs"], m["error_rate"], m["p50_ms"], m["cost_usd"], m["by_model"]) == (
        0,
        None,
        None,
        0,
        [],
    )
    bad = [
        {"start": WINDOW["end"], "end": WINDOW["start"]},
        {
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-12-01T00:00:00+00:00",
            "bucket": "hour",
        },
        {"start": "2026-11-10T00:00:00"},  # no timezone
    ]
    for params in bad:
        resp = await db_client.get(f"/projects/{pid}/metrics", params=params, headers=admin)
        assert resp.status_code == 422, params
    assert (
        await db_client.get(f"/projects/{uuid.uuid4()}/metrics", headers=admin)
    ).status_code == 404
    assert (await db_client.get(f"/projects/{pid}/metrics")).status_code == 401
