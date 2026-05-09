<!-- harden-plan: hardened on 2026-05-08T22:00:00Z. Live data probed; unit table verified. -->

# Diet Scoring Function — Plan (HARDENED)

**Goal:** Composable diet→effect scoring pipeline. Produces ranked targets/pathways/diseases for a given (food, grams) list by aggregating exposure over the KG's evidence layers.

**Tech:** Python 3.10+ pure stdlib + sqlite3.

**Stacks on:** PR #27 (Phase 4).

**Probe results:**
- 962 foods in compound_foods, dominantly `mg/100g` units
- compound_disease_evidence has 2.92M rows (Phase 3)
- compound_targets has 7K (CMAUP, Phase 0)
- KEGG layer has 455 pathway-target joins
- compound_identity is empty schema only — `COMPOUND_IN_PATHWAY` lazy contribution remains 0 until Phase 1 ingest runs

---

## File map

**Created:**
- `shrine-diet-bioactivity/lightrag/unit_normalizer.py` — pure unit conversion
- `shrine-diet-bioactivity/lightrag/diet_scorer.py` — core scoring algorithm
- `shrine-diet-bioactivity/scripts/score_diet.py` — CLI
- `shrine-diet-bioactivity/lightrag/tests/test_unit_normalizer.py`
- `shrine-diet-bioactivity/lightrag/tests/test_diet_scorer.py`
- `shrine-diet-bioactivity/lightrag/tests/test_diet_scorer_live.py`
- `docs/adr/0010-diet-scoring.md`

**Modified:**
- `shrine-diet-bioactivity/Makefile` — `score-diet-sample` smoke target
- `shrine-diet-bioactivity/lightrag/tests/test_kg_completeness_gates.py` — Phase 5 gate
- `docs/{ARCHITECTURE,KG_COMPLETENESS_AUDIT,INDEX,DATASET_PROVENANCE}.md`

---

## Task 1: unit_normalizer (pure logic)

- RED: tests covering each unit type (mg/100g, mg/100 g variants, mg/kg, unsupported uM/IU/etc)
- GREEN: `to_mg_per_gram(value, unit) -> Optional[float]` returns None for unsupported units (caller emits warning)
- Test invariants: monotonic in value; no negative output; unsupported returns None deterministically

## Task 2: diet_scorer core (pure logic, fed by SQL helpers)

- RED: tests covering Stage 1 (exposure aggregation), Stage 2 (per-layer fan-out), Stage 3 (roll-up + ranking), edge cases (empty diet, missing food, negative grams, unit mismatch)
- GREEN: stateless functions:
  - `aggregate_exposures(diet, compound_foods_rows) -> dict[compound_id, mg_total] + warnings`
  - `score_targets(exposures, compound_targets_rows) -> ranked list`
  - `score_diseases(exposures, compound_disease_evidence_rows) -> ranked list with breakdown`
  - `score_pathways(exposures, compound_identity_rows, kegg_compound_pathways_rows, kegg_pathway_genes_rows, target_scores) -> ranked list`
  - Top-level `score_diet(diet, conn) -> dict` orchestrates with SQL queries

## Task 3: score_diet.py CLI

- accepts `--diet '<json>'` or `--diet-file <path>`
- writes JSON to stdout (with `disclaimer` field)
- exit 0 on success, 2 on bad input, 3 on DB missing

## Task 4: Live-DB integration test

- 3-food sample (`Turmeric: 5, Ginger: 10, Broccoli: 100`) → expect non-empty exposures, ≥1 ranked target, ≥1 ranked disease
- Verify warnings list is reasonable

## Task 5: Audit-gate

- `test_diet_scoring_end_to_end`: runs scorer on the sample diet, asserts shape + non-empty outputs

## Task 6: Docs

- ADR 0010 (algorithm + weight rationale)
- ARCHITECTURE: add scoring sequence diagram
- INDEX, DATASET_PROVENANCE, AUDIT closeout

## Task 7: Lint, commit, PR stacked on #27
