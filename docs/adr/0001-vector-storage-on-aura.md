# ADR 0001 — Production Vector Storage on Aura, Local NanoVectorDB for Pipeline Dev Only

**Status:** Accepted (2026-04-26).
**Decider:** Matthew Mo / Syntropy Health.
**Stakeholders:** Subsystem A (data moat), Subsystem F (eval harness), Subsystem H (clinical research team).

## Context

The shrine-diet-bioactivity unified KG currently uses LightRAG's default
`NanoVectorDBStorage` — a single-process, file-backed vector store at
`rag_storage_local/`. This produced two incidents in the v1 eval re-run:

1. **Embedding-dim drift.** The 04-12 session populated NanoVectorDB at 768-dim
   (Ollama `nomic-embed-text`). The current `config_local.env` configures the
   embedder at 2048-dim (`nvidia/llama-nemotron-embed-vl-1b-v2:free` via
   OpenRouter). NanoVectorDB refuses to load mismatched-dim caches with a
   cryptic `AssertionError: Embedding dim mismatch`. The cache became stuck
   in a state that needs manual intervention every time the embedder
   changes.
2. **Dual cache paths.** `WORKING_DIR=./rag_storage_local` is interpreted
   relative to whichever cwd starts the LightRAG instance. The Makefile's
   `lightrag-server` target uses `cd lightrag && uvicorn …`, which puts the
   cache at `lightrag/rag_storage_local/`. Other entry points (`make
   lightrag-ingest-local`, ad-hoc CLI runs) may resolve `cwd` differently
   and write to `shrine-diet-bioactivity/rag_storage_local/`. Two parallel
   caches diverge silently.

These issues are not bugs in NanoVectorDB — they're a fundamental mismatch
between a single-process file cache and the multi-process / multi-machine
production target.

## Decision

**Production vector storage will live in Neo4j Aura, alongside the graph.**

Rationale:
- **Single source of truth.** The graph is already in Aura. Storing vectors
  on the same nodes (as `embedding` properties indexed by Neo4j 5.13+'s
  native vector index `db.index.vector.queryNodes`) eliminates dual-store
  consistency problems and the need for a separate vector DB vendor.
- **No cache drift.** No local file lifecycle to manage; the only "reset"
  is `DROP INDEX` + `REMOVE n.embedding` (recoverable, scoped per workspace).
- **Multi-tenant ready.** The same `scope='shared'` / `scope='tenant:<slug>'`
  property that gates graph reads (per ADR-implicit policy in `scope_context.py`)
  applies uniformly to vector reads — one access-control story.
- **No new vendor.** Aura is already a paid dependency. Adding Qdrant /
  Milvus / OpenSearch would broaden the supply-chain surface without solving
  the multi-tenant or consistency problems above.
- **HNSW under the hood.** Neo4j's native vector index uses HNSW with
  configurable similarity functions (cosine, euclidean). Performance
  characteristics are adequate for our 24K-node KG (and scale to millions
  per Neo4j benchmarks).

**Local NanoVectorDB stays for pipeline development only** — fast iteration on
ingestion / chunking / embedder changes without an Aura round-trip per upsert.
Teams switch the `LIGHTRAG_VECTOR_STORAGE` env var between `NanoVectorDBStorage`
(dev) and `Neo4JVectorStorage` (production / CI / paper-track eval).

## What is in scope of this ADR

- The architectural commitment: production = Aura-native vectors.
- An interim hygiene Make target (`lightrag-cache-reset`) that prevents the
  embedding-dim drift from silently recurring while the full migration is in
  flight.
- Documenting the canonical `WORKING_DIR` so the dev cache lives in exactly
  one place.

## What is NOT in scope of this ADR

- The actual `Neo4JVectorStorage` implementation (LightRAG ships none today —
  vector storages exposed are NanoVectorDB, Milvus, PGVector, Faiss, Qdrant,
  Mongo, OpenSearch). Building it is its own focused PR (Subsystem A++ work,
  ~1 day estimate including tests and migration). Tracked separately.
- Migration of the existing 9460 cached entity vectors. They were generated
  at 768-dim from `nomic-embed-text` and are obsolete under the 2048-dim
  Nemotron embedder. Re-embedding is part of the production move.
- Choice of similarity function (cosine vs euclidean vs dot). Defer to the
  `Neo4JVectorStorage` PR; default to cosine pending benchmarks.

## Consequences

- **Eval window (v1):** The eval can run with an empty NanoVectorDB cache;
  vector retrieval returns nothing, graph retrieval works fully. For the
  v1 paper claim (KG-grounded HDI recall, provenance, bilingual), graph
  retrieval is the dominant signal — vector retrieval primarily feeds
  semantic similarity over chunks, which we do not measure in v1 metrics.
  This is acceptable.
- **Operational:** Until `Neo4JVectorStorage` lands, the eval's vector
  retrieval is a no-op. Document in the run manifest so reviewers can tell.
- **Migration cost when `Neo4JVectorStorage` lands:** Re-embed 24,848
  nodes + 57,199 rels + ~445 chunks = ~82K embeddings. At free-tier
  OpenRouter Nemotron Embed VL 1B (no published rate limit), realistic
  throughput is ~5–10 embeddings/sec → 2–5 hours. Plan for an off-hours
  one-shot.
- **Reversal cost:** Low. `LIGHTRAG_VECTOR_STORAGE` is a config flag.
  Switching back to NanoVectorDB requires re-populating the local cache.
- **Vendor lock-in:** Increased on Neo4j. We are already locked in on the
  graph side; the marginal cost of locking in vectors is small relative to
  the consistency and access-control gains.

## Implementation phasing

| Phase | Deliverable | Status |
|---|---|---|
| **D5+** | `make lightrag-cache-reset` + dim-check guard + canonical `WORKING_DIR` | ✅ landed |
| **Storage class** | `ScopedNeo4JVectorStorage` subclass of `BaseVectorStorage`; one synthetic-node label per LightRAG namespace (`:VectorEntity` / `:VectorRelationship` / `:VectorChunk`); native Neo4j 5.13+ vector index per namespace; `db.index.vector.queryNodes()` retrieval; scope filter honored on every read; idempotent MERGE on `(id, workspace)`. Registered in both `STORAGES` and `STORAGE_IMPLEMENTATIONS`. 20 unit tests pass. `config_local.env` updated to `LIGHTRAG_VECTOR_STORAGE=ScopedNeo4JVectorStorage`. | ✅ landed 2026-04-29 |
| **Re-embed migration** | Embed all 166K Aura entities/relationships/chunks; populate vector indexes. Confirmed runnable on the free `nvidia/llama-nemotron-embed-vl-1b-v2:free` embedder — the embeddings endpoint has its own quota, separate from the 20 RPM chat-endpoint cap. Sustained 5–7 entities/sec at 16-text batches, ~9-hour wall-clock for the full 166K. Tracked as Task #11. | ⏳ in flight 2026-04-29 (free-tier OpenRouter) |
| **Production rollout** | Update `config_production.env`; deprecate `NanoVectorDBStorage` from production deploys; document the swap to local NanoVectorDB for dev iteration via env override. | follow-up |

## References

- Neo4j vector index docs: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- LightRAG storage interface: `lightrag/base.py::BaseVectorStorage`
- Existing scoped graph storage (template for the vector subclass): `shrine-diet-bioactivity/lightrag/scoped_neo4j_storage.py`
- v1 post-mortem §9c (which surfaced this need): `research-journal/shared/2026-04-26-v1-postmortem-and-next-steps.md`
