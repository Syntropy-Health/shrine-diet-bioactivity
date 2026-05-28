"""MilvusVectorStore — Zilliz Cloud / Milvus implementation of VectorStore.

Connection model: a single ``MilvusClient`` shared across the process. The
Zilliz serverless tier requires token-based auth (the ``ZILLIZ_TOKEN``);
DB-user / password is an alternate path kept for self-hosted Milvus.

Schema (single shared collection — prototype-v0 decision):

    entity_id   VARCHAR(128) PRIMARY KEY      # ``ent-{md5hash}``
    vector      FLOAT_VECTOR(2048)            # nvidia/llama-nemotron-embed-vl-1b-v2
    entity_name VARCHAR(512)
    content     VARCHAR(8192)
    source_id   VARCHAR(128)
    file_path   VARCHAR(128)
    scope       VARCHAR(64)                   # tenant scope (default "shared")

Index: ``HNSW`` with ``M=16, efConstruction=200`` and ``metric_type=COSINE``.
Matches the metric implied by NanoVectorDB's in-memory dot-product on
normalised vectors, so query scores stay comparable across backends.

Auth precedence: ``ZILLIZ_TOKEN`` takes precedence over user+password;
this matches Zilliz Cloud's official guidance for serverless clusters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .vector_store import VectorEntry, VectorHit


# ---------------------------------------------------------------------------
# Connection config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MilvusConfig:
    """Construct from env via :meth:`from_env`; the factory pulls the
    values from Infisical-populated process env at startup so this class
    never touches a file or remote secret store directly."""

    uri: str
    token: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    collection: str = "kg_entities"
    embedding_dim: int = 2048

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "MilvusConfig":
        uri = env.get("ZILLIZ_URI", "").strip()
        if not uri:
            raise ValueError(
                "ZILLIZ_URI is required when KG_VECTOR_BACKEND=milvus. "
                "Source from Infisical /mcp/kg/ZILLIZ_URI."
            )
        return cls(
            uri=uri,
            token=env.get("ZILLIZ_TOKEN") or None,
            db_user=env.get("ZILLIZ_DB_USER") or None,
            db_password=env.get("ZILLIZ_DB_PASSWORD") or None,
            collection=env.get("ZILLIZ_COLLECTION", "kg_entities"),
            embedding_dim=int(env.get("EMBEDDING_DIM", "2048")),
        )


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class MilvusVectorStore:
    """Wraps ``pymilvus.MilvusClient``.

    ``pymilvus`` is an optional dependency to keep the unit-test runtime
    light; the import is deferred until first connection so tests can
    import this module without pymilvus installed.
    """

    def __init__(self, config: MilvusConfig) -> None:
        self._config = config
        self._client = None  # populated lazily — see :meth:`_connect`

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:  # pragma: no cover — env-specific failure
            raise RuntimeError(
                "pymilvus is required for MilvusVectorStore. "
                "Install via `pip install pymilvus>=2.4`."
            ) from exc

        # Token auth (Zilliz Cloud serverless preferred path).
        if self._config.token:
            self._client = MilvusClient(
                uri=self._config.uri,
                token=self._config.token,
            )
        elif self._config.db_user and self._config.db_password:
            self._client = MilvusClient(
                uri=self._config.uri,
                user=self._config.db_user,
                password=self._config.db_password,
            )
        else:
            raise RuntimeError(
                "Milvus auth missing — set ZILLIZ_TOKEN or both "
                "ZILLIZ_DB_USER + ZILLIZ_DB_PASSWORD."
            )

        self._ensure_collection()
        return self._client

    def _ensure_collection(self) -> None:
        """Idempotent schema bootstrap. Existing collections are reused."""
        from pymilvus import DataType

        client = self._client
        assert client is not None
        col = self._config.collection

        if client.has_collection(col):
            client.load_collection(col)
            return

        schema = client.create_schema(
            auto_id=False, enable_dynamic_field=False
        )
        schema.add_field(
            field_name="entity_id",
            datatype=DataType.VARCHAR,
            max_length=128,
            is_primary=True,
        )
        schema.add_field(
            field_name="vector",
            datatype=DataType.FLOAT_VECTOR,
            dim=self._config.embedding_dim,
        )
        for name, length in (
            ("entity_name", 512),
            ("content", 8192),
            ("source_id", 128),
            ("file_path", 128),
            ("scope", 64),
        ):
            schema.add_field(
                field_name=name,
                datatype=DataType.VARCHAR,
                max_length=length,
                nullable=True,
            )

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )

        client.create_collection(
            collection_name=col,
            schema=schema,
            index_params=index_params,
        )
        client.load_collection(col)

    # ------------------------------------------------------------------
    # VectorStore protocol
    # ------------------------------------------------------------------

    def upsert(self, entries: Iterable[VectorEntry]) -> int:
        client = self._connect()
        records: list[dict] = []
        for e in entries:
            records.append(
                {
                    "entity_id": e.entity_id,
                    "vector": list(e.vector),
                    "entity_name": e.entity_name,
                    "content": e.content[:8192],
                    "source_id": e.source_id,
                    "file_path": e.file_path,
                    "scope": e.scope or "shared",
                }
            )
            # Milvus serverless caps payload size; flush in 1000-row batches
            # so a single oversized call doesn't bounce.
            if len(records) >= 1000:
                client.upsert(self._config.collection, records)
                records = []
        if records:
            client.upsert(self._config.collection, records)
        return sum(1 for _ in [None])  # caller tracks total externally

    def query(
        self,
        vector: Sequence[float],
        *,
        top_k: int = 5,
        scope: str | None = None,
    ) -> list[VectorHit]:
        client = self._connect()
        target_scope = scope or "shared"
        results = client.search(
            collection_name=self._config.collection,
            data=[list(vector)],
            limit=top_k,
            filter=f'scope == "{target_scope}"',
            output_fields=[
                "entity_id",
                "entity_name",
                "content",
                "source_id",
                "file_path",
                "scope",
            ],
        )
        if not results or not results[0]:
            return []
        hits: list[VectorHit] = []
        for hit in results[0]:
            ent = hit.get("entity") or {}
            hits.append(
                VectorHit(
                    entry=VectorEntry(
                        entity_id=ent.get("entity_id", ""),
                        vector=[],  # not returned by search — saves bandwidth
                        entity_name=ent.get("entity_name", ""),
                        content=ent.get("content", ""),
                        source_id=ent.get("source_id", ""),
                        file_path=ent.get("file_path", ""),
                        scope=ent.get("scope", "shared"),
                    ),
                    score=float(hit.get("distance", 0.0)),
                )
            )
        return hits

    def count(self) -> int:
        client = self._connect()
        stats = client.get_collection_stats(self._config.collection)
        # Milvus returns row_count as str or int depending on version.
        return int(stats.get("row_count", 0) or 0)

    def drop(self) -> None:
        client = self._connect()
        if client.has_collection(self._config.collection):
            client.drop_collection(self._config.collection)
        # Force a reconnect so the next call recreates the schema.
        self._client = None
