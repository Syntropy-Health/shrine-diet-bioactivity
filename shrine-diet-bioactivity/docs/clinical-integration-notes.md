# Clinical Integration Notes — Adjacent Agent-Layer Patterns

> **Scope:** this document describes how to build a **clinical-reasoning
> layer** on top of `shrine-diet-bioactivity` — in the agentic harness,
> **outside** the MCP server itself. If you are looking for the MCP
> contract (connection, tenancy, tool catalog), see
> [`integration-guide.md`](./integration-guide.md).

## Why clinical logic is outside the MCP

`shrine-diet-bioactivity` is intentionally scoped as a **LightRAG-driven
semantic index + retrieval server, specialized to the diet+bioactivity
ontology but not to a clinical domain**. It exposes 7 domain-agnostic
primitives (semantic-search, get-entity, get-neighbors, list-entity-types,
get-structured-properties, filter-by-property, ingest-tenant-knowledge)
and nothing else. Clinical verbs like *"find the best protocol for a
patient with elevated hsCRP"* are **compositions** of those primitives
plus a reasoning step, and that composition belongs in the agent, where:

- the clinical workflow evolves independently of the KG schema,
- guardrails (contraindication checks, dosing bounds, drug–drug
  interaction screens) are easier to express in the agent's policy
  layer than in MCP tool bodies,
- every clinic's workflow nuances live in their agent config, not in a
  tool description shared across tenants,
- the MCP stays replaceable — swap LightRAG for another retriever and
  nothing in the clinical layer has to change.

The four verbs below are the ones we'd have implemented as MCP tools
under an earlier plan. They are re-cast as **composition patterns** the
agent layer implements locally, using the seven MCP primitives.

---

## The ontology the agent composes against

The MCP accepts and returns entities of these types (from
`lightrag/entity_schema.py`):

- **Shared scope** (`scope='shared'`): `Herb`, `Compound`, `Food`,
  `Target`, `Disease`, `Symptom`, `Nutrient`
- **Tenant scope** (`scope='tenant:<id>'`): `Protocol`, `Intervention`,
  `Outcome`, `Biomarker`

And these relationship types:

- Shared: `CONTAINS_COMPOUND`, `FOUND_IN_FOOD`, `TARGETS_PROTEIN`,
  `ASSOCIATED_WITH_DISEASE`, `TREATS_SYMPTOM`
- Tenant: `INCLUDES`, `USES`, `RESULTED_IN`, `MEASURED_BY`, `INDICATES`,
  `CONTRAINDICATES`, `SYNERGIZES_WITH`

`_meta.tenant_id` on every call scopes reads to `shared ∪ tenant:<id>`
automatically. The agent never has to filter tenants manually.

---

## Pattern 1 — `find-protocols-for-biomarker`

**Intent:** "Given a biomarker of concern (e.g. elevated hsCRP), find
the tenant's protocols that target it, plus shared-library compounds
with mechanistic support."

**Composition:**

1. `filter-by-property({ entity_type: 'Biomarker', filters: [{ property: 'name', op: 'eq', value: 'hsCRP' }] })` →
   resolve the biomarker entity_id.
2. `get-neighbors({ entity_id: <biomarker_id>, depth: 2, edge_types: ['INDICATES', 'MEASURED_BY', 'RESULTED_IN', 'INCLUDES'] })` →
   walk `Biomarker ← MEASURED_BY ← Outcome ← RESULTED_IN ← Intervention ← INCLUDES ← Protocol`. Tenant-scoped by default.
3. `semantic-search({ query: "compounds that reduce <biomarker name>", mode: 'hybrid', top_k: 30 })` →
   shared-library mechanistic support via `Compound → TARGETS_PROTEIN → Target → ASSOCIATED_WITH_DISEASE`.
4. Merge + dedupe in the agent; rank by (a) presence in tenant outcomes, (b) semantic-search score.

**Guardrails the agent adds:** contraindication check (see Pattern 3)
before surfacing a compound to the clinician.

---

## Pattern 2 — `get-intervention-outcomes`

**Intent:** "What outcomes has a specific intervention produced in this
clinic's historical data?"

**Composition:**

1. `get-entity({ entity_id: <intervention_id> })` → confirm the
   intervention exists in `tenant:<id>` scope.
2. `get-neighbors({ entity_id: <intervention_id>, edge_types: ['RESULTED_IN'] })` →
   list of `Outcome` entities.
3. For each outcome: `get-neighbors({ entity_id: <outcome_id>, edge_types: ['MEASURED_BY'] })` →
   biomarker trajectory.
4. Optional: `semantic-search({ query: 'published evidence for <intervention name>', mode: 'mix' })` →
   shared-library context for comparison.

Tenant scope guarantees the intervention's outcomes are the caller's
own. The agent formats the result as a trajectory table per biomarker.

---

## Pattern 3 — `get-contraindications`

**Intent:** "Is compound / intervention X contraindicated for a patient
with condition Y (or taking compound Z)?"

**Composition:**

1. `get-neighbors({ entity_id: <compound_or_intervention_id>, edge_types: ['CONTRAINDICATES', 'SYNERGIZES_WITH'] })` →
   direct contraindication + synergy edges (both shared and tenant).
2. `semantic-search({ query: 'contraindications and interactions of <compound>', mode: 'hybrid' })` →
   mechanistic / literature context from shared KG.
3. Agent applies its clinical policy: hard block on direct
   `CONTRAINDICATES` edges where target disease/symptom matches patient
   context; warn on `SYNERGIZES_WITH` to second-compound that the patient
   is currently taking.

The MCP has no notion of *"patient context"* — that's the agent's job.

---

## Pattern 4 — `get-clinical-context`

**Intent:** The big one — "Build a merged briefing combining the tenant's
historical outcomes with shared-library mechanism for a clinician's
free-text question."

**Composition:**

1. `semantic-search({ query: <clinician_question>, mode: 'mix', top_k: 60 })` —
   LightRAG does the hard work: hybrid KG+vector retrieval across
   shared + tenant data in one pass.
2. Inspect returned entities for any `Protocol` / `Intervention` /
   `Outcome` / `Biomarker` (tenant-scope evidence).
3. `get-neighbors` expansions on any 2–3 most-relevant entities for
   depth.
4. `filter-by-property` for any exact numeric filter the clinician
   specified (e.g. "IV-delivered", "dose > 500 mg").
5. Agent synthesises the response with explicit attribution: *"your
   clinic's data says X; shared library says Y; conflict at Z."*

Because `mix` mode combines KG traversal with vector retrieval over
entity + relationship descriptions, a single MCP call usually gives
80 % of the content; the follow-up primitive calls sharpen specific
claims.

---

## Tenancy inheritance

The agent never mints or mutates tenant IDs. Rules:

- Derive the tenant slug once at session start via
  [`slugifyClerkOrgId`](../src/clerkOrgMapping.ts) from the Clerk
  `organization.id`.
- Put that slug in `_meta.tenant_id` on **every** MCP call in the
  session.
- Never read the tenant slug from a tool response and feed it into
  another call — treat the slug as session-scoped input, not retrieved
  data.

## Observability + billing

Every MCP call is audit-logged server-side (Phase A2). The agent layer
does **not** need to double-log tool calls for billing — per-tenant
query counts, token usage, and latency come from the MCP's audit
table. The agent logs higher-level events: *"clinician Q asked
clinical-verb-Z which made N MCP calls"*, so the trace goes
clinician → agent verb → MCP primitives.

## When to push a new pattern into the MCP

Almost never. Push a new server-side primitive only when:

1. The composition is identical across every agent and consumer, AND
2. Efficient execution requires one round trip (composing in the agent
   would trigger > 10 MCP calls or dominated by network latency), AND
3. The primitive is still domain-agnostic — i.e. it describes a
   **retrieval shape**, not a clinical decision.

Otherwise, compose in the agent and let the MCP keep its small, stable
surface.
