#!/usr/bin/env bash
# #104 runtime pin. Reads the kg-mcp gateway's /health JSON on stdin and exits 0
# ONLY when the scoped server reports the deployed profile, semantic /query
# enabled AND answer synthesis working (llm == "ok", #121); otherwise exits 1 and
# prints what it saw (names and states only — the health body carries no secrets).
#
# llm: the scoped server runs one tiny completion at boot and updates the state on
# every /query. A plane that retrieves but cannot synthesize (#14271: the LLM 404'd and
# kg_query answered 200 "None") is RED here, as is LLM_BINDING=none (retrieval-only).
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
    and .scoped_server.llm == "ok"
  ' >/dev/null 2>&1; then
  echo "semantic gate: OK (config=deployed, semantic=enabled, llm=ok)"
  exit 0
fi
seen="$(printf '%s' "$body" | jq -r '
    if (.scoped_server | type) == "object" then
      "config=\(.scoped_server.config // "<missing>"), semantic=\(.scoped_server.semantic // "<missing>"), reason=\(.scoped_server.semantic_reason // "-"), llm=\(.scoped_server.llm // "<missing>"), llm_reason=\(.scoped_server.llm_reason // "-")"
    else "no scoped_server object in /health" end
  ' 2>/dev/null | tr -s '[:space:]' ' ')"
echo "semantic gate: FAIL (${seen:-/health body is not JSON})"
exit 1
