# Feature: KG Data Expansion — CMAUP + SymMap Integration

## Summary

Expand the `mcp-herbal-botanicals` database with two new data sources: **CMAUP 2024** (7,865 plants with food/edible classification, 60K compounds, compound→target→disease relationships) and **SymMap v2** (1,717 TCM symptoms → 961 modern medicine symptoms → 499 herbs → 19,595 compounds). This adds the symptom/health-benefit layer and food-plant classification needed for queries like "what herbs and foods help with chronic inflammation?" — while staying on SQLite (graph DB migration is Phase 6).

## User Story

As an AI dietitian agent
I want to traverse symptom → compound → herb → food relationships via MCP tool calls
So that I can answer "I'm tired easily" with grounded, multi-source data linking health concerns to specific herbs AND foods

## Problem Statement

The current Phase 1 database (Duke + FooDB) bridges herbs→compounds→foods but has no symptom/condition mapping. The `search-by-bioactivity` tool uses `WHERE bioactivities LIKE ?` on a JSON column — a full table scan with no structured relationships. The agent cannot go from "chronic inflammation" → anti-inflammatory compounds → herbs + foods without relying on LLM parametric knowledge.

## Solution Statement

Add 5 new SQLite tables (symptoms, herb_symptoms, targets, compound_targets, target_diseases) and enrich the herbs table with food-plant classification from CMAUP. Build ETL loaders for both CMAUP CSV and SymMap tabular downloads following the existing `build-herbal-db.ts` patterns. Cross-reference compounds using the existing `normalizeCompoundName()` + `compound_name_map` mechanism. Add 3 new MCP tools (`search-by-symptom`, `get-compound-targets`, `find-functional-foods`) and update `search-by-bioactivity` to use structured symptom data.

## Metadata

| Field            | Value |
|------------------|-------|
| Type             | ENHANCEMENT |
| Complexity       | HIGH |
| Systems Affected | mcp-herbal-botanicals (ETL, schema, adapter, MCP tools, tests) |
| Dependencies     | better-sqlite3 ^11.7.0, papaparse ^5.4.1, zod ^3.25.46, @modelcontextprotocol/sdk ^1.12.1 |
| Estimated Tasks  | 12 |

---

## UX Design

### Before State

```
╔═══════════════════════════════════════════════════════════════════════╗
║                          BEFORE STATE                                ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║   User: "What helps with chronic inflammation?"                      ║
║     ↓                                                                ║
║   Agent calls: search-by-bioactivity("anti-inflammatory")            ║
║     → SQL: WHERE bioactivities LIKE '%anti-inflammatory%'            ║
║     → Full table scan on JSON column (N+1 herb lookups per compound) ║
║     → Returns compounds + herbs, but NO food suggestions             ║
║     → NO symptom-to-herb mapping                                     ║
║     → NO molecular target information                                ║
║     → Agent must use parametric knowledge to bridge to foods         ║
║                                                                      ║
║   DATA_FLOW: bioactivity text → LIKE scan → compounds → N+1 herbs   ║
║   PAIN_POINT: No structured symptoms, no targets, no food plants    ║
║                                                                      ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### After State

```
╔═══════════════════════════════════════════════════════════════════════╗
║                           AFTER STATE                                ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║   User: "What helps with chronic inflammation?"                      ║
║     ↓                                                                ║
║   Agent calls: search-by-symptom("inflammation")                     ║
║     → SQL: symptoms JOIN herb_symptoms JOIN herbs                    ║
║     → Returns: {                                                     ║
║         symptoms_matched: ["Inflammation", "Pain"],                  ║
║         herbs: [Turmeric, Ginger, Boswellia...],                     ║
║         compounds: [Curcumin, Gingerol, Boswellic acid...],          ║
║         functional_foods: [                                          ║
║           { name: "Turmeric", is_food_plant: true },                 ║
║           { name: "Ginger", is_food_plant: true },                   ║
║         ],                                                           ║
║         targets: [COX-2, NF-κB, TNF-α...],                          ║
║       }                                                              ║
║     ↓                                                                ║
║   Agent calls: get-compound-foods("curcumin")                        ║
║     → Existing tool — foods containing curcumin with amounts         ║
║                                                                      ║
║   DATA_FLOW: symptom → JOIN symptoms → herbs → compounds → foods    ║
║   VALUE_ADD: Structured symptom traversal, food plant flags, targets ║
║                                                                      ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes

| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| search-by-symptom (NEW) | N/A | Symptom → herbs + compounds + foods + targets | Agent can go from health concern to actionable recommendations |
| get-compound-targets (NEW) | N/A | Compound → molecular targets with activity values | Agent can explain WHY a compound helps |
| find-functional-foods (NEW) | N/A | Search food plants with therapeutic profiles | Agent finds food-based alternatives to supplements |
| search-by-bioactivity | JSON LIKE scan, N+1 | Structured symptom JOIN, batch herbs | Faster, more accurate, includes foods |
| herbs table | No food classification | is_food_plant, is_edible flags | Agent knows which herbs are also foods |
| get-health | 5 stats | 9 stats (includes new tables) | Better observability |

---

## Mandatory Reading

**CRITICAL: Implementation agent MUST read these files before starting any task:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `mcp-herbal-botanicals/scripts/build-herbal-db.ts` | 67-139 | Schema creation pattern — MIRROR for new tables |
| P0 | `mcp-herbal-botanicals/scripts/build-herbal-db.ts` | 26-31 | `normalizeCompoundName()` — the cross-source join key |
| P0 | `mcp-herbal-botanicals/scripts/build-herbal-db.ts` | 383-468 | `loadFoodbContent()` — streaming ETL pattern for large CSV |
| P0 | `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | 225-277 | `searchByBioactivity()` — the method to refactor |
| P1 | `mcp-herbal-botanicals/src/types.ts` | 1-63 | All existing interfaces — add new ones here |
| P1 | `mcp-herbal-botanicals/src/index.ts` | 29-64 | Zod schema patterns — MIRROR for new tools |
| P1 | `mcp-herbal-botanicals/src/index.ts` | 107-272 | Tool registration pattern — MIRROR exactly |
| P2 | `mcp-herbal-botanicals/src/__tests__/db-integration.test.ts` | 1-113 | Test pattern — MIRROR for new tests |

**External Documentation:**

| Source | Section | Why Needed |
|--------|---------|------------|
| [CMAUP Download](https://bidd.group/CMAUP/) | Download page | Identify exact CSV filenames, column headers, encoding |
| [SymMap Download](http://www.symmap.org/download/) | Download page | Identify exact file format, column names, entity IDs |
| [SymMap Paper (NAR 2019)](https://academic.oup.com/nar/article/47/D1/D1110/5150228) | Schema description | Entity-relationship model for the 6 relationship types |

---

## Patterns to Mirror

**SCHEMA_CREATION:**
```typescript
// SOURCE: mcp-herbal-botanicals/scripts/build-herbal-db.ts:67-139
// COPY THIS PATTERN for new tables:
function createSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS herbs (
      id TEXT PRIMARY KEY,
      ...
    );
    CREATE INDEX IF NOT EXISTS idx_herbs_common_name ON herbs(common_name);
  `);
}
```

**COMPOUND_NORMALIZATION:**
```typescript
// SOURCE: mcp-herbal-botanicals/scripts/build-herbal-db.ts:26-31
// USE THIS for cross-source compound matching:
export function normalizeCompoundName(name: string): string {
  return name.toLowerCase().trim().replace(/[^a-z0-9]/g, '');
}
```

**STREAMING_ETL (for large CSVs):**
```typescript
// SOURCE: mcp-herbal-botanicals/scripts/build-herbal-db.ts:383-468
// COPY THIS PATTERN for CMAUP content loading:
const rl = readline.createInterface({ input: fs.createReadStream(filePath) });
let batch: Array<...> = [];
for await (const line of rl) {
  batch.push(parsed);
  if (batch.length >= 10_000) {
    db.transaction(() => { for (const row of batch) stmt.run(...); })();
    batch = [];
  }
}
```

**CSV_LOADER (for small-medium CSVs):**
```typescript
// SOURCE: mcp-herbal-botanicals/scripts/build-herbal-db.ts:41-55
// USE THIS for SymMap tabular data:
function readCsvFile(filePath: string, encoding: BufferEncoding = 'latin1'): Record<string, string>[] {
  const raw = fs.readFileSync(filePath, encoding);
  const result = Papa.parse<Record<string, string>>(raw, { header: true, skipEmptyLines: true });
  return result.data;
}
```

**ADAPTER_METHOD:**
```typescript
// SOURCE: mcp-herbal-botanicals/src/HerbalDBAdapter.ts:50-84
// COPY THIS PATTERN for new query methods:
searchHerbs(query: string, page = 1, pageSize = 10): PaginatedResult<Herb> {
  const pattern = `%${query}%`;
  const offset = (page - 1) * pageSize;
  const countRow = this.db.prepare(`SELECT COUNT(*) as cnt FROM ...`).get(...) as { cnt: number };
  const rows = this.db.prepare(`SELECT * FROM ... LIMIT ? OFFSET ?`).all(...);
  return { data: rows.map(...), total: countRow.cnt, page, pageSize, hasMore: ... };
}
```

**TOOL_REGISTRATION:**
```typescript
// SOURCE: mcp-herbal-botanicals/src/index.ts:109-128
// MIRROR THIS 5-arg pattern:
this.server.tool(
  'tool-name',
  `Description with usage examples.`,
  ZodSchema.shape,
  { title: 'Short title', readOnlyHint: true },
  async (args) => {
    const result = this.db.methodName(args.param);
    return {
      content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      structuredContent: { result },
    };
  }
);
```

**TEST_STRUCTURE:**
```typescript
// SOURCE: mcp-herbal-botanicals/src/__tests__/db-integration.test.ts:1-16
// MIRROR THIS:
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
describe('Feature tests', () => {
  let db: HerbalDBAdapter;
  beforeAll(() => {
    if (!fs.existsSync(DB_PATH)) { console.warn('...'); return; }
    db = new HerbalDBAdapter(DB_PATH);
  });
  afterAll(() => { db?.close(); });
  it('test name', () => { if (!db) return; ... });
});
```

---

## Files to Change

| File | Action | Justification |
|------|--------|---------------|
| `scripts/download-sources.ts` | UPDATE | Add CMAUP + SymMap download URLs |
| `scripts/decompress-datasets.ts` | UPDATE | Handle CMAUP + SymMap archive extraction |
| `scripts/build-herbal-db.ts` | UPDATE | Add new tables to schema, add CMAUP/SymMap loader functions, add herbs table ALTER for food flags |
| `src/types.ts` | UPDATE | Add Symptom, Target, Disease, HerbSymptom, CompoundTarget, SymptomSearchResult interfaces |
| `src/HerbalDBAdapter.ts` | UPDATE | Add searchBySymptom(), getCompoundTargets(), findFunctionalFoods() methods; refactor searchByBioactivity() |
| `src/index.ts` | UPDATE | Register 3 new MCP tools; update server description |
| `src/__tests__/db-integration.test.ts` | UPDATE | Add tests for new tables, new query methods, symptom resolution |
| `src/__tests__/kg-expansion.test.ts` | CREATE | Dedicated test file for KG-specific queries (symptom traversal, target lookup, food plant search) |
| `package.json` | UPDATE | Add new npm scripts for CMAUP/SymMap download |

---

## NOT Building (Scope Limits)

- **Kuzu graph migration** — Phase 6; this phase stays on SQLite
- **BATMAN-TCM integration** — Phase 7; adds 2.3M predicted interactions separately
- **TCM formula data** — explicitly out of scope; ETCM/BATMAN formulas are for a future phase
- **PubChem CID resolution** — defer; continue using `normalizeCompoundName()` for cross-source joins
- **Drug interaction checking** — requires clinical-grade data; not in scope
- **New MCP server** — everything stays in the same `mcp-herbal-botanicals` server

---

## Step-by-Step Tasks

Execute in order. Each task is atomic and independently verifiable.

### Task 1: Research CMAUP + SymMap Download Formats

- **ACTION**: Download and inspect actual CMAUP and SymMap data files
- **IMPLEMENT**:
  - Visit https://bidd.group/CMAUP/ download page, identify CSV file names and column headers
  - Visit http://www.symmap.org/download/, identify file format (tab-separated, CSV, JSON)
  - Document: file names, column headers, encoding, entity counts, relationship columns
  - Check if TCM_knowledge_graph GitHub repo has pre-processed SymMap data that's easier to parse
- **VALIDATE**: Written documentation of file formats, column mappings, and download URLs
- **OUTPUT**: Create `scripts/data-source-spec.md` documenting exact file formats

### Task 2: UPDATE `scripts/download-sources.ts` — Add CMAUP + SymMap Downloads

- **ACTION**: Add download functions for CMAUP and SymMap source data
- **MIRROR**: `scripts/download-sources.ts` existing download pattern (HTTP GET → save to `data/`)
- **IMPLEMENT**:
  - `downloadCmaup()`: Download CMAUP CSV files from bidd.group
  - `downloadSymmap()`: Download SymMap tabular files from symmap.org
  - Add checksums for integrity validation
  - Add `--source` CLI flag to download individual sources (`duke`, `foodb`, `cmaup`, `symmap`)
- **GOTCHA**: CMAUP/SymMap may require browser-like User-Agent header or manual download steps. Document fallback.
- **VALIDATE**: `tsx scripts/download-sources.ts --source cmaup` succeeds; files saved to `data/`

### Task 3: UPDATE `scripts/decompress-datasets.ts` — Handle New Archives

- **ACTION**: Add extraction logic for CMAUP and SymMap archive formats
- **MIRROR**: Existing extraction pattern in `decompress-datasets.ts`
- **IMPLEMENT**: Extract CMAUP/SymMap files to `data_local_temp/cmaup/` and `data_local_temp/symmap/`
- **VALIDATE**: Extracted files accessible in `data_local_temp/` with expected column headers

### Task 4: UPDATE `scripts/build-herbal-db.ts` — Expand Schema with New Tables

- **ACTION**: Add new tables to `createSchema()` function
- **MIRROR**: `scripts/build-herbal-db.ts:67-139` — existing `CREATE TABLE` + `CREATE INDEX` pattern
- **IMPLEMENT**:
  ```sql
  -- Symptoms (SymMap)
  CREATE TABLE IF NOT EXISTS symptoms (
    id TEXT PRIMARY KEY,            -- SymMap SMSY ID or normalized slug
    name TEXT NOT NULL,
    symptom_type TEXT NOT NULL,     -- 'tcm' or 'modern'
    mm_symptom_id TEXT,            -- mapped modern medicine symptom ID
    description TEXT,
    source TEXT DEFAULT 'symmap'
  );

  -- Herb-symptom relationships (SymMap)
  CREATE TABLE IF NOT EXISTS herb_symptoms (
    herb_id TEXT NOT NULL REFERENCES herbs(id),
    symptom_id TEXT NOT NULL REFERENCES symptoms(id),
    evidence_type TEXT,            -- 'direct' or 'indirect'
    source TEXT DEFAULT 'symmap',
    PRIMARY KEY (herb_id, symptom_id)
  );

  -- Molecular targets (CMAUP)
  CREATE TABLE IF NOT EXISTS targets (
    id TEXT PRIMARY KEY,            -- CMAUP target ID or UniProt ID
    name TEXT NOT NULL,
    uniprot_id TEXT,
    gene_symbol TEXT,
    source TEXT DEFAULT 'cmaup'
  );

  -- Compound-target relationships (CMAUP)
  CREATE TABLE IF NOT EXISTS compound_targets (
    compound_id TEXT NOT NULL REFERENCES compounds(id),
    target_id TEXT NOT NULL REFERENCES targets(id),
    activity_value REAL,           -- IC50, Ki, etc.
    activity_type TEXT,            -- 'IC50', 'Ki', 'EC50'
    interaction_type TEXT,         -- 'inhibitor', 'activator', 'binder'
    source TEXT DEFAULT 'cmaup',
    PRIMARY KEY (compound_id, target_id, source)
  );

  -- Target-disease relationships (CMAUP)
  CREATE TABLE IF NOT EXISTS target_diseases (
    target_id TEXT NOT NULL REFERENCES targets(id),
    disease_name TEXT NOT NULL,
    disease_id TEXT,               -- ICD or CMAUP disease ID
    evidence_layer TEXT,           -- 'target_mapping', 'transcriptomic', 'clinical_trial'
    source TEXT DEFAULT 'cmaup',
    PRIMARY KEY (target_id, disease_name, source)
  );

  -- Indexes for new tables
  CREATE INDEX IF NOT EXISTS idx_symptoms_name ON symptoms(name);
  CREATE INDEX IF NOT EXISTS idx_symptoms_type ON symptoms(symptom_type);
  CREATE INDEX IF NOT EXISTS idx_herb_symptoms_herb ON herb_symptoms(herb_id);
  CREATE INDEX IF NOT EXISTS idx_herb_symptoms_symptom ON herb_symptoms(symptom_id);
  CREATE INDEX IF NOT EXISTS idx_targets_name ON targets(name);
  CREATE INDEX IF NOT EXISTS idx_targets_uniprot ON targets(uniprot_id);
  CREATE INDEX IF NOT EXISTS idx_compound_targets_compound ON compound_targets(compound_id);
  CREATE INDEX IF NOT EXISTS idx_compound_targets_target ON compound_targets(target_id);
  CREATE INDEX IF NOT EXISTS idx_target_diseases_target ON target_diseases(target_id);
  ```
- **ALSO**: Add `ALTER TABLE herbs ADD COLUMN is_food_plant INTEGER DEFAULT 0` and `ALTER TABLE herbs ADD COLUMN is_edible INTEGER DEFAULT 0` (for CMAUP food plant flags)
- **GOTCHA**: Use `IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN` with try-catch for idempotency
- **VALIDATE**: `tsx scripts/build-herbal-db.ts` creates all new tables; `sqlite3 data_local/herbal_botanicals.db ".tables"` shows new tables

### Task 5: UPDATE `scripts/build-herbal-db.ts` — Add SymMap ETL Loaders

- **ACTION**: Add loader functions for SymMap data
- **MIRROR**: `loadCommonNames()` pattern at `build-herbal-db.ts:176-204` for small CSV loading
- **IMPLEMENT**:
  - `loadSymmapSymptoms(db)`: Parse SymMap symptom files → insert into `symptoms` table. Handle both TCM and modern medicine symptom types. Map `mm_symptom_id` for TCM→MM symptom pairs.
  - `loadSymmapHerbSymptoms(db)`: Parse SymMap herb-symptom relationship files → insert into `herb_symptoms`. Cross-reference SymMap herb IDs to existing Duke herb IDs using `normalizeCompoundName()` on scientific names or common names. Log unmatched herbs.
  - `loadSymmapCompounds(db)`: Parse SymMap ingredient/compound data → insert into `compound_name_map` with source='symmap'. Merge into `compounds` table via `INSERT OR IGNORE`.
- **GOTCHA**: SymMap herb IDs (SMHB0001 etc.) differ from Duke IDs (numeric FNFNUM). Must cross-reference by scientific name. Use `herbs` table lookup by `scientific_name LIKE ?`.
- **GOTCHA**: SymMap may use Chinese names alongside English. Filter to English entries or map both.
- **VALIDATE**: After loading, `SELECT COUNT(*) FROM symptoms` > 1000; `SELECT COUNT(*) FROM herb_symptoms` > 5000

### Task 6: UPDATE `scripts/build-herbal-db.ts` — Add CMAUP ETL Loaders

- **ACTION**: Add loader functions for CMAUP data
- **MIRROR**: `loadFoodbContent()` streaming pattern at `build-herbal-db.ts:383-468` for large CSVs
- **IMPLEMENT**:
  - `loadCmaupPlants(db)`: Parse CMAUP plant data. For each plant that matches an existing herb (by normalized scientific name), set `is_food_plant = 1` if CMAUP classifies it as food, `is_edible = 1` if edible.
  - `loadCmaupCompounds(db)`: Parse CMAUP ingredient data → insert into `compound_name_map` (source='cmaup'). Merge new compounds into `compounds` table.
  - `loadCmaupTargets(db)`: Parse CMAUP target data → insert into `targets` table with UniProt IDs.
  - `loadCmaupCompoundTargets(db)`: Parse CMAUP ingredient-target relationships → insert into `compound_targets` with activity values. Use streaming pattern for large files.
  - `loadCmaupTargetDiseases(db)`: Parse CMAUP target-disease associations → insert into `target_diseases` with evidence layer.
- **GOTCHA**: CMAUP has 60K compounds — use batch transactions (10K per batch) as in FooDB loading.
- **GOTCHA**: CMAUP compound names may differ from Duke/FooDB — rely on `normalizeCompoundName()` + `compound_name_map` for cross-referencing.
- **VALIDATE**: After loading, `SELECT COUNT(*) FROM targets` > 500; `SELECT COUNT(*) FROM compound_targets` > 10000; `SELECT COUNT(*) FROM herbs WHERE is_food_plant = 1` > 50

### Task 7: UPDATE `src/types.ts` — Add New Interfaces

- **ACTION**: Add TypeScript interfaces for new entity types
- **MIRROR**: Existing interface pattern at `types.ts:3-63`
- **IMPLEMENT**:
  ```typescript
  export interface Symptom {
    id: string;
    name: string;
    symptom_type: 'tcm' | 'modern';
    mm_symptom_id: string | null;
    description: string | null;
  }

  export interface Target {
    id: string;
    name: string;
    uniprot_id: string | null;
    gene_symbol: string | null;
  }

  export interface CompoundTarget {
    compound_id: string;
    compound_name: string;
    target_id: string;
    target_name: string;
    activity_value: number | null;
    activity_type: string | null;
    interaction_type: string | null;
  }

  export interface SymptomSearchResult {
    symptoms_matched: Symptom[];
    herbs: Array<{
      id: string;
      common_name: string | null;
      scientific_name: string;
      is_food_plant: boolean;
      compound_count: number;
    }>;
    compounds: Array<{
      id: string;
      name: string;
      bioactivities: string[];
      herb_count: number;
      food_count: number;
    }>;
    functional_foods: Array<{
      food_name: string;
      food_group: string | null;
      shared_compounds: number;
      compound_names: string[];
    }>;
  }

  export interface FunctionalFood {
    food_name: string;
    food_group: string | null;
    herb_name: string;
    herb_scientific_name: string;
    compound_count: number;
    compound_names: string[];
  }
  ```
- **ALSO**: Update `Herb` interface to add `is_food_plant: boolean; is_edible: boolean;`
- **VALIDATE**: `npx tsc --noEmit` — types compile

### Task 8: UPDATE `src/HerbalDBAdapter.ts` — Add New Query Methods

- **ACTION**: Add 3 new query methods and refactor searchByBioactivity
- **MIRROR**: `searchHerbs()` at `HerbalDBAdapter.ts:50-84` for paginated queries
- **IMPLEMENT**:
  - `searchBySymptom(query, page, pageSize)`: Search `symptoms` table by name, JOIN through `herb_symptoms` → `herbs` → `herb_compounds` → `compounds` → `compound_foods`. Return `SymptomSearchResult` with matched symptoms, herbs (with `is_food_plant` flag), top compounds, and functional foods.
  - `getCompoundTargets(compoundId)`: SELECT from `compound_targets JOIN targets` WHERE compound matches (both raw and normalized ID). Return `CompoundTarget[]`.
  - `findFunctionalFoods(query, page, pageSize)`: Search `herbs WHERE is_food_plant = 1` matching query, then JOIN through compounds to foods. Return `PaginatedResult<FunctionalFood>`.
  - **Refactor** `searchByBioactivity()`: Replace N+1 herb lookups with a single CTE or subquery. Use `symptoms` table for better matching when available, fall back to JSON LIKE.
- **GOTCHA**: `searchBySymptom` involves 4+ table JOINs — use CTEs for readability. Consider pre-computing herb→symptom counts at ETL time if query is too slow.
- **ALSO**: Update `getStats()` to include new table counts (symptoms, herb_symptoms, targets, compound_targets, target_diseases).
- **ALSO**: Update `searchHerbs()` row mapping to include `is_food_plant` and `is_edible` from herbs table.
- **VALIDATE**: `npx tsc --noEmit`

### Task 9: UPDATE `src/index.ts` — Register 3 New MCP Tools

- **ACTION**: Add new Zod schemas and tool registrations
- **MIRROR**: `index.ts:56-60` for schema, `index.ts:209-227` for tool registration (5-arg pattern)
- **IMPLEMENT**:
  ```typescript
  // Schemas
  const SearchBySymptomSchema = z.object({
    query: z.string().min(1, 'Symptom search query is required'),
    page: z.number().min(1).optional().default(1),
    pageSize: z.number().min(1).max(50).optional().default(10),
  });

  const GetCompoundTargetsSchema = z.object({
    compound_id: z.string().min(1, 'Compound ID is required'),
  });

  const FindFunctionalFoodsSchema = z.object({
    query: z.string().min(1, 'Search query is required'),
    page: z.number().min(1).optional().default(1),
    pageSize: z.number().min(1).max(50).optional().default(20),
  });
  ```
  - Register `search-by-symptom`: "Find herbs, compounds, and foods for a health concern or symptom..."
  - Register `get-compound-targets`: "Get molecular targets for a compound..."
  - Register `find-functional-foods`: "Search for food plants with therapeutic compound profiles..."
  - Update server description to mention symptom-based queries
- **VALIDATE**: `npx tsc --noEmit && npm run build`

### Task 10: UPDATE `src/__tests__/db-integration.test.ts` — Extend Existing Tests

- **ACTION**: Add tests for new tables and updated methods
- **MIRROR**: `db-integration.test.ts:31-37` for query assertion pattern
- **IMPLEMENT**:
  - Test `getStats()` returns new table counts > 0
  - Test `searchHerbs()` returns `is_food_plant` field
  - Test refactored `searchByBioactivity()` still returns correct results for "Antiinflammatory"
- **VALIDATE**: `npm test` — all existing + new tests pass

### Task 11: CREATE `src/__tests__/kg-expansion.test.ts` — KG-Specific Tests

- **ACTION**: Create dedicated test file for knowledge graph queries
- **MIRROR**: `db-integration.test.ts:1-16` for setup/teardown pattern
- **IMPLEMENT**:
  ```typescript
  describe('KG expansion tests', () => {
    it('searchBySymptom finds herbs for inflammation', () => {
      const result = db.searchBySymptom('inflammation');
      expect(result.symptoms_matched.length).toBeGreaterThan(0);
      expect(result.herbs.length).toBeGreaterThan(0);
    });

    it('searchBySymptom returns functional foods for matched herbs', () => {
      const result = db.searchBySymptom('insomnia');
      expect(result.functional_foods.length).toBeGreaterThan(0);
    });

    it('getCompoundTargets returns targets for curcumin', () => {
      const targets = db.getCompoundTargets('curcumin');
      expect(targets.length).toBeGreaterThan(0);
      expect(targets[0].target_name).toBeDefined();
    });

    it('findFunctionalFoods returns food plants', () => {
      const result = db.findFunctionalFoods('turmeric');
      expect(result.data.length).toBeGreaterThan(0);
      expect(result.data[0].herb_name).toBeDefined();
    });

    it('herbs marked as food plants from CMAUP', () => {
      const result = db.searchHerbs('turmeric');
      expect(result.data[0].is_food_plant).toBe(true);
    });

    it('symptoms table has TCM and modern types', () => {
      const stats = db.getStats();
      expect(stats.symptoms).toBeGreaterThan(0);
      expect(stats.herb_symptoms).toBeGreaterThan(0);
    });
  });
  ```
- **VALIDATE**: `npm test` — all tests pass

### Task 12: UPDATE `package.json` — Add New Scripts

- **ACTION**: Add convenience scripts for selective data operations
- **IMPLEMENT**:
  - `"download-cmaup": "tsx scripts/download-sources.ts --source cmaup"` 
  - `"download-symmap": "tsx scripts/download-sources.ts --source symmap"`
  - `"download-all": "tsx scripts/download-sources.ts"`
  - Update `description` to mention CMAUP and SymMap
- **VALIDATE**: `npm run download-cmaup` and `npm run download-symmap` work

---

## Testing Strategy

### Unit Tests to Write

| Test File | Test Cases | Validates |
|-----------|------------|-----------|
| `kg-expansion.test.ts` | searchBySymptom (inflammation, insomnia, fatigue) | Symptom→herb→compound→food traversal |
| `kg-expansion.test.ts` | getCompoundTargets (curcumin, quercetin) | Compound→target relationships from CMAUP |
| `kg-expansion.test.ts` | findFunctionalFoods (turmeric, ginger) | Food plant search with therapeutic profiles |
| `kg-expansion.test.ts` | is_food_plant flag on herbs | CMAUP food plant classification |
| `db-integration.test.ts` | Updated getStats with new table counts | Schema expansion validation |
| `db-integration.test.ts` | Refactored searchByBioactivity | No regression in existing functionality |

### Edge Cases Checklist

- [ ] SymMap herb not found in Duke's → log and skip (don't fail ETL)
- [ ] CMAUP compound name normalization produces same ID as Duke/FooDB compound → correctly merges
- [ ] CMAUP compound name produces different ID → creates new compound with source='cmaup' provenance
- [ ] Empty symptom search query → Zod validation error
- [ ] Symptom with no linked herbs → return empty herbs array, not error
- [ ] Compound with no targets → return empty array from getCompoundTargets
- [ ] Herb is both food plant AND medicinal → both flags set correctly
- [ ] SymMap TCM symptom with no modern medicine mapping → mm_symptom_id is null

---

## Validation Commands

### Level 1: STATIC_ANALYSIS

```bash
cd mcp-herbal-botanicals && npx tsc --noEmit
```

**EXPECT**: Exit 0, no type errors

### Level 2: UNIT_TESTS

```bash
cd mcp-herbal-botanicals && npm test
```

**EXPECT**: All tests pass (existing 17 + new ~10), exit 0

### Level 3: FULL_SUITE

```bash
cd mcp-herbal-botanicals && npm test && npm run build
```

**EXPECT**: All tests pass, build succeeds

### Level 4: DATA_VALIDATION

```bash
cd mcp-herbal-botanicals && tsx scripts/audit-herbal-data.ts
```

**EXPECT**: Audit includes new table statistics; symptom coverage > 500; target coverage > 200

### Level 5: MCP_INSPECTOR

```bash
cd mcp-herbal-botanicals && npm run inspector
```

**EXPECT**: MCP Inspector connects, lists 11 tools (8 existing + 3 new), all tools return valid responses

---

## Acceptance Criteria

- [ ] 5 new SQLite tables created (symptoms, herb_symptoms, targets, compound_targets, target_diseases)
- [ ] `herbs` table has `is_food_plant` and `is_edible` columns populated from CMAUP
- [ ] SymMap data loaded: >500 symptoms, >5000 herb-symptom links
- [ ] CMAUP data loaded: >200 targets, >10000 compound-target links, >50 food plants flagged
- [ ] 3 new MCP tools registered and functional (search-by-symptom, get-compound-targets, find-functional-foods)
- [ ] `searchByBioactivity` refactored — no N+1 queries
- [ ] All existing 17 tests still pass (no regressions)
- [ ] 10+ new tests covering symptom, target, and food-plant queries
- [ ] `get-health` returns counts for all 10 tables
- [ ] Agent can answer "what helps with inflammation?" with herbs, compounds, AND foods

---

## Completion Checklist

- [ ] All 12 tasks completed in dependency order
- [ ] Each task validated immediately after completion
- [ ] Level 1: Static analysis (tsc --noEmit) passes
- [ ] Level 2: Unit tests pass (27+ tests)
- [ ] Level 3: Full test suite + build succeeds
- [ ] Level 4: Data audit includes new sources
- [ ] Level 5: MCP Inspector shows 11 tools
- [ ] All acceptance criteria met

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| CMAUP/SymMap downloads require manual steps (captcha, registration) | MEDIUM | HIGH | Document manual download process; cache archives in `data/`; add `scripts/data-source-spec.md` with instructions |
| SymMap herb IDs don't match Duke herb IDs | HIGH | MEDIUM | Cross-reference by normalized scientific name; log unmatched herbs for manual review |
| CMAUP compound name normalization produces false joins | MEDIUM | MEDIUM | Validate top-100 cross-references manually; add audit query counting ambiguous joins |
| SQLite performance degrades with 5 new tables + JOINs | LOW | MEDIUM | Add covering indexes; use CTEs; benchmark before/after; defer to Kuzu migration (Phase 6) if needed |
| SymMap data only covers TCM herbs (499 herbs vs Duke's 2,376) | HIGH | LOW | Expected — SymMap enriches a subset. Log coverage stats: "X of 2,376 Duke herbs have SymMap symptom data" |
| CMAUP "academic use" license ambiguity | LOW | LOW | Internal use only for now; flag for legal review if product goes external |

---

## Notes

- **TCM_knowledge_graph accelerator**: The GitHub project at `AI-HPC-Research-Team/TCM_knowledge_graph` has pre-processed SymMap + TCMID + PharMeBINet data as CSV files (3.4M records). Consider using this as a starting point for Task 5 (SymMap ETL) if direct SymMap download is problematic.
- **Compound name map audit**: After loading CMAUP + SymMap, run `SELECT normalized_name, COUNT(DISTINCT source) as sources FROM compound_name_map GROUP BY normalized_name HAVING sources >= 3 ORDER BY sources DESC LIMIT 50` to see which compounds are confirmed across 3+ sources.
- **Performance baseline**: Before starting, run `time echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search-by-bioactivity","arguments":{"activity":"Antiinflammatory"}}}' | npx tsx src/index.ts` to establish a latency baseline. Compare after refactoring.
- **Phase 6 prep**: The `HerbalDBAdapter` interface is clean — all public methods return typed results independent of SQLite. A `KuzuDBAdapter` implementing the same methods (including new ones from this phase) enables a drop-in replacement. Design new methods with graph traversal semantics in mind even though they're SQL now.
