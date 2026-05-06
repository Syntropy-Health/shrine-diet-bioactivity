# Runbook — drug-bioactive-bridge

Living document of items needing human attention. Stubs are append-only; the orchestrator marks them `done-auto` only on a future re-run that resolves them.

---

## harden-plan/data/missing-smiles-column — compounds table has no SMILES column

- **Status:** needs-human (architectural; patched in plan)
- **Why:** Probe of `data_local/herbal_botanicals.db` `compounds` table revealed columns `id, name, name_normalized, cas_number, pubchem_cid, compound_class, bioactivities` — no `smiles`. The original Duke import did not preserve structure data.
- **Impact on Phase 1:** RDKit-from-SMILES is no longer the primary identity path. Plan re-architected to use PubChem PUG-REST name→InChIKey resolution as primary, with RDKit retained only to verify InChIKeys when PubChem returns SMILES.
- **Hand-off steps for full SMILES enrichment (Phase 2):**
  1. Download Duke source CSVs (already in `data/duke-source-csv.zip`); confirm SMILES column exists in raw CSVs.
  2. Add SMILES enrichment step to `scripts/build-herbal-db.ts` so future rebuilds populate `compounds.smiles`.
  3. Alternative: backfill SMILES from PubChem by querying `/compound/cid/{cid}/property/CanonicalSMILES/TXT` for each compound's resolved CID after the name-resolution pass.
- **Logfire trace:** spans.jsonl@offset=0 (no Logfire MCP configured in this run)

## harden-plan/data/empty-pubchem-cid-column — compounds.pubchem_cid is 100% NULL

- **Status:** needs-human (data backfill)
- **Why:** Column exists, is TEXT typed, but `SELECT COUNT(pubchem_cid) FROM compounds` = 0 across all 94,512 rows. Was reserved during schema design but never populated.
- **Impact on Phase 1:** Cannot use `pubchem_cid`-direct path; all CIDs must come from name resolution. This is the single biggest cost driver for the bridge build (~94K names × ~250ms = ~6.5h one-time, before scope-reduction).
- **Hand-off steps:** populate this column as a side effect of `scripts/build_compound_identity.py` once it runs at full scale (Phase 2 — full backfill). Phase 1 only resolves the active subset.
- **Logfire trace:** spans.jsonl@offset=1

## harden-plan/python-pkg/rdkit-and-chembl-downloader-not-installed

- **Status:** auto-fixable in Task 0 (no human action needed unless install fails)
- **Why:** `python3 -c "import rdkit"` and `import chembl_downloader` both fail. Trivial install.
- **Hand-off steps:** none expected; if `pip install rdkit-pypi chembl-downloader httpx` fails (e.g. on minimal containers without `libxrender1`), install OS deps: `apt-get install -y libxrender1 libxext6` then retry pip.
- **Logfire trace:** spans.jsonl@offset=2

## harden-plan/code/lightrag-not-a-package

- **Status:** patched in plan (auto-resolved in Task 0 step 4 — adds `__init__.py`)
- **Why:** `lightrag/` directory has no `__init__.py`. Existing scripts (`ingest_unified.py`, `entity_schema.py`) import each other via flat name (`from entity_schema import …`). My original plan used `from lightrag.identity_bridge import …` which would have failed.
- **Patch:** Task 0 adds an empty `lightrag/__init__.py` so the package-style imports work without breaking the existing flat imports (a flat `from entity_schema import …` still works inside the package because pytest adds the dir to sys.path).
- **Logfire trace:** spans.jsonl@offset=3

## harden-plan/scope/full-94k-name-resolution-deferred

- **Status:** needs-human (scope decision documented; user approved D-hybrid which permits this scope cut)
- **Why:** 94,512 compounds × ~250ms PubChem PUG-REST roundtrip ≈ 6.5h one-time job (assuming 100% cache miss). With realistic retry/failure budget, easily 12–24h. Not viable in a single PR.
- **Phase 1 scope:** resolve only compounds in active relationships:
  - `herb_compounds` (24,469 distinct) ∪ `compound_targets` (1,232 distinct) → ~25K names → ~1.7h at 4 req/s, halved with parallelism + cache.
- **Hand-off steps for full backfill (Phase 2):**
  1. After Phase 1 lands and bridge proves out, run `make build-identity FULL=1` (flag to be added) for the remaining ~70K.
  2. Or run nightly cron for incremental fill.
- **Logfire trace:** spans.jsonl@offset=4
