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
`https://github.com/Syntropy-Health/shrine-diet-bioactivity`.

- **Commit pin.** Headline matrix, §6.5 ablation paired tests, and the
  reproducibility instructions in this section are all consistent at the
  tip of branch `feature/mcp-herbal-botanicals` (R-plan tasks R1-R9
  complete; commits `05743b5..0a3a481`). Camera-ready submission will
  pin a specific SHA via `git tag`.
- **Eval matrix.** Combined 7-system results dir at
  `research-journal/shared/results/20260504T230617Z-final-7sys/`
  (symlinks 6 systems from `20260504T042540Z` plus the
  `diet_os_llm_triage` ablation from
  `20260504T204413Z-llm-triage-ablation`).
- **Re-render.** `python3 -m eval.report --results-dir <dir>
  --cypher-runner source-attribution` regenerates `summary.md`,
  `paired_tests.md`, `category_breakdown_verdict_kappa.md`, and
  `reliability_diagram.png`. `python3 -m scripts.render_ablation_test
  --results-dir <dir>` regenerates `ablation_test.md`.
- **Stats.** Paired bootstrap with B = 10 000, Davison-Hinkley
  `(k+1)/(B+1)` p-value, fixed seed = 42, Bonferroni over 5 baselines ×
  4 metrics_tested = 20 cells (provenance + bilingual excluded as
  vacuous under v1; see §6.2).
- **LLM.** Free-tier OpenRouter Nemotron-3-nano-30B (`nvidia/nemotron-3-nano-30b-a3b:free`),
  ≤20 RPM. The free-tier rate limit is what drives the LLM-triage parse
  failures observed in §6.5; results are model-version-sensitive.
- **KG.** Neo4j AuraDB Professional 8 GB hosting `unified_diet_kg` (166K
  nodes, ~5M relationships). Read-only Bearer-auth gateway at
  `kg-mcp-test.up.railway.app/mcp`.

## 9.3 Conclusion

We present diet_os, a 6-role multi-agent clinical research system over a unified 5M-edge diet/herb/TCM knowledge graph queried via streamable-HTTP MCP. Pre-fetched typed-traversal retrieval bundles plus role-priored Layer-B/C tools produce Bonferroni-significant verdict-κ uplift (mean_diff +0.476 to +0.576, p_adj = 0.002) over MedAgents [@medagents2024], MDAgents [@mdagents2024], and yang2025 [@yang2025] baselines, and structural HDI Recall separation (Diet-OS 0.713, all baselines 0.000) under deliberate constrained inference (free-tier 30B Nemotron). A within-system triage ablation (`diet_os_llm_triage`, §6.5) collapses to baseline-equivalent (κ 0.019, HDI Recall 0.000), confirming the deterministic-triage + retrieval-seed pair as load-bearing for the architectural lift. DietResearchBench-Clinical v1 (40 scenarios, 6-metric panel) is released as a v1 reference resource; v2 expansion is in progress as a companion paper [@v2benchmark2026]. Code and benchmark are released at `https://github.com/Syntropy-Health/shrine-diet-bioactivity`.
