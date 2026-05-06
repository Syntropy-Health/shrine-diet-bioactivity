<wizard-report>
# PostHog post-wizard report

The wizard has completed a deep integration of PostHog analytics into the `kg-mcp` Python MCP gateway service (`shrine-diet-bioactivity/mcp/`). A new `analytics.py` singleton module was added and three existing files were instrumented with event capture calls. All 69 unit tests continue to pass. No existing logic was altered — only additive PostHog calls were inserted alongside the business logic.

| Event | Description | File |
|---|---|---|
| `kg_query_executed` | Natural-language query executed against the LightRAG KG (Layer A) — captures `mode`, `top_k`, `answer_length`, `reference_count` | `src/kg_mcp/tools.py` |
| `kg_traversal_executed` | Role-priored deterministic KG traversal (Layer B: diet→compounds, compound→targets, herb→diseases, etc.) — captures `start_label`, `direction`, `depth`, `top_k`, `chain_count`, `node_count`, `edge_count` | `src/kg_mcp/tools.py` |
| `kg_hdi_check_executed` | Herb-drug interaction safety lookup (HDI-Safe-50 panel) — captures `found`, `has_severity`, `evidence_tier`, `citation_count` | `src/kg_mcp/tools.py` |
| `kg_bilingual_term_looked_up` | SymMap bilingual canonicalization (EN/CN/Pinyin) — captures `source`, `confidence_score`, `resolved_english/chinese/pinyin` | `src/kg_mcp/tools.py` |
| `kg_node_neighborhood_explored` | Generic bounded-depth subgraph dump (Layer C fallback) — captures `max_depth`, `max_nodes`, `result_node_count`, `result_edge_count` | `src/kg_mcp/tools.py` |
| `mcp_auth_failed` | Authentication attempt failed at the gateway — captures `failure_reason` (missing_bearer or invalid_token) and `path` | `src/kg_mcp/auth.py` |
| `mcp_server_started` | Server process started — captures `transport` (stdio/sse/streamable-http) | `src/kg_mcp/server.py` |
| `kg_tool_error` | A KG tool raised an unhandled exception — captures `tool_name`, `error_type` | `src/kg_mcp/tools.py` |

## Files changed

- **`src/kg_mcp/analytics.py`** _(new)_ — PostHog singleton (`Posthog` instance), `capture()` and `capture_exception()` helpers, `SERVER_DISTINCT_ID` / `AUTH_DISTINCT_ID` constants, atexit shutdown registration.
- **`src/kg_mcp/tools.py`** — Import of `analytics`; try/except wrappers around all 8 tool implementations to capture success events and re-raise with `kg_tool_error` + exception capture on failure.
- **`src/kg_mcp/auth.py`** — Import of `analytics`; `mcp_auth_failed` captured in `AuthMiddleware.dispatch` on both `missing_bearer` and `invalid_token` paths.
- **`src/kg_mcp/server.py`** — Import of `analytics`; `mcp_server_started` captured in `main()` after transport validation.
- **`pyproject.toml`** — Added `posthog>=3.0.0` to `[project.dependencies]`.
- **`.env`** — `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` written (gitignored).

## Next steps

We've instrumented all critical server-side actions. To visualize this data, create an **"Analytics basics"** dashboard in PostHog with the following five insights:

1. **KG tool call volume over time** — Trends chart: `kg_query_executed` + `kg_traversal_executed` + `kg_hdi_check_executed` + `kg_bilingual_term_looked_up` + `kg_node_neighborhood_explored` as separate series. Shows overall gateway usage.

2. **Tool mix breakdown** — Trends chart: all five tool events, broken down by event name. Reveals which KG layer (A/B/C) gets used most.

3. **Auth failure rate** — Trends chart: `mcp_auth_failed` total count over time, broken down by `failure_reason` property. Alerts on brute-force or misconfigured clients.

4. **Tool error rate** — Trends chart: `kg_tool_error` count over time, broken down by `tool_name` and `error_type`. Critical for catching upstream KG service degradation.

5. **HDI check hit rate** — Trends chart: `kg_hdi_check_executed` filtered by `found = true` vs. total. Shows how often the HDI panel actually returns a match.

Navigate to [Dashboards](/dashboard) → **New dashboard** → add each of the five insights above.

### Agent skill

We've left an agent skill folder in your project at `.claude/skills/integration-python/`. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.

</wizard-report>
