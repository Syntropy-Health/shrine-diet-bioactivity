# ADR 0007: Compound identity bridge + ChEMBL evidence layer

**Date:** 2026-05-06
**Status:** Accepted
**Deciders:** dispatch-pvp Phase 1 of `pvp/20260506-013000-drug-bioactive-bridge`

## Context

The KG holds ~94K compounds across multiple sources (Duke, FooDB, CMAUP, CTD, TTD)
with no shared structural identifier. Probe of `data_local/herbal_botanicals.db`
(May 2026) shows the `compounds` table contains **no SMILES column at all** and
**zero populated `pubchem_cid`** rows out of 94,512. Without a normalized
identity layer, we cannot join measured drug-target evidence (ChEMBL) into the
same graph that holds dietary occurrence (FooDB).

This blocks the two priority user-facing query patterns:
- **A. Symptom → food** (evidence-graded food-as-medicine)
- **D. Diet → predicted physiological effects** (mechanistic diet scoring)

## Decision

Build a `compound_identity` SQLite table populated by:

1. **PubChem PUG-REST** `/compound/name/{name}/property/InChIKey,CanonicalSMILES`
   as the **primary** path, with disk-cached JSON.
2. **RDKit** `MolToInchiKey` to **verify** InChIKeys when PubChem returns a
   SMILES (also future-proofs a SMILES backfill).
3. **UniChem** source-mapping files (offline) for ChEMBL/KEGG/ChEBI/DrugBank
   cross-refs.

Then load ChEMBL bioactivities as a new `BioactivityEvidence` entity in
LightRAG with two new edges:
- `Compound HAS_EVIDENCE BioactivityEvidence` (with `pchembl`, `activity_type` props)
- `BioactivityEvidence EVIDENCE_FOR_TARGET Target` (with `confidence_score`, `year` props)

**Phase 1 scope:** ~25K active compounds (in `herb_compounds` ∪ `compound_targets`).
Full 94K backfill is Phase 2.

**MCP surface:** zero new tools. The existing thin-adapter primitives
(`semantic-search`, `get-entity`, `get-subgraph`, `list-labels`) surface the
new entity types automatically once they are in Neo4j. Adding a use-case-style
tool would have violated the `FORBIDDEN_USECASE_VERBS` guard in
`shrine-diet-bioactivity/src/tools.ts`.

## Alternatives considered

- **Full ChEMBL mirror.** Rejected — multi-GB ingest, mostly drug rows with no
  dietary relevance.
- **Open Targets disease-anchored slice.** Deferred to Phase 2.
- **Online-only PubChem resolver for everything.** Adopted by necessity (no
  SMILES locally). Mitigated by aggressive disk caching and active-subset scoping.
- **SMILES-first via RDKit.** Original plan, invalidated by the schema probe —
  no SMILES exist in the local DB.
- **New MCP tool surface for evidence queries.** Rejected — violates thin-adapter
  architecture per `src/tools.ts`.

## Consequences

- ChEMBL release pin (release 36) is part of reproducibility
  (recorded in `docs/DATASET_PROVENANCE.md`).
- PubChem cache becomes a regenerable but slow-to-rebuild artifact
  (~1.5 h cold for 25K names at 4 req/s).
- Coverage <50% on cross-refs is logged as a WARNING in build script output
  and surfaced in the runbook — does not block ingest.
- Future SMILES enrichment can land as a side-effect of running PubChem
  resolution to full backfill (Phase 2): `compounds.smiles` populated from
  PubChem `CanonicalSMILES` returns.
- KEGG enters as overlay-only (a `kegg_compound_id` column on
  `compound_identity`) — no Pathway entity in Phase 1.

## Related

- Spec: `docs/superpowers/specs/2026-05-06-drug-bioactive-bridge-design.md`
- Plan: `.claude/runs/20260506-013000-drug-bioactive-bridge/plan.md`
- Runbook: `.claude/runs/20260506-013000-drug-bioactive-bridge/runbook.md`
