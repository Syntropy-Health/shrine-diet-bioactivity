# Dataset Provenance — shrine-diet-bioactivity KG

_Last updated 2026-05-01. Single-page summary tying every Aura node and edge to its upstream source, license, ingest pipeline, and refresh cadence._

This is the doc a paper reviewer or downstream MCP integrator reads once to understand "where every edge in this KG came from".

For per-source schema, file format, and join keys see [`shrine-diet-bioactivity/data/manifest.yaml`](../shrine-diet-bioactivity/data/manifest.yaml). For the live count snapshot see [`research-journal/shared/scope-state-snapshot.md`](../research-journal/shared/scope-state-snapshot.md).

## Mission axis

Every node and edge in this KG serves the **diet ⇄ food ⇄ bioactive compound ⇄ symptom ⇄ disease** retrieval objective. The KG is intentionally narrow on this axis (per the functional parsimony principle in `2026-04-29-mcp-gateway-design.md` §8.3).

## Sources

### Tier 1 — core ingested

| Source | License | Edges | Aura node count | Loader | Last refresh |
|---|---|---|---:|---|---|
| **Dr. Duke's Phytochemical Database** | CC0 | `CONTAINS_COMPOUND`, `FOUND_IN_FOOD`, `TARGETS_PROTEIN`, `TREATS_SYMPTOM` | 105K (105,191 by source prefix) | `lightrag/ingest_unified.py`, `lightrag/ingest_direct.py` | 2026-04-12 |
| **FooDB** | CC-BY-4.0 | `FOUND_IN_FOOD` (4.13M edges) | (compounds + foods integrated under Duke) | same as Duke (joined at SQLite layer) | 2026-04-12 |
| **CMAUP v2.0** | non-commercial academic | `ASSOCIATED_WITH_DISEASE` from `plant:NPO*` rows; `TARGETS_PROTEIN` from `compound_targets` | 7,772 (CMAUP-source nodes) | `scripts/ingest_cmaup_plant_diseases.py` | 2026-04-29 |
| **TTD** (Therapeutic Target Database) | non-commercial academic | drug literature refs (PMIDs) only — drug nodes not yet ingested as entities; HDI-Safe-50 panel cites these where relevant | — | indirect (HDI-Safe-50) | — |
| **SymMap 2.0** | non-commercial academic | `TREATS_SYMPTOM`, `CONTAINS_COMPOUND`, bilingual herb cross-walk | 50,652 | `scripts/load-symmap.ts`, `lightrag/ingest_unified.py` | 2026-04-26 |
| **HERB 2.0** (chedi.ac.cn) | non-commercial academic | `ASSOCIATED_WITH_DISEASE` (capped at 5K experimental + clinical-tier rows) | 5,300 | `scripts/load-herb2.ts`, `lightrag/ingest_unified.py` | 2026-04-12 |
| **HDI-Safe-50** (curated) | derived from NIH ODS / MSK About Herbs / LiverTox (publicly accessible references; citations preserved per-edge) | `INTERACTS_WITH` (50 edges across 21 herbs × 35 drugs) | 41 + node aliases | `lightrag/ingest_hdi.py`; aliases via `scripts/enrich_hdi_aliases.py` | 2026-05-01 |
| **OpenNutrition** food bridge | CC-BY-4.0 (USDA FDC core) | `nutrition_100g` JSON property on Food nodes (90 nutrient keys) | 647 of 962 Foods enriched | `scripts/build-food-bridge.ts` → `scripts/enrich_food_nodes.py` | 2026-04-29 |

### Tier 2 — entity overlays (additive, no new edges)

| Source | What | Aura property | Loader | Last refresh |
|---|---|---|---|---|
| **NCBI MeSH** (E-utilities) | hierarchical disease/symptom terminology | `mesh_uid`, `mesh_descriptor`, `mesh_tree_numbers` on Disease + Symptom nodes | `scripts/ncbi/phase_1_mesh_overlay.py` | 2026-05-01 |
| **NCBI PubChem** (PUG-REST) | canonical chemical IDs + synonyms | `pubchem_cid`, `inchi_key`, `canonical_smiles`, `aliases` on Compound nodes (mission-scoped subset of ~1.2K compounds with `TARGETS_PROTEIN` or `FOUND_IN_FOOD` participation) | `scripts/ncbi/phase_2_pubchem_overlay.py` | 2026-05-01 |

### Tier 3 — deferred (in `data/manifest.yaml` but not loaded)

| Source | Why deferred |
|---|---|
| **CTD** (Comparative Toxicogenomics) | SQLite empty; ETL pipeline never ran. Marginally on-mission for chemical-disease toxicity overlay; defer until v1 eval signal that it's needed. |
| **TCMSP, STITCH, DisGeNET, BATMAN-TCM** | Tier-2 aspirational. Similar relationship types to what we already have via Duke/CMAUP/SymMap. Defer pending paper-claim coverage gap. |
| **Bulk TTD drug-disease** (30K rows in SQLite) | Off-mission per parsimony — drugs aren't diet. The diet-relevant drug-herb safety surface is covered by HDI-Safe-50. |

## Per-relationship-type provenance

| Edge type | Aura count | Sources | Notes |
|---|---:|---|---|
| `FOUND_IN_FOOD` | 4,134,251 | Duke + FooDB | Compound → Food. Most edges from FooDB compound-food pairs. |
| `ASSOCIATED_WITH_DISEASE` | 763,600 | CMAUP (765K plant-disease) + HERB 2.0 (5K experimental+clinical-tier) | Herb → Disease primary path |
| `CONTAINS_COMPOUND` | 85,186 | Duke | Herb → Compound; complements `FOUND_IN_FOOD` |
| `TREATS_SYMPTOM` | 41,823 | Duke bioactivity-derived + SymMap TCM | Herb → Symptom; bilingual via SymMap |
| `TARGETS_PROTEIN` | 6,465 | Duke + CMAUP `compound_targets` | Compound → Target; pharmacology mid-link for Compound→Disease chains |
| `INTERACTS_WITH` | 50 | HDI-Safe-50 curated panel | Drug ⇄ Herb; severity + mechanism_class + evidence_tier on each edge |
| `DIRECTED` | 50 | (legacy custom_kg artifacts) | Defer cleanup |

## Per-node-label inventory

| Label | Aura count | Source mix |
|---|---:|---|
| Compound | 120,217 | Duke (94K base) + SymMap ingredients + extras |
| Target | ~6,500 | Duke + CMAUP |
| Disease | ~5,000 | Duke + CMAUP plant-disease + HERB 2.0 |
| Food | 962 | Duke food list + bridge to OpenNutrition |
| Herb | ~9,000 | Duke (2,376) + SymMap (~700) + HERB 2.0 (~5K) + CMAUP (7,865) |
| Symptom | ~3,000 | Duke + SymMap (TCM + modern) |
| Drug | 35 | HDI-Safe-50 only |
| Gene (via SymMap) | ~21,000 | SymMap genes |

(All under `:unified_diet_kg` workspace label, `scope='shared'`.)

## Refresh procedures

To refresh any source from upstream and re-ingest:

```bash
cd shrine-diet-bioactivity

# Tier 1 — re-ingest a specific source
make download-symmap && make load-symmap        # SymMap 2.0
make download-herb2 && make load-herb2          # HERB 2.0
make download-cmaup && make load-cmaup          # CMAUP v2.0
make food-bridge && make enrich-nutrition       # OpenNutrition food bridge
python lightrag/ingest_hdi.py                   # HDI-Safe-50 panel

# After any Tier-1 ingest, re-stamp HDI aliases:
python scripts/enrich_hdi_aliases.py

# Tier 2 — NCBI overlay (idempotent, resumable)
python scripts/ncbi/phase_1_mesh_overlay.py --resume
python scripts/ncbi/phase_2_pubchem_overlay.py --resume

# Verify the post-refresh state
python scripts/capture_scope_state.py
# → diff research-journal/shared/scope-state-snapshot.md against prior
```

All ingestion writes use `MERGE` keyed on `(entity_id, scope)` — re-running is idempotent.

## Data integrity invariants

The KG enforces these invariants. Anything that breaks one is a bug:

1. **Every node has `scope='shared'`** (or `tenant:<slug>` for tenant-scoped data — none currently). Verified by `_preflight_scope_check` at scoped_server startup.
2. **Every edge has `scope='shared'`**. Same preflight.
3. **Every node has `entity_id` (string)** as primary key.
4. **Every edge has `source_id`** identifying the loader (`duke:contains_compound`, `cmaup:plant_disease`, `hdi-safe-50:HDI-001`, etc.).
5. **No `scope IS NULL` rows** anywhere. Bootstrap migration enforces.
6. **Indexes**: workspace label, `(entity_id)`, `(scope)`, per-relationship-type `(scope)`, `pubchem_cid` and `mesh_uid` (Phase 1+2 enrichment).

## Citation guidance for paper Methods

```
Diet–compound–symptom–disease relationships were ingested into Neo4j Aura
from Dr. Duke's Phytochemical Database (Duke, 1992; CC0, version 2023-figshare),
FooDB (Wishart Lab, CC-BY-4.0), CMAUP v2.0 (Hou et al., 2024), SymMap 2.0
(Wu et al., 2019), HERB 2.0 (Fang et al., 2021), and a curated HDI-Safe-50
panel derived from NIH ODS, MSK About Herbs, and LiverTox.

Disease and symptom terminology was overlaid with NCBI MeSH UIDs via E-utilities
(2026-05-01). Compound entries were standardized against PubChem CID + synonyms
for the mission-scoped subset (compounds with TARGETS_PROTEIN or FOUND_IN_FOOD
participation, n≈1,200) via PubChem PUG-REST.

All entities and relationships carry a `scope='shared'` property; the KG is
served via a FastMCP gateway exposing 10 typed tools at https://kg-mcp-test.up.railway.app.
```

## See also

- [`mcp/README.md`](../mcp/README.md) — server capabilities, tool catalog, usage
- [`shrine-diet-bioactivity/data/manifest.yaml`](../shrine-diet-bioactivity/data/manifest.yaml) — per-source schema details
- [`research-journal/shared/scope-state-snapshot.md`](../research-journal/shared/scope-state-snapshot.md) — live Aura snapshot
- [`research-journal/plans/2026-05-01-ncbi-enrichment-and-entity-resolution-design.md`](../research-journal/plans/2026-05-01-ncbi-enrichment-and-entity-resolution-design.md) — Phase 0/1/2 plan
- [`docs/adr/0001-vector-storage-on-aura.md`](adr/0001-vector-storage-on-aura.md) — ADR on Aura-native vectors

## Phase 1 drug-bioactive bridge sources (added 2026-05-06)

These three sources back the new `compound_identity` and `bioactivity_evidence`
SQLite tables and the `BioactivityEvidence` LightRAG entity. See
[`docs/adr/0007-compound-identity-bridge.md`](adr/0007-compound-identity-bridge.md).

### ChEMBL 36

- **Source:** EBI ChEMBL — https://chembl.gitbook.io/chembl-interface-documentation/downloads
- **Version:** Release 36 (July 2025)
- **DOI:** 10.6019/CHEMBL.database.36
- **License:** CC BY-SA 3.0
- **Access:** [`chembl-downloader`](https://pypi.org/project/chembl-downloader/) (PyPI, MIT) auto-fetches and unpacks the SQLite dump.
- **Used by:** `shrine-diet-bioactivity/scripts/build_bioactivity_evidence.py`
- **Filters at ingest:** `assays.confidence_score >= 5`; `activities.pchembl_value >= 5.0`; `activities.standard_relation IN ('=', '<', '<=')`; `activities.standard_value IS NOT NULL`.

### UniChem source-mapping (EBI)

- **Source:** EBI UniChem — https://www.ebi.ac.uk/unichem/
- **Sources mapped:** `src_id` ∈ {1 (ChEMBL), 2 (DrugBank), 6 (KEGG), 7 (ChEBI), 22 (PubChem)}.
- **License:** Free, follows ChEMBL's CC BY-SA 3.0.
- **Used by:** `shrine-diet-bioactivity/scripts/build_compound_identity.py`
- **License note:** see [`shrine-diet-bioactivity/data/UNICHEM_LICENSE.md`](../shrine-diet-bioactivity/data/UNICHEM_LICENSE.md).

### PubChem PUG-REST

- **Source:** NCBI PubChem — https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
- **License:** Public Domain (US Gov).
- **Endpoint used:** `GET /compound/name/{name}/property/InChIKey,CanonicalSMILES/CSV`
- **Rate-limit policy:** ~4 req/s (under the 5/s soft cap) with on-disk JSON cache; 404s cached as negative results.
- **Used by:** `shrine-diet-bioactivity/scripts/build_compound_identity.py` (primary name → InChIKey resolution).

---

## Phase 3 schema additions (2026-05-08)

### `diseases_canonical` — unified disease registry

Sources: SymMap (MeSH/UMLS-anchored, 1,148 rows) + CTD (MeSH-anchored via stripping the `MESH:` prefix, 6,678 rows) + CMAUP `target_diseases` (bare names, alias-resolved when possible, 2,398 new) + HERB 2.0 `herb2_herb_disease.disease_label` (mostly Chinese-language bare names, 14,833 new).

License inheritance: same as upstream sources (CC BY-SA 3.0 from CTD; CC BY 4.0 from SymMap; CMAUP and HERB 2.0 academic-use).

### `compound_disease_evidence` — replaces `chemical_diseases`

Re-ingested from CTD with three signals the legacy loader dropped:
- `pubmed_ids` (CTD column 9, pipe-separated literature anchors)
- `inference_gene_symbol` (CTD column 6, mediating gene for inferred associations)
- explicit `evidence_type` (`direct_therapeutic` / `direct_marker` / `inferred_via_gene`) enforced by CHECK constraint

`chemical_diseases` is **DEPRECATED** as of 2026-05-08; will be dropped after one stable production cycle (≥1 week).
