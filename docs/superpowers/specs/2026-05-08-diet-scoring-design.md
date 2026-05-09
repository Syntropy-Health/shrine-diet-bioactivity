# Diet Scoring Function — Design

**Status:** Draft v1 — pending user approval
**Date:** 2026-05-08
**Owner:** mymm.psu@gmail.com
**Related run:** `.claude/runs/20260508-diet-scoring/`
**Stacks on:** PR #27 (Phase 4 — KEGG pathway overlay)

## 1. Objective

Take a recorded diet (foods + portions) and produce predicted physiological-effect scores by aggregating the bioactive-compound exposures over the KG's evidence layers. Closes the last open audit doneness criterion (§5.4 use case D — *"aggregate scoring function published in a spec, with regression test"*).

The scoring function is the **read-side capstone** of Phases 0–4. It composes every edge type the project has built into one numeric output the agent layer can rank, filter, and explain.

## 2. Use case

```python
diet = [
    ("Turmeric", 5),       # 5 g of turmeric in a curry
    ("Ginger", 10),
    ("Broccoli", 100),
    ("Olive oil", 15),
]
result = score_diet(diet, conn=db_connection)
# →
# {
#   "exposures": {              # mg of each bioactive compound consumed
#     "curcumin": 14.4,
#     "gingerol": 8.2,
#     ...
#   },
#   "targets": [                # ranked target modulation
#     {"target": "NF-kappa-B p65", "score": 87.3, "evidence_count": 12,
#      "top_compounds": ["curcumin", "gingerol"]},
#     ...
#   ],
#   "pathways": [               # ranked pathway modulation
#     {"pathway": "NF-kappa B signaling pathway", "kegg_id": "hsa04064",
#      "score": 145.6, "n_targets_hit": 7},
#     ...
#   ],
#   "diseases": [               # ranked disease association
#     {"disease": "Inflammation", "mesh_id": "D007249",
#      "score": 92.1, "evidence_breakdown": {"direct_therapeutic": 3,
#      "direct_marker": 1, "inferred_via_gene": 18, "pubmed_total": 47}},
#     ...
#   ],
#   "warnings": ["Olive oil: 0 compounds in compound_foods", ...]
# }
```

## 3. Non-goals

- **Not** a clinical diagnostic tool. Output is a research-aid prediction, not medical advice.
- **Not** a recipe analyzer. Inputs are individual foods; recipe decomposition (e.g. "cup of pasta sauce") is the agent layer's job.
- **Not** time-series modeling. No acute-vs-chronic distinction, no metabolism kinetics.
- **Not** bioavailability-corrected. Compound exposure is naive (mg consumed = mg modulating); the corrective factor would need pharmacokinetics modeling we don't have data for.
- **Not** an MCP tool. The thin-adapter architecture (per `src/tools.ts`) forbids use-case verbs. Diet scoring is invoked by the agent layer via SQL or via a separate REST endpoint — out of scope for this PR.

## 4. Architecture

### 4.1 Three pure-logic modules, one CLI

```
lightrag/
├── diet_scorer.py          # core: aggregate exposures, score targets/pathways/diseases
└── unit_normalizer.py      # normalize compound_foods.content_unit → mg/g

scripts/
└── score_diet.py           # CLI: takes JSON input, returns JSON output
```

### 4.2 Algorithm — three stages

**Stage 1: Compound exposure.**

For each `(food_name, grams_consumed)` in the diet:
- Look up `compound_foods` rows for the food (exact name match; food name fuzzy-match is a Phase 5.5 follow-up).
- For each row, normalize `(content_value, content_unit)` to `mg per gram` of food.
- Compute `compound_exposure_mg = grams_consumed × mg_per_gram`.
- Aggregate per `compound_id` across all foods in the diet.

Unit-normalization table (per probe of live `compound_unit` distribution):

| `content_unit` | `mg per g` factor | Notes |
|---|---:|---|
| `mg/100g`, `mg/100 g`, `mg/100 g of dry matter`, `mg/100 g freshweight` | `value / 100` | dominant; ~67K rows |
| `mg/kg` | `value / 1000` | ~100 rows |
| `uM`, `IU`, `α-TE`, `RE`, `NE` | unsupported (would need MW) | ~3K rows; emit warning, skip row |

**Stage 2: Target / pathway / disease fan-out.**

For each compound in the exposure map, compute contributions to:

| Layer | Source table | Weight | What |
|---|---|---:|---|
| Direct targets | `compound_targets` | 1.00 | CMAUP-curated direct binding |
| Direct therapeutic disease | `compound_disease_evidence` (type='direct_therapeutic') | 0.90 | CTD direct-evidence treatment |
| Direct marker disease | `compound_disease_evidence` (type='direct_marker') | 0.70 | CTD biomarker relationship |
| Inferred disease via gene | `compound_disease_evidence` (type='inferred_via_gene') | 0.50 | CTD inference + score boost |
| KEGG pathway membership | `kegg_compound_pathways` (via `compound_identity`) | 0.60 | indirect pathway clustering (lazy: 0 today) |

**Aggregation per (compound, target/pathway/disease) row:**

```
score = compound_exposure_mg × evidence_weight × citation_factor
```

Where `citation_factor = 1 + log10(1 + n_pubmed)` for the disease layer (cap at 3.0).

**Stage 3: Roll-up + ranking.**

For targets: sum scores per target across all contributing compounds. Annotate with top contributing compounds.

For pathways: sum scores per pathway via `kegg_pathway_genes` membership. Annotate with `n_targets_hit`.

For diseases: sum scores per `disease_id` across all evidence types. Break out `evidence_breakdown` by type + total PubMed citation count.

Sort each output list by score descending, top 20.

### 4.3 Edge cases

- **Food not in `compound_foods`**: emit warning, skip that food (no exposure contribution).
- **Compound has no targets/diseases/pathways**: it contributes to the exposure map but not the output rankings.
- **Unit unsupported**: skip the specific row (not the whole food); emit warning.
- **Diet input has duplicate foods**: aggregate (sum the grams).
- **Negative grams**: reject with `ValueError`.

## 5. Definition of Done

- `lightrag/diet_scorer.py` + `lightrag/unit_normalizer.py` exist with ≥80% coverage
- `score_diet({"Turmeric": 5, "Ginger": 10})` returns a non-empty `targets` list with at least one MeSH-anchored disease in `diseases`
- `score_diet([])` returns empty exposures + empty rankings (no crash)
- Each unsupported `content_unit` produces exactly one `warnings` entry per encounter
- Citation-factor formula is unit-tested in isolation
- CLI `python scripts/score_diet.py --diet '{"Turmeric":5}' --db data_local/...` writes JSON to stdout
- ADR `0010-diet-scoring.md` documents the algorithm + weight choices
- New audit-gate test runs the scorer end-to-end against a 3-food diet and asserts non-empty outputs
- `docs/ARCHITECTURE.md` updated with a Mermaid sequence diagram of the scoring flow

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Score weights are subjective | Document rationale in ADR; weights are constants — single-place tuning |
| Food-name exact match misses ~50% of plausible matches | Phase 5.5 spec for fuzzy match (out of scope here); CLI emits warnings on miss |
| Compound exposures dominated by mass-poor herbs vs nutrient-rich foods | Document in ADR; aggregation is per-target so a heavy bell pepper won't drown out a potent turmeric compound at the target level |
| Score is dimensionless and non-comparable across runs | Document explicitly; agent layer treats scores as ordinal not cardinal |
| Numbers may "look authoritative" to end-users | All output JSON includes a `disclaimer` field flagging research-only |
| Unit-normalization wrong for a corner case | Strict validation + per-row warnings; we never silently use a row we can't normalize |

## 7. Phase 5.5 candidates (out of scope here)

- Fuzzy food-name matching (e.g. "olive oil" → "Olive oil" if case-only difference; "extra virgin olive oil" → "Olive oil" partial match)
- Bioavailability correction using compound class
- Time-series weighting (acute peak vs chronic intake)
- Cross-compound synergy modeling
- Confidence intervals on scores via bootstrap
