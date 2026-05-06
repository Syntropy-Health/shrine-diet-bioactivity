# Drug ↔ Bioactive Bridge: Design

**Status:** Draft v1 — pending user approval
**Date:** 2026-05-06
**Owner:** mymm.psu@gmail.com
**Related runs:** `.claude/runs/20260506-013000-drug-bioactive-bridge/`

## 1. Objective

Extend the unified diet KG so that a single graph traversal connects **diet taxonomy → food → compound → bioactivity evidence (IC50/Ki/efficacy) → molecular target → disease/symptom**, where the `bioactivity evidence` and `target → disease` layers come from open-source DrugBank-equivalent sources (ChEMBL, Open Targets, KEGG, with PubChem/UniChem as identity backbone).

This unlocks two primary user-facing query patterns:

- **A. Symptom → food.** Given a symptom (e.g. "low-grade inflammation"), surface foods/herbs whose bioactive compounds have *clinical* drug-evidence for the implicated targets/diseases, ranked by evidence quality.
- **D. Diet → predicted physiological effects.** Given a recorded diet (food list with portions), aggregate bioactive compound exposure → target modulation → predicted pathway/disease effects.

Secondary, free-of-cost from the same backbone:

- **C. Compound mechanism dossier.** Given a bioactive (e.g. quercetin), produce a unified evidence card: structure, drug-likeness, targets, pathways, food sources.

## 2. Non-goals

- We do NOT build a recommendation/diagnostic engine; the KG returns evidence, the LLM agent reasons.
- We do NOT mirror full ChEMBL / PubChem / Open Targets. Slice-by-intersection is the architectural backbone (Q2 decision **D**).
- We do NOT ingest KEGG DRUG bulk content (license-restricted commercially); KEGG enters as an *overlay* — pathway IDs and a thin reference table only.
- "Drug → dietary equivalent" (Q1 option B) is deferred — it requires the inverse intersect (drugs whose compounds aren't in any food) which is its own architecture.
- Production of an MCP tool surface for the new entity types ships in Phase 1; rich query orchestration (multi-hop ranked recommendations) is Phase 3.

## 3. Architecture (full vision)

```
                    ┌──────────────────────────────────────────┐
                    │          IDENTITY BACKBONE                │
                    │                                            │
   existing         │   herbal_botanicals.db                     │
   compound  ──►    │     ├─ compounds (existing)                │
   universe         │     └─ compound_identity (NEW)             │
   (~100K)          │           pk: compound_id                  │
                    │           inchikey, pubchem_cid,           │
                    │           chembl_id, kegg_id,              │
                    │           drugbank_id, unichem_src_count   │
                    │                                            │
                    │   Built by: RDKit (smiles→InChIKey)        │
                    │             + UniChem source-mapping files │
                    │             + PubChem PUG-REST (fallback)  │
                    └──────────────────┬───────────────────────┘
                                       │
                          ┌────────────┴────────────┐
                          ▼                         ▼
            ┌──────────────────────┐    ┌──────────────────────┐
            │  PHASE 1 (this PR)   │    │  PHASE 2 (later)     │
            │                      │    │                      │
            │  ChEMBL bioactivity  │    │  Open Targets disease│
            │  (compound-anchored  │    │  (disease-anchored   │
            │   intersect)         │    │   for our 47 sxs)    │
            │                      │    │                      │
            │  + KEGG pathway IDs  │    │  + PubMed unstruct.  │
            │    (overlay only)    │    │    (LLM-extracted)   │
            └──────────┬───────────┘    └──────────┬───────────┘
                       │                            │
                       └──────────┬─────────────────┘
                                  ▼
                  ┌──────────────────────────────┐
                  │  LightRAG ainsert_custom_kg  │
                  │  (extended entity schema)    │
                  └──────────┬───────────────────┘
                             ▼
                       Neo4j + Vector
                             │
                             ▼
                  ┌──────────────────────────────┐
                  │   MCP tools (extended)       │
                  │   + REST/Ollama-compat API   │
                  └──────────────────────────────┘
```

## 4. Phase 1 scope (this PR)

Single, bounded deliverable that everything else plugs into.

### 4.1 Identity bridge

New SQLite table `compound_identity` in `herbal_botanicals.db`:

| Column | Type | Source |
|---|---|---|
| `compound_id` | INTEGER PK | FK to existing `compounds.id` |
| `inchikey` | TEXT, indexed | RDKit-computed from compounds.smiles |
| `inchi` | TEXT | RDKit |
| `pubchem_cid` | INTEGER, indexed | UniChem mapping file (src_id=22) |
| `chembl_id` | TEXT, indexed | UniChem mapping file (src_id=1) |
| `kegg_compound_id` | TEXT | UniChem mapping file (src_id=6) |
| `drugbank_id` | TEXT | UniChem mapping file (src_id=2) |
| `chebi_id` | INTEGER | UniChem mapping file (src_id=7) |
| `unichem_src_count` | INTEGER | count of mapped sources (proxy for "how well-characterised") |
| `resolution_method` | TEXT | one of: `rdkit_smiles`, `unichem_inchikey`, `pubchem_name_fallback` |
| `resolved_at` | TIMESTAMP | when this row was last refreshed |

Build pipeline (Python, runs at `make build-identity`):

1. **RDKit pass** — for each compound with a SMILES, compute Standard InChI + InChIKey. Record `resolution_method='rdkit_smiles'`. Compounds with no SMILES go to step 3.
2. **UniChem pass** — bulk-download UniChem source-mapping files for src_ids {1, 2, 6, 7, 22} (ChEMBL, DrugBank, KEGG, ChEBI, PubChem). Join on InChIKey. Populate cross-ref columns.
3. **PubChem name fallback** — for compounds with neither SMILES nor a UniChem hit, query PUG-REST `/compound/name/{name}/property/InChIKey`. Rate-limited, cached. Record `resolution_method='pubchem_name_fallback'`.

Coverage target: ≥70% of compounds resolve at least one cross-ref. Below that, the bridge is too sparse to support A/D queries — surface as runbook entry, do not block.

### 4.2 ChEMBL bioactivity slice (compound-anchored intersect)

Use `chembl-downloader` (PyPI, MIT) pinned to **ChEMBL 36** (DOI `10.6019/CHEMBL.database.36`). It auto-downloads the SQLite dump and exposes a `connect()` context.

Extraction SQL (single join through `compound_structures` ↔ `activities` ↔ `assays` ↔ `target_dictionary`):

```sql
SELECT
  cs.standard_inchi_key            AS inchikey,
  md.chembl_id                     AS chembl_compound_id,
  td.chembl_id                     AS chembl_target_id,
  td.pref_name                     AS target_pref_name,
  td.target_type                   AS target_type,
  td.organism                      AS target_organism,
  act.standard_type                AS activity_type,    -- IC50, Ki, EC50, Kd, ...
  act.standard_relation            AS relation,         -- '=', '<', '>', ...
  act.standard_value               AS value,
  act.standard_units               AS units,            -- 'nM' canonical
  act.pchembl_value                AS pchembl,          -- -log10(value in M)
  act.activity_comment             AS comment,
  ass.confidence_score             AS assay_confidence, -- 0..9
  doc.chembl_id                    AS chembl_doc_id,
  doc.year                         AS publication_year
FROM compound_structures cs
JOIN molecule_dictionary md  ON md.molregno  = cs.molregno
JOIN activities act          ON act.molregno = cs.molregno
JOIN assays ass              ON ass.assay_id = act.assay_id
JOIN target_dictionary td    ON td.tid       = ass.tid
LEFT JOIN docs doc           ON doc.doc_id   = act.doc_id
WHERE cs.standard_inchi_key IN (?)        -- batch of 1000 InChIKeys from compound_identity
  AND act.standard_value IS NOT NULL
  AND act.standard_relation IN ('=', '<', '<=')
  AND ass.confidence_score >= 5            -- exclude low-confidence assays
  AND act.pchembl_value >= 5;              -- ≥ μM potency cutoff (filter noise)
```

Output: new SQLite table `bioactivity_evidence` (alongside compound_identity). Then materialised into LightRAG via `ainsert_custom_kg`.

### 4.3 Schema additions in LightRAG

New entity type:

- **`BioactivityEvidence`** — granular evidence node, NOT redundant with Target. Description template:
  > `BioactivityEvidence`: ChEMBL assay {chembl_doc_id} reports {compound_name} {relation} {value}{units} {activity_type} against {target_pref_name} ({target_organism}); pChEMBL {pchembl}, assay confidence {assay_confidence}, year {year}.

This single text-rich node is what LightRAG will return on semantic search for "what's the evidence for X on Y" type queries. The structured fields are also stored on the Neo4j node properties for Cypher-based filtering.

New relationship types:

| Source | Target | Type | Properties |
|---|---|---|---|
| `Compound` | `BioactivityEvidence` | `HAS_EVIDENCE` | `pchembl`, `activity_type`, `value_nM` |
| `BioactivityEvidence` | `Target` | `EVIDENCE_FOR_TARGET` | `confidence_score`, `year` |

Existing `Compound → Target` (CMAUP-derived `TARGETS_PROTEIN`) stays — those are predicted/curated; the new `HAS_EVIDENCE → EVIDENCE_FOR_TARGET` chain is measured. Both surface in queries; the LLM ranks.

KEGG overlay: add `kegg_compound_id` to existing `Compound` node properties (no new entity, no relationship). A future Phase 2 KEGG pathway ingestion will add `Pathway` entities and relationships.

### 4.4 MCP tool surface — no new tools

The project's MCP layer is intentionally a **thin domain-agnostic adapter** over LightRAG (5 primitives: `semantic-search`, `get-entity`, `get-subgraph`, `list-labels`, `ingest-knowledge`). `src/tools.ts` enforces this with a `FORBIDDEN_USECASE_VERBS` guard. Use-case framing belongs in the agent layer, not MCP.

So Phase 1 adds **zero new MCP tools**. The new `BioactivityEvidence` entity type and `HAS_EVIDENCE` / `EVIDENCE_FOR_TARGET` relationships become queryable through the existing 5 primitives the moment they land in Neo4j:

- `semantic-search` mode=`hybrid` → "what evidence connects curcumin to inflammation targets" returns `BioactivityEvidence` text descriptions.
- `get-entity label="BioactivityEvidence" id="<chembl_doc_id>"` → fetch a specific evidence node.
- `get-subgraph label="<compound>" max_depth=2` → traverses through `HAS_EVIDENCE` edges.

What ships in Phase 1 for the tool surface: a regression test in `src/__tests__/tool_catalog.test.ts` confirming the new entity types appear in `list-labels` output once ingested, and a docstring update in `src/tools.ts` listing the new label vocabulary.

### 4.5 Tests

- **Unit**: RDKit InChIKey computation against known fixtures (curcumin, quercetin, EGCG, caffeine, ascorbic acid).
- **Integration**: end-to-end `build-identity` on a 100-compound test slice; assert ≥70% cross-ref coverage on a curated test set of well-known phytochemicals.
- **Integration**: `extract_chembl_bioactivities` against a fixture SQLite (subset ≤5MB committed under `tests/fixtures/chembl_subset.sqlite` containing ~50 well-known phytochemicals + their activities), assert known compound→target rows present.
- **Integration**: LightRAG ingestion smoke — assert new entity types and relationships land in Neo4j.
- **Contract**: MCP tool input/output Zod schemas, including unhappy-path (unknown compound name → empty result, not error).

Coverage target: ≥80% on new code per project standard.

## 5. Phase 2 scope (separate dispatches)

Listed for context; NOT in this PR.

- **Open Targets disease-anchored slice.** Pull `association_by_overall_direct` and `association_by_datasource_direct` Parquet snapshots, filter to targets reachable from our compound universe + a curated MeSH expansion of our 47 symptoms. New entity: `DiseaseAssociation` (target↔disease score). Materialise via duckdb→parquet→ainsert_custom_kg.
- **KEGG pathway overlay (small).** Pull KEGG compound→pathway mapping (academic-licensed, fits within the project's research scope). New entity: `Pathway`. Relationship: `Compound → Pathway`.
- **PubMed unstructured extraction.** Use existing LightRAG `ainsert(text)` path on PubMed abstracts filtered by our compound names (PubMed E-utilities). New entity types extracted by LLM: `ClinicalOutcome`, `AdverseEffect`. This is the "unstructured" half of the modality split documented in `docs/unified-diet-kg-architecture.md`.

## 6. Reproducibility & licensing

- ChEMBL: CC BY-SA 3.0. Pin to release 36; record DOI in ingestion provenance.
- PubChem: public domain (US gov). PUG-REST has a 5-req/sec soft limit; respect it.
- UniChem: free; mapping files versioned by ChEMBL release.
- Open Targets: CC0. Snapshot version recorded in ingestion provenance.
- KEGG: research use only — non-commercial; document in `DATASET_PROVENANCE.md`.
- RDKit: BSD-3.

All ingestion runs append to a `provenance` table: `(source, version, doi_or_url, ingested_at, row_count)`.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| InChIKey coverage <70% on legacy compounds | RDKit + UniChem + PubChem fallback chain; surface coverage report; do not block ingest. |
| ChEMBL 36 SQLite dump >12GB | Stream-based extraction; only pull rows matching our InChIKey set (LIMIT IN-batches of 1000). |
| ChEMBL pChEMBL filter (≥5) drops too aggressively for natural-product-style weak binders | Configurable threshold via `config_local.env`; default 5.0, downgradable to 4.0 with warning. |
| LightRAG entity count blowup on bioactivity evidence | Each compound averages ~10–50 measured bioactivities — ~1–5M new evidence nodes total. Validate Neo4j memory headroom before bulk insert; chunk in 10K batches. |
| `compound_identity` becomes stale as compounds added | Idempotent rebuild script; CI nightly run as Phase 2 follow-up (not this PR). |
| RDKit Python build complications | Use `rdkit-pypi` wheel (manylinux), pinned in `pyproject.toml`. |
| Existing parallel-session WIP in `mcp/` (PostHog analytics) | Out of scope; do not touch. Phase 1 changes go in `lightrag/` and `mcp/src/kg_mcp/tools.py` (additive only). |

## 8. Open questions for user

None blocking. Recording for transparency:

1. Should `bioactivity_evidence` rows below `pchembl < 5.0` be ingested with a confidence flag, or excluded? **Default: excluded** (filterable later if needed).
2. Should the identity bridge's PubChem fallback be online-at-build-time or batched offline? **Default: online with disk cache** (simpler, deterministic per cache state).

If either default is wrong, flag at approval gate.

## 9. Definition of Done (Phase 1)

- `compound_identity` table populated with ≥70% cross-ref coverage on test set.
- `bioactivity_evidence` table populated for all matched compounds with pChEMBL ≥ 5.0.
- LightRAG schema includes `BioactivityEvidence` entity + `HAS_EVIDENCE` / `EVIDENCE_FOR_TARGET` relationships, ingested into Neo4j.
- New entity types appear in MCP `list-labels` output (regression test); `src/tools.ts` docstring lists new label vocabulary. **No new MCP tools** (thin-adapter architecture preserved).
- Test coverage ≥80% on new code.
- `DATASET_PROVENANCE.md` updated with ChEMBL 36, UniChem, PubChem PUG-REST provenance.
- `docs/unified-diet-kg-architecture.md` updated to reflect new entity types.
