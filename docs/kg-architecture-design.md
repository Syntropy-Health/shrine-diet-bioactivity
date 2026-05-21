# Knowledge Graph Architecture: Design, Rationale & Optimization

> Design document for the `mcp-herbal-botanicals` phytochemical knowledge graph — covering data aggregation strategy, synthesis pipeline, LLM agent alignment, MCP compatibility, and optimization opportunities.

**Status**: Phase 4 implemented (SQLite + bioactivity-seeded symptoms), Phases 5-8 planned  
**Last updated**: 2026-04-08

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Data Aggregation Strategy](#2-data-aggregation-strategy)
3. [Data Synthesis Pipeline](#3-data-synthesis-pipeline)
4. [Knowledge Graph Schema Design](#4-knowledge-graph-schema-design)
5. [Why Not Graphiti (and What We Took From It)](#5-why-not-graphiti-and-what-we-took-from-it)
6. [LLM Agent Alignment](#6-llm-agent-alignment)
7. [MCP Compatibility Design](#7-mcp-compatibility-design)
8. [Optimization Opportunities](#8-optimization-opportunities)
9. [Migration Path: SQLite → Kuzu](#9-migration-path-sqlite--kuzu)

---

## 1. Design Philosophy

### Core Principle: Composable Data Tool, Not Diagnostic Engine

The `mcp-herbal-botanicals` server is a **data lookup tool** — not a recommendation engine, not a diagnostic system, not a chatbot. It answers structured queries about relationships between herbs, compounds, foods, and symptoms, then returns citation-backed data for the LLM agent to reason over.

This distinction is critical:

```
❌ WRONG: "You should take ashwagandha for stress"
   (Recommendation — the MCP server never does this)

✅ RIGHT: "Ashwagandha contains withanolide A (adaptogenic). 
           Foods sharing this compound: Winter Cherry fruit."
   (Data — the LLM agent decides how to use it)
```

### Design Decisions

| Decision | Choice | Alternative Rejected | Rationale |
|----------|--------|---------------------|-----------|
| **Local-first** | Embedded SQLite → Kuzu | Cloud graph DB (Neo4j Aura) | Zero latency, offline-capable, no API keys, <200ms per call |
| **Pre-built** | ETL at build time | Runtime API queries | Deterministic, reproducible, cacheable |
| **Composable** | Separate MCP server | Single nutrition-only MCP | Clean separation of concerns; different data models |
| **Schema-first** | Zod validation on all inputs | Freeform JSON | Prevents hallucinated parameters from LLM agents |
| **Read-only** | `readOnlyHint: true` on all tools | Read-write | Data is reference material, not user state |

---

## 2. Data Aggregation Strategy

### Multi-Source Layering

The KG aggregates data from heterogeneous sources, each contributing a specific relationship layer:

```
Layer 1 (BACKBONE): Dr. Duke's Phytochemical DB
├── Herb ──[CONTAINS {ppm}]──► Compound
├── Compound ──[HAS_BIOACTIVITY]──► Bioactivity tag
└── 2,376 herbs × 94,512 compounds = 99,280 links

Layer 2 (FOOD BRIDGE): FooDB
├── Compound ──[FOUND_IN {mg/100g}]──► Food
└── 4,149,541 compound-food pairs

Layer 3 (SYMPTOM MAP): Duke Bioactivities → Structured Symptoms
├── Symptom ──[TREATED_BY]──► Herb (via compound bioactivities)
├── 53 bioactivity tags → 47 structured symptoms
└── 41,823 herb-symptom links

Layer 4 (FOOD CLASSIFICATION): Curated + CMAUP (planned)
├── Herb ──[IS_FOOD_PLANT]──► (flag)
├── Herb ──[IS_EDIBLE]──► (flag)
└── 312 food plants, 354 total edible

Layer 5 (TARGETS): CMAUP (planned)
├── Compound ──[TARGETS {IC50}]──► Protein Target
├── Target ──[ASSOCIATED_WITH]──► Disease
└── Tables created, awaiting data load

Layer 6 (DENSITY): BATMAN-TCM (planned)
├── Compound ──[PREDICTED_TARGET {score}]──► Protein Target
└── 2.3M predicted interactions
```

### Cross-Source Reconciliation

The fundamental challenge of multi-source KG construction is **entity resolution** — the same compound appears under different names across sources. Our strategy:

```
Source A (Duke):    "ASCORBIC-ACID"
Source B (FooDB):   "Ascorbic acid"
Source C (SymMap):  "L-ascorbic acid"
Source D (CMAUP):   "Vitamin C"

                    ↓ normalizeCompoundName()
                    
All → "ascorbicacid" (normalized ID)
```

**`normalizeCompoundName(name)`**: Strips to lowercase alphanumeric. This is the canonical join key across all sources.

```typescript
export function normalizeCompoundName(name: string): string {
  return name.toLowerCase().trim().replace(/[^a-z0-9]/g, '');
}
```

**Limitations**:
- Cannot resolve true synonyms: "Vitamin C" → "vitaminc" ≠ "ascorbicacid"
- Mitigation: `compound_name_map` tracks provenance; PubChem CID will resolve ambiguous cases in Phase 5

**`compound_name_map` table** (cross-source audit trail):

```sql
-- "curcumin" appears in Duke AND FooDB → same normalized ID
SELECT * FROM compound_name_map WHERE normalized_name = 'curcumin';
-- normalized_name | source | original_name | compound_id
-- curcumin         | duke   | CURCUMIN      | curcumin
-- curcumin         | foodb  | Curcumin      | curcumin
```

---

## 3. Data Synthesis Pipeline

### ETL Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Source CSVs  │────►│  Parse +     │────►│  SQLite DB   │
│  (data/)      │     │  Normalize   │     │  (data_local/│
│              │     │  (scripts/)  │     │   herbal_    │
│ duke.zip     │     │              │     │   botanicals │
│ foodb.tar.gz │     │ readCsvFile()│     │   .db)       │
│ cmaup/*.csv  │     │ normalize()  │     │              │
│ symmap/*.csv │     │ batch txn    │     │  914 MB      │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Pipeline Stages

**Stage 1: Download** (`scripts/download-sources.ts`)
- HTTP GET → `data/` directory
- Skip if file exists + size check
- Progress reporting for large files (FooDB: 952 MB)

**Stage 2: Decompress** (`scripts/decompress-datasets.ts`)
- ZIP extraction (yauzl) for Duke
- tar.gz extraction (system tar) for FooDB
- Output: `data_local_temp/{source}/` CSV files

**Stage 3: Build** (`scripts/build-herbal-db.ts`)
- Creates fresh SQLite DB
- Loads sources sequentially: Duke herbs → names → parts → compounds → herb-compounds → bioactivities → FooDB
- Compound name normalization as join key
- Streaming for large CSVs (FooDB Content.csv: 5M+ rows)
- Batch transactions: 10,000 rows per batch for throughput

**Stage 4: Migrate** (`scripts/migrate-kg-expansion.ts`)
- Incremental: adds tables to existing DB without rebuild
- Idempotent: all operations use `IF NOT EXISTS` / `OR IGNORE`
- Seeds symptoms from bioactivity tags
- Flags food plants from curated list

### Streaming Pattern for Large CSVs

```typescript
// 5M+ rows — cannot load into memory
const rl = readline.createInterface({
  input: fs.createReadStream(contentCsvPath, 'utf8'),
  crlfDelay: Infinity,
});

let batch: Array<() => void> = [];
const BATCH_SIZE = 10_000;

for await (const line of rl) {
  batch.push(() => insertStmt.run(parsed));
  if (batch.length >= BATCH_SIZE) {
    db.transaction(() => { for (const op of batch) op(); })();
    batch = [];
  }
}
```

This pattern:
- Uses constant memory regardless of file size
- Batches inserts in transactions for SQLite throughput (unbatched: ~100 rows/sec → batched: ~50,000 rows/sec)
- Reports progress every 500K lines

### Bioactivity → Symptom Synthesis

The most novel synthesis step maps Duke's unstructured bioactivity tags to structured symptoms:

```
Duke AGGREGAC.csv:
  CHEM=CURCUMIN, ACTIVITY=Antiinflammatory
  CHEM=CURCUMIN, ACTIVITY=Antioxidant
  CHEM=CURCUMIN, ACTIVITY=Anticancer

                    ↓ BIOACTIVITY_SYMPTOM_MAP

Structured symptoms:
  "Antiinflammatory" → Symptom("Inflammation", type="modern")
  "Antioxidant"      → Symptom("Oxidative stress", type="bioactivity")
  "Anticancer"       → Symptom("Cancer", type="modern")

                    ↓ herb_compounds JOIN

herb_symptoms:
  Herb("Turmeric") ──[TREATS]──► Symptom("Inflammation")
  Herb("Turmeric") ──[TREATS]──► Symptom("Oxidative stress")
  Herb("Turmeric") ──[TREATS]──► Symptom("Cancer")
```

53 bioactivity tags are mapped to 47 structured symptoms (some map to the same symptom, e.g., "Sedative" and "Hypnotic" both → "Insomnia"). This produces 41,823 herb-symptom links.

---

## 4. Knowledge Graph Schema Design

### Current State (Phase 4 — SQLite)

```sql
-- 10 tables, 19 indexes

-- NODES (entity tables)
herbs           (2,376 rows)   -- Plants with taxonomy
compounds       (94,512 rows)  -- Chemicals with bioactivities
symptoms        (47 rows)      -- Health concerns (from Duke bioactivities)
targets         (0 rows)       -- Protein targets (awaiting CMAUP)

-- EDGES (relationship tables)
herb_compounds  (99,280 rows)  -- Herb → Compound (with concentration)
compound_foods  (4,149,541)    -- Compound → Food (with content amount)
herb_symptoms   (41,823 rows)  -- Herb → Symptom (derived from bioactivities)
compound_targets (0 rows)      -- Compound → Target (awaiting CMAUP)
target_diseases  (0 rows)      -- Target → Disease (awaiting CMAUP)

-- METADATA
compound_name_map (99,430)     -- Cross-source compound name reconciliation
```

### Property Graph Mapping

Every SQL table maps directly to a property graph:

```
Tables → Nodes:
  herbs      → (:Herb {id, scientific_name, common_name, is_food_plant})
  compounds  → (:Compound {id, name, cas_number, compound_class})
  symptoms   → (:Symptom {id, name, symptom_type})
  targets    → (:Target {id, name, uniprot_id, gene_symbol})

Tables → Edges:
  herb_compounds  → (:Herb)-[:CONTAINS {plant_part, concentration_ppm}]->(:Compound)
  compound_foods  → (:Compound)-[:FOUND_IN {content_value, content_unit}]->(:Food)
  herb_symptoms   → (:Herb)-[:TREATS {evidence_type}]->(:Symptom)
  compound_targets → (:Compound)-[:TARGETS {activity_value}]->(:Target)
  target_diseases  → (:Target)-[:ASSOCIATED_WITH {evidence_layer}]->(:Disease)
```

### Why This Schema

1. **Hub-and-spoke around Compound**: Compounds are the central node connecting herbs, foods, symptoms, and targets. This reflects phytochemistry — compounds are the mechanism of action.

2. **Provenance on every edge**: The `source` column on all relationship tables tracks which database contributed each relationship. Enables multi-source citation and confidence scoring.

3. **Quantitative edges**: Concentrations (ppm) on herb→compound and content amounts (mg/100g) on compound→food enable ranking and dosage reasoning by the agent.

4. **Food plant flags on herbs**: Rather than creating a separate `food_plants` table, `is_food_plant` and `is_edible` are columns on `herbs`. This avoids a JOIN for the most common query pattern ("is this herb also a food?").

---

## 5. Why Not Graphiti (and What We Took From It)

### Graphiti's Architecture

Graphiti (github.com/getzep/graphiti, 24.6K stars) is a temporal knowledge graph framework for AI agent memory:

| Feature | Graphiti | mcp-herbal-botanicals |
|---------|----------|----------------------|
| **Purpose** | Agent memory (evolving facts) | Domain ontology (static facts) |
| **Temporal** | Yes — facts have validity windows | No — scientific data doesn't expire per-session |
| **LLM required** | Yes — for entity extraction, contradiction resolution | No — data is pre-structured |
| **Runtime** | Python + Neo4j/FalkorDB server | TypeScript + embedded SQLite/Kuzu |
| **Updates** | Per-conversation incremental | Batch ETL at build time |
| **Query** | Hybrid (semantic + keyword + graph) | Structured (SQL/Cypher + FTS) |

### Why We Rejected Graphiti

1. **Wrong problem domain**: Graphiti tracks what a *user* said and how facts evolve over time. Our data is a *reference ontology* — "ashwagandha contains withanolide A" is a scientific fact, not a temporal user preference.

2. **Mandatory LLM dependency**: Graphiti uses LLM calls for entity extraction, relationship creation, and contradiction resolution. Our data is already structured — adding LLM calls would be:
   - Slow (100ms+ per entity)
   - Expensive (API costs per compound)
   - Non-deterministic (different runs produce different graphs)

3. **Server dependency**: Graphiti requires Neo4j or FalkorDB running as a server. Our architecture is local-first, zero-dependency — the DB is a single file shipped with the MCP server.

4. **Python runtime**: Graphiti is Python-only. This architecture document predates the move to a Python `kg-mcp` gateway (`mcp/`) plus a TypeScript thin-adapter (`shrine-diet-bioactivity/src/`); the original "TypeScript-everywhere" rationale no longer applies, but the rest of the comparison still does.

### What We Took From Graphiti

Despite rejecting the framework, several concepts inspired our design:

1. **Hybrid retrieval**: Graphiti combines semantic search + keyword search + graph traversal. We implement this as:
   - Keyword: `LIKE` queries on names/synonyms
   - Structured: SQL JOINs for relationship traversal
   - Planned: semantic embeddings for fuzzy symptom matching (Phase 6)

2. **Node/Edge typing**: Graphiti's `EntityNode` and `EntityEdge` with typed relationships maps directly to our schema design (herbs, compounds as nodes; herb_compounds, compound_foods as typed edges).

3. **Kuzu as backend**: Graphiti added Kuzu support as an embedded alternative to Neo4j. We chose Kuzu for the same reason — embedded, MIT-licensed, Cypher-compatible, no server dependency.

4. **Episode provenance**: Graphiti tracks which "episode" (conversation) contributed each fact. Our `source` column on every edge table serves the same purpose — tracking which database contributed each relationship.

5. **Community nodes**: Graphiti's `CommunityNode` aggregates related entities. Our `search-by-symptom` tool returns an aggregated view (symptoms + herbs + compounds + foods) that functions similarly.

---

## 6. LLM Agent Alignment

### Designed for Agent Consumption

Every design decision considers how an LLM agent will use the returned data:

**1. Structured responses (not text)**
```json
{
  "symptoms_matched": [{"name": "Inflammation", "type": "modern"}],
  "herbs": [{"common_name": "Turmeric", "is_food_plant": true, "compound_count": 87}],
  "functional_foods": [{"food_name": "Ginger", "shared_compounds": 46}]
}
```
Agents can directly reference specific fields: "Turmeric is a food plant with 87 active compounds."

**2. Multi-hop queries pre-computed**
Instead of requiring 3 sequential tool calls (search symptom → get herbs → get foods), `search-by-symptom` traverses the entire path in one call:
```
symptom → herb_symptoms → herbs → herb_compounds → compounds → compound_foods → foods
```

**3. Overlap scores for ranking**
`get-herb-food-overlap` returns `overlap_score` (0-1) so the agent can say "Ginger shares 46% of turmeric's compounds" without doing math.

**4. Food plant flags for dietary advice**
The `is_food_plant` boolean lets the agent distinguish:
- "Turmeric (food plant) — add to cooking"
- "Ashwagandha (edible, not food) — supplement form"

**5. Tool descriptions as agent instructions**
Each MCP tool description includes:
- When to use it
- Example queries
- What parameters mean
- What the response contains

This replaces in-context learning — the agent knows which tool to call from the description alone.

### Agent Query Patterns

The tool set is designed for these natural agent workflows:

| User Says | Agent Workflow | Tools Called |
|-----------|---------------|-------------|
| "What is ashwagandha?" | Lookup → Profile | search-herbs → get-herb-profile |
| "What foods have same benefits?" | Bridge query | get-herb-food-overlap |
| "I'm tired easily" | Symptom → solutions | search-by-symptom("fatigue") |
| "What has anti-inflammatory compounds?" | Bioactivity search | search-by-bioactivity |
| "Is turmeric a functional food?" | Food plant search | find-functional-foods |
| "What foods contain curcumin?" | Compound → food | search-compounds → get-compound-foods |
| "Why does curcumin help?" | Mechanism query | get-compound-targets |

---

## 7. MCP Compatibility Design

### Protocol Alignment

The server implements MCP SDK conventions exactly:

```typescript
// 5-argument tool registration pattern
this.server.tool(
  'tool-name',                    // Snake-case name
  'Description with examples',    // Agent-readable description
  ZodSchema.shape,                // Zod schema for input validation
  { readOnlyHint: true },         // MCP options
  async (args) => {               // Handler
    const result = this.db.method(args);
    return {
      content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      structuredContent: { result },
    };
  }
);
```

### Composability across the data stack

The kg-mcp gateway combines herb/compound/symptom data with vendored
OpenNutrition macros via a single tool surface:

```
Agent has: kg-mcp gateway (10 tools over the unified KG)
           — herbs (2,376), compounds (94K), symptoms, targets, diseases
           — OpenNutrition macros (326K foods, vendored as fixture)

User: "I need more iron in my diet and want natural options"

Agent:
  1. kg_compound_to_symptoms("iron") / kg_symptom_to_compounds("fatigue")
     → herbs rich in iron
  2. kg_compound_to_diseases / nutrition lookup → foods containing iron
  3. Macro breakdown returned inline via the vendored OpenNutrition data

  Response: "Spinach has 2.7mg iron per 100g (36% DV), 23 kcal.
             Nettle tea is traditionally used for iron supplementation.
             Other iron-rich foods: lentils, beef liver, pumpkin seeds."
```

Earlier drafts of this document described a separate `mcp-opennutrition`
submodule consumed alongside this server; that submodule was removed in
2026-05 and OpenNutrition is now vendored as a fixture inside this repo.

### Transport

Stdio transport only (no HTTP). This is intentional:
- MCP clients (Claude, Claude Code) connect via stdio
- No authentication needed (local process)
- No CORS, no ports, no firewall issues

---

## 8. Optimization Opportunities

### Performance

| Issue | Current State | Optimization | Impact | Priority |
|-------|--------------|-------------|--------|----------|
| **N+1 in `findFunctionalFoods`** | 1 query per herb (up to 20) | Replace with CTE joining all herbs in one query | ~10x faster for large pageSize | MEDIUM |
| **N+1 in `searchByBioactivity`** | 1 herb lookup per compound per page | Replace with single JOIN using compound IDs as CTE | ~10x faster | MEDIUM |
| **Unbounded GROUP_CONCAT** | Concatenates all compound names, then slices | Use `GROUP_CONCAT(... LIMIT 10)` (SQLite 3.47+) or subquery | Reduces string allocation | LOW |
| **Full table scan on bioactivities** | `WHERE bioactivities LIKE ?` on JSON column | Use `herb_symptoms` JOIN instead (structured data) | Eliminates scan of 94K rows | HIGH |
| **No FTS index** | LIKE queries on names | Add FTS5 virtual table for herb/compound/symptom names | Fuzzy matching, tokenized search | MEDIUM |

### Suggested CTE for `findFunctionalFoods`:

```sql
WITH food_herbs AS (
  SELECT h.id, h.common_name, h.scientific_name
  FROM herbs h
  WHERE (h.is_food_plant = 1 OR h.is_edible = 1)
    AND (h.common_name LIKE ? OR h.scientific_name LIKE ?)
  ORDER BY (SELECT COUNT(*) FROM herb_compounds WHERE herb_id = h.id) DESC
  LIMIT ? OFFSET ?
),
food_overlaps AS (
  SELECT fh.id as herb_id, fh.common_name as herb_name, fh.scientific_name,
    cf.food_name, cf.food_group,
    COUNT(DISTINCT cf.compound_id) as compound_count,
    GROUP_CONCAT(DISTINCT c.name) as compound_names_csv,
    ROW_NUMBER() OVER (PARTITION BY fh.id ORDER BY COUNT(DISTINCT cf.compound_id) DESC) as rn
  FROM food_herbs fh
  JOIN herb_compounds hc ON fh.id = hc.herb_id
  JOIN compound_foods cf ON hc.compound_id = cf.compound_id
  JOIN compounds c ON cf.compound_id = c.id
  GROUP BY fh.id, cf.food_name
)
SELECT * FROM food_overlaps WHERE rn <= 3;
```

### Data Quality

| Issue | Current State | Optimization | Priority |
|-------|--------------|-------------|----------|
| **Symptom coverage** | 47 symptoms from 53 bioactivity tags | Load SymMap v2 for 2,678 structured symptoms | HIGH |
| **Food plant classification** | 312 from curated list | Load CMAUP for 1,737 food/edible plants | HIGH |
| **Target data** | Empty (0 rows) | Load CMAUP compound-target data (428K associations) | HIGH |
| **Compound disambiguation** | String normalization only | Add PubChem CID resolution for synonyms | MEDIUM |
| **Cross-source validation** | No automated audit | Add script to count compounds confirmed in 3+ sources | LOW |

### Architecture

| Opportunity | Description | Effort | Impact |
|-------------|-------------|--------|--------|
| **Kuzu migration** | Replace SQLite with embedded graph DB for native Cypher queries | HIGH | Eliminates complex JOINs, enables arbitrary traversals |
| **Semantic search** | Add vector embeddings for symptom/herb names | MEDIUM | Fuzzy matching: "can't sleep" → "Insomnia" |
| **Materialized views** | Pre-compute herb→symptom→food bridges | LOW | Eliminates multi-hop JOINs at query time |
| **Prepared statement cache** | Pool prepared statements across calls | LOW | ~20% reduction in query overhead |
| **Read-only connection pool** | Multiple readonly connections for concurrent queries | LOW | Better throughput under load |

### MCP Tool Design

| Opportunity | Description | Priority |
|-------------|-------------|----------|
| **`traverse-path`** | Expose arbitrary graph traversal (Cypher-like) | Phase 6 |
| **`compare-herbs`** | Compare compound profiles of 2+ herbs | LOW |
| **`suggest-foods-for-compounds`** | Given compound list, find optimal food combinations | MEDIUM |
| **Streaming responses** | Return partial results as they compute for large queries | LOW |
| **Response caching** | Cache popular queries (ashwagandha, turmeric) in-memory | LOW |

---

## 9. Migration Path: SQLite → Kuzu

### Why Migrate

SQLite handles the current schema well, but as relationships grow (BATMAN-TCM: 2.3M predicted interactions, SymMap: 6 relationship types), multi-hop queries become unwieldy:

**SQLite (current)**:
```sql
-- "Find foods that help with inflammation"
-- Requires: symptom → herb_symptom → herb → herb_compound → compound → compound_food
SELECT cf.food_name, COUNT(DISTINCT cf.compound_id) as shared
FROM symptoms s
JOIN herb_symptoms hs ON s.id = hs.symptom_id
JOIN herb_compounds hc ON hs.herb_id = hc.herb_id
JOIN compound_foods cf ON hc.compound_id = cf.compound_id
WHERE s.name LIKE '%inflammation%'
GROUP BY cf.food_name
ORDER BY shared DESC;
-- 4 JOINs, hard to optimize, hard to extend
```

**Kuzu (planned)**:
```cypher
MATCH (s:Symptom)-[:TREATED_BY]->(h:Herb)-[:CONTAINS]->(c:Compound)-[:FOUND_IN]->(f:Food)
WHERE s.name =~ '.*inflammation.*'
RETURN f.name, COUNT(DISTINCT c) as shared
ORDER BY shared DESC;
-- Natural graph traversal, easily extended with new edge types
```

### Migration Strategy

1. **Dual adapter**: Create `KuzuDBAdapter` implementing same interface as `HerbalDBAdapter`
2. **Feature flag**: Environment variable `HERBAL_DB_BACKEND=kuzu|sqlite`
3. **Data migration**: ETL script loads same source data into Kuzu property graph
4. **Test parity**: Run existing test suite against both adapters
5. **Benchmarks**: Compare latency for each tool at same data scale
6. **Cutover**: Default to Kuzu when benchmarks confirm <500ms for 3-hop queries

### Kuzu Fit

| Requirement | Kuzu Support |
|-------------|-------------|
| Embedded (no server) | Yes — file-based, like SQLite |
| Cypher queries | Yes — subset, sufficient for our traversals |
| Node.js bindings | Yes — `kuzu` npm package |
| MIT license | Yes |
| Property graph | Yes — typed nodes and edges with properties |
| Transaction support | Yes — ACID transactions |
| Import from CSV | Yes — `COPY FROM` for bulk loading |

---

*Document generated: 2026-04-08*
*Source PRD: `.claude/PRPs/prds/mcp-herbal-botanicals.prd.md`*
*Implementation report: `.claude/PRPs/reports/mcp-herbal-botanicals-phase4-kg-expansion-report.md`*
