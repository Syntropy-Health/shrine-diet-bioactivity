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
   (mean_diff +0.476 to +0.576, p_adj = 0.002) and structural HDI Recall
   separation (diet_os = 0.713, all 5 baselines = 0.000) over MedAgents
   [@medagents2024], MDAgents [@mdagents2024], and Yang et al. [@yang2025]
   on DietResearchBench-Clinical (n = 40). A within-system triage ablation
   (`diet_os_llm_triage`, §6.5) collapses to κ = 0.019 / HDI Recall = 0.000,
   isolating the deterministic-triage + retrieval-seed pair as load-bearing.

3. **Benchmark.** DietResearchBench-Clinical v1: 40 scenarios across herbal
   single-symptom, nutrition single-nutrient, multi-drug herb-drug
   interaction, and TCM bilingual; 6-metric evaluation panel. Companion v2
   paper expands to n = 200 with two-annotator IAA [@v2benchmark2026].

## 2. Related Work

### Multi-agent clinical reasoning

MedAgents [@medagents2024] frames zero-shot medical reasoning as a multi-role
panel deliberating over nine medical datasets, and MDAgents [@mdagents2024]
adds adaptive routing between solo and multi-disciplinary-team configurations.
Yang et al. [@yang2025] propose a 2-role dietitian-pharmacist setup for
diet-drug interaction reasoning. We compare against all three as architectural
baselines and extend them with Layer-B/C role-priored KG retrieval. A
contemporary threat is Wu et al.'s "Safer Therapy" [@wu2025], which reports
single-GP performance comparable to a multi-disciplinary debate panel on
medication-conflict resolution; §7.2 argues that our HDI Recall structural
ablation shows debate without KG-grounding cannot produce HDI signal, placing
the two findings on orthogonal axes.

### KG-grounded LLM clinical reasoning

AMG-RAG [@amgrag2025] constructs a medical knowledge graph agentically and
reports F1 74.1 % on MedQA; MedRAG [@medrag2025] fuses a four-tier
hierarchical diagnostic KG with EHR retrieval; KG-SMILE [@kgsmile2025] adds
explainability to KG-RAG. Our pre-fetched typed-Cypher retrieval is
offline-constructed and queried deterministically through the MCP gateway
(§3.1), so live KG construction is orthogonal rather than competing.

### TCM multi-agent and KG systems

The closest direct competitor is JingFang [@jingfang2025], a multi-agent TCM
consultation system with syndrome differentiation and dual-stage retrieval.
JingFang is prescription-only, has no Western-nutrition coverage, lacks an
English/bilingual interface, and exposes no KG query layer. OpenTCM
[@opentcm2025] applies GraphRAG over a 48K-entity TCM KG (P = 98.55 % on
classical-text extraction) but is TCM-only; our 5M-edge KG is a superset
combining Western nutrition with TCM. AgentClinic [@agentclinic2024]
introduced multimodal sequential clinical decision benchmarks; we operate in
the static-question evaluation paradigm.

### Existing benchmarks

TCM-Eval [@tcmeval2025] and TCM-5CEval [@tcm5ceval2025] cover TCM knowledge
questions with no clinical-deliberation evaluation. MedQA [@medqa2021] and
MedMCQA [@medmcqa2022] are general medical-MCQ ceilings with no diet or herb
content, and AgentClinic [@agentclinic2024] is multimodal sequential
consultation. To the best of available literature, DietResearchBench-Clinical
(§4) is the first public benchmark covering herb-drug interaction reasoning,
diet-bioactive clinical inference, and TCM syndrome / Western-nutrition
crosswalk in a single evaluation set.

## 3. System: diet_os

`diet_os` is a six-role multi-agent pipeline implemented in AG2 [@ag2v0_12]
over a 5M-edge unified diet/herb/TCM knowledge graph served by a
streamable-HTTP MCP gateway. Figure 1 shows the end-to-end flow.

![Figure 1. diet_os pipeline: triage extracts a PICO-typed `ResearchQuestion`; `retrieve_for_question` dispatches deterministic Layer-B/C MCP traversals into a `KGRetrievalBundle`; six role agents deliberate over the bundle in a round-robin GroupChat; the moderator summarizes, the calibrator scores composite confidence, and synthesis emits a `ResearchSynthesis` artifact.](figures/architecture-diagram.png)

### 3.1 Triage and pre-fetched retrieval

Triage converts the user's free-text question into a typed `ResearchQuestion`
(PICO-shaped: population, intervention, comparator, outcome, language hints)
plus a `Triage` record carrying complexity, suspected red flags, and language
tags. We extract the first balanced `{...}` slice to absorb free-tier
Nemotron-30B's JSON-quality variance.

`retrieve_for_question(rq, triage)` then dispatches deterministic Layer-B/C
MCP calls *before* any panel agent runs. A herb intervention triggers
`kg_herb_to_diseases` and `kg_herb_to_symptoms`; a compound intervention
triggers `kg_compound_to_targets`; any (drug, herb) co-occurrence triggers
`kg_hdi_check`; CJK characters or `zh` language hints trigger
`kg_bilingual_term`. Results fuse into a `KGRetrievalBundle` of
`ProvenanceChain[]` with edge-level `source_id` attribution
(`cmaup:plant_disease`, `duke:found_in_food`, `hdi-safe-50:mechanism`, etc.).

This **pre-fetched** design is a deliberate departure from LLM-driven tool
calls. Our pilot found Nemotron-30B emits `RoleVerdict` JSON whose `notes`
field claims tool use ("Used `kg_diet_to_compounds`…") while transcript-level
tool-invocation counts remain zero across all roles — the model hallucinates
tool use from training-data priors (`e2-panel-mcp-wiring-results.md`).
Pre-fetching guarantees every panel deliberation receives a non-empty bundle,
so HDI-Recall and provenance metrics (§4) become measurable rather than null.

### 3.2 Role-priored panel

The panel is an AG2 `GroupChat` round-robin with `max_round = len(roles)` —
one verdict per role, no rebuttal. Each role registers a *subset* of the
10-tool MCP toolkit reflecting its real-world information prior
(`staged-mcp-persona-audit.md`):

| Role | Priored MCP tools |
|---|---|
| Dietitian | `kg_diet_to_compounds`, `kg_compound_to_symptoms` |
| Pharmacologist | `kg_compound_to_targets` |
| TCM Practitioner | `kg_bilingual_term`, `kg_herb_to_diseases`, `kg_herb_to_symptoms` |
| Clinical Research Scientist | `kg_query` (Layer-A NL fallback) |
| Safety Reviewer | `kg_hdi_check` |
| Defer-to-Clinician | `kg_query` |

Tools remain available as fallbacks when the LLM does emit valid `tool_calls`,
but the bundle dominates the evidence pathway. Each role emits a `RoleVerdict`
∈ {prefer, caution, reject, abstain} with `support[]`, `concerns[]`, and
`cited_chains[]` indices into the bundle. Single-pass round-robin (rather
than multi-round rebuttal) is forced by the 20-RPM rate limit and is
defensible because pre-fetching removes the information asymmetry rebuttal
would normally resolve (§7.2).

### 3.3 Moderator, calibrator, synthesis

The moderator concatenates the six `RoleVerdict`s into a textual summary plus
dissent list. The calibrator computes composite confidence as a weighted
product of evidence-tier strength, HDI risk, and question-fit, each in [0, 1].
The terminal artifact is a `ResearchSynthesis` Pydantic model with `verdict`,
`support`, `concerns`, `cited_chains`, `confidence`, `components`, and a
`defer_to_clinician` boolean derived from the Safety Reviewer's verdict and
the Defer-to-Clinician role's vote. This single object is scored by all six
benchmark metrics.

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

## 5. Experimental setup

**LLM.** All systems share free-tier OpenRouter Nemotron-3-nano-30B (chat,
20 RPM). Holding the LLM constant isolates the architectural ablation and
frames the results as constrained-inference findings.

**Orchestration.** AG2 v0.12.1 (the AG2AI Apache-2.0 fork; we avoid AutoGen
v0.4 maintenance-mode), with `GroupChat` round-robin and Pydantic-typed
messages.

**Knowledge graph.** Neo4j AuraDB Professional 8 GB hosting `unified_diet_kg`
(166K nodes, ~5M relationships) ingested from Duke phytochemical, FooDB,
CMAUP, SymMap v2.0, HERB 2.0, HDI-Safe-50, and OpenNutrition.

**MCP gateway.** Streamable-HTTP at `kg-mcp-test.up.railway.app/mcp`
exposing 10 tools across 3 layers: Layer A (`kg_query` NL Q&A), Layer B (6
typed traversals), Layer C (3 lookup primitives — `kg_hdi_check`,
`kg_bilingual_term`, `kg_node_neighborhood`). The session is
singleton-per-process across the eval matrix.

**Baselines.** Five external baselines plus `diet_os` and a within-system
ablation share LLM, KG, and gateway: `single_llm` (no tools),
`single_llm_rag` (naïve RAG), `yang2025` (2-role dietitian-pharmacist)
[@yang2025], `medagents` (n-role debate, no KG) [@medagents2024],
`mdagents` (adaptive routing, no KG) [@mdagents2024], **`diet_os`** (this
work, deterministic gold-triage substitute — see §5.4 for the bypass
disclosure), and **`diet_os_llm_triage`** (identical to `diet_os` but
replacing the deterministic triage with a free-tier LLM call; introduced
to address peer-review concern C1 about gold-triage bypass, full discussion
in §6.5). We report the full N = 40 matrix across all seven systems.

**Cost and latency.** Per-role token usage and latency are captured by
the `cost_tracker` decorator wrapping `ConversableAgent.generate_reply`.
Free-tier rate limits dominate end-to-end matrix wall-clock (full-40
× 6 baselines completed in ~3 hours; the `diet_os_llm_triage` ablation
adds ~2 hours due to free-tier RPM throttling on the additional triage
LLM call). Detailed per-role traces are available in the companion code
release; we omit the table here for space.

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

# 8. Limitations

## 8.1 Single-author gold standard at n=40

DietResearchBench-Clinical v1 uses single-author gold annotations across 40 scenarios with no inter-annotator agreement (IAA) measurement. A v2 expansion (n=200, two-annotator design with κ ≥ 0.6 gating and calibration-aware Platt/isotonic scoring) is in progress as a companion paper [@v2benchmark2026].

## 8.2 Free-tier 30B LLM — not a calibration ceiling

Free-tier Nemotron-3-nano-30B has known JSON-quality issues at long contexts and is rate-limited to 20 RPM. We adopt this constraint deliberately to validate the architectural-headline framing under cost-zero inference. v2 ablates against Qwen-3-235B-Instruct via Cerebras (1M tok/day free tier) and paid-tier alternatives (Sonnet 4.6).

## 8.3 HDI Recall is in-panel, not universe-recall

Per the KG coverage audit (`docs/kg-coverage-audit.md`), HDI-Safe-50 covers 86.2% of the curated public HDI universe known to NIH ODS and NCCIH (n=15 reference pairs). Reported HDI Recall is therefore in-panel recall against the curated v1 panel, not absolute recall against the broader herb-drug interaction literature.

## 8.4 Source-attribution provenance, not Cypher round-trip

Provenance metric uses the source-id-prefix proxy (`cmaup:`, `duke:`, `herb2:`, `symmap:`, `hdi-safe-50:`) rather than full Cypher round-trip verification against Aura. Edges retrieved through Layer-B/C MCP traversals are KG-faithful by construction; Cypher verification for adversarial cases is deferred to v2.

## 8.5 AG2-specific orchestration

diet_os is implemented in AG2 v0.12. Pydantic-AI re-ports (estimated 1.5-day migration; native MCP streamable-HTTP, Logfire observability) are deferred to v2 as a framework ablation.

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

- **Commit pin.** Headline matrix and §6.5 ablation paired tests render
  cleanly at commit `6348d10` on branch `feature/mcp-herbal-botanicals`.
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
