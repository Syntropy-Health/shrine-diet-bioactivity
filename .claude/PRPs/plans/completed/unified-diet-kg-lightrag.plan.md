# Plan: Unified Diet Knowledge Graph with LightRAG

## Summary
Unify the herbal-botanicals SQLite dataset (2,376 herbs, 94K compounds, 4.3K targets, 4.1M compound-food pairs) with OpenNutrition (326K foods, 90 nutrient keys) into a single cohesive dataset, then index it into a LightRAG-powered semantic knowledge graph backed by Neo4j. Create dual embedding/LLM configs: local Ollama for dev/test and API-based (OpenAI/Anthropic) for production, with multilingual support for Chinese+English TCM data.

## User Story
As an LLM dietitian agent, I want to query a unified semantic knowledge graph spanning macronutrients, foods, herbs, phytochemicals, bioactive compounds, targets, and diseases, so that I can provide evidence-backed dietary recommendations tracing the full pathway from symptom to molecular target to food with both nutritional and phytochemical data.

## Problem → Solution
**Current**: Two isolated datasets — herbal-botanicals has phytochemical/compound/target/disease data but no nutritional profiles; OpenNutrition has 90-nutrient profiles for 326K foods but no phytochemical/bioactivity data. LLM agents must orchestrate two separate MCP servers. Graphiti was tested but is designed for episodic memory, not static reference KGs.

**Desired**: A single unified SQLite dataset with food-level nutrition enrichment via a bridge table, indexed into LightRAG's semantic KG (Neo4j graph + vector embeddings) for multi-hop retrieval. Dual config profiles for local dev vs production API.

## Metadata
- **Complexity**: Large
- **Source PRD**: `.claude/PRPs/prds/unified-phyto-kg-graphiti.prd.md`
- **PRD Phase**: Phase 2 — Unified Dataset + LightRAG migration (supersedes Graphiti)
- **Estimated Files**: 15-20

---

## UX Design
N/A — internal data pipeline and KG indexing. No user-facing UI changes. LLM agents interact via MCP tools (existing) and LightRAG query API (new).

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `mcp-herbal-botanicals/scripts/build-herbal-db.js` | 58-130 | Full SQLite schema — all CREATE TABLE statements |
| P0 | `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | all | Query patterns, pagination, tableExists() guards |
| P0 | `lightrag/lightrag/lightrag.py` | 2375-2548 | `ainsert_custom_kg()` — direct entity/relationship injection API |
| P0 | `lightrag/lightrag/kg/neo4j_impl.py` | 1021-1120 | Neo4j upsert_node/upsert_edge — Cypher MERGE patterns |
| P1 | `lightrag/env.example` | 246-400 | LLM + embedding + storage config options |
| P1 | `lightrag/lightrag/llm/ollama.py` | 175-230 | Ollama embedding function signature (`ollama_embed`) |
| P1 | `lightrag/lightrag/constants.py` | 29-41 | Default entity types — we override with domain types |
| P1 | `mcp-opennutrition/src/SQLiteDBAdapter.ts` | 116-163 | Nutrient key lists (MACRO_NUTRIENT_KEYS, MICRO_UNITS) |
| P2 | `mcp-herbal-botanicals/scripts/load-cmaup.ts` | 1-50 | ETL pattern: readTsvFile, compound lookup, cross-ref |
| P2 | `mcp-herbal-botanicals/src/__tests__/multi-source.test.ts` | 1-40 | Test pattern: vitest, skipIf, beforeAll/afterAll |
| P2 | `mcp-herbal-botanicals/Makefile` | 1-60 | Make targets pattern, Neo4j connection defaults |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| LightRAG custom KG insertion | `lightrag/lightrag/lightrag.py:2375` | `ainsert_custom_kg({"chunks":[], "entities":[], "relationships":[]})` bypasses LLM — zero cost for structured data |
| LightRAG Neo4j storage | `lightrag/lightrag/kg/neo4j_impl.py:1060` | Uses `MERGE (n:\`{workspace_label}\` {entity_id: $entity_id}) SET n += $properties SET n:\`{entity_type}\`` |
| LightRAG entity types config | `lightrag/env.example:192` | `ENTITY_TYPES='["Herb","Compound","Food",...]'` — configurable extraction types |
| LightRAG multilingual | `lightrag/env.example:179` | `SUMMARY_LANGUAGE=English` — controls extraction/summary language |
| Ollama embedding | `lightrag/lightrag/llm/ollama.py:175-230` | `ollama_embed(texts, embed_model="bge-m3:latest")` with `@wrap_embedding_func_with_attrs(embedding_dim=1024)` |
| OpenAI embedding | `lightrag/env.example:354-360` | `EMBEDDING_BINDING=openai`, `EMBEDDING_MODEL=text-embedding-3-large`, `EMBEDDING_DIM=3072` |

---

## Patterns to Mirror

### NAMING_CONVENTION
```typescript
// SOURCE: mcp-herbal-botanicals/scripts/load-cmaup.ts:1-9
// Script header with usage docstring, tsx runner
/**
 * Load CMAUP v2.0 data into herbal_botanicals.db.
 * Populates: targets, compound_targets, target_diseases tables.
 * Usage: tsx scripts/load-cmaup.ts
 */
```

### ETL_PATTERN
```typescript
// SOURCE: mcp-herbal-botanicals/scripts/load-cmaup.ts:42-50
// Build compound lookup map from existing DB, cross-reference by normalized name
export function loadCmaup(db: Database.Database): { targets: number; compoundTargets: number; ... } {
  const compoundLookup = new Map<string, string>();
  const compoundRows = db.prepare('SELECT id, name_normalized FROM compounds').all();
  for (const row of compoundRows) {
    compoundLookup.set(row.name_normalized, row.id);
  }
```

### COMPOUND_NORMALIZATION
```javascript
// SOURCE: mcp-herbal-botanicals/scripts/build-herbal-db.js:22-27
export function normalizeCompoundName(name) {
    return name.toLowerCase().trim().replace(/[^a-z0-9]/g, '');
}
```

### TEST_STRUCTURE
```typescript
// SOURCE: mcp-herbal-botanicals/src/__tests__/multi-source.test.ts:1-18
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');
const DB_EXISTS = fs.existsSync(DB_PATH);
describe.skipIf(!DB_EXISTS)('Multi-source integration tests', () => {
  let db: HerbalDBAdapter;
  beforeAll(() => { db = new HerbalDBAdapter(DB_PATH); });
  afterAll(() => { db?.close(); });
```

### MAKEFILE_TARGET
```makefile
# SOURCE: mcp-herbal-botanicals/Makefile:50-57
download: ## Download Duke + FooDB source data (~960 MB)
	npm run download-data

download-cmaup: ## Download CMAUP v2.0 data files (~10 MB)
	npm run download-cmaup
```

### LIGHTRAG_CUSTOM_KG_FORMAT
```python
# SOURCE: lightrag/lightrag/lightrag.py:2375-2510
# Direct KG injection — no LLM calls
custom_kg = {
    "chunks": [
        {"content": "text content", "source_id": "src-001", "file_path": "herbal_botanicals.db"}
    ],
    "entities": [
        {"entity_name": "Curcumin", "entity_type": "Compound",
         "description": "Anti-inflammatory polyphenol from turmeric",
         "source_id": "src-001"}
    ],
    "relationships": [
        {"src_id": "Curcumin", "tgt_id": "COX-2", "description": "inhibits COX-2 enzyme",
         "keywords": "anti-inflammatory, enzyme inhibition", "weight": 1.0,
         "source_id": "src-001"}
    ]
}
await rag.ainsert_custom_kg(custom_kg)
```

### LIGHTRAG_NEO4J_CONFIG
```env
# SOURCE: lightrag/env.example:499-511
NEO4J_URI=bolt://metro.proxy.rlwy.net:22971
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=demodemo
NEO4J_DATABASE=neo4j
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `mcp-herbal-botanicals/scripts/build-food-bridge.ts` | CREATE | Fuzzy-match FooDB 962 foods → OpenNutrition fd_ IDs |
| `mcp-herbal-botanicals/scripts/enrich-nutrition.ts` | CREATE | Add nutrition_100g from OpenNutrition to compound_foods |
| `mcp-herbal-botanicals/lightrag/config_local.env` | CREATE | Local Ollama config for dev/test |
| `mcp-herbal-botanicals/lightrag/config_production.env` | CREATE | API-based config (OpenAI embed + Claude LLM) for prod |
| `mcp-herbal-botanicals/lightrag/ingest_unified.py` | CREATE | Extract entities/rels from unified SQLite → LightRAG `ainsert_custom_kg()` |
| `mcp-herbal-botanicals/lightrag/entity_schema.py` | CREATE | Domain entity type definitions and description generators |
| `mcp-herbal-botanicals/lightrag/requirements.txt` | CREATE | Python deps for LightRAG ingestion |
| `mcp-herbal-botanicals/lightrag/test_ingest.py` | CREATE | Dry-run validation tests for ingestion pipeline |
| `mcp-herbal-botanicals/lightrag/query_benchmark.py` | CREATE | 10 benchmark multi-hop queries for evaluation |
| `mcp-herbal-botanicals/src/__tests__/food-bridge.test.ts` | CREATE | Unit tests for food bridge matching |
| `mcp-herbal-botanicals/scripts/build-herbal-db.js` | UPDATE | Add nutrition_100g column to compound_foods schema |
| `mcp-herbal-botanicals/src/HerbalDBAdapter.ts` | UPDATE | Query methods for nutrition-enriched food data |
| `mcp-herbal-botanicals/src/types.ts` | UPDATE | Add NutrientProfile interface |
| `mcp-herbal-botanicals/Makefile` | UPDATE | Add lightrag targets, food-bridge, enrich |
| `mcp-herbal-botanicals/package.json` | UPDATE | Add bridge/enrich scripts |
| `mcp-herbal-botanicals/data/manifest.yaml` | UPDATE | Add OpenNutrition as data source |

## NOT Building

- New MCP server — extending existing mcp-herbal-botanicals
- Web UI — using LightRAG's built-in WebUI + Neo4j Browser
- Custom embedding model training — using off-the-shelf models
- Full OpenNutrition ingestion (326K foods) into KG — only the ~962 FooDB-bridged foods get KG nodes
- Production deployment — this is PoC on Railway test instances
- LLM-based entity extraction — all data is pre-structured, using `ainsert_custom_kg()` exclusively
- Graphiti integration — superseded by LightRAG

---

## Step-by-Step Tasks

### Task 1: Add OpenNutrition to Data Manifest
- **ACTION**: Update `data/manifest.yaml` to document OpenNutrition as a Tier-1 data source
- **IMPLEMENT**: Add entry under `datasets:` with name, version, license (ODbL), path (`../mcp-opennutrition/data_local/opennutrition_foods.db`), schema details (foods table, nutrition_100g JSON, 326K rows), and join keys (food name fuzzy match + USDA FDC ID)
- **MIRROR**: Existing manifest entries (duke, foodb) for format
- **VALIDATE**: `cat data/manifest.yaml | grep -c opennutrition` returns 1

### Task 2: Build Food Name Bridge Table
- **ACTION**: Create `scripts/build-food-bridge.ts` to fuzzy-match FooDB's 962 food names to OpenNutrition's 326K foods
- **IMPLEMENT**:
  1. Read all `SELECT DISTINCT food_name FROM compound_foods` from herbal DB (962 foods)
  2. For each FooDB food name:
     a. Try exact case-insensitive match against OpenNutrition `foods.name`
     b. Try LIKE `%{name}%` match filtered by `type='everyday'` (prefer whole foods)
     c. Try tokenized match (split on spaces, match all tokens)
  3. Create bridge table: `CREATE TABLE food_nutrition_bridge (foodb_food_name TEXT PRIMARY KEY, opennutrition_id TEXT, opennutrition_name TEXT, match_type TEXT, match_score REAL)`
  4. Insert matched pairs with match quality score
  5. Report stats: exact matches, fuzzy matches, unmatched
- **IMPORTS**: `better-sqlite3`, `path`, `fs`
- **GOTCHA**: OpenNutrition DB is at `../mcp-opennutrition/data_local/opennutrition_foods.db` (different submodule). Open both DBs. FooDB uses generic names ("Chicken", "Apple") while OpenNutrition uses specific names ("Chicken Breast, Boneless Skinless, Cooked"). Prefer `type='everyday'` matches.
- **VALIDATE**: Run script, expect 400-600 matches (50-60% of 962). Log unmatched for manual review.

### Task 3: Enrich compound_foods with Nutrition Data
- **ACTION**: Create `scripts/enrich-nutrition.ts` to populate nutrition_100g on compound_foods rows via the bridge
- **IMPLEMENT**:
  1. Read `food_nutrition_bridge` table
  2. For each bridged food, fetch `nutrition_100g` JSON from OpenNutrition DB
  3. Add column to herbal DB: `ALTER TABLE compound_foods ADD COLUMN nutrition_100g TEXT`
  4. Update rows: `UPDATE compound_foods SET nutrition_100g = ? WHERE food_name = ?`
  5. Report coverage: N foods enriched, M total compound_foods rows enriched
- **IMPORTS**: `better-sqlite3`, `path`
- **GOTCHA**: `nutrition_100g` is stored as JSON TEXT in OpenNutrition. Don't parse/reparse — copy as-is. Only update foods that have a bridge match.
- **VALIDATE**: `SELECT COUNT(*) FROM compound_foods WHERE nutrition_100g IS NOT NULL` should be > 0

### Task 4: Update Types and Adapter for Nutrition Data
- **ACTION**: Add `NutrientProfile` interface and update adapter queries to return nutrition data
- **IMPLEMENT**:
  - In `src/types.ts`: Add `NutrientProfile` interface matching OpenNutrition's 90-key JSON structure (calories, protein, carbohydrates, total_fat, dietary_fiber, vitamins, minerals, amino acids)
  - In `src/HerbalDBAdapter.ts`: Update `getCompoundFoods()` and `findFunctionalFoods()` to include `nutrition_100g` in SELECT when available
  - Add `getFoodNutrition(foodName: string): NutrientProfile | null` method
- **MIRROR**: Existing adapter query pattern with `tableExists()` guard and `emptyPaginated()` fallback
- **VALIDATE**: `npx tsc --noEmit` passes, existing tests still pass

### Task 5: Create LightRAG Python Environment
- **ACTION**: Create `mcp-herbal-botanicals/lightrag/` directory with requirements and config files
- **IMPLEMENT**:
  - `requirements.txt`: `lightrag-hku>=0.1.0`, `neo4j>=5.26`, `numpy`, `python-dotenv`
  - `config_local.env` (dev/test — local Ollama):
    ```
    LLM_BINDING=ollama
    LLM_BINDING_HOST=http://localhost:11434
    LLM_MODEL=qwen3.5:9b
    OLLAMA_LLM_NUM_CTX=32768
    EMBEDDING_BINDING=ollama
    EMBEDDING_BINDING_HOST=http://localhost:11434
    EMBEDDING_MODEL=bge-m3:latest
    EMBEDDING_DIM=1024
    LIGHTRAG_GRAPH_STORAGE=Neo4JStorage
    LIGHTRAG_KV_STORAGE=JsonKVStorage
    LIGHTRAG_VECTOR_STORAGE=NanoVectorDBStorage
    LIGHTRAG_DOC_STATUS_STORAGE=JsonDocStatusStorage
    NEO4J_URI=bolt://metro.proxy.rlwy.net:22971
    NEO4J_USERNAME=neo4j
    NEO4J_PASSWORD=demodemo
    WORKSPACE=unified_diet_kg
    ENTITY_TYPES='["Herb","Compound","Food","Target","Disease","Symptom","Nutrient"]'
    SUMMARY_LANGUAGE=English
    MAX_ASYNC=4
    MAX_PARALLEL_INSERT=2
    ```
  - `config_production.env` (production — API models, multilingual):
    ```
    LLM_BINDING=openai
    LLM_BINDING_HOST=https://api.openai.com/v1
    LLM_MODEL=gpt-4o-mini
    EMBEDDING_BINDING=openai
    EMBEDDING_BINDING_HOST=https://api.openai.com/v1
    EMBEDDING_MODEL=text-embedding-3-large
    EMBEDDING_DIM=3072
    LIGHTRAG_GRAPH_STORAGE=Neo4JStorage
    LIGHTRAG_KV_STORAGE=JsonKVStorage
    LIGHTRAG_VECTOR_STORAGE=NanoVectorDBStorage
    LIGHTRAG_DOC_STATUS_STORAGE=JsonDocStatusStorage
    NEO4J_URI=${NEO4J_URI}
    NEO4J_USERNAME=${NEO4J_USERNAME}
    NEO4J_PASSWORD=${NEO4J_PASSWORD}
    WORKSPACE=unified_diet_kg_prod
    ENTITY_TYPES='["Herb","Compound","Food","Target","Disease","Symptom","Nutrient","TCM_Formula","Meridian","Organ"]'
    SUMMARY_LANGUAGE=English
    MAX_ASYNC=8
    MAX_PARALLEL_INSERT=4
    RERANK_BINDING=jina
    RERANK_MODEL=jina-reranker-v2-base-multilingual
    ```
- **GOTCHA**: Production config uses env var substitution for secrets (NEO4J_URI etc.) — never hardcode. Local config hardcodes Railway test credentials (already public in Makefile).
- **VALIDATE**: `python -c "from dotenv import dotenv_values; c = dotenv_values('config_local.env'); assert 'ENTITY_TYPES' in c"`

### Task 6: Create Domain Entity Schema
- **ACTION**: Create `lightrag/entity_schema.py` defining how SQLite entities map to LightRAG KG nodes and edges
- **IMPLEMENT**:
  ```python
  ENTITY_TYPES = {
      "Herb": {"source_table": "herbs", "id_field": "id",
               "desc_template": "{scientific_name} ({common_name}). Family: {family}. Uses: {usage_type}"},
      "Compound": {"source_table": "compounds", "id_field": "id",
                    "desc_template": "{name}. Class: {compound_class}. Bioactivities: {bioactivities}"},
      "Food": {"source_table": "compound_foods", "id_field": "food_name",
               "desc_template": "{food_name} ({food_group}). Nutrients: {nutrition_summary}"},
      "Target": {"source_table": "targets", "id_field": "id",
                  "desc_template": "{target_name}. Protein: {protein_target}"},
      "Disease": {"source_table": "target_diseases", "id_field": "disease_name",
                   "desc_template": "{disease_name}. Evidence: {evidence_layer}"},
      "Symptom": {"source_table": "symptoms", "id_field": "id",
                   "desc_template": "{symptom_name}"},
  }

  RELATIONSHIP_TYPES = {
      "CONTAINS_COMPOUND": {"source": "herb_compounds", "src_type": "Herb", "tgt_type": "Compound",
                             "desc_template": "{herb_name} contains {compound_name} ({concentration_low_ppm}-{concentration_high_ppm} PPM in {plant_part})"},
      "FOUND_IN_FOOD": {"source": "compound_foods", "src_type": "Compound", "tgt_type": "Food",
                          "desc_template": "{compound_name} found in {food_name} ({content_value} {content_unit})"},
      "TARGETS_PROTEIN": {"source": "compound_targets", "src_type": "Compound", "tgt_type": "Target",
                            "desc_template": "{compound_name} targets {target_name} (activity: {activity_value})"},
      "ASSOCIATED_WITH_DISEASE": {"source": "target_diseases", "src_type": "Target", "tgt_type": "Disease",
                                    "desc_template": "{target_name} associated with {disease_name} ({evidence_layer})"},
      "TREATS_SYMPTOM": {"source": "herb_symptoms", "src_type": "Herb", "tgt_type": "Symptom",
                           "desc_template": "{herb_name} treats {symptom_name}"},
      "HAS_NUTRIENT_PROFILE": {"source": "food_nutrition_bridge", "src_type": "Food", "tgt_type": "Nutrient",
                                 "desc_template": "{food_name} provides {nutrient_name}: {value} {unit} per 100g"},
  }
  ```
- **GOTCHA**: Chinese herb names from TCM datasets — entity descriptions should include both scientific_name and common_name. For production config, `SUMMARY_LANGUAGE=English` ensures English-language graph summaries even when source data contains Chinese characters.
- **VALIDATE**: `python -c "from entity_schema import ENTITY_TYPES, RELATIONSHIP_TYPES; assert len(ENTITY_TYPES) == 6; assert len(RELATIONSHIP_TYPES) == 6"`

### Task 7: Create LightRAG Unified Ingestion Script
- **ACTION**: Create `lightrag/ingest_unified.py` to extract entities and relationships from the unified SQLite DB and load them into LightRAG via `ainsert_custom_kg()`
- **IMPLEMENT**:
  1. Parse CLI args: `--config {local|production}`, `--dry-run`, `--max-herbs N`, `--max-compounds N`, `--max-foods N`, `--batch-size N`
  2. Load config from `config_{local|production}.env` via `dotenv`
  3. Initialize LightRAG with Neo4j storage:
     ```python
     from lightrag import LightRAG, QueryParam
     from lightrag.llm.ollama import ollama_model_complete, ollama_embed  # or openai variants
     rag = LightRAG(working_dir="./rag_storage", llm_model_func=..., embedding_func=...)
     await rag.initialize_storages()
     ```
  4. Connect to SQLite DB at `../data_local/herbal_botanicals.db`
  5. Extract entities in order (respecting FK dependencies):
     a. **Herbs** → `SELECT * FROM herbs LIMIT {max_herbs}` → entity_type="Herb"
     b. **Compounds** → `SELECT * FROM compounds LIMIT {max_compounds}` → entity_type="Compound"
     c. **Foods** → `SELECT DISTINCT food_name, food_group, nutrition_100g FROM compound_foods LIMIT {max_foods}` → entity_type="Food"
     d. **Targets** → `SELECT * FROM targets` → entity_type="Target"
     e. **Diseases** → `SELECT DISTINCT disease_name FROM target_diseases UNION SELECT DISTINCT disease_name FROM chemical_diseases` → entity_type="Disease"
     f. **Symptoms** → `SELECT * FROM symptoms` → entity_type="Symptom"
  6. Extract relationships:
     a. **CONTAINS_COMPOUND** → `SELECT h.scientific_name, c.name, hc.* FROM herb_compounds hc JOIN herbs h ... JOIN compounds c ...`
     b. **FOUND_IN_FOOD** → `SELECT c.name, cf.* FROM compound_foods cf JOIN compounds c ...`
     c. **TARGETS_PROTEIN** → `SELECT c.name, t.target_name, ct.* FROM compound_targets ct JOIN compounds c ... JOIN targets t ...`
     d. **ASSOCIATED_WITH_DISEASE** → `SELECT t.target_name, td.disease_name, td.* FROM target_diseases td JOIN targets t ...`
     e. **TREATS_SYMPTOM** → `SELECT h.scientific_name, s.symptom_name FROM herb_symptoms hs JOIN herbs h ... JOIN symptoms s ...`
  7. Batch into LightRAG `ainsert_custom_kg()` calls of `batch_size` entities+relationships per call
  8. Generate description text for each entity using templates from `entity_schema.py`
  9. Print ingestion stats: entities per type, relationships per type, elapsed time
  10. Cleanup: `await rag.finalize_storages()`
- **IMPORTS**: `lightrag`, `sqlite3`, `asyncio`, `argparse`, `dotenv`, `json`, `time`
- **GOTCHA**:
  - `ainsert_custom_kg()` embeds entity descriptions — make descriptions rich and searchable (include synonyms, bioactivities, nutrient summaries)
  - For Chinese TCM herb names: include both `scientific_name` and `common_name` in description so embeddings capture both languages
  - Batch size matters — too large may OOM on embedding calls. Start with 500 entities per batch.
  - `source_id` in the custom_kg format links chunks to entities — use a synthetic source_id per batch like `"batch-herbs-001"`
  - Neo4j workspace label isolates data — use `WORKSPACE=unified_diet_kg` to avoid colliding with old Graphiti data
- **VALIDATE**: `python ingest_unified.py --config local --dry-run` should print entity/relationship counts without writing to Neo4j

### Task 8: Create Query Benchmark Script
- **ACTION**: Create `lightrag/query_benchmark.py` with 10 multi-hop benchmark queries
- **IMPLEMENT**:
  ```python
  BENCHMARK_QUERIES = [
      # Single-hop
      {"query": "What compounds are in turmeric?", "mode": "local", "expected_entities": ["Curcumin", "Turmeric"]},
      {"query": "What foods contain quercetin?", "mode": "local", "expected_entities": ["Quercetin"]},
      # Multi-hop (compound → target → disease)
      {"query": "What foods help with inflammation?", "mode": "hybrid", "expected_entities": ["Curcumin", "COX-2"]},
      {"query": "What herbs target COX-2 enzyme?", "mode": "hybrid", "expected_entities": ["COX-2"]},
      # Multi-hop (symptom → herb → compound → food)
      {"query": "What dietary sources contain anti-cancer compounds?", "mode": "hybrid", "expected_entities": []},
      {"query": "Which foods are rich in compounds that target NF-kB pathway?", "mode": "global", "expected_entities": ["NF-kB"]},
      # Nutrition + phytochemical crossover
      {"query": "What foods high in vitamin C also contain antioxidant compounds?", "mode": "mix", "expected_entities": []},
      {"query": "Which herbs used for diabetes are also protein-rich foods?", "mode": "mix", "expected_entities": []},
      # TCM / multilingual
      {"query": "What are the medicinal properties of ginger in traditional medicine?", "mode": "hybrid", "expected_entities": ["Ginger"]},
      {"query": "Compare the bioactive compounds in green tea vs black tea", "mode": "hybrid", "expected_entities": ["Green tea", "Black tea"]},
  ]
  ```
  Run each query against LightRAG in all modes (local, global, hybrid, mix), measure latency, check if expected entities appear in response, output comparison table.
- **VALIDATE**: Script runs without error, produces markdown comparison table

### Task 9: Write Tests for Food Bridge and Ingestion
- **ACTION**: Create TypeScript tests for food bridge and Python tests for ingestion
- **IMPLEMENT**:
  - `src/__tests__/food-bridge.test.ts`: Test fuzzy matching logic, bridge table creation, edge cases (no match, multiple matches, exact vs fuzzy)
  - `lightrag/test_ingest.py`: Test entity extraction from SQLite (counts, description generation, batch formatting), dry-run mode validation
- **MIRROR**: Vitest pattern from `multi-source.test.ts` (skipIf on DB existence)
- **VALIDATE**: `cd mcp-herbal-botanicals && npm test` passes, `cd lightrag && python -m pytest test_ingest.py` passes

### Task 10: Update Makefile and package.json
- **ACTION**: Add new targets for food bridge, nutrition enrichment, and LightRAG operations
- **IMPLEMENT**:
  - `package.json` scripts:
    ```json
    "build-food-bridge": "tsx scripts/build-food-bridge.ts",
    "enrich-nutrition": "tsx scripts/enrich-nutrition.ts",
    ```
  - `Makefile` targets:
    ```makefile
    food-bridge: ## Build food name bridge between FooDB and OpenNutrition
    	npm run build-food-bridge

    enrich-nutrition: food-bridge ## Enrich compound_foods with OpenNutrition data
    	npm run enrich-nutrition

    lightrag-setup: ## Install LightRAG Python dependencies
    	cd lightrag && pip install -r requirements.txt

    lightrag-ingest-local: ## Ingest unified KG into LightRAG (local Ollama)
    	cd lightrag && python ingest_unified.py --config local --batch-size 500

    lightrag-ingest-prod: ## Ingest unified KG into LightRAG (production API)
    	cd lightrag && python ingest_unified.py --config production --batch-size 200

    lightrag-dry-run: ## Dry-run ingestion (no writes)
    	cd lightrag && python ingest_unified.py --config local --dry-run

    lightrag-benchmark: ## Run 10 benchmark queries against LightRAG
    	cd lightrag && python query_benchmark.py --config local

    lightrag-server: ## Start LightRAG API server (local)
    	cd lightrag && lightrag-server
    ```
  - Update `setup` target: `setup: download build migrate food-bridge enrich-nutrition`
- **VALIDATE**: `make help` shows all new targets, `make lightrag-dry-run` succeeds

### Task 11: Clean Up Graphiti Artifacts
- **ACTION**: Remove old Graphiti submodule and scripts that are superseded by LightRAG
- **IMPLEMENT**:
  - Remove `graphiti/` submodule from `.gitmodules` (the root-level one)
  - Keep `mcp-herbal-botanicals/graphiti/` directory but rename configs to `graphiti_legacy/` or add README noting it's superseded
  - Update `docs/kg-ingestion-comparison.md` with LightRAG results
- **GOTCHA**: Don't delete the Graphiti PoC data — it's useful as a comparison reference. Just mark it as legacy.
- **VALIDATE**: `git submodule status` shows lightrag but not graphiti at root level

---

## Testing Strategy

### Unit Tests (TypeScript)

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| bridge exact match | "Garlic" | fd_ ID for Garlic from OpenNutrition | No |
| bridge fuzzy match | "Chicken" | fd_ ID for "Chicken Breast..." | No |
| bridge no match | "Beefalo" | null (no OpenNutrition equivalent) | Yes |
| bridge scoring | "Apple" vs "Apples" | Prefers exact singular match | Yes |
| nutrition enrichment | bridged food | nutrition_100g JSON populated | No |

### Unit Tests (Python)

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| entity extraction herbs | SQLite herbs table | List of entity dicts with type="Herb" | No |
| entity extraction compounds | SQLite compounds table | List with descriptions containing bioactivities | No |
| description generation | Herb row with Chinese name | Description includes both languages | Yes |
| dry-run mode | --dry-run flag | Counts printed, no Neo4j writes | No |
| batch sizing | 1000 entities, batch_size=500 | 2 batches created | No |
| empty table | target_diseases with 0 rows | Empty list, no error | Yes |

### Edge Cases Checklist
- [ ] Empty nutrition_100g JSON (food exists but no nutrient data)
- [ ] Chinese-only herb names (no English common_name)
- [ ] Compound with no food associations
- [ ] Food in FooDB not in OpenNutrition (unmatched bridge)
- [ ] Neo4j connection timeout during ingestion
- [ ] LightRAG workspace collision with existing data
- [ ] Very long entity descriptions (>8192 tokens for embedding)

---

## Validation Commands

### Static Analysis
```bash
cd mcp-herbal-botanicals && npx tsc --noEmit
```
EXPECT: Zero type errors

### Unit Tests
```bash
cd mcp-herbal-botanicals && npm test
```
EXPECT: All tests pass (existing + new food-bridge tests)

### Python Tests
```bash
cd mcp-herbal-botanicals/lightrag && python -m pytest test_ingest.py -v
```
EXPECT: All ingestion tests pass

### Build Verification
```bash
cd mcp-herbal-botanicals && npm run build
```
EXPECT: Clean build, no errors

### Dry-Run Ingestion
```bash
cd mcp-herbal-botanicals && make lightrag-dry-run
```
EXPECT: Prints entity/relationship counts matching SQLite data

### Food Bridge Validation
```bash
cd mcp-herbal-botanicals && npm run build-food-bridge
```
EXPECT: 400+ matched foods, stats printed

### Neo4j Verification (after real ingestion)
```bash
cd mcp-herbal-botanicals && make neo4j-check
```
EXPECT: Nodes and relationships in `unified_diet_kg` workspace

---

## Acceptance Criteria
- [ ] OpenNutrition added to manifest.yaml
- [ ] Food bridge matches 400+ of 962 FooDB foods to OpenNutrition IDs
- [ ] compound_foods table has nutrition_100g for bridged foods
- [ ] LightRAG config_local.env works with Ollama (embedding + LLM)
- [ ] LightRAG config_production.env uses OpenAI embeddings + API LLM
- [ ] Entity types: Herb, Compound, Food, Target, Disease, Symptom all ingested
- [ ] Relationships: CONTAINS_COMPOUND, FOUND_IN_FOOD, TARGETS_PROTEIN, ASSOCIATED_WITH_DISEASE, TREATS_SYMPTOM all ingested
- [ ] Dry-run mode prints accurate counts without Neo4j writes
- [ ] Benchmark queries return relevant results in hybrid mode
- [ ] TypeScript build passes (zero errors)
- [ ] All tests pass (TypeScript + Python)
- [ ] Chinese herb names appear correctly in entity descriptions

## Completion Checklist
- [ ] Code follows discovered patterns (ETL, test, Makefile)
- [ ] Error handling: SQLite connection errors, Neo4j timeouts, missing tables
- [ ] No hardcoded secrets (production config uses env var substitution)
- [ ] Tests follow vitest/pytest patterns
- [ ] Makefile targets documented with `##` comments
- [ ] Graphiti artifacts marked as legacy
- [ ] Self-contained — all context in this plan

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Food name fuzzy matching produces low recall | Medium | Medium | Manual review of unmatched foods; consider USDA FDC ID cross-reference as secondary join key |
| Ollama embedding model OOM on large batches | Low | Medium | Batch size configurable; default 500; reduce to 100 if OOM |
| LightRAG `ainsert_custom_kg()` API changes in newer versions | Low | High | Pin `lightrag-hku` version in requirements.txt |
| Neo4j Railway instance storage limits | Medium | Low | Subsample: cap at 2,376 herbs, 5K compounds, 1K foods for PoC |
| Chinese characters cause encoding issues in Neo4j/embeddings | Low | Medium | UTF-8 throughout; test with known Chinese herb names early |
| LightRAG query quality poor for domain-specific multi-hop | Medium | High | Tune entity descriptions for searchability; use mix mode with reranker |

## Notes
- LightRAG was chosen over Graphiti because: (1) `ainsert_custom_kg()` bypasses LLM for structured data, (2) no episodic memory overhead, (3) 5 query modes with reranker, (4) built-in WebUI/API server, (5) Ollama native support for local embeddings
- The production config includes TCM-specific entity types (`TCM_Formula`, `Meridian`, `Organ`) for future TCM dataset expansion
- The `SUMMARY_LANGUAGE=English` setting ensures all graph summaries are in English even when source data contains Chinese — this is intentional for the LLM agent which operates in English
- The `jina-reranker-v2-base-multilingual` reranker in production config handles Chinese+English queries natively
- OpenNutrition's USDA FDC IDs in the `source` JSON field could serve as a secondary join key if fuzzy name matching proves insufficient — this is a noted fallback but not in initial scope
