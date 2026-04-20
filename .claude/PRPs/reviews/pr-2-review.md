# PR Review: #2 — feat: mcp-herbal-botanicals — phytochemical knowledge graph MCP server

**Reviewed**: 2026-04-09
**Author**: supmo668
**Branch**: feature/mcp-herbal-botanicals → main
**Decision**: APPROVE with comments

## Summary

Solid implementation of a first-of-kind phytochemical MCP server with 11 tools, comprehensive test coverage (29/29), and thorough documentation. No security vulnerabilities found. Three minor performance/style items noted as non-blocking.

## Findings

### CRITICAL
None

### HIGH
None

### MEDIUM

1. **N+1 query in `findFunctionalFoods`** — `HerbalDBAdapter.ts:486-503`
   - For each matching herb, a separate SQL query fetches top foods. With `pageSize=20`, this is 20 queries.
   - Non-blocking: acceptable at current data scale. Can be consolidated with a CTE in a future optimization pass.

### LOW

1. **Hardcoded `'__none__'` SQL fallback** — `HerbalDBAdapter.ts:401`
   - When `herbIds` is empty, `'__none__'` is interpolated into SQL. Not injectable (hardcoded constant), but mixes interpolation with parameterized queries. Use `WHERE 1=0` or early return instead.

2. **Unvalidated `dbPath` constructor parameter** — `HerbalDBAdapter.ts:39`
   - Accepts any path. Only reachable from tests (MCP server uses default). DB opened readonly, so even worst case is read-only file access. Consider removing param or adding path validation.

## Validation Results

| Check | Result |
|---|---|
| Type check | Skipped (pre-existing rootDir config issue unrelated to this PR) |
| Lint | Skipped (no lint script configured) |
| Tests | Pass (29/29) |
| Build | Pass |
| Security scan | Pass (no CRITICAL/HIGH findings) |

## Files Reviewed

| File | Type | Change |
|------|------|--------|
| `src/index.ts` | Source | Modified — 3 new MCP tools |
| `src/HerbalDBAdapter.ts` | Source | Modified — 3 new query methods |
| `src/types.ts` | Source | Modified — 6 new interfaces |
| `scripts/migrate-kg-expansion.ts` | Source | Added — schema migration + data seeding |
| `scripts/build-herbal-db.ts` | Source | Added — ETL pipeline |
| `scripts/download-sources.ts` | Source | Added — data download |
| `scripts/decompress-datasets.ts` | Source | Added — archive extraction |
| `scripts/audit-herbal-data.ts` | Source | Added — data quality audit |
| `src/__tests__/kg-expansion.test.ts` | Test | Added — 12 tests |
| `src/__tests__/db-integration.test.ts` | Test | Added — 17 tests |
| `src/__tests__/normalize.test.ts` | Test | Added — 5 tests |
| `package.json` | Config | Added |
| `tsconfig.json` | Config | Added |
| `vitest.config.ts` | Config | Added |
| `.mcp.json` (×2) | Config | Added |
| `.gitignore` | Config | Added |
| `README.md` | Docs | Added |
| `CLAUDE.md` | Docs | Added |
| `docs/data-sources-catalog.md` | Docs | Added |
| `docs/kg-architecture-design.md` | Docs | Added |
| `docs/data-audit-results.md` | Docs | Added |
| `.claude/PRPs/*` | Docs | Added — PRD, plans, reports |
