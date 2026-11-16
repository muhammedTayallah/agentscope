# Design decisions

## 2026-11-16: Phase 1 scaffold, projects and API keys

- **Local dev without Docker.** Docker can't pull Docker Hub images on this machine (see TaskPilot's decisions for the details), so local Postgres 16 and Redis run natively in the existing WSL distro on E: (`Ubuntu-24.04`, shared with TaskPilot). AgentScope has its own role and databases (`agentscope`, `agentscope_test`), set up by `scripts/wsl-setup.sh`. `scripts/services.ps1 start` keeps WSL awake. `docker-compose.yml` stays the reference runtime, and the **CI `compose` job** runs `docker compose up --wait` plus the Phase 1 smoke test, since it can't run locally.
- **API keys:** `ask_` + 256 random bits (`secrets.token_urlsafe(32)`). Only a SHA-256 hash (unique index) and a 12-character display prefix are stored. A fast hash is right here: unlike passwords, a 256-bit random key can't be brute-forced, and a slow hash would cost every ingestion request. The full key is returned once, at creation. Keys can be revoked (`revoked_at`); revoked keys get 401. Several keys per project allow rotation.
- **Two auth schemes, both `Authorization: Bearer`:**
  - **Management** (`/projects…`) uses a single `ADMIN_TOKEN` from env, compared in constant time. If it's empty, management returns 503 rather than running open. There are no user accounts yet; a dashboard login can replace this before deploy (Phase 8).
  - **SDK** (`/v1/…`) uses a project API key that resolves to its project. `GET /v1/project` lets the SDK check its config, and Phase 2 ingestion goes under `/v1`.
- **Health** checks Postgres (`SELECT 1`) and Redis (`PING`) and returns 503 with per-dependency status if either fails.
- **Worker:** ARQ with one `ping` job for now. An integration test enqueues it on real Redis and runs a burst worker. In Compose the worker uses the backend image and waits for the backend to be healthy, because the backend runs the migrations.
- **Frontend:** only a status page (backend, database, Redis) through the Vite `/api` proxy. Project management is done through the API for now; the dashboard arrives in Phase 3.
- **Tests:** unit tests always run. Integration tests run when `TEST_DATABASE_URL` / `TEST_REDIS_URL` are set (from `.env` locally, from service containers in CI) and migrate the test database from scratch.
- **Caches on E::** `.cache/env.sh` points uv (Python installs, tools), npm and temp files at E:. The uv package cache is shared with the other portfolio projects at `E:\ai-agent-portfolio\.uv-cache`.

## 2026-11-16: Phase 2 ingestion API and SDK

- **Data model:** `traces` (one agent run) and `spans` (steps, with `parent_id` for nesting and `kind` = span / llm / tool). LLM spans carry `model`, `input_tokens` and `output_tokens`, so Phase 4 can compute cost. `input`, `output` and `metadata` are JSONB. `spans.parent_id` is **not** a foreign key: children finish, and so arrive, before their parents.
- **IDs come from the SDK** (UUIDv4), so `POST /v1/ingest` is an **upsert**. Retries are harmless, and a span can arrive before its trace. Such a trace gets a `(pending)` placeholder row that the real trace data later fills in. Duplicate IDs within one batch are de-duplicated (last one wins), since Postgres can't upsert a row twice in one statement.
- **Cross-project safety:** clients choose IDs, so a batch that references a trace or span ID owned by another project is rejected with **409**. The upserts' `WHERE project_id = excluded.project_id` also guarantees another project's rows are never overwritten.
- **Limits:** 500 traces and 500 spans per batch, timezone-aware timestamps required, errors capped at 10k characters. The SDK caps each input, output or metadata value at 50k characters of JSON.
- **Writes happen in the request** (a few multi-row upserts). Moving ingestion onto the ARQ queue is a Phase 7 load-test decision, made only if measurements call for it.
- **SDK (`agentscope_sdk`, distribution `agentscope-sdk`):**
  - API: `trace()` / `span()` context managers and an `@observe` decorator (sync and async). Nesting comes from `contextvars`. Errors are recorded and re-raised. Anything unserialisable becomes `repr()`.
  - Delivery: a bounded queue (10k) and a daemon thread that sends batches every second or every 100 events. 5xx, 429 and network errors are retried 3 times with backoff, then dropped with a warning. Other 4xx (bad key, invalid data) are dropped at once. Nothing raises into user code.
  - Exit and flush: `flush(timeout)` waits for delivery and warns if events are still unsent. At exit the SDK flushes for at most 2 s.
  - Import name `agentscope_sdk`, because `agentscope` is an existing, unrelated PyPI package.
- **Unreachable server, measured on Windows:** the demo script runs normally and exits 0. Exit is delayed by about 7 s (its own `flush(5)` plus the 2 s exit flush), because refused connections take about 2 s each on Windows. Both flushes log "events still unsent".
- **Phase 2 "done when" is tested automatically:** `tests/test_sdk_end_to_end.py` runs the real SDK against the real app (Starlette `TestClient` as the SDK's HTTP client) and the real database, then checks the stored tree, timestamps, tokens and tool input/output. The backend uses the SDK as an editable dev dependency.

## 2026-11-16: Phase 3 runs list and span tree UI

- **Read API** (admin token, like management): `GET /projects/{id}/traces` takes `q` (case-insensitive name substring with LIKE wildcards escaped), `status`, `limit` (≤ 200) and `offset`, and returns `{items, total}`. Each run includes its span count and token totals. `GET /projects/{id}/traces/{trace_id}` returns the trace with all spans, ordered by start time. Another project's run gets 404.
- **Shortcuts, noted in code:** offset paging, and per-project span aggregation on every list request. Both are fine at demo scale; the Phase 7 load test decides whether to move to keyset paging or a per-page/stored aggregate.
- **Dashboard auth:** sign in with the server's `ADMIN_TOKEN`, checked against `GET /projects` and kept in `localStorage`. A 401 on a saved token signs out. This is single-admin by design until accounts are needed (Phase 8).
- **Tree built on the client** (`lib/tree.ts`, unit tested). Spans whose parent is missing become roots, so nothing is hidden. Self-parents and cycles can't hang the page. Siblings are ordered by start time. Each row has a timeline bar placed relative to the run, coloured by kind (LLM violet, tool amber, error red).
- **URL state:** filters, page and the selected span (`?span=`) live in the URL, so reloads and shared links open the same view.
- **No data-fetching library:** a 20-line `useFetch` hook covers this phase. React Router is the only new frontend dependency.
- **Dev port 5180:** DocuMind and HireFlow both use 5173, and running them side by side made the AgentScope check hit HireFlow's server. Compose, CORS and CI use 5180 too.
- **Python pinned to 3.12** (`backend/.python-version`). Without a pin, uv had picked its newest managed Python (3.14), unlike CI and Docker.
- **Verification:** `frontend/e2e/send_trace.py` sends a 6-span trace through the SDK (including an error span). `frontend/e2e/flow.mjs` (Playwright) then checks sign-in, rejection of a wrong token, project switching, search, the exact tree nesting, collapse/expand, the span details (model, tokens, input/output, error), URL state across a reload, and a phone-sized layout.

## 2026-11-16: Phase 4 metrics and charts

- **`GET /projects/{id}/metrics?start&end&bucket`** (admin token). Defaults: the last 7 days, hourly buckets for windows up to 2 days and daily otherwise, at most 1000 buckets. Buckets are cut in UTC (`date_trunc` on `timezone('UTC', …)`, independent of the DB session time zone). Empty buckets come back as zeros, so the time axis is continuous.
- **What's counted:**
  - Runs and errors come from traces, bucketed by trace start.
  - Latency is trace duration, as `percentile_cont` p50/p95/p99 over finished traces only; a running trace counts as a run but not toward latency.
  - Tokens and cost come from spans, bucketed by span start: LLM spans, plus any span that reports tokens.
- **Prices** (`core/pricing.py`) are in USD per 1M tokens. Built-in defaults cover Anthropic's current models (list prices). Gemini and anything else go in `MODEL_PRICES` (a JSON env var). **Unpriced models are reported as unpriced, never as $0**, and listed so the gap is visible. Shortcut, noted in code: Haiku 5.5's higher rate for prompts over 100K tokens isn't applied.
- **"Done when" is checked twice:**
  - `tests/test_metrics_api.py` seeds a 7-trace dataset whose expected numbers are worked out by hand in its docstring, then asserts them exactly: runs 6, error rate 1/3, p50/p95/p99 300/880/976 ms, per-day p50/p95, cost per model and per day. It also covers configured prices, the hourly grid, defaults, validation and project isolation.
  - `frontend/e2e/seed_metrics.py` + `e2e/metrics.mjs` load the same dataset into a live server, and Playwright reads the same numbers off the dashboard: tiles, usage table and the time-series table. It also checks that every chart draws marks, that tooltips work, and the range switch.
- **Chart design**, following the dataviz method:
  - Forms: stat tiles for the headline numbers; stacked columns for volume (successful runs in series blue, failures in status-critical red); one latency chart with p50/p95 lines on a single axis (no dual axis); labelled horizontal bars for cost by model; a usage table and a collapsible time-series table as the accessible text view.
  - Colors: the two pairs used (blue/critical red, blue/orange) pass the palette validator on the white card surface.
  - Marks and text: tooltip and legend text stay in ink colors; bars are at most 24px wide with a 2px surface gap and rounded data ends; dots are filled with a surface ring; lines don't bridge empty buckets.
  - Light theme only, like the rest of the app.
- **Windows quirk:** Vitest fails ("failed to find the current suite") when started from a lowercase `e:\` path, as VS Code sometimes opens the folder. Running from `E:\…` works, and CI on Linux is unaffected.
- **Phase 3 bug fixed:** the header's project switcher read the project from `useParams`, which a layout route can't see, so it never showed the current project. It now uses `useMatch`, and Runs | Metrics tabs were added.

## 2026-11-16: Phase 5 instrumented demo agent

- **What:** `evals/` is a third uv package (`agentscope-evals`) holding a customer-support agent for a fictional shop. Its tools are deterministic and local (`search_kb`, `get_order`, a safe AST `calculate`), so Phase 6 evals are repeatable and need no network apart from the LLM.
- **LLM:** Gemini via `google-genai`, default `gemini-3.5-flash-lite` (was `gemini-3.8-flash` until the comparison below) (`--model` / `AGENT_MODEL` to change). It uses a **hand-written function-calling loop** with automatic function calling disabled, so every model call and every tool call is its own span. The model's turn is appended unchanged, because Gemini 3 needs its thought signatures back. Each function response carries the call's `id`.
- **Trace layout:** a `support-agent` trace (input: question; output: answer; metadata: `agent_version`, `model`), then alternating `gemini` (llm) and tool spans. LLM spans record `input_tokens = prompt_token_count` and `output_tokens = candidates + thoughts`, since Google bills thinking as output.
- **Errors:** a tool error (unknown order, bad expression, unknown tool or bad arguments) marks its span as an error and is returned to the model as `{"error": …}`, so the agent can recover. Model errors and hitting the step limit (6 calls) mark the trace as failed.
- **`agent_version`** goes on every trace now, so Phase 6 can compare versions.
- **Gemini price:** `MODEL_PRICES={"gemini-3.8-flash": [0.75, 3.75]}` in `.env` / `.env.example`, from Google's pricing page. That's the paid Standard tier with thinking included in output, valid **through 2026-12-31**; it rises to $1.50 / $7.50 on 2027-01-01. It's kept in config, not code, so the change is a one-line edit.
- **Test isolation fix:** backend test settings are built with `_env_file=None`. pydantic-settings deep-merges dictionaries, so `.env`'s `MODEL_PRICES` leaked into the tests even when they passed `{}`.
- **CLI:** `uv run python -m agentscope_evals "question"` reads only its four keys (`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `AGENTSCOPE_API_KEY`, `AGENTSCOPE_HOST`) from the repo `.env`; shell variables win.
- **Tests:** 17, using a scripted Gemini client that returns real `google-genai` types and an SDK recorder. They cover the full tool loop, the request contents sent back to the model, span kinds, tokens and nesting, tool-error recovery, the step limit and model failure.
- **Live verification (2026-11-16):** `gemini-3.8-flash` returned **503 "high demand"** on every attempt, after the SDK's own retries; the failed runs were traced as failed, with 0 tokens. `gemini-3.6-flash` (same price, $0.75 / $3.75 until 2026-12-31) worked, so the live runs used `--model gemini-3.6-flash`; the default stays 3.8. Results:
  - Refund question: `get_order` and `search_kb` called in parallel, answered correctly.
  - Unknown order B7777: the tool error was returned to the model, which asked the customer to check the id.
  - Express shipping: `search_kb` then `calculate` (40 + 12 = 52), 3 model calls.
  - The dashboard shows each run's llm and tool spans with tokens, inputs and outputs. Metrics showed cost $0.009, matching (3,837 × 0.75 + 1,635 × 3.75) / 1e6, with latency p50 29 s and p95 2 m (individual Gemini calls took 30-56 s at the time).
- The CLI prints one line on failure (the run is already traced) and uses ASCII in its status line, because the Windows console mangled `·`.
- **Flash-Lite comparison (2026-11-16):** the same 4 questions on `gemini-3.5-flash-lite` (`$0.30 / $2.50`, no date change; added to `MODEL_PRICES`) were all answered correctly, including the tool-error recovery. Measured from the traces:

  | model | avg run latency | avg tokens in / out | cost per run |
  |---|---|---|---|
  | gemini-3.6-flash | 105 s | 959 / 409 | $0.00225 |
  | gemini-3.5-flash-lite | 9 s | 1,017 / 76 | $0.00050 |

  Flash-Lite thinks far less (fewer output tokens) and made one redundant `search_kb` call, but it was about 11× faster and 4.5× cheaper with no loss of correctness on these questions. This is a 4-question sample, not an eval; Phase 6 is where the versions get compared properly.
