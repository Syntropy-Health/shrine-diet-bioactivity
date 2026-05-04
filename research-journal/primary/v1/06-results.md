## 6. Results

We report the full N = 40 matrix across all six systems. Headline numbers and
statistical tests are bundled with the paper as `tables/headline-matrix.md`,
`tables/paired-tests.md`, `tables/per-category.md`,
`tables/failure-taxonomy.md`, `figures/per-category-heatmap.png`, and
`figures/reliability-diagram.png`.

### 6.1 Headline matrix

The headline matrix (`tables/headline-matrix.md`) is reproduced inline below.
All values are mean [95% bootstrap CI].

| System | Verdict κ | ECE | HDI Recall | Provenance | Defer Acc | Bilingual |
| --- | --- | --- | --- | --- | --- | --- |
| single_llm | 0.055 [0.011, 0.114] | 0.326 [0.228, 0.400] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.548 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| single_llm_rag | -0.013 [-0.045, 0.000] | 0.397 [0.397, 0.397] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.548 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| yang2025 | 0.017 [0.000, 0.056] | 0.341 [0.294, 0.380] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.548 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| medagents | 0.000 [0.000, 0.000] | 0.024 [0.019, 0.030] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.548 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| mdagents | 0.000 [0.000, 0.000] | 0.015 [0.009, 0.021] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.548 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| **diet_os** | **0.251 [0.061, 0.451]** | 0.542 [0.400, 0.680] | **0.709 [0.333, 1.000]** | 1.000 [1.000, 1.000] | **0.696 [0.550, 0.825]** | 0.000 [0.000, 0.000] |

`diet_os` reaches Verdict κ = 0.251 against an envelope of κ ≤ 0.055 for every
baseline; HDI Recall = 0.709 against 0.000 for every baseline (a structural
separation, not a margin); Defer Acc = 0.696 against a flat 0.548 baseline
(+0.148). `diet_os` posts the worst ECE (0.542) — the calibration trade-off
discussed in §7. Provenance is 1.000 across the board because the
source-attribution proxy is vacuously satisfied by systems that emit no
candidate chains; Bilingual is 0.000 across the board because the v1 metric
reads candidate-chain language only and no system surfaces zh chains. Both
are reframed in §6.2 and §8. The `single_llm_rag` baseline lands at κ =
−0.013, slightly worse than the no-tool `single_llm` (κ = 0.055): naïve
LightRAG retrieval over our KG returns dense unfiltered context that the
30 B Nemotron model treats as conflicting evidence and answers `caution`
to nearly every scenario, slightly mis-aligning with the gold distribution.
This is consistent with the broader claim that grounded retrieval requires
typed traversal, not vector dump.

### 6.2 Paired statistical tests

Paired bootstrap tests (B = 10 000 iterations, Davison–Hinkley
`(k+1)/(B+1)` p-value, Bonferroni-corrected over the full
n_baselines × n_metrics_tested = 5 × 4 = 20-cell family at adjusted
α' = 0.0025; `tables/paired-tests.md`) confirm the architectural
headline. **Sign convention**: for Verdict κ, HDI Recall, and Defer
Acc, higher is better and a positive `mean_diff = diet_os − baseline`
is favourable; for ECE, lower is better and a positive `mean_diff` is
*adverse*. **Surrogate disclosure**: the paired κ test resamples
per-scenario gold-vs-predicted verdict correctness rather than the κ
statistic itself (κ requires a list and is not iid-resampleable), so
the test answers "is `diet_os` more often verdict-correct than
baseline?", not "is `diet_os`'s κ statistic higher?". The conclusions
agree on direction.

After the corrected family-size correction, all five Verdict κ
comparisons remain significant; HDI Recall comparisons remain
significant for all five baselines; Defer Acc comparisons drop to
borderline / non-significant under the 20-cell correction (was
significant under the previous under-counted 5-cell correction — see
`tables/paired-tests.md` for the corrected p_adj column). The lone
adverse direction is ECE: `diet_os` is significantly *worse* than
`medagents` and `mdagents`, a calibration trade-off (§7.3). The Provenance metric (source-attribution proxy)
returns 1.0 for any system with non-empty candidate chains and is vacuously
1.0 for the five baselines that emit none — under v1 framing it does not
separate `diet_os` from the field; full Cypher round-trip verification is
deferred to v2 (§8).

### 6.3 Per-category breakdown

The per-category Verdict κ heatmap (`figures/per-category-heatmap.png`,
data in `tables/per-category.md`) shows `diet_os` strongest on `tcm_bilingual`
(κ = 0.167), `nutrition` (0.153), and `multi_drug_hdi` (0.138), and weakest
on `herbal_single_symptom` (κ = -0.081). Baselines are essentially flat
across categories (max non-`diet_os` cell: `single_llm` on `multi_drug_hdi`,
0.062). The `herbal_single_symptom` regression is consistent with eval-time
intervention extraction missing the herb's canonical KG name in
single-symptom scenarios — the `_intervention_from_scenario_id` heuristic
favours multi-token names (e.g. "St John's wort + sertraline") and degrades
on bare herbal mononyms.

### 6.4 Failure-mode taxonomy

Across the 40 `diet_os` runs (`tables/failure-taxonomy.md`) we observe zero
strict successes (gold-match verdict with confidence ≥ 0.1) and a clean
three-bucket failure distribution: 27/40 (67.5%) `retrieval_empty`, 7/40
`panel_mis_vote`, 6/40 `calibrator_under_confidence`. The dominant failure
mode is upstream of the panel: the eval-time
`_intervention_from_scenario_id` heuristic misses canonical KG names for
non-Duke compounds and TCM herbs, producing empty candidate chains.
`case-hdi-001-sjw-sertraline` illustrates the pattern: gold `reject`,
predicted `caution`, candidate_chains = 0, confidence = 0.016. Of the 13
runs that *do* surface chains, 7 are panel mis-votes and 6 are correct
verdicts under-scored by the calibrator. The 0.709 HDI Recall is therefore
concentrated in those 13 non-empty runs; the lower 95% bound (0.286 on the
paired-test mean_diff, 0.333 on the absolute Recall CI) reflects this
small effective sample. The structural separation over baselines (all
0.000) is preserved because no baseline has a mechanism to surface HDI
claims at all — independent of how many of its 40 runs produce chains.
