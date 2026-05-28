"""Contract tests for VectorStore implementations.

Each implementation is run through the same suite via parametrize; a
``FakeVectorStore`` lives alongside the tests so the contract is
self-checked without needing live infra. Milvus is exercised through the
adapter's *connection-deferred* path (no pymilvus install required at
import time); behavioural Milvus tests live in
``mcp/tests/integration/`` (Phase 5 PR3) and are gated by ZILLIZ_URI.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Iterable, Sequence

import pytest

from kg_mcp.storage import VectorEntry, VectorHit, VectorStore
from kg_mcp.storage.milvus import MilvusConfig, MilvusVectorStore
from kg_mcp.storage.nano import NanoVectorDBVectorStore


pytestmark = [pytest.mark.unit]


# ─── Fake implementation — proves the protocol is usable from outside ──────


class FakeVectorStore:
    """In-memory store used in unit tests of consumers (not just the
    contract suite). Naive O(n) cosine — fine for fixtures."""

    def __init__(self) -> None:
        self._entries: dict[str, VectorEntry] = {}

    def upsert(self, entries: Iterable[VectorEntry]) -> int:
        n = 0
        for e in entries:
            self._entries[e.entity_id] = e
            n += 1
        return n

    def query(
        self,
        vector: Sequence[float],
        *,
        top_k: int = 5,
        scope: str | None = None,
    ) -> list[VectorHit]:
        target = scope or "shared"
        results: list[tuple[float, VectorEntry]] = []
        for e in self._entries.values():
            if e.scope != target:
                continue
            s = sum(a * b for a, b in zip(vector, e.vector))
            results.append((s, e))
        results.sort(key=lambda kv: kv[0], reverse=True)
        return [VectorHit(entry=e, score=s) for s, e in results[:top_k]]

    def count(self) -> int:
        return len(self._entries)

    def drop(self) -> None:
        self._entries.clear()


# ─── Protocol surface ─────────────────────────────────────────────────────


def test_fake_satisfies_vector_store_protocol():
    """Lock the protocol-typing contract: any duck-typed impl is accepted."""
    store: VectorStore = FakeVectorStore()
    assert isinstance(store, VectorStore)


def test_nano_satisfies_protocol(tmp_path):
    store: VectorStore = NanoVectorDBVectorStore(tmp_path / "missing.json")
    assert isinstance(store, VectorStore)


def test_milvus_satisfies_protocol():
    store: VectorStore = MilvusVectorStore(
        MilvusConfig(uri="https://placeholder.invalid", token="t")
    )
    assert isinstance(store, VectorStore)


# ─── Shared behaviour suite ───────────────────────────────────────────────


def _seed(store: VectorStore) -> None:
    store.upsert([
        VectorEntry(
            entity_id="ent-alpha",
            vector=[1.0, 0.0, 0.0],
            entity_name="Alpha",
            content="alpha entity",
            source_id="duke:treats_symptom",
            file_path="clinical_anchors",
            scope="shared",
        ),
        VectorEntry(
            entity_id="ent-beta",
            vector=[0.0, 1.0, 0.0],
            entity_name="Beta",
            content="beta entity",
            source_id="cmaup:target_disease",
            file_path="clinical_anchors",
            scope="shared",
        ),
        VectorEntry(
            entity_id="ent-gamma-private",
            vector=[0.0, 0.0, 1.0],
            entity_name="Gamma",
            content="private entity",
            source_id="herb2:herb_disease",
            file_path="clinical_anchors",
            scope="tenant-foo",
        ),
    ])


# Test against impls that don't need network. Nano gets a per-test
# tmp_path so persistence is opt-in via the fixture wrapper below.


def _nano(tmp_path: Path) -> NanoVectorDBVectorStore:
    return NanoVectorDBVectorStore(tmp_path / "fixture.json")


@pytest.fixture(params=["fake", "nano"])
def store(request, tmp_path) -> VectorStore:
    if request.param == "fake":
        return FakeVectorStore()
    return _nano(tmp_path)


class TestVectorStoreContract:
    def test_count_zero_on_fresh_store(self, store: VectorStore) -> None:
        assert store.count() == 0

    def test_upsert_then_count(self, store: VectorStore) -> None:
        _seed(store)
        assert store.count() == 3

    def test_query_returns_nearest_neighbour(self, store: VectorStore) -> None:
        _seed(store)
        hits = store.query([1.0, 0.0, 0.0], top_k=1)
        assert len(hits) == 1
        assert hits[0].entry.entity_id == "ent-alpha"
        # Cosine of identical unit vectors should be ~1.0.
        assert hits[0].score == pytest.approx(1.0, abs=1e-6)

    def test_query_respects_top_k(self, store: VectorStore) -> None:
        _seed(store)
        # Vector midway between alpha + beta — both should rank above
        # the private gamma.
        hits = store.query([0.7, 0.7, 0.0], top_k=2)
        ids = [h.entry.entity_id for h in hits]
        assert set(ids) == {"ent-alpha", "ent-beta"}

    def test_query_returns_empty_on_empty_store(self, store: VectorStore) -> None:
        assert store.query([1.0, 0.0, 0.0]) == []

    def test_query_scope_isolation(self, store: VectorStore) -> None:
        """A tenant-scoped entity must not surface in a `shared` query."""
        _seed(store)
        shared_ids = {
            h.entry.entity_id
            for h in store.query([0.0, 0.0, 1.0], top_k=5, scope="shared")
        }
        assert "ent-gamma-private" not in shared_ids
        tenant_ids = {
            h.entry.entity_id
            for h in store.query([0.0, 0.0, 1.0], top_k=5, scope="tenant-foo")
        }
        assert "ent-gamma-private" in tenant_ids

    def test_upsert_is_idempotent(self, store: VectorStore) -> None:
        _seed(store)
        _seed(store)  # second insert overwrites; doesn't add
        assert store.count() == 3

    def test_drop_clears_store(self, store: VectorStore) -> None:
        _seed(store)
        store.drop()
        assert store.count() == 0
        assert store.query([1.0, 0.0, 0.0]) == []


# ─── Nano-specific: file format round-trip ────────────────────────────────


class TestNanoFileFormat:
    """The migration script (Phase 4 PR2) depends on Nano being able to
    read the live ``vdb_entities.json`` shape. Pin the format here so a
    LightRAG upgrade that changes the on-disk schema fails loudly."""

    def test_reads_lightrag_nano_format(self, tmp_path: Path) -> None:
        # Two 4-dim entries, base64-packed float32 row-major.
        floats = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        blob = struct.pack(f"<{len(floats)}f", *floats)
        import base64

        payload = {
            "embedding_dim": 4,
            "data": [
                {
                    "__id__": "ent-a",
                    "entity_name": "Alpha",
                    "content": "alpha",
                    "source_id": "duke:foo",
                    "file_path": "clinical_anchors",
                },
                {
                    "__id__": "ent-b",
                    "entity_name": "Beta",
                    "content": "beta",
                    "source_id": "duke:foo",
                    "file_path": "clinical_anchors",
                },
            ],
            "matrix": base64.b64encode(blob).decode("ascii"),
        }
        path = tmp_path / "vdb_entities.json"
        path.write_text(json.dumps(payload))

        store = NanoVectorDBVectorStore(path)
        assert store.count() == 2
        hits = store.query([1.0, 0.0, 0.0, 0.0], top_k=1)
        assert hits[0].entry.entity_id == "ent-a"
        assert hits[0].entry.source_id == "duke:foo"

    def test_persist_round_trip(self, tmp_path: Path) -> None:
        """Opt-in persistence: write, drop the in-memory store, re-open,
        confirm data was flushed to disk."""
        path = tmp_path / "vdb_entities.json"
        store = NanoVectorDBVectorStore(path, persist_on_upsert=True)
        store.upsert([
            VectorEntry(
                entity_id="ent-x",
                vector=[1.0, 0.0, 0.0, 0.0],
                entity_name="X",
                content="x",
            ),
        ])
        # Reload from disk; in-memory state is discarded.
        reopened = NanoVectorDBVectorStore(path)
        assert reopened.count() == 1


# ─── Milvus config — env wiring ───────────────────────────────────────────


class TestMilvusConfig:
    def test_from_env_requires_uri(self):
        with pytest.raises(ValueError, match="ZILLIZ_URI"):
            MilvusConfig.from_env({})

    def test_from_env_token_path(self):
        cfg = MilvusConfig.from_env(
            {"ZILLIZ_URI": "https://x.serverless.zilliz", "ZILLIZ_TOKEN": "tok"}
        )
        assert cfg.uri == "https://x.serverless.zilliz"
        assert cfg.token == "tok"
        assert cfg.db_user is None

    def test_from_env_db_password_path(self):
        cfg = MilvusConfig.from_env({
            "ZILLIZ_URI": "https://x.serverless.zilliz",
            "ZILLIZ_DB_USER": "u",
            "ZILLIZ_DB_PASSWORD": "p",
        })
        assert cfg.db_user == "u"
        assert cfg.db_password == "p"
        assert cfg.token is None

    def test_from_env_default_collection(self):
        cfg = MilvusConfig.from_env({
            "ZILLIZ_URI": "https://x.zilliz",
            "ZILLIZ_TOKEN": "t",
        })
        assert cfg.collection == "kg_entities"

    def test_from_env_custom_embedding_dim(self):
        cfg = MilvusConfig.from_env({
            "ZILLIZ_URI": "https://x.zilliz",
            "ZILLIZ_TOKEN": "t",
            "EMBEDDING_DIM": "3072",
        })
        assert cfg.embedding_dim == 3072
