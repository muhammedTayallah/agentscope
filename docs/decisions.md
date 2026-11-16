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
