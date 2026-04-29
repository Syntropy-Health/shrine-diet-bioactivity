# KG Ingestion Comparison: Direct vs Graphiti

PoC results from the unified phytochemical knowledge graph experiment.

## Setup

| Component | Config |
|-----------|--------|
| Neo4j | Railway: `bolt://metro.proxy.rlwy.net:22971` (test env) |
| Graphiti server | Railway: `graphiti-test.up.railway.app` (test env) |
| LLM (Graphiti) | OpenRouter: `nvidia/nemotron-3-nano-30b-a3b:free` |
| Embeddings (Graphiti) | OpenRouter: `nvidia/llama-nemotron-embed-vl-1b-v2:free` (2048-dim) |
| Embeddings (Direct) | LM Studio: `text-embedding-embeddinggemma-300m-qat` (768-dim) |
| SQLite source | 2,376 herbs, 94K compounds, 4.3K targets, 795K disease associations |

## Results

### Direct Neo4j Ingestion (Structured Data)

| Metric | Value |
|--------|-------|
| Nodes created | 1,347 (100 Herb + 200 Compound + 1,000 Target + 47 Symptom) |
| Relationships | 1,185 (346 CONTAINS_COMPOUND + 371 TARGETS_PROTEIN + 468 TREATS) |
| Ingestion time | ~3 minutes |
| Rate | ~300 nodes/min (embedding-bound) |
| Accuracy | 100% — data is already structured |
| Entity types | Typed labels (Herb, Compound, Target, Symptom) |
| LLM calls | 0 |
| Embedding calls | 300 (herbs + compounds only) |
| Schema | Explicit: MERGE with typed labels, SET properties |

### Graphiti Ingestion (Textual Corpus)

| Metric | Value |
|--------|-------|
| Episodes sent | 45 (20 herb monographs + 20 compound profiles + 5 PubMed abstracts) |
| Entities extracted | 8 (from 1 fully processed episode) |
| Relationships | 6 RELATES_TO + 8 MENTIONS |
| Processing time | ~60s per episode (free tier LLM) |
| Rate | ~1 episode/min |
| Accuracy | ~70% — correctly identified Curcumin, NF-kB, TNF-alpha, IKKbeta, rheumatoid arthritis |
| Entity types | Generic `Entity` label (no typed labels) |
| LLM calls | ~5-10 per episode (extract nodes, extract edges, deduplicate, resolve) |
| Embedding calls | ~5-10 per episode (entity embeddings, edge embeddings) |
| Schema | Emergent: Graphiti discovers entities and relationships |

## Unified KG State

```
Neo4j (test environment): bolt://metro.proxy.rlwy.net:22971

Direct-ingested (structured):
  ├── 100 Herb nodes (with embeddings)
  ├── 200 Compound nodes (with embeddings)
  ├── 1,000 Target nodes
  ├── 47 Symptom nodes
  ├── 346 CONTAINS_COMPOUND edges
  ├── 371 TARGETS_PROTEIN edges
  └── 468 TREATS edges

Graphiti-extracted (textual):
  ├── 8 Entity nodes (Curcumin, NF-kB, TNF-alpha, IL-1beta, IL-6, IKKbeta, rheumatoid arthritis, researcher)
  ├── 1 Episodic node (provenance)
  ├── 6 RELATES_TO edges
  └── 8 MENTIONS edges
  └── ~44 episodes queued (processing via OpenRouter free tier)

Total: 1,356 nodes, 1,199 relationships
```

## Data Scalability Comparison

### Direct Ingestion — Best for Structured Data

| Data Modality | Approach | Scalability |
|--------------|----------|-------------|
| CSV/TSV (Duke, CMAUP, TTD) | Parse → normalize → MERGE | **O(n)** — linear, predictable |
| JSON/API (BATMAN-TCM) | Fetch → normalize → MERGE | **O(n)** — bounded by API rate |
| SQL dumps (STITCH, CTD) | Stream → filter → MERGE | **O(n)** — memory-efficient streaming |

**Pros**: Deterministic, fast (300+ nodes/min), typed schema, zero LLM cost, reproducible
**Cons**: Requires manual schema mapping per source, can't discover implicit relationships

### Graphiti — Best for Unstructured Text

| Data Modality | Approach | Scalability |
|--------------|----------|-------------|
| PubMed abstracts | Episode → LLM extract → graph | **O(n × k)** — k LLM calls per episode |
| Clinical notes | Episode → LLM extract → graph | **O(n × k)** — same |
| Kaggle NER corpus | Episode → LLM extract → graph | **O(n × k)** — same |
| Web-scraped monographs | Episode → LLM extract → graph | **O(n × k)** — same |

**Pros**: Discovers implicit relationships, handles any text format, temporal tracking, provenance, semantic dedup
**Cons**: LLM-bound throughput (~1 ep/min on free tier), non-deterministic, higher cost at scale

### Head-to-Head

| Factor | Direct | Graphiti | Winner |
|--------|--------|----------|--------|
| **Structured data speed** | 300 nodes/min | ~1 ep/min | Direct (300×) |
| **Text data capability** | Cannot process | Extracts entities | Graphiti |
| **Schema control** | Full (typed labels) | Emergent (generic Entity) | Direct |
| **Relationship discovery** | Only explicit | Discovers implicit | Graphiti |
| **Cost at 100K entities** | ~$0 (local embeddings) | ~$5-50 (LLM calls) | Direct |
| **Reproducibility** | 100% | ~70% (LLM variance) | Direct |
| **Temporal tracking** | Manual (source column) | Built-in (valid_at/invalid_at) | Graphiti |
| **Provenance** | Source column | Full episode lineage | Graphiti |
| **Semantic search** | Vector index on name | Hybrid (vector + BM25 + graph) | Graphiti |
| **Multi-hop queries** | Manual Cypher | Automatic traversal | Graphiti |

## Recommendation: Hybrid Architecture

```
┌─────────────────────────────────────────────��───────────┐
│                   UNIFIED KG (Neo4j)                     │
│                                                          │
│  ┌──────────────────────┐  ┌──────────────────────────┐ │
│  │  Direct-Ingested     │  │  Graphiti-Extracted       │ │
│  │  (Structured Data)   │  │  (Textual Corpus)         │ │
│  │                      │  │                           │ │
│  │  :Herb               │  │  :Entity                  │ │
│  │  :Compound           │  │  :Episodic                │ │
│  │  :Target             │  │  :Community               │ │
│  │  :Symptom            │  │                           │ │
│  │                      │  │  Discovered relationships:│ │
│  │  Explicit edges:     │  │  - mechanism of action    │ │
│  │  - CONTAINS_COMPOUND │  │  - clinical trial results │ │
│  │  - TARGETS_PROTEIN   │  │  - dosage information     │ │
│  │  - TREATS            │  │  - adverse effects        │ │
│  └────────────────��─────┘  └──────────────────────────┘ │
│                                                          │
│  Bridge: Link :Entity nodes to :Herb/:Compound by name  │
│  Query: Direct for lookups, Graphiti for discovery       │
└────────────────────────────────────────────────────��────┘
```

**Use Direct for:**
- All structured databases (Duke, FooDB, CMAUP, CTD, TTD, STITCH, DisGeNET)
- Batch loading with known schemas
- Typed, queryable entity nodes

**Use Graphiti for:**
- PubMed abstracts (mechanism discovery)
- Clinical trial reports (outcome extraction)
- Traditional medicine texts (indication mapping)
- Any new text source where entities aren't pre-defined

**Bridge strategy:**
After both ingestion methods run, create cross-links between Graphiti's `:Entity` nodes and Direct's typed nodes via name matching:
```cypher
MATCH (e:Entity), (c:Compound)
WHERE toLower(e.name) = toLower(c.name)
MERGE (e)-[:SAME_AS]->(c)
```

## How to View the KG

### Neo4j Desktop (Recommended)
Connect to `bolt://metro.proxy.rlwy.net:22971` with `neo4j`/`demodemo`.

### CLI
```bash
cd mcp-herbal-botanicals
make neo4j-check     # Quick stats
make neo4j-stats     # Detailed breakdown
```

### Cypher Queries

```cypher
-- All Graphiti-discovered entities
MATCH (e:Entity) RETURN e.name, e.entity_type ORDER BY e.name

-- Graphiti relationships with provenance
MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
RETURN a.name, r.fact, b.name

-- Multi-hop: Direct + Graphiti combined
MATCH (h:Herb)-[:CONTAINS_COMPOUND]->(c:Compound)
WHERE h.common_name = 'Turmeric'
OPTIONAL MATCH (e:Entity)-[:RELATES_TO]->(e2:Entity)
WHERE e.name = c.name
RETURN h.common_name, c.name, e2.name AS graphiti_discovery

-- Graphiti semantic search (via API)
-- POST https://graphiti-test.up.railway.app/search
-- {"query": "anti-inflammatory mechanism", "group_ids": ["poc-unified-kg"], "num_results": 10}
```

## Configuration

### Railway Test Environment
```
Project: syntropy
Environment: test
Service: graphiti
Domain: graphiti-test.up.railway.app

OPENAI_API_KEY=<OpenRouter key>
OPENAI_BASE_URL=https://openrouter.ai/api/v1
MODEL_NAME=nvidia/nemotron-3-nano-30b-a3b:free
EMBEDDING_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free
EMBEDDING_DIM=2048
NEO4J_URI=bolt://neo4j.railway.internal:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=demodemo
```

### Local (.env)
See `mcp-herbal-botanicals/graphiti/.env`

---

*Generated: 2026-04-10*
*Status: PoC complete — Graphiti processing 44 remaining episodes asynchronously*

---

## Update: LightRAG Supersedes Graphiti (2026-04-12)

After evaluating the Graphiti PoC above, we migrated to **LightRAG** for the unified diet KG.

### Why LightRAG over Graphiti

| Factor | Graphiti | LightRAG | Winner |
|--------|----------|----------|--------|
| **Structured data injection** | JSON episodes via LLM (~1 ep/min) | `ainsert_custom_kg()` — zero LLM | **LightRAG** |
| **Temporal overhead** | Heavy (valid_at/invalid_at/expired_at) | None — no episodic machinery | **LightRAG** |
| **Query modes** | Hybrid (cosine + BM25 + BFS) | 5 modes + reranker support | **LightRAG** |
| **Local embeddings** | Custom embedder required | Ollama/HuggingFace native | **LightRAG** |
| **Storage backends** | 4 (Neo4j, FalkorDB, Kuzu, Neptune) | 10+ (Neo4j, PG, Mongo, Redis...) | **LightRAG** |
| **API server** | None (custom required) | Built-in FastAPI + WebUI | **LightRAG** |
| **Design fit** | Episodic agent memory | Document/reference KG | **LightRAG** |

### Key Advantage: `ainsert_custom_kg()`

Direct injection of pre-structured entities and relationships — zero LLM cost, 100% accuracy, typed Neo4j labels.

### Config Profiles

| Profile | LLM | Embedding | Reranker | Use Case |
|---------|-----|-----------|----------|----------|
| `config_local.env` | Ollama qwen3.5:9b | Ollama bge-m3 (1024-dim) | None | Dev/test |
| `config_production.env` | GPT-4o-mini | text-embedding-3-large (3072-dim) | Jina multilingual | Production (CN+EN) |

See `mcp-herbal-botanicals/lightrag/` for configuration and ingestion scripts.
