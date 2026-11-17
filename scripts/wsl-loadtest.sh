#!/usr/bin/env bash
# Phase 7 load test, run inside WSL Linux (API, Postgres and the generator on one Linux box).
#   wsl -d Ubuntu-24.04 -u root -- bash scripts/wsl-loadtest.sh <label> [rate] [duration] [workers]
# Needs Postgres + Redis running (scripts/services.ps1 start) and uv in the distro.
set -euo pipefail
LABEL="${1:?label}"; RATE="${2:-200}"; DURATION="${3:-60}"; WORKERS="${4:-4}"
cd "$(dirname "$0")/../backend"

# Linux venv and caches live inside the WSL disk, apart from the Windows .venv.
export UV_PROJECT_ENVIRONMENT=/root/.venvs/agentscope-backend
export UV_CACHE_DIR=/root/.cache/uv UV_PYTHON_PREFERENCE=only-system UV_LINK_MODE=copy
export PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1
uv sync --frozen -q  # dev deps: the load generator uses httpx

uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers "$WORKERS" \
  --log-level warning --no-access-log &
API=$!
trap 'kill $API 2>/dev/null; wait $API 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8100/health >/dev/null && break
  sleep 1
done

uv run --no-sync python scripts/loadtest.py --base http://127.0.0.1:8100 \
  --rate "$RATE" --duration "$DURATION" --label "$LABEL"
