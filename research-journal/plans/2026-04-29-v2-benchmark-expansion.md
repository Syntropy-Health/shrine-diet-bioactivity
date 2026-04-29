# DietResearchBench-Clinical v2 — Expansion Plan

_Authored 2026-04-29. Draft for discussion._

This memo proposes how to grow the v1 benchmark (40 scenarios, single-author gold, no IAA) into v2 (target: 200 scenarios with two-annotator gold, κ ≥ 0.6 IAA on the verdict label, κ ≥ 0.7 on the binary HDI label). It is the planning counterpart to Subsystem F's "Plan pending" status in the program plan.

## 1. v1 retrospective — what informs v2

### What v1 got right

- **Schema:** the `Scenario` + `GoldStandard` Pydantic models held up across 40 scenarios with no churn. Reuse as-is.
- **Stratified split:** 60/20/20 with entity-level leakage guard works. Reuse.
- **6-metric panel:** verdict κ, ECE, HDI recall, provenance, defer accuracy, bilingual consistency. The metric panel is research-defensible. The runner produces them correctly.
- **6 baseline systems:** the architectural-ablation framing (single_llm / single_llm_rag / yang2025 / medagents / mdagents / diet_os) is a clean comparison structure. Reuse.

### What v1 got wrong (or didn't get to)

- **Single annotator (the author).** Unmeasured IAA — paper reviewers will reject this.
- **Hand-seeded distribution.** No principled coverage of clinical scenarios beyond the author's intuition.
- **No difficulty calibration.** All 40 scenarios are mixed-difficulty; can't report difficulty-stratified accuracy.
- **No gold-quality regression suite.** When we add scenarios in v2, we have no automated check that gold labels remain internally consistent.
- **Bilingual subset n=7.** CIs on bilingual metrics will be huge at this n.
- **`defer_acc = 0.551` was a constant** across all 5 baselines — likely an artifact of constant `defer=False` predictions matching the gold rate. v2 needs to ensure the defer-label distribution is non-trivial (≥ 25% of scenarios should require deferral) so the metric discriminates.

### v1 run 4 confounds (now being addressed)

- LLM rate-limit (free-tier 20 RPM) → degraded most diet_os runs.
- kg_query empty subgraph → no KG context; addressed by Task #11 re-embed migration in flight.

These do not change v2's design, but they explain why we cannot yet read v1 results as evidence for or against architecture choices.

## 2. v2 sample size — power-based, not aspirational

The 200-scenario target in the program plan was a round number. Let's anchor it to statistics.

The headline test is the paired-bootstrap comparison of `diet_os` against each of 5 baselines on each of 6 metrics, with Bonferroni correction (α' = 0.01 per cell, 30 cells). We want ≥ 80% power to detect a meaningful effect at α' = 0.01.

For Cohen's κ and HDI Recall (both bounded [0,1] proportion-like), a difference of 0.20 between systems is "moderate" and clinically interesting. To detect Δκ = 0.20 at 80% power, α' = 0.01, paired:

| n | Detectable Δ (κ, paired bootstrap, 1000 iters) |
|---:|---|
| 40 | ~0.30 (Bonferroni-padded, wide CIs) |
| 100 | ~0.20 |
| **200** | ~0.14 |
| 400 | ~0.10 |

n=200 is right-sized to detect clinically meaningful gaps without being so large that gold-quality budget breaks. **Keep the 200 target.**

For bilingual specifically, n=7 in v1 was inadequate. v2 needs ≥ 30 bilingual scenarios for any reportable Bonferroni-adjusted bilingual claim.

## 3. v2 dataset shape — coverage matrix

200 scenarios partitioned across two axes:

### Axis A — Clinical category (rows)

| Category | Scenarios | Rationale |
|---|---:|---|
| Herbal — single-herb intervention | 50 | Most common dietitian use case; covers C1 (KG ablation) cleanly |
| Herbal — drug-herb interaction (HDI) | 40 | Highest-stakes; directly tests C1 HDI Recall against `hdi_safe_50.json` |
| Nutrition — single-nutrient | 30 | Folate, vitamin D, zinc, omega-3 cases — well-defined Cochrane evidence |
| Nutrition — dietary pattern (Mediterranean, DASH, ...) | 20 | Multi-component intervention; tests Dietitian agent's framework reasoning |
| TCM — single-herb TCM | 25 | Bilingual reasoning; tests C4 and SymMap retrieval |
| TCM — multi-herb formula (Liu Wei Di Huang Wan, ...) | 15 | Composite reasoning; harder bilingual |
| Special-population modifiers | 20 | Pregnancy, pediatric, geriatric, renal-impaired — test the Safety Reviewer |

Total: 200.

### Axis B — Difficulty (columns, applied to every category)

| Difficulty | Definition | Scenarios per category | Total |
|---|---|---:|---:|
| Easy | Single intervention, single outcome, monolingual, no special population | ~40% | 80 |
| Medium | Comparison + 1 confound (e.g., mixed evidence quality, common side effect) | ~40% | 80 |
| Hard | Multi-confound (polypharmacy / pregnancy / contradicting evidence streams) | ~20% | 40 |

This lets us report `accuracy × difficulty` heatmaps in the paper — a standard ablation that reviewers expect.

### Axis C — Defer requirement

Within the 200, 60 scenarios (30%) should have a gold defer label of `True` (e.g., "this requires a clinician's review because of pregnancy / drug interaction / lack of evidence"). Without this, `defer_acc` collapses to a constant as in v1.

## 4. Annotation protocol

### Annotator panel

- **A1 — Registered Dietitian** (RD) with ≥ 5 years clinical experience.
- **A2 — Clinical Pharmacist** (PharmD) with ≥ 5 years drug-information experience.
- **A3 — Adjudicator** (MD or senior researcher) — resolves disagreements. Only consulted when A1 vs A2 disagree by > 1 ordinal step on verdict, or differ on binary HDI/defer labels.

Both A1 and A2 annotate every scenario independently. A3 adjudicates ~10–15% based on v1 patterns.

### Annotation tool

Build (or re-use) a minimal web UI: one scenario per page, all gold-label fields next to the scenario, "submit + next" flow. A1 and A2 should never see each other's labels.

Start with the simplest viable: a Streamlit app reading scenarios from `scenarios/v2/*.json`, writing per-annotator JSON to `gold/v2/<annotator>/<scenario_id>.json`. Follow-up improvement (not blocking v2 launch): integrate with Label Studio if friction warrants.

### IAA gates (must pass before v2 ships)

| Label | Method | Target | If missed |
|---|---|---:|---|
| Verdict (4-class ordinal) | Cohen's quadratic-weighted κ | ≥ 0.60 | Adjudicate then re-measure; if < 0.50 after adjudication, redesign the verdict rubric |
| HDI binary (interaction-recommended-block? Y/N) | Cohen's κ | ≥ 0.70 | Adjudicate; if < 0.60, the HDI-Safe-50 panel categories may be ambiguous — split mechanism classes |
| Defer binary | Cohen's κ | ≥ 0.65 | Same — adjudicate, redesign |
| Bilingual concept consistency | Inter-rater agreement on TCM scenarios | ≥ 0.70 | Recruit a TCM-trained reviewer for adjudication |

Provenance and ECE are not directly annotated — they're computed from system outputs against the live KG and the gold confidence (the latter is just the annotators' label, no inter-rater calc).

## 5. Gold-label schema additions for v2

Extend `GoldStandard` with:

```python
class GoldStandard(BaseModel):
    # v1 fields preserved
    verdict: Literal["prefer", "caution", "reject", "abstain"]
    hdi_claims: list[HDIClaim]
    provenance_chains: list[ProvenanceChain]   # canonical cypher path(s)
    defer_to_clinician: bool
    bilingual_terms: list[BilingualTerm] | None

    # v2 additions
    annotator_id: Literal["A1", "A2", "A3-adjudicated"]
    confidence: Literal["low", "medium", "high"]                # annotator's certainty
    evidence_quality: Literal["A", "B", "C", "D", "expert"]     # GRADE-style overlay
    difficulty: Literal["easy", "medium", "hard"]               # explicit per-scenario
    contraindications: list[str]                                # for special-population scenarios
    references: list[str]                                       # PMIDs / Cochrane IDs supporting the verdict
```

The `references` field is critical for paper Methods: each gold verdict must cite at least one PubMed PMID or Cochrane Review ID so reviewers can audit.

## 6. Scenario authoring pipeline

1. **Seed from v1.** All 40 v1 scenarios become v2 candidates (after re-annotation by A1+A2). Likely ~30 carry over after IAA pass (some will be rejected as ambiguous).
2. **Backfill from clinical evidence sources.** For each category, sample from:
   - **Cochrane Systematic Reviews** for nutrition/intervention scenarios (open metadata; full text where licensed).
   - **NIH ODS factsheets** for nutrition single-nutrient scenarios.
   - **NCCIH herb factsheets** for herbal/HDI scenarios.
   - **TCM clinical trial registry** (ChiCTR/clinicaltrials.gov filtered to TCM) for TCM scenarios.
3. **LLM-assisted scaffolding (NOT gold).** Use a paid LLM tier to draft scenario text from the cited primary source. Annotators always treat the LLM-drafted scenario as a *suggestion* — they verify against the source PMID before approving the scenario into the dataset. LLM-generated gold labels are forbidden.
4. **Difficulty assignment.** Author and at least one annotator both tag difficulty before annotation begins. Disagreement → adjudicate as part of the IAA pass.

## 7. Quality regression suite

Every gold-label addition or change must pass these CI gates before merging:

- **Schema validation:** Pydantic strict mode on every scenario JSON.
- **Reference resolves:** every PMID / Cochrane ID is fetchable from the public APIs at CI time (cache for offline runs).
- **No leakage:** the entity-level leakage guard from v1 still passes for the new split.
- **HDI gold consistency:** every HDI claim with severity ≥ moderate must reference an entry in `hdi_safe_50.json` OR be flagged for inclusion in v2's expanded `hdi_safe_panel.json`.
- **Bilingual gold reciprocity:** every TCM scenario's English↔CN labels must round-trip through SymMap's `symmap_tcm_symptoms` table (the term either exists or has an explicit "novel" tag with a PMID source).
- **Difficulty-stratified power:** per-category scenario count meets the §3 distribution within ±10% before merging; CI fails if a category is under-filled.

## 8. Effort and timeline

| Phase | Deliverable | Estimate |
|---|---|---|
| **Author/scaffold** | 200 candidate scenario JSONs, source-cited, LLM-drafted, author-reviewed | 3–4 weeks |
| **Annotate (A1 + A2 independently)** | ~6 hours/100 scenarios per annotator at clinical pace | 2–3 weeks calendar (parallel) |
| **Adjudicate (A3)** | Resolve ~10–15% disagreements | 1 week |
| **IAA measurement + redesign loops** | Iterate until gates pass | 1–2 weeks (allow for one redesign) |
| **Annotation tooling** | Minimal Streamlit UI + reference cache | 3 days |
| **Quality regression suite** | CI gates per §7 | 1 week |
| **Paper Methods section update** | Document the protocol, the IAA results, the difficulty distribution | 1 week |
| **Total** | **~3 months calendar, 1.5 person-months effort** | |

This is consistent with the Subsystem F "4–5 weeks (half spent on annotation + IAA)" estimate — the annotators do the bulk of the work in parallel.

## 9. Decision points (need user input before §6 begins)

1. **Annotator recruitment.** Are A1 (RD) and A2 (PharmD) already lined up, or does this need a contractor budget? (Typical clinical annotator rate: $100–150/hour. 200 scenarios × 6 minutes each × 2 annotators ≈ 40 hours total ≈ $4–6K total. Adjudication adds ~$1K.)
2. **Annotation tool.** Streamlit MVP vs. Label Studio integration. MVP is faster; Label Studio is more rigorous but adds 1–2 weeks of integration work. Default to MVP unless reviewer protocol requires Label Studio's audit trail.
3. **Source license check.** Cochrane full-text and NCCIH content have specific reuse terms. Plan assumes we cite + summarize, not redistribute. Confirm with legal before publishing the dataset.
4. **Reference cache budget.** Caching PMIDs at CI time costs nothing (NCBI APIs are free); Cochrane API access requires institutional login. If we don't have access, fall back to citing the Cochrane ID without the abstract text.
5. **TCM-bilingual annotator.** A1 (RD) likely doesn't read Chinese clinical literature. We need either A2 to be bilingual, or A3 (adjudicator) to be a TCM-trained reviewer. If neither, recruit a fourth annotator A4 for the 40 TCM scenarios specifically.

## 10. v2 launch criteria (definition-of-done)

- [ ] 200 scenarios in `research-journal/shared/datasets/dietbench_clinical_v2.json`, schema-valid.
- [ ] All §7 quality gates green in CI.
- [ ] IAA reports archived: `gold/v2/iaa-report.md` showing each label's κ.
- [ ] Difficulty distribution within ±10% of §3 targets.
- [ ] Splits regenerated: `splits_v2_seed42.json`.
- [ ] v1 → v2 migration note in `research-journal/shared/2026-04-29-v2-benchmark-expansion.md` (this doc) updated with final stats.
- [ ] Paper Methods section drafted with: protocol, IAA results, difficulty distribution, ablation plan against the 6 baselines.

## 11. What v2 does *not* address

- **System architecture changes.** v2 is an evaluation-quality upgrade, not an architecture change. Any system improvements (Aura vector storage, paid LLM tier, panel role tuning) are tracked separately.
- **Paper writing.** Methods section is bundled with v2 because the protocol is the dataset; Results, Discussion, Limitations are downstream.
- **Companion-paper γ.** The companion benchmark/resource paper builds on v2 but is its own scope (Subsystem G.2).

## 12. Recommended sequencing

Given the parallel re-embed migration (Task #11) is now in flight and v1 eval has the rate-limit blocker, the sensible sequence is:

1. **Now → 1 week:** finish §6 scaffold + Streamlit MVP. Author 50 of 200 scenarios as a pilot.
2. **Week 1–2:** A1 + A2 annotate the 50 pilot scenarios. Compute IAA on the pilot.
3. **Decision point:** if pilot IAA < 0.5, redesign rubric before scaling to 200. If ≥ 0.5, scale.
4. **Week 2–8:** complete the remaining 150 + adjudicate.
5. **Week 8–10:** quality gates + splits + Methods section.

This is consistent with the program plan's "4–5 weeks" Subsystem F estimate but spreads it across calendar time to allow annotators to work at clinical pace.
