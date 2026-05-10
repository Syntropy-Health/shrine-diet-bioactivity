# shrine-diet-bioactivity

**Thin MCP adapter over the scoped LightRAG wrapper.** Owns tenancy +
audit only; carries zero retrieval logic of its own. All knowledge —
structured nutrition properties, bioactivity relationships, compound
metadata — lives in a single Neo4j knowledge graph, queried through
LightRAG's API.

Five domain-agnostic tools cover every retrieval and ingestion mode
the agent needs. Clinical verbs (*find protocols for a biomarker,
compare interventions, check contraindications*) are **agent-layer**
compositions on top of these primitives — see
[`docs/clinical-integration-notes.md`](./docs/clinical-integration-notes.md).

For wiring a client, see [`docs/integration-guide.md`](./docs/integration-guide.md).

## MCP tool catalog

| # | Tool | LightRAG route | Purpose |
|---|---|---|---|
| 1 | `semantic-search` | `POST /query` | 5-mode KG retrieval (local/global/hybrid/mix/naive), scope-filtered |
| 2 | `get-entity` | `GET /graphs?max_depth=0` | Single entity by id with full property bag |
| 3 | `get-subgraph` | `GET /graphs?max_depth=N` | Connected neighborhood, scope-filtered |
| 4 | `list-labels` | `GET /graph/label/popular` | Ontology shape visible in caller scope |
| 5 | `ingest-knowledge` | `POST /documents/custom_kg` | Tenant-private write; server forces `scope=tenant:<id>` |
| — | `get-health` | — | Server status |

Every call is scope-filtered (`['shared', 'tenant:<id>']`) via
`ScopedNeo4JStorage` + a per-request `ContextVar` and emits one audit
row in `audit/mcp_audit.db`.

## Architecture

```
  MCP client (agent, IDE, CLI)
         │  MCP stdio, 5 tools + health
         ▼
  shrine-diet-bioactivity (Node/TS)
         │  HTTP
         ▼
  scoped_server.py (FastAPI)           audit/mcp_audit.db
    │ set ContextVar[scope_filter]
    ▼
  LightRAG + ScopedNeo4JStorage
    │  WHERE n.scope IN $scope_filter
    ▼
  Neo4j workspace=unified_diet_kg
```

## Setup

```bash
npm install
npm test                         # 55+ unit/integration tests
npm run build                    # emits build/index.js

# Python side (scoped LightRAG wrapper)
cd lightrag
pip install -r requirements.txt
make lightrag-test-scope         # unit tests, no Neo4j required
```

Run the server:

```bash
# 1. Start the scoped LightRAG wrapper on :9621
make lightrag-server

# 2. Start the MCP (wires to :9621 by default)
npx tsx src/index.ts
# or: node build/index.js
```

Env:

| Variable | Default | Purpose |
|---|---|---|
| `LIGHTRAG_API_URL` | `http://localhost:9621` | Scoped LightRAG wrapper URL |
| `MCP_AUDIT_DB` | `./audit/mcp_audit.db` | Audit log SQLite path |

## Usage with Claude

`.mcp.json`:

```json
{
  "mcpServers": {
    "shrine-diet-bioactivity": {
      "type": "stdio",
      "command": "node",
      "args": ["/path/to/shrine-diet-bioactivity/build/index.js"],
      "env": { "LIGHTRAG_API_URL": "http://localhost:9621" }
    }
  }
}
```

## Data coverage (current prototype KG)

The KG is already populated in Neo4j. The MCP never re-reads raw
source files; it only queries the graph. See
[`docs/opennutrition-to-kg.md`](./docs/opennutrition-to-kg.md) for the
archived ingestion workflow (how to rebuild from raw sources if
needed).

| Ontology | Rows in graph | Source |
|---|---|---|
| Herbs | ~2,376 | Dr. Duke's Phytochemical DB |
| Compounds | ~5,000 (subsampled) | Dr. Duke's + FooDB |
| Foods | subsampled | OpenNutrition 326K catalog |
| Targets / Diseases / Symptoms | CMAUP + TTD + curated | — |

Subsample config (pinned for reproducibility) lives in
[`Makefile`](./Makefile) under `MAX_HERBS`, `MAX_COMPOUNDS`,
`MAX_FOODS`, `MAX_RELATIONSHIPS`. `make lightrag-ingest-prototype`
reproduces the current KG from the SQLite intermediate.

## Reference submodules

- `lightrag/` — **active dependency**. The scoped wrapper subclasses
  its Neo4j storage and mounts its graph routes.

The previously-vendored `mcp-opennutrition/` submodule was removed in
2026-05 (its TSV→KG mapping methodology is preserved in
`docs/opennutrition-to-kg.md`; the OpenNutrition MCP server it shipped
was never composed at runtime).

## Part of Syntropy Health

Data foundation for [Syntropy Health](https://github.com/Syntropy-Health)'s AI
dietitian / clinical-practice platform.
