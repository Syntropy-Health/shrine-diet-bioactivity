# Plan: Unified `shrine-diet-bioactivity` MCP Server

> Runs in parallel with `multi-tenant-enforcement-bootstrap.plan.md`; no dependency either way.
> One-line merge conflict in `src/index.ts` is expected — resolved by whichever plan lands first.

## Summary
Merge the 8 `mcp-opennutrition` tools into the existing `mcp-herbal-botanicals` server, rename the unified server to `shrine-diet-bioactivity` (matching Syntropy's Shrine-agent naming convention and reflecting the diet+bioactivity scope), and add a new `search-foods` meta-tool that transparently queries both backends (FooDB-linked foods with compound metadata + OpenNutrition's 326K-food nutrition lookup). Underlying data sources stay physically separate (Neo4j KG, herbal SQLite, OpenNutrition SQLite). OpenNutrition submodule is demoted to a data-source-only role — its TSV→SQLite scripts still build the DB consumed by the unified server, but its MCP process is retired.

## User Story
As a **Syntropy-Journals engineer integrating ShrineAgent with the Diet KG**,
I want **one MCP server named `shrine-diet-bioactivity` exposing herbs, compounds, foods, nutrition, and semantic search under one tool catalog**,
so that **the agent has a single namespace to reason over, cross-domain queries (e.g., "anti-inflammatory foods ranked by protein density") are answered with one tool call, and the `.mcp.json` has one coherent entry that matches our Shrine-family naming**.

## Problem → Solution
**Current state**:
- Two MCP servers — `mcp-herbal-botanicals` (15 tools) and `mcp-opennutrition` (8 tools, submodule).
- Names are mismatched from the consumer (ShrineAgent) — "herbal-botanicals" reads as a subdomain, not the umbrella server.
- Consumers must configure both in `.mcp.json`; the agent juggles two tool catalogs with domain overlap.
- Cross-domain food queries require manual join: `get-compound-foods` → for each food → `search-food-by-name` → rank in agent memory.
- OpenNutrition's aggressive "MANDATORY" tool descriptions bias agent tool-selection even when herbal is the better fit.

**Desired state**:
- One MCP server named `shrine-diet-bioactivity` with 24 tools (15 herbal + 8 nutrition + 1 new `search-foods` meta-tool).
- One `.mcp.json` entry under the unified name.
- Internal routing: tools dispatch to the right backend (LightRAG/Neo4j, herbal SQLite, OpenNutrition SQLite).
- New `search-foods(query, filters?)` meta-tool that fans out to both FooDB-linked foods (with compound attribution) and OpenNutrition foods (with nutrition), dedupes via the food bridge, and returns source-attributed results.
- Tool descriptions rewritten to clarify domain boundaries without "MANDATORY" bias.
- OpenNutrition submodule retained as the TSV→SQLite conversion source.

## Metadata
- **Complexity**: **Large** (14 files, ~700 lines, rename + port + new meta-tool)
- **Source PRD**: N/A (architectural follow-up to `multi-tenant-diet-kg-mcp.prd.md`)
- **Related Plans**: `multi-tenant-enforcement-bootstrap.plan.md` (parallel, independent)
- **Estimated Files**: 14 (8 new, 6 updated, directory rename via `git mv`)

---

## UX Design

### Before
```
┌────────────────────────────────────────────────────────────┐
│ .mcp.json:                                                 │
│   - mcp-herbal-botanicals (15 tools)                       │
│   - mcp-opennutrition     (8 tools)                        │
│                                                            │
│ ShrineAgent: "anti-inflammatory foods ranked by protein?"  │
│   Step 1: mcp-herbal-botanicals.search-by-bioactivity      │
│           → compound list                                  │
│   Step 2: for each compound, get-compound-foods            │
│           → food list (some w/ nutrition via bridge)       │
│   Step 3: for foods NOT bridged, mcp-opennutrition.        │
│           search-food-by-name → nutrition                  │
│   Step 4: agent merges, dedupes, ranks by protein          │
│                                                            │
│   ⚠  2 MCP servers, 4+ round-trips, agent does dedup       │
└────────────────────────────────────────────────────────────┘
```

### After
```
┌────────────────────────────────────────────────────────────┐
│ .mcp.json:                                                 │
│   - shrine-diet-bioactivity (24 tools)                     │
│                                                            │
│ ShrineAgent: "anti-inflammatory foods ranked by protein?"  │
│   Step 1: search-by-bioactivity("anti-inflammatory")       │
│           → compound list                                  │
│   Step 2: search-foods({ compound_ids: [...],              │
│                           sort_by: "protein",              │
│                           include_nutrition: true })       │
│           → merged, deduped, source-attributed results     │
│             [{ food_name, sources:['foodb','opennutrition'],│
│                nutrition_100g:{...}, compound_matches:[...]│
│              }]                                            │
│                                                            │
│   ✓ 1 MCP server, 2 round-trips, server does dedup         │
└────────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| `.mcp.json` entries | 2 | 1 under `shrine-diet-bioactivity` | `mcp-opennutrition` entry removed |
| Package name | `mcp-herbal-botanicals` | `shrine-diet-bioactivity` | Breaking change — migration doc provides before/after snippet |
| Directory name | `mcp-herbal-botanicals/` | `shrine-diet-bioactivity/` | `git mv` preserves history |
| Tool count | 15 + 8 = 23 | 24 (15 + 8 + 1 meta-tool) | `search-foods` is new |
| Tool description tone | Herbal: neutral; OpenNutrition: "MANDATORY" | All neutral with cross-references | Biggest UX improvement for tool-selection quality |
| DB file path | `mcp-herbal-botanicals/data_local/herbal_botanicals.db` | `shrine-diet-bioactivity/data_local/herbal_botanicals.db` | DB filename unchanged; only parent directory renames |
| Submodule role | MCP server + data source | Data source only | `mcp-opennutrition/` stays, its `npm run convert-data` still runs |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `mcp-opennutrition/src/index.ts` | 1-340, full | The 8 tools + schemas to port |
| P0 | `mcp-opennutrition/src/SQLiteDBAdapter.ts` | 1-300 | Adapter to port; DB path line 29 changes |
| P0 | `mcp-opennutrition/src/types.ts` | full | MacroResult, FullNutritionProfile, NutrientGap — move into `nutrition/types.ts` |
| P0 | `mcp-opennutrition/src/rda.ts` | full | RDA reference data — port wholesale |
| P0 | `mcp-herbal-botanicals/src/index.ts` | 1-600 | Merge target; follow existing tool-registration style |
| P0 | `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | full | Mirror pattern for `OpenNutritionDBAdapter`; also has the `food_nutrition_bridge` queries needed by `search-foods` meta-tool |
| P1 | `mcp-herbal-botanicals/package.json` | full | Name field renames; verify no collisions with deps |
| P1 | `mcp-herbal-botanicals/Makefile` | full | Internal paths use relative dir; most references stay intact post-`git mv` |
| P1 | `mcp-opennutrition/package.json` | full | Scripts stay in submodule; `convert-data` is the only thing we keep depending on |
| P1 | `mcp-opennutrition/scripts/` | directory | TSV→SQLite — stays in submodule, triggered from our Makefile |
| P2 | `CLAUDE.md` | full | Many `mcp-herbal-botanicals` references — global rename |
| P2 | `.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md` | full | References server name — update where mentioned |
| P2 | `.gitmodules` | full | Confirms `mcp-opennutrition` submodule path remains `shrine-diet-bioactivity/../mcp-opennutrition` or similar |
| P2 | `mcp-herbal-botanicals/docs/*.md` | all | Ensure no hard links break after rename |

## Patterns to Mirror

### TOOL_REGISTRATION_STYLE
// SOURCE: `mcp-herbal-botanicals/src/index.ts:155-178`
```typescript
this.server.tool(
  'search-herbs',
  `[domain description, neutral tone, cross-references to related tools]`,
  SearchHerbsSchema.shape,
  { title: '[Title]', readOnlyHint: true },
  async (args) => {
    try {
      const result = this.db.searchHerbs(args.query, args.page, args.pageSize);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }], structuredContent: { result } };
    } catch (error: unknown) {
      return errorContent(error);
    }
  }
);
```
All 9 newly added tools (8 ported + 1 meta-tool) adopt this style.

### ADAPTER_PATTERN
// SOURCE: `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` (constructor)
```typescript
export class HerbalDBAdapter {
  private readonly db: Database.Database;
  constructor() {
    const dbPath = path.join(__dirname, '..', 'data_local', 'herbal_botanicals.db');
    this.db = new Database(dbPath, { readonly: true });
  }
}
```
`OpenNutritionDBAdapter` follows the same constructor style, resolving via env-var override then submodule fallback:
```typescript
const envPath = process.env.OPENNUTRITION_DB_PATH;
const defaultPath = path.join(__dirname, '..', '..', 'mcp-opennutrition', 'data_local', 'opennutrition_foods.db');
this.db = new Database(envPath ?? defaultPath, { readonly: true });
```

### ERROR_HANDLING
// SOURCE: `mcp-herbal-botanicals/src/index.ts:105-108`
```typescript
function errorContent(error: unknown): { content: Array<{ type: 'text'; text: string }>; isError: true } {
  const message = error instanceof Error ? error.message : 'Internal database error';
  return { content: [{ type: 'text', text: message }], isError: true };
}
```
All ported tools and the new meta-tool use this helper.

### META_TOOL_DEDUPE_PATTERN
// SOURCE: New — built on top of `food_nutrition_bridge` table in `herbal_botanicals.db`
```typescript
// Bridge rows: { foodb_food_id, opennutrition_food_id, match_confidence, match_strategy }
// Use the bridge to identify which FooDB foods also exist in OpenNutrition.
// For unmatched FooDB foods: source = ['foodb']; for unmatched OpenNutrition: source = ['opennutrition'];
// For bridged: source = ['foodb', 'opennutrition'], with compound_matches + nutrition_100g merged.
```

### TEST_STRUCTURE
// SOURCE: `mcp-herbal-botanicals/src/__tests__/food-bridge.test.ts`
Port opennutrition tests to `src/__tests__/opennutrition-*.test.ts`. Add new `src/__tests__/search-foods-meta.test.ts` for the meta-tool with golden-file responses for known queries.

---

## Files to Change

### Directory rename
| From | To | Action |
|---|---|---|
| `mcp-herbal-botanicals/` | `shrine-diet-bioactivity/` | `git mv` — all contents preserved |

### New files (inside renamed directory)
| File | Justification |
|---|---|
| `shrine-diet-bioactivity/src/OpenNutritionDBAdapter.ts` | Ported adapter with updated DB path |
| `shrine-diet-bioactivity/src/nutrition/rda.ts` | Ported RDA reference data |
| `shrine-diet-bioactivity/src/nutrition/types.ts` | MacroResult / NutrientGap / FullNutritionProfile interfaces |
| `shrine-diet-bioactivity/src/meta/search-foods.ts` | New meta-tool business logic (dedup + merge across backends) |
| `shrine-diet-bioactivity/src/meta/types.ts` | `UnifiedFoodResult` type with source-attribution |
| `shrine-diet-bioactivity/src/__tests__/opennutrition-adapter.test.ts` | Ported adapter tests |
| `shrine-diet-bioactivity/src/__tests__/search-foods-meta.test.ts` | New meta-tool tests (dedup, source attribution, sort/filter) |
| `shrine-diet-bioactivity/src/__tests__/tool-catalog.test.ts` | Regression: exactly 24 tools, no collisions |
| `shrine-diet-bioactivity/docs/unified-mcp-migration.md` | Integrator one-pager: rename + removed entry + new tool catalog |
| `docs/opennutrition-submodule-role.md` | Explains submodule is data-source-only after unification |

### Updated files
| File | Justification |
|---|---|
| `shrine-diet-bioactivity/src/index.ts` | Register 8 ported tools + 1 meta-tool; rewrite descriptions (no "MANDATORY"); rename class; instantiate dual adapters |
| `shrine-diet-bioactivity/package.json` | `name: "shrine-diet-bioactivity"`; optional `bin` entry; server version bump to 2.0.0 |
| `shrine-diet-bioactivity/Makefile` | Add `opennutrition-data` target; paths mostly unchanged (relative) |
| `shrine-diet-bioactivity/README.md` | Rename title + examples |
| `CLAUDE.md` | Global rename; architecture diagram; build commands; mention 24-tool unified server |
| `.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md` | Update any `mcp-herbal-botanicals` references to `shrine-diet-bioactivity` |

## NOT Building

- **Deleting `mcp-opennutrition` submodule** — stays in-tree as data source.
- **Editing files inside the submodule** — creates upstream drift; use wrapper docs instead.
- **Renaming `herbal_botanicals.db`** — internal filename; renaming requires a rebuild step with no user-visible benefit. Flagged as a future follow-up.
- **Changing MCP tool IDs for the 15 existing herbal tools** — backward-compatible preservation; consumers only need to update the server name, not tool names.
- **Adding tenant scoping to the 8 nutrition tools** — nutrition is globally shared scientific data; no tenant data makes sense here.
- **Merging FooDB food_ids and OpenNutrition fd_* IDs into one namespace** — identity confusion risk; `search-foods` meta-tool returns both with source attribution instead.
- **Server-side rate limiting, caching, circuit breakers** — deferred to ops-readiness plan.
- **Node.js version bump or bundler change** — infrastructure stays as-is.
- **TypeScript SDK version bump** — stay on `@modelcontextprotocol/sdk@^1.12.1` (matches both source servers today).

---

## Step-by-Step Tasks

Tracks A–E port and register. Track F renames the package. Track G adds the meta-tool. Track H covers docs. F can run first (unblocks mental model) or last (less disruption during porting) — recommend **F first** so all subsequent tasks land on the final layout.

### TRACK F — Rename to `shrine-diet-bioactivity` (run first)

#### Task F1: `git mv` the directory
- **ACTION**: Single atomic rename preserving git history.
- **IMPLEMENT**:
  ```bash
  cd /home/mo/projects/SyntropyHealth/research/open-diet-data
  git mv mcp-herbal-botanicals shrine-diet-bioactivity
  git commit -m "refactor: rename mcp-herbal-botanicals → shrine-diet-bioactivity"
  ```
- **MIRROR**: N/A.
- **IMPORTS**: N/A.
- **GOTCHA 1**: The `mcp-opennutrition` submodule is a sibling of the renamed dir. Its `.gitmodules` path is absolute from repo root (`mcp-opennutrition`) — UNAFFECTED by the rename. Confirm with `git submodule status` post-rename.
- **GOTCHA 2**: If any IDE/editor has `mcp-herbal-botanicals` indexed, restart to avoid stale paths.
- **GOTCHA 3**: Any worktrees under `.worktrees/` referencing the old path need `git worktree repair`.
- **VALIDATE**: `ls shrine-diet-bioactivity/src/index.ts` exists; `git log --follow shrine-diet-bioactivity/src/index.ts` shows full history.

#### Task F2: Rename `package.json` name field
- **ACTION**: Update name, bump version to 2.0.0 (breaking name change), add binary entry.
- **IMPLEMENT**:
  ```json
  {
    "name": "shrine-diet-bioactivity",
    "version": "2.0.0",
    "description": "Diet + bioactivity knowledge graph MCP server — herbs, compounds, foods, nutrition, and semantic KG search under one unified tool catalog.",
    "bin": { "shrine-diet-bioactivity": "./build/index.js" }
  }
  ```
- **MIRROR**: `mcp-opennutrition/package.json:5-8` for `bin` shape.
- **IMPORTS**: N/A.
- **GOTCHA**: Delete `node_modules` and `package-lock.json` before `npm install` to avoid stale references to the old name.
- **VALIDATE**: `npm install && npm run build` succeeds; `build/index.js` is produced and executable.

#### Task F3: Rename server class and `McpServer` name field
- **ACTION**: `HerbalBotanicalsMCPServer` → `ShrineDietBioactivityMCPServer`; MCP server name string updated.
- **IMPLEMENT**: In `src/index.ts` around line 114-137:
  ```typescript
  class ShrineDietBioactivityMCPServer {
    private readonly server = new McpServer(
      {
        name: 'shrine-diet-bioactivity',
        version: '2.0.0',
        description: `Unified diet + bioactivity knowledge graph MCP server. Covers herbs, phytochemical compounds, foods (FooDB-linked + OpenNutrition 326K-food lookup), molecular targets, diseases, symptoms, and semantic graph traversal.

  Use this server when a query involves:
  - Dietary/nutrition lookups (macros, micros, ingredients, barcodes)
  - Herbal/phytochemical knowledge (compounds, bioactivities, herb profiles)
  - Cross-domain questions linking compounds to foods to health outcomes
  - Semantic/discovery queries over the knowledge graph

  Tool catalog: 15 herbal/compound/KG tools + 8 nutrition tools + 1 unified \`search-foods\` meta-tool. See docs/unified-mcp-migration.md for the full catalog.`,
      },
      { capabilities: { logging: {} } }
    );
  ```
- **MIRROR**: Existing server instantiation.
- **IMPORTS**: N/A.
- **GOTCHA**: Console marker at line 592 (`'mcp-herbal-botanicals MCP Server running on stdio'`) updates to `'shrine-diet-bioactivity MCP Server running on stdio'` — any monitoring/log grep in Syntropy-Journals that matches the old string will break. Note in migration doc.
- **VALIDATE**: Start the server; stderr marker shows new name.

#### Task F4: Update all path references in docs + PRDs
- **ACTION**: Global find-replace `mcp-herbal-botanicals` → `shrine-diet-bioactivity` in:
  - `CLAUDE.md`
  - `.claude/PRPs/prds/multi-tenant-diet-kg-mcp.prd.md`
  - `.claude/PRPs/plans/multi-tenant-enforcement-bootstrap.plan.md` (the other plan — ensures they describe the same world)
  - `.claude/PRPs/plans/completed/*.md` (if references exist)
  - `README.md` at repo root (if references exist)
  - `docs/*.md` under the new `shrine-diet-bioactivity/docs/`
- **IMPLEMENT**: Use `grep -rln "mcp-herbal-botanicals"` to find all occurrences, then targeted edits.
- **MIRROR**: N/A.
- **IMPORTS**: N/A.
- **GOTCHA 1**: Completed plan files (`.claude/PRPs/plans/completed/`) are historical records — keep old references in those files intact; only update the PRD and active plans. Add a "post-rename" note at the top of the PRD explaining the rename.
- **GOTCHA 2**: Scripts under `scripts/` may reference the old path — grep them too.
- **VALIDATE**: `grep -rln "mcp-herbal-botanicals" . --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=completed` returns no results in active files.

#### Task F5: Verify Makefile paths
- **ACTION**: Makefile uses relative paths within the directory — most unchanged. Only targets that reference sibling paths (e.g., `../mcp-opennutrition`) need verification.
- **IMPLEMENT**: `grep -n mcp-herbal-botanicals shrine-diet-bioactivity/Makefile` — should return zero. `grep -n mcp-opennutrition shrine-diet-bioactivity/Makefile` — should be references to the submodule, still valid.
- **MIRROR**: N/A.
- **IMPORTS**: N/A.
- **GOTCHA**: `BATCH_SIZE`, `CONFIG` and other vars unchanged.
- **VALIDATE**: `make help` lists all targets correctly; `make lightrag-dry-run` works after rename.

---

### TRACK A — Port OpenNutrition Code

#### Task A1: Port `SQLiteDBAdapter` → `OpenNutritionDBAdapter`
- **ACTION**: Copy adapter to `shrine-diet-bioactivity/src/OpenNutritionDBAdapter.ts`, rename class, switch DB path resolution, add env-var override, add startup file-existence check.
- **IMPLEMENT**:
  ```typescript
  import Database from 'better-sqlite3';
  import fs from 'fs';
  import path from 'path';
  import { fileURLToPath } from 'url';
  import type { MacroResult, MealMacroResult, FullNutritionProfile, NutrientGapResult } from './nutrition/types.js';
  import { getRDAProfile } from './nutrition/rda.js';

  export class OpenNutritionDBAdapter {
    private readonly db: Database.Database;
    constructor() {
      const __dirname = path.dirname(fileURLToPath(import.meta.url));
      const envPath = process.env.OPENNUTRITION_DB_PATH;
      const defaultPath = path.join(__dirname, '..', '..', 'mcp-opennutrition', 'data_local', 'opennutrition_foods.db');
      const resolved = envPath ?? defaultPath;
      if (!fs.existsSync(resolved)) {
        throw new Error(`OpenNutrition DB not found at ${resolved}. Run \`make opennutrition-data\` to build it, or set OPENNUTRITION_DB_PATH.`);
      }
      this.db = new Database(resolved, { readonly: true });
    }
    // ... copy all existing methods verbatim
  }
  ```
- **MIRROR**: `src/HerbalDBAdapter.ts` constructor style.
- **IMPORTS**: As above.
- **GOTCHA**: Opennutrition adapter uses `async` on every method despite synchronous `better-sqlite3`. Preserve the `async` signatures for API compatibility — consumers may await.
- **VALIDATE**: Instantiation succeeds when DB exists; throws clear error when DB missing.

#### Task A2: Port `rda.ts` → `src/nutrition/rda.ts`
- **ACTION**: `cp` with attribution header.
- **IMPLEMENT**: Identical content to `mcp-opennutrition/src/rda.ts` plus leading comment: `// Adapted from mcp-opennutrition submodule — upstream is the authoritative source. Do not edit here; re-port from submodule when upstream changes.`
- **MIRROR**: N/A.
- **IMPORTS**: Unchanged from original.
- **GOTCHA**: Keep the file in a subdirectory (`nutrition/`) so the top-level `src/` doesn't balloon.
- **VALIDATE**: `getRDAProfile('adult_male').vitamin_c` returns expected value.

#### Task A3: Port types → `src/nutrition/types.ts`
- **ACTION**: New file with the 5 nutrition-specific interfaces.
- **IMPLEMENT**: Copy MacroResult, MealMacroResult, FullNutritionProfile, NutrientGap, NutrientGapResult from `mcp-opennutrition/src/types.ts`. Do NOT merge into main `src/types.ts` — keep nutrition types in a subdirectory for maintainability.
- **MIRROR**: Existing `src/types.ts` interface style.
- **IMPORTS**: None.
- **GOTCHA**: Existing `src/types.ts` has a `NutrientProfile` type (lines 51-93 — 90 per-100g keys). That's the food-bridge enrichment shape. Do NOT conflict — document the distinction in a header comment on `nutrition/types.ts`: "Response shapes for OpenNutrition tools. See ../types.ts NutrientProfile for the per-100g enrichment shape attached to compound_foods."
- **VALIDATE**: `npm run build` succeeds.

---

### TRACK B — Register 9 Tools in `index.ts`

#### Task B1: Add 9 Zod schemas
- **ACTION**: Port 8 opennutrition schemas + add new `SearchFoodsSchema` for the meta-tool.
- **IMPLEMENT**: Insert after existing schemas (after line 99):
  ```typescript
  // --- OpenNutrition schemas (ported) ---
  const SearchFoodByNameSchema = z.object({
    query: z.string().min(1),
    page: z.number().min(1).optional().default(1),
    pageSize: z.number().optional().default(5),
  });
  const GetFoodsSchema = z.object({
    page: z.number().min(1).optional().default(1),
    pageSize: z.number().optional().default(5),
  });
  const GetFoodByIdSchema = z.object({
    id: z.string().startsWith('fd_'),
  });
  const GetFoodByEan13Schema = z.object({
    ean_13: z.string().length(13),
  });
  const CalculateMacrosSchema = z.object({
    query: z.string().min(1),
    portion_grams: z.number().positive().optional().default(100),
  });
  const CalculateMealMacrosSchema = z.object({
    ingredients: z.array(z.object({
      food: z.string().min(1),
      grams: z.number().positive(),
    })).min(1),
  });
  const NutrientGapAnalysisSchema = z.object({
    consumed: z.array(z.object({
      nutrient: z.string().min(1),
      amount: z.number().min(0),
    })).min(1),
    target_profile: z.enum(['adult_male', 'adult_female']),
  });
  const GetFullNutritionProfileSchema = z.object({
    query: z.string().min(1),
  });

  // --- New meta-tool schema ---
  const SearchFoodsSchema = z.object({
    query: z.string().min(1).optional().describe('Free-text food name; either query OR compound_ids required'),
    compound_ids: z.array(z.string()).optional().describe('Filter foods containing any of these compound IDs'),
    include_nutrition: z.boolean().default(true),
    include_compounds: z.boolean().default(true),
    sort_by: z.enum(['relevance', 'protein', 'fiber', 'compound_count', 'calories']).default('relevance'),
    limit: z.number().min(1).max(100).default(25),
  }).refine(v => v.query || (v.compound_ids && v.compound_ids.length > 0), {
    message: 'Either query or compound_ids is required',
  });
  ```
- **MIRROR**: Existing schemas at lines 30-99.
- **IMPORTS**: Already has `z`.
- **GOTCHA**: `SearchFoodsSchema` uses `.refine()` for cross-field validation — confirm MCP SDK handles refined schemas in `.shape` usage; if not, move the check into the handler.
- **VALIDATE**: `npm run build` clean.

#### Task B2: Register 8 ported tools with rewritten descriptions
- **ACTION**: Register ported tools; REWRITE descriptions — no "MANDATORY" wording — following herbal style.
- **IMPLEMENT**: Example rewrite for `search-food-by-name`:
  > **Before**: "MANDATORY: Use this tool ANY time you need to search for foods by name..."
  > **After**: "Search foods by name in the OpenNutrition 326K-food database (packaged, grocery, everyday, prepared). Returns nutrient profile and ingredients when available. Use when the user names a specific food (brand, common, alternate). For phytochemical-first food discovery (e.g., 'foods with quercetin'), use `search-foods` or `get-compound-foods`."

  Apply similar rewrites to all 8 tools. Handler bodies follow herbal try/catch pattern with `errorContent`.

- **MIRROR**: Existing herbal tool descriptions (lines 155-472).
- **IMPORTS**: `import { OpenNutritionDBAdapter } from './OpenNutritionDBAdapter.js'`.
- **GOTCHA 1**: Every opennutrition tool description currently contains "MANDATORY"/"MUST"/"REQUIRED" wording — grep after rewrite to confirm zero remain in the ported block.
- **GOTCHA 2**: `readOnlyHint: true` for all 8 — none write.
- **GOTCHA 3**: `structuredContent` field is mandatory in returns; replicate herbal's conventional shape.
- **VALIDATE**:
  - `npm run build` clean.
  - `grep -c MANDATORY shrine-diet-bioactivity/src/index.ts` returns 0 inside tool description blocks.
  - MCP Inspector shows 8 tools with neutral descriptions.

#### Task B3: Register `search-foods` meta-tool
- **ACTION**: Delegate to `src/meta/search-foods.ts` module (built in Track G).
- **IMPLEMENT**:
  ```typescript
  this.server.tool(
    'search-foods',
    `Unified food search across the FooDB (compound-attributed) and OpenNutrition (nutrition-attributed) datasets. Returns deduplicated, source-attributed results with optional nutrition + compound metadata.

  Use when: a user asks for foods matching some criteria AND wants both compound attribution and nutrition — e.g., "anti-inflammatory foods high in protein", "foods with curcumin and low sugar".

  Returns: Array of UnifiedFoodResult with \`sources: ['foodb' | 'opennutrition']\` per item; bridged foods show both sources. Sort options: relevance, protein, fiber, compound_count, calories.`,
    SearchFoodsSchema.shape,
    { title: 'Unified food search (cross-backend)', readOnlyHint: true },
    async (args) => {
      try {
        const result = await searchFoodsMeta(this.db, this.nutritionDb, args);
        return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }], structuredContent: { result } };
      } catch (error: unknown) {
        return errorContent(error);
      }
    }
  );
  ```
- **MIRROR**: Existing tool registrations.
- **IMPORTS**: `import { searchFoodsMeta } from './meta/search-foods.js'`.
- **GOTCHA**: Meta-tool needs BOTH adapters — confirm constructor signature carries both.
- **VALIDATE**: Inspector shows 24 total tools; `search-foods({query:'oat'})` returns results with source attribution.

#### Task B4: Update server constructor + `main()`
- **ACTION**: Rename class (from Track F), instantiate both adapters.
- **IMPLEMENT**:
  ```typescript
  class ShrineDietBioactivityMCPServer {
    constructor(
      private readonly transport: StdioServerTransport,
      private readonly db: HerbalDBAdapter,
      private readonly nutritionDb: OpenNutritionDBAdapter,
    ) { this.registerTools(); }
  }

  async function main(): Promise<void> {
    const db = new HerbalDBAdapter();
    const nutritionDb = new OpenNutritionDBAdapter();
    const transport = new StdioServerTransport();
    const server = new ShrineDietBioactivityMCPServer(transport, db, nutritionDb);
    await server.connect();
    console.error('shrine-diet-bioactivity MCP Server running on stdio (24 tools, unified)');
  }
  ```
- **MIRROR**: Existing `main()` at lines 587-598.
- **IMPORTS**: As noted in B2/B3.
- **GOTCHA**: If herbal DB missing and opennutrition DB present, user should see a clear error identifying WHICH DB is missing — both adapter constructors fail-fast with specific paths.
- **VALIDATE**: Server boots when both DBs present; fails with specific error when either missing.

---

### TRACK G — `search-foods` Meta-Tool

#### Task G1: Design the `UnifiedFoodResult` shape
- **ACTION**: Define the response type combining both backends.
- **IMPLEMENT** (`src/meta/types.ts`):
  ```typescript
  export type FoodSource = 'foodb' | 'opennutrition';

  export interface UnifiedFoodResult {
    /** Canonical display name (from whichever source had the better match). */
    food_name: string;
    /** All source-specific IDs we have for this food. */
    ids: {
      foodb_food_id?: string;
      opennutrition_food_id?: string;
    };
    /** Which sources contributed to this result. */
    sources: FoodSource[];
    /** Match quality: 1.0 exact name, >=0.8 strong via food bridge, <0.8 fuzzy. */
    confidence: number;
    /** Per-100g nutrition, when include_nutrition=true. Sourced from OpenNutrition or the food bridge. */
    nutrition_100g?: Record<string, number>;
    /** Compound matches from FooDB, when include_compounds=true. */
    compound_matches?: Array<{
      compound_id: string;
      compound_name: string;
      content_value: number | null;
      content_unit: string | null;
    }>;
  }

  export interface SearchFoodsResponse {
    query: string | null;
    compound_ids: string[] | null;
    sort_by: string;
    total: number;
    results: UnifiedFoodResult[];
  }
  ```
- **MIRROR**: Existing response shapes in `src/types.ts`.
- **IMPORTS**: None.
- **GOTCHA**: Schema is the consumer contract — freeze early, change via version bump.
- **VALIDATE**: Types compile; schema is self-documenting.

#### Task G2: Implement `searchFoodsMeta()` business logic
- **ACTION**: New module handling the fan-out, dedup-via-bridge, and sort logic.
- **IMPLEMENT** (`src/meta/search-foods.ts`):
  ```typescript
  /**
   * Unified food search: fans out to HerbalDBAdapter (FooDB foods with compound
   * attribution) + OpenNutritionDBAdapter (nutrition lookup), dedupes via the
   * food_nutrition_bridge table, and returns source-attributed results.
   */
  import type { HerbalDBAdapter } from '../HerbalDBAdapter.js';
  import type { OpenNutritionDBAdapter } from '../OpenNutritionDBAdapter.js';
  import type { SearchFoodsResponse, UnifiedFoodResult, FoodSource } from './types.js';

  interface SearchArgs {
    query?: string;
    compound_ids?: string[];
    include_nutrition: boolean;
    include_compounds: boolean;
    sort_by: 'relevance' | 'protein' | 'fiber' | 'compound_count' | 'calories';
    limit: number;
  }

  export async function searchFoodsMeta(
    herbal: HerbalDBAdapter,
    nutrition: OpenNutritionDBAdapter,
    args: SearchArgs,
  ): Promise<SearchFoodsResponse> {
    // 1. Parallel fetches
    const [foodbHits, onHits, bridgeRows] = await Promise.all([
      fetchFooDBHits(herbal, args),                    // SELECT from compound_foods + compounds
      args.query ? nutrition.searchByName(args.query, 1, args.limit * 2) : Promise.resolve([]),
      herbal.getFoodBridgeRows(),                      // SELECT * FROM food_nutrition_bridge
    ]);

    // 2. Dedupe via bridge: build map of foodb_food_id → opennutrition_food_id
    const bridgeIndex = new Map<string, string>();
    for (const row of bridgeRows) bridgeIndex.set(row.foodb_food_id, row.opennutrition_food_id);

    // 3. Merge. Start with FooDB hits (compound-attributed), join nutrition via bridge.
    //    Then append OpenNutrition-only hits that weren't already represented.
    const results = new Map<string, UnifiedFoodResult>();  // key: canonical dedupe key
    for (const f of foodbHits) {
      const key = dedupeKey(f.food_name, f.foodb_food_id);
      results.set(key, {
        food_name: f.food_name,
        ids: { foodb_food_id: f.foodb_food_id, opennutrition_food_id: bridgeIndex.get(f.foodb_food_id) },
        sources: bridgeIndex.has(f.foodb_food_id) ? ['foodb', 'opennutrition'] : ['foodb'],
        confidence: bridgeIndex.has(f.foodb_food_id) ? 1.0 : 0.8,
        nutrition_100g: args.include_nutrition ? f.nutrition_100g : undefined,
        compound_matches: args.include_compounds ? f.compounds : undefined,
      });
    }
    for (const f of onHits) {
      const key = dedupeKey(f.name, f.id);
      if (results.has(key)) continue; // bridged already
      results.set(key, {
        food_name: f.name,
        ids: { opennutrition_food_id: f.id },
        sources: ['opennutrition'],
        confidence: 0.9,
        nutrition_100g: args.include_nutrition ? f.nutrition_100g : undefined,
        compound_matches: undefined,
      });
    }

    // 4. Sort + limit
    const sorted = sortResults(Array.from(results.values()), args.sort_by);
    const sliced = sorted.slice(0, args.limit);

    return {
      query: args.query ?? null,
      compound_ids: args.compound_ids ?? null,
      sort_by: args.sort_by,
      total: results.size,
      results: sliced,
    };
  }

  // dedupeKey, fetchFooDBHits, sortResults — implemented in same module
  ```
- **MIRROR**: Promise.all fan-out pattern; existing adapter async signatures.
- **IMPORTS**: As above.
- **GOTCHA 1**: `herbal.getFoodBridgeRows()` does not currently exist — ADD to `HerbalDBAdapter` as a new method: `getFoodBridgeRows(): Array<{foodb_food_id: string, opennutrition_food_id: string, match_confidence: number, match_strategy: string}>`. Cache the result (bridge is static).
- **GOTCHA 2**: `fetchFooDBHits` joins `compound_foods`, `compounds`, `food_nutrition_bridge` — this is SQL the existing adapter doesn't expose. Add a new method `searchFoodsByCompoundOrName(args)` to HerbalDBAdapter.
- **GOTCHA 3**: `dedupeKey` should normalize: lowercase + trim + strip punctuation. Test covers "Olive oil" vs "olive oil" dedup correctly.
- **GOTCHA 4**: Sort by `compound_count` when args.include_compounds is false yields zeros — document and fall back to relevance.
- **VALIDATE**: Unit tests cover: (a) query-only, (b) compound-only, (c) both, (d) empty results, (e) dedup correctness, (f) each sort_by option.

#### Task G3: Add `HerbalDBAdapter` helper methods
- **ACTION**: Two new methods on `HerbalDBAdapter` to serve the meta-tool.
- **IMPLEMENT**:
  ```typescript
  /** All bridge rows; cached because the table is static post-ingestion. */
  getFoodBridgeRows(): BridgeRow[] {
    if (!this._bridgeCache) {
      this._bridgeCache = this.db.prepare(
        'SELECT foodb_food_id, opennutrition_food_id, match_confidence, match_strategy FROM food_nutrition_bridge'
      ).all() as BridgeRow[];
    }
    return this._bridgeCache;
  }

  /** Search foods by free-text OR compound_ids. Returns foods w/ compound attribution + nutrition_100g. */
  searchFoodsByCompoundOrName(args: {query?: string; compound_ids?: string[]; limit: number}): FoodHit[] {
    // Assemble query based on which filter was provided; reuse existing compound_foods joins.
  }
  ```
- **MIRROR**: Existing methods on `HerbalDBAdapter`.
- **IMPORTS**: Add `BridgeRow` and `FoodHit` types to `src/types.ts`.
- **GOTCHA**: Cache the bridge rows — 962 rows × 4 fields fits comfortably in memory. Invalidate on DB reconnect (shouldn't happen in practice).
- **VALIDATE**: Existing tests still pass; new methods have direct unit tests.

#### Task G4: Write `search-foods-meta.test.ts`
- **ACTION**: Full coverage for the meta-tool.
- **IMPLEMENT**: Tests:
  - `searchFoodsMeta({query:'oat'})` — returns deduped list with both sources for bridged foods
  - `searchFoodsMeta({compound_ids:['CMP123']})` — returns only FooDB hits with compound attribution
  - `searchFoodsMeta({query:'nonexistent_food_xyz'})` — returns empty results, total=0
  - `searchFoodsMeta({query:'oat', sort_by:'protein'})` — verify sort order
  - Dedup: insert a seed FooDB food "Olive oil" bridged to OpenNutrition's "olive oil, extra virgin" — one result, two sources
  - Dedup: unbridged duplicate (name similar but not in bridge) — two separate results (conservative)
  - Edge: `compound_ids=[]` with no query — Zod validation error (via refine)
  - Edge: `limit=1` — respected
- **MIRROR**: `src/__tests__/food-bridge.test.ts` fixtures.
- **IMPORTS**: `from '../meta/search-foods.js'`.
- **GOTCHA**: Mock adapters OR use real DB with known test fixtures. Prefer real DB for integration guarantees — the herbal DB is readonly and predictable.
- **VALIDATE**: All meta-tool tests pass.

---

### TRACK C — Build Pipeline

#### Task C1: Makefile target for OpenNutrition data
- **ACTION**: Add target triggering submodule's conversion script.
- **IMPLEMENT**:
  ```makefile
  opennutrition-data: ## Build OpenNutrition SQLite from submodule TSVs (~326K foods)
  	@[ -d ../mcp-opennutrition/src ] || (echo "Submodule not initialized. Run: git submodule update --init --recursive" && exit 1)
  	cd ../mcp-opennutrition && npm install && npm run convert-data

  setup: download build migrate food-bridge enrich-nutrition opennutrition-data ## Full pipeline including nutrition DB
  ```
- **MIRROR**: Existing `make setup` orchestration.
- **IMPORTS**: N/A.
- **GOTCHA**: Preflight check catches uninitialized submodule with an actionable message.
- **VALIDATE**: Fresh clone → `git submodule update --init && cd shrine-diet-bioactivity && make opennutrition-data` produces `mcp-opennutrition/data_local/opennutrition_foods.db`.

#### Task C2: Update `package.json` dependencies
- **ACTION**: Audit opennutrition runtime deps; add only what the ported adapter needs.
- **IMPLEMENT**: Runtime deps likely unchanged — `better-sqlite3` already present, `zod` already present, `randomUUID` is built-in. Confirm by grepping ported files for imports.
- **MIRROR**: Existing `package.json`.
- **IMPORTS**: N/A.
- **GOTCHA**: `papaparse` and `yauzl` from opennutrition are data-prep only — they stay in the submodule, NOT added here.
- **VALIDATE**: `npm install` clean; `npm audit` shows no new issues.

---

### TRACK D — Tests

#### Task D1: Port opennutrition adapter tests
- **ACTION**: Copy to `src/__tests__/opennutrition-adapter.test.ts`, adjust imports.
- **IMPLEMENT**: Use real DB (built via `make opennutrition-data` as CI prereq). Pick 3-5 stable `fd_*` IDs that exist in every build for `getFoodById` tests.
- **MIRROR**: `src/__tests__/db-integration.test.ts`.
- **IMPORTS**: `from '../OpenNutritionDBAdapter.js'`.
- **GOTCHA**: If OpenNutrition upstream rebuilds change `fd_*` ID space, tests break — use content-based assertions (e.g., "food with name containing 'olive' exists") where possible.
- **VALIDATE**: `npm test -- opennutrition-adapter` passes.

#### Task D2: Tool-catalog regression test
- **ACTION**: Assert unified server exposes exactly 24 tools with expected names.
- **IMPLEMENT**:
  ```typescript
  import { describe, it, expect } from 'vitest';

  const EXPECTED_TOOLS = [
    // Herbal / compound / KG (15):
    'search-herbs', 'get-herb-compounds', 'search-compounds', 'get-compound-foods',
    'get-herb-food-overlap', 'search-by-bioactivity', 'get-herb-profile',
    'search-by-symptom', 'get-compound-targets', 'find-functional-foods',
    'search-diseases', 'get-target-diseases', 'get-chemical-diseases',
    'semantic-search', 'get-health',
    // OpenNutrition (8):
    'search-food-by-name', 'get-foods', 'get-food-by-id', 'get-food-by-ean13',
    'calculate-macros', 'calculate-meal-macros', 'nutrient-gap-analysis',
    'get-full-nutrition-profile',
    // Meta (1):
    'search-foods',
  ];

  describe('tool catalog', () => {
    it('exposes exactly 24 tools with no collisions', () => {
      // enumerate via MCP SDK introspection or spy
      expect(registeredTools.sort()).toEqual(EXPECTED_TOOLS.sort());
      expect(new Set(registeredTools).size).toBe(24);
    });
    it('has no description containing "MANDATORY"', () => {
      for (const descr of registeredDescriptions) {
        expect(descr).not.toMatch(/MANDATORY/);
      }
    });
  });
  ```
- **MIRROR**: Existing vitest patterns.
- **IMPORTS**: Small refactor to `index.ts` exports a factory or tool array.
- **GOTCHA**: The description-lint assertion is deliberately broad; it's cheap insurance against someone re-importing a ported description verbatim later.
- **VALIDATE**: Test passes; description assertion is informational if any tool uses the word legitimately (none do today).

---

### TRACK E — Docs & Handoff

#### Task E1: Migration doc for consumers
- **ACTION**: `docs/unified-mcp-migration.md` — one-page integrator doc.
- **IMPLEMENT**: Sections:
  - **Rename**: `mcp-herbal-botanicals` → `shrine-diet-bioactivity`
  - **Removed entry**: `mcp-opennutrition` no longer runs as its own server
  - **Before/after `.mcp.json` snippet**
  - **Full 24-tool catalog** grouped: KG/semantic (1), herbs/compounds/foods (14), nutrition (8), unified meta (1)
  - **Meta-tool guide**: when to use `search-foods` vs single-source tools
  - **Tool rename preservation**: all 23 existing tool IDs unchanged — only the server name changes
  - **Version**: server now at 2.0.0; clients should pin
- **MIRROR**: Existing `docs/*.md` style.
- **GOTCHA**: Publish this BEFORE the Phase 6 integration handoff from the blockers plan — integrators see the unified surface from day one.
- **VALIDATE**: Renders cleanly on GitHub.

#### Task E2: Update `CLAUDE.md`
- **ACTION**: Global rename + architectural diagram update + command updates.
- **IMPLEMENT**:
  - Repo Layout: `shrine-diet-bioactivity/` replaces `mcp-herbal-botanicals/`; note submodule demotion
  - Architecture diagram: single MCP box labeled "shrine-diet-bioactivity (24 tools)"
  - Tech stack section: merge the two MCP server rows into one
  - Build commands: `cd shrine-diet-bioactivity && make setup` (unchanged directory-relative)
- **MIRROR**: Existing CLAUDE.md tone.
- **GOTCHA**: Line 11 of current CLAUDE.md references "15 MCP tools (14 SQLite + 1 semantic search)" — update to "24 tools (14 herbal SQLite + 8 OpenNutrition SQLite + 1 semantic search + 1 unified search-foods meta-tool)".
- **VALIDATE**: Diff is coherent; no dangling `mcp-herbal-botanicals` references.

#### Task E3: Submodule role doc
- **ACTION**: `docs/opennutrition-submodule-role.md` — explain the submodule's new role.
- **IMPLEMENT**: Concise doc: "The `mcp-opennutrition` submodule is retained as the upstream reference and the source of the TSV→SQLite conversion pipeline. Its MCP server is NOT launched. Rebuild the DB via `make opennutrition-data` in the `shrine-diet-bioactivity` directory."
- **MIRROR**: Existing docs.
- **GOTCHA**: Link from CLAUDE.md and the migration doc.
- **VALIDATE**: Link check clean.

---

## Testing Strategy

### Unit Tests (new)

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `OpenNutritionDBAdapter.searchByName('oat')` | Common food | Non-empty array | No |
| `OpenNutritionDBAdapter.getFoodById('fd_invalid')` | Nonexistent ID | null / empty | Yes |
| `OpenNutritionDBAdapter.calculateMacros('banana', 150)` | Food + portion | MacroResult scaled to 150g | No |
| `HerbalDBAdapter.getFoodBridgeRows()` | No args | ~962 rows cached | No |
| `searchFoodsMeta({query:'oat'})` | Bridged food | Result with sources=['foodb','opennutrition'] | No |
| `searchFoodsMeta({compound_ids:['CMP...']})` | Compound filter | FooDB-only results with compound_matches | No |
| `searchFoodsMeta({query:'nonexistent_xyz'})` | No match | total=0, results=[] | Yes |
| `searchFoodsMeta({sort_by:'protein'})` | Multi results | Sorted desc by protein | No |
| `searchFoodsMeta({compound_ids:[]})` | No filter | Zod validation error via refine | Yes |
| Tool-catalog test | Server instantiation | 24 unique tool names present | No |
| Description lint | Server metadata | No "MANDATORY" in any tool description | No |
| `OpenNutritionDBAdapter` constructor | Missing DB | Clear error naming `make opennutrition-data` | Yes |

### Regression Tests
| Test | Expected |
|---|---|
| All 15 existing herbal tool tests | Pass unchanged — no behavioral change |
| `get-compound-foods` returns `nutrition_100g` | Still attached via bridge |
| `semantic-search` with `_meta.tenant_id` | Tenant scoping still works (depends on blockers plan) |

### Edge Cases Checklist
- [x] Missing `opennutrition_foods.db` → specific error
- [x] Missing `herbal_botanicals.db` → specific error
- [x] Both DBs missing → two distinct errors
- [x] Tool name collision at registration → MCP SDK throws; test catches at build time
- [x] `search-foods` with no query + no compound_ids → Zod refine rejects
- [x] `search-foods` with unknown compound_id → empty FooDB hits, opennutrition hits if query present
- [x] `search-foods` with limit=100 — performance test (<500ms P95)
- [x] Bridge dedup: foods named identically but not bridged → stay as 2 results (conservative)

---

## Validation Commands

### Static Analysis
```bash
cd shrine-diet-bioactivity && npm run build
```
EXPECT: Zero TypeScript errors; `build/index.js` executable.

### Unit Tests
```bash
cd shrine-diet-bioactivity && npm test
```
EXPECT: 45+ existing tests pass, 15-20 new tests added (opennutrition adapter + meta-tool + catalog).

### Integration via MCP Inspector
```bash
cd shrine-diet-bioactivity && npx @modelcontextprotocol/inspector node build/index.js
# Verify:
#   - Server name 'shrine-diet-bioactivity' shown
#   - 24 tools listed, all with neutral (no MANDATORY) descriptions
#   - search-foods({query:'oat'}) returns sources:['foodb','opennutrition'] for bridged items
#   - search-herbs('turmeric') unchanged behavior
```
EXPECT: All tools functional in the unified server.

### Build Pipeline
```bash
cd shrine-diet-bioactivity && make clean setup
```
EXPECT: Herbal DB + OpenNutrition DB both built; MCP server boots.

### Description Lint (CI-friendly)
```bash
cd shrine-diet-bioactivity && ! grep -n "MANDATORY" src/index.ts
```
EXPECT: Exit 0 (no matches inside tool descriptions).

### Rename Completeness
```bash
grep -rln "mcp-herbal-botanicals" . \
  --exclude-dir=node_modules --exclude-dir=.git \
  --exclude-dir=completed --exclude-dir=build
```
EXPECT: Zero hits in active files (completed/ plan history retained intentionally).

### Manual Validation
- [ ] `.mcp.json` with only one entry (`shrine-diet-bioactivity`) loads in Claude Code / ShrineAgent.
- [ ] LLM agent can answer "anti-inflammatory foods ranked by protein" in 2 tool calls (down from 4).
- [ ] No tool description contains "MANDATORY".
- [ ] `make lightrag-server` still works after rename.
- [ ] `git log --follow shrine-diet-bioactivity/src/index.ts` shows pre-rename history.

---

## Acceptance Criteria
- [ ] Directory renamed via `git mv` with full history preserved.
- [ ] `package.json` name = `shrine-diet-bioactivity`, version = 2.0.0.
- [ ] MCP server name string + stderr marker + class name all consistently use the new name.
- [ ] 24 tools exposed; zero collisions; zero "MANDATORY" in descriptions.
- [ ] `search-foods` meta-tool implemented, tested, and returns source-attributed deduped results.
- [ ] `opennutrition-data` Makefile target works; full `make setup` green on fresh clone.
- [ ] All existing 45 tests pass + new tests (≥65 total).
- [ ] CLAUDE.md, migration doc, submodule-role doc all updated and linked.
- [ ] No residual `mcp-herbal-botanicals` references in active files.
- [ ] OpenNutrition submodule untouched internally.

## Completion Checklist
- [ ] Code follows discovered patterns (herbal tool style, errorContent, try/catch).
- [ ] Error handling matches codebase style.
- [ ] Logging follows codebase conventions.
- [ ] Tests follow vitest patterns.
- [ ] No hardcoded DB paths — both adapters support env-var overrides.
- [ ] Documentation updated: CLAUDE.md, migration doc, submodule role doc.
- [ ] No scope creep: DB filename unchanged, no `.worktrees/` restructure, no SDK version bump.
- [ ] Self-contained — no questions needed during implementation.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `git mv` breaks active worktrees or stale IDE indexes | Medium | Low | Document `git worktree repair` + IDE restart in F1 GOTCHA |
| Consumers' `.mcp.json` breaks silently after rename | High | Medium | Migration doc with before/after; version bumped to 2.0.0 signals breaking change; keep old dir as symlink for 30 days? (decide — currently: no symlink, clean break) |
| `search-foods` dedupe via bridge yields false duplicates or misses | Medium | Medium | Conservative dedupe: only merge if bridge row exists; unbridged name-matches stay separate; test coverage for both cases |
| Meta-tool latency >500ms under load | Low | Medium | Bridge rows cached in adapter; Promise.all fan-out; benchmark; fall back to single-backend path if either side slow |
| Description rewrite removes critical disambiguation hints | Low | Medium | Human review of all 8 new descriptions; cross-references between competing tools (e.g., `search-food-by-name` mentions `search-foods`) |
| `Zod.refine()` doesn't work when SDK uses `.shape` | Low | Medium | Fallback: move refine check into handler body; same user-visible error |
| OpenNutrition upstream changes `fd_*` ID space | Low | Low | Integration tests use content-based assertions (e.g., "olive" match) not hardcoded IDs |
| Description lint catches false positives | Low | Low | Scope the grep to tool-registration blocks only (between `server.tool(` and `);`) |
| Merge conflict with blockers plan on `src/index.ts` | High | Low | Whichever merges first wins; rebase the other; mechanical |

## Notes

- **Why `shrine-diet-bioactivity` specifically**: Aligns with Syntropy's agent-naming convention (ShrineAgent is the consumer). "Diet" covers foods/nutrition/macros; "bioactivity" covers the phytochemical/compound/target side. Together they describe the merged domain precisely — no marketing gloss.
- **Why version 2.0.0**: Breaking change to the package name. SemVer requires a major bump when the identifier changes.
- **Why keep tool IDs unchanged**: The 15 existing herbal tool IDs are stable public surface. Renaming them would break every downstream prompt template and regression test. Server-name change is enough to signal the unification; tool-catalog reorganization is internal.
- **Why a meta-tool instead of modifying existing tools**: Single-responsibility — `get-compound-foods` stays a pure compound→foods lookup; `search-food-by-name` stays a pure name→nutrition lookup. The meta-tool layers the cross-backend concern on top. Consumers who want a single backend can still address it.
- **Dedup philosophy**: Conservative — only merge when the food_nutrition_bridge table explicitly says so (rigorous 5-strategy fuzzy matching from a prior plan). Name-only coincidental matches stay separate to avoid identity confusion.
- **Follow-ups deferred**: (1) Rename `herbal_botanicals.db` → `shrine_diet_bioactivity.db`; (2) vendor the OpenNutrition submodule (copy-in, sever upstream) if divergence grows; (3) add tenant-scoped overlays for nutrition (custom formulas) if any clinic needs them; (4) consolidate the FooDB/OpenNutrition food identity spaces with a canonical food registry.
- **Coordination with blockers plan**: Both plans touch `src/index.ts`. Recommend landing this plan's Track F (rename) first as a mechanical change, then running blockers plan against the new directory name. Tracks A–E and G can run after F and merge cleanly with the tenant changes.
