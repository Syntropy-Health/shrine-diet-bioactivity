## 7. Discussion

### 7.1 Architectural ablation: KG-grounding is the lift

The Bonferroni-significant Verdict κ uplift (mean_diff +0.476 to +0.576
across all five baselines, p_adj = 0.002) and the structural HDI Recall
separation (0.713 vs 0.000 for every baseline, p_adj = 0.006) localize
the lift to role-priored Layer-B/C retrieval — not panel size, not LLM
scale. `medagents` and `mdagents`, both multi-agent debate systems
without KG grounding, post the same Verdict κ = 0.000 as the no-tool
`single_llm` baseline. Adding agents without adding evidence retrieval
moves no headline metric. The within-system `diet_os_llm_triage`
ablation (§6.5) further localizes the lift to the joint
deterministic-triage + retrieval-seed pair: replacing the deterministic
substitute with a free-tier LLM triage call collapses κ to 0.019 and
HDI Recall to 0.000, regressing the system to single_llm-equivalent
performance.

### 7.2 Address: Wu et al. (2025) "Safer Therapy"

Wu et al. [@wu2025] recently reported that single-GP performance is
comparable to multi-disciplinary multi-agent systems on medication
conflict resolution, raising the question of whether multi-agent debate
alone is worth the inference cost. Our results are orthogonal: their
axis is debate-style consensus among agents sharing the same
retrieval-free input; our axis is KG-grounded retrieval. The HDI Recall
structural separation in §6.1 (diet_os = 0.713, all five baselines =
0.000) shows that debate without KG-grounding cannot produce non-zero
HDI recall on DietResearchBench-Clinical regardless of panel size. HDI
Recall is structurally non-zero only for systems that invoke
`kg_hdi_check` and surface mechanism-tagged chains — a capability
absent in all five baselines by design, mirroring the real-world
absence of KG integration in those architectures.
**Debate alone is insufficient; KG-grounded retrieval is what produces
HDI signal.**

### 7.3 Calibration trade-off

ECE is highest for `diet_os` at 0.543 — significantly worse than
`medagents` (0.024, mean_diff +0.531) and `mdagents` (0.015, mean_diff
+0.540) at p_adj = 0.002. The trade-off reflects panel-derived
confidence variance under an uncalibrated free-tier model: `medagents`
and `mdagents` emit near-constant low confidence, collapsing ECE toward
the gold rate, while `diet_os`'s composite confidence (evidence-tier ×
HDI-risk × question-fit, §3.3) carries honest but uncalibrated signal.
Post-hoc Platt/isotonic calibration on a held-out fold is straightforward
v2 work (§8.2, §9).
