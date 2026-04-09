# Code Review: KG Expansion — Local Changes

**Reviewed**: 2026-04-08
**Branch**: feature/mcp-herbal-botanicals
**Decision**: APPROVE with comments

## Summary

Clean implementation following existing patterns exactly. 386 lines added across 5 modified files + 2 new files. All changes are additive — no regressions to existing functionality. 3 MEDIUM issues found, 0 CRITICAL or HIGH.

## Findings

### CRITICAL
None

### HIGH
None

### MEDIUM

1. **SQL injection surface in `searchBySymptom`** — `HerbalDBAdapter.ts:381-386`
   - Dynamic `IN (${placeholders})` construction uses `.map(() => '?').join(',')` which is safe (parameterized).
   - However, the fallback `'__none__'` string literal at line 403 for empty herbIds is injected directly. This is safe because it's a hardcoded constant, not user input, but consider using `WHERE 1=0` instead for clarity.
   - **Severity**: MEDIUM (no actual vulnerability, style concern)

2. **N+1 query in `findFunctionalFoods`** — `HerbalDBAdapter.ts:486-503`
   - For each food herb, a separate query fetches top foods sharing compounds.
   - With `pageSize=20`, this is 20 additional queries. Acceptable for the data scale but could be consolidated into a single CTE-based query for better performance.
   - **Severity**: MEDIUM (performance, not correctness)

3. **`GROUP_CONCAT` in subquery may not be limited** — `HerbalDBAdapter.ts:472`
   - `GROUP_CONCAT(DISTINCT c.name)` inside a subquery with `LIMIT 10` — the LIMIT applies to the outer SELECT, not the GROUP_CONCAT. For herbs with hundreds of compounds, this could produce very long strings.
   - Already mitigated by `.slice(0, 10)` on the result, but the DB still concatenates all names.
   - **Severity**: MEDIUM (minor performance)

### LOW

1. **Hardcoded food plant lists in migration** — `migrate-kg-expansion.ts:95-138`
   - Food plant classification uses static Sets of known food/edible plant names. This is documented as a placeholder until CMAUP data is available, which is the correct approach.
   - Consider adding a comment noting these will be replaced by CMAUP classification.

2. **`page` parameter unused in `searchBySymptom`** — `HerbalDBAdapter.ts:354`
   - The `page` and `pageSize` params are accepted but only `pageSize` is used for the herbs LIMIT. The symptom results themselves aren't paginated. This matches the intent (paginate herbs, not symptoms) but the param names could be misleading.

## Validation Results

| Check | Result |
|---|---|
| Type check | ⏭️ Skipped (pre-existing rootDir issue) |
| Lint | ⏭️ No lint script configured |
| Tests | Pass (29/29) |
| Build | Pass |
| MCP Integration | Pass (11 tools registered, all respond) |

## Files Reviewed

| File | Change | Lines |
|---|---|---|
| `src/types.ts` | Modified | +61 |
| `src/HerbalDBAdapter.ts` | Modified | +234 |
| `src/index.ts` | Modified | +82 |
| `package.json` | Modified | +1 |
| `tsconfig.json` | Modified | +1/-1 |
| `scripts/migrate-kg-expansion.ts` | Added | +350 |
| `src/__tests__/kg-expansion.test.ts` | Added | +109 |

## Pattern Compliance

- Zod schemas: Match existing pattern (top-level const, `.shape` passed to tool)
- Tool registration: Exact 5-arg pattern match
- Adapter methods: Follow existing pagination and query patterns
- Test structure: Mirrors `db-integration.test.ts` exactly
- Return shapes: Consistent `{ content: [...], structuredContent: {...} }` pattern
