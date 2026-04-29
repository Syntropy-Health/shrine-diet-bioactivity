# Scope State Snapshot

_Generated 2026-04-29T09:29:31.928331+00:00_  
_Workspace: `unified_diet_kg`_  

**Policy:** open-source data ingests under `scope='shared'`. 
Tenant-scoped data uses `scope='tenant:<slug>'`. The scoped LightRAG 
server enforces these scopes on every read. This snapshot is the 
audit baseline — any deviation from the policy that this report can 
see (NULL scopes, unexpected tenant tags) is a defect.

## Health check

- Untagged nodes (scope IS NULL): **0** _(must be 0)_
- Untagged relationships (scope IS NULL): **0** _(must be 0)_
- Bootstrap status: ✅ clean

## Node count by scope

| scope | nodes |
|---|---|
| shared | 161181 |

## Relationship count by scope

| scope | rels |
|---|---|
| shared | 4268469 |

## Nodes — scope × source prefix

| scope | source_prefix | nodes |
|---|---|---|
| shared | duke | 105191 |
| shared | symmap | 50652 |
| shared | herb2 | 5300 |
| shared | chunk-4a8b37f00a98d1be712299e1fb39212f | 38 |

## Relationships — scope × type

| scope | rel_type | rels |
|---|---|---|
| shared | FOUND_IN_FOOD | 4134251 |
| shared | CONTAINS_COMPOUND | 85186 |
| shared | TREATS_SYMPTOM | 41823 |
| shared | TARGETS_PROTEIN | 6465 |
| shared | ASSOCIATED_WITH_DISEASE | 644 |
| shared | INTERACTS_WITH | 50 |
| shared | DIRECTED | 50 |

## Scope indexes

| name | entityType | labelsOrTypes | properties | state |
|---|---|---|---|---|
| shared_diet_kg_edge_scope_associated_with_disease | RELATIONSHIP | ['ASSOCIATED_WITH_DISEASE'] | ['scope'] | ONLINE |
| shared_diet_kg_edge_scope_contains_compound | RELATIONSHIP | ['CONTAINS_COMPOUND'] | ['scope'] | ONLINE |
| shared_diet_kg_edge_scope_directed | RELATIONSHIP | ['DIRECTED'] | ['scope'] | ONLINE |
| shared_diet_kg_edge_scope_found_in_food | RELATIONSHIP | ['FOUND_IN_FOOD'] | ['scope'] | ONLINE |
| shared_diet_kg_edge_scope_interacts_with | RELATIONSHIP | ['INTERACTS_WITH'] | ['scope'] | ONLINE |
| shared_diet_kg_edge_scope_targets_protein | RELATIONSHIP | ['TARGETS_PROTEIN'] | ['scope'] | ONLINE |
| shared_diet_kg_edge_scope_treats_symptom | RELATIONSHIP | ['TREATS_SYMPTOM'] | ['scope'] | ONLINE |
| shared_diet_kg_node_scope | NODE | ['unified_diet_kg'] | ['scope'] | ONLINE |

## Idempotency contract

Future ingestion must:
1. Set `scope='shared'` (or `tenant:<slug>`) on every node and edge it writes.
2. Use `MERGE` (not `CREATE`) on `(entity_id)` for nodes and `(src, tgt, rel_type)` for edges.
3. Re-running the same job over the same input must not increase counts in this snapshot.

If a new dataset is being added: append a row to `data/manifest.yaml` 
with the source slug, expected entity/edge counts, and primary join key. 
Then run a fresh snapshot and diff against the prior one — only the 
expected source-prefix counts should grow.
