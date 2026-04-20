# shrine-diet-bioactivity — Integration Guide

Audience: **Syntropy-Journals engineers** wiring ShrineAgent (or any other MCP
client) to the diet + bioactivity knowledge graph. Covers the MCP tool
catalog, the tenant scoping contract, and the Clerk `org_id → tenant_id`
mapping rule.

For clinical-workflow composition patterns (which live in the agent
layer, not this MCP), see
[`clinical-integration-notes.md`](./clinical-integration-notes.md).

> **Status as of 2026-04-20** — architectural pivot in progress.
> The server is being refactored to a **thin adapter over LightRAG**
> with a narrow SQLite annex for structured numeric filters. The old
> 14-tool domain catalog retires; the new 7-tool surface is tracked in
> [`lightrag-thin-adapter-pivot.plan.md`](../../.claude/PRPs/plans/lightrag-thin-adapter-pivot.plan.md).
> Phase A1 of the multi-tenant enforcement work has shipped (scope
> context, `ScopedNeo4JStorage`, bootstrap migration, Clerk mapper).
> Phase A2 (FastAPI wrapper + audit log + cross-tenant canary) is
> in flight.

---

## 1. What the server is

One MCP server named `shrine-diet-bioactivity` is a **thin retrieval +
tenancy + audit adapter** over LightRAG and a SQLite property annex.
Specialised to the diet+bioactivity ontology — domain-agnostic in its
query surface.

**Target tool catalog (7 tools, post-pivot):**

| # | Tool | Backed by | Purpose |
|---|---|---|---|
| 1 | `semantic-search` | LightRAG `POST /query` | Hybrid / local / global / mix / naive KG retrieval, scope-filtered |
| 2 | `get-entity` | LightRAG graph routes | Look up one entity by id, scope-filtered |
| 3 | `get-neighbors` | LightRAG graph routes | Expand 1–2-hop neighborhood, optional edge-type filter, scope-filtered |
| 4 | `list-entity-types` | LightRAG graph routes | Discover ontology labels + counts in scope |
| 5 | `get-structured-properties` | SQLite annex | Exact property lookup (nutrition_100g, LD50, half-life, dosage) |
| 6 | `filter-by-property` | SQLite annex | Numeric / enum filters (`protein_g > 20`, `class = flavonoid`) |
| 7 | `ingest-tenant-knowledge` | LightRAG `/documents` + scoped `ainsert_custom_kg` | Tenant write path; scope forced to `tenant:<id>` |

Why so few tools: LightRAG's API already serves semantic retrieval and
graph traversal over the full ontology; reinventing domain verbs
(`find-functional-foods`, `search-by-bioactivity`) locked the catalog
into specific clinical / culinary workflows. Composition moves to the
agent layer — see `clinical-integration-notes.md`.

**Ontology (the only specialisation axis):**

- Shared: `Herb`, `Compound`, `Food`, `Target`, `Disease`, `Symptom`, `Nutrient`
- Tenant-only: `Protocol`, `Intervention`, `Outcome`, `Biomarker`
- 12 relationship types spanning both (see `lightrag/entity_schema.py`)

## 2. Wiring ShrineAgent (`.mcp.json`)

```json
{
  "mcpServers": {
    "shrine-diet-bioactivity": {
      "command": "node",
      "args": ["/path/to/shrine-diet-bioactivity/build/index.js"],
      "env": {
        "LIGHTRAG_API_URL": "http://localhost:9621"
      }
    }
  }
}
```

The server speaks stdio. `LIGHTRAG_API_URL` is only required if the agent
will call `semantic-search`; all SQLite tools work offline.

## 3. Passing tenant context

Every MCP tool call carries an optional `_meta` field. The agent side sets
`_meta.tenant_id` to the tenant slug; the server extracts it, validates it,
and forwards `scope_filter` downstream.

```ts
// Consumer side (simplified — ShrineAgent)
await client.callTool({
  name: 'semantic-search',
  arguments: { query: 'anti-inflammatory herbs for hsCRP reduction', mode: 'hybrid' },
  _meta: { tenant_id: 'clinic-mayfield' },   // ← the one field that matters
});
```

Server-side extraction (see `src/tenant.ts`):

```ts
const tenant = extractTenantContext(extra._meta);
// tenant = { tenantId: 'clinic-mayfield',
//            scopeFilter: ['shared', 'tenant:clinic-mayfield'] }
validateTenantId(tenant.tenantId);           // throws on malformed slug
```

Omitting `_meta.tenant_id` (or passing an empty / whitespace string) yields
a **shared-only** query — the client still gets the public diet KG, but
sees no tenant-private data.

## 4. Tenant ID format

Tenant IDs are **3–64 char lowercase slugs** matching:

```
/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/
```

| Rule | Rejected examples | Reason |
|---|---|---|
| Lowercase only | `Clinic-A` | Normalisation and Cypher safety |
| Alphanumeric + hyphen | `clinic_a`, `clinic.a`, `'; DROP TABLE` | Injection-safe |
| No leading/trailing hyphen | `-clinic`, `clinic-` | Parser ambiguity |
| 3–64 chars | `ab`, `a` × 65 | Collision + readability |

Invalid tenant IDs make the tool return `{ isError: true, content: [{ text: "Invalid tenant_id ..." }] }` — the agent should surface the error, not retry blindly.

## 5. Clerk `org_id → tenant_id` mapping

Syntropy-Journals authenticates clinics via Clerk. A Clerk `organization.id`
looks like `org_2abc123XYZ` — uppercase + underscore, **fails** the tenant
regex above. Consumers **must** run every Clerk `org_id` through the
canonical slugifier before passing it into `_meta.tenant_id`.

### Canonical rule

1. Strip the `org_` prefix.
2. Lowercase.
3. Replace underscores with hyphens.
4. Cap at 60 chars (leaves headroom; most Clerk IDs are 24–28 chars).
5. Validate against the tenant regex; reject on mismatch (do **not** silently drop characters beyond the cap).

### Reference implementation

TypeScript reference: [`src/clerkOrgMapping.ts`](../src/clerkOrgMapping.ts) —
ships with the server. Two exports:

```ts
import { slugifyClerkOrgId, slugifyClerkOrgIdSafe } from 'shrine-diet-bioactivity';

slugifyClerkOrgId('org_2abc123XYZ');            // → '2abc123xyz'
slugifyClerkOrgId('org_CLINIC_MAYFIELD_01');    // → 'clinic-mayfield-01'
slugifyClerkOrgId('org_2x');                    // throws (too short after strip)

slugifyClerkOrgIdSafe(null);                    // → null  (no throw)
slugifyClerkOrgIdSafe('org_bad!char');          // → null  (no throw)
```

`slugifyClerkOrgId` throws on any input that would produce an invalid
slug (empty, too short, leading/trailing hyphen, disallowed char).
`slugifyClerkOrgIdSafe` is the swallow-errors variant for code paths
where a missing/invalid org means "anonymous, shared-only".

| Clerk `org_id` | Mapped `tenant_id` |
|---|---|
| `org_2abc123XYZ` | `2abc123xyz` |
| `org_CLINIC_MAYFIELD_01` | `clinic-mayfield-01` |
| `org_2x` *(too short after strip)* | **throws** |

The Python equivalent (for data-pipeline code that ingests clinic artifacts
directly) ships alongside the TS version with identical behaviour.

### Why this rule exists

- Clerk IDs are **immutable per organisation** — a clinic's tenant slug is stable for the life of the Clerk org.
- The Cypher filter only understands the slug, so every call site needs the same mapping or tenants split across two scopes and see half their data.
- One-way mapping: the TS utility is the **only** sanctioned path. Don't hand-slug in the UI layer and again on the server — re-derive from `org_id` at the call boundary.

## 6. Scope semantics

Two scope values exist on every Neo4j node and edge:

| Scope value | Meaning | Who can see it |
|---|---|---|
| `shared` | Public diet KG — herbs, compounds, foods, targets, diseases, symptoms | Everyone |
| `tenant:<id>` | Private clinic knowledge — protocols, interventions, outcomes, biomarkers | Only that tenant |

A query always filters with `scope IN ['shared', 'tenant:<caller-id>']`.

```
tenant clinic-mayfield sees:    shared ∪ tenant:clinic-mayfield
tenant clinic-northvale sees:   shared ∪ tenant:clinic-northvale
anonymous / missing tenant:     shared only
```

Tenant writes land **exclusively** on `tenant:<id>` — the ingestion API
refuses to tag writes as `shared` (that's reserved for the shared ETL
pipelines in `lightrag/ingest_unified.py`).

## 7. Enforcement, observability, and the tool catalog — what's live vs planned

### Tenant enforcement

**Live today (Phase A1):**
- `semantic-search` extracts `tenant_id` from `_meta`, validates, and forwards `scope_filter` to `POST /query` on LightRAG.
- `slugifyClerkOrgId` + `slugifyClerkOrgIdSafe` — shipped in `src/clerkOrgMapping.ts`, 11 test cases.
- `lightrag/scope_context.py` — per-request `ContextVar[tuple[str, ...]]` with `("shared",)` default + slug validator.
- `lightrag/scoped_neo4j_storage.py` — `ScopedNeo4JStorage(Neo4JStorage)` subclass overrides 9 read methods to inject `WHERE n.scope IN $scope_filter` (plus matching predicates on edge / endpoint scope). Writes pass through unchanged.
- `lightrag/bootstrap_scope.py` — idempotent one-shot migration: tags every legacy node + relationship with `scope="shared"`, creates scope property indexes, fails closed on residual `NULL`. Run via `make lightrag-bootstrap-scope` (add `-dry-run` to preview).
- 21 Python + 11 TS unit tests.

**Code landed, pending live verification (Phase A2):**
- `lightrag/scoped_server.py` — FastAPI wrapper on port 9621. Accepts `scope_filter` in `POST /query`, validates every scope value, sets the `ContextVar`, delegates to `rag.aquery()`, resets on completion. Fails closed on missing/malformed scope. `make lightrag-server` now boots this (not upstream LightRAG).
- `lightrag/audit_log.py` — append-only SQLite audit at `lightrag/audit/mcp_audit.db`. Context-manager API emits one row per tool call, defensive (an audit failure never breaks a query).
- `lightrag/canary_smoke_test.py` — runnable cross-tenant canary. Inserts sentinel as `tenant:canary-a`, queries as `tenant:canary-b` via the scoped server, asserts the sentinel id does NOT appear. Cleanup guaranteed. `make lightrag-canary-test`.
- `lightrag/test_scope_enforcement.py` — 8 unit tests against a fake async Neo4j driver confirming every overridden read method (`get_node`, `get_nodes_batch`, `node_degree`, `get_edge`, `get_node_edges`, `get_all_labels`, …) injects the `WHERE scope IN $scope_filter` predicate. Plus one integration test gated behind `LIGHTRAG_RUN_INTEGRATION=true` that runs the canary path from pytest.
- Startup preflight: `scoped_server.py` refuses to boot if any node/relationship in the workspace still has `scope IS NULL` — forces `make lightrag-bootstrap-scope` first.

**To flip A2 from code-landed to live-verified** on a Neo4j instance:

```bash
make lightrag-bootstrap-scope       # one-shot migration against target Neo4j
make lightrag-server                # boots scoped_server.py, preflight checks
# in another shell:
make lightrag-canary-test           # cross-tenant isolation pass/fail
make lightrag-test-integration      # pytest integration path (gated)
make audit-recent                   # sanity-check the audit table
```

**Still open:**
- Vector-side isolation: currently only shared-scope embeddings exist; tenant embeddings will land with Phase B ingest, and the NanoVectorDB metadata filter closes the vector recall gap.
- Per-MCP-tool audit (TS-side): the Python audit captures per-`/query` calls on the server; the TS MCP layer will add richer per-tool rows (tool name, MCP transport latency) in Phase D so the table has one row per MCP tool invocation.

### Observability — audit log for traceable / billable operation

Every MCP tool call emits one append-only row into an audit SQLite
table `audit/mcp_audit.db`:

```
ts | tenant_id | tool | query_hash | scope_filter |
latency_ms | result_count | token_usage | status | error_class
```

No raw queries or PII — queries are SHA-256 hashed. The table supports:

- **Traceability:** every action a clinic's agent took, by tenant, for
  incident response.
- **Billing:** per-tenant invocation counts and LLM token usage, rolled
  up monthly.
- **Debug:** per-tenant error class filtering.

Consumers do not need to double-log MCP calls — use the audit table as
the source of truth for billable events.

### Tool-catalog pivot

The server is mid-pivot from 15 domain-verb tools to 7 domain-agnostic
primitives (see §1). Retiring: `search-herbs`, `search-compounds`,
`get-herb-compounds`, `get-compound-foods`, `get-compound-targets`,
`get-herb-food-overlap`, `get-herb-profile`, `search-by-bioactivity`,
`search-by-symptom`, `find-functional-foods`, and the 8 planned
OpenNutrition tools + `search-foods` meta-tool. OpenNutrition's 326K
foods flow into `get-structured-properties` and `filter-by-property`;
semantic retrieval over food descriptions stays on `semantic-search`.

Agent-layer composition patterns for clinical verbs
(`find-protocols-for-biomarker`, `get-intervention-outcomes`,
`get-contraindications`, `get-clinical-context`) live in
[`clinical-integration-notes.md`](./clinical-integration-notes.md).

## 8. Tenant-only entity types

The ingestion API (Phase 4 of the master PRD) accepts four tenant-scoped
entity types that are **not** part of the shared ETL:

| Entity | Meaning |
|---|---|
| `Protocol` | Clinic treatment plan with ordered phases (screening → treatment → validation) |
| `Intervention` | Therapeutic action: compound + route + dosage + frequency (unifies IV, oral, topical) |
| `Outcome` | Structured clinical observation with measurable direction + magnitude |
| `Biomarker` | Lab marker (hsCRP, HbA1c, cortisol, TSH, insulin, IL-6…) linking outcomes to targets |

And seven tenant relationship types: `INCLUDES`, `USES`, `RESULTED_IN`,
`MEASURED_BY`, `INDICATES`, `CONTRAINDICATES`, `SYNERGIZES_WITH`.

Entities/relationships of these types are what `tenant:<id>` scope is for.
Shared ETL skips them — see `lightrag/entity_schema.py` and the
`source_table=None` branch in `lightrag/ingest_unified.py`.

## 9. Example flow

```text
User (clinic practitioner)
  "Which of our anti-inflammation protocols pair well with curcumin for
   patients showing elevated hsCRP?"

ShrineAgent (Clerk session → org_2abcDEF)
  slugifyClerkOrgId('org_2abcDEF')          → '2abcdef'
  client.callTool({
    name: 'semantic-search',
    arguments: {
      query: 'anti-inflammation protocols with curcumin for elevated hsCRP',
      mode: 'hybrid',
    },
    _meta: { tenant_id: '2abcdef' },
  });

shrine-diet-bioactivity MCP
  tenant = extractTenantContext(_meta)      → { tenantId: '2abcdef',
                                                 scopeFilter: ['shared',
                                                               'tenant:2abcdef'] }
  POST /query { query, mode, top_k, scope_filter: ['shared','tenant:2abcdef'] }

LightRAG (post-enforcement)
  ScopedNeo4JStorage: WHERE n.scope IN $scope_filter
  returns: curcumin (shared) + tenant's Protocol/Intervention nodes
```

## 10. Further reading

- [`clinical-integration-notes.md`](./clinical-integration-notes.md) — **how to build the clinical-verb layer in the agent**, outside this MCP's scope
- `../.claude/PRPs/plans/lightrag-thin-adapter-pivot.plan.md` — active plan: 7-tool catalog, retirement list, migration path
- `../.claude/PRPs/plans/multi-tenant-enforcement-bootstrap.plan.md` — Phase A1 (shipped) and A2 (FastAPI wrapper + audit log + canary)
- `../.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md` — product rationale, phases, success metrics
- `../.claude/PRPs/plans/shrine-diet-bioactivity-unification.plan.md` — original scope-and-rename reasoning; the merge-8-tools + search-foods portions are superseded by the thin-adapter pivot
- `../src/tenant.ts` + `../src/clerkOrgMapping.ts` — tenant extraction and Clerk slug utility
- `../lightrag/entity_schema.py` — canonical ontology registry (entity + relationship types)
