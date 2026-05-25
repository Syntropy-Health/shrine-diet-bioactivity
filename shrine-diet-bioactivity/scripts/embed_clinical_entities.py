"""Selective clinical-entity embedding pass for kg_query semantic search.

Why this exists: the `kg-mcp` semantic-search tool (LightRAG's local/mix
modes) anchors retrieval on entity-vector matches. With an empty
`entities_vdb`, that path returns `"None"`. A full re-embed of all
155K KG entities would be wasteful — 90K compounds are orphan and
can't anchor a useful subgraph anyway.

This script embeds only the entities that act as **clinical anchors**:
all connected herbs / foods / diseases / symptoms / targets, plus all
connected compounds (degree ≥ 1). For each entity, the embedded text
is enriched with its 1-hop typed neighborhood so a search for "arthritis"
surfaces not only the Symptom node but every Herb that treats it.

Architecture:
  - LightRAG is initialized with a *throwaway* NetworkX graph storage
    (rag_storage_clinical_embed/) so this pass does NOT touch the real
    Aura graph. Only NanoVectorDB vectors are written.
  - The final vdb_entities.json is copied into the scoped_server's
    working_dir (rag_storage_local/) so the live MCP adapter picks
    it up on restart.
  - Resumable: existing entity vectors (by entity_name mdhash) are
    skipped so re-running fills only what's missing.

Usage:
    python embed_clinical_entities.py [--batch 200] [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

SCRIPT_DIR = Path(__file__).parent
LIGHTRAG_DIR = SCRIPT_DIR.parent / "lightrag"


# ─── OpenRouter-compatible embed (inlined to keep this script standalone) ───
# lightrag's bundled openai_embed hardcodes encoding_format="base64" which
# OpenRouter rejects. This is a direct call with float encoding + transient
# retry, mirroring the version in ingest_unified.py (which lives behind PR #67).

_TRANSIENT_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504, 520, 522, 524})


async def _openai_compat_embed(
    texts: list[str],
    model: str,
    base_url: str,
    api_key: str | None,
    embedding_dim: int,
    max_retries: int = 5,
):
    """Call an OpenAI-compatible /embeddings endpoint with float encoding."""
    import asyncio as _asyncio

    import httpx
    import numpy as np

    url = base_url.rstrip("/") + "/embeddings"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"model": model, "input": texts, "dimensions": embedding_dim}

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
            data = body.get("data")
            if isinstance(data, list):
                if any("index" not in d for d in data):
                    raise RuntimeError(f"embeddings response item missing 'index': {data[:2]}")
                ordered = sorted(data, key=lambda d: d["index"])
                return np.array([d["embedding"] for d in ordered], dtype=np.float32)
            err = body.get("error", body)
            code = err.get("code") if isinstance(err, dict) else None
            if code in _TRANSIENT_HTTP_CODES and attempt < max_retries:
                last_err = RuntimeError(f"transient embeddings error: {err}")
            else:
                raise RuntimeError(f"embeddings endpoint returned no data: {err}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _TRANSIENT_HTTP_CODES and attempt < max_retries:
                last_err = exc
            else:
                raise
        except httpx.RequestError as exc:
            if attempt < max_retries:
                last_err = exc
            else:
                raise
        await _asyncio.sleep(min(2 ** attempt, 30))

    raise RuntimeError(f"embeddings failed after {max_retries} attempts: {last_err}")

# ─── Constants ────────────────────────────────────────────────────────────

CLINICAL_ANCHOR_TYPES: tuple[str, ...] = (
    "Herb", "Food", "Disease", "Symptom", "Target", "Compound",
)
WORKSPACE = "unified_diet_kg"
EMBED_WORKING_DIR = LIGHTRAG_DIR / "rag_storage_clinical_embed"  # throwaway
SERVER_WORKING_DIR = LIGHTRAG_DIR / "rag_storage_local"  # scoped_server reads here
MAX_NEIGHBORS_PER_REL = 30  # cap per-relationship-type listing to keep text under budget
MAX_TEXT_CHARS = 2000  # nemotron-embed handles ~8K tokens, well under


# ─── Aura query helpers ───────────────────────────────────────────────────


def _connect():
    load_dotenv(LIGHTRAG_DIR / ".." / ".env")
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )


def fetch_anchor_ids(driver) -> list[tuple[str, str]]:
    """Return (entity_id, entity_type) for every connected anchor entity."""
    cypher = """
    MATCH (n)
    WHERE n.scope = 'shared'
      AND n.entity_type IN $types
      AND (n)--()
    RETURN n.entity_id AS id, n.entity_type AS et
    ORDER BY n.entity_type, n.entity_id
    """
    with driver.session() as s:
        return [(r["id"], r["et"]) for r in s.run(cypher, types=list(CLINICAL_ANCHOR_TYPES))]


def fetch_neighborhoods(driver, ids: list[str]) -> dict[str, dict]:
    """Batch-fetch each entity's description + 1-hop typed neighborhood.

    Returns: {entity_id: {"description": str, "edges": [(rel_type, neighbor_id, direction), ...]}}
    """
    cypher = """
    MATCH (n) WHERE n.entity_id IN $ids
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE m.entity_id IS NOT NULL
    WITH n, r, m
    RETURN n.entity_id AS id,
           n.entity_type AS et,
           n.description AS desc,
           collect(DISTINCT {
             rel: type(r),
             nbr: m.entity_id,
             out: startNode(r).entity_id = n.entity_id
           }) AS edges
    """
    out: dict[str, dict] = {}
    with driver.session() as s:
        for row in s.run(cypher, ids=ids):
            out[row["id"]] = {
                "entity_type": row["et"],
                "description": row["desc"] or "",
                "edges": [e for e in row["edges"] if e.get("nbr")],
            }
    return out


# ─── Rich-text composer ───────────────────────────────────────────────────


def compose_rich_text(entity_id: str, entity_type: str, base_description: str, edges: list[dict]) -> str:
    """Compose the string that gets embedded for one entity.

    Layout:
        <entity_id> (<entity_type>). <description>.
        <REL_TYPE_OUT>: nbr1, nbr2, ...
        <REL_TYPE_IN> ← : nbr3, nbr4, ...

    Outbound and inbound edges are listed separately so directionality
    is preserved (Herb-TREATS_SYMPTOM-Symptom reads differently from
    the reverse). Each rel-type list is capped to keep total under
    MAX_TEXT_CHARS.
    """
    head = f"{entity_id} ({entity_type})."
    if base_description:
        head += f" {base_description.strip()}"

    by_key: dict[tuple[str, bool], set[str]] = {}
    for e in edges:
        key = (e["rel"], bool(e.get("out")))
        by_key.setdefault(key, set()).add(e["nbr"])

    blocks: list[str] = []
    for (rel, is_out), nbrs in sorted(by_key.items()):
        sample = sorted(nbrs)[:MAX_NEIGHBORS_PER_REL]
        arrow = "→" if is_out else "←"
        blocks.append(f"{rel} {arrow}: {', '.join(sample)}.")

    text = head + ("\n" + "\n".join(blocks) if blocks else "")
    if len(text) > MAX_TEXT_CHARS:
        text = text[: MAX_TEXT_CHARS - 3] + "..."
    return text


# ─── LightRAG bootstrap (throwaway graph + real NanoVectorDB) ─────────────


async def build_rag() -> object:
    from lightrag import LightRAG
    from lightrag.llm.openai import gpt_4o_mini_complete
    from lightrag.utils import EmbeddingFunc

    embedding_model = os.environ.get("EMBEDDING_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free")
    embedding_dim = int(os.environ.get("EMBEDDING_DIM", "2048"))
    embedding_host = os.environ.get("EMBEDDING_BINDING_HOST", "https://openrouter.ai/api/v1")
    api_key = (
        os.environ.get("EMBEDDING_BINDING_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )

    embed_func = EmbeddingFunc(
        embedding_dim=embedding_dim,
        max_token_size=8192,
        func=partial(
            _openai_compat_embed,
            model=embedding_model,
            base_url=embedding_host,
            api_key=api_key,
            embedding_dim=embedding_dim,
        ),
    )

    EMBED_WORKING_DIR.mkdir(exist_ok=True)
    rag = LightRAG(
        working_dir=str(EMBED_WORKING_DIR),
        llm_model_func=gpt_4o_mini_complete,  # required signature; never invoked for ainsert_custom_kg
        embedding_func=embed_func,
        graph_storage="NetworkXStorage",
        kv_storage="JsonKVStorage",
        vector_storage="NanoVectorDBStorage",
        doc_status_storage="JsonDocStatusStorage",
        workspace=WORKSPACE,
    )
    await rag.initialize_storages()
    return rag


# ─── Resume support ───────────────────────────────────────────────────────


def already_embedded_names() -> set[str]:
    """Read the existing vdb_entities.json (if any) and return the set of
    entity_names already embedded, so we can skip them on resume.

    LightRAG stores entries by `__id__` = "ent-<md5(entity_name)>". The
    `entity_name` is preserved in the meta-fields, so we can read it back
    directly without recomputing the hash.
    """
    vdb_path = EMBED_WORKING_DIR / WORKSPACE / "vdb_entities.json"
    if not vdb_path.exists():
        return set()
    try:
        with open(vdb_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return set()
    out: set[str] = set()
    # NanoVectorDB stores entries either as a list or a dict — handle both.
    raw_entries = data.get("data") if isinstance(data, dict) else data
    if isinstance(raw_entries, list):
        for e in raw_entries:
            if isinstance(e, dict) and "entity_name" in e:
                out.add(e["entity_name"])
    return out


# ─── Main driver ──────────────────────────────────────────────────────────


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=200, help="entities per ainsert_custom_kg call")
    parser.add_argument("--limit", type=int, default=None, help="cap total entities (debug)")
    parser.add_argument("--copy-to-server", action="store_true", default=True,
                        help="after embedding, copy vdb_entities.json into the scoped_server's working_dir")
    args = parser.parse_args()

    driver = _connect()
    print("Fetching anchor IDs...")
    anchors = fetch_anchor_ids(driver)
    print(f"  {len(anchors)} connected anchors found")
    for et in CLINICAL_ANCHOR_TYPES:
        n = sum(1 for _, t in anchors if t == et)
        print(f"    {et:10s}: {n}")

    already = already_embedded_names()
    if already:
        print(f"  resume: {len(already)} already embedded — will skip")
    pending = [(i, t) for i, t in anchors if i not in already]
    if args.limit:
        pending = pending[: args.limit]
    print(f"  pending: {len(pending)}")

    if not pending:
        print("Nothing to do.")
        driver.close()
        return 0

    print("\nInitializing LightRAG (throwaway NetworkX + NanoVectorDB)...")
    rag = await build_rag()

    start = time.time()
    total_batches = (len(pending) + args.batch - 1) // args.batch
    embedded = 0
    for bi in range(0, len(pending), args.batch):
        chunk = pending[bi : bi + args.batch]
        chunk_ids = [eid for eid, _ in chunk]
        nbh = fetch_neighborhoods(driver, chunk_ids)
        entities = []
        for eid, et in chunk:
            meta = nbh.get(eid, {})
            text = compose_rich_text(eid, et, meta.get("description", ""), meta.get("edges", []))
            entities.append({
                "entity_name": eid,
                "entity_type": et,
                "description": text,  # rich-text — gets embedded as "name\n" + this
                "scope": "shared",
                "source_id": f"clinical-embed:batch-{bi // args.batch + 1:04d}",
                "file_path": "clinical_anchors",
            })

        custom_kg = {
            "chunks": [{
                "content": f"Clinical anchor batch {bi // args.batch + 1}",
                "source_id": f"clinical-embed:batch-{bi // args.batch + 1:04d}",
                "file_path": "clinical_anchors",
            }],
            "entities": entities,
            "relationships": [],
        }
        await rag.ainsert_custom_kg(custom_kg)  # type: ignore[attr-defined]
        embedded += len(entities)
        elapsed = time.time() - start
        rate = embedded / elapsed if elapsed > 0 else 0
        eta = (len(pending) - embedded) / rate if rate > 0 else 0
        print(
            f"  batch {bi // args.batch + 1}/{total_batches}: +{len(entities)} "
            f"(total {embedded}/{len(pending)}, "
            f"{rate:.1f}/s, ETA {eta/60:.1f} min)",
            flush=True,
        )

    print("\nFinalizing storages...")
    await rag.finalize_storages()  # type: ignore[attr-defined]

    if args.copy_to_server:
        src = EMBED_WORKING_DIR / WORKSPACE / "vdb_entities.json"
        dst = SERVER_WORKING_DIR / WORKSPACE / "vdb_entities.json"
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            sz_mb = dst.stat().st_size / 1024 / 1024
            print(f"Copied {src} → {dst} ({sz_mb:.1f} MB)")

    driver.close()
    total = time.time() - start
    print(f"\nDone in {total/60:.1f} min ({embedded} entities embedded)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
