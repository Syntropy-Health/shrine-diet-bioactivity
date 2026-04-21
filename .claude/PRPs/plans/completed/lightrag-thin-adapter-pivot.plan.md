# Plan: LightRAG-Driven Thin-Adapter MCP (Architectural Pivot)

> **Superseded by `lightrag-thin-adapter-pivot-v2.plan.md`** — v2 drops the
> SQLite annex entirely, collapses the 7-tool catalog to 5 tools, and
> reuses LightRAG's `/graphs` + `/query` primitives instead of rolling
> a custom `filter-by-property` route. This plan is kept for history;
> move to `completed/` once v2 merges.
>
> Original plan below ↓
>
> Supersedes the domain-merge portion of `shrine-diet-bioactivity-unification.plan.md`.
> The multi-tenant enforcement plan (`multi-tenant-enforcement-bootstrap.plan.md`)
> is preserved, extended with an audit-log deliverable for traceable/billable
> operation. No change to the data model or ontology — only to the tool surface
> and server role in the agentic harness.

## Summary

Reposition `shrine-diet-bioactivity` in the agentic harness as
**"LightRAG-driven semantic index & retrieval, specialized to the diet+
bioactivity ontology but not to clinical domain logic"**. The MCP becomes a
**thin adapter** over the LightRAG HTTP API (and its scoped wrapper from
Phase A2), plus a narrow SQLite annex for structured numeric filters that
vector retrieval can't serve. The 14 existing domain-verb tools and the 8
planned OpenNutrition tools retire. Clinical verbs
(`find-protocols-for-biomarker`, `get-intervention-outcomes`,
`get-contraindications`, `get-clinical-context`) leave MCP scope entirely —
they become the job of the agent layer above, documented as
`shrine-diet-bioactivity/docs/clinical-integration-notes.md`.

## User Story

As an **engineer integrating a clinical AI agent with the diet+bioactivity
KG**, I want the MCP server to expose a **small, stable, domain-agnostic
retrieval surface** backed by LightRAG — so that (a) my agent owns the
clinical reasoning verbs, (b) my tool catalog doesn't churn when the
clinical workflow evolves, (c) every query is tenant-scoped and
audit-logged for traceability and billing, and (d) I inherit LightRAG
feature upgrades with zero tool-catalog change.

## Problem → Solution

**Current state (post-Phase A1):**
- 15 MCP tools on `shrine-diet-bioactivity` — 14 domain-shaped SQLite query
  handlers (`search-by-bioactivity`, `find-functional-foods`,
  `get-herb-profile`, etc.) + 1 semantic-search pass-through.
- 8 more domain tools slated to merge from `mcp-opennutrition`
  (`search-food-by-name`, etc.) + a planned `search-foods` meta-tool.
- Tool names and Zod schemas bake in specific clinical/culinary use-cases,
  which blocks novel agent queries from composing cleanly.
- LightRAG's own API (`/query`, graph routes, document routes) already
  provides every retrieval primitive the agent needs — and it's maintained
  upstream.

**Desired state:**
- **7-tool catalog**, all domain-agnostic, covering every retrieval and
  ingestion mode the agent needs:

  | # | Tool | Layer | Purpose |
  |---|---|---|---|
  | 1 | `semantic-search` | LightRAG `/query` pass-through | Hybrid / local / global / mix / naive retrieval, scope-filtered |
  | 2 | `get-entity` | LightRAG graph routes pass-through | Look up one entity by id, scope-filtered |
  | 3 | `get-neighbors` | LightRAG graph routes pass-through | Expand 1-hop neighborhood of an entity, scope-filtered |
  | 4 | `list-entity-types` | LightRAG graph routes pass-through | Discover ontology labels in a given scope |
  | 5 | `get-structured-properties` | SQLite annex | Exact property lookup (e.g. `nutrition_100g` for a food, LD50 for a compound) |
  | 6 | `filter-by-property` | SQLite annex | Numeric / enum filters (e.g. `protein_g > 20`, `bioactivity = anti-inflammatory`) — domain-agnostic, ontology-bounded |
  | 7 | `ingest-tenant-knowledge` | LightRAG `/documents/text` + custom-KG pass-through | Tenant-private write path; scope forced to `tenant:<id>` |

- Every tool is scope-filtered through Phase A2's `scoped_server.py`.
- Every tool emits an audit record (tenant, tool, query hash, latency,
  result count, token usage) for traceability + per-tenant billing.
- The MCP description leads with the **ontology + retrieval modes**, not
  use-cases. Use-cases move into the agent-layer integration notes.

## Metadata

- **Complexity**: **Medium** — most of the work is deletion + thin
  wrappers; the hard parts (`ScopedNeo4JStorage`, bootstrap) are already in
  Phase A1.
- **Estimated Files**: ~18 (6 new, 4 updated, ~20 deleted/retired)
- **Parallel to**: `multi-tenant-enforcement-bootstrap.plan.md` Phase A2
  (`scoped_server.py`, audit log, canary).
- **Supersedes (partially)**: `shrine-diet-bioactivity-unification.plan.md`
  — the merge-8-tools + search-foods-meta-tool sections are dropped; the
  rename / package identity work already landed.

---

## Architecture

```
┌───────────────────────────────────────────────────────────┐
│  Agent layer (ShrineAgent, CLI, etc.)                     │
│  clinical verbs composed on top:                           │
│   find-protocols-for-biomarker, get-intervention-outcomes, │
│   get-contraindications, get-clinical-context, …           │
│  (see docs/clinical-integration-notes.md)                  │
└──────────────────────────┬────────────────────────────────┘
                           │  MCP protocol, 7 tools
                           ▼
┌───────────────────────────────────────────────────────────┐
│  shrine-diet-bioactivity MCP (thin adapter)               │
│  - _meta.tenant_id extraction + slug validation            │
│  - scope_filter = ['shared','tenant:<id>']                 │
│  - per-request audit log                                    │
│  - routing: 5 pass-throughs + 2 SQLite-backed primitives   │
└───┬────────────────────────────────────────┬──────────────┘
    │ HTTP                                   │ SQLite
    ▼                                        ▼
┌──────────────────────────────┐  ┌────────────────────────┐
│  scoped_server.py (Phase A2) │  │ herbal_botanicals.db   │
│  FastAPI, sets ContextVar    │  │ opennutrition_foods.db │
│  forwards to LightRAG        │  │ (structured numeric /   │
│                              │  │  enum property store)   │
└──┬───────────────────────────┘  └────────────────────────┘
   │
   ▼
┌───────────────────────────────┐
│  LightRAG + ScopedNeo4JStorage │
│  Neo4j (scope-filtered reads)  │
│  NanoVectorDB / file KV        │
└───────────────────────────────┘
```

The MCP is **transport + tenancy + audit**, not a query authoring layer.
Retrieval intelligence lives in LightRAG; structured filters live in
SQLite; clinical reasoning lives in the agent layer.

---

## Tool Specifications

### 1. `semantic-search` *(exists — expand description, no logic change)*

Already a pass-through to `POST /query`. Accepts `query`, `mode ∈
{local, global, hybrid, mix, naive}`, `top_k`. Scope forwarded from
`_meta.tenant_id`. No domain-use-case hints in the description —
describe it as "retrieve KG entities and relations relevant to a
natural-language query, modes map to LightRAG's retrieval strategies".

### 2. `get-entity` *(new)*

```ts
{ entity_id: string, entity_type?: string }
→ { entity: { entity_id, entity_type, description, scope, ... } | null }
```

Proxies to LightRAG's graph `GET /graph/entity/{id}` (or equivalent).
Scope-filtered via `scoped_server`. `entity_type` is an optional hint for
disambiguation but the server does not validate against it.

### 3. `get-neighbors` *(new)*

```ts
{ entity_id: string, depth?: 1|2, edge_types?: string[] }
→ { edges: [{ src, tgt, rel_type, description, scope, ... }] }
```

One-hop or two-hop neighborhood. `edge_types` optionally filters to
named relationship types from the 12 registered in
`entity_schema.py`. Proxies to LightRAG graph routes + `ScopedNeo4JStorage`.

### 4. `list-entity-types` *(new)*

```ts
{}
→ { entity_types: [{ label, count_in_scope }] }
```

Exposes the ontology shape to the agent. Returns the 10 entity types
(Herb / Compound / Food / Target / Disease / Symptom + Protocol /
Intervention / Outcome / Biomarker) with live counts inside the
caller's scope. Agent uses this to verify what's queryable.

### 5. `get-structured-properties` *(new, SQLite annex)*

```ts
{ entity_id: string, property_keys?: string[] }
→ { properties: Record<string, number | string | null> }
```

Looks up structured properties the KG doesn't carry — `nutrition_100g`
(90 fields), LD50, half-life, dosage ranges, compound concentrations.
Reads from `herbal_botanicals.db` / `opennutrition_foods.db`. Ontology-
bounded: only returns properties registered in a small metadata table
per entity type. **No** tenant scope — shared data only; tenant
structured data is stored as entity/edge properties in the graph via
`ingest-tenant-knowledge`.

### 6. `filter-by-property` *(new, SQLite annex)*

```ts
{
  entity_type: 'Food'|'Compound'|'Herb'|...,
  filters: [{ property: string, op: 'eq'|'gt'|'gte'|'lt'|'lte'|'in', value: any }],
  limit?: number
}
→ { entities: [{ entity_id, entity_type, matched_properties }] }
```

Structured-filter primitive for queries LightRAG can't serve:
`foods where protein_g > 20`, `compounds where class = flavonoid`.
Whitelisted property names per entity type (schema-driven, rejects
unknown keys). Shared data only; agent joins with scoped semantic
search for tenant overlay.

### 7. `ingest-tenant-knowledge` *(new)*

```ts
{
  mode: 'text' | 'custom_kg',
  text?: string,                         // when mode='text'
  entities?: [{ entity_name, entity_type, description }],
  relationships?: [{ src, tgt, rel_type, description, keywords?, weight? }],
  source_label?: string                  // for audit trail
}
→ { ingested: { entities: n, relationships: m }, job_id: string }
```

Tenant write path. The server **forces** `scope="tenant:<id>"` from
`_meta.tenant_id` — rejects any ingest call where `tenant_id` is absent.
Payload validated against `entity_schema.ENTITY_TYPES` /
`RELATIONSHIP_TYPES`. Proxies to LightRAG's `/documents/text` (mode=text)
or `ainsert_custom_kg` (mode=custom_kg). Refuses `scope="shared"`
attempts — shared ETL runs separately via `ingest_unified.py`.

---

## Retirement List

**14 tools retired** (domain verbs — agent composes equivalents from
primitives 1–6):

- `search-herbs`, `search-compounds` → `semantic-search` + `filter-by-property`
- `get-herb-compounds`, `get-compound-foods`, `get-compound-targets`,
  `get-herb-food-overlap` → `get-neighbors` with `edge_types` filter
- `get-herb-profile` → `get-entity` + `get-neighbors` (depth=2)
- `search-by-bioactivity`, `search-by-symptom` → `semantic-search`
- `find-functional-foods` → `semantic-search` + `filter-by-property`
- `get-health` → keep as one lightweight endpoint (server-health only, no data)

**8 OpenNutrition tools retired** (`search-food-by-name`, etc.) — their
326K-food data flows into `get-structured-properties` and
`filter-by-property`, searchable via `semantic-search` over food
descriptions already in the KG.

**Planned `search-foods` meta-tool dropped** — its purpose (cross-backend
food ranking) falls out of `semantic-search` + `filter-by-property`
composed by the agent.

---

## Traceable / Billable Audit Layer

Every MCP tool invocation emits one audit record. Persisted to a local
SQLite DB (`audit/mcp_audit.db`) for dev, swappable for Postgres /
ClickHouse in production. Schema:

```sql
CREATE TABLE mcp_audit (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ts              TEXT NOT NULL,          -- ISO 8601 UTC
  tenant_id       TEXT,                   -- null = shared / anonymous
  tool            TEXT NOT NULL,          -- e.g. 'semantic-search'
  query_hash      TEXT,                   -- SHA-256 of the normalised query body
  scope_filter    TEXT NOT NULL,          -- JSON array
  latency_ms      INTEGER NOT NULL,
  result_count    INTEGER,                -- rows / entities returned
  token_usage     INTEGER,                -- LLM tokens consumed by LightRAG, if any
  status          TEXT NOT NULL,          -- 'ok' | 'error' | 'invalid_tenant'
  error_class     TEXT                    -- on status != 'ok'
);

CREATE INDEX idx_audit_tenant_ts ON mcp_audit(tenant_id, ts);
```

Queries the log enables:
- **Traceability**: "show every query tenant:clinic-a ran in the last 24 h"
- **Billing**: "count of invocations and token usage per tenant per day"
- **Debug**: "last 100 errors for tenant:clinic-a"

No PII in the audit log — queries are hashed, not stored verbatim.
Raw-query retention lives elsewhere (observability stack) if needed.
The audit table is append-only; monthly rollups are produced by a
separate aggregation job.

---

## Phase Breakdown

### Phase D1 — Tool-catalog cutover *(this plan's core)*

Files:
- `src/index.ts` — delete the 14 domain-verb tool handlers; add 6 new
  thin-adapter handlers (semantic-search stays). Server description
  rewritten to lead with ontology + retrieval modes.
- `src/structured_properties.ts` — SQLite annex helpers + schema
  metadata whitelist
- `src/lightrag_proxy.ts` — small HTTP client for the scoped LightRAG
  wrapper (used by 1, 2, 3, 4, 7)
- `src/audit_log.ts` — audit emitter (opens `mcp_audit.db`, appends one
  row per tool call, never throws on log failure)
- `src/__tests__/structured_properties.test.ts`
- `src/__tests__/lightrag_proxy.test.ts`
- `src/__tests__/audit_log.test.ts`
- `src/__tests__/ingest_tenant_knowledge.test.ts`
- `src/__tests__/tool_catalog.test.ts` — smoke test: exactly 7 tools
  registered, each returns schema

Deletions (after tests confirm agent-side equivalents work):
- Remove the 14 domain-verb handler bodies from `src/index.ts`.
- Keep `HerbalDBAdapter.ts` but trim to the surface the annex primitives
  use — the herb/compound/food query methods it no longer needs go away.
- Deprecate `mcp-opennutrition` submodule for MCP use; its TSV→SQLite
  build scripts stay as the data-source pipeline for `opennutrition_foods.db`.

### Phase D2 — Doc cutover

- `docs/integration-guide.md` — rewrite §1 catalog table to the 7 tools.
  §3 tenant scoping unchanged.
- `docs/clinical-integration-notes.md` — **new**, describes the adjacent
  agent layer and how to compose clinical verbs on the 7 primitives.
- `README.md` — update tool table and positioning ("thin adapter over
  LightRAG / SQLite annex").
- `shrine-diet-bioactivity-unification.plan.md` — add a `> Superseded
  by lightrag-thin-adapter-pivot.plan.md` banner at the top, move
  plan to `.claude/PRPs/plans/completed/` once this plan lands.

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `lightrag/lightrag/api/routers/query_routes.py` | 16-143, 325, 535 | `POST /query` surface shape — semantic-search proxy mirrors this |
| P0 | `lightrag/lightrag/api/routers/graph_routes.py` | whole file | Graph endpoints for get-entity, get-neighbors, list-entity-types |
| P0 | `shrine-diet-bioactivity/lightrag/entity_schema.py` | 1-230 | Ontology registry — `filter-by-property` whitelist and `ingest-tenant-knowledge` validation anchor here |
| P0 | `shrine-diet-bioactivity/lightrag/scoped_neo4j_storage.py` | 1-end | Existing scope-filter WHERE injection — pass-throughs must preserve it |
| P1 | `shrine-diet-bioactivity/src/tenant.ts` | 1-55 | _meta.tenant_id extraction pattern all new handlers reuse |
| P1 | `shrine-diet-bioactivity/src/clerkOrgMapping.ts` | 1-end | Consumer-side utility, referenced from integration docs |
| P1 | `shrine-diet-bioactivity/src/HerbalDBAdapter.ts` | whole file | Trim to the annex surface — identify methods to keep vs drop |
| P2 | `lightrag/lightrag/api/lightrag_server.py` | 1-70 | How LightRAG boots FastAPI — pattern the audit emitter mirrors |

---

## Success Criteria

- [ ] `list_tools` returns exactly 7 tools.
- [ ] No tool description contains a clinical / culinary use-case verb
  (`find-functional-foods`, `search-by-bioactivity`, etc.).
- [ ] Every tool call results in one audit row with correct
  `tenant_id`, `scope_filter`, `tool`, `latency_ms`.
- [ ] Agent-side regression suite (clinical verbs composed by the
  ShrineAgent integration tests) passes against the new 7-tool catalog —
  measured via ShrineAgent's own E2E harness, not this repo.
- [ ] Cross-tenant canary still passes (Phase A2 test is the gate).
- [ ] LightRAG upgrade from 1.x → 1.y requires zero MCP tool changes —
  verified in a dry-run upgrade PR.

## Out of Scope

- **Vector-side tenant filter**: currently shared-only embeddings are
  indexed. Tenant ingest writes to the graph; tenant embeddings land in
  a follow-up. Phase A2 notes this gap.
- **Clinical-verb MCPs**: deliberately not built here. Agent layer owns
  these; see `docs/clinical-integration-notes.md`.
- **Billing pipeline**: this plan lands the audit table; aggregation +
  invoice generation is a downstream finance-layer concern.
- **Multi-region / shard split**: single-Neo4j, single-SQLite assumption.
