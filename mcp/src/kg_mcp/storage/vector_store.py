"""VectorStore protocol — the only contract the kg-mcp gateway depends on.

Why a protocol (not an ABC): callers want duck-typing for testability —
a tiny ``FakeVectorStore`` in unit tests should pass instance checks
without subclassing. ``typing.Protocol`` gives that without runtime
inheritance overhead. Implementations live in sibling modules.

Single-collection design (per prototype-v0 decision): all entities live in
one Milvus collection; the ``scope`` field is metadata used by callers to
filter (matches the scoped_server's Aura-side tenant scoping). Equality
metric is ``COSINE`` — the embed-time normalisation in
``embed_clinical_entities.py`` already targets unit-norm vectors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class VectorEntry:
    """One entity-with-embedding bound for the vector store.

    Field shape mirrors NanoVectorDB's per-entry record so the migration
    script (Phase 4) maps 1:1 without an intermediate schema:

      ``entity_id``    — primary key; format ``ent-{md5hash}``
      ``vector``       — 2048-dim float32 list/array
      ``entity_name``  — display name; never used as a key
      ``content``      — full description text (for re-embed sanity checks)
      ``source_id``    — chunk identifier, joins to LightRAG chunks vdb
      ``file_path``    — provenance tag (``clinical_anchors`` in current data)
      ``scope``        — tenant scope (defaults to ``shared``)
      ``metadata``     — open-ended per-impl extensions (rarely populated)
    """

    entity_id: str
    vector: Sequence[float]
    entity_name: str = ""
    content: str = ""
    source_id: str = ""
    file_path: str = ""
    scope: str = "shared"
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VectorHit:
    """A single result row returned by :meth:`VectorStore.query`.

    ``score`` is the raw similarity returned by the impl (cosine in
    [0.0, 1.0] for the default metric). The full :class:`VectorEntry`
    is returned so callers can read provenance fields without a second
    lookup.
    """

    entry: VectorEntry
    score: float


@runtime_checkable
class VectorStore(Protocol):
    """The minimal surface every implementation must provide.

    Methods are sync for now — both NanoVectorDB (local file) and pymilvus
    expose sync APIs, and the gateway wraps the whole call in an asyncio
    thread pool. Switch to async if a future impl needs it.
    """

    def upsert(self, entries: Iterable[VectorEntry]) -> int:
        """Insert-or-replace ``entries`` keyed by ``entity_id``.

        Returns the number of records written (post-dedup-by-key).
        Implementations MUST be idempotent: calling ``upsert`` twice with
        the same payload leaves the store in the same observable state.
        """
        ...

    def query(
        self,
        vector: Sequence[float],
        *,
        top_k: int = 5,
        scope: str | None = None,
    ) -> list[VectorHit]:
        """Return the top-k nearest neighbours by cosine similarity.

        ``scope`` filters at the metadata level (``shared`` if None).
        Implementations MUST return an empty list when the store is empty,
        never raise.
        """
        ...

    def count(self) -> int:
        """Total entity count across all scopes — cheap monitoring probe."""
        ...

    def drop(self) -> None:
        """Wipe the underlying collection. Test / migration use only."""
        ...
