# Runbook — disease-canonicalization

Living document of items needing human attention. Stubs are append-only.

---

## Phase 3 spec patches landed at harden-plan (2026-05-08)

No `[needs-human]` items at hardening time. Two minor architecture corrections were patched directly into plan.md (no runbook stub needed):

1. **`herb2_herb_disease.disease` → `disease_label`**: spec assumed a column name that doesn't exist; live schema uses `disease_label` + `disease_id` + `source_pmid`. Plan §Task 3 updated. Bonus: `source_pmid` is per-row PubMed evidence we can route through `disease_name_aliases` later for full provenance.

2. **CTD empty-string vs NULL `direct_evidence`**: probe revealed 906,247 of 934,070 rows store `''` (not NULL) when no direct evidence exists. Plan §Task 4 evidence_type classifier updated to handle both as the "inferred" case.

Both patches are zero-risk corrections to factual assumptions that would have caused mid-execution skips (silent data loss).

## Anticipated Phase 3.5 follow-up

`source_pmid` in `herb2_herb_disease` is a per-row PubMed ID that complements CTD's `pubmed_ids`. This PR routes it through `disease_name_aliases` only as text (no structured citation column on alias rows). A small future PR could add a parallel `compound_disease_evidence`-style row for HERB 2.0 herb→disease evidence with structured citation handling. Out of scope here.
