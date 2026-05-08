# KEGG Pathway Overlay — Design

**Status:** Draft v1 — pending user approval
**Date:** 2026-05-08
**Owner:** mymm.psu@gmail.com
**Related run:** `.claude/runs/20260508-kegg-pathways/`
**Stacks on:** PR #25 (Phase 3 — disease canonicalization)

## 1. Objective

Add a KEGG-sourced pathway layer that closes the use-case-D mechanistic chain:

```
Food → Compound → Pathway → Gene → Target → Disease
```

Currently the chain has two complete paths (direct compound-target binding via CMAUP; gene-mediated inference via CTD `inference_gene_symbol`). Pathway membership is a third orthogonal evidence path that lets the agent layer answer questions like:

> "Curcumin appears in 4 NF-kB-related pathways, alongside compound X (in food Y) — is there a synergy hypothesis?"

## 2. Why now

After Phase 3 closed disease canonicalization, the only remaining doneness criterion from the original audit (§5.4) is *"Pathway-level rollup available — requires Phase 2 KEGG overlay."* This phase is that overlay.

KEGG also provides the gene-symbol → pathway crosswalk that lets us cluster bioactivity evidence: instead of seeing 50 raw target hits for curcumin, we see those 50 grouped under ~12 pathways. That's the right axis for human-readable diet-effect explanations.

## 3. Non-goals

- **Not** ingesting KEGG DRUG (drug-interaction database — overlaps DrugBank, separate licensing risk).
- **Not** ingesting KEGG REACTION (chemical-reaction-level detail — too granular for our query patterns).
- **Not** building a KEGG visualization. The data is queryable through the existing 5 MCP primitives.
- **Not** running compound resolution against KEGG names. Resolution happens through `compound_identity.kegg_compound_id` (Phase 1 path) — when that table is populated, joins activate.

## 4. License posture (important)

KEGG is **academic-use-only**. Commercial deployment requires a paid license from Pathway Solutions, Inc. ([details](https://www.kegg.jp/kegg/legal.html)).

This phase ships ingest scripts for academic-research use (the project's stated scope per `README.md` and the related `Diet Insight Engine` research collaboration). The DATASET_PROVENANCE.md update will include a **clear license box** marking KEGG as academic-only and flagging any future commercial deployment will need to either (a) acquire a license or (b) drop the KEGG layer and use ChEMBL/Open Targets pathway data instead.

The license boundary is enforced via a build-time toggle: `make build-kegg-pathways` is the only entry point that fetches KEGG data. There's no implicit dependency — every other build target works without KEGG.

## 5. Architecture

### 5.1 Three new tables (self-contained KEGG layer)

```sql
CREATE TABLE kegg_pathways (
  id            TEXT PRIMARY KEY,        -- 'hsa01100' style
  name          TEXT NOT NULL,           -- 'Metabolic pathways'
  organism      TEXT NOT NULL DEFAULT 'hsa',  -- 'hsa' = Homo sapiens
  category      TEXT,                     -- 'Metabolism' | 'Signal Transduction' | etc.
  source        TEXT NOT NULL DEFAULT 'kegg',
  ingested_at   TEXT NOT NULL
);
CREATE INDEX idx_kp_name ON kegg_pathways(name);

CREATE TABLE kegg_compound_pathways (
  kegg_compound_id  TEXT NOT NULL,        -- 'C00031' style (KEGG Compound ID)
  kegg_pathway_id   TEXT NOT NULL,
  ingested_at       TEXT NOT NULL,
  PRIMARY KEY (kegg_compound_id, kegg_pathway_id),
  FOREIGN KEY (kegg_pathway_id) REFERENCES kegg_pathways(id)
);
CREATE INDEX idx_kcp_compound ON kegg_compound_pathways(kegg_compound_id);

CREATE TABLE kegg_pathway_genes (
  kegg_pathway_id   TEXT NOT NULL,
  kegg_gene_id      TEXT NOT NULL,        -- 'hsa:1234' (KEGG-prefixed Entrez)
  gene_symbol       TEXT,                  -- HUGO symbol — primary join key for our targets
  ingested_at       TEXT NOT NULL,
  PRIMARY KEY (kegg_pathway_id, kegg_gene_id),
  FOREIGN KEY (kegg_pathway_id) REFERENCES kegg_pathways(id)
);
CREATE INDEX idx_kpg_gene_symbol ON kegg_pathway_genes(gene_symbol);
```

### 5.2 Ingest pipeline

Single Python script `scripts/build_kegg_pathways.py` calling KEGG REST API:

1. `GET /list/pathway/hsa` → parse 340-row pathway list → write to `kegg_pathways`
2. `GET /link/cpd/pathway/hsa` → parse pathway↔compound links → write to `kegg_compound_pathways` (~5K rows)
3. `GET /link/hsa/pathway` → parse pathway↔gene links → write to `kegg_pathway_genes` (~30K rows)
4. For each `kegg_pathway_genes` row, resolve `kegg_gene_id` (e.g. `hsa:1234`) to HUGO `gene_symbol` via batch lookup `GET /find/genes/{ids}` (KEGG returns gene aliases including HUGO).

KEGG REST API rate limits: ~3 req/s soft cap. The pipeline makes ~10 batch requests total — well under any concern. Total runtime expected: <30 seconds.

### 5.3 LightRAG schema additions

New entity:

```python
"Pathway": {
    "source_table": "kegg_pathways",
    "id_field": "id",
    "name_field": "name",
    "query": "SELECT id, name, organism, category FROM kegg_pathways ORDER BY id",
}
```

New relationships:

```python
"COMPOUND_IN_PATHWAY": {
    "source_table": "kegg_compound_pathways",
    "src_type": "Compound",
    "tgt_type": "Pathway",
    # Joins through compound_identity.kegg_compound_id; only fires when Phase 1
    # ingest has run. Until then, the relationship is empty (gracefully).
    "query": (
        "SELECT c.name AS src_name, kp.name AS tgt_name, kp.id AS pathway_id "
        "FROM kegg_compound_pathways kcp "
        "JOIN compound_identity ci ON ci.kegg_compound_id = kcp.kegg_compound_id "
        "JOIN compounds c ON c.id = ci.compound_id "
        "JOIN kegg_pathways kp ON kp.id = kcp.kegg_pathway_id "
        "ORDER BY c.id, kp.id"
    ),
}

"PATHWAY_INCLUDES_TARGET": {
    "source_table": "kegg_pathway_genes",
    "src_type": "Pathway",
    "tgt_type": "Target",
    # Joins through targets.gene_symbol — works regardless of Phase 1 state.
    "query": (
        "SELECT kp.name AS src_name, t.name AS tgt_name, "
        "       kpg.kegg_gene_id AS kegg_gene_id "
        "FROM kegg_pathway_genes kpg "
        "JOIN targets t ON t.gene_symbol = kpg.gene_symbol "
        "JOIN kegg_pathways kp ON kp.id = kpg.kegg_pathway_id "
        "ORDER BY kp.id, t.id"
    ),
}
```

### 5.4 Use case D query — closed mechanistic chain

```sql
-- Foods → compounds → KEGG pathways → KEGG genes ↔ our targets ↔ diseases
SELECT
  cf.food_name,
  c.name AS compound,
  kp.name AS pathway,
  kpg.gene_symbol,
  t.name AS target,
  d.preferred_name AS disease,
  cde.evidence_type
FROM compound_foods cf
JOIN compounds c ON c.id = cf.compound_id
JOIN compound_identity ci ON ci.compound_id = c.id  -- requires Phase 1 ingest
JOIN kegg_compound_pathways kcp ON kcp.kegg_compound_id = ci.kegg_compound_id
JOIN kegg_pathways kp ON kp.id = kcp.kegg_pathway_id
JOIN kegg_pathway_genes kpg ON kpg.kegg_pathway_id = kp.id
JOIN targets t ON t.gene_symbol = kpg.gene_symbol
LEFT JOIN compound_disease_evidence cde
  ON cde.compound_id = c.id
  AND cde.inference_gene_symbol = kpg.gene_symbol
LEFT JOIN diseases_canonical d ON d.id = cde.disease_id
WHERE cf.food_name = ?
GROUP BY cf.food_name, kp.id, t.id;
```

This single query joins Phase 0 (compound_foods, targets), Phase 1 (compound_identity), Phase 3 (compound_disease_evidence, diseases_canonical), and Phase 4 (KEGG tables) into one mechanistic explanation chain.

## 6. Definition of Done

- `kegg_pathways` populated with ≥300 human pathways (KEGG hsa organism baseline ~340)
- `kegg_compound_pathways` populated with ≥5,000 rows
- `kegg_pathway_genes` populated with ≥20,000 rows; ≥80% have a non-NULL `gene_symbol`
- LightRAG `Pathway` entity + `COMPOUND_IN_PATHWAY` + `PATHWAY_INCLUDES_TARGET` relationships defined and queryable
- `PATHWAY_INCLUDES_TARGET` query returns ≥1,000 rows when run against the live DB (joins `targets.gene_symbol`)
- `COMPOUND_IN_PATHWAY` query is *defined but may return 0 rows* until Phase 1 ingest runs — that's the deliberate Phase 1↔Phase 4 decoupling
- ADR `0009-kegg-pathway-overlay.md` documents the design + license posture
- 80%+ test coverage on new ingest module
- New audit-gate tests added for the 3 KEGG tables
- DATASET_PROVENANCE.md flags KEGG as academic-only with explicit commercial-deployment opt-out instructions

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| KEGG API rate-limits or downtime | Cache responses to local files; skip-if-cached on re-run; defer-and-retry on 5xx |
| KEGG license violation in commercial deployments | Build-time toggle; opt-out documented in DATASET_PROVENANCE.md; no implicit dependency |
| `gene_symbol` resolution may have <100% coverage | Floor of 80% in DoD; rest stay as `kegg_gene_id` only and won't join `targets` until upstream resolves |
| `compound_identity` empty (Phase 1 ingest pending) | `COMPOUND_IN_PATHWAY` returns 0 rows initially — accepted; activates automatically when Phase 1 ingest runs |
| KEGG reorg of pathway IDs | Cache + version-pin in `DATASET_PROVENANCE.md`; idempotent rebuild |

## 8. Out of scope

- Diet scoring function (Phase 5)
- KEGG REACTION ingest (too granular)
- KEGG DRUG ingest (overlapping data + license risk)
- Pathway visualization UI
- Cross-organism (mouse/rat) pathway data — `hsa` only
