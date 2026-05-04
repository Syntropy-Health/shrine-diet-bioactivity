## 3. System: diet_os

`diet_os` is a six-role multi-agent pipeline implemented in AG2 [@ag2v0_12]
over a 5M-edge unified diet/herb/TCM knowledge graph served by a
streamable-HTTP MCP gateway. Figure 1 shows the end-to-end flow.

![Figure 1. diet_os pipeline: triage extracts a PICO-typed `ResearchQuestion`; `retrieve_for_question` dispatches deterministic Layer-B/C MCP traversals into a `KGRetrievalBundle`; six role agents deliberate over the bundle in a round-robin GroupChat; the moderator summarizes, the calibrator scores composite confidence, and synthesis emits a `ResearchSynthesis` artifact.](figures/architecture-diagram.png)

### 3.1 Triage and pre-fetched retrieval

Triage converts the user's free-text question into a typed `ResearchQuestion`
(PICO-shaped: population, intervention, comparator, outcome, language hints)
plus a `Triage` record carrying complexity, suspected red flags, and language
tags. We extract the first balanced `{...}` slice to absorb free-tier
Nemotron-30B's JSON-quality variance.

`retrieve_for_question(rq, triage)` then dispatches deterministic Layer-B/C
MCP calls *before* any panel agent runs. A herb intervention triggers
`kg_herb_to_diseases` and `kg_herb_to_symptoms`; a compound intervention
triggers `kg_compound_to_targets`; any (drug, herb) co-occurrence triggers
`kg_hdi_check`; CJK characters or `zh` language hints trigger
`kg_bilingual_term`. Results fuse into a `KGRetrievalBundle` of
`ProvenanceChain[]` with edge-level `source_id` attribution
(`cmaup:plant_disease`, `duke:found_in_food`, `hdi-safe-50:mechanism`, etc.).

This **pre-fetched** design is a deliberate departure from LLM-driven tool
calls. Our pilot found Nemotron-30B emits `RoleVerdict` JSON whose `notes`
field claims tool use ("Used `kg_diet_to_compounds`…") while transcript-level
tool-invocation counts remain zero across all roles — the model hallucinates
tool use from training-data priors (`e2-panel-mcp-wiring-results.md`).
Pre-fetching guarantees every panel deliberation receives a non-empty bundle,
so HDI-Recall and provenance metrics (§4) become measurable rather than null.

### 3.2 Role-priored panel

The panel is an AG2 `GroupChat` round-robin with `max_round = len(roles)` —
one verdict per role, no rebuttal. Each role registers a *subset* of the
10-tool MCP toolkit reflecting its real-world information prior
(`staged-mcp-persona-audit.md`):

| Role | Priored MCP tools |
|---|---|
| Dietitian | `kg_diet_to_compounds`, `kg_compound_to_symptoms` |
| Pharmacologist | `kg_compound_to_targets` |
| TCM Practitioner | `kg_bilingual_term`, `kg_herb_to_diseases`, `kg_herb_to_symptoms` |
| Clinical Research Scientist | `kg_query` (Layer-A NL fallback) |
| Safety Reviewer | `kg_hdi_check` |
| Defer-to-Clinician | `kg_query` |

Tools remain available as fallbacks when the LLM does emit valid `tool_calls`,
but the bundle dominates the evidence pathway. Each role emits a `RoleVerdict`
∈ {prefer, caution, reject, abstain} with `support[]`, `concerns[]`, and
`cited_chains[]` indices into the bundle. Single-pass round-robin (rather
than multi-round rebuttal) is forced by the 20-RPM rate limit and is
defensible because pre-fetching removes the information asymmetry rebuttal
would normally resolve (§7.2).

### 3.3 Moderator, calibrator, synthesis

The moderator concatenates the six `RoleVerdict`s into a textual summary plus
dissent list. The calibrator computes composite confidence as a weighted
product of evidence-tier strength, HDI risk, and question-fit, each in [0, 1].
The terminal artifact is a `ResearchSynthesis` Pydantic model with `verdict`,
`support`, `concerns`, `cited_chains`, `confidence`, `components`, and a
`defer_to_clinician` boolean derived from the Safety Reviewer's verdict and
the Defer-to-Clinician role's vote. This single object is scored by all six
benchmark metrics.
