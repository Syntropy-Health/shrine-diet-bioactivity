# Feature: MCP Herbal Botanicals — Phase 1: Data Acquisition & ETL Pipeline

## Summary

Build a reproducible ETL pipeline that downloads Dr. Duke's Phytochemical CSV and FooDB compound-food data, normalizes compound names across both sources, and outputs a pre-joined SQLite database at `mcp-herbal-botanicals/data_local/herbal_botanicals.db`. The pipeline mirrors mcp-opennutrition's build patterns exactly: TypeScript scripts run via `tsx`, data downloaded to `data/`, intermediate files in `data_local_temp/`, final SQLite in `data_local/`, chained via npm `convert-data` script.

## User Story

As the mcp-herbal-botanicals MCP server
I want a pre-built SQLite database containing herb→compound→food relationships
So that I can serve compound bridge queries with <200ms latency and zero runtime dependencies

## Problem Statement

No single database bridges herbal medicine to food nutrition. Dr. Duke's maps plants→compounds (104K rows), FooDB maps compounds→foods (millions of content rows), but they use different naming conventions and have no shared identifiers. The ETL must normalize compound names to join them into a unified SQLite database.

## Solution Statement

A three-stage pipeline: (1) Download and extract source archives, (2) Parse CSVs into normalized SQLite tables with compound name normalization as the join key, (3) Validate data quality with an audit script. Compound names are normalized by lowercasing, stripping whitespace/hyphens, and matching across sources. PubChem CID enrichment is deferred to an optional post-build step.

## Metadata

| Field            | Value                                             |
| ---------------- | ------------------------------------------------- |
| Type             | NEW_CAPABILITY                                    |
| Complexity       | HIGH                                              |
| Systems Affected | New: `mcp-herbal-botanicals/` (scripts/, data/, data_local/) |
| Dependencies     | better-sqlite3 ^11.7.0, yauzl ^3.2.0, tsx ^4.19.2, typescript ^5.8.3, vitest ^4.0.18 |
| Estimated Tasks  | 10                                                |

---

## UX Design

### Before State

```
╔══════════════════════════════════════════════════════════════════════════╗
║                           BEFORE STATE                                 ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             ║
║   │  Dr. Duke's  │    │    FooDB     │    │   PubChem    │             ║
║   │  CSV (5.8MB) │    │  CSV (952MB) │    │   REST API   │             ║
║   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘             ║
║          │                   │                   │                      ║
║          ▼                   ▼                   ▼                      ║
║   [Manual download]   [Manual download]   [Manual lookup]              ║
║   [Manual parsing]    [Manual parsing]    [Per-compound]               ║
║   [No join key]       [No join key]       [Rate limited]               ║
║                                                                        ║
║   PAIN: No way to query "herbs sharing compounds with foods"           ║
║   PAIN: Compound names differ across sources (no shared IDs)           ║
║   PAIN: No pre-built database exists for this bridge                   ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### After State

```
╔══════════════════════════════════════════════════════════════════════════╗
║                            AFTER STATE                                 ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║   ┌──────────────┐    ┌──────────────┐                                 ║
║   │  Dr. Duke's  │    │    FooDB     │                                 ║
║   │  CSV (5.8MB) │    │  CSV (952MB) │                                 ║
║   └──────┬───────┘    └──────┬───────┘                                 ║
║          │                   │                                         ║
║          ▼                   ▼                                         ║
║   ┌──────────────────────────────────────┐                             ║
║   │     npm run convert-data             │                             ║
║   │  ┌─────────────────────────────────┐ │                             ║
║   │  │ 1. decompress-datasets.ts       │ │                             ║
║   │  │ 2. build-herbal-db.ts           │ │                             ║
║   │  │    - parse Duke CSVs            │ │                             ║
║   │  │    - parse FooDB CSVs           │ │                             ║
║   │  │    - normalize compound names   │ │                             ║
║   │  │    - join herb→compound→food    │ │                             ║
║   │  │ 3. rm -rf data_local_temp       │ │                             ║
║   │  └─────────────────────────────────┘ │                             ║
║   └──────────────────┬───────────────────┘                             ║
║                      ▼                                                 ║
║   ┌──────────────────────────────────────┐                             ║
║   │  data_local/herbal_botanicals.db     │                             ║
║   │  ┌────────┐ ┌───────────┐            │                             ║
║   │  │ herbs  │→│herb_compds│            │                             ║
║   │  │ 2376   │ │  104388   │            │                             ║
║   │  └────────┘ └─────┬─────┘            │                             ║
║   │                   │                  │                             ║
║   │             ┌─────▼─────┐            │                             ║
║   │             │ compounds │            │                             ║
║   │             │   29585   │            │                             ║
║   │             └─────┬─────┘            │                             ║
║   │                   │                  │                             ║
║   │             ┌─────▼─────┐            │                             ║
║   │             │compd_foods│            │                             ║
║   │             │  (joined) │            │                             ║
║   │             └───────────┘            │                             ║
║   └──────────────────────────────────────┘                             ║
║                                                                        ║
║   VALUE: Single SQLite DB with pre-joined herb→compound→food data      ║
║   VALUE: <200ms query latency, zero runtime dependencies               ║
║   VALUE: Reproducible build from `npm run convert-data`                ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### Interaction Changes

| Location | Before | After | User Impact |
|----------|--------|-------|-------------|
| `mcp-herbal-botanicals/` | Does not exist | New project with ETL pipeline | Developers can build the herbal DB from source |
| `data_local/herbal_botanicals.db` | Does not exist | SQLite with 4 tables, indexes | MCP server (Phase 2) can query herb↔compound↔food |
| `npm run convert-data` | N/A | Downloads, parses, joins, builds SQLite | One command to reproduce the database |

---

## Mandatory Reading

**CRITICAL: Implementation agent MUST read these files before starting any task:**

| Priority | File | Lines | Why Read This |
|----------|------|-------|---------------|
| P0 | `mcp-opennutrition/scripts/tsv-to-sqlite.ts` | 1-120 | SQLite creation pattern: ALL TEXT columns, json() wrapping, transaction batching |
| P0 | `mcp-opennutrition/scripts/decompress-dataset.ts` | 1-76 | ZIP decompression with yauzl: lazyEntries, stream pipeline, ESM guard |
| P0 | `mcp-opennutrition/package.json` | 1-38 | npm scripts chain, dependency versions, ESM config, bin/files fields |
| P1 | `mcp-opennutrition/tsconfig.json` | 1-15 | TypeScript config: ES2022, Node16, strict, rootDir/outDir |
| P1 | `mcp-opennutrition/vitest.config.ts` | 1-8 | Test config: include src/**/*.test.ts, exclude build/** |
| P1 | `mcp-opennutrition/src/SQLiteDBAdapter.ts` | 26-31 | ESM path resolution: fileURLToPath + path.join(__dirname, '..', 'data_local', ...) |
| P1 | `mcp-opennutrition/scripts/audit-data-completeness.ts` | 1-68 | Audit pattern: readonly DB, json_extract counts, markdown table output |
| P2 | `mcp-opennutrition/.gitignore` | all | What to exclude: data_local/, data_local_temp/, build/, node_modules/ |

**External Documentation:**

| Source | Section | Why Needed |
|--------|---------|------------|
| [Dr. Duke's Ag Data Commons](https://agdatacommons.nal.usda.gov/articles/dataset/Dr_Duke_s_Phytochemical_and_Ethnobotanical_Databases/24660351) | File downloads | Duke-Source-CSV.zip download URL and data dictionary |
| [FooDB Downloads](https://foodb.ca/downloads) | CSV download | foodb_2020_4_7_csv.tar.gz (952 MB) |
| [PubChem PUG-REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) | Name-to-CID lookup | `GET /compound/name/{name}/cids/JSON`, 5 req/sec limit |
| [better-sqlite3 v11 API](https://github.com/WiseLibs/better-sqlite3/blob/master/docs/api.md) | Transaction, prepare, exec | Matches v^11.7.0 in opennutrition |

---

## Patterns to Mirror

**PROJECT_SETUP:**
```json
// SOURCE: mcp-opennutrition/package.json:1-38
// COPY THIS PATTERN — adapt name, description, scripts:
{
  "name": "mcp-herbal-botanicals",
  "version": "1.0.0",
  "main": "index.js",
  "type": "module",
  "bin": { "mcp-herbal-botanicals": "./build/index.js" },
  "files": ["build"],
  "scripts": {
    "build": "rm -rf build && tsc && npm run convert-data && chmod 755 build/index.js",
    "convert-data": "tsx scripts/decompress-datasets.ts && tsx scripts/build-herbal-db.ts && rm -rf data_local_temp",
    "test": "vitest run"
  }
}
```

**SQLITE_TABLE_CREATION:**
```typescript
// SOURCE: mcp-opennutrition/scripts/tsv-to-sqlite.ts:60-66
// COPY THIS PATTERN — all columns TEXT, double-quoted names:
function createTable(db: Database.Database, columns: string[]): void {
  const columnDefinitions = columns.map(col => `"${col}" TEXT`).join(', ');
  const createTableSQL = `CREATE TABLE IF NOT EXISTS foods (${columnDefinitions})`;
  db.exec(createTableSQL);
}
```

**TRANSACTION_BATCH_INSERT:**
```typescript
// SOURCE: mcp-opennutrition/scripts/tsv-to-sqlite.ts:90-112
// COPY THIS PATTERN — single transaction, prepared statement, JSON validation:
const insertMany = db.transaction((rows: string[][]) => {
  for (const row of rows) {
    stmt.run(rowToInsert);
  }
});
insertMany(rows);
```

**ZIP_DECOMPRESSION:**
```typescript
// SOURCE: mcp-opennutrition/scripts/decompress-dataset.ts:14-62
// COPY THIS PATTERN — yauzl lazyEntries, stream pipeline, readEntry():
yauzl.open(DATASET_ZIP, { lazyEntries: true }, (err, zipfile) => {
  zipfile.readEntry();
  zipfile.on('entry', (entry) => {
    if (/\/$/.test(entry.fileName)) {
      zipfile.readEntry();  // skip directories
    } else {
      // stream pipeline → readEntry() in .then()
    }
  });
});
```

**ESM_ENTRY_GUARD:**
```typescript
// SOURCE: mcp-opennutrition/scripts/decompress-dataset.ts:72-73
// COPY THIS PATTERN — all scripts must have this guard:
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(console.error);
}
```

**AUDIT_PATTERN:**
```typescript
// SOURCE: mcp-opennutrition/scripts/audit-data-completeness.ts:34-43
// COPY THIS PATTERN — readonly DB, json_extract counts:
const db = new Database(dbPath, { readonly: true });
const row = db.prepare(`
  SELECT COUNT(*) as cnt FROM herbs
  WHERE json_extract(alternate_names, '$') IS NOT NULL
`).get() as { cnt: number };
```

---

## Files to Change

| File | Action | Justification |
| ---- | ------ | ------------- |
| `mcp-herbal-botanicals/package.json` | CREATE | Project config, dependencies, npm scripts |
| `mcp-herbal-botanicals/tsconfig.json` | CREATE | TypeScript config mirroring opennutrition |
| `mcp-herbal-botanicals/vitest.config.ts` | CREATE | Test runner config |
| `mcp-herbal-botanicals/.gitignore` | CREATE | Exclude data_local/, data_local_temp/, build/, node_modules/ |
| `mcp-herbal-botanicals/scripts/download-sources.ts` | CREATE | Download Duke ZIP + FooDB CSV archive |
| `mcp-herbal-botanicals/scripts/decompress-datasets.ts` | CREATE | Extract both archives to data_local_temp/ |
| `mcp-herbal-botanicals/scripts/build-herbal-db.ts` | CREATE | Main ETL: parse CSVs, normalize, join, build SQLite |
| `mcp-herbal-botanicals/scripts/audit-herbal-data.ts` | CREATE | Validate built database quality |
| `mcp-herbal-botanicals/scripts/enrich-pubchem-cids.ts` | CREATE | Optional: batch resolve compound names to PubChem CIDs |
| `mcp-herbal-botanicals/data/.gitkeep` | CREATE | Placeholder for downloaded source archives |

---

## NOT Building (Scope Limits)

- **MCP server code** — Phase 2 (separate plan, can run in parallel worktree)
- **Runtime API calls to PubChem/Wikidata** — deferred; all data is pre-built
- **FooDB API integration** — download CSV only; FooDB API is beta/unstable
- **Full PubChem CID resolution for all 29K compounds** — optional enrichment script only; not blocking for build
- **Drug interaction data** — out of scope per PRD
- **Supplement product data (NIH DSLD)** — future phase per PRD

---

## Step-by-Step Tasks

### Task 1: CREATE `mcp-herbal-botanicals/` project scaffold

- **ACTION**: Create project directory with package.json, tsconfig.json, vitest.config.ts, .gitignore
- **IMPLEMENT**:
  - `package.json`: ESM (`"type": "module"`), same dependency versions as opennutrition, npm scripts for build/convert-data/test
  - `tsconfig.json`: ES2022, Node16, strict, rootDir=src, outDir=build
  - `vitest.config.ts`: include src/**/*.test.ts
  - `.gitignore`: data_local/, data_local_temp/, build/, node_modules/
  - Create directories: `data/`, `data_local/`, `scripts/`, `src/`, `src/__tests__/`
- **MIRROR**: `mcp-opennutrition/package.json:1-38`, `mcp-opennutrition/tsconfig.json:1-15`
- **DEPENDENCIES** (package.json):
  ```json
  {
    "dependencies": {
      "@modelcontextprotocol/sdk": "^1.12.1",
      "better-sqlite3": "^11.7.0",
      "yauzl": "^3.2.0",
      "zod": "^3.25.46"
    },
    "devDependencies": {
      "@types/better-sqlite3": "^7.6.13",
      "@types/node": "^22.15.29",
      "@types/yauzl": "^2.10.3",
      "tsx": "^4.19.2",
      "typescript": "^5.8.3",
      "vitest": "^4.0.18"
    }
  }
  ```
- **VALIDATE**: `cd mcp-herbal-botanicals && npm install && npx tsc --noEmit` (must succeed with empty src/)
- **GOTCHA**: Must create a minimal `src/index.ts` (e.g., `export {}`) for tsc to have something to compile

### Task 2: CREATE `scripts/download-sources.ts`

- **ACTION**: Script to download Dr. Duke's ZIP and FooDB CSV archive
- **IMPLEMENT**:
  - Download `Duke-Source-CSV.zip` from `https://ndownloader.figshare.com/files/43363335` → `data/duke-source-csv.zip` (5.8 MB)
  - Download `foodb_2020_4_7_csv.tar.gz` from `https://foodb.ca/public/foodb_2020_4_7_csv.tar.gz` → `data/foodb-csv.tar.gz` (952 MB)
  - Use Node.js `fetch()` + `fs.createWriteStream()` with streaming (do NOT load 952 MB into memory)
  - Skip download if file already exists and has expected size
  - Print progress to stderr
- **MIRROR**: Download pattern is new (opennutrition ships data in repo), but follow ESM guard pattern from `decompress-dataset.ts:72-73`
- **GOTCHA**: FooDB download is ~952 MB — must stream, not buffer. Use `pipeline(response.body, writeStream)` from `stream/promises`
- **GOTCHA**: The FooDB URL may require following redirects — use `{ redirect: 'follow' }` in fetch options
- **VALIDATE**: `tsx scripts/download-sources.ts && ls -la data/duke-source-csv.zip data/foodb-csv.tar.gz`

### Task 3: CREATE `scripts/decompress-datasets.ts`

- **ACTION**: Extract both archives into `data_local_temp/`
- **IMPLEMENT**:
  - Create `data_local_temp/duke/` and `data_local_temp/foodb/` subdirectories
  - **Duke ZIP**: Use yauzl with `lazyEntries: true` pattern from opennutrition. Extract all 16 CSVs to `data_local_temp/duke/`
  - **FooDB tar.gz**: Use `tar -xzf data/foodb-csv.tar.gz -C data_local_temp/foodb/` via `child_process.execSync` (Node.js has no native tar library; this is simpler than adding a dependency)
  - Print extracted file count to stderr
- **MIRROR**: `mcp-opennutrition/scripts/decompress-dataset.ts:1-76` for ZIP extraction
- **GOTCHA**: Duke CSVs are Latin-1 encoded, not UTF-8. Must decode with `iconv-lite` or use `Buffer.toString('latin1')` when reading
- **GOTCHA**: FooDB tar.gz extracts to a subdirectory like `foodb_2020_4_7_csv/` — account for nested directory
- **VALIDATE**: `tsx scripts/decompress-datasets.ts && ls data_local_temp/duke/*.csv | wc -l` (expect 16 files)

### Task 4: CREATE `scripts/build-herbal-db.ts` — Schema Creation

- **ACTION**: Create SQLite database with 5 tables and indexes
- **IMPLEMENT**:
  - Delete existing `data_local/herbal_botanicals.db` if present (idempotent)
  - Create new database at `data_local/herbal_botanicals.db`
  - Create tables:

  ```sql
  CREATE TABLE herbs (
    id TEXT PRIMARY KEY,           -- FNFNUM as string
    scientific_name TEXT NOT NULL,  -- FNFTAX.TAXON
    common_name TEXT,               -- from COMMON_NAMES.CNNAM (first match)
    family TEXT,                    -- FNFTAX.FAMILY
    genus TEXT,                     -- FNFTAX.GENUS
    species TEXT,                   -- FNFTAX.SPECIES
    usage_type TEXT,                -- FNFTAX.USEAGE: G/F/M
    alternate_names TEXT            -- JSON array of all common names
  );

  CREATE TABLE compounds (
    id TEXT PRIMARY KEY,            -- normalized compound name slug
    name TEXT NOT NULL,             -- original CHEMICALS.CHEM (uppercase)
    name_normalized TEXT NOT NULL,  -- lowercase, stripped
    cas_number TEXT,                -- CHEMICALS.CASNUM (sparse: 97/29585)
    pubchem_cid TEXT,               -- populated by enrich-pubchem-cids.ts (initially NULL)
    compound_class TEXT,            -- from FARMACY_NEW.CHEMCLASS (sparse)
    bioactivities TEXT              -- JSON array from AGGREGAC join
  );

  CREATE TABLE herb_compounds (
    herb_id TEXT NOT NULL REFERENCES herbs(id),
    compound_id TEXT NOT NULL REFERENCES compounds(id),
    plant_part TEXT,                -- PARTS.PPNA (full name, e.g., "Root")
    plant_part_code TEXT,           -- FARMACY_NEW.PPCO (e.g., "RT")
    concentration_low_ppm REAL,     -- FARMACY_NEW.AMT_LO (parsed)
    concentration_high_ppm REAL,    -- FARMACY_NEW.AMT_HI (parsed)
    reference TEXT,                 -- FARMACY_NEW.REFERENCE
    source TEXT DEFAULT 'duke',     -- data provenance
    PRIMARY KEY (herb_id, compound_id, plant_part_code)
  );

  CREATE TABLE compound_foods (
    compound_id TEXT NOT NULL REFERENCES compounds(id),
    food_name TEXT NOT NULL,         -- FooDB Foods.name
    food_name_scientific TEXT,       -- FooDB Foods.name_scientific
    food_group TEXT,                 -- FooDB Food group (if available)
    content_value REAL,              -- FooDB Contents.orig_content
    content_min REAL,                -- FooDB Contents.orig_min
    content_max REAL,                -- FooDB Contents.orig_max
    content_unit TEXT,               -- FooDB Contents.orig_unit
    food_part TEXT,                  -- FooDB Contents.orig_food_part
    citation TEXT,                   -- FooDB Contents.orig_citation
    foodb_food_id TEXT,              -- FooDB Foods.public_id (e.g., "FOOD00765")
    foodb_compound_id TEXT,          -- FooDB Compounds.public_id (e.g., "FDB000004")
    source TEXT DEFAULT 'foodb',     -- data provenance
    PRIMARY KEY (compound_id, food_name, food_part)
  );

  CREATE TABLE compound_name_map (
    normalized_name TEXT NOT NULL,   -- lowercase, stripped name
    source TEXT NOT NULL,            -- 'duke' or 'foodb'
    original_name TEXT NOT NULL,     -- original name from source
    compound_id TEXT REFERENCES compounds(id),
    PRIMARY KEY (normalized_name, source)
  );

  -- Indexes for query performance
  CREATE INDEX idx_herbs_common_name ON herbs(common_name);
  CREATE INDEX idx_herbs_scientific_name ON herbs(scientific_name);
  CREATE INDEX idx_compounds_name_normalized ON compounds(name_normalized);
  CREATE INDEX idx_compounds_name ON compounds(name);
  CREATE INDEX idx_herb_compounds_herb ON herb_compounds(herb_id);
  CREATE INDEX idx_herb_compounds_compound ON herb_compounds(compound_id);
  CREATE INDEX idx_compound_foods_compound ON compound_foods(compound_id);
  CREATE INDEX idx_compound_foods_food ON compound_foods(food_name);
  CREATE INDEX idx_compound_name_map_normalized ON compound_name_map(normalized_name);
  ```

- **MIRROR**: `mcp-opennutrition/scripts/tsv-to-sqlite.ts:55-66` for table creation pattern
- **GOTCHA**: Unlike opennutrition (all TEXT), we use REAL for concentration columns because we need numeric comparisons. Parse PPM strings carefully — some contain non-numeric values like "not available"
- **VALIDATE**: `tsx scripts/build-herbal-db.ts && sqlite3 data_local/herbal_botanicals.db ".tables"` (expect 5 tables)

### Task 5: ADD to `scripts/build-herbal-db.ts` — Compound Name Normalization

- **ACTION**: Implement the `normalizeCompoundName()` function used throughout ETL
- **IMPLEMENT**:
  ```typescript
  function normalizeCompoundName(name: string): string {
    return name
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]/g, '')  // strip all non-alphanumeric
  }
  // Examples:
  // "QUERCETIN" → "quercetin"
  // "Vitamin C" → "vitaminc"
  // "beta-Carotene" → "betacarotene"
  // "L-Ascorbic acid" → "lascorbicacid"
  // "(+)-Catechin" → "catechin"
  ```
- **GOTCHA**: Duke uses UPPERCASE names (e.g., "QUERCETIN"), FooDB uses mixed case (e.g., "Quercetin"). Stripping all non-alphanumeric handles hyphens, parentheses, plus signs, spaces
- **GOTCHA**: Some Duke chemical names have leading/trailing whitespace in the CSV
- **VALIDATE**: Unit test with known compound name pairs from both sources

### Task 6: ADD to `scripts/build-herbal-db.ts` — Parse Duke CSVs

- **ACTION**: Parse the 6 relevant Duke CSV files and insert into herbs, compounds, herb_compounds tables
- **IMPLEMENT**:
  1. **Parse FNFTAX.csv** (2,376 rows) → `herbs` table
     - Key: `FNFNUM` (integer → string for id)
     - Map: `TAXON` → scientific_name, `FAMILY` → family, `GENUS` → genus, `SPECIES` → species, `USEAGE` → usage_type
  2. **Parse COMMON_NAMES.csv** (2,920 rows) → UPDATE `herbs.common_name` and `herbs.alternate_names`
     - Group by FNFNUM, first name becomes common_name, all become JSON array alternate_names
  3. **Parse CHEMICALS.csv** (29,585 rows) → `compounds` table
     - Key: normalized name slug as id
     - Map: `CHEM` → name, `normalizeCompoundName(CHEM)` → name_normalized, `CASNUM` → cas_number
     - Also insert into `compound_name_map` with source='duke'
  4. **Parse PARTS.csv** (115 rows) → in-memory Map<string, string> for PPCO→PPNA lookup
  5. **Parse FARMACY_NEW.csv** (104,388 rows) → `herb_compounds` table
     - Join: `FNFNUM` → herb_id, `normalizeCompoundName(CHEM)` → compound lookup
     - Map: `PPCO` → plant_part_code, PARTS lookup → plant_part
     - Parse `AMT_LO` → concentration_low_ppm, `AMT_HI` → concentration_high_ppm
     - PPM parsing: `parseFloat()`, treat NaN/empty/non-numeric as NULL
  6. **Parse AGGREGAC.csv** (28,929 rows) → UPDATE `compounds.bioactivities`
     - Group activities by CHEM, store as JSON array on compounds table
- **MIRROR**: `mcp-opennutrition/scripts/tsv-to-sqlite.ts:68-113` for batch insert with transaction wrapping
- **GOTCHA**: Duke CSVs are Latin-1 encoded. Read with `fs.readFileSync(path, 'latin1')` or pipe through iconv
- **GOTCHA**: CSV parsing — Duke CSVs have quoted fields with commas inside. Use a proper CSV parser, not `.split(',')`. Add `csv-parse` (from `csv` npm package) as a dependency, or use a simple state machine
- **GOTCHA**: FARMACY_NEW has 104K rows — must use transaction batching for performance
- **GOTCHA**: Some FNFNUM values in FARMACY_NEW may not exist in FNFTAX (orphaned records) — skip with warning
- **VALIDATE**: `sqlite3 data_local/herbal_botanicals.db "SELECT COUNT(*) FROM herbs"` → expect ~2,376

### Task 7: ADD to `scripts/build-herbal-db.ts` — Parse FooDB CSVs

- **ACTION**: Parse FooDB Food, Compound, and Content CSVs and insert into compound_foods table
- **IMPLEMENT**:
  1. **Parse FooDB `Compound.csv`** → in-memory Map<compoundId, { name, public_id, cas, pubchem_cid }>
     - Also insert each into `compound_name_map` with source='foodb'
     - Normalize names with `normalizeCompoundName()` for matching
  2. **Parse FooDB `Food.csv`** → in-memory Map<foodId, { name, name_scientific, public_id, food_group }>
  3. **Parse FooDB `Content.csv`** (very large file — millions of rows) → `compound_foods` table
     - Filter: only rows where `source_type = 'Compound'` (skip 'Nutrient' rows)
     - Join: `source_id` → Compound map → normalize name → look up compound_id in compounds table
     - If compound_id not found in `compounds` table (not in Duke's), create a new compounds row
     - Join: `food_id` → Food map → food_name, food_name_scientific, food_group
     - Map: `orig_content` → content_value, `orig_min` → content_min, `orig_max` → content_max, `orig_unit` → content_unit
  4. **Cross-reference compounds**: After loading both Duke and FooDB compounds, match on `name_normalized` via `compound_name_map`
     - Build a mapping: for each FooDB compound, find the Duke compound with matching normalized name
     - Update compound_foods.compound_id to point to the Duke compound where matches exist
- **MIRROR**: Same transaction batch insert pattern as Task 6
- **GOTCHA**: FooDB Content.csv is the largest file (~100M+ rows possible). Process line by line or in chunks, not all in memory. Use `readline` or streaming CSV parser
- **GOTCHA**: FooDB CSV column order may differ from schema docs — read header row and find column indexes dynamically
- **GOTCHA**: The `standard_content` field in Contents may be NULL even when `orig_content` has a value. Use `orig_content` as primary
- **GOTCHA**: Many FooDB compounds won't match any Duke compound. This is expected — the compound_foods table will contain both matched and unmatched compounds
- **VALIDATE**: `sqlite3 data_local/herbal_botanicals.db "SELECT COUNT(*) FROM compound_foods"` → expect 10,000+ rows

### Task 8: CREATE `scripts/audit-herbal-data.ts`

- **ACTION**: Validate the built database quality
- **IMPLEMENT**:
  - Open `data_local/herbal_botanicals.db` in readonly mode
  - Report counts:
    - Total herbs, compounds, herb_compounds, compound_foods rows
    - Herbs with at least 1 compound
    - Compounds with at least 1 herb AND at least 1 food (the "bridge" compounds)
    - Top 10 herbs by compound count
    - Top 10 compounds by food count
  - Validate top-50 herbal supplements coverage (hardcoded list):
    ```
    Ashwagandha (Withania somnifera), Turmeric (Curcuma longa), Ginseng (Panax ginseng),
    Echinacea, Ginkgo (Ginkgo biloba), St. John's Wort (Hypericum perforatum),
    Valerian (Valeriana officinalis), Chamomile (Matricaria recutita),
    Milk Thistle (Silybum marianum), Garlic (Allium sativum), ...
    ```
    For each: check if herb exists, has compounds, has food matches
  - Print results as markdown table to stdout
- **MIRROR**: `mcp-opennutrition/scripts/audit-data-completeness.ts:1-68`
- **VALIDATE**: `tsx scripts/audit-herbal-data.ts` produces valid markdown output

### Task 9: CREATE `scripts/enrich-pubchem-cids.ts` (Optional Enhancement)

- **ACTION**: Batch-resolve compound names to PubChem CIDs via PUG-REST
- **IMPLEMENT**:
  - Open `data_local/herbal_botanicals.db` in writable mode
  - Query all compounds where `pubchem_cid IS NULL`
  - For each compound name, call:
    ```
    GET https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/cids/JSON
    ```
  - Rate limit: 200ms between requests (5/sec)
  - Update `compounds.pubchem_cid` with the first returned CID
  - Cache results locally in a `data_local/pubchem_cache.json` file to avoid re-fetching on reruns
  - Handle 404 (not found) gracefully — log and skip
  - Print progress: "Resolved 1234/29585 compounds (4.2%)"
  - **Expected runtime**: ~29,585 compounds × 200ms = ~1.6 hours
- **GOTCHA**: PUG-REST rate limit is 5 requests/second. If you get HTTP 503 with `PUGREST.ServerBusy`, back off to 500ms
- **GOTCHA**: Some Duke compound names won't resolve (e.g., "QUERCETIN-3-O-GLUCOSIDE" may need a simpler form). Try the original name first, then strip common suffixes
- **VALIDATE**: `sqlite3 data_local/herbal_botanicals.db "SELECT COUNT(*) FROM compounds WHERE pubchem_cid IS NOT NULL"` — expect at least a few hundred after partial run

### Task 10: Wire up npm scripts and test end-to-end

- **ACTION**: Update package.json scripts and run full pipeline
- **IMPLEMENT**:
  - `"download-data"`: `tsx scripts/download-sources.ts`
  - `"convert-data"`: `tsx scripts/decompress-datasets.ts && tsx scripts/build-herbal-db.ts && rm -rf data_local_temp`
  - `"build"`: `rm -rf build && tsc && npm run convert-data && chmod 755 build/index.js`
  - `"audit"`: `tsx scripts/audit-herbal-data.ts`
  - `"enrich"`: `tsx scripts/enrich-pubchem-cids.ts`
  - `"test"`: `vitest run`
  - Add a `preconvert` check: if `data/duke-source-csv.zip` doesn't exist, print instructions to run `npm run download-data` first
- **MIRROR**: `mcp-opennutrition/package.json:9-14` for script naming pattern
- **VALIDATE**: `npm run download-data && npm run convert-data && npm run audit`
- **GOTCHA**: FooDB download (952 MB) takes significant time. The `download-data` script should be separate from `convert-data` so developers don't re-download every build

---

## Testing Strategy

### Unit Tests to Write

| Test File | Test Cases | Validates |
|-----------|-----------|-----------|
| `src/__tests__/normalize.test.ts` | Compound name normalization: uppercase, hyphens, parens, spaces, unicode | `normalizeCompoundName()` |
| `src/__tests__/etl-validation.test.ts` | DB exists, tables exist, row counts > 0, top herbs have compounds | Post-build database integrity |

### Edge Cases Checklist

- [ ] Duke CSV with Latin-1 encoded characters (accented plant names)
- [ ] Duke PPM values that are empty, "not available", or negative
- [ ] FooDB Content rows with NULL orig_content but non-NULL orig_min/orig_max
- [ ] FooDB compounds with no matching Duke compound (should still be inserted)
- [ ] Duke herbs with zero compounds in FARMACY_NEW
- [ ] Compound names with special characters: `(+)-Catechin`, `1,8-Cineole`, `beta-Sitosterol`
- [ ] Extremely long compound names (>200 chars)
- [ ] Duplicate compound names after normalization (must deduplicate)

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

**EXPECT**: All tests pass

### Level 3: FULL_PIPELINE

```bash
cd mcp-herbal-botanicals && npm run download-data && npm run convert-data
```

**EXPECT**: `data_local/herbal_botanicals.db` exists, >10 MB

### Level 4: DATA_VALIDATION

```bash
cd mcp-herbal-botanicals && npm run audit
```

**EXPECT**: Output shows:
- herbs count > 2,000
- compounds count > 20,000
- herb_compounds count > 50,000
- compound_foods count > 5,000
- "bridge" compounds (have both herb AND food) > 500
- Top-50 herbs all found in database

### Level 5: SPOT_CHECK

```bash
cd mcp-herbal-botanicals && sqlite3 data_local/herbal_botanicals.db "
  SELECT h.common_name, COUNT(DISTINCT hc.compound_id) as compounds
  FROM herbs h
  JOIN herb_compounds hc ON h.id = hc.herb_id
  WHERE h.scientific_name LIKE '%Withania somnifera%'
  GROUP BY h.id
"
```

**EXPECT**: Ashwagandha with 30+ compounds

---

## Acceptance Criteria

- [ ] `npm run download-data` downloads both source archives successfully
- [ ] `npm run convert-data` produces `data_local/herbal_botanicals.db` without errors
- [ ] Database contains 5 tables: herbs, compounds, herb_compounds, compound_foods, compound_name_map
- [ ] herbs table has 2,000+ rows with common names populated
- [ ] compounds table has 20,000+ rows with normalized names
- [ ] herb_compounds table has 50,000+ rows linking herbs to compounds
- [ ] compound_foods table has 5,000+ rows linking compounds to foods
- [ ] "Bridge" compounds (in both herb_compounds AND compound_foods) > 500
- [ ] Ashwagandha, Turmeric, Ginseng, Echinacea all present with compounds
- [ ] `npm run audit` produces readable markdown quality report
- [ ] Pipeline is idempotent: running convert-data twice produces same database
- [ ] All TypeScript compiles without errors (`npx tsc --noEmit`)
- [ ] Unit tests pass (`npm test`)

---

## Completion Checklist

- [ ] All 10 tasks completed in dependency order
- [ ] Each task validated immediately after completion
- [ ] Level 1: Static analysis (tsc --noEmit) passes
- [ ] Level 2: Unit tests pass
- [ ] Level 3: Full pipeline completes without errors
- [ ] Level 4: Data audit shows expected counts
- [ ] Level 5: Spot checks for known herbs return correct data
- [ ] All acceptance criteria met

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| FooDB Content.csv too large for memory (~100M rows) | HIGH | HIGH | Stream-parse with readline; process in chunks of 10K rows per transaction |
| Duke CSV Latin-1 encoding causes garbled names | MEDIUM | MEDIUM | Read with `latin1` encoding; test with known accented names |
| Compound name normalization misses matches | HIGH | MEDIUM | Start with aggressive stripping (all non-alphanumeric); audit match rate; refine if <40% |
| FooDB download URL changes or becomes unavailable | LOW | HIGH | Document manual download instructions as fallback; check URL before download |
| PubChem rate limiting during CID enrichment | MEDIUM | LOW | CID enrichment is optional; cache results; exponential backoff on 503 |
| Duke FARMACY_NEW has orphaned FNFNUM references | LOW | LOW | Skip with console.warn; count orphans in audit |

---

## Notes

### Data Source Details (from research)

**Dr. Duke's Duke-Source-CSV.zip** (5.8 MB, 16 CSV files):
- Primary tables: FNFTAX (2,376 plants), FARMACY_NEW (104,388 plant-chemical rows), CHEMICALS (29,585), AGGREGAC (28,929 chemical-activity rows), COMMON_NAMES (2,920), PARTS (115)
- Join path: `FNFTAX.FNFNUM → FARMACY_NEW.FNFNUM → FARMACY_NEW.CHEM → CHEMICALS.CHEM`
- Bioactivity join: `CHEMICALS.CHEM → AGGREGAC.CHEM → AGGREGAC.ACTIVITY`
- PPM values in `FARMACY_NEW.AMT_LO` and `AMT_HI` columns (strings, need parsing)
- Only 97/29,585 chemicals have CAS numbers
- License: CC0 (public domain, US government)

**FooDB foodb_2020_4_7_csv.tar.gz** (952 MB):
- Key tables: Food.csv, Compound.csv, Content.csv
- Content.csv bridges compounds to foods: `source_id → Compound.id`, `food_id → Food.food_id`, `source_type = 'Compound'`
- Compound.csv has `pubchem_compound_id` but it's NULL for many entries
- License: CC BY-NC 4.0 (non-commercial)

### Compound Name Normalization Strategy

The critical challenge is matching Duke's "QUERCETIN" to FooDB's "Quercetin". The strategy:
1. **Primary**: Normalize both names by lowercasing and stripping all non-alphanumeric characters
2. **Secondary**: If Duke compound has a CAS number (97 cases), match to FooDB's `cas_number` field
3. **Tertiary**: PubChem CID resolution (optional enrichment step, not blocking)

Expected match rate: ~30-50% of Duke compounds will have FooDB food matches. This is sufficient for MVP — most common dietary compounds (vitamins, flavonoids, alkaloids) will match.

### Future Enhancements (Not In This Phase)

- LOTUS/Wikidata SPARQL integration for additional herb→compound data
- USDA Flavonoid DB as public-domain fallback for compound→food mapping
- COCONUT 2.0 for broader natural products coverage
- Streaming PubChem CID resolution during build (parallelized)
