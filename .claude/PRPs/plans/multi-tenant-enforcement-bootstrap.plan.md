# Plan: Multi-Tenant Enforcement & Bootstrap (Blockers #1–#3)

## Summary
Close the three integration-readiness blockers for the Diet KG MCP before Syntropy-Journals wiring (Phase 6): (1) tag all existing 7,722 Neo4j nodes/edges with `scope="shared"` so filtering has something to filter on; (2) make LightRAG's `/query` endpoint actually enforce `scope_filter` at the Cypher level via a `ScopedNeo4JStorage` subclass + thin FastAPI wrapper; (3) document and implement the canonical Clerk `org_id → tenant_id` slug rule with a reference utility for consumers. Current client-side scoping is theater because the server ignores `scope_filter` and half the graph has no `scope` property.

## User Story
As a **Syntropy-Journals engineer** wiring ShrineAgent to the Diet KG MCP,
I want **the MCP server to actually isolate clinic data server-side** with a documented Clerk mapping rule,
so that **I can safely pass `org_id` from Clerk, trust that tenant A never sees tenant B's data, and produce an integration doc that describes real behavior rather than aspirations**.

## Problem → Solution
**Current state**:
- 7,722 existing Neo4j nodes have no `scope` property. A strict filter returns zero rows; a permissive filter leaks everything.
- LightRAG's `/query` endpoint has no `scope_filter` field in `QueryRequest`/`QueryParam`; the field sent by `semantic-search` is silently dropped.
- Clerk's `org_2abc123XYZ` format is rejected by the tenant regex. No mapping rule exists.

**Desired state**:
- All pre-existing nodes/edges tagged `scope="shared"` + `scope` index created. Preflight gate in CI blocks deploys if any node has `scope IS NULL`.
- LightRAG-side enforcement: `ScopedNeo4JStorage` subclass injects `AND n.scope IN $scope_filter` into every read Cypher. A thin FastAPI wrapper (`scoped_server.py`) replaces the upstream binary and plumbs `scope_filter` through a `contextvars.ContextVar` into storage calls.
- Canary cross-tenant isolation test in CI: insert sentinel as `tenant:canary-a`, query as `tenant:canary-b`, assert empty.
- Canonical Clerk mapping rule documented: `clerk_org_id → lowercased, underscore→hyphen, prefix stripped, length-capped` slug. Reference utilities published in both TypeScript and Python for consumer adoption.

## Metadata
- **Complexity**: **Large** (3 subsystems, 15 files, ~800 lines)
- **Source PRD**: `.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md` (covers Phase 1 + enforcement portion of Phase 3 + groundwork for Phase 6)
- **PRD Phase**: **Phase 1 (Scope Bootstrap)** + **Phase 3 enforcement supplement** + **Phase 6 prerequisite (Clerk mapping)**
- **Estimated Files**: 15 (11 new, 4 updated)

---

## UX Design

### Before
```
┌──────────────────────────────────────────────────────────────────┐
│ ShrineAgent ─► MCP semantic-search(query, _meta.tenant_id)        │
│                    │                                              │
│                    ▼                                              │
│  POST /query body: { query, mode, scope_filter:['shared',         │
│                                                 'tenant:X'] }     │
│                    │                                              │
│                    ▼                                              │
│  LightRAG server: ignores scope_filter (unknown field)            │
│                    │                                              │
│                    ▼                                              │
│  Neo4j returns ALL nodes (tenant X sees tenant Y's data).         │
│  Existing 7,722 nodes have no scope property; untracked.          │
└──────────────────────────────────────────────────────────────────┘
              ⚠  "Tenant isolation" is a lie.
```

### After
```
┌──────────────────────────────────────────────────────────────────┐
│ ShrineAgent ─► slugifyClerkOrgId("org_2abc")    → "org-2abc"      │
│                    │                                              │
│                    ▼                                              │
│ MCP semantic-search(query, _meta.tenant_id="org-2abc")            │
│                    │                                              │
│                    ▼                                              │
│ POST /query body: { query, mode, scope_filter:['shared',          │
│                                                'tenant:org-2abc']}│
│                    │                                              │
│                    ▼                                              │
│ scoped_server.py ─► ContextVar[scope_filter].set(...)             │
│                    │                                              │
│                    ▼                                              │
│ ScopedNeo4JStorage: every MATCH injects                           │
│   WHERE n.scope IN $scope_filter                                  │
│                    │                                              │
│                    ▼                                              │
│ Neo4j returns ONLY: shared ∪ tenant:org-2abc                      │
│ Canary test: tenant:canary-b cannot see tenant:canary-a data.     │
└──────────────────────────────────────────────────────────────────┘
              ✓ Enforcement is real and CI-gated.
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| `make lightrag-server` | Starts upstream binary | Starts `scoped_server.py` wrapper on same port (9621) | /query honors scope_filter; other endpoints dropped for now |
| `POST /query` body | `scope_filter` silently ignored | `scope_filter` required; absent → 400 | Explicit fail-closed |
| Neo4j node properties | Mixed: new entities have `scope`, old 7,722 have none | All nodes have `scope`; `scope` index exists | One-shot migration |
| Tenant ID format | Regex-validated only; no Clerk mapping | `slugifyClerkOrgId()` reference utility + docs | Consumer-side transformation |
| CI | No isolation tests | Canary cross-tenant test gates every push | Added to npm test + pytest |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `mcp-herbal-botanicals/lightrag/ingest_unified.py` | 113-119, 154-163, 189-205 | Confirms `scope:"shared"` flows into new entities/relationships; shape of `custom_kg` dict |
| P0 | `lightrag/lightrag/kg/neo4j_impl.py` | 25-30, 67-143, 271, 458-671 | Async Neo4j driver, workspace label pattern, retrieval method signatures — these are the subclass extension points |
| P0 | `lightrag/lightrag/base.py` | 85-170 | `QueryParam` dataclass — reveals there's no `scope_filter` today; we use contextvars to avoid editing submodule |
| P0 | `lightrag/lightrag/api/routers/query_routes.py` | 16-143 | `QueryRequest` pydantic model + `to_query_params()` — mirror for our wrapper request schema |
| P0 | `lightrag/lightrag/api/lightrag_server.py` | 1-70 | How LightRAG boots FastAPI; mirror for our wrapper's startup (dotenv, rag instantiation) |
| P1 | `mcp-herbal-botanicals/lightrag/fix_unknown_entities.py` | 1-200 | Established one-shot script pattern — argparse, dotenv, neo4j driver, rule-based classifier. Bootstrap script must mirror this exactly. |
| P1 | `mcp-herbal-botanicals/src/tenant.ts` | 1-55 | Existing regex + extractTenantContext — error message at L42 updates to reference new docs |
| P1 | `mcp-herbal-botanicals/src/__tests__/tenant.test.ts` | 1-115 | Vitest structure; mirror for new `clerkOrgMapping.test.ts` |
| P1 | `mcp-herbal-botanicals/lightrag/test_ingest.py` | 1-100 | Pytest structure; mirror for `test_bootstrap_scope.py` and `test_scope_enforcement.py` |
| P2 | `mcp-herbal-botanicals/Makefile` | 195-223 | Target conventions; new `lightrag-bootstrap-scope` and `lightrag-canary-test` targets follow these |
| P2 | `mcp-herbal-botanicals/lightrag/config_local.env` | 33-36 | NEO4J_URI/USERNAME/PASSWORD env var names; wrapper re-reads these |
| P2 | `.claude/PRPs/reports/multi-tenant-query-gateway-report.md` | 62-67 | Report explicitly flags server-side enforcement as open — this plan closes it |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| `contextvars` in async Python | Python 3.11 docs — `contextvars.ContextVar` | ContextVar values propagate across `await` within the same task; perfect for passing per-request scope from FastAPI handler → deep storage call without threading arguments through LightRAG's internals |
| Neo4j property indexes | Neo4j 5.x docs | `CREATE INDEX name IF NOT EXISTS FOR (n:Label) ON (n.scope)` — idempotent; prefer over composite since `entity_type` is a label not a property in LightRAG's model |
| Neo4j relationship property indexes | Neo4j 5.x docs | `CREATE INDEX r_scope_idx IF NOT EXISTS FOR ()-[r]-() ON (r.scope)` — required because LightRAG also does `MATCH ()-[r]->()` edge reads |
| LightRAG custom storage override | LightRAG README — `graph_storage` / `kv_storage` pluggable backends | `LightRAG(graph_storage_cls=ScopedNeo4JStorage)` is the supported hook (constructor accepts class); confirm at implementation time |
| Clerk org_id format | Clerk docs — "Organization" | Canonical: `org_<base58>`; uppercase & underscore; 27-32 chars typical; immutable per org |
| FastAPI dependency injection + contextvars | FastAPI docs — background tasks | Set contextvar in a `Depends()` or directly in the handler before awaiting the LightRAG call |

```
KEY_INSIGHT: LightRAG's Neo4JStorage uses workspace labels (backtick-quoted) plus `entity_id` property for lookups. Adding a WHERE clause on `n.scope` is orthogonal.
APPLIES_TO: ScopedNeo4JStorage subclass — every read method overrides to append `AND n.scope IN $scope_filter`.
GOTCHA: Write paths (upsert_node, upsert_edge) MUST NOT filter — new tenant inserts would be rejected. Only read paths get the WHERE injection.
```

```
KEY_INSIGHT: ContextVar values set in a FastAPI handler propagate through `await` chains automatically — no need to modify QueryParam.
APPLIES_TO: scoped_server.py uses `_SCOPE_FILTER_VAR.set(body.scope_filter)` before `await rag.aquery(...)`; ScopedNeo4JStorage reads `_SCOPE_FILTER_VAR.get()`.
GOTCHA: If no value is set, `.get()` raises LookupError unless a default is provided. Provide default `["shared"]` to fail-safe on missing context.
```

```
KEY_INSIGHT: `ainsert_custom_kg` passes every key in each entity/relationship dict as a Neo4j property. The `scope` field in ingest_unified.py DOES land on new nodes.
APPLIES_TO: Plan assumption verified — Phase 1 bootstrap only needs to tag existing nodes, not retroactively re-ingest.
GOTCHA: Verify this assumption via a one-liner `MATCH (n:unified_diet_kg) WHERE n.scope IS NOT NULL RETURN count(n) LIMIT 1` before running bootstrap — if it returns 0, the ingestion path is also broken and Phase 1 must re-ingest, not just tag.
```

---

## Patterns to Mirror

### NAMING_CONVENTION
// SOURCE: `mcp-herbal-botanicals/lightrag/fix_unknown_entities.py:1-24`
```python
"""
<One-line purpose>

<Why this exists, what it does, what the input/output looks like.>

Usage:
    python fix_unknown_entities.py --config local --dry-run
    python fix_unknown_entities.py --config local
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
```
New Python scripts (`bootstrap_scope.py`, `scoped_server.py`) mirror this header + argparse + dotenv pattern.

### ERROR_HANDLING (TypeScript)
// SOURCE: `mcp-herbal-botanicals/src/tenant.ts:38-45`
```typescript
export function validateTenantId(tenantId: string | null): void {
  if (tenantId === null) return;
  if (!TENANT_ID_PATTERN.test(tenantId)) {
    throw new Error(
      `Invalid tenant_id "${tenantId}": must be 3-64 lowercase alphanumeric characters or hyphens`,
    );
  }
}
```
`clerkOrgMapping.ts` uses identical throw-on-invalid pattern; the updated error message references the new mapping doc.

### ERROR_HANDLING (Python)
// SOURCE: `mcp-herbal-botanicals/lightrag/ingest_unified.py` (existing style)
```python
if not os.environ.get("NEO4J_URI"):
    raise RuntimeError("NEO4J_URI not set — check config_{local,production}.env")
```
Fail-fast at startup on missing config; no silent defaults. Bootstrap and scoped server follow this.

### LOGGING_PATTERN
// SOURCE: `mcp-herbal-botanicals/lightrag/fix_unknown_entities.py` (existing style — `print()` for scripts, stderr for MCP)
Scripts use `print(f"[bootstrap-scope] ...")` to stderr for progress; MCP server uses `console.error(...)` as in `src/index.ts:592`. New scoped_server logs via Python `logging` at INFO level with tenant_id on every query.

### NEO4J_DRIVER_PATTERN
// SOURCE: `lightrag/lightrag/kg/neo4j_impl.py:25-30, 67-143`
```python
from neo4j import AsyncGraphDatabase

class Neo4JStorage(BaseGraphStorage):
    def __init__(self, ...):
        self._driver_uri = os.environ["NEO4J_URI"]
        self._driver_user = os.environ["NEO4J_USERNAME"]
        self._driver_password = os.environ["NEO4J_PASSWORD"]

    async def initialize(self):
        self._driver = AsyncGraphDatabase.driver(
            self._driver_uri, auth=(self._driver_user, self._driver_password)
        )
```
Bootstrap script uses the **sync** `neo4j.GraphDatabase` driver (one-shot context). `ScopedNeo4JStorage` inherits the async one.

### TEST_STRUCTURE (Python)
// SOURCE: `mcp-herbal-botanicals/lightrag/test_ingest.py:1-30`
```python
import pytest
from entity_schema import ENTITY_TYPES, describe_entity

@pytest.mark.unit
def test_describe_entity_protocol():
    result = describe_entity("Protocol", {"name": "Anti-inflammation", "phases": "screening,treatment"})
    assert "Anti-inflammation" in result
```
New tests: `test_bootstrap_scope.py` uses `@pytest.mark.integration` (requires Neo4j); `test_scope_enforcement.py` uses both `@pytest.mark.unit` (context var propagation) and `@pytest.mark.integration` (canary roundtrip).

### TEST_STRUCTURE (TypeScript)
// SOURCE: `mcp-herbal-botanicals/src/__tests__/tenant.test.ts:1-20`
```typescript
import { describe, it, expect } from 'vitest';
import { extractTenantContext, validateTenantId } from '../tenant.js';

describe('extractTenantContext', () => {
  it('returns shared-only when meta is undefined', () => {
    const ctx = extractTenantContext(undefined);
    expect(ctx.tenantId).toBeNull();
  });
});
```
`clerkOrgMapping.test.ts` mirrors this exactly.

### MAKEFILE_TARGET
// SOURCE: `mcp-herbal-botanicals/Makefile:199-201`
```makefile
lightrag-dry-run: ## Dry-run ingestion — print entity/relationship counts (no writes)
	cd lightrag && python3 ingest_unified.py --config local --dry-run
```
New targets: `lightrag-bootstrap-scope`, `lightrag-bootstrap-scope-dry-run`, `lightrag-canary-test`, `lightrag-server` (updated to run `scoped_server.py`).

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `mcp-herbal-botanicals/lightrag/bootstrap_scope.py` | CREATE | One-shot migration: tag all nodes+edges `scope='shared'`, create indexes, verify |
| `mcp-herbal-botanicals/lightrag/scope_context.py` | CREATE | `ContextVar[list[str]]` module + helpers; single source of truth for per-request scope |
| `mcp-herbal-botanicals/lightrag/scoped_neo4j_storage.py` | CREATE | `ScopedNeo4JStorage(Neo4JStorage)` — overrides read methods to inject WHERE clause |
| `mcp-herbal-botanicals/lightrag/scoped_server.py` | CREATE | Minimal FastAPI app; `/query` endpoint with `scope_filter`; sets ContextVar; wraps LightRAG |
| `mcp-herbal-botanicals/lightrag/test_bootstrap_scope.py` | CREATE | Integration tests against Neo4j — migration idempotent, preflight check, index creation |
| `mcp-herbal-botanicals/lightrag/test_scope_enforcement.py` | CREATE | Unit (contextvar, Cypher generation) + integration (canary cross-tenant) |
| `mcp-herbal-botanicals/lightrag/canary_smoke_test.py` | CREATE | Runnable CI canary: insert sentinel, query as wrong tenant, assert empty |
| `mcp-herbal-botanicals/src/clerkOrgMapping.ts` | CREATE | `slugifyClerkOrgId(orgId)` reference utility for consumers |
| `mcp-herbal-botanicals/src/__tests__/clerkOrgMapping.test.ts` | CREATE | Vitest coverage for slugifier |
| `mcp-herbal-botanicals/docs/tenant-mapping.md` | CREATE | Canonical doc: Clerk `org_id` → `tenant_id` rule, examples, consumer code snippets |
| `mcp-herbal-botanicals/src/tenant.ts` | UPDATE | Error message at L41-44 references `docs/tenant-mapping.md`; no regex change |
| `mcp-herbal-botanicals/Makefile` | UPDATE | Add 4 targets; point `lightrag-server` at `scoped_server.py` |
| `mcp-herbal-botanicals/lightrag/requirements.txt` | UPDATE | Pin `fastapi`, `uvicorn`, `python-dotenv` if not already present |
| `mcp-herbal-botanicals/package.json` | UPDATE | Add `test:canary` script that runs Python canary post-build |
| `CLAUDE.md` | UPDATE | New "Tenant Scoping" section: how enforcement works, how to run canary, Clerk mapping pointer |

## NOT Building

- **Tenant registry table or Clerk webhook** — lives in Syntropy-Journals, not here. This plan only ships a slug utility + docs.
- **Phase 4 ingestion tool** (`ingest-tenant-data` MCP tool) — separate plan after this lands.
- **Tenant auth / API keys** — this plan assumes ShrineAgent is trusted to send correct `tenant_id`. Authenticity is the consumer's responsibility.
- **Cypher for all 14 SQLite tools to accept `tenant_id`** — SQLite has no tenant data; tenant_id would be a no-op. Deferred.
- **Replacement for other LightRAG endpoints** (`/documents`, `/health`, admin). `scoped_server.py` only serves `/query` and `/healthz`. Other endpoints return 404 until a future plan.
- **Rate limiting, caching, circuit breakers** on the wrapper — flagged for a later ops-readiness plan.
- **Migration to separate Neo4j databases per tenant** — PRD explicitly rules this out.
- **Re-ingestion of the 7,722 existing nodes** — bootstrap updates in-place via `SET n.scope='shared'`; no re-embedding.

---

## Step-by-Step Tasks

Tasks are grouped into **3 tracks** that can run sequentially. Track A (bootstrap) MUST complete and be verified on Neo4j before Track B's canary test can pass. Track C (Clerk mapping) is independent and can run in parallel with A or B.

### TRACK A — Phase 1 Scope Bootstrap

#### Task A1: Verify assumption that new entities carry `scope` into Neo4j
- **ACTION**: Run a one-shot Cypher check against the current Neo4j instance to determine whether `ainsert_custom_kg` actually persists the `scope` field. This gates whether bootstrap is sufficient or re-ingest is required.
- **IMPLEMENT**: Connect via sync neo4j driver, run `MATCH (n:\`unified_diet_kg\`) WHERE n.scope IS NOT NULL RETURN count(n) AS with_scope, (MATCH (n:\`unified_diet_kg\`) RETURN count(n)) AS total`. Log both counts.
- **MIRROR**: `fix_unknown_entities.py:1-40` for argparse + dotenv loading.
- **IMPORTS**: `from neo4j import GraphDatabase`, `from dotenv import load_dotenv`
- **GOTCHA**: If `with_scope == 0`, ingestion is not writing scope despite the dict containing it — file a follow-up task to investigate LightRAG's property filter. Do NOT proceed with bootstrap until resolved — tagging existing nodes would fix nothing for future ingests.
- **VALIDATE**: `python3 lightrag/bootstrap_scope.py --config local --probe` prints counts. Proceed only if `with_scope > 0` for recently-ingested tenant types (Protocol/Intervention — should be 0 since none exist) and all Herb/Compound/Food nodes (should equal total for that label).

#### Task A2: Implement `bootstrap_scope.py` migration
- **ACTION**: Build the one-shot migration that tags all existing nodes + edges with `scope='shared'` and creates indexes. Idempotent: re-running is a no-op.
- **IMPLEMENT**:
  ```python
  # Pseudo-structure
  def run(dry_run: bool, workspace: str) -> BootstrapReport:
      with driver.session() as s:
          # 1. Count nodes/edges missing scope
          missing_nodes = s.run(f"MATCH (n:`{workspace}`) WHERE n.scope IS NULL RETURN count(n)").single()[0]
          missing_edges = s.run(f"MATCH (:`{workspace}`)-[r]-(:`{workspace}`) WHERE r.scope IS NULL RETURN count(r)").single()[0]
          if dry_run: return BootstrapReport(missing_nodes, missing_edges, 0, 0)
          # 2. Tag in batches of 10k to avoid long transactions
          s.run(f"MATCH (n:`{workspace}`) WHERE n.scope IS NULL SET n.scope = 'shared'")
          s.run(f"MATCH (:`{workspace}`)-[r]-(:`{workspace}`) WHERE r.scope IS NULL SET r.scope = 'shared'")
          # 3. Indexes (idempotent)
          s.run(f"CREATE INDEX scope_node_idx IF NOT EXISTS FOR (n:`{workspace}`) ON (n.scope)")
          s.run("CREATE INDEX scope_rel_idx IF NOT EXISTS FOR ()-[r]-() ON (r.scope)")
          # 4. Verify
          leftover = s.run(f"MATCH (n:`{workspace}`) WHERE n.scope IS NULL RETURN count(n)").single()[0]
          assert leftover == 0, f"Bootstrap incomplete: {leftover} nodes still missing scope"
      return BootstrapReport(...)
  ```
- **MIRROR**: `fix_unknown_entities.py` header + argparse + `--config local/production` + `--dry-run` flag. Use sync `neo4j.GraphDatabase` driver (one-shot).
- **IMPORTS**: `import argparse`, `import os`, `from pathlib import Path`, `from dataclasses import dataclass`, `from dotenv import load_dotenv`, `from neo4j import GraphDatabase`
- **GOTCHA**: Workspace label must be backtick-escaped in Cypher (labels are not parameterizable). Read the workspace name from env `LIGHTRAG_WORKSPACE` or default `unified_diet_kg`. Run `SET` statements inside a single transaction per batch; for a 7,722-node graph a single transaction is fine, but parameterize the batch size for future large graphs.
- **VALIDATE**:
  - `python3 lightrag/bootstrap_scope.py --config local --dry-run` prints "N nodes, M edges to update" without writing.
  - `python3 lightrag/bootstrap_scope.py --config local` completes, prints "0 nodes remaining without scope", creates both indexes.
  - Re-running is a no-op: "0 nodes, 0 edges to update".

#### Task A3: Add Makefile target
- **ACTION**: Wire `bootstrap_scope.py` into Makefile with two targets (dry-run + apply).
- **IMPLEMENT**:
  ```makefile
  lightrag-bootstrap-scope-dry-run: ## Preview scope bootstrap — counts only, no writes
  	cd lightrag && python3 bootstrap_scope.py --config local --dry-run

  lightrag-bootstrap-scope: ## Tag existing nodes+edges with scope='shared' and create indexes
  	cd lightrag && python3 bootstrap_scope.py --config local
  ```
- **MIRROR**: `Makefile:199-201` for indentation (tab, not spaces) and `## ` comment style (used by `make help`).
- **IMPORTS**: N/A
- **GOTCHA**: Makefile uses tabs not spaces; copy-paste from editor may convert.
- **VALIDATE**: `make help | grep bootstrap-scope` shows both new targets.

#### Task A4: Write integration tests for bootstrap
- **ACTION**: `test_bootstrap_scope.py` covers: idempotency, dry-run accuracy, post-run invariant (0 missing).
- **IMPLEMENT**: Three tests marked `@pytest.mark.integration` (require running Neo4j):
  - `test_bootstrap_dry_run_does_not_write` — run with `--dry-run`, assert counts match before-state.
  - `test_bootstrap_tags_all_nodes` — run, assert `MATCH (n) WHERE n.scope IS NULL RETURN count(n) == 0`.
  - `test_bootstrap_is_idempotent` — run twice, assert second run reports 0 updates.
- **MIRROR**: `test_ingest.py:1-50` for pytest + dotenv loading + conditional skip when DB unavailable.
- **IMPORTS**: `import pytest`, `from neo4j import GraphDatabase`, `from bootstrap_scope import run, BootstrapReport`
- **GOTCHA**: Integration tests need a test-only Neo4j workspace to avoid polluting dev. Use env `LIGHTRAG_WORKSPACE=bootstrap_test` fixture + teardown via `MATCH (n:\`bootstrap_test\`) DETACH DELETE n`.
- **VALIDATE**: `cd lightrag && python3 -m pytest test_bootstrap_scope.py -m integration -v` — all 3 pass against live Neo4j.

---

### TRACK B — LightRAG Server-Side Scope Enforcement

#### Task B1: Create `scope_context.py` with ContextVar
- **ACTION**: Single source of truth for per-request scope, passed through async call chains without threading args.
- **IMPLEMENT**:
  ```python
  """Per-request scope filter passed via contextvars — no LightRAG submodule changes."""
  from __future__ import annotations
  import contextvars

  SCOPE_FILTER_VAR: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
      "scope_filter", default=["shared"],
  )

  def get_scope_filter() -> list[str]:
      return SCOPE_FILTER_VAR.get()

  def set_scope_filter(values: list[str]) -> contextvars.Token[list[str]]:
      return SCOPE_FILTER_VAR.set(values)
  ```
- **MIRROR**: Python stdlib contextvars docs.
- **IMPORTS**: `import contextvars`
- **GOTCHA**: ContextVar **default** of `["shared"]` is critical — if the storage subclass is called outside a FastAPI request (e.g., by `ingest_unified.py`), the default prevents LookupError and also prevents accidental leakage (fail-safe).
- **VALIDATE**: Simple unit test: set+get roundtrip; get without set returns default.

#### Task B2: Implement `ScopedNeo4JStorage` subclass
- **ACTION**: Override the read methods on `Neo4JStorage` to inject `AND n.scope IN $scope_filter` into every Cypher query. Write methods inherited unchanged.
- **IMPLEMENT**:
  ```python
  """ScopedNeo4JStorage — Neo4JStorage subclass with per-query scope enforcement.

  Reads ContextVar[scope_filter] on every retrieval call and appends a
  WHERE clause to the Cypher template. Writes are unaffected (tenant ingestion
  writes `scope` via the custom_kg payload, which inherits unchanged).
  """
  from __future__ import annotations
  from lightrag.kg.neo4j_impl import Neo4JStorage
  from scope_context import get_scope_filter

  class ScopedNeo4JStorage(Neo4JStorage):
      async def get_node(self, node_id: str):
          scope = get_scope_filter()
          async with self._driver.session() as s:
              result = await s.run(
                  f"MATCH (n:`{self._workspace_label}`) "
                  f"WHERE n.entity_id = $id AND n.scope IN $scope "
                  f"RETURN n",
                  id=node_id, scope=scope,
              )
              # ... unchanged return shape
      # Override every other read method: get_nodes, get_edge, get_edges,
      # has_node, has_edge, get_all_labels, etc.
  ```
- **MIRROR**: `lightrag/lightrag/kg/neo4j_impl.py:458-671` — read each read method signature and transplant its body with the WHERE injection. Do NOT touch `upsert_node`, `upsert_edge`, `delete_node`, etc.
- **IMPORTS**: `from lightrag.kg.neo4j_impl import Neo4JStorage`, `from scope_context import get_scope_filter`
- **GOTCHA 1**: LightRAG's retrieval also does bulk reads (`get_nodes`, `get_edges_for_nodes`). Each must be overridden or `scope` leaks. Grep the upstream file for `async def` on read methods and override them all — no partial coverage.
- **GOTCHA 2**: Some upstream methods may use driver-session inside a loop; preserve original structure to avoid perf regressions. Only add the WHERE clause.
- **GOTCHA 3**: Vector retrieval happens BEFORE the graph lookup in LightRAG's pipeline. Scope filter on graph reads means: vector search may rank a tenant:X chunk highly, but the subsequent graph read filters it out — this yields fewer-than-top_k results. Acceptable trade-off for correctness. Document in the module docstring.
- **VALIDATE**: Unit test calls `get_node` with different ContextVar values and asserts the executed Cypher contains the right `$scope` param. Use neo4j driver's query-interception or mock the driver.

#### Task B3: Implement `scoped_server.py` FastAPI wrapper
- **ACTION**: Thin FastAPI app that hosts LightRAG with `ScopedNeo4JStorage`, exposes `/query` with `scope_filter`, sets ContextVar, forwards to `rag.aquery()`.
- **IMPLEMENT**:
  ```python
  """Scoped LightRAG server — replaces upstream `lightrag-server` binary.

  Hosts LightRAG with ScopedNeo4JStorage and plumbs per-request scope_filter
  through a ContextVar. Only /query and /healthz are exposed; other upstream
  endpoints are out of scope for this iteration.

  Usage: python3 scoped_server.py --config local
  """
  from __future__ import annotations
  import argparse, os
  from pathlib import Path
  from fastapi import FastAPI, HTTPException
  from pydantic import BaseModel, Field
  from dotenv import load_dotenv
  from lightrag import LightRAG, QueryParam
  from scoped_neo4j_storage import ScopedNeo4JStorage
  from scope_context import set_scope_filter

  app = FastAPI()

  class QueryBody(BaseModel):
      query: str = Field(min_length=1)
      mode: str = Field(default="hybrid")
      top_k: int = Field(default=60, ge=1, le=200)
      scope_filter: list[str] = Field(default_factory=lambda: ["shared"])

  @app.post("/query")
  async def query(body: QueryBody):
      _reject_invalid_scope(body.scope_filter)
      token = set_scope_filter(body.scope_filter)
      try:
          result = await app.state.rag.aquery(
              body.query,
              param=QueryParam(mode=body.mode, top_k=body.top_k),
          )
          return {"result": result, "scope_filter": body.scope_filter}
      finally:
          # ContextVar token ensures cleanup even on exception
          from scope_context import SCOPE_FILTER_VAR
          SCOPE_FILTER_VAR.reset(token)

  @app.get("/healthz")
  async def healthz():
      return {"status": "ok"}

  # ... main() instantiates LightRAG with graph_storage_cls=ScopedNeo4JStorage
  ```
- **MIRROR**: `lightrag/lightrag/api/lightrag_server.py:1-70` for dotenv loading, config paths, uvicorn startup. `lightrag/lightrag/api/routers/query_routes.py:16-143` for request schema shape.
- **IMPORTS**: `from fastapi import FastAPI, HTTPException`, `from pydantic import BaseModel, Field`, `from lightrag import LightRAG, QueryParam`, `from scoped_neo4j_storage import ScopedNeo4JStorage`, `from scope_context import set_scope_filter, SCOPE_FILTER_VAR`, `import uvicorn`
- **GOTCHA 1**: LightRAG constructor takes `graph_storage` as either a string key (for built-in) or a class — verify the correct kwarg name at implementation by reading LightRAG's `LightRAG.__init__` signature. If the class-injection path doesn't exist, fall back to monkey-patching `Neo4JStorage` before LightRAG imports it.
- **GOTCHA 2**: `_reject_invalid_scope()` must validate each entry matches `^(shared|tenant:[a-z0-9][a-z0-9-]{1,62}[a-z0-9])$` — defense in depth against MCP-layer bypasses.
- **GOTCHA 3**: FastAPI + uvicorn bound to 0.0.0.0:9621 exposes to LAN. Bind to 127.0.0.1 by default; gate prod bind via `LIGHTRAG_BIND_HOST` env.
- **GOTCHA 4**: ContextVar reset via token is important — without it, the value bleeds into the next request handled by the same asyncio task slot. Always use try/finally.
- **VALIDATE**: `python3 scoped_server.py --config local` starts; `curl -X POST localhost:9621/query -d '{"query":"turmeric","mode":"hybrid"}'` returns a result. With `scope_filter=["shared","tenant:does-not-exist"]`, results are identical to `["shared"]` because no tenant data exists yet.

#### Task B4: Update Makefile `lightrag-server` target
- **ACTION**: Redirect `make lightrag-server` to run our wrapper instead of upstream binary.
- **IMPLEMENT**:
  ```makefile
  lightrag-server: ## Start SCOPED LightRAG API server (tenant isolation enforced)
  	cd lightrag && python3 scoped_server.py --config local
  ```
- **MIRROR**: Existing target format.
- **IMPORTS**: N/A
- **GOTCHA**: The upstream binary is preserved at `cd lightrag && lightrag-server` if anyone needs it for debugging. Document this in a comment.
- **VALIDATE**: `make lightrag-server` boots on port 9621.

#### Task B5: Write canary smoke test + pytest integration
- **ACTION**: Irrefutable proof of cross-tenant isolation. MUST be green in CI before any integration doc is written.
- **IMPLEMENT**: `canary_smoke_test.py` is a standalone script that:
  1. Uses sync neo4j driver to insert two sentinel nodes: `CREATE (:unified_diet_kg {entity_id: 'canary-A', scope: 'tenant:canary-a', description: 'sentinel-A'})` and same for `canary-b`.
  2. POSTs to `localhost:9621/query` with `scope_filter=['shared','tenant:canary-a']` and the query "sentinel".
  3. Asserts response contains `canary-A` and does NOT contain `canary-B`.
  4. Repeats swapped.
  5. Cleans up: `MATCH (n {entity_id: 'canary-A' OR entity_id: 'canary-B'}) DETACH DELETE n`.

  `test_scope_enforcement.py` wraps the above as a pytest `@pytest.mark.integration` test plus unit tests for:
  - ContextVar set/get roundtrip in async context.
  - `ScopedNeo4JStorage` Cypher generation — mock driver, assert WHERE clause appears.
  - `_reject_invalid_scope()` throws on malformed tags.

- **MIRROR**: `test_ingest.py:1-50` for fixture patterns.
- **IMPORTS**: `import httpx`, `from neo4j import GraphDatabase`, `import pytest`, `import asyncio`
- **GOTCHA**: Scoped server must be running for integration tests. Either (a) start it as a pytest fixture with `subprocess.Popen` + teardown, or (b) require users to `make lightrag-server &` before `pytest -m integration`. Document choice.
- **VALIDATE**: `python3 lightrag/canary_smoke_test.py` exits 0 with "CANARY PASSED: cross-tenant isolation verified". Non-zero exit if any leakage detected.

#### Task B6: Add CI-facing Makefile target
- **ACTION**: One command a CI pipeline can call to run the canary.
- **IMPLEMENT**:
  ```makefile
  lightrag-canary-test: ## CI gate: verify cross-tenant isolation end-to-end
  	cd lightrag && python3 canary_smoke_test.py --config local
  ```
- **MIRROR**: Existing Makefile targets.
- **GOTCHA**: CI must run bootstrap first — document that dependency in the target description.
- **VALIDATE**: `make lightrag-canary-test` passes locally after bootstrap + scoped_server running.

---

### TRACK C — Clerk org_id → tenant_id Mapping

#### Task C1: Implement TypeScript slugifier
- **ACTION**: Reference utility that consumers (Syntropy-Journals) import. Converts Clerk `org_2abc123XYZ` to regex-valid `org-2abc123xyz`.
- **IMPLEMENT**:
  ```typescript
  /**
   * Convert a Clerk org_id into a tenant_id slug that passes the MCP regex.
   *
   * Rule:
   *   1. Lowercase
   *   2. Replace underscores with hyphens
   *   3. Strip any characters not in [a-z0-9-]
   *   4. Collapse repeated hyphens
   *   5. Trim leading/trailing hyphens
   *   6. Truncate to 64 chars
   *   7. Validate against TENANT_ID_PATTERN
   *
   * Returns null if the result is <3 chars or otherwise fails validation.
   */
  export function slugifyClerkOrgId(orgId: string): string | null {
    if (typeof orgId !== 'string' || !orgId) return null;
    let slug = orgId.toLowerCase().replace(/_/g, '-').replace(/[^a-z0-9-]/g, '');
    slug = slug.replace(/-+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
    return /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/.test(slug) ? slug : null;
  }
  ```
- **MIRROR**: `src/tenant.ts:1-11` for JSDoc header style + regex constant co-location.
- **IMPORTS**: None (pure function).
- **GOTCHA**: Null return is intentional — caller must handle "org_id cannot be mapped" as an explicit branch (fail-closed). Do NOT throw, because this runs in hot paths.
- **VALIDATE**: Unit tests in `__tests__/clerkOrgMapping.test.ts`.

#### Task C2: Write TypeScript tests
- **ACTION**: Vitest coverage for slugifier — happy path + edge cases.
- **IMPLEMENT**: Tests:
  - `'org_2abc123XYZ' → 'org-2abc123xyz'`
  - `'org_A' → null` (too short after strip)
  - `'ORG_' → null` (invalid after trim)
  - `null/undefined/123 → null` (bad input types)
  - Max-length input (65 chars of mixed case) → truncated and validated
  - Unicode input (`'org_café'`) → stripped to `'org-caf'` or null
- **MIRROR**: `src/__tests__/tenant.test.ts:1-115` exactly.
- **IMPORTS**: `import { describe, it, expect } from 'vitest'`, `import { slugifyClerkOrgId } from '../clerkOrgMapping'`
- **GOTCHA**: Don't over-test — focus on the documented rules, not every possible Clerk format edge.
- **VALIDATE**: `npm test -- clerkOrgMapping` all green.

#### Task C3: Write the canonical mapping doc
- **ACTION**: `docs/tenant-mapping.md` is the single source of truth for the Clerk → tenant_id rule. The updated tenant.ts error message references this file.
- **IMPLEMENT**: Markdown doc with sections:
  - **The rule** (the 7-step algorithm from C1's JSDoc).
  - **Why a slug at all** (explain the regex constraint and Neo4j property-string usage).
  - **Worked examples** table (Clerk input → slug output, 6 rows).
  - **Where to store the mapping** (recommend a `tenant_registry` table in the consumer DB; provide Postgres DDL as reference).
  - **How to integrate** — TypeScript snippet showing ShrineAgent calling `slugifyClerkOrgId()` before every MCP tool call.
  - **Collision handling** — probability is low for random Clerk IDs; if it happens, recommend appending hash suffix in the registry.
- **MIRROR**: Existing repo docs like `docs/unified-diet-kg-architecture.md`.
- **GOTCHA**: Do NOT recommend auto-normalization inside the MCP server. That hides misconfigurations.
- **VALIDATE**: Doc renders on GitHub with working table and fenced code. Link-check: `CLAUDE.md` and `src/tenant.ts` error message point to it.

#### Task C4: Update tenant.ts error message
- **ACTION**: Error thrown by `validateTenantId` should point to the mapping doc so integrators immediately know how to fix Clerk format mismatches.
- **IMPLEMENT**:
  ```typescript
  throw new Error(
    `Invalid tenant_id "${tenantId}": must match /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/. ` +
    `To derive a tenant_id from a Clerk org_id, see docs/tenant-mapping.md or ` +
    `use slugifyClerkOrgId() from ./clerkOrgMapping.`,
  );
  ```
- **MIRROR**: Existing error message style at `src/tenant.ts:41-43`.
- **IMPORTS**: N/A.
- **GOTCHA**: Error messages propagate through MCP — keep under 256 chars to avoid client truncation.
- **VALIDATE**: Update `tenant.test.ts` assertion to match new message; all existing tests pass.

#### Task C5: Provide Python slug utility (parity)
- **ACTION**: Python equivalent for internal scripts/tools that need to produce slugs (demo seeding, CLI).
- **IMPLEMENT**: `mcp-herbal-botanicals/lightrag/clerk_mapping.py`:
  ```python
  """Reference slugifier for Clerk org_id → tenant_id (parity with src/clerkOrgMapping.ts)."""
  from __future__ import annotations
  import re

  _TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")

  def slugify_clerk_org_id(org_id: str | None) -> str | None:
      if not isinstance(org_id, str) or not org_id:
          return None
      slug = org_id.lower().replace("_", "-")
      slug = re.sub(r"[^a-z0-9-]", "", slug)
      slug = re.sub(r"-+", "-", slug).strip("-")[:64]
      return slug if _TENANT_RE.match(slug) else None
  ```
- **MIRROR**: `slugifyClerkOrgId` semantics exactly (test parity via identical test cases in both languages).
- **IMPORTS**: `import re`.
- **GOTCHA**: Keep TypeScript and Python implementations semantically identical — add a comment in each linking to the other.
- **VALIDATE**: Pytest test cases match TypeScript test cases 1:1 in `lightrag/test_clerk_mapping.py`.

---

### CROSS-CUTTING — Docs & Plumbing

#### Task D1: Update CLAUDE.md
- **ACTION**: Add a "Tenant Scoping" section documenting: what enforcement is now real, how to run bootstrap, how to run canary, where mapping lives.
- **IMPLEMENT**: New section after "Architecture", ~40 lines. Subsections: Scope Bootstrap, Server-Side Enforcement (scoped_server.py), Canary Test, Clerk Mapping (link).
- **MIRROR**: Existing CLAUDE.md tone and structure.
- **GOTCHA**: Do NOT claim tenant isolation is "complete" — list the remaining Phase 4 (ingestion) and Phase 5 (demo) gaps.
- **VALIDATE**: Section renders on GitHub; all mentioned commands are discoverable via `make help`.

#### Task D2: Update requirements.txt + package.json
- **ACTION**: Pin any new deps introduced by `scoped_server.py` (fastapi, uvicorn, httpx for tests).
- **IMPLEMENT**:
  - `lightrag/requirements.txt`: add if missing: `fastapi>=0.115`, `uvicorn>=0.30`, `httpx>=0.27`, `pytest-asyncio>=0.24`.
  - `package.json`: add script `"test:canary": "python3 lightrag/canary_smoke_test.py"`.
- **MIRROR**: Existing version-pinning conventions in the two files.
- **GOTCHA**: LightRAG already pins fastapi/uvicorn; avoid version conflicts by matching LightRAG's pins.
- **VALIDATE**: `pip install -r lightrag/requirements.txt` and `npm install` both succeed with no warnings.

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `slugifyClerkOrgId('org_2abc123XYZ')` | valid Clerk ID | `'org-2abc123xyz'` | No |
| `slugifyClerkOrgId('')` | empty | `null` | Yes |
| `slugifyClerkOrgId('_')` | all strippable | `null` | Yes |
| `slugifyClerkOrgId('a'.repeat(100))` | > 64 chars | truncated and validated or null | Yes |
| `get_scope_filter()` without prior set | cold context | `['shared']` (default) | Yes |
| `set_scope_filter(['tenant:x'])` then get | set | `['tenant:x']` | No |
| `_reject_invalid_scope(['../../etc/passwd'])` | injection | throws HTTPException | Yes |
| `ScopedNeo4JStorage.get_node` | mock driver | Cypher contains `AND n.scope IN $scope` | No |
| `bootstrap_scope.run(dry_run=True)` | fixture Neo4j with 10 untagged nodes | `BootstrapReport(missing_nodes=10, updated=0)` | Yes |
| `bootstrap_scope.run(dry_run=False)` twice | fixture | First writes 10, second writes 0 | Yes (idempotency) |

### Integration Tests

| Test | Setup | Assertion |
|---|---|---|
| `test_canary_cross_tenant_isolation` | Insert `tenant:canary-a` + `tenant:canary-b` sentinels | Query as `canary-a` returns A not B; query as `canary-b` returns B not A |
| `test_shared_visible_to_all_tenants` | Use existing shared data | Query with any tenant_id returns shared entities |
| `test_no_scope_yields_zero` | Temporarily clear scope on one node | Scoped query returns empty — verifies preflight gate catches this |
| `test_bootstrap_idempotent_on_live_graph` | Real Neo4j with mixed state | Two consecutive runs; second reports 0 updates |

### Edge Cases Checklist
- [x] Empty input (scope_filter=[]) — rejected by pydantic min_items or normalized to `['shared']`
- [x] Maximum size input (scope_filter with 1000 entries) — rejected (max 10 entries per pydantic)
- [x] Invalid types (scope_filter=None, scope_filter='shared') — pydantic rejects
- [x] Concurrent requests with different tenant_ids — ContextVar token reset prevents bleed (verified by asyncio task interleaving test)
- [x] Network failure mid-query — FastAPI catches; MCP gets HTTP 5xx; client retries or falls back to SQLite tools
- [x] Permission denied on Neo4j (bootstrap) — fail-fast with clear message
- [x] Bootstrap interrupted mid-run — idempotent; resumes on next run
- [x] Scope injection attempt (`tenant:' OR '1'='1`) — regex validation rejects; defense-in-depth at both MCP and wrapper layers

---

## Validation Commands

### Static Analysis
```bash
cd mcp-herbal-botanicals && npm run build          # TypeScript
cd mcp-herbal-botanicals/lightrag && python3 -m py_compile bootstrap_scope.py scoped_server.py scoped_neo4j_storage.py scope_context.py clerk_mapping.py
```
EXPECT: Zero type errors / zero compile errors.

### Unit Tests
```bash
cd mcp-herbal-botanicals && npm test -- tenant clerkOrgMapping semantic-search-scope
cd mcp-herbal-botanicals/lightrag && python3 -m pytest -m unit -v
```
EXPECT: All unit tests pass (TypeScript: ≥30 tests total; Python: ≥15 unit tests).

### Integration Tests (require running Neo4j + scoped_server)
```bash
# Prereq: Neo4j running, bootstrap applied, scoped_server up
cd mcp-herbal-botanicals && make lightrag-bootstrap-scope
cd mcp-herbal-botanicals && make lightrag-server &
cd mcp-herbal-botanicals && make lightrag-canary-test
cd mcp-herbal-botanicals/lightrag && python3 -m pytest -m integration -v
```
EXPECT: Canary exits 0 with "CANARY PASSED"; all integration tests green.

### Full Test Suite
```bash
cd mcp-herbal-botanicals && npm test
cd mcp-herbal-botanicals/lightrag && python3 -m pytest -v
```
EXPECT: No regressions (baseline before this plan: 45 TS + 42 py tests; after: ≥60 TS + ≥60 py).

### Database Validation
```bash
cd mcp-herbal-botanicals && make lightrag-bootstrap-scope-dry-run
```
EXPECT: Output shows `missing_nodes=0 missing_edges=0` after initial bootstrap has been applied.

### Preflight Check (CI gate)
```bash
# Must return 0; non-zero blocks deploys
cypher-shell -a $NEO4J_URI -u $NEO4J_USERNAME -p $NEO4J_PASSWORD \
  "MATCH (n:\`unified_diet_kg\`) WHERE n.scope IS NULL RETURN count(n) AS untagged"
```
EXPECT: `untagged = 0`.

### Manual Validation
- [ ] `make lightrag-bootstrap-scope-dry-run` shows reasonable before/after numbers (~7,722 nodes, ~795 edges).
- [ ] `make lightrag-bootstrap-scope` completes without error; re-run shows `0 updates`.
- [ ] `make lightrag-server` starts and `curl localhost:9621/healthz` returns `{"status":"ok"}`.
- [ ] `curl -X POST localhost:9621/query -d '{"query":"turmeric","mode":"hybrid","scope_filter":["shared"]}'` returns results.
- [ ] `curl -X POST localhost:9621/query -d '{"query":"turmeric","mode":"hybrid","scope_filter":["shared","tenant:foo"]}'` returns the same shared results (no tenant data yet) + `_tenant_canary_absent = true` metadata.
- [ ] `make lightrag-canary-test` prints "CANARY PASSED".
- [ ] `npm test -- clerkOrgMapping` passes; `slugifyClerkOrgId('org_2abc123XYZ')` returns `'org-2abc123xyz'`.
- [ ] `docs/tenant-mapping.md` renders correctly on GitHub with worked examples.

---

## Acceptance Criteria
- [ ] All 3 tracks' tasks (A1–A4, B1–B6, C1–C5) completed.
- [ ] All validation commands pass.
- [ ] Canary cross-tenant isolation test green locally and documented in CLAUDE.md.
- [ ] Bootstrap is idempotent; re-running produces zero updates.
- [ ] No TypeScript build errors; no Python type errors (mypy lightrag/*.py).
- [ ] No lint errors (`ruff check lightrag/` and `npm run lint` if configured).
- [ ] Existing 45+ TS and 42 Python tests continue to pass (no regressions).
- [ ] `docs/tenant-mapping.md` exists with examples, linked from CLAUDE.md and tenant.ts error message.
- [ ] Matches UX design: ShrineAgent → slugify → MCP → scoped_server → ScopedNeo4JStorage → filtered Neo4j results.

## Completion Checklist
- [ ] Code follows discovered patterns (fix_unknown_entities.py header style, tenant.test.ts vitest style, Makefile target comment style).
- [ ] Error handling matches codebase style (throw on invalid input; fail-fast on missing env; try/finally on ContextVar reset).
- [ ] Logging follows codebase conventions (script stderr via `print()`; wrapper via Python `logging`).
- [ ] Tests follow test patterns (`@pytest.mark.unit/integration`, vitest describe/it/expect).
- [ ] No hardcoded values (workspace label from env; Neo4j creds from env; bind host from env).
- [ ] Documentation updated: CLAUDE.md, docs/tenant-mapping.md, updated tenant.ts error message.
- [ ] No unnecessary scope additions (no Phase 4 ingestion, no registry table, no rate limiting).
- [ ] Self-contained — no questions needed during implementation.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LightRAG's `LightRAG()` constructor doesn't accept a custom `graph_storage_cls` | Medium | High — cannot inject ScopedNeo4JStorage cleanly | Fall back to monkey-patching `lightrag.kg.neo4j_impl.Neo4JStorage = ScopedNeo4JStorage` at scoped_server.py import time — verified in Task B3 GOTCHA 1 |
| Upstream LightRAG has more read methods than expected — partial override leaks | Medium | Critical — silent cross-tenant leak | Task B2 requires grepping `lightrag/lightrag/kg/neo4j_impl.py` for `async def` in read context and overriding ALL; add a startup assertion that lists overridden methods vs detected methods |
| `ainsert_custom_kg` does NOT persist the `scope` field on nodes (verification in A1 fails) | Low | High — bootstrap alone won't fix future ingests | If A1 probe returns `with_scope == 0`, add Task A1.5 to patch ingest_unified.py's custom_kg payload shape or file upstream; re-ingest may be needed |
| ContextVar value bleeds across asyncio tasks in some uvicorn worker models | Low | Critical — cross-tenant leak | Task B3 uses `try/finally` with `.reset(token)`; integration test includes concurrent request test that interleaves tenants |
| Neo4j property-value constraints reject `tenant:something` format | Very low | Medium | Neo4j accepts arbitrary strings as property values; regex-validated before insert |
| Bootstrap long transaction locks production Neo4j | Low | Medium (downtime during bootstrap) | Use batch size parameter; document running during low-traffic window; test on staging first |
| Slugify produces collisions for different Clerk orgs | Very low | Medium | Document in tenant-mapping.md: recommend registry with unique constraint on slug; append hash suffix on collision |
| Pydantic default_factory ordering causes `scope_filter=[]` to be treated as no-filter | Low | Critical | Validate `len(scope_filter) >= 1` explicitly in `_reject_invalid_scope`; add test case |

## Notes

- **Architectural decision log**: We chose contextvars over extending LightRAG's `QueryParam` because the latter requires modifying the submodule (upstream divergence). ContextVar is invisible to LightRAG but plumbs through async/await chains exactly like a thread-local would in a sync world.
- **Why not a Neo4j tenant filter plugin**: Neo4j Enterprise has row-level security, but the project uses Community Edition (per PRD). Property-based filtering is the only option.
- **Phase 6 prerequisites**: After this plan lands, Syntropy-Journals integration needs (1) `.mcp.json` entry with `LIGHTRAG_API_URL`, (2) the tenant_registry table (consumer-side), (3) Clerk webhook to populate registry on org.created, (4) ShrineAgent wrapper that resolves org_id → slug → _meta.tenant_id. Those are out of scope here but documented in docs/tenant-mapping.md.
- **Follow-up plan**: Phase 4 (tenant ingestion) — a new MCP tool `ingest-tenant-data` that validates tenant-scoped entities against the Phase 2 schema (Protocol/Intervention/Outcome/Biomarker) and rejects writes that mix shared types with tenant scope (or vice versa).
- **Open decision to defer**: Whether `scoped_server.py` should eventually be upstreamed to LightRAG or live as a permanent wrapper. Keep it local for now; reassess after 30 days of production use.
- **Observability**: This plan adds logging on every tenant query but stops short of per-tenant metrics. A separate ops-readiness plan should add Prometheus counters for `query_count{tenant}`, `empty_result_rate{tenant}`, `p95_latency{tenant}`.
