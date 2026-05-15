# ADR 0008: Disease Canonicalization

**Date:** 2026-05-08
**Status:** Accepted
**Deciders:** dispatch-pvp run `20260508-disease-canonicalization`
**Supersedes:** N/A
**Related:** ADR 0007 (compound-identity bridge — same architectural family of "promote to first-class entity")

## Context

Through the Phase 1 + Phase 2 work (PRs #19–#23), the KG accumulated three independent free-text disease columns that all referred to the same conceptual entities:

- `chemical_diseases.disease_name` (CTD; 6,678 distinct strings)
- `target_diseases.disease_name` (CMAUP; 2,976 distinct strings)
- `symptom_disease_map.disease_name` (SymMap-matched; 40 strings)

These overlap heavily — "Diabetes Mellitus", "Hypertension", "Inflammation" all appear in 2+ surfaces — but they were siloed. Cross-source queries had to resort to free-text `LIKE`, defeating the formal-ontology benefit of having MeSH/UMLS/ICD-10 IDs in the source data.

Plus the CTD loader silently dropped two high-value signals: `PubMedIDs` (per-row literature anchors, 1–50 per pair) and `InferenceGeneSymbol` (the gene mediating an inferred association). Both are direct enablers of use-case-A "evidence-graded recommendation" queries.

## Decision

Promote `Disease` to a first-class unified entity:

1. **`diseases_canonical`** — registry of one row per real-world disease concept, keyed by formal-ID priority (MeSH → UMLS → ICD-10 → local-slug fallback).
2. **`disease_name_aliases`** — every observed disease string from any source, joined back to canonical via PK `(disease_id, alias, source)`.
3. **`compound_disease_evidence`** — replaces `chemical_diseases`; explicit `evidence_type` column (`direct_therapeutic` / `direct_marker` / `inferred_via_gene`) enforced by CHECK constraint; preserves `pubmed_ids` and `inference_gene_symbol`.

Migration is non-destructive: legacy `chemical_diseases` stays populated alongside `compound_disease_evidence` for one stable production cycle. No drop in this PR.

## Live-DB outcome (executed during the PR)

- **24,403 canonical disease entities** (5,351 with MeSH, 855 with UMLS)
- **29,075 disease-name aliases** across 4 sources
- **2,922,025 compound_disease_evidence rows** (vs 934K in legacy `chemical_diseases` — captures inferred-via-gene that legacy filter dropped)
- **2,756,378 rows preserve PubMed citations** (94% citation fill rate)
- **2,892,760 rows carry `inference_gene_symbol`** for mechanistic chain (compound → gene → disease)

## Alternatives considered

- **Free-text fuzzy matching to merge concepts.** Rejected — risks merging distinct diseases (e.g., "Hypertension" vs "Pulmonary Hypertension") whose MeSH IDs differ. Canonicalization is by formal-ID equality only; bare-name aliases never auto-merge canonical rows.
- **External disease ontology (DOID, MONDO).** Out of scope for this PR. SymMap + CTD already provide MeSH/UMLS for the diseases we touch; integrating a third ontology adds complexity without clear use-case benefit yet.
- **Dropping `chemical_diseases` immediately.** Rejected — the dual-write parallel-cycle keeps existing queries working during the migration. Drop scheduled for a follow-up PR after one stable production cycle.
- **Promoting `Symptom` similarly to canonical.** Out of scope. The 47 hand-curated symptoms are already a small intentional taxonomy; canonicalizing them would add complexity without addressing a real query bottleneck.

## Consequences

- **Wins:**
  - Cross-source disease queries are now indexed equality joins (was: free-text `LIKE`).
  - Use case A doneness criterion ("top-10 ranked food results have ≥1 PubMed citation") is achievable — 94% citation fill rate on the new evidence layer.
  - Use case D's mechanistic chain (compound → gene → target → disease) becomes navigable: 2.89M `inferred_via_gene` rows join through `targets.gene_symbol`.
  - Disease entity in LightRAG renders with full ontology cross-refs (MeSH/UMLS/ICD-10/HPO) instead of bare names.
- **Trade-offs:**
  - CTD ingest doubles in time (60s → 1m 39s — measured). Acceptable.
  - Schema gains 3 tables + 6 indexes; ~1.5GB additional disk for the populated CDE rows.
  - HERB 2.0 contributed 14,833 mostly-Chinese disease names with no formal IDs (local-slug fallback). They're searchable by alias but don't participate in cross-ontology joins. Phase 3.5 candidate: harvest English translations.

## Reproducibility

- Canonicalization run: `make build-disease-canonical`
- CTD re-ingest: `make load-ctd`
- Source data versions: CTD downloads from `ctdbase.org/reports/` (not version-pinned upstream; we capture file size + timestamp at download).

## Schema invariants

- `diseases_canonical(mesh_id)` UNIQUE WHERE NOT NULL — no two canonical rows share a MeSH ID
- `diseases_canonical(umls_id)` UNIQUE WHERE NOT NULL — same for UMLS
- `compound_disease_evidence` CHECK: `evidence_type='inferred_via_gene'` ⇒ `inference_score IS NOT NULL`; `evidence_type IN ('direct_therapeutic','direct_marker')` ⇒ both inference fields NULL
- `disease_name_aliases.disease_id` REFERENCES `diseases_canonical(id)` — orphans rejected at insert time when `PRAGMA foreign_keys = ON`

## Related

- Spec: `docs/superpowers/specs/2026-05-08-disease-canonicalization-design.md`
- Plan: `.claude/runs/20260508-disease-canonicalization/plan.md` (hardened)
- Audit closeout: `docs/KG_COMPLETENESS_AUDIT.md` Phase 3 section
