# Abstract

Clinical research teams are multi-agent systems by design — yet recent
multi-agent LLM systems for medical reasoning operate without grounded
retrieval over domain knowledge. We present diet_os, a 6-role multi-agent
clinical research system grounded on a unified 5M-edge diet/herb/TCM
knowledge graph queried via a streamable-HTTP MCP gateway with role-priored
typed-traversal tools. We deliberately adopt a constrained-inference setup
(free-tier 30B Nemotron) to demonstrate that architectural choices —
pre-fetched retrieval and role-priored tool registration — produce
paper-grade signal independent of frontier-model inference budget. On
DietResearchBench-Clinical (n=40, 6-metric panel), diet_os achieves
Bonferroni-significant verdict-κ uplift (mean_diff +0.476 to +0.576,
p_adj = 0.002) over MedAgents, MDAgents, and yang2025 baselines, plus
structural HDI Recall separation (diet_os 0.713, all baselines 0.000).
A triage-ablation variant (`diet_os_llm_triage`) that replaces the
deterministic gold-triage substitute with the same free-tier LLM
collapses to baseline-equivalent (κ 0.019, HDI Recall 0.000), isolating
the deterministic-triage + retrieval-seed pair as load-bearing for the
architectural lift.
All gains are measured against baselines near zero; diet_os records zero
strict successes (0/40) under v1 eval-harness heuristics, with the
architectural signal concentrated in the 13/40 runs that surface
non-empty retrieval bundles. We release the benchmark as a v1 reference
resource; companion v2 (n=200, two-annotator IAA) is in progress.
