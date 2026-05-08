# 9. Future Work and Conclusion

## 9.1 Future Work

- v2 benchmark: n=200, two-annotator IAA, calibration-aware Platt/isotonic step [@v2benchmark2026]
- Pydantic-AI orchestration ablation (1.5-day migration)
- Paid-tier LLM ablation (Qwen-3-235B, Sonnet 4.6)
- Cypher round-trip provenance verification against Aura
- Bilingual metric reading panel deliberation text (not just `candidate_chains`)
- `kg_disease_to_herbs` inverse traversal for the systematic-review persona

## 9.2 Reproducibility

All numbers in this paper are reproducible from the public repository at
`https://github.com/Syntropy-Health/shrine-diet-bioactivity`. See
Appendix A.6 for full re-render commands, stats configuration, and LLM/KG
details, plus pinned commit SHAs.

## 9.3 Conclusion

We present diet_os, a 6-role multi-agent clinical research system over a unified 5M-edge diet/herb/TCM knowledge graph queried via streamable-HTTP MCP. Pre-fetched typed-traversal retrieval bundles plus role-priored Layer-B/C tools produce Bonferroni-significant verdict-κ uplift (mean_diff +0.476 to +0.576, p_adj = 0.002) over MedAgents [@medagents2024], MDAgents [@mdagents2024], and yang2025 [@yang2025] baselines, and structural HDI Recall separation (Diet-OS 0.713, all baselines 0.000) under deliberate constrained inference (free-tier 30B Nemotron). A within-system triage ablation (`diet_os_llm_triage`, §6.5) collapses to baseline-equivalent (κ 0.019, HDI Recall 0.000), confirming the deterministic-triage + retrieval-seed pair as load-bearing for the architectural lift. DietResearchBench-Clinical v1 (40 scenarios, 6-metric panel) is released as a v1 reference resource; v2 expansion is in progress as a companion paper [@v2benchmark2026]. Code and benchmark are released at `https://github.com/Syntropy-Health/shrine-diet-bioactivity`.
