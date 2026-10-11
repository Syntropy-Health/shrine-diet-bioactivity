#!/usr/bin/env bash
# #104 runtime pin. Reads the kg-mcp gateway's /health JSON on stdin and exits 0
# ONLY when the scoped server reports the deployed profile AND semantic /query
# enabled; otherwise exits 1 and prints what it saw (names and states only — the
# health body carries no secrets).
#
# Why a runtime check: a Railway service variable overrides the image's
# `ENV SHRINE_CONFIG=deployed` (measured 2026-10-11: kg-mcp test had
# SHRINE_CONFIG=local), and no unit test on the Dockerfile can see that.
set -uo pipefail

body="$(cat)"
if ! printf '%s' "$body" | jq -e . >/dev/null 2>&1; then
  echo "semantic gate: /health body is not JSON"
  exit 1
fi

read -r cfg sem reason < <(
  printf '%s' "$body" | jq -r '[
    (.scoped_server.config // "<missing>"),
    (.scoped_server.semantic // "<missing>"),
    (.scoped_server.semantic_reason // "-")
  ] | map(gsub("\\s+"; "_")) | join(" ")'
)

if [[ "$cfg" == "deployed" && "$sem" == "enabled" ]]; then
  echo "semantic gate: OK (config=deployed, semantic=enabled)"
  exit 0
fi
echo "semantic gate: FAIL (config=$cfg, semantic=$sem, reason=${reason//_/ })"
exit 1
