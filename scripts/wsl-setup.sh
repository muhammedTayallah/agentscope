#!/usr/bin/env bash
# One-time local setup inside the WSL distro (run as root): Redis + agentscope role and DBs.
# Usage: wsl -d Ubuntu-24.04 -u root -- bash scripts/wsl-setup.sh <db-password>
set -euo pipefail
PW="$1"
export DEBIAN_FRONTEND=noninteractive
command -v redis-server >/dev/null || { apt-get update -qq; apt-get install -y -qq redis-server; }
service redis-server start >/dev/null
psql_q() { su postgres -c "psql -qtAc \"$1\""; }
if [ "$(psql_q "SELECT 1 FROM pg_roles WHERE rolname='agentscope'")" = "1" ]; then
  psql_q "ALTER ROLE agentscope WITH LOGIN PASSWORD '$PW'"
else
  psql_q "CREATE ROLE agentscope LOGIN PASSWORD '$PW'"
fi
for db in agentscope agentscope_test; do
  [ "$(psql_q "SELECT 1 FROM pg_database WHERE datname='$db'")" = "1" ] || su postgres -c "createdb -O agentscope $db"
done
psql_q "SELECT string_agg(datname, ',') FROM pg_database WHERE datname LIKE 'agentscope%'"
redis-cli ping
