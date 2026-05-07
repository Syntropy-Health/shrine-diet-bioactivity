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

**Baselines.** Five external baselines plus `diet_os` and a within-system
ablation share LLM, KG, and gateway: `single_llm` (no tools),
`single_llm_rag` (naïve RAG), `yang2025` (two-agent barrier-identification + strategy-execution; JMIR Yang behavioral baseline) [@yang2025], `medagents` (n-role debate, no KG) [@medagents2024],
`mdagents` (adaptive routing, no KG) [@mdagents2024], **`diet_os`** (this
work, deterministic gold-triage substitute — see §5.4 for the bypass
disclosure), and **`diet_os_llm_triage`** (identical to `diet_os` but
replacing the deterministic triage with a free-tier LLM call; introduced
to address peer-review concern C1 about gold-triage bypass, full discussion
in §6.5). We report the full N = 40 matrix across all seven systems.

**Cost and latency.** Per-role token usage and latency are captured by
the `cost_tracker` decorator wrapping `ConversableAgent.generate_reply`.
Free-tier rate limits dominate end-to-end matrix wall-clock (full-40
× 6 baselines completed in ~3 hours; the `diet_os_llm_triage` ablation
adds ~2 hours due to free-tier RPM throttling on the additional triage
LLM call). Detailed per-role traces are available in the companion code
release; we omit the table here for space.
