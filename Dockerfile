# syntax=docker/dockerfile:1
# AgentScope production image: the FastAPI backend serving the built React UI at / and the
# API at /api. Set RUN_WORKER=true to also run the ARQ worker in-process (single-service
# hosts); otherwise run `arq app.workers.main.WorkerSettings` from this image separately.
# Config comes from environment variables only (no .env inside the image).

# ---- 1. frontend build -------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Python dependencies (uv) ---------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS python
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Lockfile first so the dependency layer is cached until it changes. The SDK is a dev-only
# path dependency of the backend; it's copied so uv can read the lockfile's sources.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version backend/
COPY sdk/ sdk/
RUN cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend/ backend/
RUN cd backend && uv sync --frozen --no-dev

# ---- 3. runtime ---------------------------------------------------------------------------
# Same Python as the uv image above, so the venv's interpreter path (/usr/local/bin) matches.
FROM python:3.12-slim-bookworm AS runtime
RUN useradd --create-home --uid 10001 agentscope
COPY --from=python --chown=agentscope:agentscope /app/backend /app/backend
COPY --from=frontend --chown=agentscope:agentscope /src/frontend/dist /app/frontend/dist
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/frontend/dist \
    PORT=10000
USER agentscope
WORKDIR /app/backend
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
# Migrate, then serve. PORT is set by the host (Render: 10000 by default).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*'"]
