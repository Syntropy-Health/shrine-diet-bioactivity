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
Bonferroni-significant verdict-κ uplift (mean_diff +0.476 to +0.575,
p_adj < 0.0001) over MedAgents, MDAgents, and yang2025 baselines, plus
structural HDI Recall separation (diet_os 0.709, all baselines 0.000).
We release the benchmark as a v1 reference resource; companion v2 (n=200,
two-annotator IAA) is in progress.
