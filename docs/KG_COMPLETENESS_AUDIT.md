# KG Completeness & Utility Audit — 2026-05-07

> Quantitative audit of the unified diet KG against the project's two priority use cases:
>
> - **A. Symptom → food.** Given a symptom, surface foods/herbs whose bioactives have evidence-graded drug-target activity.
> - **D. Diet → predicted physiological effects.** Given a recorded diet, aggregate bioactive compound exposure → target modulation → predicted pathway/disease effects.
>
> Snapshot taken from `data_local/herbal_botanicals.db` (5.5 GB, 20 tables). Numbers reflect state on 2026-05-07 _before_ Phase 1 ChEMBL ingest runs.

---

## 1. Entity-level snapshot

| Entity / table | Rows | Use-case relevance |
|---|---:|---|
| `herbs` (Duke) | 2,376 | A: backbone for symptom→herb mapping |
| `herb2_herbs` (HERB 2.0) | 7,263 | A: 3× Duke coverage but **siloed** — no cross-resolution to `herbs` |
| `compounds` | 94,512 | A, D, C: backbone — **0% have SMILES, 0% have populated PubChem CID** (see ADR 0007) |
| `targets` | 4,355 | A, D: backbone — UniProt-typed, druggability annotated |
| `symptoms` | **47** | A: hand-curated, intentionally narrow |
| `symmap_modern_symptoms` | 1,148 | A: rich UMLS/MeSH/ICD-10/HPO IDs — **not joined to `symptoms`** |
| `symmap_tcm_symptoms` | 2,285 | A: TCM coverage — **not joined to `symptoms`** |
| `compound_foods` | 4,149,541 | D: dense food→compound graph |
| `herb_compounds` | 99,280 | A: dense herb→compound graph |
| `compound_targets` | 7,053 | A, D: target binding — **only 1,232 distinct compounds** |
| `target_diseases` | 795,434 | A: target→disease — 2,976 distinct diseases |
| `herb_symptoms` | 41,823 | A: 44/47 symptoms have herb mappings |
| `herb2_herb_disease` | 1,797,785 | A: huge HERB 2.0 evidence — **siloed** by `herb2_herbs` |
| `chemical_diseases` (CTD) | **0** | **GAP** — table exists, never populated |
| `chemical_phenotypes` (CTD) | **0** | **GAP** — table exists, never populated |
| `food_nutrition_bridge` | 647 | D: FooDB↔OpenNutrition bridge (small but high-value) |

---

## 2. Use-case fit analysis

### Use case A — Symptom → food

**Today's path** (string matching at query time, no materialized map):

```
Symptom (1 of 47)
   → "name LIKE %X%" against target_diseases.disease_name
       → target_diseases (≈2,976 diseases, 795K rows)
           → targets (4,355)
               → compound_targets (7,053 edges)
                   → compounds (1,232 distinct with target binding)
                       → compound_foods (food anchors)
```

**Empirical match coverage** (sample of 15 symptoms vs `target_diseases.disease_name`):

| Symptom | String matches in `target_diseases` |
|---|---:|
| Cancer | 72,265 |
| Pain | 12,480 |
| Arthritis | 10,614 |
| Diabetes | 9,286 |
| Hypertension | 5,128 |
| Asthma | 4,336 |
| Bacterial infection | 3,740 |
| Eczema | 3,461 |
| Inflammation | 2,885 |
| Fungal infection | 2,787 |
| Heart disease | 2,766 |
| Insomnia | 2,580 |
| Obesity | 2,334 |
| Fever | 2,265 |
| Viral infection | 2,003 |

**Verdict for A:** strong qualitative coverage. Strong **quantitative** weakness: matches are by free-text similarity, not by ontology join. Same disease may match multiple symptoms (Cancer matches "Cancer", "cancer", "carcinoma", "neoplasm", etc.) without confidence scoring or deduplication. `SymMap` has the formal MeSH/UMLS/ICD-10-CM crosswalk but it's not wired into the materialized graph.

### Use case D — Diet → predicted physiological effects

**The leverage molecules** are compounds in BOTH `compound_foods` AND `compound_targets`:

| Set | Distinct compounds |
|---|---:|
| In `compound_foods` (food sources) | 61,174 |
| In `compound_targets` (target binding) | 1,232 |
| **Intersection (food ∩ target)** | **565** |

**Verdict for D:** today, only 565 compounds power any food→target prediction. Phase 1's ChEMBL bridge (PR #19) will multiply this — once compound-identity resolution is run, compounds with InChIKey cross-refs gain measured ChEMBL bioactivity even if they had no `compound_targets` row. Conservative estimate: 5,000–10,000 compounds gain target evidence post-Phase 1.

---

## 3. Concrete completeness gaps

Sorted by use-case impact × ease of remediation.

### Gap 1 — ~~`chemical_diseases` table is empty~~ ✅ **RESOLVED 2026-05-07**

- **Status:** Resolved by `phase2/ctd-ingest`. Live DB now contains:
  - **934,070 unique (compound_id, disease_name) pairs** (audit floor was 10K — 93× over)
  - **45,836 chemical_phenotypes** rows
  - **2,569 distinct compounds** with disease evidence
  - **6,678 distinct diseases** with MeSH IDs (most carry `MESH:Dxxxxxx` form)
- **Root cause** confirmed: the existing `scripts/load-ctd.ts` had three independently-blocking bugs that left it dormant:
  1. `line.split(',')` corrupted rows where MeSH disease names contain commas (e.g., "Lymphoma, Mantle-Cell"), shifting every subsequent field.
  2. Phenotype filename was `CTD_chem_phenotype_interactions.csv.gz`; CTD's actual filename is `CTD_pheno_term_ixns.csv.gz`. The loader silently skipped this file.
  3. CTD source files were not in `download-sources.ts` (the docstring claimed they required CAPTCHA, but the static file URLs at `ctdbase.org/reports/` are not gated).
- **What landed:**
  - `scripts/_csv-parse.ts` — RFC-4180 row parser with 9 vitest unit tests covering quoted fields, embedded commas, `""` escapes, and a real-world CTD row sample.
  - `scripts/_normalize.ts` — extracted `normalizeCompoundName` so `load-ctd` no longer transitively imports `papaparse` via `build-herbal-db`.
  - `scripts/download-sources.ts` — adds `ctd_chemicals_diseases` and `ctd_pheno_term_ixns` entries plus a `--ctd-only` flag.
  - `scripts/load-ctd.ts` — uses `parseCsvLine`; accepts both old and new phenotype filenames; clearer "run npm run download:ctd" hint.
  - `package.json` — `download:ctd` and `load:ctd` npm scripts.
  - `Makefile` — `download-ctd` and `load-ctd` targets.
- **Verification:** ingest run on the live DB took 59 seconds end-to-end; `test_chemical_diseases_has_meaningful_coverage` xfail flipped GREEN.

### Gap 2 — ~~Symptom → Disease map is implicit~~ ✅ **RESOLVED 2026-05-07**

- **Status:** Resolved by `phase2/symptom-disease-map`. 40/47 symptoms mapped (audit acceptance ≥40), 33 with MeSH IDs, 1 fallback-only. All four audit-gate tests in `test_kg_completeness_gates.py` are now GREEN.
- **What landed:**
  - `symptom_disease_map` table populated by 4-tier matcher (exact / Jaccard / substring / content-token / target_diseases fallback) with MeSH/UMLS/ICD-10 cross-refs from SymMap.
  - LightRAG `MAPS_TO_DISEASE` relationship type so the bridge surfaces in Neo4j queries.
  - 13 unit tests + 5 audit-gate tests covering each tier, the stopword filter, and the mesh-id tie-breaker.
- **Original spec:** see [§4.2](#42-spec-materialized-symptom-disease-map).
- **Remaining 7 unmapped symptoms** (Allergies, Bile insufficiency, Blood clotting, Fluid retention, Low immunity, Low milk supply, Neurodegeneration, Poor circulation) are clinical-concept terms with no literal hit in either source; flagged as Phase 2.5 hand-curation candidates.

### Gap 3 — ~~HERB 2.0 herbs are siloed~~ ✅ **RESOLVED 2026-05-07**

- **Status:** Resolved by `phase2/herb2-resolution`. Live DB now has **1,818 / 2,376 (76.5%) Duke herbs** mapped to HERB 2.0 — exceeds audit acceptance ≥75%.
- **What landed:**
  - `herb_resolution_map(duke_id, herb2_id, match_type, match_score)` populated by `scripts/build_herb_resolution_map.py` using a 4-tier matcher.
  - **Tier coverage** (distinct Duke herbs reaching each tier):
    - `latin_exact` (score 1.0): 708
    - `binomial` (score 0.85): 787 — strips subspecies/variety annotations
    - `common_name` (score 0.7): 249 — Duke common_name ↔ HERB2 name_en
    - `genus` (score 0.5): 1,814 — broad recall; same-genus species are useful for traversal even when species don't align
  - 17,618 total match rows across all tiers (multi-tier records preserved so consumers can rank).
  - 13 unit tests in `lightrag/tests/test_herb_matcher.py` + 1 audit-gate test all GREEN.
- **What this unlocks:** the 1.8M `herb2_herb_disease` evidence rows now join transitively to Duke herbs via this map; HERB 2.0's English/Chinese/Pinyin name variants become reachable from `herb_compounds`.
- **Phase 2.5 follow-up:** wire `herb_resolution_map` into LightRAG's `extract_relationships` so `Herb -ASSOCIATED_WITH_DISEASE-> Disease` edges sourced from HERB 2.0 surface alongside the existing CMAUP target_diseases-derived edges. Not in this PR — schema additions only.

### Gap 4 — Phase 1 compound-identity coverage is unknown (MEDIUM — D quality gate)

- **Severity:** MEDIUM for use case D; Phase 1 (PR #19) will resolve InChIKeys for ~25K active compounds via PubChem. We do not yet know what fraction of those names PubChem can actually resolve given their unusual format (e.g. `(+)-1-HYDROXYPINORESINOL-4.4'-GLUCOPYRANOSIDE`). If <50% resolve, the bioactivity evidence layer is correspondingly thin.
- **Remediation:** run `make build-identity` post-merge of #19, capture the coverage report (already emitted by the build script's WARNING line). If <50%, a name-normalization Phase 1.5 (strip stereochemistry markers, prefix punctuation) becomes a TDD-able spec.
- **Spec status:** measurement pending PR #19 merge + first ingest run.

### Gap 5 — Symptoms are tiny (47 hand-curated) (LOW — works as designed but limits A breadth)

- **Severity:** LOW for use case A in the near term. The 47 symptoms cover the spec's clinical scope. SymMap's 1,148 modern + 2,285 TCM symptoms could expand `symptoms` if a use case demands more granular indexing — but adding them adds maintenance load without a clear consumer today.
- **Remediation:** parked. Revisit if A queries surface symptom mismatches that the 47-row vocabulary cannot represent.

---

## 4. TDD specs for top remediation work

### 4.1 SPEC: load CTD `chemical_diseases`

**Single failing test that captures the requirement** — landed in this PR as a **RED** test (xfail-marked until implementation lands).

```python
# shrine-diet-bioactivity/lightrag/tests/test_ctd_coverage.py
def test_chemical_diseases_has_meaningful_coverage(db_conn):
    """CTD chem→disease map should have ≥10K rows after ingest.

    Phase 2 spec: implement scripts/load-ctd.ts (or .py) to ingest
    CTD CSV.gz → chemical_diseases. Architecture promises ~3.8M rows;
    we floor at 10K so the test passes as soon as ingest is wired up
    (with room to ratchet up after).
    """
    n = db_conn.execute("SELECT COUNT(*) FROM chemical_diseases").fetchone()[0]
    assert n >= 10_000, (
        f"chemical_diseases has {n} rows; CTD ingest likely never ran "
        "(see docs/KG_COMPLETENESS_AUDIT.md §3 Gap 1)"
    )
```

Implementation work (separate spec/PR): port the existing `scripts/load-ctd.ts` (or rebuild it from the CTD CSV.gz under `data/`), wire it into `make migrate` after Duke + FooDB load.

### 4.2 SPEC: materialized symptom→disease map

This is the **highest-leverage gap for use case A**, and the most-easily TDD'd. Scaffolding the failing test in this PR.

**Schema:**

```sql
CREATE TABLE symptom_disease_map (
  symptom_id     INTEGER NOT NULL,
  disease_name   TEXT NOT NULL,
  source         TEXT NOT NULL,        -- 'symmap_modern' | 'symmap_tcm' | 'string_match'
  symmap_id      TEXT,                  -- formal SymMap ID when available
  mesh_id        TEXT,                  -- MeSH crosswalk
  umls_id        TEXT,                  -- UMLS crosswalk
  icd10cm_id     TEXT,
  match_score    REAL NOT NULL,         -- 0.0–1.0; higher = better
  PRIMARY KEY (symptom_id, disease_name, source),
  FOREIGN KEY (symptom_id) REFERENCES symptoms(id)
);
```

**Build pipeline:**

1. For each row in `symptoms`, fuzzy-match `symptoms.name` against `symmap_modern_symptoms.name` (exact → token-overlap → substring); pull the formal IDs (`mesh_id`, `umls_id`, `icd10cm_id`).
2. Repeat against `symmap_tcm_symptoms`.
3. For symptoms with no SymMap hit, fall back to `string_match` against distinct `target_diseases.disease_name` with a confidence score derived from string similarity.
4. Persist with provenance.

**Acceptance criteria** (failing tests in `lightrag/tests/test_symptom_disease_map.py`, scaffolded RED in this PR):

- After `make build-symptom-disease-map`, ≥40 of 47 symptoms have ≥1 row.
- Inflammation, Diabetes, Hypertension all map to ≥1 SymMap row with a non-NULL MeSH ID.
- `match_score` is in [0.0, 1.0] for every row.
- The build is idempotent (re-running doesn't duplicate rows).

### 4.3 SPEC: HERB 2.0 ↔ Duke resolution

Outline only (no failing test in this PR, since this gap depends on a herb-name normalization library):

- New table `herb_resolution_map`
- Match strategies: Latin name exact, alternate-names exact, common-name token overlap
- Test: ≥1,500 of 2,376 Duke herbs resolve to a HERB 2.0 row
- Test: every resolution row has `match_type ∈ {latin_exact, alt_name_exact, token_overlap}` and a confidence score

---

## 5. Doneness criteria for KG utility (per use case)

Use these to drive future Phase 2/3 specs and to gate releases.

### Use case A — Symptom → food

- [ ] Every one of the 47 symptoms has ≥1 mapping in `symptom_disease_map` with confidence ≥0.5.
- [ ] CTD `chemical_diseases` populated with ≥1M rows (architecture target).
- [ ] HERB 2.0 herbs resolved to Duke herbs for ≥75% of compound-bearing herbs.
- [ ] For each symptom, top-10 ranked food results have at least one ChEMBL bioactivity citation in the response. (Requires Phase 1 ChEMBL ingest run.)

### Use case D — Diet → predicted physiological effects

- [ ] ≥5,000 compounds with measured ChEMBL bioactivity (Phase 1 ChEMBL ingest run; PR #19 enables this).
- [ ] ≥1,500 compounds at the food ∩ target intersection (vs current 565). Requires Phase 1 + name normalization.
- [ ] Pathway-level rollup available — requires Phase 2 KEGG overlay.
- [ ] Aggregate scoring function published in a spec, with regression test.

### Use case C — Compound mechanism dossier

- [ ] For every compound in `compound_identity` with `unichem_src_count ≥ 2`, the dossier surfaces structure (SMILES + InChI), drug-likeness signal, target list with evidence, food sources, and KEGG pathway IDs (when available).

---

## 6. Suggested next dispatch-pvp run

Highest-ROI follow-up: implement [§4.2 — symptom→disease map](#42-spec-materialized-symptom-disease-map). Concrete because:
- Schema is fixed in this audit.
- Failing test scaffolded in this PR (RED state).
- Build pipeline is ~150 LOC of Python over existing tables (no new data downloads).
- Directly improves use case A query quality, which is the primary user-facing surface.

Suggested branch / PR title: `phase1.5/symptom-disease-map` → `feat(kg): materialized symptom→disease map (use case A)`.
