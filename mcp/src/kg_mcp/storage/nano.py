"""NanoVectorDBVectorStore — wraps the local LightRAG NanoVectorDB files.

NanoVectorDB stores each collection as a single JSON document with:

    {
      "embedding_dim": int,                       # all vectors share this dim
      "data": [{"__id__": "ent-...", "entity_name": ..., ...}, ...],
      "matrix": "<base64-encoded float32 row-major>"
    }

The matrix is ``len(data) × embedding_dim`` float32, row-major. Each
``data[i]`` corresponds to row ``i`` of the matrix (the per-entry ``vector``
field also stored is a redundant base64 copy that we ignore).

This adapter is *read-only by default* — the source-of-truth for vector
writes in prototype-v0 is the migration script (Phase 4). ``upsert`` works
in memory and persists back to disk only if explicitly requested via
``persist_on_upsert=True`` at construction. This guard keeps the 413 MB
file from being silently rewritten in a test or accidental call.
"""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from .vector_store import VectorEntry, VectorHit


class NanoVectorDBVectorStore:
    """File-backed VectorStore reading LightRAG ``vdb_*.json``.

    Behaviour notes:

    * ``query`` does a brute-force cosine scan over the in-memory matrix.
      Acceptable at 26K × 2048 (~50 MB float32 → ~0.5 ms/query). If the
      collection grows past 100K, swap to a real index — or just use Milvus,
      which is what Phase 4 lands.
    * Vectors are L2-normalised on load so cosine reduces to a single dot
      product. We assume embed-time normalisation but enforce it on the read
      path so a non-normalised source file still yields well-scaled scores.
    """

    def __init__(
        self,
        path: Path,
        *,
        persist_on_upsert: bool = False,
    ) -> None:
        self._path = Path(path)
        self._persist_on_upsert = persist_on_upsert
        # Lazy-load: the 413 MB file should not be read at construction time
        # if a caller only wants ``count()``. Loading happens on first read.
        self._embedding_dim: int | None = None
        self._entries: list[VectorEntry] = []
        self._matrix: list[list[float]] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._path.exists():
            # Empty store — legal during fresh-cluster bring-up; query
            # returns []; upsert builds the in-memory state.
            self._embedding_dim = 0
            self._entries = []
            self._matrix = []
            self._loaded = True
            return

        raw = json.loads(self._path.read_text())
        self._embedding_dim = int(raw.get("embedding_dim") or 0)

        # Decode base64-packed float32 matrix.
        import struct

        matrix_b64 = raw.get("matrix") or ""
        if matrix_b64 and self._embedding_dim:
            blob = base64.b64decode(matrix_b64)
            n_floats = len(blob) // 4
            unpacked = struct.unpack(f"<{n_floats}f", blob)
            d = self._embedding_dim
            rows = [list(unpacked[i : i + d]) for i in range(0, n_floats, d)]
            self._matrix = [self._normalise(r) for r in rows]
        else:
            self._matrix = []

        data = raw.get("data", []) or []
        self._entries = [
            VectorEntry(
                entity_id=row.get("__id__", ""),
                vector=self._matrix[i] if i < len(self._matrix) else [],
                entity_name=row.get("entity_name", ""),
                content=row.get("content", ""),
                source_id=row.get("source_id", ""),
                file_path=row.get("file_path", ""),
                scope=row.get("scope", "shared"),
            )
            for i, row in enumerate(data)
        ]
        self._loaded = True

    @staticmethod
    def _normalise(v: Sequence[float]) -> list[float]:
        # Defensive normalisation — embed-time may or may not produce
        # unit-norm vectors depending on the model.
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0.0:
            return list(v)
        return [x / norm for x in v]

    # ------------------------------------------------------------------
    # VectorStore protocol
    # ------------------------------------------------------------------

    def upsert(self, entries: Iterable[VectorEntry]) -> int:
        self._ensure_loaded()
        by_id = {e.entity_id: i for i, e in enumerate(self._entries)}
        written = 0
        for entry in entries:
            norm_vec = self._normalise(entry.vector)
            new_entry = VectorEntry(
                entity_id=entry.entity_id,
                vector=norm_vec,
                entity_name=entry.entity_name,
                content=entry.content,
                source_id=entry.source_id,
                file_path=entry.file_path,
                scope=entry.scope,
                metadata=entry.metadata,
            )
            if entry.entity_id in by_id:
                idx = by_id[entry.entity_id]
                self._entries[idx] = new_entry
                self._matrix[idx] = norm_vec
            else:
                self._entries.append(new_entry)
                self._matrix.append(norm_vec)
                by_id[entry.entity_id] = len(self._entries) - 1
            written += 1
        if self._persist_on_upsert:
            self._persist()
        return written

    def query(
        self,
        vector: Sequence[float],
        *,
        top_k: int = 5,
        scope: str | None = None,
    ) -> list[VectorHit]:
        self._ensure_loaded()
        if not self._matrix:
            return []
        q = self._normalise(vector)
        # Filter scope first to skip work over unrelated entries.
        target_scope = scope or "shared"
        scored: list[tuple[float, int]] = []
        for i, entry in enumerate(self._entries):
            if entry.scope != target_scope:
                continue
            row = self._matrix[i]
            # Dot product on normalised vectors == cosine similarity.
            s = sum(a * b for a, b in zip(q, row))
            scored.append((s, i))
        scored.sort(key=lambda kv: kv[0], reverse=True)
        return [
            VectorHit(entry=self._entries[i], score=s)
            for s, i in scored[:top_k]
        ]

    def count(self) -> int:
        self._ensure_loaded()
        return len(self._entries)

    def drop(self) -> None:
        self._embedding_dim = 0
        self._entries = []
        self._matrix = []
        self._loaded = True
        if self._persist_on_upsert and self._path.exists():
            self._path.unlink()

    # ------------------------------------------------------------------
    # Persistence (only when persist_on_upsert=True)
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Re-serialise the in-memory state back to disk (atomic)."""
        import struct

        dim = self._embedding_dim or (
            len(self._matrix[0]) if self._matrix else 0
        )
        flat: list[float] = [x for row in self._matrix for x in row]
        blob = struct.pack(f"<{len(flat)}f", *flat) if flat else b""
        payload = {
            "embedding_dim": dim,
            "data": [
                {
                    "__id__": e.entity_id,
                    "entity_name": e.entity_name,
                    "content": e.content,
                    "source_id": e.source_id,
                    "file_path": e.file_path,
                    "scope": e.scope,
                }
                for e in self._entries
            ],
            "matrix": base64.b64encode(blob).decode("ascii"),
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload))
        tmp.replace(self._path)
