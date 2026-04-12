# Plan: Data Manifest & Multi-Source ETL Pipeline

## Summary
Create a unified data manifest (YAML) describing all 7 Tier-1 datasets with schemas, download URLs, and normalization rules. Build download and integration scripts that extend the existing ETL pipeline to fetch CMAUP, SymMap, CTD, HERB 2.0, and TTD data, then populate the SQLite database with compound-target-disease relationships. Also clone Graphiti as a git submodule for Phase 3.

## User Story
As an LLM dietitian agent, I want a comprehensive knowledge graph spanning herbs, compounds, foods, targets, diseases, symptoms, and clinical evidence from 7+ sources, so that I can trace full pathways from health concerns to dietary interventions with molecular-level grounding.

## Problem → Solution
Current DB has 2 sources (Duke + FooDB) with empty target/disease tables → Unified manifest + ETL populates 7 sources with compound-target-disease-symptom data across all tables.

## Metadata
- **Complexity**: Large
- **Source PRD**: `.claude/PRPs/prds/unified-phyto-kg-graphiti.prd.md`
- **PRD Phase**: Phase 1 — Data Manifest & ETL + Phase 2 — SQLite Integration + Phase 3 — Graphiti Setup (combined for efficiency)
- **Estimated Files**: 12-15 new/modified

---

## UX Design

N/A — internal data pipeline change. No user-facing UX transformation.

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `mcp-herbal-botanicals/scripts/download-sources.ts` | all | Download pattern: DownloadTarget interface, streaming, skip-if-exists |
| P0 | `mcp-herbal-botanicals/scripts/build-herbal-db.ts` | 1-120 | Schema creation, normalizeCompoundName, CSV parsing, batch transactions |
| P0 | `mcp-herbal-botanicals/scripts/migrate-kg-expansion.ts` | all | Migration pattern: IF NOT EXISTS, OR IGNORE, transaction batching |
| P1 | `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | 1-50, 460-585 | Adapter patterns for new query methods |
| P1 | `mcp-herbal-botanicals/src/types.ts` | all | Existing type definitions |
| P1 | `mcp-herbal-botanicals/src/index.ts` | 66-80, 125-145 | Zod schema + tool registration pattern |
| P2 | `mcp-herbal-botanicals/package.json` | all | npm script conventions |
| P2 | `.gitmodules` | all | Submodule configuration pattern |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| CMAUP download | `https://bidd.group/CMAUP/download.html` | 13 TSV files, no auth, base URL `https://bidd.group/CMAUP/downloadFiles/` |
| CTD download | `https://ctdbase.org/downloads/` | CSV.gz files, CAPTCHA required — must download manually |
| TTD download | `https://ttd.idrblab.cn/full-data-download` | TSV files: P1-01 through P1-05, no auth |
| HERB 2.0 | `https://herb.ac.cn/Download/` | Server unreliable — may need manual download or mirror |
| SymMap v2 | `https://www.symmap.org/` | Site unreliable — may need cached/archived data |
| Graphiti | `https://github.com/getzep/graphiti.git` | v0.28.2 stable, Python, supports OpenAI-compatible embeddings |
| Graphiti embedder | `graphiti_core/embedder/openai.py` | `OpenAIEmbedderConfig(base_url=..., embedding_model=..., embedding_dim=...)` |
| Graphiti ingestion | `graphiti.add_episode()` | `EpisodeType.json` for structured data, JSON string body |

---

## Patterns to Mirror

### DOWNLOAD_PATTERN
```typescript
// SOURCE: scripts/download-sources.ts:17-37
interface DownloadTarget {
  url: string;
  filename: string;
  description: string;
  expectedMinSize: number;
}

const SOURCES: Record<string, DownloadTarget> = {
  duke: {
    url: 'https://ndownloader.figshare.com/files/43363335',
    filename: 'duke-source-csv.zip',
    description: "Dr. Duke's Phytochemical DB (CSV)",
    expectedMinSize: 1_000_000,
  },
};
```

### NORMALIZE_COMPOUND
```typescript
// SOURCE: scripts/build-herbal-db.ts:26-31
export function normalizeCompoundName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]/g, '');
}
```

### CSV_PARSING
```typescript
// SOURCE: scripts/build-herbal-db.ts:41-55
function readCsvFile(filePath: string, encoding: BufferEncoding = 'latin1'): Record<string, string>[] {
  const raw = fs.readFileSync(filePath, encoding);
  const result = Papa.parse<Record<string, string>>(raw, {
    header: true,
    skipEmptyLines: true,
    transformHeader: (h: string) => h.trim(),
  });
  return result.data;
}
```

### MIGRATION_PATTERN
```typescript
// SOURCE: scripts/migrate-kg-expansion.ts:1-13
// Incremental migration — IF NOT EXISTS / OR IGNORE
// Safe to run multiple times
// Transaction-wrapped batch inserts
```

### SCHEMA_CREATION
```typescript
// SOURCE: scripts/build-herbal-db.ts:67-78
function createSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS herbs (
      id TEXT PRIMARY KEY,
      scientific_name TEXT NOT NULL,
      ...
    );
  `);
}
```

### BATCH_INSERT
```typescript
// SOURCE: scripts/build-herbal-db.ts (FooDB loading pattern)
// Collect 10,000 operations before flushing to database
// Use db.transaction(() => { ... }) for atomicity
```

### TEST_STRUCTURE
```typescript
// SOURCE: src/__tests__/kg-expansion.test.ts:1-16
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
const DB_EXISTS = fs.existsSync(DB_PATH);
describe.skipIf(!DB_EXISTS)('Test suite name', () => {
  let db: HerbalDBAdapter;
  beforeAll(() => { db = new HerbalDBAdapter(DB_PATH); });
  afterAll(() => { db?.close(); });
});
```

### ERROR_CONTENT_HANDLER
```typescript
// SOURCE: src/index.ts:86-89
function errorContent(error: unknown): { content: Array<{ type: 'text'; text: string }>; isError: true } {
  const message = error instanceof Error ? error.message : 'Internal database error';
  return { content: [{ type: 'text', text: message }], isError: true };
}
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `mcp-herbal-botanicals/data/manifest.yaml` | CREATE | Unified dataset manifest |
| `mcp-herbal-botanicals/scripts/download-sources.ts` | UPDATE | Add CMAUP, TTD download targets |
| `mcp-herbal-botanicals/scripts/migrate-multi-source.ts` | CREATE | ETL for CMAUP, CTD, HERB, TTD, SymMap |
| `mcp-herbal-botanicals/scripts/load-cmaup.ts` | CREATE | CMAUP-specific TSV parser and loader |
| `mcp-herbal-botanicals/scripts/load-ctd.ts` | CREATE | CTD CSV.gz parser (chemical-disease, chemical-gene) |
| `mcp-herbal-botanicals/scripts/load-ttd.ts` | CREATE | TTD TSV parser (targets + druggability) |
| `mcp-herbal-botanicals/src/types.ts` | UPDATE | Add Disease, ClinicalTrial, ChemicalDisease types |
| `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | UPDATE | Add query methods for new tables |
| `mcp-herbal-botanicals/src/index.ts` | UPDATE | Register new MCP tools for targets/diseases |
| `mcp-herbal-botanicals/src/__tests__/multi-source.test.ts` | CREATE | Integration tests for new data |
| `mcp-herbal-botanicals/package.json` | UPDATE | Add new npm scripts |
| `.gitmodules` | UPDATE | Add graphiti submodule |
| `graphiti/` | CREATE (submodule) | Clone from getzep/graphiti |
| `mcp-herbal-botanicals/graphiti/` | CREATE | Python config, ingestion scripts |
| `mcp-herbal-botanicals/graphiti/ingest.py` | CREATE | Graphiti ingestion script |
| `mcp-herbal-botanicals/graphiti/config.py` | CREATE | Graphiti + Neo4j + embedder config |
| `mcp-herbal-botanicals/graphiti/requirements.txt` | CREATE | Python dependencies |
| `docs/graphiti-neo4j-guide.md` | CREATE | Visualization and setup guide |

## NOT Building

- Web scraper for BATMAN-TCM (no bulk download available)
- DisGeNET integration (requires paid subscription for full data)
- STITCH filtering pipeline (200GB raw, deferred to Tier 2)
- Production Graphiti deployment (experiment only)
- New MCP tools beyond what new data enables (deferred to separate phase)
- Kuzu migration (deferred pending Graphiti experiment)

---

## Step-by-Step Tasks

### Task 1: Create Data Manifest (manifest.yaml)
- **ACTION**: Create `mcp-herbal-botanicals/data/manifest.yaml` describing all 7 datasets
- **IMPLEMENT**: YAML document with per-dataset entries containing: name, version, url, format, license, entity_types, row_counts, download_method (auto/manual), files list with column schemas, normalization_rules, join_keys
- **MIRROR**: No existing config pattern — this is the first YAML config in the project
- **IMPORTS**: N/A (data file)
- **GOTCHA**: CTD requires CAPTCHA (mark as `download_method: manual`). HERB 2.0 and SymMap servers are unreliable (mark as `download_method: manual_fallback`). Include SHA256 checksums where known.
- **VALIDATE**: YAML parses without error; all 7 datasets documented with schemas

### Task 2: Extend Download Script for CMAUP + TTD
- **ACTION**: Add CMAUP and TTD download targets to `scripts/download-sources.ts`
- **IMPLEMENT**: Add new entries to SOURCES record following the DownloadTarget interface pattern. CMAUP has 6 key files at `https://bidd.group/CMAUP/downloadFiles/`. TTD has 5 files.
- **MIRROR**: DOWNLOAD_PATTERN — same DownloadTarget interface, skip-if-exists logic
- **IMPORTS**: Same as existing (fs, path, pipeline, Readable)
- **GOTCHA**: CMAUP files are TSV not CSV. Add `--cmaup-only` and `--ttd-only` flags following existing `--duke-only`/`--foodb-only` pattern. Some URLs may redirect — keep `redirect: 'follow'`.
- **VALIDATE**: `tsx scripts/download-sources.ts --cmaup-only` downloads all CMAUP files to `data/`

### Task 3: Create CMAUP Loader Script
- **ACTION**: Create `scripts/load-cmaup.ts` to parse CMAUP TSV files and populate targets, compound_targets, target_diseases tables
- **IMPLEMENT**:
  - Parse `CMAUPv2.0_download_Plants.txt` → enrich herbs table (scientific_name matching + food/edible classification)
  - Parse `CMAUPv2.0_download_Targets.txt` → populate targets table (id, uniprot_id, gene_symbol, name)
  - Parse `CMAUPv2.0_download_Ingredient_Target_Associations_ActivityValues_References.txt` → populate compound_targets (compound_id via normalizeCompoundName, target_id, activity_value, interaction_type)
  - Parse `CMAUPv2.0_download_Plant_Human_Disease_Associations.txt` → populate target_diseases
  - Use batch transactions (10K per flush)
  - Cross-reference compounds via normalizeCompoundName() + compound_name_map
- **MIRROR**: CSV_PARSING (adapt for TSV: delimiter '\t'), BATCH_INSERT, NORMALIZE_COMPOUND
- **IMPORTS**: fs, path, Database, Papa (with delimiter: '\t'), normalizeCompoundName from build-herbal-db
- **GOTCHA**: CMAUP compound IDs won't match Duke's IDs directly — MUST join via normalized name. Track match rate and log unmatched compounds. CMAUP uses tab-separated, not comma-separated.
- **VALIDATE**: `tsx scripts/load-cmaup.ts` populates targets (758+), compound_targets (non-zero), target_diseases (non-zero). Log match rates.

### Task 4: Create CTD Loader Script
- **ACTION**: Create `scripts/load-ctd.ts` to parse manually-downloaded CTD CSV.gz files
- **IMPLEMENT**:
  - New tables: `chemical_diseases` (chemical_id, disease_name, disease_id, direct_evidence, inference_gene_symbol, inference_score, source), `chemical_phenotypes` (chemical_id, phenotype_name, phenotype_id, interaction, source)
  - Parse `CTD_chemicals_diseases.csv.gz` → chemical_diseases
  - Parse `CTD_chem_phenotype_interactions.csv.gz` → chemical_phenotypes
  - Join to existing compounds via normalizeCompoundName on CTD ChemicalName
  - Filter to only chemicals that match our compound universe (skip pharmaceutical-only chemicals)
- **MIRROR**: SCHEMA_CREATION, BATCH_INSERT, NORMALIZE_COMPOUND
- **IMPORTS**: fs, path, zlib (for gunzip), readline (for streaming), Database
- **GOTCHA**: CTD files have comment headers (lines starting with #). Skip them during parsing. Files can be large (2GB+) — MUST stream line-by-line, not read entire file. CTD requires manual download due to CAPTCHA — script should check for file existence and print instructions if missing.
- **VALIDATE**: After manual CTD download, `tsx scripts/load-ctd.ts` populates chemical_diseases with 1000+ rows (filtered to our compound universe)

### Task 5: Create TTD Loader Script
- **ACTION**: Create `scripts/load-ttd.ts` to parse TTD target data with druggability status
- **IMPLEMENT**:
  - Parse `P1-01-TTD_target_download.txt` → enrich targets table with druggability_status (Successful, Clinical Trial, Preclinical, Research)
  - Parse `P1-05-TTD_drug_disease.txt` → enrich target_diseases with drug-disease associations
  - Cross-reference targets via gene_symbol and uniprot_id matching with CMAUP targets
- **MIRROR**: CSV_PARSING (TSV), BATCH_INSERT
- **IMPORTS**: fs, path, Database
- **GOTCHA**: TTD uses a non-standard flat-file format (not strict TSV in some files). Some files use key-value pairs per record. Read the Download_Readme for column definitions. Dedup targets by uniprot_id.
- **VALIDATE**: Targets table enriched with druggability_status column; at least 500 targets have status set

### Task 6: Create Orchestrator Migration Script
- **ACTION**: Create `scripts/migrate-multi-source.ts` as the single entry point for all new data integration
- **IMPLEMENT**:
  - Step 1: Schema additions (new tables: chemical_diseases, chemical_phenotypes; new columns on targets: druggability_status)
  - Step 2: Load CMAUP (call load-cmaup logic)
  - Step 3: Load CTD (call load-ctd logic, skip if files not present)
  - Step 4: Load TTD (call load-ttd logic, skip if files not present)
  - Step 5: Print summary stats (total rows per table, match rates, unmatched compounds)
  - All operations idempotent (IF NOT EXISTS, INSERT OR IGNORE)
- **MIRROR**: MIGRATION_PATTERN from migrate-kg-expansion.ts
- **IMPORTS**: Database, all loader modules
- **GOTCHA**: Must run AFTER existing migrate-kg-expansion.ts (depends on symptoms, targets tables existing). Add a check for prerequisite tables.
- **VALIDATE**: `npm run migrate-multi-source` completes without error; getStats() shows populated counts

### Task 7: Update Types and Adapter
- **ACTION**: Add new TypeScript types and adapter methods for new data
- **IMPLEMENT**:
  - types.ts: Add `Disease`, `ChemicalDisease`, `ChemicalPhenotype`, `TargetDruggability` interfaces
  - HerbalDBAdapter.ts: Add methods:
    - `getTargetDiseases(targetId: string): Disease[]`
    - `searchDiseases(query: string, page, pageSize): PaginatedResult<Disease>`
    - `getChemicalDiseases(compoundId: string): ChemicalDisease[]`
  - Update `getStats()` to include new table counts
- **MIRROR**: Existing adapter methods (parameterized queries, PaginatedResult return type)
- **IMPORTS**: Types from types.ts
- **GOTCHA**: Reuse existing normalizeCompoundName for compound lookups. Cap IN-clause arrays (MAX_IN_PARAMS = 50, from recent fix).
- **VALIDATE**: TypeScript compiles (`npx tsc --noEmit`), new methods return expected types

### Task 8: Register New MCP Tools
- **ACTION**: Add MCP tools for querying new data layers
- **IMPLEMENT**:
  - `search-diseases`: Search diseases by name, returns associated targets and compounds
  - `get-target-diseases`: Get diseases associated with a specific target
  - `get-chemical-diseases`: Get disease associations for a compound (from CTD)
  - Each with Zod schema, description, try/catch error handling
- **MIRROR**: Existing tool registration pattern (5-arg server.tool call), ERROR_CONTENT_HANDLER
- **IMPORTS**: z from zod, new adapter methods
- **GOTCHA**: Wrap all handlers in try/catch returning errorContent() (fix from review). Add readOnlyHint: true to all tools.
- **VALIDATE**: `npm run build` succeeds; MCP inspector shows 14+ tools

### Task 9: Clone Graphiti Submodule
- **ACTION**: Add graphiti as a git submodule at repo root
- **IMPLEMENT**:
  ```bash
  git submodule add https://github.com/getzep/graphiti.git graphiti
  ```
- **MIRROR**: SUBMODULE_PATTERN from .gitmodules (existing usda-fdc-data, mcp-opennutrition entries)
- **IMPORTS**: N/A
- **GOTCHA**: Clone at repo root level (same as other submodules), not inside mcp-herbal-botanicals/. Verify .gitmodules updated correctly.
- **VALIDATE**: `.gitmodules` has 3 entries; `ls graphiti/` shows repo contents

### Task 10: Create Graphiti Configuration
- **ACTION**: Create Python configuration for Graphiti with local embeddings and Railway Neo4j
- **IMPLEMENT**:
  - `mcp-herbal-botanicals/graphiti/requirements.txt`: graphiti-core, neo4j, openai
  - `mcp-herbal-botanicals/graphiti/config.py`:
    ```python
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j-test-2be3.up.railway.app:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")  # MUST be set
    EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-embeddinggemma-300m-qat")
    EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))  # verify actual dim
    ```
  - `mcp-herbal-botanicals/graphiti/.env.example` with all env vars documented
- **MIRROR**: No existing Python pattern — follow standard Python conventions (os.getenv, dotenv)
- **IMPORTS**: os, dotenv
- **GOTCHA**: Neo4j password MUST be provided as env var — never hardcode. The proxy endpoint `metro.proxy.rlwy.net:22971` may be needed instead of the domain endpoint depending on network. Embedding dimension must match the actual model output — verify with a test curl before configuring.
- **VALIDATE**: `python -c "from config import *; print(NEO4J_URI)"` prints the URI

### Task 11: Create Graphiti Ingestion Script
- **ACTION**: Create `mcp-herbal-botanicals/graphiti/ingest.py` to load SQLite data into Graphiti KG
- **IMPLEMENT**:
  - Connect to Graphiti with config from config.py
  - Read herbs, compounds, targets, diseases from SQLite
  - For each entity type, create episodes via `graphiti.add_episode()` with `EpisodeType.json`
  - Batch in groups of 100 episodes (Graphiti makes LLM calls per episode)
  - Progress logging with counts
  - Start with herbs (2,376) and compounds (top 1,000 by herb_count) for initial experiment
  - Add compound-target and compound-food edges as separate episode batches
- **MIRROR**: Graphiti `add_episode` pattern from research
- **IMPORTS**: graphiti_core, sqlite3, json, asyncio, config
- **GOTCHA**: Graphiti calls LLM for entity extraction even on structured JSON — this can be slow and costly. Start with a SMALL subset (100 herbs, 500 compounds) to validate. Use local LLM via LM Studio if possible for extraction too (set `OPENAI_BASE_URL`). The 4.1M compound-food edges should NOT be ingested — sample top 10K by content_value.
- **VALIDATE**: After running on 100-herb subset, Neo4j Browser at `https://neo4j-test-2be3.up.railway.app:7474` shows Herb and Compound nodes

### Task 12: Create Neo4j Visualization Guide
- **ACTION**: Create `docs/graphiti-neo4j-guide.md` with setup and visualization instructions
- **IMPLEMENT**:
  - Section 1: Cloud Neo4j (Railway) — how to connect Neo4j Browser to the Railway instance
  - Section 2: Local Neo4j — `docker run` commands, Graphiti local config
  - Section 3: Cypher query examples for exploring the KG
  - Section 4: Graphiti search API examples
  - Section 5: Comparison queries (same question via MCP tool vs Graphiti vs raw Cypher)
- **MIRROR**: Existing docs style from `docs/data-sources-catalog.md` and `docs/kg-architecture-design.md`
- **IMPORTS**: N/A (documentation)
- **GOTCHA**: Railway Neo4j may use HTTP port 7474 for browser and bolt port 7687 for connections — document both. Include proxy endpoint as fallback.
- **VALIDATE**: Doc renders correctly in markdown; all Cypher examples are syntactically valid

### Task 13: Update Package.json and Write Tests
- **ACTION**: Add npm scripts for new ETL stages and write integration tests
- **IMPLEMENT**:
  - package.json scripts:
    - `"download-cmaup": "tsx scripts/download-sources.ts --cmaup-only"`
    - `"download-ttd": "tsx scripts/download-sources.ts --ttd-only"`
    - `"migrate-multi-source": "tsx scripts/migrate-multi-source.ts"`
    - `"download-all": "tsx scripts/download-sources.ts"`
  - Tests in `src/__tests__/multi-source.test.ts`:
    - getStats() returns non-zero for targets, compound_targets, target_diseases
    - searchDiseases finds known diseases
    - getCompoundTargets returns results for curcumin (after CMAUP loaded)
    - getChemicalDiseases returns results (after CTD loaded)
    - getTargetDiseases returns results
    - Pagination works on new endpoints
- **MIRROR**: TEST_STRUCTURE (describe.skipIf pattern)
- **IMPORTS**: vitest, HerbalDBAdapter, fs, path
- **GOTCHA**: Tests depend on data being loaded — use describe.skipIf(!DB_EXISTS) pattern. Some tests may need additional skipIf for CTD-specific data (manual download dependency).
- **VALIDATE**: `npm test` passes; new tests are either green (if data loaded) or properly skipped (if not)

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| getStats includes new tables | N/A | targets > 0, compound_targets > 0 | No |
| searchDiseases("diabetes") | "diabetes" | Non-empty results | No |
| searchDiseases("xyznonexistent") | "xyznonexistent" | Empty results | Yes |
| getCompoundTargets("curcumin") | "curcumin" | Non-empty after CMAUP | No |
| getChemicalDiseases with unknown compound | "fake_id" | Empty array | Yes |
| getTargetDiseases pagination | page=1, pageSize=5 | 5 results, hasMore=true | No |
| normalizeCompoundName handles CMAUP names | "β-Sitosterol" | "sitosterol" | Yes |

### Edge Cases Checklist
- [x] Empty input (Zod min(1) validation)
- [ ] Compound with no target matches (return empty array)
- [ ] CTD files not present (skip with warning)
- [ ] CMAUP TSV with malformed rows (skip row, log warning)
- [ ] Duplicate targets across CMAUP + TTD (dedup by uniprot_id)
- [ ] Compound name normalization edge cases (unicode, CJK characters)

---

## Validation Commands

### Static Analysis
```bash
cd mcp-herbal-botanicals && npx tsc --noEmit
```
EXPECT: Zero type errors

### Unit Tests
```bash
cd mcp-herbal-botanicals && npx vitest run
```
EXPECT: All tests pass (or properly skipped if data not loaded)

### Full ETL Pipeline
```bash
cd mcp-herbal-botanicals
npm run download-data          # Duke + FooDB (existing)
npm run convert-data           # Build base DB (existing)
npm run migrate-kg             # KG expansion (existing)
npm run download-cmaup         # New: fetch CMAUP
npm run download-ttd           # New: fetch TTD
npm run migrate-multi-source   # New: load all new sources
```
EXPECT: Each command completes without error; getStats shows populated counts

### Database Validation
```bash
cd mcp-herbal-botanicals
npx tsx -e "
  const { HerbalDBAdapter } = await import('./src/HerbalDBAdapter.js');
  const db = new HerbalDBAdapter('data_local/herbal_botanicals.db');
  console.log(JSON.stringify(db.getStats(), null, 2));
  db.close();
"
```
EXPECT: targets > 700, compound_targets > 1000, target_diseases > 500

### Graphiti Smoke Test
```bash
cd mcp-herbal-botanicals/graphiti
python -c "
from config import *
print(f'Neo4j: {NEO4J_URI}')
print(f'Embeddings: {EMBEDDING_BASE_URL}')
print(f'Model: {EMBEDDING_MODEL}')
print(f'Dim: {EMBEDDING_DIM}')
"
```
EXPECT: Prints all config values without error

### Submodule Validation
```bash
git submodule status
```
EXPECT: Shows graphiti submodule alongside usda-fdc-data and mcp-opennutrition

### Manual Validation
- [ ] manifest.yaml passes YAML lint
- [ ] All 7 datasets documented with schemas in manifest
- [ ] CMAUP download script fetches files successfully
- [ ] TTD download script fetches files successfully
- [ ] CTD manual download instructions are clear in manifest
- [ ] Graphiti config connects to Railway Neo4j (may need password)
- [ ] Neo4j Browser accessible at Railway HTTP endpoint

---

## Acceptance Criteria
- [ ] manifest.yaml describes all 7 Tier-1 datasets with schemas
- [ ] CMAUP and TTD auto-downloadable via npm scripts
- [ ] CTD, HERB, SymMap documented with manual download instructions
- [ ] targets table populated with 700+ entries (CMAUP)
- [ ] compound_targets table populated with non-zero entries
- [ ] target_diseases table populated with non-zero entries
- [ ] Graphiti cloned as submodule with Python config
- [ ] All validation commands pass
- [ ] New integration tests written and passing (or properly skipped)
- [ ] No type errors, no lint errors

## Completion Checklist
- [ ] Code follows discovered patterns (DownloadTarget, normalizeCompoundName, batch transactions)
- [ ] Error handling uses try/catch + errorContent() pattern
- [ ] Tests use describe.skipIf(!DB_EXISTS) pattern
- [ ] No hardcoded secrets (Neo4j password from env var)
- [ ] manifest.yaml is comprehensive and human-readable
- [ ] docs/graphiti-neo4j-guide.md covers local + cloud setup
- [ ] package.json has all new npm scripts
- [ ] Self-contained — no questions needed during implementation

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| CMAUP download URLs change | Low | Medium | Document alternative access in manifest |
| CTD CAPTCHA blocks automation | Certain | Low | Mark as manual download, provide clear instructions |
| HERB 2.0 / SymMap servers down | High | Medium | Use cached/archived data; mark as manual_fallback in manifest |
| CMAUP compound names don't match Duke's | Medium | High | Log match rates; accept partial coverage; try PubChem CID fallback |
| Graphiti OOM on large datasets | Medium | Medium | Start with small subset (100 herbs); batch ingestion |
| Neo4j Railway needs credentials | Certain | Low | User must provide password as env var |
| Embedding model dimension unknown | Medium | Low | Test with curl to local LM Studio before configuring |

## Notes
- The PRD combines Phases 1-3 into this single plan because Phase 3 (Graphiti setup) has no data dependency and can happen in parallel with Phase 2 (SQLite integration)
- Phase 4 (Graphiti indexing) and Phase 5 (benchmarking) will be separate plans once this foundation is in place
- BATMAN-TCM is explicitly skipped due to no bulk download — if user acquires data later, a loader can be added following the same pattern
- The manifest.yaml becomes the single source of truth for all dataset metadata — future phases reference it instead of hardcoded values
