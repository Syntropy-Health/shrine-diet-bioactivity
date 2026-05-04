## 1. Introduction

Clinical research teams operate as multi-agent systems by design — a
registered dietitian, a clinical pharmacist, a TCM practitioner, a clinical
research scientist, a safety reviewer, and a deferral authority each bring
different priors, evidence sources, and decision criteria. Yet recent
multi-agent LLM systems (MedAgents [@medagents2024], MDAgents
[@mdagents2024], Yang et al. [@yang2025]) operate without grounded retrieval
over domain knowledge — agents debate from training-data priors. For diet,
herb, and TCM clinical questions where evidence is encoded in 5M+
relationships across heterogeneous sources (Duke, FooDB, CMAUP, SymMap v2.0,
HERB 2.0, HDI-Safe-50), retrieval is the architectural lift debate alone
cannot supply.

We present `diet_os`, a 6-role multi-agent system that reasons over a
pre-fetched typed-traversal retrieval bundle from a unified diet/herb/TCM
knowledge graph queried via streamable-HTTP MCP. We deliberately adopt a
constrained-inference setup (free-tier OpenRouter Nemotron-3-nano-30B) to
demonstrate that architectural choices, not LLM scale, produce paper-grade
signal.

Three contributions:

1. **System.** `diet_os`: 6 role agents (Dietitian, Pharmacologist, TCM
   Practitioner, Clinical Research Scientist, Safety Reviewer,
   Defer-to-Clinician) registered with role-priored Layer-B/C MCP tools over
   a unified KG. Pre-fetched retrieval substitutes for LLM-driven tool calls
   under constrained-inference free-tier 30B Nemotron.

2. **Architectural ablation.** Bonferroni-significant verdict-κ uplift
   (mean_diff +0.476 to +0.575, p_adj < 0.001) and structural HDI Recall
   separation (diet_os = 0.709, all 5 baselines = 0.000) over MedAgents
   [@medagents2024], MDAgents [@mdagents2024], and Yang et al. [@yang2025]
   on DietResearchBench-Clinical (n = 40).

3. **Benchmark.** DietResearchBench-Clinical v1: 40 scenarios across herbal
   single-symptom, nutrition single-nutrient, multi-drug herb-drug
   interaction, and TCM bilingual; 6-metric evaluation panel. Companion v2
   paper expands to n = 200 with two-annotator IAA [@v2benchmark2026].
