## 4. Benchmark: DietResearchBench-Clinical v1

DietResearchBench-Clinical v1 is a 40-scenario benchmark across four clinical
categories: **herbal_single_symptom** (10; e.g. turmeric × osteoarthritis,
valerian × insomnia), **nutrition** (10; e.g. vitamin D, omega-3,
Mediterranean pattern), **multi_drug_hdi** (10; from the HDI-Safe-50 panel,
e.g. SJW × warfarin, grapefruit × simvastatin), and **tcm_bilingual** (10;
herb-name and modern-symptom bilingual lookups via SymMap v2.0).

Each scenario carries a `GoldStandard` record:
`expected_complexity` ∈ {low, moderate, high}, `expected_panel_verdict` ∈
{prefer, caution, reject, abstain}, `expected_evidence_tier` ∈
{clinical_trial, observational, mechanistic, unknown}, `expected_min_chains`,
`expected_defer`, `expected_red_flags` (mechanism classes such as
`serotonergic_interaction`, `coagulation`), `expected_hdi_severity`, and
`languages`.

Six metrics score every prediction:
**Verdict κ** (Cohen's quadratic-weighted κ);
**ECE** (10-bin equal-width on `confidence`);
**HDI Recall** (severe-or-moderate gold HDI claims surfaced via
`kg_hdi_check`); **Provenance** (source-attribution v1: fraction of
`cited_chains` whose edges carry a `source_id` prefix in
`{cmaup:, duke:, herb2:, symmap:, hdi-safe-50:}`); **Defer Accuracy**
(binary agreement on `defer_to_clinician`); **Bilingual Coverage**
(CJK-character detection over `candidate_chains` on `tcm_bilingual`).
Means use 95 % bootstrap CIs (1000 iters); paired comparisons use
paired-bootstrap with Bonferroni correction over five `diet_os`-vs-baseline
contrasts (α' = 0.01).

Scenarios are split 60/20/20 with seed 42 (`splits_seed42.json`). The
entity-level leakage guard is enforced with one documented v1 exemption:
`case-nutrition-008-probiotics-ibs` shares the *probiotics* entity across
train and test, an unavoidable artefact at N = 40. The companion v2 release
(n = 200, two-annotator IAA target κ ≥ 0.6 on verdict and κ ≥ 0.7 on binary
HDI) closes this gap [@v2benchmark2026].
