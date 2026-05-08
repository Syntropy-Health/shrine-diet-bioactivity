# Disease Canonicalization — Design

**Status:** Draft v1 — pending user approval
**Date:** 2026-05-08
**Owner:** mymm.psu@gmail.com
**Related run:** `.claude/runs/20260508-disease-canonicalization/`
**Stacks on:** PRs #19, #20, #21, #22, #23 (Phase 1 + Phase 2 audit closeout)

## 1. Objective

Promote `Disease` to a first-class unified entity in the KG, replacing the three independent free-text disease columns (`chemical_diseases.disease_name`, `target_diseases.disease_name`, `symptom_disease_map.disease_name`) with a single canonical registry joinable by formal MeSH/UMLS/ICD-10 IDs across all sources. Re-encode CTD's chemical-disease evidence into a typed schema that preserves PubMed citations and gene-symbol inference paths that the current loader silently drops.

This unifies use case A's symptom→disease→food query path and unlocks evidence-graded recommendations against literature anchors.

## 2. Why now

The Phase 2 audit closeout (PRs #21–#23) revealed three independent disease-touching surfaces that each parse / join free text:

- `chemical_diseases.disease_name` — 6,678 distinct strings from CTD
- `target_diseases.disease_name` — 2,976 distinct strings from CMAUP
- `symptom_disease_map.disease_name` — 40 strings from SymMap matches

These overlap heavily ("Diabetes Mellitus" appears under all three) but are siloed. Any cross-source query reduces to free-text LIKE, defeating the formal-ontology benefit of having MeSH/UMLS/ICD-10 IDs in the first place.

Plus the CTD loader currently drops two high-value signals:
- `PubMedIDs` (column 9) — 1–50 citations per chemical-disease pair, ~10M total citations across the dataset
- `InferenceGeneSymbol` (column 6) — the gene mediating an inferred association, joinable to our existing `targets` table

Both are "evidence-graded recommendation" gold for use case A.

## 3. Non-goals

- Replacing `target_diseases` or `symptom_disease_map` schemas wholesale. Those keep their natural keys; only the disease-naming surface gets unified.
- Cross-mapping every disease vocabulary on earth. We canonicalize what's already in our DB plus the CTD MeSH IDs that arrive through the new ingest. Other vocabularies (DOID, ICD-11, OMIM expansion) are out of scope.
- Building a UI for browsing the canonical disease registry. Schema-only addition; queries flow through the existing 5 MCP primitives.
- Touching the Phase 1 ChEMBL evidence layer. `bioactivity_evidence` already references targets, not diseases — orthogonal change.

## 4. Architecture

### 4.1 Three new tables

```sql
-- Canonical disease registry — one row per real-world concept,
-- unified across CTD / SymMap / target_diseases / herb2_herb_disease.
CREATE TABLE diseases_canonical (
  id              TEXT PRIMARY KEY,        -- 'mesh:D003920' | 'umls:C0011849' | 'local:slugified-name'
  preferred_name  TEXT NOT NULL,
  mesh_id         TEXT,                    -- MeSH descriptor or supplementary ID, prefix-stripped
  umls_id         TEXT,
  icd10cm_id      TEXT,
  hpo_id          TEXT,
  source_origin   TEXT NOT NULL,           -- which loader first registered this disease
  created_at      TEXT NOT NULL
);
CREATE INDEX idx_dc_mesh ON diseases_canonical(mesh_id) WHERE mesh_id IS NOT NULL;
CREATE INDEX idx_dc_umls ON diseases_canonical(umls_id) WHERE umls_id IS NOT NULL;
CREATE INDEX idx_dc_name ON diseases_canonical(preferred_name);
CREATE UNIQUE INDEX idx_dc_unique_mesh ON diseases_canonical(mesh_id) WHERE mesh_id IS NOT NULL;
CREATE UNIQUE INDEX idx_dc_unique_umls ON diseases_canonical(umls_id) WHERE umls_id IS NOT NULL;

-- Free-text alias registry — every disease name string ever seen,
-- pointing back to canonical. Built by the unification pass.
CREATE TABLE disease_name_aliases (
  disease_id  TEXT NOT NULL,               -- FK to diseases_canonical.id
  alias       TEXT NOT NULL,
  source      TEXT NOT NULL,               -- 'ctd' | 'symmap' | 'target_diseases' | 'herb2'
  PRIMARY KEY (disease_id, alias, source),
  FOREIGN KEY (disease_id) REFERENCES diseases_canonical(id)
);
CREATE INDEX idx_dna_alias_lower ON disease_name_aliases(lower(alias));

-- Compound → disease evidence with explicit type + citations + gene anchor.
-- Replaces chemical_diseases.
CREATE TABLE compound_disease_evidence (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  compound_id            TEXT NOT NULL,
  disease_id             TEXT NOT NULL,
  evidence_type          TEXT NOT NULL,    -- 'direct_therapeutic' | 'direct_marker' | 'inferred_via_gene'
  inference_gene_symbol  TEXT,             -- non-null iff evidence_type='inferred_via_gene'
  inference_score        REAL,             -- non-null iff evidence_type='inferred_via_gene'
  pubmed_ids             TEXT,             -- pipe-separated, preserves CTD's format
  source                 TEXT NOT NULL DEFAULT 'ctd',
  ingested_at            TEXT NOT NULL,
  FOREIGN KEY (compound_id) REFERENCES compounds(id),
  FOREIGN KEY (disease_id)  REFERENCES diseases_canonical(id),
  CHECK (
    (evidence_type IN ('direct_therapeutic', 'direct_marker')
       AND inference_gene_symbol IS NULL AND inference_score IS NULL)
    OR
    (evidence_type = 'inferred_via_gene'
       AND inference_score IS NOT NULL)
  )
);
CREATE INDEX idx_cde_compound ON compound_disease_evidence(compound_id);
CREATE INDEX idx_cde_disease  ON compound_disease_evidence(disease_id);
CREATE INDEX idx_cde_gene     ON compound_disease_evidence(inference_gene_symbol)
  WHERE inference_gene_symbol IS NOT NULL;
CREATE INDEX idx_cde_type     ON compound_disease_evidence(evidence_type);
```

### 4.2 Disease ID convention

Each canonical disease's `id` follows a stable, deterministic prefix scheme:

- `mesh:D003920` — when the disease has a MeSH descriptor or supplementary concept ID
- `umls:C0011849` — when no MeSH but UMLS CUI exists
- `icd10cm:E11` — when only ICD-10-CM is available
- `local:diabetes-mellitus` — last-resort slugified preferred_name (only used when no formal ID exists, e.g., legacy CMAUP `target_diseases` entries with bare strings)

Priority order during canonicalization:
1. If a MeSH ID is present in any source for this concept → use MeSH ID as canonical
2. Else if UMLS CUI is present → use UMLS
3. Else if ICD-10-CM is present → use ICD
4. Else slugify the preferred name with `local:` prefix

### 4.3 Loader changes

Two modified loaders + one new one:

**Modified `scripts/load-ctd.ts`** (the only existing CSV→DB code that writes disease rows):
- Read CTD column 9 (`PubMedIDs`) and 6 (`InferenceGeneSymbol`).
- Resolve each row's `(disease_name, disease_id)` against `diseases_canonical` via `disease_name_aliases` lookup; if no match, INSERT a new canonical row with the parsed MeSH ID (CTD's `disease_id` is `MESH:D018268` form — strip the prefix).
- Emit `evidence_type` based on the row: `direct_therapeutic` for `direct_evidence='therapeutic'`, `direct_marker` for `direct_evidence='marker/mechanism'`, `inferred_via_gene` for non-empty `InferenceGeneSymbol` + numeric score.
- Write to `compound_disease_evidence` instead of `chemical_diseases`.

**New `scripts/build_disease_canonical.py`** (orchestrator):
- One-time canonicalization pass that ingests disease names from all four sources (`target_diseases`, `symmap_modern_symptoms`, `chemical_diseases` if still around for one cycle, `herb2_herb_disease`) into `diseases_canonical` + `disease_name_aliases`.
- Idempotent (UPSERT semantics; safe to re-run after each source-data refresh).
- For each input row: parse formal IDs out of any `disease_id` column, join with existing canonical entries by MeSH/UMLS, create new canonical row if no match.

**Modified `scripts/build_symptom_disease_map.py`**:
- After inserting a row, also UPSERT into `disease_name_aliases` so the symptom→disease bridge contributes its disease vocabulary to the canonical registry.

### 4.4 LightRAG schema additions

Update `lightrag/entity_schema.py`:

- `Disease` entity now sources from `diseases_canonical` (was: aggregated from multiple tables via a query builder). The `query` becomes:
  ```sql
  SELECT id AS disease_name, preferred_name, mesh_id, umls_id, icd10cm_id
  FROM diseases_canonical ORDER BY id
  ```
  with `name_field = 'preferred_name'` so descriptions read naturally.
- New relationship: `Compound -COMPOUND_TREATS_DISEASE-> Disease` (sources from `compound_disease_evidence` where `evidence_type='direct_therapeutic'`).
- New relationship: `Compound -COMPOUND_MARKER_FOR_DISEASE-> Disease` (sources where `evidence_type='direct_marker'`).
- New relationship: `Compound -COMPOUND_INFERRED_DISEASE-> Disease` with `inference_gene_symbol` + `inference_score` as edge properties.
- Existing `MAPS_TO_DISEASE` and `ASSOCIATED_WITH_DISEASE` queries get updated to JOIN through `disease_name_aliases` → `diseases_canonical.id` rather than free-text disease_name.

### 4.5 Migration semantics

Both old (`chemical_diseases`) and new (`compound_disease_evidence`) tables co-exist for **one stable production cycle (≥1 week)** before the old is dropped. During the parallel period:
- New CTD ingest writes to BOTH tables.
- Existing queries against `chemical_diseases` continue working unchanged.
- New queries (LightRAG schema, MCP tools indirectly) use `compound_disease_evidence`.
- Audit-gate test_chemical_diseases_has_meaningful_coverage stays GREEN against the legacy table during the transition.

After the parallel period:
- Drop `chemical_diseases` and `chemical_phenotypes` (the latter is empty in scope of this PR; it's a Phase 2.5 follow-up).
- The audit-gate test gets renamed/repointed to `compound_disease_evidence ≥ 800K rows`.
- `target_diseases` STAYS — it's CMAUP's natural representation; we just add aliases linking it to the canonical registry.

## 5. Use cases unblocked

### 5.1 Symptom → food, evidence-graded with citations

```sql
SELECT
  cf.food_name,
  c.name AS bioactive_compound,
  d.preferred_name AS disease,
  cde.evidence_type,
  cde.pubmed_ids,
  cde.inference_gene_symbol,
  sdm.match_score AS symptom_to_disease_confidence
FROM symptoms s
JOIN symptom_disease_map sdm ON sdm.symptom_id = s.id
JOIN diseases_canonical d
  ON d.mesh_id = sdm.mesh_id          -- canonical join, NOT free-text LIKE
JOIN compound_disease_evidence cde ON cde.disease_id = d.id
JOIN compounds c ON c.id = cde.compound_id
JOIN compound_foods cf ON cf.compound_id = c.id
WHERE s.name = ?
ORDER BY
  sdm.match_score DESC,
  CASE cde.evidence_type
    WHEN 'direct_therapeutic' THEN 1
    WHEN 'direct_marker'      THEN 2
    ELSE 3                                -- inferred ranks below direct
  END,
  LENGTH(cde.pubmed_ids) DESC             -- more citations = stronger
LIMIT 20;
```

### 5.2 Diet → physiological effect prediction with mechanism

```sql
-- Foods → compounds → genes (CTD inference) → existing CMAUP target/disease layer
SELECT
  cf.food_name,
  c.name AS compound,
  cde.inference_gene_symbol AS mediating_gene,
  t.name AS protein_target,                -- joined via gene_symbol
  td.disease_name AS associated_disease    -- existing CMAUP path
FROM compound_foods cf
JOIN compounds c ON c.id = cf.compound_id
JOIN compound_disease_evidence cde
  ON cde.compound_id = c.id
  AND cde.evidence_type = 'inferred_via_gene'
LEFT JOIN targets t ON t.gene_symbol = cde.inference_gene_symbol
LEFT JOIN target_diseases td ON td.target_id = t.id
WHERE cf.food_name = ?;
```

This is **the** mechanistic chain that Phase 1 (compound→target via ChEMBL) and Phase 2 (compound→disease via CTD) wanted to compose — disease canonicalization is what stitches them.

### 5.3 Compound mechanism dossier with full provenance

```sql
SELECT json_object(
  'compound', c.name,
  'cas', c.cas_number,
  'pubchem_cid', ci.pubchem_cid,
  'chembl_id', ci.chembl_id,
  'targets', json_group_array(DISTINCT json_object(
    'name', t.name, 'uniprot', t.uniprot_id, 'gene', t.gene_symbol)),
  'diseases', json_group_array(DISTINCT json_object(
    'name', d.preferred_name,
    'mesh_id', d.mesh_id,
    'evidence_type', cde.evidence_type,
    'pubmed_count', LENGTH(cde.pubmed_ids) - LENGTH(REPLACE(cde.pubmed_ids, '|', '')) + 1)),
  'foods', json_group_array(DISTINCT cf.food_name)
)
FROM compounds c
LEFT JOIN compound_identity ci ON ci.compound_id = c.id
LEFT JOIN compound_targets ct ON ct.compound_id = c.id
LEFT JOIN targets t ON t.id = ct.target_id
LEFT JOIN compound_disease_evidence cde ON cde.compound_id = c.id
LEFT JOIN diseases_canonical d ON d.id = cde.disease_id
LEFT JOIN compound_foods cf ON cf.compound_id = c.id
WHERE c.id = ?;
```

## 6. Quantitative impact

| Metric | Before | After |
|---|---|---|
| Disease entities | 3 separate denormalized columns + free-text JOINs | ~6,500–10,000 canonical rows (CTD ∪ SymMap ∪ target_diseases ∪ herb2) |
| Cross-source disease join | `LIKE '%' ‖ name ‖ '%'` (noisy, slow) | indexed equality on `diseases_canonical.id` |
| PubMed citations preserved | 0 | ~5–50 per CTD row × ~3.8M raw CTD rows ≈ 5–10M citation references |
| Gene-mediated inference path | dropped during ingest | preserved as `inference_gene_symbol`, joinable to `targets.gene_symbol` |
| Schema invariant enforcement | parser logic only | CHECK constraint on `evidence_type` ↔ inference fields |
| LightRAG `Disease` entity rendering | 3 disjoint sources, possible duplication | one entity per concept, full ontology cross-refs in description |

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Dual-write phase doubles INSERT time | Acceptable — CTD ingest is 60s today; doubling is still <2 min |
| Disease unification mis-merges concepts ("Hypertension" ≠ "Pulmonary Hypertension") | MeSH ID is the primary key; concepts with different MeSH IDs stay distinct. Slugified `local:` IDs are conservative — we never auto-merge by name similarity. |
| Existing queries against `chemical_diseases` break during/after migration | Parallel-table design + 1-week stable cycle before drop. Old table is read-only after PR ships. |
| CHECK constraint rejects edge-case CTD rows | Add a "unknown" evidence type as escape hatch + log to runbook. |
| PubMed ID format drift over time | Stored as opaque pipe-separated text; downstream parsers can split on '\|'. No schema impact. |
| Mass disease-name fuzzy-matching is expensive | We do NOT fuzzy-match. Canonicalization is by formal-ID equality only. Free-text aliases populate `disease_name_aliases` but are never used to merge canonical rows. |

## 8. Definition of Done

- `diseases_canonical` populated with rows from all four sources; unique-MeSH constraint validates.
- `disease_name_aliases` covers ≥95% of distinct disease names found across the four sources.
- `compound_disease_evidence` has ≥800K rows from re-ingested CTD (vs 934K in `chemical_diseases` today; some reduction expected from dropping rows that fail the CHECK constraint).
- Every row in `compound_disease_evidence` has a non-NULL `disease_id` resolving to `diseases_canonical`.
- ≥40% of `compound_disease_evidence` rows of `evidence_type='direct_therapeutic'` carry at least one `pubmed_ids` value (CTD's actual fill rate; will measure during ingest).
- LightRAG schema's `Disease` entity sources from `diseases_canonical`; existing `MAPS_TO_DISEASE` and `ASSOCIATED_WITH_DISEASE` queries updated to canonical IDs.
- Audit gate `test_chemical_diseases_has_meaningful_coverage` superseded by new gate `test_compound_disease_evidence_has_meaningful_coverage` (≥800K).
- New audit gate: `test_disease_canonicalization_unifies_sources` — every disease string from `target_diseases.disease_name`, `symmap_modern_symptoms.name`, and CTD has at least one row in `disease_name_aliases`.
- `chemical_diseases` table marked deprecated in `docs/DATASET_PROVENANCE.md`; scheduled for drop after one stable cycle.
- ADR `0008-disease-canonicalization.md` documents the design + alternatives rejected.
- 80%+ test coverage on new canonicalization modules.

## 9. Open questions for user

None blocking. Recording for transparency:

1. **Should `chemical_diseases` be dropped or left as a deprecated view over `compound_disease_evidence`?** Default: drop after 1 stable cycle. A view would let any external consumer survive the migration but adds permanent legacy surface area.
2. **Should `evidence_type='inferred_via_gene'` rows with `pubmed_ids IS NULL` be ingested?** Default: yes (the gene-mediated inference is itself the evidence; CTD provides citations only for some inferred rows).
3. **Should we backfill `pubmed_ids` for `direct_evidence='therapeutic'` rows in the existing `chemical_diseases` table during migration?** Default: no — re-running CTD ingest produces the new schema directly; backfilling is wasted work.

If any of these defaults are wrong, flag at approval gate.
