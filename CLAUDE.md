# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Diet Data aggregates three authoritative open-source nutrition databases (USDA FoodData Central, OpenNutrition MCP, NIH DSLD) for RAG-powered health applications. It is the data foundation for the [Diet Insight Engine](https://github.com/Syntropy-Health/diet-insight-engine) Symptom-Diet Optimizer (SDO). Part of the [Syntropy Health](https://github.com/Syntropy-Health) ecosystem.

## Repository Layout

- `usda-fdc-data/` — Git submodule: USDA FoodData Central (Python, 900k+ foods)
- `mcp-opennutrition/` — Git submodule: OpenNutrition MCP server (TypeScript/Node.js, 326k+ foods → SQLite)
- `scripts/` — Setup and data automation (bash + Python)
- `output/` — Generated data directory (gitignored)
- `docs/` — Audit results, analysis
- `PRD.md` — Product requirements for RAG-powered nutrition intelligence
- `AGENT.md` — NutritionDataAgent specification (data models, query interfaces, RAG pipeline)
- `DATA_SOURCES.md` — Data source evaluation and selection rationale
- `.claude/PRPs/plans/` — Existing feature plans (developer-integration-guide)

## Build & Setup Commands

```bash
# Full setup (clones submodules, installs deps, builds)
./scripts/setup.sh

# Initialize submodules if already cloned
git submodule update --init --recursive

# USDA data: download and process → output/usda/usda_food_nutrition_data.csv
./scripts/fetch-usda.sh

# OpenNutrition MCP server: build TypeScript → SQLite DB
cd mcp-opennutrition && npm install && npm run build

# MCP server tests
cd mcp-opennutrition && npm test          # vitest run

# NIH DSLD queries (external API, no key required)
python scripts/query-nih-dsld.py --ingredient "vitamin d"

# Generate RAG embeddings (requires OPENAI_API_KEY or --local flag)
python scripts/generate-embeddings.py --input output/usda/usda_food_nutrition_data.csv
python scripts/generate-embeddings.py --input output/usda/usda_food_nutrition_data.csv --local
```

## Architecture

### Data Flow

```
USDA CSV (900k+ foods) ──► generate-embeddings.py ──► Vector Store (ChromaDB/Pinecone)
                                                            │
OpenNutrition (326k foods) ──► MCP Server (Node.js) ──────►│──► NutritionDataAgent
                                                            │       ├── USDADataLoader
NIH DSLD (100k+ supplements) ──► REST API ────────────────►│       ├── MCPFoodClient
                                                                    └── DSLDClient
                                                                         │
                                                               Unified Query Interface
                                                                         │
                                                         Diet Insight Engine (SDO)
```

### Key Integration Points

- **MCP Protocol**: OpenNutrition exposes `search_foods`, `get_food`, `barcode_lookup`, `browse_foods` tools via `@modelcontextprotocol/sdk`. MCP tools registered with Zod schemas in `mcp-opennutrition/src/index.ts`.
- **SQLite**: OpenNutrition data stored in `mcp-opennutrition/build/opennutrition.db` with `nutrition_100g` JSON column containing 90 nutrient keys.
- **RAG Pipeline**: USDA data → chunk → embed (OpenAI or sentence-transformers) → vector store → query at inference time.
- **NIH DSLD**: External REST API at `https://api.ods.od.nih.gov/dsld/v9` — used as validation/reference layer, not primary RAG source.

### Technology Stack

| Component | Stack |
|---|---|
| MCP Server | TypeScript, Node.js 18+, better-sqlite3, Zod, vitest |
| USDA Processing | Python 3.8+ |
| Embeddings | Python, OpenAI API or sentence-transformers |
| NIH DSLD Client | Python, requests |
| Data Format | CSV (USDA), SQLite (OpenNutrition), JSON REST (NIH) |

## Submodules

Both data sources are git submodules. After cloning, always run:
```bash
git submodule update --init --recursive
```

| Submodule | Upstream |
|---|---|
| `usda-fdc-data` | https://github.com/mkayeterry/usda-fdc-data |
| `mcp-opennutrition` | https://github.com/deadletterq/mcp-opennutrition |

## Active Branches & Features

- `main` — Stable branch with initial data sources
- `feature/prd-01-macro-calculation` — Config-driven macro calculation for OpenNutrition
- `.claude/PRPs/plans/developer-integration-guide.plan.md` — Planned: Developer docs for MCP/LangGraph/Python integration pathways

## Data Audit Notes

OpenNutrition DB (326,759 foods): Calories 95.5% coverage, protein 74.7%, carbs 90.2%, fat 69.5%, fiber 53.8%. A `data_completeness` score should flag foods with missing core macros. See `docs/data-audit-results.md`.

## Conventions

- Scripts use descriptive docstring headers with usage examples (see `scripts/query-nih-dsld.py`)
- No API keys required for core data sources; only `OPENAI_API_KEY` optional for cloud embeddings
- Python scripts handle missing dependencies gracefully with try/except ImportError
- MCP tools use Zod schemas for input validation
- `output/` directory is gitignored — all generated data lives there
