# 9. Future Work and Conclusion

## 9.1 Future Work

- v2 benchmark: n=200, two-annotator IAA, calibration-aware Platt/isotonic step [@v2benchmark2026]
- Pydantic-AI orchestration ablation (1.5-day migration)
- Paid-tier LLM ablation (Qwen-3-235B, Sonnet 4.6)
- Cypher round-trip provenance verification against Aura
- Bilingual metric reading panel deliberation text (not just `candidate_chains`)
- `kg_disease_to_herbs` inverse traversal for the systematic-review persona

## 9.2 Conclusion

We present diet_os, a 6-role multi-agent clinical research system over a unified 5M-edge diet/herb/TCM knowledge graph queried via streamable-HTTP MCP. Pre-fetched typed-traversal retrieval bundles plus role-priored Layer-B/C tools produce **[FILL FROM Results: Bonferroni-significant verdict-κ uplift over MedAgents/MDAgents/yang2025 baselines and structural HDI Recall separation]** under deliberate constrained inference (free-tier 30B Nemotron). DietResearchBench-Clinical v1 (40 scenarios, 6-metric panel) is released as a v1 reference resource; v2 expansion is in progress as a companion paper. Code and benchmark are released at `https://github.com/Syntropy-Health/shrine-diet-bioactivity`.
