# Deploying AgentScope

AgentScope ships as **one Docker image** (`/Dockerfile`): the FastAPI backend serves the built React UI at `/` and the API at `/api`. Migrations run on start. The ARQ worker can run inside the same process (`RUN_WORKER=true`), so a single web service is enough.

## Render (free tier)

`render.yaml` is a Render Blueprint with three resources:

| Resource | What it is |
|---|---|
| `agentscope` | Docker web service: UI, API and the ARQ worker in-process (`RUN_WORKER=true`) |
| `agentscope-db` | Postgres 16 (free: expires 30 days after creation) |
| `agentscope-redis` | Key Value (Redis) for the job queue, private and `noeviction` |

Steps:

1. Push this repository to GitHub.
2. In Render: **New → Blueprint →** pick the repository. Render reads `render.yaml`.
3. When asked, paste **`GEMINI_API_KEY`** (used by the LLM judge in eval runs).
4. Wait for the first deploy. `autoDeployTrigger: checksPass` means later pushes to `main` deploy only after CI passes.
5. Open the service URL and sign in with **`ADMIN_TOKEN`**. Render generates it; find it under the service's **Environment** tab.

After that:

```bash
# create a project; its key is in the response
curl -X POST https://<your-service>.onrender.com/api/projects \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "Support agent"}'

# point the SDK (or the demo agent / eval CLI) at the deployment
export AGENTSCOPE_HOST=https://<your-service>.onrender.com/api
export AGENTSCOPE_API_KEY=ask_...
```

Free-tier caveats: the service sleeps after 15 idle minutes (the first request takes about a minute to wake it), the SDK's background sender retries meanwhile, and free Postgres is deleted after 30 days unless upgraded.

## Any other host

Run the image with:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Postgres 16; `postgres://` / `postgresql://` URLs are accepted |
| `REDIS_URL` | Redis 6+ |
| `ADMIN_TOKEN` | a long random string |
| `PORT` | port to listen on (default 10000) |
| `RUN_WORKER` | `true` for one service; otherwise also run `arq app.workers.main.WorkerSettings` from the same image |
| `GEMINI_API_KEY`, `JUDGE_MODEL`, `MODEL_PRICES` | optional: the eval judge and cost metrics |

The health check is `GET /api/health`.
