# Open Diet Data

Open-source nutrition and dietary supplement data sources for RAG-powered health applications.

## 📚 Documentation index

**Start here:** [`docs/INDEX.md`](docs/INDEX.md) — single source of navigation for the project, grouped by audience (newcomer / architect / data-engineer / researcher / clinical / ops).

**KG completeness audit:** [`docs/KG_COMPLETENESS_AUDIT.md`](docs/KG_COMPLETENESS_AUDIT.md) — quantitative gap analysis vs the two priority use cases (Symptom→food, Diet→effects), with concrete TDD specs for the top three remediations.

## Overview

This repository aggregates authoritative open-source nutrition databases for use in AI-powered dietary recommendation systems. It serves as the data foundation for the [Diet Insight Engine](https://github.com/Syntropy-Health/diet-insight-engine) and related Syntropy Health applications.

## Data Sources

| Source | Description | Items | API Key Required |
| --- | --- | --- | --- |
| **USDA FoodData Central** | Gold-standard US nutrition database | 900k+ foods | ❌ No |
| **OpenNutrition MCP** | MCP server for LLM food queries | 300k+ foods | ❌ No |
| **NIH DSLD** | Dietary supplement label database | 100k+ products | ❌ No |
| **ChEMBL 36 + UniChem + PubChem** | Compound-identity bridge → drug-target bioactivity evidence (Phase 1 — see [ADR 0007](docs/adr/0007-compound-identity-bridge.md)) | ~25k active compounds; measured IC50/Ki/EC50 | ❌ No |

## Repository Structure

```text
open-diet-data/
├── README.md           # This file
├── PRD.md              # Product requirements document
├── AGENT.md            # Data agent specification
├── DATA_SOURCES.md     # Exploration references
├── scripts/            # Automation scripts
│   ├── setup.sh        # Complete setup script
│   ├── fetch-usda.sh   # USDA data download
│   ├── build-mcp.sh    # MCP server build
│   ├── query-nih-dsld.py    # NIH DSLD queries
│   └── generate-embeddings.py  # RAG embeddings
├── output/             # Generated data (gitignored)
├── usda-fdc-data/      # Submodule: USDA FoodData Central
└── mcp-opennutrition/  # Submodule: OpenNutrition MCP
```

---

## Prerequisites

| Tool | Version | Installation |
| --- | --- | --- |
| **Python** | 3.8+ | [python.org](https://www.python.org/downloads/) |
| **Node.js** | 18+ | [nodejs.org](https://nodejs.org/) |
| **Git** | 2.x | [git-scm.com](https://git-scm.com/) |

### Optional (for embeddings)

| Tool | Purpose | Required Key |
| --- | --- | --- |
| **OpenAI API** | Cloud embeddings | `OPENAI_API_KEY` |
| **sentence-transformers** | Local embeddings | None |

---

## Quick Start

### One-Line Setup

```bash
git clone --recurse-submodules git@github.com:Syntropy-Health/open-diet-data.git
cd open-diet-data
./scripts/setup.sh
```

### Manual Setup

#### 1. Clone Repository

```bash
git clone --recurse-submodules git@github.com:Syntropy-Health/open-diet-data.git
cd open-diet-data
```

If already cloned without submodules:

```bash
git submodule update --init --recursive
```

#### 2. Setup USDA FoodData Central

```bash
./scripts/fetch-usda.sh
```

Or manually:

```bash
cd usda-fdc-data
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py --output_dir ../output/usda
deactivate
```

#### 3. Setup OpenNutrition MCP Server

```bash
./scripts/build-mcp.sh
```

Or manually:

```bash
cd mcp-opennutrition
npm install
npm run build
```

---

## Detailed Setup Guide

### USDA FoodData Central

**Source**: [fdc.nal.usda.gov](https://fdc.nal.usda.gov/)
**License**: Public Domain (US Government)
**API Key**: ❌ Not required

#### What Gets Downloaded

| Dataset | Size | Description |
| --- | --- | --- |
| Foundation Foods | ~50 MB | Whole foods with detailed nutrients |
| SR Legacy | ~30 MB | Historical USDA reference data |
| Branded Foods | ~2 GB | Commercial products with labels |

#### Output

```bash
output/usda/usda_food_nutrition_data.csv
```

Contains 900k+ food items with:
- 70+ nutrient columns (vitamins, minerals, amino acids)
- Portion sizes and gram weights
- Brand information (for branded foods)
- Food categories

#### Script Options

```bash
# Basic fetch
./scripts/fetch-usda.sh

# Keep intermediate files (warning: large)
./scripts/fetch-usda.sh --keep-files

# Custom filename
./scripts/fetch-usda.sh --filename my_data.csv
```

---

### OpenNutrition MCP Server

**Source**: [opennutrition.app](https://www.opennutrition.app/)
**License**: MIT
**API Key**: ❌ Not required (runs locally)

#### What Gets Built

The build process:
1. Compiles TypeScript to JavaScript
2. Decompresses bundled OpenNutrition dataset
3. Converts TSV data to SQLite database

#### Output

```bash
mcp-opennutrition/build/index.js      # MCP server entry
mcp-opennutrition/build/opennutrition.db  # SQLite database
```

#### MCP Configuration

**For Claude Desktop** (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mcp-opennutrition": {
      "command": "/usr/bin/node",
      "args": ["/path/to/open-diet-data/mcp-opennutrition/build/index.js"]
    }
  }
}
```

**For VS Code / Cline** (`.vscode/mcp.json`):

```json
{
  "mcpServers": {
    "mcp-opennutrition": {
      "command": "node",
      "args": ["mcp-opennutrition/build/index.js"]
    }
  }
}
```

#### Available MCP Tools

| Tool | Description | Example |
| --- | --- | --- |
| `search_foods` | Search by name/brand | "organic spinach" |
| `browse_foods` | Paginated food list | page=1, limit=20 |
| `get_food` | Get by food ID | "food_12345" |
| `barcode_lookup` | Find by EAN-13 barcode | "0042222850325" |

---

### NIH Dietary Supplement Label Database (DSLD)

**Source**: [dsld.od.nih.gov](https://dsld.od.nih.gov/)
**API Docs**: [dsld.od.nih.gov/api-guide](https://dsld.od.nih.gov/api-guide)
**License**: Public Domain (US Government)
**API Key**: ❌ Not required

#### Query Examples

```bash
# Search by ingredient
python scripts/query-nih-dsld.py --ingredient "vitamin d"

# Search by product name
python scripts/query-nih-dsld.py --product "fish oil"

# Search by brand
python scripts/query-nih-dsld.py --brand "nature made"

# Get specific product label
python scripts/query-nih-dsld.py --label 123456 --json
```

#### API Endpoints (No Key Required)

| Endpoint | Description |
| --- | --- |
| `GET /dsld/v9/browse` | Search products |
| `GET /dsld/v9/label/{id}` | Get product label |
| `GET /dsld/v9/ingredient` | Search by ingredient |

---

## Generating RAG Embeddings

### With OpenAI (Cloud)

Requires `OPENAI_API_KEY`:

```bash
# Get your API key from: https://platform.openai.com/api-keys
export OPENAI_API_KEY='sk-...'

# Generate embeddings
python scripts/generate-embeddings.py \
  --input output/usda/usda_food_nutrition_data.csv \
  --output output/embeddings/
```

### With Local Model (No API Key)

Uses sentence-transformers (all-MiniLM-L6-v2):

```bash
pip install sentence-transformers

python scripts/generate-embeddings.py \
  --input output/usda/usda_food_nutrition_data.csv \
  --local
```

### Output

```bash
output/embeddings/usda_embeddings.json
```

---

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | Optional | For cloud embeddings ([get key](https://platform.openai.com/api-keys)) |

No other API keys are required - all data sources are publicly accessible.

---

## Use Cases

- **RAG-powered dietary recommendations**: Query foods by nutrient content
- **Symptom-deficiency correlation**: Map symptoms to nutritional deficiencies
- **LLM food queries**: Enable Claude/GPT to look up nutrition data via MCP
- **Supplement validation**: Cross-reference dosages with NIH DSLD
- **Recipe nutrition analysis**: Calculate nutrient totals for recipes

---

## Integration

This data is consumed by:

- [diet-insight-engine](https://github.com/Syntropy-Health/diet-insight-engine) - Symptom-Diet Optimizer (SDO)
- `health-store-agent` - Product recommendations
- Custom Shopify wellness products (future)

---

## Troubleshooting

### USDA Download Fails

```bash
# Check internet connection and try again
./scripts/fetch-usda.sh

# If branded foods fail (large file), try foundation only
cd usda-fdc-data
python3 main.py --output_dir ../output/usda --skip-branded
```

### MCP Server Won't Start

```bash
# Verify Node.js version
node --version  # Should be 18+

# Rebuild from scratch
cd mcp-opennutrition
rm -rf node_modules build
npm install
npm run build
```

### NIH DSLD Rate Limiting

The NIH API has rate limits. If you see 429 errors:

```bash
# Add delays between requests
python scripts/query-nih-dsld.py --ingredient "vitamin d" --delay 1
```

---

## Documentation

- [PRD.md](./PRD.md) - Product requirements and architecture
- [AGENT.md](./AGENT.md) - NutritionDataAgent specification
- [DATA_SOURCES.md](./DATA_SOURCES.md) - Source evaluation and references

## Official Data Source Links

| Source | Website | API Docs |
| --- | --- | --- |
| USDA FDC | [fdc.nal.usda.gov](https://fdc.nal.usda.gov/) | [Download](https://fdc.nal.usda.gov/download-datasets/) |
| OpenNutrition | [opennutrition.app](https://www.opennutrition.app/) | N/A (local) |
| NIH DSLD | [dsld.od.nih.gov](https://dsld.od.nih.gov/) | [API Guide](https://dsld.od.nih.gov/api-guide) |

---

## License

- **USDA FoodData Central**: Public Domain (US Government)
- **OpenNutrition**: MIT License
- **NIH DSLD**: Public Domain (US Government)
- **Scripts & Documentation**: MIT License

## Contributing

1. Fork the repository
2. Add data sources as submodules
3. Update documentation
4. Submit a pull request

---

Part of the [Syntropy Health](https://github.com/Syntropy-Health) ecosystem.
