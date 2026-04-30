# MCP Gateway Over LightRAG KG — Design

_Authored 2026-04-29. Companion to Task #12. Tracks the MCP server that the publication's clinical agent will call._

## 1. What scoped_server already provides

`shrine-diet-bioactivity/lightrag/scoped_server.py` is a FastAPI app exposing 5 endpoints:

| Endpoint | Purpose | Backed by |
|---|---|---|
| `GET /health` | Config + status | static |
| `POST /query` | LightRAG `aquery` — natural-language Q&A in 5 modes (local/global/hybrid/naive/mix) | LightRAG → vector + graph |
| `GET /graphs?label=` | Expand subgraph from a labeled node, depth- and node-bounded | `rag.get_knowledge_graph` |
| `GET /graph/label/popular` | Top-N entity labels in the workspace | popular-labels chunk |
| `POST /documents/custom_kg` | Tenant-scoped writes | `rag.ainsert_custom_kg` |

Every endpoint enforces the `scope_filter` contract (D3): defaults to `["shared"]` for `/query`; required for the read-`/graphs`/popular-labels and write-`/custom_kg` paths.

## 2. Sufficiency for general KG query

`POST /query` covers general natural-language KG question-answering — the LightRAG `mix`/`hybrid` modes do (vector retrieval) → (graph expansion) → (LLM synthesis) end-to-end. For an LLM agent that wants to ask "does ginger help with chemotherapy nausea?", this is enough.

**It is not enough** for the publication's panel agents (Dietitian, Pharmacologist, TCM, Safety, etc.) because:

1. **No traversal-pattern guarantees.** LightRAG's keyword extractor decides which entities to seed from. The agent cannot enforce "start from a Food node and traverse FOUND_IN_FOOD/CONTAINS_COMPOUND first" — exactly the deterministic information-seeking strategy each clinical role would use IRL.

2. **No edge-type guarantees.** A query about "compound→symptom" pathways may or may not retrieve the actual `TREATS_SYMPTOM` edges depending on the LLM's keyword choice and the vector index's seed coverage. For C1 (HDI Recall) and C3 (provenance faithfulness) — both metrics that *measure* the right traversal happened — non-determinism in retrieval becomes non-determinism in metric.

3. **No drug-herb interaction (HDI) lookup primitive.** The HDI-Safe-50 panel is a curated 50-edge resource the Safety agent should consult by lookup, not by NL similarity. A direct primitive `kg_hdi_check(drug, herb)` is more accurate and cheaper than an `aquery("does drug X interact with herb Y?")`.

4. **No bilingual canonicalization primitive.** SymMap's bilingual symptom mappings are a structured cross-walk; the TCM agent benefits from `kg_bilingual_term("黄连")` returning the canonical English/Pinyin/CN triple directly rather than guessing from `aquery`.

**Conclusion:** keep `POST /query` as the general-purpose tool, and add **prior-injecting tools** that enforce the role's natural information path. The set is small and stable — one tool per role's primary traversal motif.

## 3. MCP toolkit design

The MCP gateway is a thin shim over scoped_server. New tools either:

- **(W)** Wrap an existing endpoint (`/query` or `/graphs`) with role-specific defaults and a stricter input/output schema.
- **(C)** Wrap a new Cypher-typed endpoint that scoped_server gains (a single `POST /traverse` accepting structured pattern + filters).

The toolkit has 10 tools across 3 layers:

### Layer A — General Q&A (1 tool, type W)

| MCP tool | Backs onto | What it does | Used by |
|---|---|---|---|
| `kg_query` | `POST /query` | Natural-language question → free-form answer with cited sources. Mode default `mix`. | Any agent for open-ended questions. **Default fallback.** |

### Layer B — Role-priored entrypoints (6 tools, type C)

Each tool **enforces the starting node type** so the LLM cannot guess. Output is a typed `KGResult` (chains + raw subgraph counts). Implementation: scoped_server gains a `POST /traverse` that takes `{start_label, start_id_or_name, edge_type, direction, depth, top_k, scope_filter}` and runs typed Cypher under the hood; the MCP tools call it with hard-coded `start_label` + `edge_type`.

| MCP tool | Start node | Edge | Direction | Depth | Used by | Claim it serves |
|---|---|---|---|---|---|---|
| `kg_diet_to_compounds` | `Food` | `CONTAINS_COMPOUND`, `FOUND_IN_FOOD` | inbound + outbound | ≤2 | Dietitian | C1 nutrition pathways |
| `kg_compound_to_targets` | `Compound` | `TARGETS_PROTEIN` | outbound | 1 | Pharmacologist | C1 pharmacokinetics |
| `kg_compound_to_diseases` | `Compound` | `TARGETS_PROTEIN` → `ASSOCIATED_WITH_DISEASE` | outbound chain | 2 | Pharmacologist | C1, C3 |
| `kg_herb_to_diseases` | `Herb` | `ASSOCIATED_WITH_DISEASE` | outbound | 1 | TCM, Pharmacologist | C3 provenance |
| `kg_herb_to_symptoms` | `Herb` | `TREATS_SYMPTOM` | outbound | 1 | TCM, Dietitian | C4 |
| `kg_compound_to_symptoms` | `Compound` | `CONTAINS_COMPOUND`-back-edge then `TREATS_SYMPTOM` | composite | 2 | Dietitian | C1 mechanism→symptom |

Each tool takes a single semantic input (e.g., a compound or food name OR a free-text query that gets vector-resolved to a starting node first). Output is a structured `ProvenanceChain[]` so the agent can cite paths in its synthesis — a paper-grade artifact.

### Layer C — Lookup primitives (3 tools, type W or direct Cypher)

These bypass natural-language entirely; deterministic by ID.

| MCP tool | Backs onto | What it does | Used by |
|---|---|---|---|
| `kg_hdi_check` | direct Cypher (new endpoint) | `(drug, herb) → {severity, mechanism_class, evidence_tier}` from HDI-Safe-50 panel. Returns `null` if unknown. | Safety Reviewer |
| `kg_bilingual_term` | direct Cypher | `term (any of EN/CN/Pinyin) → {english, chinese, pinyin, source}` from SymMap. | TCM, bilingual queries |
| `kg_node_neighborhood` | wraps `GET /graphs` | One node, expand bounded subgraph. The shim sets `max_depth=2, max_nodes=200`. Used for general graph exploration when other tools missed. | Any agent |

Total: **10 MCP tools.** Small, well-scoped, role-aligned.

## 4. Why this shape — design tensions resolved

**Tension 1: more tools vs. fewer.** A single `kg_query` is fewer-cognitive-load for the LLM but loses pathway determinism. A separate tool per Cypher pattern is determinist but explodes (`Compound→Target→Disease→Drug→Side effect → ...`). Resolution: **role-priored tools (Layer B) cover the 6 traversal motifs that match the 6 panel roles**, with `kg_node_neighborhood` as the safety net for everything else. 10 tools is a manageable budget for the agent's context window.

**Tension 2: parameter schema strictness vs. flexibility.** Strict schemas (Pydantic models) catch agent hallucinations early; loose schemas let the agent improvise. Resolution: **strict on Layer B+C** (each tool takes 1–2 typed inputs, returns a structured result), **loose on Layer A** (`kg_query` accepts a free string). The Layer-B/C tools are where the panel's deterministic behavior lives; `kg_query` is where exploration lives.

**Tension 3: where Cypher lives.** Two options:
  - In the MCP server (Cypher gets sent over HTTP to a generic /cypher endpoint)
  - In scoped_server (typed `/traverse` and `/hdi_check` and `/bilingual_term` endpoints)
  
  Resolution: **scoped_server.** Reasons: (a) the scope filter and audit log already live there — putting Cypher in MCP would duplicate that contract; (b) reviewers reproducing the paper see one HTTP server with named endpoints, not raw Cypher passed through; (c) future LLM-injection safety: the agent never gets to write Cypher.

**Tension 4: option (a) port vs. option (b) shim.** The user chose (b) — fewer Aha-moments needed; lets us ship the gateway in hours not days. The shim still gets the prior-enforcing tools because we add the small `/traverse` and `/hdi_check` endpoints to scoped_server (~50 lines of Cypher each), then the MCP shim wraps them. The MCP layer itself stays a few hundred lines.

## 5. Tool input/output schemas (sketches)

```python
# Layer A
class KgQueryInput(BaseModel):
    question: str
    mode: Literal["mix", "hybrid", "local", "global", "naive"] = "mix"
    top_k: int = Field(40, ge=1, le=200)

class KgQueryOutput(BaseModel):
    answer: str
    references: list[str]   # entity_ids the answer cites


# Layer B (one shape, parameterized at registration)
class TraversalInput(BaseModel):
    seed: str               # entity_id OR free-text resolved-to-entity
    top_k: int = Field(20, ge=1, le=200)

class TraversalOutput(BaseModel):
    chains: list[dict]      # serialized ProvenanceChain
    seeds_resolved: list[str]
    raw_subgraph_node_count: int
    raw_subgraph_edge_count: int


# Layer C
class HDICheckInput(BaseModel):
    drug: str
    herb: str

class HDICheckOutput(BaseModel):
    found: bool
    severity: Literal["mild", "moderate", "severe"] | None
    mechanism_class: Literal["CYP450", "P-gp", "PD-antagonism", "coagulation", "serotonergic"] | None
    evidence_tier: str | None
    citations: list[str]    # source_ids


class BilingualTermInput(BaseModel):
    term: str
    languages: list[Literal["en", "cn", "pinyin"]] = ["en", "cn", "pinyin"]

class BilingualTermOutput(BaseModel):
    english: str | None
    chinese: str | None
    pinyin: str | None
    source: str
    confidence: float
```

## 6. Ordering — what to build in what order

Each step is one PR.

1. **scoped_server gains `POST /traverse`** — typed Cypher dispatcher with switch on `(start_label, edge_type, direction)`. Tests cover each Layer-B motif. Idempotent reads, scope-filtered.
2. **scoped_server gains `POST /hdi_check`** — direct Cypher against `HDI-Safe-50` mechanism panel.
3. **scoped_server gains `POST /bilingual_term`** — direct Cypher against SymMap bilingual tables.
4. **MCP server `mcp/`** — Python module that imports `mcp` SDK, registers the 10 tools, each tool is a thin async function calling scoped_server with the role-correct payload. Tests with a mocked `httpx.AsyncClient`.
5. **End-to-end smoke** — start scoped_server, start the MCP server in stdio mode, agent calls `kg_compound_to_targets("Curcumin")`, expect non-empty `chains`.
6. **Wire diet_os panel** — replace `kg_query.py` (today's LightRAG-direct call) with the MCP tool set. Each panel role gets the tools that match its prior.

Steps 1–3 are scoped_server; steps 4–6 are MCP and panel.

## 7. What the MCP server is NOT

- **Not a writer** to the publication-scope graph. Writes go through the existing `/documents/custom_kg` endpoint (tenant-scoped only). The MCP shim does not expose write tools.
- **Not authenticated** beyond the scoped_server's existing scope filter. Authentication wrapper (per-agent identity, audit attribution) is a separate layer if/when the MCP server is exposed beyond the publication agent.
- **Not a replacement for `kg_query`.** Layer A's general tool stays — agents that don't know the right traversal use it. Layer B/C are *opinionated* tools, not the only tools.

## 8. Trade-off considerations (design-only; not implementation scope)

These four axes shape the design but are explicitly **out of scope for the
implementation milestone**. They are review hooks the design must support
without dictating the first cut.

### 8.1 Latency + LLM sampling cost

Each tool call has a wall-clock cost the agent pays per scenario. The current shape:

| Tool | Per-call dominant cost | Mitigation built into the design |
|---|---|---|
| Layer A (`kg_query`) | LLM keyword extraction (LightRAG) + vector retrieval + graph expansion + LLM synthesis. ~5–15 s end-to-end. | Mode `mix` is the default; `local` / `naive` are faster fallbacks the agent can pick. |
| Layer B (typed traversals) | One Cypher round-trip if seed is an `entity_id`; one extra vector lookup if seed is free text. ~50–500 ms. | Seed input accepts `entity_id` directly — agent that knows the canonical name skips the LLM-bounded resolve step. |
| Layer C (lookup primitives) | One indexed Cypher round-trip. ~20–80 ms. | Direct ID match, no LLM, no embedding. |

**LLM sampling implication.** A panel scenario today fires ~7 LLM calls (triage + 6 roles + moderator). The MCP layer must NOT add another LLM call per tool invocation; vector resolution for free-text seeds in Layer B is the only LLM-adjacent path, and it uses the embedder (separate quota from chat) — verified during the migration.

**Continuous lever.** When v1/v2 results come in, look at the histogram of `(tool, latency)` per scenario. If `kg_query` dominates wall-clock, the design supports moving more queries to Layer B by tuning panel-role prompts to prefer the named tool over the general one. No code change needed.

### 8.2 Semantic accuracy

Layer-A tools have **broad recall, lower precision**: the LightRAG keyword extractor casts a wide net and the LLM synthesizes from many chunks. Layer-B tools have **narrow precision, lower recall**: the Cypher traversal is exact but only along the encoded edge type.

Trade-off: an agent calling `kg_compound_to_targets("aspirin")` gets exactly the TARGETS_PROTEIN edges out of "aspirin" — high precision. If the answer requires a longer chain (Compound → Target → Disease → Drug), the agent must call `kg_compound_to_diseases` instead. The tool naming carries this contract; agent prompts must teach the right tool for the right traversal.

**Failure mode the design protects against.** An LLM agent that doesn't know the right traversal will reach for `kg_query` (Layer A) — fine. The danger is an agent that calls Layer B with the wrong start label (e.g., asking for compound→target on a herb name). Mitigation: tool names encode start type, and the input docstring includes a one-line example. If the wrong type is passed, the typed Cypher returns empty and the agent falls back to `kg_query`. Empty-on-mismatch beats hallucinated-on-mismatch.

**Continuous lever.** Add a "pre-resolution probe": before running the typed traversal, the gateway verifies the seed resolves to a node with the expected label. If not, return a structured "seed type mismatch — try kg_query or kg_node_neighborhood" error so the agent self-corrects. Out of scope for v1 of the gateway; design accommodates it.

### 8.3 Generalizability

Today's 6 named Layer-B tools cover the entity types in the current KG (Herb, Compound, Target, Food, Disease, Symptom). New entity types (Gene, Protein, Drug as first-class, Pathway, ...) would need new tools.

Two tensions and how the design resolves each:

1. **Explicit named tools vs. one parameterized generic tool.** A single `kg_typed_traversal(start_label, edge_types, ...)` is one tool definition but pushes label/edge validation to the agent — which can hallucinate combinations. The current design picks **explicit named tools for the 6 known role motifs** + **a generic `kg_node_neighborhood`** as the safety net. Future entity types get new named tools; bounded growth.

2. **What about new edge types?** When ingestion adds edges (e.g., `MODULATES_PATHWAY`), no existing Layer-B tool covers them. Choices: (a) extend `kg_compound_to_diseases` semantics to include the new edge — risks breaking the contract; (b) add `kg_compound_to_pathways` — clean but adds tool-budget pressure. Default to (b). The naming convention is generative: `kg_<source>_to_<destination>` makes new tools self-documenting.

**Anti-pattern to avoid.** Creating a tool per (start_label, edge_type, direction, depth) tuple. That's combinatorial explosion. The criterion for adding a Layer-B tool: **a panel role would call this traversal as a primary information-seeking move**. If no role would, it doesn't get a named tool.

**Continuous lever.** Tool-call telemetry over time shows which traversals the panel actually uses. After v1/v2 eval results, retire underused tools and promote frequently-used `kg_node_neighborhood` patterns into named tools.

### 8.4 Continuous optimization strategy

The MCP gateway is a contract surface that lives long. Three dimensions of continuous improvement, each with a hook in the current design:

| Dimension | Signal we collect | Hook in current design |
|---|---|---|
| **Tool-selection quality** | Per-scenario distribution of tool calls; rate at which the agent's final synthesis cites results from the tool's output | scoped_server already audits each call (`audit/mcp_audit.db`); MCP layer adds one more row per tool invocation. Enable later by uncommenting the audit hook in `client.py`. |
| **Tool-output usefulness** | "Empty subgraph" rate per tool per scenario category; chains-cited vs. chains-returned | Layer B output schema includes `raw_subgraph_node_count`; runner can attribute "empty" outcomes to tool choice and tune prompts. |
| **Tool defaults (top_k, depth)** | Eval metric uplift when defaults change | Layer-B tools register defaults centrally (factory in `server.py`); changing one constant changes all tools. No per-scenario configuration leaks into agent prompts. |

**A/B regimen.** Once v1 baseline lands with this gateway, do a focused A/B: replace `kg_query` calls in the dietitian agent with `kg_diet_to_compounds` + `kg_compound_to_symptoms` for nutrition scenarios. Measure C1 (HDI Recall) and C3 (provenance) deltas. Promote the winner to default panel prompt. Repeat per role. This is paper-grade ablation work that uses the gateway exactly as built.

**What this implies for code today.** Two small affordances we keep in the design but don't implement now:
- An optional `audit_tag` field on every tool input (free string the agent can pass for telemetry correlation, e.g. scenario id)
- A debug-mode `?explain=true` query parameter on `/traverse` that returns the full Cypher executed — useful when investigating why a traversal returned empty

Neither is in the v1 implementation. Both have clear reservation in the schema (`Field(default=None, exclude_unset=True)` for `audit_tag`; query-string passthrough on the typed-traverse endpoint).

---

## 9. Open questions

1. **Tool naming convention.** `kg_compound_to_targets` reads well in agent prompts but is verbose. Alternatives: `query_compound_targets` (shorter), `compound→targets` (Unicode arrow, possibly fragile across MCP clients). Default to the verbose form for clarity unless the agent context budget pushes back.

2. **Default `top_k` per tool.** Higher `top_k` → more context for the panel; lower → faster + tighter context. Layer B defaults to 20 as a starting point; may tune per role from v1 eval re-run results.

3. **Streaming responses.** MCP supports streaming for long-running tools. `kg_query` in mix mode can take 5–10 seconds; streaming would let the panel start digesting partial answer. Defer until after non-streaming MVP works.
