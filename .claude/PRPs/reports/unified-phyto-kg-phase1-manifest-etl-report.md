# Implementation Report: Data Manifest & Multi-Source ETL Pipeline

## Summary
Created a unified data manifest (YAML) for 7 Tier-1 phytochemical datasets, extended the ETL pipeline with download scripts for CMAUP and TTD, built loader scripts for CMAUP/CTD/TTD data integration, added 3 new MCP tools (search-diseases, get-target-diseases, get-chemical-diseases), cloned Graphiti as a git submodule with Python configuration for local embeddings and Railway Neo4j, and created a comprehensive Neo4j visualization guide.

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | 7/10 | 8/10 |
| Files Changed | 12-15 | 18 |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | Create data manifest (manifest.yaml) | ✅ Complete | 7 datasets + 4 deferred documented |
| 2 | Extend download script for CMAUP + TTD | ✅ Complete | 7 new download targets added |
| 3 | Create CMAUP loader script | ✅ Complete | Targets, compound-targets, plant-diseases |
| 4 | Create CTD loader script | ✅ Complete | Chemical-diseases, chemical-phenotypes with gzip streaming |
| 5 | Create TTD loader script | ✅ Complete | Druggability status enrichment |
| 6 | Create orchestrator migration | ✅ Complete | Single entry point for all sources |
| 7 | Update types and adapter | ✅ Complete | Deviated — used `evidence_layer` column name from existing schema |
| 8 | Register new MCP tools | ✅ Complete | 3 new tools (14 total) |
| 9 | Clone Graphiti submodule | ✅ Complete | v0.28.2+ at repo root |
| 10 | Create Graphiti config | ✅ Complete | config.py, .env.example, requirements.txt |
| 11 | Create Graphiti ingestion script | ✅ Complete | Dry-run mode, batch ingestion, subset limits |
| 12 | Create Neo4j visualization guide | ✅ Complete | Cloud + local setup, Cypher examples, comparison table |
| 13 | Update package.json + write tests | ✅ Complete | 4 new npm scripts, 10 new tests |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | ✅ Pass | `npx tsc --noEmit` — zero errors |
| Unit Tests | ✅ Pass | 36 passed, 3 properly skipped (CMAUP-dependent) |
| Build | ✅ Pass | `npm run build` succeeds |
| Integration | N/A | Data download required for full integration validation |
| Edge Cases | ✅ Pass | Missing tables handled gracefully via tableExists() |

## Files Changed

| File | Action | Lines |
|---|---|---|
| `mcp-herbal-botanicals/data/manifest.yaml` | CREATED | +220 |
| `mcp-herbal-botanicals/scripts/download-sources.ts` | UPDATED | +60 |
| `mcp-herbal-botanicals/scripts/load-cmaup.ts` | CREATED | +130 |
| `mcp-herbal-botanicals/scripts/load-ctd.ts` | CREATED | +170 |
| `mcp-herbal-botanicals/scripts/load-ttd.ts` | CREATED | +150 |
| `mcp-herbal-botanicals/scripts/migrate-multi-source.ts` | CREATED | +120 |
| `mcp-herbal-botanicals/src/types.ts` | UPDATED | +25 |
| `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | UPDATED | +120 |
| `mcp-herbal-botanicals/src/index.ts` | UPDATED | +80 |
| `mcp-herbal-botanicals/src/__tests__/multi-source.test.ts` | CREATED | +95 |
| `mcp-herbal-botanicals/package.json` | UPDATED | +5 |
| `mcp-herbal-botanicals/graphiti/config.py` | CREATED | +50 |
| `mcp-herbal-botanicals/graphiti/ingest.py` | CREATED | +230 |
| `mcp-herbal-botanicals/graphiti/requirements.txt` | CREATED | +4 |
| `mcp-herbal-botanicals/graphiti/.env.example` | CREATED | +20 |
| `docs/graphiti-neo4j-guide.md` | CREATED | +200 |
| `.gitmodules` | UPDATED | +3 |
| `graphiti/` | CREATED (submodule) | - |

## Deviations from Plan

1. **Column name mismatch**: The existing `target_diseases` table uses `evidence_layer` not `evidence`. Updated adapter queries to use `SELECT td.evidence_layer as evidence` for consistency with the TypeScript interface.
2. **No `druggability_status` on targets**: The existing targets table doesn't have this column yet (added by TTD loader during migration). Removed from `TargetDisease` type since it's a target property, not a join column.
3. **Table existence guards**: Added `tableExists()` and `emptyPaginated()` helper methods to gracefully handle queries against tables that haven't been created yet (e.g., `chemical_diseases` before CTD migration runs).

## Issues Encountered

1. **Tests failing on missing tables**: `chemical_diseases` and `target_diseases` queries failed because the tables either don't exist or have different column names than expected. Resolved by adding `tableExists()` guards and fixing column names to match the actual schema.
2. **Background agent rate-limited**: Initial Graphiti and dataset research agents hit 429 errors. Resolved by retrying.

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `src/__tests__/multi-source.test.ts` | 10 tests (7 active, 3 CMAUP-dependent skipped) | searchDiseases, getTargetDiseases, getChemicalDiseases, getStats new fields, pagination |
| `src/__tests__/kg-expansion.test.ts` | 12 tests (existing, updated to skipIf) | KG expansion coverage |
| `src/__tests__/db-integration.test.ts` | 10 tests (existing, updated to skipIf) | Core adapter coverage |

## Next Steps
- [ ] Download CMAUP data: `npm run download-cmaup`
- [ ] Download TTD data: `npm run download-ttd`
- [ ] Download CTD data manually from https://ctdbase.org/downloads/
- [ ] Run multi-source migration: `npm run migrate-multi-source`
- [ ] Set Neo4j password in `graphiti/.env`
- [ ] Start LM Studio with embedding model
- [ ] Run Graphiti ingestion: `cd graphiti && python ingest.py --dry-run`
- [ ] Code review via `/code-review`
- [ ] Create PR via `/prp-pr`
