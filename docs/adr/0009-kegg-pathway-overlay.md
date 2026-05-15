# ADR 0009: KEGG Pathway Overlay

**Date:** 2026-05-08
**Status:** Accepted
**Deciders:** dispatch-pvp run `20260508-kegg-pathways`
**Related:** ADR 0007 (compound-identity bridge), ADR 0008 (disease canonicalization)

## Context

After Phase 3 closed disease canonicalization, the only remaining doneness criterion from the original audit (§5.4) was *"Pathway-level rollup available — requires Phase 2 KEGG overlay."* This phase delivers that overlay.

Two concrete query patterns motivate the work:

1. **Mechanistic explanation for use case D.** Today the chain `food → compound → disease` has two paths (direct CMAUP target binding, gene-mediated CTD inference). Pathway membership is a third orthogonal evidence path that lets the agent layer cluster `compound→target` hits under human-readable pathway names instead of presenting them as a flat list of 50 protein names.
2. **Cross-evidence corroboration.** When ChEMBL says compound X targets protein Y *and* KEGG says pathway P contains protein Y *and* CTD says compound X is therapeutic for a disease in pathway P — that's a much stronger hypothesis than any single edge alone.

## Decision

Add three SQLite tables populated from the KEGG REST API:

- `kegg_pathways` — registry, ~370 human pathways
- `kegg_compound_pathways` — many-to-many compound↔pathway
- `kegg_pathway_genes` — pathway↔gene with HUGO symbol resolution

Plus LightRAG schema additions:

- `Pathway` entity (sources from `kegg_pathways`)
- `COMPOUND_IN_PATHWAY` relationship (lazy — joins through `compound_identity.kegg_compound_id`; activates when Phase 1 ingest runs)
- `PATHWAY_INCLUDES_TARGET` relationship (joins `targets.gene_symbol`; works without Phase 1)

The design is **self-contained**: KEGG ingest doesn't depend on Phase 1, and Phase 1 doesn't depend on KEGG. The two layers compose at query time when both are populated.

## Live-DB outcome

```
make build-kegg-pathways
→ 370 pathways
→ 10,556 compound-pathway links (9,008 reference-only pathways dropped — no hsa equivalent)
→ 39,340 pathway-gene links
→ 100% HUGO-symbol resolution (9,378 of 9,378 genes)
→ 455 pathway-target joins via gene_symbol
```

## Alternatives considered

- **Reactome instead of KEGG.** Rejected — KEGG has stronger compound-pathway coverage (small-molecule metabolism). Reactome is more cell-signaling focused; the two are complementary but adding both would dilute Phase 4's scope. Reactome is a Phase 5 candidate.
- **WikiPathways instead of KEGG.** Rejected — community-curated, less stable IDs, smaller compound coverage.
- **Cache KEGG data into a stable internal mirror.** Rejected for now — KEGG file URLs are stable and we cache responses on the dev box. If KEGG decommissions a public REST endpoint, we'll need to re-evaluate; the cached files work as a frozen artifact in the meantime.
- **Store KEGG pathway graph as Cypher in Neo4j directly.** Rejected — keeping the SQLite ground-truth pattern means the LightRAG entity extraction stays uniform with all other phases. Pathway as an entity gets ingested via `ainsert_custom_kg` like everything else.
- **Process all KEGG organisms (mouse, rat, etc.).** Rejected — `hsa` (human) is the only organism our use cases need today. Cross-species pathway data would multiply the table size 10x without proportional value.

## License posture (important)

KEGG is **academic-use-only**. Commercial deployment requires a license from Pathway Solutions, Inc. (https://www.kegg.jp/kegg/legal.html).

This phase is shipped with two safeguards:

1. **Build-time toggle:** `make build-kegg-pathways` is the only entry point that fetches KEGG data. Drop the target from CI and the rest of the build pipeline still works.
2. **Provenance documentation:** `docs/DATASET_PROVENANCE.md` includes a clear KEGG entry calling out the academic-only license.

For commercial deployments, the cleanest path is: skip `build-kegg-pathways`, leave the three KEGG tables empty, lose `Pathway`/`COMPOUND_IN_PATHWAY`/`PATHWAY_INCLUDES_TARGET` graph coverage, and either acquire a KEGG license or substitute Reactome/WikiPathways pathway data.

## Consequences

- **Wins:**
  - Use case D mechanistic chain `compound → pathway → gene → target → disease` is now navigable end-to-end.
  - 455 pathway-target joins on the live DB — agent layer can cluster compound-target hits by pathway.
  - 100% HUGO-symbol resolution gives clean joins to `targets.gene_symbol` (no fuzzy matching).
- **Trade-offs:**
  - Adds an academic-only data source. Commercial deployment story documented but adds friction.
  - 9,008 KEGG reference (`map`) pathways have no organism-specific (`hsa`) counterpart and were dropped at ingest. That's lost coverage; could be revisited if a downstream agent specifically requests reference-pathway data.
  - First-time ingest takes ~30 minutes (gene-symbol batch resolution). Re-runs hit cache and complete in under 1 second.

## Reproducibility

- Live ingest: `make build-kegg-pathways`
- Cache directory: `data_local/kegg_cache/` (gitignored; per-endpoint TSV files)
- Source data versions: KEGG REST is not version-pinned upstream; cache files capture the response at fetch time. Cache invalidation is a manual delete of the file.

## Schema invariants

- `kegg_pathways(id)` PK on the organism-prefixed pathway ID (e.g. `hsa01100`)
- `kegg_compound_pathways(kegg_compound_id, kegg_pathway_id)` ternary PK; FK on `kegg_pathway_id`
- `kegg_pathway_genes(kegg_pathway_id, kegg_gene_id)` PK; FK on `kegg_pathway_id`; `gene_symbol` may be NULL for unresolved genes (≤20% in spec acceptance)

## Related

- Spec: `docs/superpowers/specs/2026-05-08-kegg-pathway-overlay-design.md`
- Plan: `.claude/runs/20260508-kegg-pathways/plan.md`
- Audit closeout: `docs/KG_COMPLETENESS_AUDIT.md` Phase 4 section
