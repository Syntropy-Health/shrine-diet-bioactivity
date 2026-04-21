---
supersedes: .claude/PRPs/plans/lightrag-thin-adapter-pivot.plan.md
branch: feature/mcp-herbal-botanicals
status: in-progress
---

# Plan v2: LightRAG-Driven Thin-Adapter MCP — 5-Tool Catalog, Zero SQLite

> Supersedes `lightrag-thin-adapter-pivot.plan.md` (7-tool catalog with a
> SQLite annex). The v1 plan's architecture is sound; this v2 narrows it
> further after a design review pointed out two issues:
>
> 1. A SQLite annex fragments the knowledge store and contradicts the
>    "all knowledge in the KG" goal. Structured properties like
>    `nutrition_100g`, `LD50`, compound class, bioactivity weights live
>    as Neo4j node/edge properties, not in a sibling SQL DB.
> 2. A custom `filter-by-property` primitive duplicates a surface
>    LightRAG already exposes. Reuse `GET /graphs?label&max_depth`
>    (subgraph) and `POST /query` (with `user_prompt` for structured
>    constraints).
>
> Net effect: **6 tools → 5 tools**, ~900 lines of TS deleted, no new
> Cypher-injection surface, zero data drift between "authoritative KG"
> and "SQLite annex".

---

## Architectural reset vs surgical cleanup — decision

The cleanest interpretation of "reset to before MCP-over-MCP" is
`git reset --hard 77c5e57`. It drops 13 commits, most of which we
actually want to keep (ScopedNeo4JStorage, ContextVar plumbing,
bootstrap migration, Clerk slug mapper, Phase A2 FastAPI wrapper,
audit log, cross-tenant canary, all PRDs and plans).

**Decision: surgical cleanup on current HEAD.** Final tree is
identical to "reset + cherry-pick the tenancy commits" but with less
ceremony and linear history. The misstep being undone is the
**MCP-over-MCP shape** (shrine-diet-bioactivity wrapping both an
OpenNutrition MCP and a KG MCP), not the tenancy work that happened
alongside it.

What we undo in-place:
- `src/index.ts` — 14 domain-verb handlers gone; 5 thin-adapter
  handlers in their place.
- `src/HerbalDBAdapter.ts` — deleted (713 lines).
- `src/__tests__/{db-integration,food-bridge,kg-expansion,multi-source,normalize}.test.ts` — deleted.
- `data_local/*.db` — removed from any live runtime path (stays as
  build-artifact reference for reproducing the prototype KG).
- `mcp-opennutrition/` — kept as submodule, unwired from Makefile
  runtime, documented as reference.

What we keep (all from post-`77c5e57` commits):
- `lightrag/scoped_neo4j_storage.py`, `scope_context.py`,
  `bootstrap_scope.py`, `scoped_server.py`, `audit_log.py`,
  `canary_smoke_test.py`, `entity_schema.py`.
- `src/tenant.ts`, `src/clerkOrgMapping.ts`.
- All `.claude/PRPs/` planning docs.

---

## Final catalog — 5 tools (+ health)

| # | Tool | LightRAG route |
|---|---|---|
| 1 | `semantic-search` | `POST /query` — 5 modes, `user_prompt`, `top_k`, `ids`; scope-filtered |
| 2 | `get-entity` | `GET /graphs?label=<id>&max_depth=0` — single node |
| 3 | `get-subgraph` | `GET /graphs?label=<id>&max_depth=N&max_nodes=M` — neighborhood |
| 4 | `list-labels` | `GET /graph/label/popular?limit=N` — ontology shape in scope |
| 5 | `ingest-knowledge` | `POST /documents/text` or `ainsert_custom_kg` — scope forced to `tenant:<id>` |

Plus `get-health` — server-only, no data.

Every tool:
- Extracts `_meta.tenant_id`, validates via `clerkOrgMapping`, builds
  `scope_filter = ["shared"] ∪ ["tenant:<id>"?]`.
- Proxies to the scoped LightRAG wrapper (`scoped_server.py`).
- Emits one row into `mcp_audit.db` (same schema as Python audit_log).
- Descriptions lead with **ontology + retrieval modes**. No
  clinical/culinary verbs anywhere in tool schemas.

Clinical verbs (`find-protocols-for-biomarker`,
`get-intervention-outcomes`, `get-contraindications`,
`get-clinical-context`) stay out of MCP. They live in the agent
layer; see `docs/clinical-integration-notes.md`.

---

## Scoped-server surface extension (Python side)

The Phase A2 wrapper currently handles only `POST /query` and
`GET /health`. Extend to cover every LightRAG route the 5 tools need.

All routes use the existing `_SCOPE_FILTER_VAR` ContextVar +
`ScopedNeo4JStorage` WHERE-injection pattern, so scope enforcement
is inherited automatically. No new Cypher; no whitelist surface.

| Route | Added for | Scope handling |
|---|---|---|
| `POST /query` | `semantic-search` | Existing — `scope_filter` in body |
| `GET /graphs` | `get-entity`, `get-subgraph` | New — `scope_filter` via query param or header |
| `GET /graph/label/popular` | `list-labels` | New — filter popular-labels query by scope |
| `POST /documents/text` | `ingest-knowledge` | New — force `scope=tenant:<id>` into every written entity/edge; reject `shared` writes from tenant context |
| `POST /documents/custom_kg` | `ingest-knowledge` mode=custom_kg | New — same scope forcing applied to payload |

**No new primitives, no custom filters.** These are 1-to-1
pass-throughs to LightRAG with ContextVar injection.

---

## Cross-tenant canary — design + extensions

What `canary_smoke_test.py` does today (Phase A2):

1. **Plant** — inserts a sentinel node directly into Neo4j via raw
   Cypher with `scope="tenant:canary-a"` and a random UUID
   entity_id. Bypasses LightRAG's ingest path so the test provably
   exercises the *read-side* filter.
2. **Negative assertion (the gate)** — `POST /query` to
   `scoped_server` as `tenant:canary-b` asking about the sentinel.
   Assert the sentinel UUID string does **not** appear in the
   response body. Exit 1 if it leaks.
3. **Positive sanity** — query as owner `tenant:canary-a`; warning
   only if sentinel missing (hybrid retrieval has variable recall;
   isolation is the gate, not recall).
4. **Cleanup** — `DETACH DELETE` regardless of outcome, WARN on
   cleanup failure.

Why this shape:
- Direct-Cypher write → proves `ScopedNeo4JStorage` read filter
  enforces isolation, not the ingest auto-tagging.
- Random UUID per run → unambiguous string-containment assertion.
- Hybrid mode → exercises full pipeline, filter must hold through
  embed → vector → graph → LLM synthesis.

Extensions added in this plan (one per new route):

| Check | Route | Expectation |
|---|---|---|
| existing /query leak | `POST /query` | sentinel UUID not in response body |
| **new** /graphs leak | `GET /graphs?label=<sentinel>` as tenant:canary-b | empty nodes + edges |
| **new** label popularity leak | `GET /graph/label/popular?limit=300` as tenant:canary-b | sentinel UUID not in returned labels |
| **new** ingest-scope-forcing | `POST /documents/text` as tenant:canary-b with `scope="shared"` in payload | 400/403, nothing written |
| **new** ingest audit | Any /documents call | one audit row with `tenant_id=canary-b`, `status=ok` or `status=invalid_tenant` |

Known gaps that stay out of scope (flagged for follow-up):
- Response-body assertion is on final LLM text; tighter version
  would use `only_need_context=True` and assert on raw node list.
- Vector-side isolation doesn't exist (embeddings are shared). When
  tenant-private embeddings land, add vector-recall canary variant.

---

## OpenNutrition handling

- `mcp-opennutrition/` stays as a git submodule.
- Removed from `make setup` / runtime Makefile targets.
- Its TSV→KG ingestion logic (the method) is preserved as a
  documented workflow under `docs/opennutrition-to-kg.md` — can be
  re-run manually when full 326k ingestion is desired.
- **No data re-ingestion in this plan.** Current prototype KG has
  a subsample; that subsample is what the MCP serves.

### Subsample reproducibility

Inspection of `ingest_unified.py` shows subsampling is pure SQL
`LIMIT N` via CLI args (`--max-herbs`, `--max-compounds`, etc.) —
no RNG. So "fix the seed" reduces to two concrete tasks:

1. **Capture the exact CLI args used to build the current KG** in a
   new Makefile target `lightrag-ingest-prototype` — so re-running
   produces the same node counts.
2. **Audit SQL queries** in `entity_schema.ENTITY_TYPES[*].query`
   for missing `ORDER BY` clauses. SQLite row order without an
   explicit `ORDER BY` depends on insertion order + index state —
   not deterministic across rebuilds of the underlying DB. Add
   `ORDER BY <primary_key>` to every query so `LIMIT N` is
   reproducible regardless of the DB state.
3. Introduce `SUBSAMPLE_SEED` env var slot in `config_local.env`
   (unused today; reserved for future RNG-based sampling).

No re-run required.

---

## Phase breakdown

### D1a — Python pass-throughs (scoped_server.py)

Files:
- `lightrag/test_scoped_server_graph.py` — **new** — failing tests for
  `/graphs`, `/graph/label/popular`, `/documents/text`,
  `/documents/custom_kg`, audit emission per route, scope-forcing on
  ingest, reject shared-from-tenant.
- `lightrag/scoped_server.py` — extend with the 4 new routes. Mount
  upstream `graph_routes.py` handlers inline where useful; reuse
  ContextVar pattern everywhere.
- `lightrag/canary_smoke_test.py` — extend with 4 new checks.

TDD order:
1. RED: write every test in `test_scoped_server_graph.py`; run pytest → all fail.
2. GREEN: implement route-by-route; re-run after each.
3. REFACTOR: extract `audit_context_manager` + `scope_validator`
   helpers if duplication appears across routes.

### D1b — TypeScript thin adapter

Files (new):
- `src/lightrag_proxy.ts` — typed HTTP client; Zod response schemas;
  handles `NEO4J_URI` / `LIGHTRAG_API_URL`; timeout + retry.
- `src/audit_log.ts` — SQLite-backed emitter mirroring Python shape.
- `src/__tests__/lightrag_proxy.test.ts` — failing tests.
- `src/__tests__/audit_log.test.ts` — failing tests.
- `src/__tests__/tool_catalog.test.ts` — failing smoke: exactly 5
  tools + `get-health`; no clinical verbs in descriptions.

Files (rewritten):
- `src/index.ts` — 14 handlers deleted; 5 new handlers wired to
  proxy + audit.

Files (deleted):
- `src/HerbalDBAdapter.ts`
- `src/__tests__/db-integration.test.ts`
- `src/__tests__/food-bridge.test.ts`
- `src/__tests__/kg-expansion.test.ts`
- `src/__tests__/multi-source.test.ts`
- `src/__tests__/normalize.test.ts`

TDD order:
1. RED: all three test files above fail.
2. GREEN: implement `lightrag_proxy.ts`, `audit_log.ts`, then
   rewrite `index.ts`.
3. DELETE: remove `HerbalDBAdapter.ts` + legacy tests. Run full
   vitest — must still be green.
4. REFACTOR.

### D1c — Makefile + submodule cleanup

- `Makefile`: remove `build`, `food-bridge`, `enrich-nutrition`
  targets from `setup`. Add `lightrag-ingest-prototype` with pinned
  CLI args. Add `lightrag-canary-test-full` that runs extended
  canary.
- `.gitmodules`: `mcp-opennutrition` stays; add comment "reference
  only — not wired to runtime".
- `data_local/*.db` — add to `.gitignore` if not already; document
  as build artifact.

### D2 — Docs

- `shrine-diet-bioactivity/docs/integration-guide.md` — §1 catalog
  rewritten to 5 tools; §3 tenant scoping unchanged; §N new section
  on "SQLite removed; all data in KG".
- `shrine-diet-bioactivity/docs/clinical-integration-notes.md` — new.
  Shows agent-side composition of clinical verbs on the 5 primitives.
- `shrine-diet-bioactivity/docs/opennutrition-to-kg.md` — new.
  Archived workflow to re-ingest full OpenNutrition when needed.
- `README.md` — update positioning to "thin LightRAG adapter, zero
  SQLite".
- `lightrag-thin-adapter-pivot.plan.md` — superseded-by banner
  already added via this plan's frontmatter; move to
  `.claude/PRPs/plans/completed/` after D1+D2 merge.
- `shrine-diet-bioactivity-unification.plan.md` — superseded banner;
  move to `completed/`.

---

## Mandatory reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `lightrag/lightrag/api/routers/graph_routes.py` | 89-196 | `/graphs`, `/graph/label/*` — shapes the pass-throughs |
| P0 | `lightrag/lightrag/api/routers/query_routes.py` | 16-143 | Already mirrored in `scoped_server.py` |
| P0 | `shrine-diet-bioactivity/lightrag/scoped_server.py` | whole file | Extension target |
| P0 | `shrine-diet-bioactivity/lightrag/scope_context.py` | whole file | ContextVar plumbing — reused verbatim |
| P0 | `shrine-diet-bioactivity/lightrag/audit_log.py` | whole file | Audit emitter — reused verbatim |
| P1 | `shrine-diet-bioactivity/src/tenant.ts` | 1-55 | `_meta.tenant_id` extraction — reused |
| P1 | `shrine-diet-bioactivity/src/clerkOrgMapping.ts` | 1-70 | Clerk slug validation — reused |
| P1 | `shrine-diet-bioactivity/lightrag/canary_smoke_test.py` | whole file | Extension target |
| P1 | `shrine-diet-bioactivity/lightrag/entity_schema.py` | whole file | Needed for SQL ORDER BY audit |
| P2 | `shrine-diet-bioactivity/lightrag/ingest_unified.py` | 220-300 | CLI arg shape → prototype Makefile target |

---

## Success criteria

- [ ] `list_tools` returns exactly 5 tools + `get-health`.
- [ ] No tool description contains clinical / culinary verbs.
- [ ] Every tool call emits one `mcp_audit.db` row with correct
      `tenant_id`, `scope_filter`, `tool`, `latency_ms`.
- [ ] `HerbalDBAdapter.ts` + 5 legacy test files deleted.
- [ ] Extended canary passes: /query, /graphs, /graph/label/popular,
      /documents/text (scope-forcing), audit-row-per-call.
- [ ] `make lightrag-ingest-prototype` reproduces current KG
      node/edge counts to within ±0 (exact match).
- [ ] `ingest_unified.py` SQL queries all include explicit
      `ORDER BY <pk>` so `LIMIT` is deterministic across DB
      rebuilds.
- [ ] Vitest + pytest 80%+ coverage on changed code.
- [ ] LightRAG upgrade from 1.x → 1.y requires zero MCP tool
      changes (verified by running `npm test` after upstream bump).

## Out of scope

- Vector-side tenant isolation (shared embeddings today; follow-up).
- Clinical-verb MCPs (agent-layer only).
- Billing pipeline (this plan lands the audit table).
- Full OpenNutrition 326k ingestion (manual, workflow preserved).
- Multi-region / shard split (single Neo4j + single MCP).
