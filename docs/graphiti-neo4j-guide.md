# Graphiti + Neo4j Knowledge Graph Guide

How to set up, ingest, visualize, and query the phytochemical knowledge graph.

## Architecture

```
SQLite (herbal_botanicals.db)
  │
  ├── herbs, compounds, targets, diseases
  │
  └── graphiti/ingest.py ──► Graphiti (Python SDK)
                                │
                                ├── LLM (entity extraction)
                                ├── Embeddings (vector indexing)
                                │
                                └──► Neo4j (graph storage)
                                      │
                                      ├── EntityNode (Herb, Compound, Target...)
                                      ├── EpisodicNode (provenance)
                                      └── Edges (CONTAINS, TARGETS, TREATS...)
```

## Setup

### Option A: Cloud Neo4j (Railway)

The project has a Neo4j instance on Railway. **Use the TCP proxy** — the domain endpoint has DNS reliability issues.

| Property | Value |
|----------|-------|
| **Bolt URI (use this)** | `bolt://metro.proxy.rlwy.net:22971` |
| Domain URI (fallback) | `bolt://neo4j-test-2be3.up.railway.app:7687` |
| Credentials | `neo4j` / `demodemo` |

**How to view the Neo4j KG on Railway:**

Railway exposes Neo4j via TCP proxy only (no HTTP browser endpoint). To visualize:

1. **Neo4j Desktop** (recommended): Add remote connection → `bolt://metro.proxy.rlwy.net:22971` → `neo4j`/`demodemo`
2. **Makefile**: `make neo4j-check` shows node/edge counts, `make neo4j-stats` shows detailed breakdown
3. **Python**: See "Quick Check" section below

```bash
cd mcp-herbal-botanicals/graphiti
cp .env.example .env
# Credentials are pre-configured — ready to use
```

### Option B: Local Neo4j (Docker)

```bash
docker run -d \
  --name neo4j-herbal \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:5-community
```

Then update `.env`:
```
NEO4J_URI=bolt://localhost:7687
NEO4J_PASSWORD=password123
```

### Embedding Server (LM Studio)

Start LM Studio, load `text-embedding-embeddinggemma-300m-qat`, and verify:

```bash
curl http://127.0.0.1:1234/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "text-embedding-embeddinggemma-300m-qat",
    "input": "test embedding"
  }'
```

Note the dimension from the response — update `EMBEDDING_DIM` in `.env` if not 768.

## Ingestion

### Prerequisites

```bash
cd mcp-herbal-botanicals

# Build the SQLite database (if not already done)
npm run download-data
npm run convert-data
npm run migrate-kg
npm run migrate-multi-source   # loads CMAUP, CTD, TTD

# Set up Python environment
cd graphiti
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Dry Run

```bash
python ingest.py --dry-run
```

Shows what would be ingested without connecting to Neo4j.

### Run Ingestion

```bash
# Start small (default: 100 herbs, 500 compounds)
python ingest.py

# Ingest everything (slow — LLM calls per episode)
MAX_HERBS=2376 MAX_COMPOUNDS=10000 python ingest.py
```

## Visualizing the KG

### Neo4j Browser

1. Open Neo4j Browser:
   - **Cloud**: `https://neo4j-test-2be3.up.railway.app:7474`
   - **Local**: `http://localhost:7474`
2. Log in with credentials from `.env`

### Useful Cypher Queries

**Count all nodes and relationships:**
```cypher
MATCH (n) RETURN labels(n) AS type, COUNT(n) AS count
ORDER BY count DESC
```

**Find all herbs:**
```cypher
MATCH (h:Entity {entity_type: 'Herb'})
RETURN h.name, h.scientific_name, h.is_food_plant
ORDER BY h.name
LIMIT 50
```

**Find compounds in a specific herb:**
```cypher
MATCH (h:Entity {name: 'Turmeric'})-[r]->(c:Entity {entity_type: 'Compound'})
RETURN h.name, type(r), c.name, c.compound_class
```

**Multi-hop: Symptom → Herb → Compound → Target:**
```cypher
MATCH path = (s:Entity {entity_type: 'Symptom'})-[*1..3]-(t:Entity {entity_type: 'Target'})
WHERE s.name CONTAINS 'inflammation'
RETURN path
LIMIT 20
```

**Food plants with most compound connections:**
```cypher
MATCH (h:Entity {is_food_plant: true})-[r]->(c:Entity {entity_type: 'Compound'})
RETURN h.name, COUNT(c) AS compound_count
ORDER BY compound_count DESC
LIMIT 20
```

**Visualize a herb's neighborhood:**
```cypher
MATCH (h:Entity {name: 'Ashwagandha'})-[r]-(connected)
RETURN h, r, connected
```

## Querying via Graphiti Python SDK

```python
from graphiti_core import Graphiti
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

# Configure (same as ingest.py)
embedder = OpenAIEmbedder(config=OpenAIEmbedderConfig(
    base_url="http://127.0.0.1:1234/v1",
    api_key="not-needed",
    embedding_model="text-embedding-embeddinggemma-300m-qat",
    embedding_dim=768,
))

graphiti = Graphiti(
    "bolt://neo4j-test-2be3.up.railway.app:7687",
    "neo4j", "your-password",
    embedder=embedder,
)

# Semantic search (hybrid: embedding + BM25 + graph traversal)
results = await graphiti.search("anti-inflammatory compounds in turmeric")
for edge in results:
    print(f"{edge.fact} (valid: {edge.valid_at})")

# Node search
from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF
config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
config.limit = 10
nodes = await graphiti._search(query="quercetin", config=config)

await graphiti.close()
```

## Comparison: MCP Tool-Call vs Graphiti vs Raw Cypher

### Query: "What foods help with inflammation?"

**MCP (search-by-symptom):**
```json
// Tool call: search-by-symptom({ "query": "inflammation" })
// Returns: structured JSON with exact symptom matches, herbs, compounds, foods
// Latency: <200ms
// Coverage: Only finds "Inflammation" symptom (exact match)
```

**Graphiti (semantic search):**
```python
results = await graphiti.search("foods that help with inflammation")
# Returns: edges with facts, provenance, temporal validity
# Latency: ~500ms-2s (embedding + graph traversal)
# Coverage: Finds "inflammation", "anti-inflammatory", "chronic pain" (semantic)
```

**Raw Cypher:**
```cypher
MATCH (s:Entity)-[:TREATS]->(h:Entity {is_food_plant: true})-[:CONTAINS]->(c:Entity)
WHERE s.name CONTAINS 'inflam'
RETURN h.name, COLLECT(DISTINCT c.name) AS compounds
ORDER BY SIZE(compounds) DESC
LIMIT 10
// Latency: ~100ms
// Coverage: Only exact string match on "inflam"
```

### When to Use Each

| Query Type | Best Approach |
|------------|---------------|
| Exact lookup by ID | MCP tool call |
| Structured aggregation | MCP tool call |
| Natural language question | Graphiti semantic search |
| Multi-hop traversal | Graphiti or Cypher |
| Exploratory/discovery | Graphiti semantic search |
| Visualization | Cypher in Neo4j Browser |
| Offline / embedded | MCP tool call (SQLite) |
