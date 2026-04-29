#!/usr/bin/env bash
# DietResearchBench-Clinical v1 lifecycle runner.
#
# Why this exists: the v1 2026-04-25 run silently emitted all-zero results
# because the LightRAG server wasn't running. This script enforces the
# correct sequence:
#   1. Load .env (Aura creds + OpenRouter key)
#   2. Start scoped_server in the background
#   3. Wait for /health to come up (bounded — bail if it never does)
#   4. Hand off to eval/runner.py, which runs its OWN preflight gate before
#      executing any baseline. The gate is *also* enforced inside the runner
#      so direct python invocations get the same protection.
#   5. Always tear down the server, even on error.
#
# Usage:
#   bash scripts/run_v1_eval.sh                    # full 6-baseline matrix on test split
#   SYSTEMS=diet_os bash scripts/run_v1_eval.sh    # subset
#
# Exit codes:
#   0  success
#   1  setup error (.env missing, server failed to come up)
#   2  preflight gate or runner failure
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ─── Load .env ────────────────────────────────────────────────────────────
if [[ ! -f ./.env ]]; then
  echo "ERROR: ./.env missing — copy from .env.template and fill in Aura + OpenRouter." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${NEO4J_URI:?NEO4J_URI not set in .env}"
: "${NEO4J_USERNAME:?NEO4J_USERNAME not set in .env}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD not set in .env}"
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY not set in .env}"

# ─── Start LightRAG server in background ──────────────────────────────────
LIGHTRAG_PORT="${LIGHTRAG_PORT:-9621}"
LIGHTRAG_URL="http://localhost:${LIGHTRAG_PORT}"
SERVER_LOG="$(mktemp -t lightrag-server-XXXXXX.log)"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Tearing down LightRAG server (pid=$SERVER_PID)..." >&2
    kill "$SERVER_PID" 2>/dev/null || true
    # Give it 5s to exit gracefully, then SIGKILL
    for _ in 1 2 3 4 5; do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$SERVER_PID" 2>/dev/null || true
  fi
  echo "Server log preserved at: $SERVER_LOG" >&2
}
trap cleanup EXIT INT TERM

echo "Starting LightRAG scoped_server on :${LIGHTRAG_PORT} (log: $SERVER_LOG)..." >&2
(
  cd "$ROOT/lightrag" && \
  exec uvicorn scoped_server:app --host 0.0.0.0 --port "$LIGHTRAG_PORT"
) >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
echo "Server pid=$SERVER_PID" >&2

# ─── Wait for /health ──────────────────────────────────────────────────────
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-90}"
echo "Waiting up to ${HEALTH_TIMEOUT}s for ${LIGHTRAG_URL}/health..." >&2
for i in $(seq 1 "$HEALTH_TIMEOUT"); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "ERROR: server process died before becoming healthy. Tail of log:" >&2
    tail -40 "$SERVER_LOG" >&2 || true
    exit 1
  fi
  if curl -sf -m 2 "${LIGHTRAG_URL}/health" >/dev/null 2>&1; then
    echo "Server healthy after ${i}s." >&2
    break
  fi
  if [[ "$i" -eq "$HEALTH_TIMEOUT" ]]; then
    echo "ERROR: server did not become healthy within ${HEALTH_TIMEOUT}s. Tail of log:" >&2
    tail -40 "$SERVER_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done

export LIGHTRAG_URL

# ─── Run eval ─────────────────────────────────────────────────────────────
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="../research-journal/shared/results/${TS}"
echo "Running eval — output: ${OUT_DIR}" >&2

SYSTEMS_FLAG=()
if [[ -n "${SYSTEMS:-}" ]]; then
  SYSTEMS_FLAG=(--systems "$SYSTEMS")
fi

# The runner runs its own preflight gate before any baseline executes.
# Exit code 2 on preflight failure or runner exception.
python3 -m eval.runner \
  --bench ../research-journal/shared/datasets/dietresearchbench_v1.json \
  --splits ../research-journal/shared/datasets/splits_seed42.json \
  --out "$OUT_DIR" \
  "${SYSTEMS_FLAG[@]}"

echo "Run complete: $OUT_DIR" >&2
echo "$OUT_DIR"
