"""
Tenant-scoped Neo4j storage for LightRAG.

Subclasses ``lightrag.kg.neo4j_impl.Neo4JStorage`` and overrides every
read method to inject ``WHERE <n>.scope IN $scope_filter`` (plus
matching predicates on edge / endpoint scope). Writes are **not**
filtered — tenant ingestion must be able to insert new tenant-scoped
nodes and edges.

Scope filter comes from :mod:`scope_context` (a ``ContextVar`` set by
``scoped_server.py`` per request). Default is ``("shared",)`` — missing
context falls back to the public KG.

Register via LightRAG constructor::

    from lightrag import LightRAG
    from scoped_neo4j_storage import ScopedNeo4JStorage

    rag = LightRAG(graph_storage="ScopedNeo4JStorage", ...)

Or by directly passing the class if your LightRAG version supports it.

Filter semantics (for every read):

- Node reads: ``n.scope IN $scope_filter``
- Edge reads: ``start.scope IN $scope_filter``
    ``AND end.scope IN $scope_filter``
    ``AND r.scope IN $scope_filter``
- Node-degree / node-edges: connected nodes *and* relationships filtered

Writes (``upsert_node``, ``upsert_edge``, ``delete_*``) are inherited
unchanged — the tenant ingestion API is responsible for stamping
``scope="tenant:<id>"`` on the payload it submits.
"""

from __future__ import annotations

from typing import Any

from lightrag.kg.neo4j_impl import READ_RETRY, Neo4JStorage
from lightrag.utils import logger

from scope_context import get_scope_filter


class ScopedNeo4JStorage(Neo4JStorage):
    """Neo4JStorage with WHERE-clause tenant filtering on all reads."""

    # ------------------------------------------------------------------
    # Node reads
    # ------------------------------------------------------------------

    @READ_RETRY
    async def get_node(self, node_id: str) -> dict[str, str] | None:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            try:
                query = (
                    f"MATCH (n:`{workspace_label}` {{entity_id: $entity_id}}) "
                    f"WHERE n.scope IN $scope_filter "
                    f"RETURN n"
                )
                result = await session.run(
                    query, entity_id=node_id, scope_filter=scopes
                )
                try:
                    records = await result.fetch(2)
                    if len(records) > 1:
                        logger.warning(
                            f"[{self.workspace}] Multiple nodes with label "
                            f"'{node_id}'. Using first."
                        )
                    if not records:
                        return None
                    node_dict = dict(records[0]["n"])
                    if "labels" in node_dict:
                        node_dict["labels"] = [
                            label
                            for label in node_dict["labels"]
                            if label != workspace_label
                        ]
                    return node_dict
                finally:
                    await result.consume()
            except Exception as e:
                logger.error(
                    f"[{self.workspace}] Error getting node '{node_id}': {e}"
                )
                raise

    @READ_RETRY
    async def get_nodes_batch(
        self, node_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $node_ids AS id
            MATCH (n:`{workspace_label}` {{entity_id: id}})
            WHERE n.scope IN $scope_filter
            RETURN n.entity_id AS entity_id, n
            """
            result = await session.run(
                query, node_ids=node_ids, scope_filter=scopes
            )
            nodes: dict[str, dict[str, Any]] = {}
            async for record in result:
                entity_id = record["entity_id"]
                node_dict = dict(record["n"])
                if "labels" in node_dict:
                    node_dict["labels"] = [
                        label
                        for label in node_dict["labels"]
                        if label != workspace_label
                    ]
                nodes[entity_id] = node_dict
            await result.consume()
            return nodes

    @READ_RETRY
    async def node_degree(self, node_id: str) -> int:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            try:
                query = f"""
                MATCH (n:`{workspace_label}` {{entity_id: $entity_id}})
                WHERE n.scope IN $scope_filter
                OPTIONAL MATCH (n)-[r]-(m)
                WHERE r.scope IN $scope_filter
                  AND m.scope IN $scope_filter
                RETURN COUNT(r) AS degree
                """
                result = await session.run(
                    query, entity_id=node_id, scope_filter=scopes
                )
                try:
                    record = await result.single()
                    if not record:
                        return 0
                    return int(record["degree"])
                finally:
                    await result.consume()
            except Exception as e:
                logger.error(
                    f"[{self.workspace}] Error getting degree for '{node_id}': {e}"
                )
                raise

    @READ_RETRY
    async def node_degrees_batch(self, node_ids: list[str]) -> dict[str, int]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $node_ids AS id
            MATCH (n:`{workspace_label}` {{entity_id: id}})
            WHERE n.scope IN $scope_filter
            OPTIONAL MATCH (n)-[r]-(m)
            WHERE r.scope IN $scope_filter AND m.scope IN $scope_filter
            RETURN n.entity_id AS entity_id, COUNT(r) AS degree
            """
            result = await session.run(
                query, node_ids=node_ids, scope_filter=scopes
            )
            degrees: dict[str, int] = {}
            async for record in result:
                degrees[record["entity_id"]] = int(record["degree"])
            await result.consume()
            for nid in node_ids:
                degrees.setdefault(nid, 0)
            return degrees

    # ------------------------------------------------------------------
    # Edge reads
    # ------------------------------------------------------------------

    @READ_RETRY
    async def get_edge(
        self, source_node_id: str, target_node_id: str
    ) -> dict[str, str] | None:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        try:
            async with self._driver.session(
                database=self._DATABASE, default_access_mode="READ"
            ) as session:
                query = f"""
                MATCH (start:`{workspace_label}` {{entity_id: $src}})
                      -[r]-
                      (end:`{workspace_label}` {{entity_id: $tgt}})
                WHERE start.scope IN $scope_filter
                  AND end.scope IN $scope_filter
                  AND r.scope IN $scope_filter
                RETURN properties(r) AS edge_properties
                """
                result = await session.run(
                    query,
                    src=source_node_id,
                    tgt=target_node_id,
                    scope_filter=scopes,
                )
                try:
                    records = await result.fetch(2)
                    if len(records) > 1:
                        logger.warning(
                            f"[{self.workspace}] Multiple edges "
                            f"'{source_node_id}' → '{target_node_id}'. Using first."
                        )
                    if not records:
                        return None
                    edge_result = dict(records[0]["edge_properties"])
                    defaults = {
                        "weight": 1.0,
                        "source_id": None,
                        "description": None,
                        "keywords": None,
                    }
                    for k, v in defaults.items():
                        edge_result.setdefault(k, v)
                    return edge_result
                finally:
                    await result.consume()
        except Exception as e:
            logger.error(
                f"[{self.workspace}] Error getting edge "
                f"'{source_node_id}' → '{target_node_id}': {e}"
            )
            raise

    @READ_RETRY
    async def get_edges_batch(
        self, pairs: list[dict[str, str]]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $pairs AS pair
            MATCH (start:`{workspace_label}` {{entity_id: pair.src}})
                  -[r]-
                  (end:`{workspace_label}` {{entity_id: pair.tgt}})
            WHERE start.scope IN $scope_filter
              AND end.scope IN $scope_filter
              AND r.scope IN $scope_filter
            RETURN pair.src AS src, pair.tgt AS tgt,
                   properties(r) AS edge_properties
            """
            payload = [{"src": p["src"], "tgt": p["tgt"]} for p in pairs]
            result = await session.run(
                query, pairs=payload, scope_filter=scopes
            )
            edges: dict[tuple[str, str], dict[str, Any]] = {}
            async for record in result:
                edges[(record["src"], record["tgt"])] = dict(
                    record["edge_properties"]
                )
            await result.consume()
            return edges

    @READ_RETRY
    async def get_node_edges(
        self, source_node_id: str
    ) -> list[tuple[str, str]] | None:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            MATCH (n:`{workspace_label}` {{entity_id: $entity_id}})
                  -[r]-
                  (m:`{workspace_label}`)
            WHERE n.scope IN $scope_filter
              AND m.scope IN $scope_filter
              AND r.scope IN $scope_filter
            RETURN n.entity_id AS src, m.entity_id AS tgt
            """
            result = await session.run(
                query, entity_id=source_node_id, scope_filter=scopes
            )
            edges: list[tuple[str, str]] = []
            async for record in result:
                edges.append((record["src"], record["tgt"]))
            await result.consume()
            return edges if edges else None

    @READ_RETRY
    async def get_nodes_edges_batch(
        self, node_ids: list[str]
    ) -> dict[str, list[tuple[str, str]]]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            UNWIND $node_ids AS id
            MATCH (n:`{workspace_label}` {{entity_id: id}})
                  -[r]-
                  (m:`{workspace_label}`)
            WHERE n.scope IN $scope_filter
              AND m.scope IN $scope_filter
              AND r.scope IN $scope_filter
            RETURN id AS src_id, m.entity_id AS tgt_id
            """
            result = await session.run(
                query, node_ids=node_ids, scope_filter=scopes
            )
            out: dict[str, list[tuple[str, str]]] = {nid: [] for nid in node_ids}
            async for record in result:
                out[record["src_id"]].append(
                    (record["src_id"], record["tgt_id"])
                )
            await result.consume()
            return out

    # ------------------------------------------------------------------
    # Label enumeration
    # ------------------------------------------------------------------

    @READ_RETRY
    async def get_all_labels(self) -> list[str]:
        workspace_label = self._get_workspace_label()
        scopes = get_scope_filter()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            query = f"""
            MATCH (n:`{workspace_label}`)
            WHERE n.scope IN $scope_filter
            RETURN DISTINCT n.entity_id AS entity_id
            ORDER BY entity_id
            """
            result = await session.run(query, scope_filter=scopes)
            labels: list[str] = []
            async for record in result:
                if record["entity_id"]:
                    labels.append(record["entity_id"])
            await result.consume()
            return labels
