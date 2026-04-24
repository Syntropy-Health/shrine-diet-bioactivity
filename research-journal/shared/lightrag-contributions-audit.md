# LightRAG Contributions Audit

> Distilled from codebase-analyst audit 2026-04-22. Anchored to `lightrag/` submodule head at the audit time. For the paper's Methods section and the companion-paper D-list.

## Substrate citation

LightRAG: Guo, Z., Xia, L., Yu, Y., Ao, T., & Huang, C. (2025). *LightRAG: Simple and Fast Retrieval-Augmented Generation*. Findings of the Association for Computational Linguistics: EMNLP 2025, pp. 10746–10761. arXiv:2410.05779. ACL Anthology: [2025.findings-emnlp.568](https://aclanthology.org/2025.findings-emnlp.568/). Repo: [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG).

## Methods-section positioning paragraph

> We use LightRAG (Guo et al., 2025) as the semantic knowledge graph substrate, employing its `ainsert_custom_kg` API for deterministic, zero-LLM-cost ingestion of seven structured biomedical datasets (Duke Phytochemical, FooDB, CMAUP, CTD, TTD, OpenNutrition, SymMap, HERB 2.0) and its five query modes (local, global, hybrid, naive, mix) for downstream retrieval. On top of the base framework we contribute three extensions: (1) `ScopedNeo4JStorage`, a subclass of LightRAG's Neo4j storage backend that injects per-request tenant predicates into every Cypher read via Python's `ContextVar` mechanism, enabling multi-tenant isolation on a shared graph without modifying LightRAG's query API; (2) a startup preflight guard and cross-tenant isolation canary that together provide runtime verification of scope correctness through LightRAG's full retrieval pipeline including LLM synthesis; and (3) a two-tier entity taxonomy (six shared biomedical types populated from structured ETL, four clinical-practice types populated via tenant API) that separates curated public knowledge from organization-private clinical data within the same knowledge graph instance.

## Confirmed novel extensions (companion paper D-list)

### D-ext-1 — `ScopedNeo4JStorage` + `ContextVar` pattern

- Subclass of `lightrag.kg.neo4j_impl.Neo4JStorage` that overrides every read method to inject `WHERE n.scope IN $scope_filter` on Cypher.
- Per-request tenant context via Python `ContextVar`.
- Files: `shrine-diet-bioactivity/lightrag/scoped_neo4j_storage.py`, `scope_context.py`, `scoped_server.py`.
- Novelty: upstream LightRAG has no tenant concept (GitHub #310, #2133). Extension is additive; does not modify LightRAG query API.

### D-ext-2 — Preflight + isolation canary

- `bootstrap_scope.py` retroactively stamps `scope='shared'` on untagged nodes and indexes `scope` property.
- `_preflight_scope_check()` at server startup refuses to serve until migration is complete.
- `canary_smoke_test.py` exercises 4 isolation surfaces (query synthesis, subgraph retrieval, label enumeration, write scope enforcement) with a directly-injected sentinel.

### D-ext-3 — Two-tier entity taxonomy

- Shared tier (ingested from SQLite): Herb, Compound, Food, Target, Disease, Symptom.
- Tenant tier (via `POST /documents/custom_kg`): Protocol, Intervention, Outcome, Biomarker.
- `fix_unknown_entities.py` rule-based classifier fills the `entity_type=UNKNOWN` stubs that `ainsert_custom_kg` creates when a relationship edge references an un-ingested entity.

## Patterns worth describing but not novel

- **Structured-first ingestion via `ainsert_custom_kg`.** The API exists upstream but no peer-reviewed paper has published this pattern. Worth claiming as "first peer-reviewed demonstration" in the companion paper (D2).
- **Scoped FastAPI wrapper** — mirrors upstream routes with added scope-filter enforcement on ingest payload rewriting.
- **Dual config profiles** (Ollama local; OpenAI + Jina multilingual production) — configuration, not novel.
- **5-tool MCP thin adapter** (TypeScript) — architectural choice with rationale, not a new primitive.

## Gaps (what is NOT customized)

- Vector-side tenant isolation is absent; embeddings are a shared index.
- LLM extraction prompts are upstream defaults (no domain tuning for Chinese TCM extraction).
- Query modes (local/global/hybrid/naive/mix) are vanilla.
- Chunking parameters are upstream defaults.

## Upstream behavior worth flagging

`ainsert_custom_kg` auto-creates stub nodes with `entity_type="UNKNOWN"` when a relationship references an un-ingested entity (upstream `lightrag.py:2470-2484`). In cross-batch ingestion this produces unclassified stubs that must be post-processed with a classifier. This is not a bug in our code; it is a documented upstream limitation.

## Key files (for reviewer-accessible appendix)

| File | Role |
|---|---|
| `lightrag/scoped_neo4j_storage.py` | Multi-tenant storage extension |
| `lightrag/scope_context.py` | `ContextVar` plumbing |
| `lightrag/scoped_server.py` | Scoped FastAPI wrapper |
| `lightrag/bootstrap_scope.py` | Migration + preflight guard |
| `lightrag/canary_smoke_test.py` | Isolation canary |
| `lightrag/entity_schema.py` | Taxonomy + description generators |
| `lightrag/ingest_unified.py` | Structured-first ingestion pipeline |
| `lightrag/fix_unknown_entities.py` | Rule-based stub classifier |
| `scripts/build-food-bridge.ts` | 5-strategy cross-ontology matcher |
