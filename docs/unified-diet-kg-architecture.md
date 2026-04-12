# Unified Diet Knowledge Graph — Architecture & Data Flow

## Overview

The unified diet KG aggregates structured phytochemical databases and nutritional datasets into a single semantic knowledge graph, queryable by LLM agents via MCP tools and LightRAG's semantic search API.

## Data Sources — Structured vs Unstructured

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DATA SOURCES BY MODALITY                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  STRUCTURED (direct ainsert_custom_kg — zero LLM cost)             │
│  ═══════════════════════════════════════════════════                │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐   │
│  │ Dr. Duke's DB   │  │ FooDB           │  │ OpenNutrition    │   │
│  │ (CSV → SQLite)  │  │ (CSV → SQLite)  │  │ (TSV → SQLite)   │   │
│  │                 │  │                 │  │                  │   │
│  │ 2,376 herbs     │  │ 4.1M compound   │  │ 326K foods       │   │
│  │ 94K compounds   │  │    → food pairs  │  │ 90 nutrient keys │   │
│  │ 99K herb-cmpd   │  │ 962 unique      │  │ USDA+CNF+AUSNUT  │   │
│  │    links        │  │    foods         │  │    +FRIDA merged │   │
│  └────────┬────────┘  └────────┬────────┘  └────────┬─────────┘   │
│           │                    │                     │              │
│  ┌────────┴────────┐  ┌───────┴─────────┐  ┌───────┴──────────┐   │
│  │ CMAUP v2.0     │  │ CTD             │  │ TTD              │   │
│  │ (TSV → SQLite)  │  │ (CSV.gz→SQLite) │  │ (TSV → SQLite)   │   │
│  │                 │  │                 │  │                  │   │
│  │ 758 targets     │  │ 17.7K chemicals │  │ 3,730 targets    │   │
│  │ 429K cmpd-tgt   │  │ 3.8M chem-      │  │ druggability     │   │
│  │    associations  │  │    disease pairs │  │    status        │   │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘   │
│                                                                     │
│  UNSTRUCTURED (LightRAG LLM extraction — future phase)             │
│  ═══════════════════════════════════════════════════                │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐   │
│  │ PubMed          │  │ Clinical Notes  │  │ TCM Monographs   │   │
│  │ Abstracts       │  │ (future)        │  │ (HERB 2.0,       │   │
│  │                 │  │                 │  │  SymMap text)     │   │
│  │ LLM extracts    │  │ LLM extracts    │  │ Chinese+English  │   │
│  │ entities &      │  │ treatment       │  │ LLM extracts     │   │
│  │ relationships   │  │ outcomes,       │  │ herb properties,  │   │
│  │ from text       │  │ side effects    │  │ formulas         │   │
│  └─────────────────┘  └─────────────────┘  └──────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Ingestion Pipeline

```
┌────────────────────────────────────────────────────────────────────┐
│                      INGESTION PIPELINE                            │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  PHASE 1: SQLite Aggregation (TypeScript/Node.js)                 │
│  ─────────────────────────────────────────────────                 │
│                                                                    │
│  Duke CSV ──┐                                                      │
│  FooDB CSV ─┤──► build-herbal-db.js ──► herbal_botanicals.db      │
│  CMAUP TSV ─┤──► load-cmaup.ts      ──┘  (unified SQLite)        │
│  CTD CSV.gz ┤──► load-ctd.ts         ──┘                          │
│  TTD TSV ───┘──► load-ttd.ts         ──┘                          │
│                                                                    │
│  OpenNutrition ──► build-food-bridge.ts ──► food_nutrition_bridge  │
│    (sibling DB)     (5-strategy fuzzy      (FooDB ↔ ON mapping)   │
│                      name matching)                                │
│                 ──► enrich-nutrition.ts ──► nutrition_100g column  │
│                     (copy JSON per food)    on compound_foods      │
│                                                                    │
│  PHASE 2: LightRAG Knowledge Graph (Python)                       │
│  ─────────────────────────────────────────                         │
│                                                                    │
│  herbal_botanicals.db                                              │
│       │                                                            │
│       ├─► entity_schema.py ──► Entity descriptions (searchable)   │
│       │     6 types: Herb, Compound, Food, Target, Disease,       │
│       │              Symptom                                       │
│       │     5 relationships: CONTAINS_COMPOUND, FOUND_IN_FOOD,    │
│       │              TARGETS_PROTEIN, ASSOC_WITH_DISEASE,         │
│       │              TREATS_SYMPTOM                                │
│       │                                                            │
│       └─► ingest_unified.py ──► LightRAG ainsert_custom_kg()     │
│             │                      │                               │
│             │  STRUCTURED PATH     │  (zero LLM calls)            │
│             │  ════════════════     │                               │
│             │                      ▼                               │
│             │                ┌──────────────┐                      │
│             │                │   LightRAG   │                      │
│             │                │              │                      │
│             │                │ ┌──────────┐ │                      │
│             │                │ │ Neo4j    │ │  Graph storage       │
│             │                │ │ (Railway)│ │  Typed entity labels │
│             │                │ └──────────┘ │                      │
│             │                │ ┌──────────┐ │                      │
│             │                │ │ NanoVDB  │ │  Vector embeddings   │
│             │                │ └──────────┘ │                      │
│             │                │ ┌──────────┐ │                      │
│             │                │ │ JSON KV  │ │  LLM response cache  │
│             │                │ └──────────┘ │                      │
│             │                └──────┬───────┘                      │
│             │                       │                              │
│             │  UNSTRUCTURED PATH    │  (LLM extraction, future)   │
│             │  ══════════════════   │                               │
│             │                       │                              │
│             │  PubMed text ──► ainsert() ──► LLM entity extraction│
│             │  TCM monographs ─┘      (uses ENTITY_TYPES config)  │
│             │                                                      │
└─────────────┴──────────────────────────────────────────────────────┘
```

## Query Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                      QUERY ARCHITECTURE                            │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  LLM Dietitian Agent (Diet Insight Engine SDO)                    │
│       │                                                            │
│       ├──► MCP Tools (14 structured tools)                        │
│       │      │                                                     │
│       │      ├─► search-herbs          ─┐                          │
│       │      ├─► get-herb-compounds     │                          │
│       │      ├─► search-compounds       │  SQLite queries          │
│       │      ├─► get-compound-foods     │  (deterministic, fast)   │
│       │      ├─► search-by-symptom      │                          │
│       │      ├─► find-functional-foods  │                          │
│       │      ├─► get-compound-targets   ├──► HerbalDBAdapter       │
│       │      ├─► get-target-diseases    │      │                   │
│       │      ├─► search-diseases        │      └──► SQLite DB      │
│       │      ├─► get-chemical-diseases  │                          │
│       │      └─► get-health            ─┘                          │
│       │                                                            │
│       ├──► semantic-search MCP tool (bridges to LightRAG)         │
│       │      │                                                     │
│       │      └──► POST /query ──► LightRAG API                    │
│       │           │                                                │
│       │           ├─► mode: local   (entity-focused retrieval)    │
│       │           ├─► mode: global  (community/summary-based)     │
│       │           ├─► mode: hybrid  (local + global combined)     │
│       │           ├─► mode: mix     (KG + vector + reranker)      │
│       │           └─► mode: naive   (direct vector search)        │
│       │                                                            │
│       └──► LightRAG Ollama-compatible endpoint (direct)           │
│              │                                                     │
│              └──► Chat API (query as chat completion)              │
│                                                                    │
│  Access modes:                                                     │
│    MCP:  Claude Desktop / Claude Code / any MCP client            │
│    API:  POST http://localhost:9621/query (FastAPI)                │
│    CLI:  make lightrag-benchmark / python query_benchmark.py      │
│    Chat: Ollama-compatible endpoint (Open WebUI, etc.)            │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Entity-Relationship Schema

```
                     TREATS_SYMPTOM
             ┌──────────────────────────┐
             │                          ▼
         ┌───────┐              ┌──────────┐
         │ Herb  │              │ Symptom  │
         └───┬───┘              └──────────┘
             │
             │ CONTAINS_COMPOUND
             ▼
         ┌──────────┐     TARGETS_PROTEIN     ┌────────┐
         │ Compound ├─────────────────────────►│ Target │
         └────┬─────┘                          └───┬────┘
              │                                    │
              │ FOUND_IN_FOOD          ASSOCIATED_WITH_DISEASE
              ▼                                    ▼
         ┌────────┐                          ┌─────────┐
         │  Food  │                          │ Disease │
         │        │                          └─────────┘
         │ nutrition_100g: {                      
         │   calories, protein,                   
         │   vitamins, minerals,                  
         │   amino acids, fatty acids             
         │   (90 keys from OpenNutrition)         
         │ }                                      
         └────────┘                               
```

## Configuration Profiles

| Profile | LLM | Embedding | Reranker | Neo4j | Use Case |
|---------|-----|-----------|----------|-------|----------|
| **config_local.env** | Ollama qwen3.5:9b | Ollama bge-m3 (1024-dim) | None | Railway test | Dev, test, eval |
| **config_production.env** | GPT-4o-mini | text-embedding-3-large (3072-dim) | Jina multilingual | Prod instance | Production (CN+EN TCM) |

## Food Bridge Matching Strategies

The bridge maps FooDB's 962 generic food names to OpenNutrition's 326K specific food entries:

| Priority | Strategy | Score | Example |
|----------|----------|-------|---------|
| 1 | Exact case-insensitive | 1.0 | "Garlic" → "Garlic" |
| 2 | Everyday type exact | 0.95 | "Rice" → "Rice, Cooked" (type=everyday) |
| 3 | Alternate names match | 0.92 | "Maize" → "Corn" (via alternate_names JSON) |
| 4 | Prefix match | varies | "Chicken" → "Chicken Breast, Boneless..." |
| 5 | Token match | ≤0.9 | "Green tea" → "Organic Green Tea Leaves" |

## Key Design Decisions

1. **LightRAG over Graphiti**: Graphiti is designed for episodic agent memory with temporal provenance. Our data is a static reference graph. LightRAG's `ainsert_custom_kg()` bypasses LLM extraction entirely — 100% accuracy, zero API cost for structured data.

2. **SQLite as aggregation layer**: All 6+ structured datasets normalize into a single SQLite database first. This provides deterministic, fast MCP tool queries. LightRAG indexes the same data for semantic search.

3. **Dual query paths**: MCP tools for structured lookups (fast, deterministic). LightRAG for semantic multi-hop queries (flexible, natural language). Both access the same underlying data.

4. **Name-based food bridge**: FooDB uses its own IDs (FOOD00286), not USDA FDC IDs. OpenNutrition has USDA FDC IDs but no FooDB cross-reference. Fuzzy name matching with alternate_names expansion is the pragmatic join strategy.

5. **Multilingual production config**: TCM datasets contain Chinese herb names. Production uses OpenAI text-embedding-3-large (multilingual) and Jina multilingual reranker for Chinese+English semantic search.
