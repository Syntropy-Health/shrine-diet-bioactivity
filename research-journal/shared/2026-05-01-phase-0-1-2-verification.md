# Phase 0/1/2 Verification — 2026-05-01

Verified directly against Aura at workspace `unified_diet_kg`, scope=`shared`.
Cypher used here mirrors the predicates in `lightrag/scoped_server.py`.

## Phase 0 — HDI alias-resolved /hdi_check

| Drug | Herb (alias form) | Result |
|---|---|---|
| `Warfarin` | `St. John's Wort` | severity=severe, mechanism=CYP450 |
| `warfarin` | `Hypericum perforatum` | severity=severe, mechanism=CYP450 |
| `Warfarin` | `Ginkgo biloba` | severity=severe, mechanism=coagulation |

All three resolve through the alias predicate. Pre-Phase-0 the panel rejected lowercase + Latin name lookups.

## Phase 1 — MeSH overlay (Disease + Symptom)

| Label | Total | MeSH-tagged | Coverage |
|---|---:|---:|---:|
| Disease | 2,976 | 2,068 | 69.5% |
| Symptom | 3,334 | 927 | 27.8% |

Match rate is upstream-bound. TCM-specific symptoms (e.g., bilingual SymMap entries) often have no MeSH equivalent.

## Phase 2 — PubChem overlay (Compound)

- Total Compound nodes: **120,217**
- With `pubchem_cid` stamped: **11,535**
- Mission-critical (TARGETS_PROTEIN-active + pubchem_cid): **1,095** of ~1,156 attempted (94% match rate)

### Alias-resolved /traverse seed (Compound)

| Seed | Resolves to |
|---|---|
| `curcumin` | CURCUMIN (CID 969516), Curcumin (CID 969516) |
| `Curcumin` | CURCUMIN (CID 969516), Curcumin (CID 969516) |
| `CURCUMIN` | CURCUMIN (CID 969516), Curcumin (CID 969516) |
| `tryptophan` | Tryptophan (CID 6305), TRYPTOPHAN (CID 6305) |

Lowercase seeds — which previously failed casing-sensitive matches in /traverse — now resolve via PubChem-derived aliases.
