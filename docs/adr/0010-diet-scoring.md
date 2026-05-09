# ADR 0010: Diet Scoring Function

**Date:** 2026-05-08
**Status:** Accepted
**Deciders:** dispatch-pvp run `20260508-diet-scoring`
**Related:** ADR 0007–0009 (the data layers this function composes)

## Context

After Phases 0–4 built the data scaffolding (compound identity, symptom→disease map, CTD evidence, disease canonical, KEGG pathways), the audit's last open doneness criterion (§5.4) was *"aggregate scoring function published in a spec, with regression test."*

Diet scoring is the **read-side capstone**: it turns a list of `(food_name, grams)` into ranked predictions of which targets/pathways/diseases are likely modulated. Every edge type Phases 0–4 built feeds into the final score.

## Decision

Pure-logic Python module (`lightrag/diet_scorer.py` + `lightrag/unit_normalizer.py`) with a CLI entrypoint (`scripts/score_diet.py`). Three-stage algorithm:

```
Stage 1 — Per-food unit normalization → mg/g exposure aggregated per compound
Stage 2 — Fan out to targets / diseases / pathways via per-layer evidence weights
Stage 3 — Roll up + rank, top-N per output category
```

### Evidence weights (single-place tuning)

| Layer | Weight | Rationale |
|---:|---:|---|
| Direct compound→target binding (CMAUP) | **1.00** | Gold-standard direct binding; unambiguous mechanism |
| Direct therapeutic (CTD) | 0.90 | Treatment relationship from curated direct evidence |
| Direct marker (CTD) | 0.70 | Biomarker — informative but doesn't imply causation |
| Inferred via gene (CTD) | 0.50 | Gated by upstream InferenceScore; non-zero is meaningful |
| KEGG pathway membership | 0.60 | Indirect pathway clustering; lazy until Phase 1 ingest runs |

### Citation factor

For the disease layer, score gets a logarithmic boost based on PubMed citation count:

```
citation_factor(n) = min(1 + log10(1 + n), 3.0)
```

Capped at 3.0 so heavy-cited diseases (Cancer, Inflammation — thousands of citations) don't dominate the rank entirely.

### Output

JSON dict with: `exposures` (per-compound mg consumed), `targets` (top-20 ranked), `diseases` (top-20 with evidence breakdown), `pathways` (top-20 with target-hit count), `warnings` (unmappable foods / unsupported units), `disclaimer` (research-only flag).

## Live-DB outcome

Sample diet `{Turmeric: 5g, Ginger: 10g, Broccoli: 100g}` produces:

- Multiple compound exposures (turmeric and ginger are compound-rich)
- Top-ranked diseases include Liver Cirrhosis, Mammary Neoplasms, Hepatocellular Carcinoma, Prostatic Neoplasms, Hypertension — all with thousands of PubMed citations and full evidence breakdowns (direct_therapeutic + direct_marker + inferred_via_gene)
- Each entry carries the `disclaimer` field flagging research-only

## Alternatives considered

- **MCP tool with use-case verb (`score-diet`).** Rejected — violates the project's `FORBIDDEN_USECASE_VERBS` thin-adapter constraint. The scorer is a Python library; agent layers wrap it.
- **Bioavailability-corrected scoring.** Rejected for v1 — no per-compound pharmacokinetics data; would require a new ingest. Would change the per-compound weight, not the algorithm shape — clean to add later.
- **Time-series modeling (acute vs chronic intake).** Rejected — would require multi-day diet inputs and metabolism kinetics. The current naive "mg consumed = mg modulating" is the simplest correct baseline.
- **Fuzzy food-name matching.** Deferred to Phase 5.5. Today, missing-food rows produce a warning and are skipped; this is preferable to silent partial matches that could be wrong.
- **Linear weighting via ML training.** Rejected — no training set; weights come from author judgment + ADR documentation. Future work: learn weights from a labeled diet→outcome dataset if one exists.

## Consequences

- **Wins:**
  - Use case D doneness criterion (§5.4) now satisfied; the entire audit is closed.
  - Single Python module ties together every Phase 0–4 edge layer.
  - Output is research-explainable: each ranked entry carries its evidence chain.
  - CLI ships immediately; no MCP surface needed (clean separation per thin-adapter constraint).
- **Trade-offs:**
  - Scores are dimensionless and **ordinal only** — comparable within one run, not across runs. The disclaimer field flags this explicitly.
  - Weights are author judgment, not data-derived. Single-place constants (`EVIDENCE_WEIGHTS` dict) make tuning trivial; ML-learned weights are future work.
  - Compounds with no targets/diseases/pathways contribute to `exposures` but not to rankings — that's correct behavior but produces some "silent" food-compound pairs.
  - `COMPOUND_IN_PATHWAY` contribution remains 0 until Phase 1 ingest runs (via `compound_identity.kegg_compound_id` lookup). Pathway ranking still works through the `target_score → kegg_pathway_genes` join.

## Algorithmic invariants

- **Idempotent scoring:** same diet + same DB → bit-exact same output.
- **Monotonic in exposure:** doubling grams of one food doubles its exposure contribution (linear in mg).
- **Score weights bounded:** every output score ≥ 0; no negative-evidence subtraction in v1.
- **Top-N cap:** outputs are capped at 20 per category to keep response payloads manageable.

## Reproducibility

- Live run: `make score-diet-sample`
- Sample diet: `{"Turmeric":5,"Ginger":10,"Broccoli":100}`
- Output is a deterministic function of `(diet, db_state)` — no RNG, no time-dependence beyond the SQL state.

## Related

- Spec: `docs/superpowers/specs/2026-05-08-diet-scoring-design.md`
- Plan: `.claude/runs/20260508-diet-scoring/plan.md`
- Audit closeout: `docs/KG_COMPLETENESS_AUDIT.md` Phase 5 section
