#!/usr/bin/env bash
# #104 runtime pin. Reads the kg-mcp gateway's /health JSON on stdin and exits 0
# ONLY when the scoped server reports the deployed profile AND semantic /query
# enabled; otherwise exits 1 and prints what it saw (names and states only — the
# health body carries no secrets).
#
# Why a runtime check: a Railway service variable overrides the image's
# `ENV SHRINE_CONFIG=deployed` (measured 2026-10-11: kg-mcp test had
# SHRINE_CONFIG=local), and no unit test on the Dockerfile can see that.
#
# jq makes the decision; bash never splits fields (splitting on whitespace let an
# empty field shift the next one into its slot — a measured false green).
set -uo pipefail

body="$(cat)"
if printf '%s' "$body" | jq -e '
    (.scoped_server | type == "object")
    and .scoped_server.config == "deployed"
    and .scoped_server.semantic == "enabled"
  ' >/dev/null 2>&1; then
  echo "semantic gate: OK (config=deployed, semantic=enabled)"
  exit 0
fi
seen="$(printf '%s' "$body" | jq -r '
    if (.scoped_server | type) == "object" then
      "config=\(.scoped_server.config // "<missing>"), semantic=\(.scoped_server.semantic // "<missing>"), reason=\(.scoped_server.semantic_reason // "-")"
    else "no scoped_server object in /health" end
  ' 2>/dev/null | tr -s '[:space:]' ' ')"
echo "semantic gate: FAIL (${seen:-/health body is not JSON})"
exit 1
