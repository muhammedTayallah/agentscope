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
