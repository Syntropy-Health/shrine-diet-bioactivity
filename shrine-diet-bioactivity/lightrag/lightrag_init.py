"""Shared LightRAG initialization helper.

Centralizes the embedding/storage configuration that previously lived
inline in ingest_unified.py so HDI / snapshot / new ingest scripts can
reuse the same workspace + embedding model without drift.

Reads the following env vars (typically loaded from
``shrine-diet-bioactivity/lightrag/config_local.env`` or
``config_production.env`` plus the shared ``.env`` for Aura creds):

  EMBEDDING_BINDING        (ollama | openai)
  EMBEDDING_MODEL
  EMBEDDING_DIM
  EMBEDDING_BINDING_HOST
  LIGHTRAG_GRAPH_STORAGE   (Neo4JStorage)
  LIGHTRAG_KV_STORAGE
  LIGHTRAG_VECTOR_STORAGE
  LIGHTRAG_DOC_STATUS_STORAGE
  WORKING_DIR
  WORKSPACE
"""
from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from typing import Tuple


# Importing scoped_neo4j_*_storage modules triggers their module-level
# registration of ScopedNeo4JStorage / ScopedNeo4JVectorStorage into upstream
# LightRAG's STORAGE_IMPLEMENTATIONS whitelist.  This must happen before any
# LightRAG() call that passes either class name as graph_storage /
# vector_storage.
try:
    import scoped_neo4j_storage as _sns  # noqa: F401
    import scoped_neo4j_vector_storage as _snvs  # noqa: F401
except ImportError:
    pass


def init_lightrag(working_dir: str | None = None):
    """Construct and initialize a LightRAG instance from current env.

    Returns a tuple ``(rag, workspace)``. Caller must ``await
    rag.initialize_storages()`` then ``await rag.finalize_storages()``
    when done.
    """
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc

    embedding_binding = os.getenv("EMBEDDING_BINDING", "ollama")
    embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:latest")
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "768"))
    embedding_host = os.getenv("EMBEDDING_BINDING_HOST", "http://localhost:11434")

    if embedding_binding == "ollama":
        from lightrag.llm.ollama import ollama_embed, ollama_model_complete

        llm_func = ollama_model_complete
        embed_func = EmbeddingFunc(
            embedding_dim=embedding_dim,
            max_token_size=8192,
            func=partial(
                ollama_embed.func,
                embed_model=embedding_model,
                host=embedding_host,
            ),
        )
    else:
        from lightrag.llm.openai import gpt_4o_mini_complete, openai_embed

        llm_func = gpt_4o_mini_complete
        embed_func = EmbeddingFunc(
            embedding_dim=embedding_dim,
            max_token_size=8192,
            func=partial(openai_embed.func, model=embedding_model),
        )

    wd = working_dir or os.getenv("WORKING_DIR", "./rag_storage_local")
    Path(wd).mkdir(parents=True, exist_ok=True)

    graph_storage = os.getenv("LIGHTRAG_GRAPH_STORAGE", "NetworkXStorage")
    kv_storage = os.getenv("LIGHTRAG_KV_STORAGE", "JsonKVStorage")
    vector_storage = os.getenv("LIGHTRAG_VECTOR_STORAGE", "NanoVectorDBStorage")
    doc_status_storage = os.getenv(
        "LIGHTRAG_DOC_STATUS_STORAGE", "JsonDocStatusStorage"
    )
    workspace = os.getenv("WORKSPACE", "unified_diet_kg")

    rag = LightRAG(
        working_dir=wd,
        llm_model_func=llm_func,
        embedding_func=embed_func,
        graph_storage=graph_storage,
        kv_storage=kv_storage,
        vector_storage=vector_storage,
        doc_status_storage=doc_status_storage,
        workspace=workspace,
    )
    return rag, workspace
