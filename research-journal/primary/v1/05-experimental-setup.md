## 5. Experimental setup

**LLM.** All systems share free-tier OpenRouter Nemotron-3-nano-30B (chat,
20 RPM). Holding the LLM constant isolates the architectural ablation and
frames the results as constrained-inference findings.

**Orchestration.** AG2 v0.12.1 (the AG2AI Apache-2.0 fork; we avoid AutoGen
v0.4 maintenance-mode), with `GroupChat` round-robin and Pydantic-typed
messages.

**Knowledge graph.** Neo4j AuraDB Professional 8 GB hosting `unified_diet_kg`
(166K nodes, ~5M relationships) ingested from Duke phytochemical, FooDB,
CMAUP, SymMap v2.0, HERB 2.0, HDI-Safe-50, and OpenNutrition.

**MCP gateway.** Streamable-HTTP at `kg-mcp-test.up.railway.app/mcp`
exposing 10 tools across 3 layers: Layer A (`kg_query` NL Q&A), Layer B (6
typed traversals), Layer C (3 lookup primitives — `kg_hdi_check`,
`kg_bilingual_term`, `kg_node_neighborhood`). The session is
singleton-per-process across the eval matrix.

**Baselines.** Six systems share LLM, KG, and gateway: `single_llm` (no
tools), `single_llm_rag` (naïve RAG), `yang2025` (2-role
dietitian-pharmacist) [@yang2025], `medagents` (n-role debate, no KG)
[@medagents2024], `mdagents` (adaptive routing, no KG) [@mdagents2024], and
**`diet_os`** (this work). We report the full N = 40 matrix.

**Table 1. Per-role cost and latency for `diet_os` (mean over N = 40).**

| Role | avg_prompt (tok) | avg_completion (tok) | avg_latency (ms) |
|---|---:|---:|---:|
| Dietitian | [FILL FROM cost_latency.csv] | [FILL] | [FILL] |
| Pharmacologist | [FILL] | [FILL] | [FILL] |
| TCM Practitioner | [FILL] | [FILL] | [FILL] |
| Clinical Research Scientist | [FILL] | [FILL] | [FILL] |
| Safety Reviewer | [FILL] | [FILL] | [FILL] |
| Defer-to-Clinician | [FILL] | [FILL] | [FILL] |

Values populated from `cost_latency.csv` (E6 cost-tracker decorator on
`ConversableAgent.generate_reply`) before submission.
