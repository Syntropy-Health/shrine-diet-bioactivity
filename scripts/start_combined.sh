#!/usr/bin/env bash
# Combined-service entrypoint: scoped_server (internal :9621) + MCP gateway
# (FastMCP streamable-http on $PORT). Runs as PID 1 in the Railway container.
#
# Lifecycle:
#   1. Start scoped_server in background.
#   2. Wait for it to become healthy on :9621/health.
#   3. Start MCP gateway in foreground bound to $PORT.
#   4. If either dies, exit non-zero so Railway restarts the container.
set -euo pipefail

INTERNAL_PORT="${INTERNAL_LIGHTRAG_PORT:-9621}"
EXTERNAL_PORT="${PORT:-8080}"
HEALTH_URL="http://127.0.0.1:${INTERNAL_PORT}/health"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"

cleanup() {
  echo "[start_combined] shutting down..." >&2
  if [[ -n "${LIGHTRAG_PID:-}" ]] && kill -0 "$LIGHTRAG_PID" 2>/dev/null; then
    kill "$LIGHTRAG_PID" 2>/dev/null || true
    wait "$LIGHTRAG_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ─── 1. Start scoped_server ──────────────────────────────────────────────
echo "[start_combined] starting scoped_server on :${INTERNAL_PORT}" >&2
cd /app/lightrag
uvicorn scoped_server:app --host 127.0.0.1 --port "$INTERNAL_PORT" &
LIGHTRAG_PID=$!
echo "[start_combined] scoped_server pid=$LIGHTRAG_PID" >&2

# ─── 2. Wait for /health ──────────────────────────────────────────────────
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
  if ! kill -0 "$LIGHTRAG_PID" 2>/dev/null; then
    echo "[start_combined] ERROR: scoped_server died before becoming healthy" >&2
    exit 1
  fi
  if curl -fsS -m 2 "$HEALTH_URL" >/dev/null 2>&1; then
    echo "[start_combined] scoped_server healthy after ${i}s" >&2
    break
  fi
  if [[ "$i" -eq "$HEALTH_TIMEOUT" ]]; then
    echo "[start_combined] ERROR: scoped_server did not become healthy in ${HEALTH_TIMEOUT}s" >&2
    exit 1
  fi
  sleep 1
done

# ─── 3. Start MCP gateway in foreground ──────────────────────────────────
# FastMCP supports `streamable-http` transport on a configurable host/port.
# kg_mcp.server.main() reads PORT/HOST from env (or its own CLI). We bind
# 0.0.0.0:$PORT so Railway's edge can route to us.
export LIGHTRAG_URL="${LIGHTRAG_URL:-http://127.0.0.1:${INTERNAL_PORT}}"
export MCP_HOST="0.0.0.0"
export MCP_PORT="$EXTERNAL_PORT"
export MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"

cd /app
echo "[start_combined] starting MCP gateway (transport=$MCP_TRANSPORT) on :${EXTERNAL_PORT}" >&2
exec python -m kg_mcp.server
