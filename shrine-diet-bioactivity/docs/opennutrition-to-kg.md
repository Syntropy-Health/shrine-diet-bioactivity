# OpenNutrition → Knowledge Graph — Archived Workflow

This document preserves the ingestion workflow used to build the
current **prototype** knowledge graph from OpenNutrition + Duke +
FooDB + CMAUP + CTD + TTD sources. It is **not** wired into any
default runtime target — shrine-diet-bioactivity runs against the
already-ingested Neo4j workspace and never re-reads the raw TSV
sources.

Keep this file when you need to:

- re-ingest from scratch against a fresh Neo4j workspace,
- extend to the full 326k OpenNutrition catalog (the prototype
  subsample is narrower — see `Makefile` MAX_* variables),
- port the ingestion methodology to a new dataset.

---

## 1. Source datasets

| Source | Path in tree | Size | Format |
|---|---|---|---|
| Dr. Duke's Phytochemical DB | `data/duke-*.csv` | ~40 MB | CSV |
| FooDB | `data/foodb-*.csv` | ~900 MB | CSV |
| OpenNutrition | `data/opennutrition/foods.tsv` (vendored) | ~200 MB | TSV |
| CMAUP v2.0 | `data/cmaup-*.tsv` | ~10 MB | TSV |
| CTD chemicals | `data/CTD_chemicals_diseases.csv.gz` | ~50 MB | CSV.gz |
| TTD targets | `data/ttd-*.txt` | ~5 MB | TSV |

OpenNutrition was previously consumed as the `mcp-opennutrition/`
git submodule. That submodule was removed in 2026-05; the TSV data
is now vendored under `shrine-diet-bioactivity/data/opennutrition/`
and accessed directly by the ingest pipeline. The upstream MCP server
it shipped is not part of this project's runtime.

## 2. Pipeline overview

```
raw CSV/TSV
    │
    ▼  build-herbal-db.ts            # SQLite intermediate
herbal_botanicals.db  ──►  food-bridge  ──►  enrich-nutrition
    │                      (fuzzy join: FooDB food_name ↔
    │                       OpenNutrition food_name)
    ▼
ingest_unified.py             # LightRAG custom_kg payloads
    │                         # with scope='shared' on every row
    ▼
rag.ainsert_custom_kg(...)    # via ScopedNeo4JStorage
    │
    ▼
Neo4j (workspace=unified_diet_kg, scope-indexed)
```

## 3. Reproducible prototype run

The prototype KG is reproducible from the raw sources with:

```bash
make download          # ~960 MB (Duke + FooDB)
make build             # Build SQLite intermediate
make food-bridge       # Bridge FooDB foods ↔ OpenNutrition
make enrich-nutrition  # Add nutrition_100g to compound_foods
make lightrag-bootstrap-scope   # Create scope='shared' index
make lightrag-ingest-prototype  # Pinned MAX_* flags — see Makefile
```

The `lightrag-ingest-prototype` target uses the Makefile's pinned
MAX_HERBS / MAX_COMPOUNDS / MAX_RELATIONSHIPS variables plus
SUBSAMPLE_SEED (reserved for future RNG sampling). SQL queries in
`entity_schema.py` include explicit `ORDER BY <pk>` so `LIMIT N`
subsampling is deterministic across rebuilds of the SQLite
intermediate.

## 4. Scaling to the full OpenNutrition catalog (~326k foods)

Replace the Makefile pin with unbounded flags:

```makefile
MAX_FOODS         := 0       # 0 = unlimited in lightrag-ingest-prototype
MAX_RELATIONSHIPS := 0
```

Expect the ingestion to take 2–6 hours on local Ollama embeddings.
Switch to `config_production.env` (OpenAI `text-embedding-3-large`,
3072-dim) for full-catalog production runs.

Ingestion is **not** part of the MCP runtime. Run it separately from
any live shrine-diet-bioactivity deployment — the Neo4j workspace is
updated in place, and the MCP starts seeing new nodes on the next
query with no restart required.

## 5. What NOT to do

- Don't wire `make setup` into a CI job that deploys the MCP. The
  ingestion is heavyweight and belongs in an offline data pipeline.
- Don't store nutrition data in a sibling SQLite DB for the MCP to
  query — that creates two sources of truth and the property-annex
  approach was retired in the v2 plan.
- Don't call `ingest_unified.py` with mismatched embedding models
  against an existing workspace; LightRAG's CLAUDE.md explains why.
