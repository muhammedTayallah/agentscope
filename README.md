# AgentScope

A small self-hosted observability and evaluation platform for LLM agents (a mini Langfuse). Agents send traces through the Python SDK; a dashboard shows runs, nested spans, cost, latency and errors, and runs eval datasets to compare agent versions.

**Status:** Phase 2 (ingestion API + SDK) of [PLAN.md](PLAN.md) is done.

## Run with Docker

```bash
cp .env.example .env      # set POSTGRES_PASSWORD and ADMIN_TOKEN
docker compose up --build
```

Services: frontend http://localhost:5173 · API http://localhost:8000 (docs at `/docs`) · Postgres 5432 · Redis 6379 · ARQ worker.

## Run locally without Docker (Windows + WSL)

```powershell
wsl -d Ubuntu-24.04 -u root -- bash scripts/wsl-setup.sh <db-password>   # once
.\scripts\services.ps1 start                                              # Postgres + Redis
```

```bash
source .cache/env.sh          # Git Bash: keep caches on E:
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload                 # API
uv run arq app.workers.main.WorkerSettings           # worker (second terminal)
cd ../frontend && npm install && npm run dev         # UI (third terminal)
```

## Projects and API keys

Management calls need `Authorization: Bearer $ADMIN_TOKEN`:

```bash
# Create a project; the response contains its first API key. It's shown only once, so save it.
curl -X POST localhost:8000/projects -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" -d '{"name": "My agent"}'

curl localhost:8000/projects -H "Authorization: Bearer $ADMIN_TOKEN"
curl -X POST   localhost:8000/projects/<id>/api-keys -H "Authorization: Bearer $ADMIN_TOKEN"            # extra key
curl -X DELETE localhost:8000/projects/<id>/api-keys/<key_id> -H "Authorization: Bearer $ADMIN_TOKEN"   # revoke
```

SDK calls use a project key:

```bash
curl localhost:8000/v1/project -H "Authorization: Bearer ask_..."   # 200 with the project, 401 if invalid or revoked
```

## Sending traces

Use the Python SDK in [`sdk/`](sdk/README.md) (`agentscope-sdk`):

```python
from agentscope_sdk import AgentScope

scope = AgentScope()   # AGENTSCOPE_API_KEY, AGENTSCOPE_HOST

with scope.trace("support-run", input=question) as run:
    with scope.span("llm-call", kind="llm", model="gemini-3.8-flash") as llm:
        llm.update(output=reply, input_tokens=120, output_tokens=12)
    run.update(output=reply)
```

It posts batches to `POST /v1/ingest` (`{"traces": [...], "spans": [...]}`, up to 500 each), which upserts by ID.

## Tests

```bash
cd backend && uv run ruff check . && uv run pytest     # integration tests use TEST_DATABASE_URL / TEST_REDIS_URL
cd sdk && uv run ruff check . && uv run pytest
cd frontend && npm test
```

CI runs all three suites, plus a `docker compose up` smoke test.

Design decisions: [docs/decisions.md](docs/decisions.md).
