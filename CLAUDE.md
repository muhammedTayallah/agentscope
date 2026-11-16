# AgentScope

A small self-hosted observability and evaluation platform for LLM agents (a mini Langfuse). Agents send traces through our Python SDK; a dashboard shows runs, nested spans, cost, latency and errors, and runs eval datasets to compare agent versions.

## Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic
- **Database:** PostgreSQL 16
- **Background jobs:** Redis + ARQ
- **Frontend:** React + Vite + TypeScript + Tailwind + Recharts
- **Infra:** Docker Compose
- **LLM-as-judge:** Google Gemini (`google-genai` SDK, default `gemini-3.8-flash`), with the Anthropic SDK as an alternative provider. Provider, model and keys come from env vars (`JUDGE_PROVIDER`, `JUDGE_MODEL`, `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`). Never hardcode them.
- **SDK:** `sdk/` is its own uv package, `agentscope-sdk`.

## Rules

- Use **uv** for all Python work (`uv init`, `uv add`, `uv run`). Never use pip.
- **Never write anything to the C: drive.** Everything stays inside this project folder on E:, including caches, virtualenvs, temp files and tool output.
- Write tests for everything: pytest for the backend and SDK, Vitest for the frontend. Lint with **ruff**.
- Secrets go only in `.env`. Keep `.env.example` updated with every variable, using placeholder values.
- Record important design decisions in `docs/decisions.md`.
- **Work one phase at a time** (see `PLAN.md`). Stop when the phase's "Done when" is met. Never start the next phase on your own.

## Layout

```
backend/
  app/
    api/        # FastAPI routers
    core/       # config, security, logging
    db/         # models, session, Alembic migrations
    services/   # business logic
    workers/    # ARQ jobs
  tests/
sdk/            # agentscope-sdk (separate uv package)
frontend/
  src/
evals/
docs/
```
