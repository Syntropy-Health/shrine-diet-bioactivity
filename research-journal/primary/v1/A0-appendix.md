# Appendix

This appendix follows the bibliography and is excluded from the ML4H Findings 4-page body budget per venue convention. Sections relocated here from the body retain full numerical content and reviewer-relevant detail.

## A.1 Pre-fetch design rationale and pilot data

_Source: relocated from §3.1 (T14.9). Body keeps a one-clause back-reference._

The §3.1 pre-fetched design choice is motivated by the following pilot observation:

This **pre-fetched** design is a deliberate departure from LLM-driven tool
calls. Our pilot found Nemotron-30B emits `RoleVerdict` JSON whose `notes`
field claims tool use ("Used `kg_diet_to_compounds`…") while transcript-level
tool-invocation counts remain zero across all roles — the model hallucinates
tool use from training-data priors (`e2-panel-mcp-wiring-results.md`).
Pre-fetching guarantees every panel deliberation receives a non-empty bundle,
so HDI-Recall and provenance metrics (§4) become measurable rather than null.

## A.2 Cost & latency per-role traces

_Source: relocated from §5 cost-and-latency paragraph (T14.10). Body keeps a one-clause "see A.2" pointer._

Per-role cost and latency detail relocated from §5:

**Cost and latency.** Per-role token usage and latency are captured by
the `cost_tracker` decorator wrapping `ConversableAgent.generate_reply`.
Free-tier rate limits dominate end-to-end matrix wall-clock (full-40
× 6 baselines completed in ~3 hours; the `diet_os_llm_triage` ablation
adds ~2 hours due to free-tier RPM throttling on the additional triage
LLM call). Detailed per-role traces are available in the companion code
release; we omit the table here for space.

## A.3 Failure-mode case studies

_Source: relocated from §6.4 case-study walkthrough (T14.8). Body retains the headline 13-non-empty / 0.713 / 0.300 numbers; case-level detail and `case-hdi-001-sjw-sertraline` walkthrough live here._

The §6.4 failure-mode taxonomy in the body summarizes a three-bucket distribution; below is the full per-bucket detail and the canonical case-study illustration referenced from §6.4.

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

## A.4 Extended related work

_Reserve target for any §2 prose squeezed out by C-ADDS (T14.13–T14.15) or for HealthGenie / additional comparators if they need framing without body weight._

(Content placeholder — populated only if needed during C-ASSEMBLE.)

## A.5 Limitations and Broader Impact

_Source: relocated from §8 in entirety (T14.11). Body §8 keeps only a 3-line stub referencing this section._

The body §8 stub references this section. Below are the full limitation subsections relocated from §8:

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

## A.6 Reproducibility extended

_Source: relocated from §9.2 reproducibility detail (T14.12). Body §9.2 keeps the URL + commit pin + a forward-pointer; full commands, stats config, LLM/KG details live here. Plan B integrity bullet (T14.20) inserts here._

Full reproducibility detail relocated from §9.2 of the body:

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
