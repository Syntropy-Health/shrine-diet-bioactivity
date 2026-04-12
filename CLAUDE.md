# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Diet Data builds a **unified diet knowledge graph** spanning macronutrients, foods, herbs, phytochemical compounds, molecular targets, and diseases. It aggregates 7+ authoritative datasets into a semantic KG powered by LightRAG (Neo4j graph + vector embeddings), queryable by LLM agents via 15 MCP tools and a REST/Ollama-compatible API.

Data foundation for the [Diet Insight Engine](https://github.com/Syntropy-Health/diet-insight-engine) Symptom-Diet Optimizer (SDO). Part of the [Syntropy Health](https://github.com/Syntropy-Health) ecosystem.

## Repository Layout

- `mcp-herbal-botanicals/` — **Primary MCP server**: 15 tools (14 SQLite + 1 semantic search via LightRAG)
  - `data_local/herbal_botanicals.db` — Unified SQLite (herbs, compounds, foods, targets, diseases, symptoms)
  - `lightrag/` — LightRAG config, ingestion scripts, benchmarks (Python)
  - `graphiti/` — Legacy Graphiti PoC (superseded by LightRAG)
- `mcp-opennutrition/` — Git submodule: OpenNutrition MCP server (326k+ foods, 90 nutrient keys)
- `lightrag/` — Git submodule: LightRAG framework (semantic KG + RAG)
- `usda-fdc-data/` — Git submodule: USDA FoodData Central (Python, 900k+ foods)
- `scripts/` — Setup and data automation (bash + Python)
- `docs/` — Architecture docs, KG comparison, data schematics
- `output/` — Generated data directory (gitignored)
- `.claude/PRPs/` — Plans, PRDs, and implementation reports

## Build & Setup Commands

```bash
# Initialize submodules
git submodule update --init --recursive

# Herbal-botanicals: full pipeline (download → build → bridge → enrich)
cd mcp-herbal-botanicals && make setup

# Or step-by-step:
cd mcp-herbal-botanicals
make download          # Duke + FooDB (~960 MB)
make build             # Build SQLite from CSVs
make migrate           # KG expansion (symptoms, targets)
make food-bridge       # Bridge FooDB foods ↔ OpenNutrition
make enrich-nutrition  # Add nutrition_100g to compound_foods

# LightRAG KG ingestion
make lightrag-setup       # Install Python deps
make lightrag-dry-run     # Preview entity/relationship counts
make lightrag-ingest-local  # Ingest into Neo4j (Ollama embeddings)
make lightrag-benchmark   # Run 10 benchmark queries

# Tests
cd mcp-herbal-botanicals && npm test      # vitest (45 tests)
cd mcp-herbal-botanicals/lightrag && python -m pytest test_ingest.py  # Python tests

# OpenNutrition MCP server
cd mcp-opennutrition && npm install && npm run build && npm test
```

## Architecture

### Unified Data Flow

```
STRUCTURED DATA (zero LLM cost):
  Duke CSV (2.4K herbs, 94K compounds) ─┐
  FooDB CSV (4.1M compound-food pairs) ──┤──► herbal_botanicals.db
  CMAUP TSV (758 targets, 429K links) ──┤      (unified SQLite)
  CTD CSV.gz (17.7K chemicals) ──────────┤          │
  TTD TSV (3.7K targets) ───────────────┘          │
                                                    ├──► LightRAG ainsert_custom_kg()
  OpenNutrition (326K foods) ──► food bridge ──────┘      │
    (nutrition_100g enrichment)                            ▼
                                               ┌──────────────────┐
                                               │ LightRAG (Neo4j) │
                                               │ Semantic KG      │
                                               │ 5 query modes    │
                                               └────────┬─────────┘
                                                        │
  LLM Agent ──► MCP Tools (15) ──► SQLite (structured) │
       │                                                │
       └──► semantic-search tool ──► LightRAG API ──────┘
       └──► REST API (POST /query) ─────────────────────┘
       └──► Ollama-compat chat endpoint ────────────────┘
```

### Key Integration Points

- **MCP Protocol**: herbal-botanicals exposes 15 tools (14 SQLite + 1 semantic-search via LightRAG). OpenNutrition exposes 8 tools. Both use `@modelcontextprotocol/sdk` with Zod schemas.
- **SQLite**: Unified `herbal_botanicals.db` with 12 tables (herbs, compounds, compound_foods, targets, diseases, symptoms, food_nutrition_bridge). OpenNutrition in sibling `opennutrition_foods.db`.
- **LightRAG**: Semantic KG indexed in Neo4j with 6 entity types (Herb, Compound, Food, Target, Disease, Symptom) and 5 relationship types. Queries via FastAPI REST API or Ollama-compatible chat endpoint.
- **Food Bridge**: FooDB's 962 foods fuzzy-matched to OpenNutrition's 326K foods via 5-strategy name matching (exact, everyday, alternate_names, prefix, token), enriching compound_foods with 90-nutrient profiles.
- **Dual Config**: `config_local.env` (Ollama, zero cost) for dev/test. `config_production.env` (OpenAI + Jina multilingual reranker) for production with Chinese+English TCM support.

### Technology Stack

| Component | Stack |
|---|---|
| MCP Server (herbal) | TypeScript, Node.js 18+, better-sqlite3, Zod, vitest |
| MCP Server (nutrition) | TypeScript, Node.js 18+, better-sqlite3, Zod, vitest |
| Semantic KG | Python 3.10+, LightRAG, Neo4j 5.26+ |
| Embeddings (local) | Ollama, bge-m3 (1024-dim) |
| Embeddings (prod) | OpenAI text-embedding-3-large (3072-dim) |
| Graph DB | Neo4j (Railway hosted) |
| NIH DSLD Client | Python, requests |

## Submodules

After cloning, always run: `git submodule update --init --recursive`

| Submodule | Purpose | Upstream |
|---|---|---|
| `usda-fdc-data` | USDA FoodData Central raw data | https://github.com/mkayeterry/usda-fdc-data |
| `mcp-opennutrition` | OpenNutrition MCP server (326K foods) | https://github.com/deadletterq/mcp-opennutrition |
| `lightrag` | LightRAG semantic KG framework | https://github.com/HKUDS/LightRAG |

## Active Branches & Features

- `main` — Stable branch with initial data sources
- `feature/mcp-herbal-botanicals` — Unified diet KG: herbal-botanicals + OpenNutrition + LightRAG
- `.claude/PRPs/plans/` — Feature plans and implementation reports

## Data Audit Notes

OpenNutrition DB (326,759 foods): Calories 95.5% coverage, protein 74.7%, carbs 90.2%, fat 69.5%, fiber 53.8%. A `data_completeness` score should flag foods with missing core macros. See `docs/data-audit-results.md`.

## Conventions

- Scripts use descriptive docstring headers with usage examples (see `scripts/query-nih-dsld.py`)
- No API keys required for core data sources; only `OPENAI_API_KEY` optional for cloud embeddings
- Python scripts handle missing dependencies gracefully with try/except ImportError
- MCP tools use Zod schemas for input validation
- `output/` directory is gitignored — all generated data lives there
