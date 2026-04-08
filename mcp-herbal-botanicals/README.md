# mcp-herbal-botanicals

The first MCP server for dietary and phytochemical compound data. Bridges herbal medicine to food nutrition using Dr. Duke's Phytochemical Database and FooDB.

## What It Does

Given a herb (e.g., ashwagandha), returns its active phytochemical compounds, and which common foods share those same compounds. Enables AI agents to answer queries like:

> "What foods give me the same benefits as ashwagandha?"

## Data Coverage

| Table | Rows | Source |
|-------|------|--------|
| Herbs | 2,376 | Dr. Duke's Phytochemical DB |
| Compounds | 94,512 | Dr. Duke's + FooDB |
| Herb-Compound links | 99,280 | Dr. Duke's |
| Compound-Food links | 4,149,541 | FooDB |
| Bridge compounds | 4,449 | Compounds in both herbs AND foods |

**92% of top-25 herbal supplements covered** with compound data and food overlap.

## MCP Tools

| Tool | Description |
|------|-------------|
| `search-herbs` | Fuzzy search herbs by common/scientific name |
| `get-herb-compounds` | Active compounds for a given herb with concentrations |
| `search-compounds` | Search compounds by name, see herb + food associations |
| `get-compound-foods` | Foods containing a specific compound |
| `get-herb-food-overlap` | Foods sharing the most compounds with a herb |
| `search-by-bioactivity` | Herbs/compounds by health benefit (anti-inflammatory, etc.) |
| `get-herb-profile` | Full herb monograph (compounds, bioactivities, food overlap) |
| `get-health` | Database stats and health check |

## Setup

```bash
# Install dependencies
npm install

# Download source data (~960 MB total)
npm run download-data

# Build database from source CSVs
npm run convert-data

# Run tests
npm test

# Run data quality audit
npm run audit

# Build TypeScript
npm run build
```

## Usage with Claude

Add to your Claude MCP config (`.mcp.json` or Claude settings):

```json
{
  "mcpServers": {
    "herbal-botanicals": {
      "type": "stdio",
      "command": "npx",
      "args": ["tsx", "/path/to/mcp-herbal-botanicals/src/index.ts"]
    }
  }
}
```

Then ask Claude: "What compounds are in turmeric?" or "What foods share compounds with ashwagandha?"

## Data Sources

| Source | License | Role |
|--------|---------|------|
| [Dr. Duke's Phytochemical DB](https://phytochem.nal.usda.gov) | CC0 (Public Domain) | Herb-to-compound mappings |
| [FooDB](https://foodb.ca) | CC BY-NC 4.0 | Compound-to-food mappings |

## Architecture

```
Dr. Duke's CSV (5.8 MB)  ──► build-herbal-db.ts ──► herbal_botanicals.db
                                                         │
FooDB CSV (952 MB)  ────────►  (compound name     ──► SQLite with
                                normalization)          pre-joined data
                                                         │
                                                    MCP Server (stdio)
                                                    ├── search-herbs
                                                    ├── get-herb-compounds
                                                    ├── search-compounds
                                                    ├── get-compound-foods
                                                    ├── get-herb-food-overlap
                                                    ├── search-by-bioactivity
                                                    ├── get-herb-profile
                                                    └── get-health
```

## Part of Syntropy Health

This MCP server is the data foundation for [Syntropy Health](https://github.com/Syntropy-Health)'s AI dietitian, composable with [mcp-opennutrition](../mcp-opennutrition/) for complete food + herbal nutrition coverage.
