# shrine-diet-bioactivity

**LightRAG-driven semantic index + retrieval MCP server** over the
diet + bioactivity knowledge graph. Specialized to the data ontology
(herbs, phytochemical compounds, foods, targets, diseases, symptoms,
plus tenant-scoped protocols / interventions / outcomes / biomarkers) —
domain-agnostic in its tool surface. Multi-tenant by design, with
per-request audit logging for traceability and billing.

Clinical-workflow verbs (*find protocols for a biomarker, compare
interventions, check contraindications*) are **agent-layer**
compositions on top of this MCP — see
[`docs/clinical-integration-notes.md`](./docs/clinical-integration-notes.md).

For wiring a client, see [`docs/integration-guide.md`](./docs/integration-guide.md).

## Data Coverage

| Table | Rows | Source |
|-------|------|--------|
| Herbs | 2,376 | Dr. Duke's Phytochemical DB |
| Compounds | 94,512 | Dr. Duke's + FooDB |
| Herb-Compound links | 99,280 | Dr. Duke's |
| Compound-Food links | 4,149,541 | FooDB |
| Bridge compounds | 4,449 | In both herbs AND foods |
| Foods (structured nutrition) | 326,759 | OpenNutrition (90 nutrient keys) |
| Targets / Diseases / Symptoms | 4,355 / 50K+ / 47 | CMAUP + TTD + curated |

## MCP Tools — post-pivot target (7 tools, domain-agnostic)

| # | Tool | Backed by | Purpose |
|---|---|---|---|
| 1 | `semantic-search` | LightRAG `/query` | Hybrid / local / global / mix / naive KG retrieval, scope-filtered |
| 2 | `get-entity` | LightRAG graph routes | Look up an entity by id |
| 3 | `get-neighbors` | LightRAG graph routes | 1–2-hop neighborhood, optional edge-type filter |
| 4 | `list-entity-types` | LightRAG graph routes | Discover ontology labels + in-scope counts |
| 5 | `get-structured-properties` | SQLite annex | Exact property lookup (nutrition_100g, LD50, dosage) |
| 6 | `filter-by-property` | SQLite annex | Numeric / enum filters |
| 7 | `ingest-tenant-knowledge` | LightRAG `/documents` + `ainsert_custom_kg` | Tenant write path; scope forced to `tenant:<id>` |

The current codebase still ships the legacy 14-tool surface — see
[`.claude/PRPs/plans/lightrag-thin-adapter-pivot.plan.md`](../.claude/PRPs/plans/lightrag-thin-adapter-pivot.plan.md)
for the migration.

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
