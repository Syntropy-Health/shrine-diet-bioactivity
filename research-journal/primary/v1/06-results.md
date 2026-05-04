## 6. Results

We report the full N = 40 matrix across all seven systems (six external
systems plus the `diet_os_llm_triage` ablation that addresses peer-review
concern C1). Headline numbers and statistical tests are bundled with the
paper as `tables/headline-matrix.md`, `tables/paired-tests.md`,
`tables/per-category.md`, `tables/failure-taxonomy.md`,
`tables/ablation-test.md`, `figures/per-category-heatmap.png`, and
`figures/reliability-diagram.png`.

### 6.1 Headline matrix

The headline matrix (`tables/headline-matrix.md`) is reproduced inline below.
All values are mean [95% bootstrap CI].

| System | Verdict κ | ECE | HDI Recall | Provenance | Defer Acc | Bilingual |
| --- | --- | --- | --- | --- | --- | --- |
| single_llm | 0.056 [0.011, 0.117] | 0.325 [0.228, 0.400] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.550 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| single_llm_rag | -0.012 [-0.043, 0.000] | 0.397 [0.397, 0.397] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.550 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| yang2025 | 0.017 [0.000, 0.056] | 0.341 [0.294, 0.383] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.550 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| medagents | 0.000 [0.000, 0.000] | 0.024 [0.019, 0.030] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.550 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| mdagents | 0.000 [0.000, 0.000] | 0.015 [0.009, 0.021] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.550 [0.400, 0.700] | 0.000 [0.000, 0.000] |
| **diet_os** | **0.258 [0.067, 0.466]** | 0.543 [0.396, 0.683] | **0.713 [0.333, 1.000]** | 1.000 [1.000, 1.000] | **0.699 [0.550, 0.825]** | 0.000 [0.000, 0.000] |
| diet_os_llm_triage | 0.019 [-0.049, 0.092] | 0.090 [0.019, 0.186] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.550 [0.400, 0.700] | 0.000 [0.000, 0.000] |

`diet_os` reaches Verdict κ = 0.258 against an envelope of κ ≤ 0.056 for every
external baseline; HDI Recall = 0.713 against 0.000 for every baseline (a
structural separation, not a margin); Defer Acc = 0.699 against a flat 0.550
baseline (+0.149). `diet_os` posts the worst ECE (0.543) — the calibration
trade-off discussed in §7. Provenance is 1.000 across the board because the
source-attribution proxy is vacuously satisfied by systems that emit no
candidate chains; Bilingual is 0.000 across the board because the v1 metric
reads candidate-chain language only and no system surfaces zh chains. Both
are reframed in §6.2 and §8. The `single_llm_rag` baseline lands at κ =
−0.012, slightly worse than the no-tool `single_llm` (κ = 0.056): naïve
LightRAG retrieval over our KG returns dense unfiltered context that the
30 B Nemotron model treats as conflicting evidence and answers `caution`
to nearly every scenario, slightly mis-aligning with the gold distribution.
This is consistent with the broader claim that grounded retrieval requires
typed traversal, not vector dump. The final row, `diet_os_llm_triage`, is the
architectural ablation introduced to address peer-review concern C1 about
gold-triage bypass: it shares all of `diet_os`'s code paths (KG retrieval,
6-role panel, calibrator) but replaces the deterministic gold-triage
substitute with a free-tier Nemotron LLM call. Its κ collapses to 0.019 and
HDI Recall collapses to 0.000, isolating the gold-triage substitute as
load-bearing for the architectural lift; full discussion in §6.5.

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

Under the corrected family-size correction, all five Verdict κ
comparisons remain significant (p_adj = 0.002); all five HDI Recall
comparisons remain significant (p_adj = 0.006); and all five Defer Acc
comparisons remain significant (p_adj = 0.040, just under the α = 0.05
threshold). The lone adverse direction is ECE: `diet_os` is significantly
*worse* than `medagents` and `mdagents` (p_adj = 0.002), a calibration
trade-off (§7.3). The Provenance metric (source-attribution proxy)
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
verdicts under-scored by the calibrator. The 0.713 HDI Recall is therefore
concentrated in those 13 non-empty runs; the lower 95% bound (0.300 on the
paired-test mean_diff, 0.333 on the absolute Recall CI) reflects this
small effective sample. The structural separation over baselines (all
0.000) is preserved because no baseline has a mechanism to surface HDI
claims at all — independent of how many of its 40 runs produce chains.

### 6.5 Triage ablation: deterministic substitute is load-bearing

To isolate which architectural component drives the lift, we run
`diet_os_llm_triage` — an ablation that shares all of `diet_os`'s code
(retrieval, 6-role panel, calibrator) but replaces the deterministic
gold-triage substitute (§5.4) with a free-tier Nemotron LLM call producing
the same `Triage` Pydantic model. Headline numbers from the §6.1 matrix
collapse to baseline-equivalent: κ falls from 0.258 to 0.019, HDI Recall
falls from 0.713 to 0.000, Defer Acc falls from 0.699 to 0.550. The
ablation paired bootstrap (`tables/ablation-test.md`, B = 10 000, no
Bonferroni — single planned comparison) confirms the collapse is
statistically robust: verdict-correctness mean_diff = 0.476 [0.300,
0.650] (p = 0.0001), HDI Recall mean_diff = 0.715 [0.429, 1.000] (p =
0.0003), Defer Acc mean_diff = 0.149 [0.050, 0.275] (p = 0.002), and ECE
mean_diff = 0.462 [0.305, 0.618] adverse to `diet_os` (p = 0.0001) — the
ablation has *better* calibration but only because it falls back to a
constant `caution` default that happens to align with the gold class
prior, exactly the behaviour a calibrated panel should not exhibit.

The proximate failure mode is the LLM triage step itself: 33 of 40 runs
(82.5%) terminate with `runner-error: Invalid JSON: EOF while parsing a
list` — the free-tier Nemotron-3-nano-30B (≤20 RPM) emits malformed JSON
on the structured `ResearchQuestion` output. The runner falls back to
default `complexity='low'`, `red_flags=[]`, `clarification_questions=[]`,
which seeds zero retrieval keys; consequently 40 of 40 runs (100%) have
empty candidate chains, and 33 of 40 panels terminate at
`moderator_summary='error'` after exhausting AG2's `Maximum rounds (3)`.
Two architectural components are therefore load-bearing in combination:
(i) the deterministic triage substitute, which is invariably
parse-clean, and (ii) the gold-question-anchored retrieval seed, which
requires triage output the panel can actually use. Removing (i) breaks
(ii) by cascading failure, regressing the system to the `single_llm`
envelope. We discuss the v2 path — a small purpose-trained triage model
or schema-constrained decoding — in §8. The 0.090 ECE that
`diet_os_llm_triage` posts is *not* an architectural strength to retain;
it is the spurious low-error of a system that has stopped engaging with
the question.
