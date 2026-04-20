# Plan: Multi-Tenant Query Gateway (Phase 3)

## Summary
Add tenant-aware middleware to the MCP server so every tool call enforces scope isolation. The `semantic-search` tool injects a scope filter into LightRAG queries (shared + tenant-scoped data). SQLite tools continue to serve shared data only (they have no tenant data). A `tenant_id` is extracted from the MCP request's `_meta` field and validated before any query executes.

## User Story
As an AI agent acting on behalf of a longevity wellness clinic,
I want my MCP tool calls to only return shared dietary KG data plus my clinic's proprietary data,
So that my recommendations reflect both published science and my clinic's experience without leaking other tenants' data.

## Problem → Solution
Currently all 15 MCP tools see all data identically with zero tenant awareness → After this phase, `semantic-search` enforces `scope = 'shared' OR scope = 'tenant:{id}'` on every LightRAG query, and a future Phase 4 ingestion path will write tenant-scoped data that is invisible to other tenants.

## Metadata
- **Complexity**: Medium
- **Source PRD**: `.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md`
- **PRD Phase**: Phase 3 — Query Gateway
- **Estimated Files**: 5-7

---

## UX Design

N/A — internal change. No user-facing UI transformation. The MCP protocol interface is unchanged from the agent's perspective except that agents now pass `tenant_id` in `_meta`.

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| MCP tool call | No `_meta.tenant_id` | Agent passes `{ _meta: { tenant_id: "clinic_a" } }` | Optional — omitted = shared-only |
| semantic-search response | Returns all KG data | Returns shared + tenant-scoped data only | Scope filter injected into LightRAG POST body |
| SQLite tool response | Returns all shared data | Returns all shared data (unchanged) | SQLite has no tenant data — no filtering needed |

---

## Mandatory Reading

Files that MUST be read before implementing:

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 (critical) | `mcp-herbal-botanicals/src/index.ts` | 100-175 | Tool registration pattern: `this.server.tool(name, desc, schema, opts, handler)` with `errorContent()` |
| P0 (critical) | `mcp-herbal-botanicals/src/index.ts` | 473-543 | `semantic-search` tool handler — the LightRAG bridge that needs scope injection |
| P0 (critical) | `mcp-herbal-botanicals/src/index.ts` | 113-150 | `HerbalBotanicalsMCPServer` class constructor and `registerTools()` entry point |
| P1 (important) | `mcp-herbal-botanicals/src/types.ts` | all | TypeScript interfaces — add TenantContext here |
| P1 (important) | `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | 1-30 | DB adapter constructor pattern |
| P1 (important) | `mcp-herbal-botanicals/src/__tests__/db-integration.test.ts` | 1-60 | Test patterns: `describe.skipIf`, `beforeAll`/`afterAll`, vitest imports |
| P2 (reference) | `mcp-herbal-botanicals/lightrag/entity_schema.py` | 1-50 | Entity types and scope metadata (Python side, for context) |
| P2 (reference) | `mcp-herbal-botanicals/node_modules/@modelcontextprotocol/sdk/dist/esm/shared/protocol.d.ts` | 170-200 | `RequestHandlerExtra` type — `_meta`, `authInfo`, `sessionId` |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| MCP `_meta` field | MCP spec draft `/specification/draft/basic/index#meta` | `_meta` is an open record on all requests; clients can pass arbitrary keys; servers receive it via `extra._meta` in tool handlers |
| MCP tool handler signature | `@modelcontextprotocol/sdk` ^1.12.1 | `ToolCallback<Args> = (args: ShapeOutput<Args>, extra: RequestHandlerExtra) => ...` — `extra._meta` is `Record<string, unknown> \| undefined` |
| LightRAG POST /query | LightRAG API | Body: `{ query, mode, top_k }` — no native scope parameter; must be added as custom field or post-filter |

---

## Patterns to Mirror

Code patterns discovered in the codebase. Follow these exactly.

### TOOL_REGISTRATION
```typescript
// SOURCE: mcp-herbal-botanicals/src/index.ts:154-177
this.server.tool(
  'search-herbs',
  `Search herbs and botanicals by common name...`,
  SearchHerbsSchema.shape,
  { title: 'Search herbs by name', readOnlyHint: true },
  async (args) => {
    try {
      const result = this.db.searchHerbs(args.query, args.page, args.pageSize);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        structuredContent: { result },
      };
    } catch (error: unknown) {
      return errorContent(error);
    }
  }
);
```

### ERROR_HANDLING
```typescript
// SOURCE: mcp-herbal-botanicals/src/index.ts:104-107
function errorContent(error: unknown): { content: Array<{ type: 'text'; text: string }>; isError: true } {
  const message = error instanceof Error ? error.message : 'Internal database error';
  return { content: [{ type: 'text', text: message }], isError: true };
}
```

### SEMANTIC_SEARCH_BRIDGE
```typescript
// SOURCE: mcp-herbal-botanicals/src/index.ts:499-533
const rawUrl = process.env.LIGHTRAG_API_URL || 'http://localhost:9621';
let parsedUrl: URL;
try {
  parsedUrl = new URL('/query', rawUrl);
} catch {
  return { content: [{ type: 'text', text: 'Invalid LIGHTRAG_API_URL configuration' }], isError: true };
}
if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
  return { content: [{ type: 'text', text: 'LIGHTRAG_API_URL must use http or https' }], isError: true };
}
const response = await fetch(parsedUrl.toString(), {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: args.query,
    mode: args.mode,
    top_k: args.top_k,
  }),
  signal: AbortSignal.timeout(30_000),
});
```

### ZOD_SCHEMA
```typescript
// SOURCE: mcp-herbal-botanicals/src/index.ts:29-33
const SearchHerbsSchema = z.object({
  query: z.string().min(1, 'Search query must not be empty'),
  page: z.number().min(1).optional().default(1),
  pageSize: z.number().min(1).max(50).optional().default(10),
});
```

### TEST_STRUCTURE
```typescript
// SOURCE: mcp-herbal-botanicals/src/__tests__/db-integration.test.ts:1-18
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as path from 'path';
import * as fs from 'fs';
import { HerbalDBAdapter } from '../HerbalDBAdapter.js';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const DB_EXISTS = fs.existsSync(DB_PATH);

describe.skipIf(!DB_EXISTS)('HerbalDBAdapter integration tests', () => {
  let db: HerbalDBAdapter;
  beforeAll(() => { db = new HerbalDBAdapter(DB_PATH); });
  afterAll(() => { db?.close(); });
  // ...
});
```

### INTERFACE_DEFINITION
```typescript
// SOURCE: mcp-herbal-botanicals/src/types.ts:1-14
export interface Herb {
  id: string;
  scientific_name: string;
  common_name: string | null;
  family: string | null;
  // ...
}
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `mcp-herbal-botanicals/src/types.ts` | UPDATE | Add `TenantContext` interface |
| `mcp-herbal-botanicals/src/tenant.ts` | CREATE | Tenant extraction + validation utility (pure functions, testable) |
| `mcp-herbal-botanicals/src/index.ts` | UPDATE | Extract tenant context in `semantic-search` handler; inject scope into LightRAG POST body |
| `mcp-herbal-botanicals/src/__tests__/tenant.test.ts` | CREATE | Unit tests for tenant extraction/validation |
| `mcp-herbal-botanicals/src/__tests__/semantic-search-scope.test.ts` | CREATE | Tests for scope injection into LightRAG queries |

## NOT Building

- SQLite query scoping — SQLite only has shared data; no tenant rows exist yet (Phase 4)
- Tenant CRUD / tenant registration — demo uses hardcoded allowed tenants
- Per-user permissions within a tenant — out of scope per PRD
- LightRAG server-side scope enforcement — that would require modifying the LightRAG framework; we do client-side scope injection in the POST body
- Auth / JWT validation — `tenant_id` comes from `_meta`; Clerk integration is Phase 6

---

## Step-by-Step Tasks

### Task 1: Add TenantContext interface to types.ts
- **ACTION**: Add a `TenantContext` interface to `mcp-herbal-botanicals/src/types.ts`
- **IMPLEMENT**:
  ```typescript
  /** Tenant scoping context extracted from MCP _meta. */
  export interface TenantContext {
    /** Tenant identifier, e.g. "clinic_a". Null means shared-only query. */
    tenantId: string | null;
    /** Scope filter values for Neo4j queries. Always includes "shared". */
    scopeFilter: string[];
  }
  ```
- **MIRROR**: INTERFACE_DEFINITION pattern
- **IMPORTS**: None needed
- **GOTCHA**: Keep it at the end of the file to avoid import order issues
- **VALIDATE**: `npm run build` — zero type errors

### Task 2: Create tenant.ts utility module
- **ACTION**: Create `mcp-herbal-botanicals/src/tenant.ts` with pure utility functions
- **IMPLEMENT**:
  ```typescript
  import type { TenantContext } from './types.js';

  /** Regex for valid tenant IDs: lowercase alphanumeric + hyphens, 3-64 chars. */
  const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

  /**
   * Extract tenant context from MCP request _meta.
   * Returns null tenantId if _meta is missing or has no tenant_id.
   */
  export function extractTenantContext(meta: Record<string, unknown> | undefined): TenantContext {
    if (!meta || typeof meta.tenant_id !== 'string' || meta.tenant_id.trim() === '') {
      return { tenantId: null, scopeFilter: ['shared'] };
    }
    const tenantId = meta.tenant_id.trim();
    return {
      tenantId,
      scopeFilter: ['shared', `tenant:${tenantId}`],
    };
  }

  /**
   * Validate that a tenant ID is well-formed.
   * Throws if the ID is present but malformed.
   */
  export function validateTenantId(tenantId: string | null): void {
    if (tenantId === null) return;
    if (!TENANT_ID_PATTERN.test(tenantId)) {
      throw new Error(
        `Invalid tenant_id "${tenantId}": must be 3-64 lowercase alphanumeric characters or hyphens`
      );
    }
  }

  /**
   * Build scope filter parameter for LightRAG query.
   * Returns the scope values to include in the query body.
   */
  export function buildScopeParam(ctx: TenantContext): { scope_filter: string[] } {
    return { scope_filter: ctx.scopeFilter };
  }
  ```
- **MIRROR**: Pure functions, no side effects, testable in isolation
- **IMPORTS**: `type { TenantContext }` from `./types.js`
- **GOTCHA**: Use `.js` extension in import (ESM module resolution). Tenant ID regex must prevent injection — no special chars beyond hyphens.
- **VALIDATE**: `npm run build` — zero type errors

### Task 3: Write unit tests for tenant.ts
- **ACTION**: Create `mcp-herbal-botanicals/src/__tests__/tenant.test.ts`
- **IMPLEMENT**: Test all paths:
  - `extractTenantContext(undefined)` → `{ tenantId: null, scopeFilter: ['shared'] }`
  - `extractTenantContext({})` → null tenantId
  - `extractTenantContext({ tenant_id: 'clinic_a' })` → `{ tenantId: 'clinic_a', scopeFilter: ['shared', 'tenant:clinic_a'] }`
  - `extractTenantContext({ tenant_id: '' })` → null tenantId
  - `extractTenantContext({ tenant_id: 123 })` → null tenantId (non-string)
  - `extractTenantContext({ tenant_id: '  clinic-b  ' })` → trimmed `clinic-b`
  - `validateTenantId(null)` → no throw
  - `validateTenantId('clinic_a')` → throws (underscore not allowed)
  - `validateTenantId('ab')` → throws (too short)
  - `validateTenantId('clinic-a')` → no throw
  - `validateTenantId('a'.repeat(65))` → throws (too long)
  - `validateTenantId('Clinic-A')` → throws (uppercase)
  - `buildScopeParam({ tenantId: null, scopeFilter: ['shared'] })` → `{ scope_filter: ['shared'] }`
  - `buildScopeParam({ tenantId: 'x', scopeFilter: ['shared', 'tenant:x'] })` → correct
- **MIRROR**: TEST_STRUCTURE pattern — vitest `describe`/`it`/`expect`
- **IMPORTS**: `{ describe, it, expect }` from `vitest`; `{ extractTenantContext, validateTenantId, buildScopeParam }` from `../tenant.js`
- **GOTCHA**: No DB required — pure unit tests, no `skipIf`
- **VALIDATE**: `npm test` — all tests pass

### Task 4: Update semantic-search handler with scope injection
- **ACTION**: Modify the `semantic-search` tool handler in `mcp-herbal-botanicals/src/index.ts` to extract tenant context and inject scope filter into the LightRAG POST body
- **IMPLEMENT**:
  1. Add imports at top of file:
     ```typescript
     import { extractTenantContext, validateTenantId, buildScopeParam } from './tenant.js';
     ```
  2. The tool handler callback receives `(args, extra)` — `extra` is `RequestHandlerExtra` which has `_meta`. Update the handler signature from `async (args) => {` to `async (args, extra) => {`.
  3. At the start of the try block, extract and validate:
     ```typescript
     const tenant = extractTenantContext(extra._meta as Record<string, unknown> | undefined);
     validateTenantId(tenant.tenantId);
     ```
  4. Inject scope into the LightRAG POST body:
     ```typescript
     body: JSON.stringify({
       query: args.query,
       mode: args.mode,
       top_k: args.top_k,
       ...buildScopeParam(tenant),
     }),
     ```
  5. Add tenant context to structuredContent for transparency:
     ```typescript
     structuredContent: { ...result, _tenant: { tenantId: tenant.tenantId, scopeFilter: tenant.scopeFilter } },
     ```
- **MIRROR**: SEMANTIC_SEARCH_BRIDGE pattern, ERROR_HANDLING pattern
- **IMPORTS**: `extractTenantContext, validateTenantId, buildScopeParam` from `./tenant.js`
- **GOTCHA**: The `extra` parameter is already available in the handler signature — the SDK passes it as the second argument to ToolCallback. The existing handlers only use `args` and ignore `extra`, so adding it is backward-compatible. `_meta` type is `RequestMeta` which extends to `Record<string, unknown>` for unknown keys — cast safely.
- **VALIDATE**: `npm run build` — zero type errors; `npm test` — all existing tests still pass

### Task 5: Add optional tenant_id to all other tool handlers (extract only, no filtering)
- **ACTION**: For the 14 SQLite tools, update handler signatures to accept `extra` parameter and extract tenant context for logging/transparency, but do NOT filter SQLite queries (SQLite has shared data only)
- **IMPLEMENT**: For each tool handler, change `async (args) => {` to `async (args, extra) => {` and add at the start of the try block:
  ```typescript
  const tenant = extractTenantContext(extra._meta as Record<string, unknown> | undefined);
  ```
  Then include tenant info in the structuredContent:
  ```typescript
  structuredContent: { result, _tenant: { tenantId: tenant.tenantId } },
  ```
  This establishes the convention that all tools are tenant-aware, even if SQLite tools don't filter (yet).
- **MIRROR**: TOOL_REGISTRATION pattern
- **IMPORTS**: Already imported in Task 4
- **GOTCHA**: Don't add filtering to SQLite tools — they have no tenant data. The `_tenant` field in structuredContent is for agent transparency only.
- **VALIDATE**: `npm run build`; `npm test`

### Task 6: Write scope injection integration test
- **ACTION**: Create `mcp-herbal-botanicals/src/__tests__/semantic-search-scope.test.ts`
- **IMPLEMENT**: Test that `buildScopeParam` produces correct JSON for the LightRAG POST body:
  - Shared-only query: `scope_filter: ['shared']`
  - Tenant query: `scope_filter: ['shared', 'tenant:clinic_a']`
  - Test the full JSON body shape that would be sent to LightRAG
  - Test that invalid tenant_id throws before the fetch
  - Test edge case: `_meta` present but no `tenant_id` → shared-only
- **MIRROR**: TEST_STRUCTURE pattern
- **IMPORTS**: vitest, tenant utilities
- **GOTCHA**: Don't test actual HTTP calls to LightRAG — that requires a running server. Test the request body construction and tenant extraction logic.
- **VALIDATE**: `npm test` — all tests pass

### Task 7: Validate full build and test suite
- **ACTION**: Run complete build and test suite to confirm no regressions
- **IMPLEMENT**: 
  ```bash
  cd mcp-herbal-botanicals && npm run build && npm test
  ```
- **MIRROR**: N/A
- **IMPORTS**: N/A
- **GOTCHA**: Ensure no TypeScript errors from the `extra` parameter addition
- **VALIDATE**: Zero build errors, all tests green

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| extractTenantContext — undefined | `undefined` | `{ tenantId: null, scopeFilter: ['shared'] }` | Yes |
| extractTenantContext — empty object | `{}` | `{ tenantId: null, scopeFilter: ['shared'] }` | Yes |
| extractTenantContext — valid | `{ tenant_id: 'clinic-a' }` | `{ tenantId: 'clinic-a', scopeFilter: ['shared', 'tenant:clinic-a'] }` | No |
| extractTenantContext — empty string | `{ tenant_id: '' }` | `{ tenantId: null, scopeFilter: ['shared'] }` | Yes |
| extractTenantContext — non-string | `{ tenant_id: 123 }` | `{ tenantId: null, scopeFilter: ['shared'] }` | Yes |
| extractTenantContext — whitespace | `{ tenant_id: '  clinic-b  ' }` | trimmed to `clinic-b` | Yes |
| validateTenantId — null | `null` | no throw | No |
| validateTenantId — valid | `'clinic-a'` | no throw | No |
| validateTenantId — underscore | `'clinic_a'` | throws | Yes |
| validateTenantId — too short | `'ab'` | throws | Yes |
| validateTenantId — too long | 65 chars | throws | Yes |
| validateTenantId — uppercase | `'Clinic-A'` | throws | Yes |
| buildScopeParam — shared only | `{ tenantId: null, ... }` | `{ scope_filter: ['shared'] }` | No |
| buildScopeParam — with tenant | `{ tenantId: 'x', ... }` | `{ scope_filter: ['shared', 'tenant:x'] }` | No |

### Edge Cases Checklist
- [x] No `_meta` field (undefined) → shared-only
- [x] Empty `_meta` object → shared-only
- [x] `tenant_id` is non-string (number, boolean, object) → shared-only
- [x] `tenant_id` is empty string → shared-only
- [x] `tenant_id` has whitespace → trimmed
- [x] `tenant_id` has injection characters (`'; DROP TABLE`) → rejected by regex
- [x] `tenant_id` has uppercase → rejected by regex
- [x] `tenant_id` too short/long → rejected by regex

---

## Validation Commands

### Static Analysis
```bash
cd mcp-herbal-botanicals && npm run build
```
EXPECT: Zero type errors, build output in `build/`

### Unit Tests
```bash
cd mcp-herbal-botanicals && npm test
```
EXPECT: All tests pass (existing + new)

### Full Test Suite
```bash
cd mcp-herbal-botanicals && npm run build && npm test
```
EXPECT: No regressions

### Manual Validation
- [ ] Build succeeds with zero errors
- [ ] All existing 45 tests still pass
- [ ] New tenant tests pass (expect ~14 new tests)
- [ ] `semantic-search` handler compiles with `extra` parameter
- [ ] Invalid tenant_id throws descriptive error
- [ ] Missing tenant_id defaults to shared-only

---

## Acceptance Criteria
- [ ] All tasks completed
- [ ] All validation commands pass
- [ ] Tests written and passing (~14 new tests)
- [ ] No type errors
- [ ] `tenant_id` extracted from `_meta` in all 15 tool handlers
- [ ] `semantic-search` injects `scope_filter` into LightRAG POST body
- [ ] Invalid `tenant_id` returns error (not silent failure)
- [ ] Missing `tenant_id` defaults to shared-only (backward compatible)
- [ ] No SQL injection or Cypher injection via tenant_id (regex-validated)

## Completion Checklist
- [ ] Code follows discovered patterns (tool registration, error handling, Zod schemas)
- [ ] Error handling matches codebase style (errorContent helper)
- [ ] Tests follow test patterns (vitest describe/it/expect)
- [ ] No hardcoded values (tenant patterns use constants)
- [ ] No unnecessary scope additions
- [ ] Self-contained — no questions needed during implementation

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LightRAG API ignores `scope_filter` in POST body | Medium | Scope not enforced server-side | Phase 3 is client-side injection; LightRAG server needs to honor it (may need LightRAG fork/config) |
| MCP clients don't pass `_meta.tenant_id` | Low | Falls back to shared-only (safe default) | Document convention; Phase 6 wires ShrineAgent |
| `extra._meta` type mismatch | Low | TypeScript compilation error | Cast to `Record<string, unknown>` safely |

## Notes
- The LightRAG POST `/query` endpoint doesn't natively support `scope_filter`. This plan injects it into the POST body. The LightRAG server-side handling (Cypher WHERE clause injection) may need a separate task — either a LightRAG config option or a custom query endpoint. For now, the scope data is sent; enforcement depends on LightRAG server support.
- All 14 SQLite tools are made tenant-aware (extract context) but don't filter. This is intentional — SQLite only has shared data. When Phase 4 adds tenant ingestion, SQLite tools may not need filtering at all if tenant data only lives in Neo4j.
- The `tenant_id` regex allows hyphens but not underscores, matching Clerk's `org_` prefix convention (which would be stripped to just the ID portion by the calling agent).
