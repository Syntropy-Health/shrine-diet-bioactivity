# Multi-Tenant Diet Knowledge Graph MCP Toolkit

## Problem Statement

AI agents serving longevity wellness clinics need access to a comprehensive dietary knowledge graph (herbs, compounds, nutrients, targets, diseases) that can be customized per-clinic with proprietary protocols, experimental results, and patient data — without leaking tenant-specific knowledge across organizations. Today, the herbal-botanicals MCP server queries a static shared SQLite/Neo4j graph with no tenant isolation, no access scoping, and no way for clinics to contribute knowledge back into the system.

## Evidence

- Current MCP server has 15 tools but zero tenant awareness — every query sees all data identically
- LightRAG's `ainsert_custom_kg()` supports workspace isolation but only as a static env var, not per-request
- Syntropy-Journals already has a partner portal (`components/partner/`), Clerk auth, and Stripe subscriptions — the user/org identity infrastructure exists
- Neo4j supports label-based and property-based access filtering natively — no separate database needed
- The LightRAG API (`POST /query`) accepts workspace parameters — tenant routing is architecturally feasible

## Proposed Solution

Extend the LightRAG-backed diet knowledge graph into a multi-tenant MCP toolkit where:
1. **Shared knowledge** (dietary KG) is accessible to all tenants
2. **Tenant-specific knowledge** (protocols, experiments, custom relationships) is scoped to the owning organization
3. A **query gateway** rewrites MCP tool calls to enforce tenant boundaries at the Neo4j/LightRAG level
4. The MCP toolkit is consumable by any AI agent (Syntropy's ShrineAgent, external clients, CLI)

## Key Hypothesis

We believe that providing a tenant-scoped dietary knowledge graph via MCP will enable clinics to build AI-powered dietary recommendation tools that combine shared scientific knowledge with their proprietary protocols. We'll know we're right when a demo clinic can add custom herb→condition relationships and query them alongside shared data without seeing other tenants' contributions.

## What We're NOT Building

- Per-tenant Neo4j database instances — single DB with query-time scoping
- A full RBAC system — tenant scoping only (shared vs tenant-owned), not per-user permissions within a tenant
- Patient-facing UI — this is an agent/API toolkit, not a consumer product
- Data pipeline for anonymized patient records — tenant can ingest via API, anonymization is their responsibility
- Billing/metering for knowledge sharing — deferred to later phase

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| Demo readiness | Working multi-tenant demo with 2 simulated clinics | End-to-end walkthrough |
| Tenant isolation | Zero cross-tenant data leakage on 20 test queries | Automated test suite |
| Shared KG coverage | 7,000+ shared entities accessible to all tenants | `make lightrag-metrics` |
| Ingestion latency | Clinic can add 100 relationships in <30s | Timed ingestion test |
| MCP tool response | semantic-search returns in <5s | Benchmark queries |

## Open Questions

- [ ] How does Clerk org_id map to Neo4j tenant scoping? Does ShrineAgent pass org context in MCP calls?
- [x] Should tenant-added nodes inherit shared entity types (Herb, Compound) or get new types? → **Resolved**: 4 orthogonal tenant types (Protocol, Intervention, Outcome, Biomarker) form a clinical practice layer. Injectable/Supplement merged into Intervention (compound + delivery context). ClinicalNote split into structured Outcome + Biomarker for queryable optimization.
- [ ] What's the knowledge sharing model? Can a clinic opt-in to make their relationships "community" visible?
- [ ] How do we handle conflicting tenant claims? (Clinic A says herb X helps condition Y, Clinic B says it doesn't)
- [ ] Should the query planner use different LightRAG modes based on query intent? (local for lookups, hybrid for discovery)

---

## Users & Context

**Primary User**
- **Who**: AI agents (ShrineAgent, external LLM clients) acting on behalf of longevity wellness clinic practitioners
- **Current behavior**: Agents query the shared herbal-botanicals MCP with no tenant context; clinics cannot contribute knowledge
- **Trigger**: A clinic practitioner asks their AI agent a dietary question that requires both shared scientific data AND the clinic's proprietary protocols
- **Success state**: Agent seamlessly queries shared KG + tenant-specific knowledge in one MCP call, with zero data leakage

**Job to Be Done**
When a clinic's AI agent needs to answer dietary/supplement questions, I want it to access our shared phytochemical knowledge graph enriched with our clinic's proprietary protocols, so I can give evidence-backed recommendations that reflect both published science and our clinical experience.

**Non-Users**
- End patients (they interact with the clinic's AI, not the KG directly)
- Researchers doing bulk data export (this is optimized for real-time agent queries)
- Clinics without an AI agent (MCP requires an agent client)

---

## Solution Detail

### Core Capabilities (MoSCoW)

| Priority | Capability | Rationale |
|----------|------------|-----------|
| Must | Tenant-scoped Neo4j queries — shared + tenant data in single query | Core isolation requirement |
| Must | `scope` property on all Neo4j nodes/edges (`shared` / `tenant:{id}`) | Enforcement mechanism |
| Must | Tenant-aware MCP tools — pass `tenant_id` in tool context | Agent must declare identity |
| Must | Tenant ingestion API — clinics can add entities/relationships | Clinics need to contribute knowledge |
| Must | Mark all existing 7,722 nodes as `scope: shared` | Bootstrap shared KG |
| Should | Query planner — route to LightRAG mode based on intent | Better retrieval quality |
| Should | Custom entity types for tenant data (Protocol, Intervention, Outcome, Biomarker) | Clinics add clinical practice knowledge with measurable feedback loops |
| Should | Audit log — who queried/ingested what, when | Compliance, debugging |
| Could | Knowledge sharing opt-in — tenant marks relationships as "community" | Future marketplace |
| Could | Metering — track query volume per tenant | Future billing |
| Won't | Per-user permissions within a tenant — deferred | Adds complexity beyond demo |
| Won't | Cross-tenant knowledge marketplace — deferred | Needs legal/business framework |

### MVP Scope

1. `scope` property on all Neo4j nodes/edges
2. Tenant-aware `semantic-search` MCP tool with query filtering
3. Tenant ingestion endpoint (add entities/relationships scoped to tenant)
4. Demo with 2 simulated clinics: Clinic A adds IV intervention protocols for inflammation, Clinic B adds herbal intervention protocols for stress — each sees shared + own data only, with biomarker-tracked outcomes

### Entity-Relationship Schema Extension

```
EXISTING (mark scope: shared):
  :Herb, :Compound, :Food, :Target, :Disease, :Symptom, :Nutrient
  CONTAINS_COMPOUND, FOUND_IN_FOOD, TARGETS_PROTEIN, ASSOCIATED_WITH_DISEASE, TREATS_SYMPTOM

NEW (tenant entity types — clinical practice layer):
  :Protocol      — clinic treatment plans with ordered phases (screening/treatment/validation)
  :Intervention  — therapeutic action: compound + route + dosage + frequency (unifies IV/oral/topical)
  :Outcome       — structured clinical observation with measurable direction + magnitude
  :Biomarker     — measurable physiological indicator (hsCRP, HbA1c, cortisol) linking outcomes to targets

NEW (tenant relationship types):
  INCLUDES           — Protocol → Intervention (ordered steps within a protocol)
  USES               — Intervention → {Compound, Herb, Food} (what bioactive is administered)
  RESULTED_IN        — Intervention → Outcome (clinical result of an intervention)
  MEASURED_BY        — Outcome → Biomarker (what was measured to determine the outcome)
  INDICATES          — Biomarker → {Disease, Symptom} (what condition this biomarker tracks)
  CONTRAINDICATES    — {Compound, Intervention} → {Disease, Symptom} (safety constraints)
  SYNERGIZES_WITH    — {Compound, Intervention} → {Compound, Intervention} (combination effects)

OPTIMIZATION TRAVERSAL (key AI query path):
  Protocol → INCLUDES → Intervention → USES → Compound → TARGETS_PROTEIN → Target
                             │                                                │
                             └── RESULTED_IN → Outcome → MEASURED_BY → Biomarker
                                                                         │
                                                              INDICATES → Disease

SCOPING RULES:
  - Every node has: scope = "shared" | "tenant:{tenant_id}"
  - Every edge has: scope = "shared" | "tenant:{tenant_id}"
  - Shared nodes can be endpoints of tenant-scoped edges
  - Tenant queries: MATCH ... WHERE (n.scope = 'shared' OR n.scope = $tenant_scope)
  - Shared queries: MATCH ... WHERE n.scope = 'shared'
```

### Query Gateway Architecture

```
┌──────────────────────────────────────────────────────────┐
│  LLM Agent (ShrineAgent, external client)                │
│     │                                                    │
│     ├─► MCP Tool Call (with tenant_id in context)        │
│     │                                                    │
│  ┌──▼──────────────────────────────────────────────────┐ │
│  │  Query Gateway (tenant-aware middleware)             │ │
│  │                                                     │ │
│  │  1. Extract tenant_id from MCP request context      │ │
│  │  2. Validate tenant_id against allowed tenants      │ │
│  │  3. Determine query intent (lookup vs discovery)    │ │
│  │  4. Route to appropriate handler:                   │ │
│  │                                                     │ │
│  │     ┌─────────────┐     ┌──────────────────────┐   │ │
│  │     │ SQLite       │     │ LightRAG API         │   │ │
│  │     │ (structured) │     │ (semantic search)    │   │ │
│  │     │              │     │                      │   │ │
│  │     │ Fast lookups │     │ + scope filter:      │   │ │
│  │     │ No scoping   │     │   shared OR tenant:X │   │ │
│  │     │ (shared only)│     │                      │   │ │
│  │     └──────────────┘     └──────────────────────┘   │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  Neo4j (single database, workspace: unified_diet_kg)     │
│  ┌──────────────────────────────────────────────────┐    │
│  │  scope: shared    │  scope: tenant:clinic_a      │    │
│  │  ─────────────    │  ────────────────────        │    │
│  │  7,722 nodes      │  Protocol, Injectable nodes  │    │
│  │  795 edges        │  Custom relationships        │    │
│  │  (dietary KG)     │  (visible only to clinic_a)  │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## Technical Approach

**Feasibility**: HIGH — Neo4j property filtering is native, LightRAG workspace supports scoping, MCP context can carry tenant_id.

**Architecture Notes**
- Single Neo4j database with `scope` property on every node/edge — avoids per-tenant infrastructure
- LightRAG queries augmented with Cypher `WHERE` clause: `(n.scope = 'shared' OR n.scope = $tenant_scope)`
- Tenant ingestion uses existing `ainsert_custom_kg()` with `scope` in entity/edge metadata
- Syntropy-Journals integration via MCP: ShrineAgent passes `org_id` from Clerk auth as `tenant_id` in MCP tool context

**Technical Risks**

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| LightRAG doesn't support per-query scope filtering natively | Medium | Implement as Cypher post-filter or custom LightRAG storage override |
| Query performance degrades with scope checks on large graph | Low | Neo4j composite index on (scope, entity_type) |
| Tenant data accidentally ingested without scope tag | Medium | Ingestion validation — reject entities without explicit scope |
| MCP context doesn't carry tenant_id | Low | MCP protocol supports `meta` field; fallback to API key → tenant mapping |

---

## Implementation Phases

| # | Phase | Description | Status | Parallel | Depends | PRP Plan |
|---|-------|-------------|--------|----------|---------|----------|
| 1 | Scope Bootstrap + Server-Side Enforcement + Clerk Mapping | Tag existing 7,722 nodes/795 edges with `scope: shared`; make LightRAG `/query` actually honor `scope_filter` via `ScopedNeo4JStorage` + thin FastAPI wrapper; publish canonical Clerk `org_id → tenant_id` slug rule + reference utility | in-progress | - | - | [plan](../../plans/multi-tenant-enforcement-bootstrap.plan.md) |
| 2 | Schema Extension | Add tenant entity types (Protocol, Intervention, Outcome, Biomarker) and relationship types to entity_schema.py | complete | with 1 | - | [plan](../../plans/completed/multi-tenant-schema-extension.plan.md) |
| 3 | Query Gateway (client-side) | Tenant-aware middleware for MCP tools — extract tenant_id, inject scope filter in POST body | complete (server-side enforcement tracked under Phase 1 plan) | - | 1 | [plan](../../plans/completed/multi-tenant-query-gateway.plan.md) |
| 4 | Tenant Ingestion | API/script for clinics to add tenant-scoped entities and relationships | pending | with 3 | 2 | - |
| 5 | Demo Scenarios | Create 2 simulated clinics with sample protocols, run benchmark queries | pending | - | 3, 4 | - |
| 6 | Syntropy-Journals Integration | Wire ShrineAgent to pass org_id as tenant_id in MCP calls | pending | - | 5 | - |

### Phase Details

**Phase 1: Scope Bootstrap**
- **Goal**: Tag all existing KG data as `shared` so tenant scoping can be enforced
- **Scope**: Run Cypher `MATCH (n) SET n.scope = 'shared'` + `MATCH ()-[r]->() SET r.scope = 'shared'`; add `scope` to entity_schema.py; update ingest_unified.py to set scope on all new entities
- **Success signal**: `MATCH (n) WHERE n.scope IS NULL RETURN COUNT(n)` returns 0

**Phase 2: Schema Extension**
- **Goal**: Define tenant-specific entity and relationship types for clinical practice layer
- **Scope**: Add Protocol, Intervention, Outcome, Biomarker to entity_schema.py with description generators; add INCLUDES, USES, RESULTED_IN, MEASURED_BY, INDICATES, CONTRAINDICATES, SYNERGIZES_WITH relationship types; add `scope` metadata to ingestion pipeline
- **Success signal**: `make lightrag-dry-run` shows new entity types; schema validates; all tests pass

**Phase 3: Query Gateway**
- **Goal**: MCP tools enforce tenant isolation at query time
- **Scope**: Middleware that extracts `tenant_id` from MCP request context, rewrites LightRAG queries to include scope filter, validates tenant access
- **Success signal**: Tenant A cannot see Tenant B's entities in any MCP tool response

**Phase 4: Tenant Ingestion**
- **Goal**: Clinics can add their own entities and relationships via API
- **Scope**: New MCP tool `ingest-tenant-data` that accepts entities/relationships and tags with `scope: tenant:{id}`; validation that shared entities are never overwritten
- **Success signal**: Clinic A adds 10 Protocol entities, only Clinic A can query them

**Phase 5: Demo Scenarios**
- **Goal**: End-to-end demo with realistic clinic data
- **Scope**: Clinic A (injectable protocols for inflammation), Clinic B (herbal protocols for stress); benchmark 10 cross-tenant queries showing isolation
- **Success signal**: Demo walkthrough completes without data leakage

**Phase 6: Syntropy-Journals Integration**
- **Goal**: ShrineAgent uses the diet KG MCP with tenant context
- **Scope**: Add `mcp-herbal-botanicals` to Syntropy-Journals `.mcp.json`; pass Clerk `org_id` as `tenant_id` in MCP tool calls
- **Success signal**: ShrineAgent dietary queries hit the KG with correct tenant scoping

### Parallelism Notes

Phase 1 (scope bootstrap) and Phase 2 (schema extension) can run in parallel — Phase 1 modifies existing Neo4j data while Phase 2 extends the Python entity schema. Phases 3 and 4 can run in parallel after Phase 2 — the query gateway and ingestion API are independent code paths that both depend on the scope field existing.

---

## Decisions Log

| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Tenant isolation | Property-based scoping (`scope` field) | Separate Neo4j databases per tenant; Separate LightRAG workspaces | Single DB is simpler, cheaper, enables shared→tenant edge references |
| Scope model | `shared` / `tenant:{id}` string | Separate boolean `is_shared` + `tenant_id` fields | Single field is simpler to filter, less state to maintain |
| Tenant identity | MCP request context → `tenant_id` | API key → tenant mapping; JWT claims | MCP protocol supports meta fields; aligns with Clerk org_id |
| New entity types | Extend existing schema | Separate schema per tenant | Shared schema enables cross-type relationships (Protocol → Compound) |

---

## Research Summary

**Market Context**
- Multi-tenant knowledge graphs are common in enterprise RAG (Azure AI Search, Pinecone namespaces, Weaviate tenants)
- Neo4j supports property-based access control natively; no need for separate databases
- LightRAG's workspace parameter provides coarse-grained isolation but not per-query scoping

**Technical Context**
- Syntropy-Journals has Clerk auth (org_id available), partner portal, LangGraph agents — integration path exists
- Current MCP server is pure proxy with no middleware layer — query gateway needs to be built
- LightRAG's `ainsert_custom_kg()` accepts arbitrary properties on entities — `scope` can be added without framework changes
- Neo4j composite index on `(scope, entity_type)` would maintain query performance at scale

---

*Generated: 2026-04-13*
*Status: DRAFT - needs validation*
