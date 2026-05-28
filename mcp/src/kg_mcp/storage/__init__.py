"""Storage adapters injected into the kg-mcp gateway at startup.

The gateway never instantiates a backend directly — it depends on the
:class:`VectorStore` protocol. Selecting an implementation is the job of
``mcp/src/kg_mcp/storage/factory.py`` (Phase 3 PR2).

Available implementations:

* :class:`NanoVectorDBVectorStore` — wraps the local LightRAG NanoVectorDB
  JSON files. Default for local dev.
* :class:`MilvusVectorStore` — Zilliz Cloud / Milvus serverless. Default for
  prod once Phase 4 migration lands.
"""
from __future__ import annotations

from .vector_store import VectorEntry, VectorHit, VectorStore

__all__ = ["VectorEntry", "VectorHit", "VectorStore"]
