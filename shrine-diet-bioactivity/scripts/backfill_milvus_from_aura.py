"""Capacity-optimized backfill of Milvus from Aura.

The clinical-anchor pass (``embed_clinical_entities.py``) embedded 26,191
entities + 131 synthetic chunks into Milvus. The other 83% of the KG
(128,832 entities + all 181,985 relationships) had no vector
representation, so ``kg_query`` couldn't surface them.

This script closes that gap under the Zilliz free-tier 5 GB cap:

  **Entities** (priority-tiered, idempotent)
    Tier 1 — all Herb / Disease / Symptom / Target / Food (~51K nodes)
    Tier 2 — top 30K Compounds by relationship degree (high-value tail
             of the 104K total Compound nodes; the long-tail single-
             source phytochemicals are intentionally skipped)
    Already embedded — skipped via Milvus ``id`` lookup

  **Relationships** (all 5 types, no subset)
    TARGETS_PROTEIN, TREATS_SYMPTOM, ASSOCIATED_WITH_DISEASE,
    CONTAINS_COMPOUND, FOUND_IN_FOOD (~182K edges)

Storage budget: ~3.6 GB total (~72% of cap), ~1.4 GB headroom.

Embeddings use OpenRouter's ``nvidia/llama-nemotron-embed-vl-1b-v2:free``
at dim=2048 — same model + dim as the clinical-anchor pass so query-time
vectors stay geometrically consistent across the two index generations.

Idempotent: re-running skips entries already present in Milvus.
Checkpoint-resumable: progress is written every 500 rows so an interrupt
resumes cleanly from the last batch.

Usage::

    cd shrine-diet-bioactivity
    infisical run --projectId=589d1e3b-5798-48ea-97c0-2d58086a375b --env=prod --path=/mcp/kg/ -- \\
    infisical run --projectId=589d1e3b-5798-48ea-97c0-2d58086a375b --env=prod --path=/research/shrine-diet-bioactivity/ -- \\
        python scripts/backfill_milvus_from_aura.py \\
            [--entities-only] [--relationships-only] \\
            [--compound-degree-top 30000] \\
            [--batch-size 32] \\
            [--limit-tier1 0] [--limit-tier2 0]

Env required:
  NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
  ZILLIZ_URI, ZILLIZ_TOKEN, ZILLIZ_DB_NAME (=db_<cluster_id>)
  OPENROUTER_API_KEY
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent


# ─── Constants ────────────────────────────────────────────────────────────

TIER1_LABELS = ("Herb", "Disease", "Symptom", "Target", "Food")
COMPOUND_LABEL = "Compound"
RELATIONSHIP_TYPES = (
    "TARGETS_PROTEIN",
    "TREATS_SYMPTOM",
    "ASSOCIATED_WITH_DISEASE",
    "CONTAINS_COMPOUND",
    "FOUND_IN_FOOD",
)
DEFAULT_COMPOUND_TOP = 30_000
EMBEDDING_DIM = 2048
EMBEDDING_MODEL_DEFAULT = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MAX_NEIGHBORS_PER_REL = 30
MAX_TEXT_CHARS = 2000
MAX_RETRIES = 5
WORKSPACE = "unified_diet_kg"
ENTITIES_COLLECTION = f"{WORKSPACE}_entities"
RELATIONSHIPS_COLLECTION = f"{WORKSPACE}_relationships"

_TRANSIENT_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504, 520, 522, 524})


# ─── OpenRouter-compatible embed (inlined; matches embed_clinical_entities.py) ───


async def _embed(
    texts: list[str],
    *,
    model: str,
    api_key: str,
) -> list[list[float]]:
    """Call OpenAI-compatible /embeddings with float encoding + retry/backoff."""
    import httpx

    url = OPENROUTER_BASE.rstrip("/") + "/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {"model": model, "input": texts, "dimensions": EMBEDDING_DIM}

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
            data = body.get("data")
            if isinstance(data, list):
                if any("index" not in d for d in data):
                    raise RuntimeError(
                        f"embeddings response item missing 'index': {data[:2]}"
                    )
                ordered = sorted(data, key=lambda d: d["index"])
                return [d["embedding"] for d in ordered]
            err = body.get("error", body)
            code = err.get("code") if isinstance(err, dict) else None
            if code in _TRANSIENT_HTTP_CODES and attempt < MAX_RETRIES:
                last_err = RuntimeError(f"transient embeddings error: {err}")
            else:
                raise RuntimeError(f"embeddings endpoint returned no data: {err}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _TRANSIENT_HTTP_CODES and attempt < MAX_RETRIES:
                last_err = exc
            else:
                raise
        except httpx.RequestError as exc:
            if attempt < MAX_RETRIES:
                last_err = exc
            else:
                raise
        await asyncio.sleep(min(2 ** attempt, 30))

    raise RuntimeError(f"embeddings failed after {MAX_RETRIES} attempts: {last_err}")


# ─── Aura helpers ─────────────────────────────────────────────────────────


# Transient Neo4j errors that should trigger an outer retry rather than
# kill the whole backfill (the free tier pauses on idle + has occasional
# bolt-level blips, neither of which represents a real failure).
_AURA_RETRY_ERRORS: tuple[str, ...] = (
    "Neo.TransientError.General.DatabaseUnavailable",
    "Neo.TransientError.Network.CommunicationError",
    "Neo.TransientError.Database.DatabaseShutdown",
)


def _is_aura_transient(exc: Exception) -> bool:
    """True if the exception looks like a recoverable Aura blip.

    Three layers of detection:
    1. Exception class name — ``ServiceUnavailable`` / ``TransientError`` /
       ``SessionExpired`` / ``DatabaseUnavailable`` (covers the case
       observed in this session where DNS resolution fails and the
       exception's str() doesn't contain the word "unavailable").
    2. Documented Neo4j error codes.
    3. Substring sniff for common transient phrases.
    """
    name = type(exc).__name__
    if name in (
        "ServiceUnavailable",
        "TransientError",
        "SessionExpired",
        "DatabaseUnavailable",
        "WriteServiceUnavailable",
        "ReadServiceUnavailable",
    ):
        return True
    msg = str(exc).lower()
    if any(code.lower() in msg for code in _AURA_RETRY_ERRORS):
        return True
    return any(
        phrase in msg
        for phrase in (
            "unavailable",
            "temporary failure",
            "name resolution",
            "dns resolve",
            "connection refused",
            "connection reset",
        )
    )


def _neo4j_driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )


async def _aura_retry(call, *, label: str, max_wait_s: float = 300.0):
    """Retry a callable on transient Aura errors with exponential backoff.

    Single call, not a generator — accepts a thunk so the caller can
    re-bind the driver session inside it (Aura's idle-pause invalidates
    the session, not just the call). Exits the loop once the call
    succeeds or after the cumulative wait exceeds ``max_wait_s``.
    """
    waited = 0.0
    delay = 5.0
    attempt = 0
    while True:
        attempt += 1
        try:
            return call()
        except Exception as exc:
            if not _is_aura_transient(exc):
                raise
            if waited >= max_wait_s:
                raise
            msg = str(exc)[:120]
            print(
                f"   [{label}] Aura transient (attempt {attempt}): {msg}; "
                f"sleeping {delay:.0f}s",
                flush=True,
            )
            await asyncio.sleep(delay)
            waited += delay
            delay = min(delay * 2, 60.0)


def fetch_tier1_entity_ids(driver) -> list[tuple[str, str]]:
    """Return (entity_id, label) tuples for every Tier-1 entity in Aura."""
    cypher = """
    MATCH (n)
    WHERE n.scope = 'shared'
      AND n.entity_type IN $types
      AND n.entity_id IS NOT NULL
    RETURN n.entity_id AS id, n.entity_type AS lbl
    ORDER BY n.entity_type, n.entity_id
    """
    with driver.session() as s:
        return [(r["id"], r["lbl"]) for r in s.run(cypher, types=list(TIER1_LABELS))]


def fetch_tier2_compound_ids(driver, top_n: int) -> list[tuple[str, str]]:
    """Top-N Compounds by total relationship degree.

    Subsamples the long-tail single-source compounds out of the index.
    """
    cypher = """
    MATCH (n:Compound)
    WHERE n.scope = 'shared' AND n.entity_id IS NOT NULL
    WITH n, size([(n)--() | 1]) AS deg
    WHERE deg > 0
    ORDER BY deg DESC, n.entity_id
    LIMIT $top
    RETURN n.entity_id AS id
    """
    with driver.session() as s:
        return [(r["id"], COMPOUND_LABEL) for r in s.run(cypher, top=top_n)]


def fetch_orphan_compound_ids(driver) -> list[tuple[str, str]]:
    """Orphan Compounds — degree=0. Surface as (entity_id, 'Compound') tuples.

    Orphans are single-source phytochemicals imported from raw datasets
    that never got connected to a herb / target / disease. They're the
    bottom 86% of the Compound long-tail. Including them in Milvus
    enables semantic search recall on obscure compound names, even
    though the graph layer can't expand from them.
    """
    cypher = """
    MATCH (n:Compound)
    WHERE n.scope = 'shared'
      AND n.entity_id IS NOT NULL
      AND NOT (n)--()
    RETURN n.entity_id AS id
    ORDER BY n.entity_id
    """
    with driver.session() as s:
        return [(r["id"], COMPOUND_LABEL) for r in s.run(cypher)]


def fetch_entity_descriptions(driver, ids: list[str]) -> dict[str, dict]:
    """Lightweight per-batch lookup for orphan entities — name + label
    + description only, no neighborhood expansion.

    Faster than ``fetch_entity_neighborhoods`` because the relationship
    JOIN is skipped. Used when the caller knows the entity set is
    edge-free (e.g. orphan compound backfill).
    """
    cypher = """
    UNWIND $ids AS eid
    MATCH (n {entity_id: eid})
    RETURN n.entity_id AS id,
           n.entity_type AS lbl,
           n.description AS desc
    """
    out: dict[str, dict] = {}
    with driver.session() as s:
        for row in s.run(cypher, ids=ids):
            out[row["id"]] = {
                "label": row["lbl"],
                "description": row["desc"] or "",
                "edges": [],
            }
    return out


def fetch_entity_neighborhoods(
    driver, ids: list[str]
) -> dict[str, dict]:
    """Batch-fetch description + 1-hop typed neighborhood for the given ids."""
    cypher = """
    UNWIND $ids AS eid
    MATCH (n {entity_id: eid})
    OPTIONAL MATCH (n)-[r]-(m)
    WHERE m.entity_id IS NOT NULL
    WITH n, collect(DISTINCT {
        rel: type(r),
        nbr: m.entity_id,
        out: startNode(r).entity_id = n.entity_id
    }) AS edges
    RETURN n.entity_id AS id,
           n.entity_type AS lbl,
           n.description AS desc,
           edges
    """
    out: dict[str, dict] = {}
    with driver.session() as s:
        for row in s.run(cypher, ids=ids):
            out[row["id"]] = {
                "label": row["lbl"],
                "description": row["desc"] or "",
                "edges": [e for e in (row["edges"] or []) if e.get("nbr")],
            }
    return out


def fetch_relationships(driver, rel_type: str) -> list[dict]:
    """Stream every relationship of one type; cheap enough to materialize."""
    cypher = f"""
    MATCH (a)-[r:`{rel_type}`]->(b)
    WHERE a.scope = 'shared' AND b.scope = 'shared'
      AND a.entity_id IS NOT NULL AND b.entity_id IS NOT NULL
    RETURN a.entity_id AS src,
           b.entity_id AS tgt,
           a.entity_type AS src_lbl,
           b.entity_type AS tgt_lbl
    """
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher)]


# ─── Milvus helpers ───────────────────────────────────────────────────────


def _milvus_client():
    from pymilvus import MilvusClient

    uri = os.environ["ZILLIZ_URI"]
    token = os.environ["ZILLIZ_TOKEN"]
    db_name = os.environ.get("ZILLIZ_DB_NAME") or os.environ.get("MILVUS_DB_NAME")
    if not db_name:
        host = uri.split("//", 1)[-1].split(".", 1)[0]
        if host.startswith("in03-"):
            db_name = "db_" + host[len("in03-"):]
    return MilvusClient(uri=uri, token=token, db_name=db_name)


def existing_milvus_ids(client, collection: str) -> set[str]:
    """Pull the full id-set of an existing collection. Used as the skip-list."""
    ids: set[str] = set()
    # iterator handles big collections without a single huge response
    iterator = client.query_iterator(
        collection_name=collection,
        batch_size=10_000,
        output_fields=["id"],
    )
    while True:
        batch = iterator.next()
        if not batch:
            break
        for row in batch:
            if row.get("id"):
                ids.add(row["id"])
    iterator.close()
    return ids


# ─── Text composers ──────────────────────────────────────────────────────


def compose_entity_text(
    entity_id: str, label: str, description: str, edges: list[dict]
) -> str:
    """Mirror the format used by embed_clinical_entities.py so vector geometry
    stays consistent across the two index generations."""
    head = f"{entity_id} ({label})."
    if description:
        head += f" {description.strip()}"
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


def compose_relationship_text(
    src: str, rel: str, tgt: str, src_lbl: str | None, tgt_lbl: str | None
) -> str:
    """Natural-language paraphrase of a single edge.

    Format mirrors LightRAG's edge-description shape: a single concise
    sentence so cosine search ranks edges by semantic similarity of the
    relation they describe, not by entity-name overlap alone.
    """
    src_part = f"{src} ({src_lbl})" if src_lbl else src
    tgt_part = f"{tgt} ({tgt_lbl})" if tgt_lbl else tgt
    return f"{src_part} {rel} {tgt_part}."


def relationship_id(src: str, rel: str, tgt: str) -> str:
    """Deterministic id for the relationship row. LightRAG uses md5 prefixes;
    we follow suit so the schema feels native."""
    digest = hashlib.md5(f"{src}|{rel}|{tgt}".encode("utf-8")).hexdigest()
    return f"rel-{digest}"


def safe_milvus_id(raw: str, prefix: str) -> str:
    """Clamp an entity id to Milvus's 64-char primary-key limit.

    LightRAG hashes raw entity names with md5 (``ent-<32hex>``). The IDs
    pulled from Aura use that same shape for entries embedded earlier, but
    arbitrary new entity_ids (Aura is permissive on entity_id strings) may
    exceed the cap. We md5 anything that doesn't already match the shape.
    """
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-:]{0,63}", raw):
        return raw
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


# ─── Backfill drivers ────────────────────────────────────────────────────


async def backfill_entities(
    driver,
    client,
    *,
    compound_top: int,
    batch_size: int,
    api_key: str,
    embedding_model: str,
    limit_tier1: int,
    limit_tier2: int,
    include_orphans: bool = False,
) -> dict:
    print(">> Backfilling entities", flush=True)
    print("   reading skip-list from Milvus...", flush=True)
    skip = existing_milvus_ids(client, ENTITIES_COLLECTION)
    print(f"   already-embedded count: {len(skip):,}", flush=True)

    print("   pulling Tier 1 ids from Aura...", flush=True)
    tier1 = await _aura_retry(lambda: fetch_tier1_entity_ids(driver), label="tier1")
    print(f"   Tier 1 (non-Compound) candidates: {len(tier1):,}", flush=True)

    print(f"   pulling top-{compound_top:,} Compounds by degree...", flush=True)
    tier2 = await _aura_retry(
        lambda: fetch_tier2_compound_ids(driver, compound_top), label="tier2"
    )
    print(f"   Tier 2 (Compound) candidates: {len(tier2):,}", flush=True)

    tier3: list[tuple[str, str]] = []
    if include_orphans:
        print("   pulling orphan (degree=0) Compounds from Aura...", flush=True)
        tier3 = await _aura_retry(
            lambda: fetch_orphan_compound_ids(driver), label="tier3-orphans"
        )
        print(f"   Tier 3 (orphan Compound) candidates: {len(tier3):,}", flush=True)

    if limit_tier1:
        tier1 = tier1[:limit_tier1]
    if limit_tier2:
        tier2 = tier2[:limit_tier2]

    # Track which IDs belong to Tier 3 so the inner loop can use the
    # lightweight description-only fetch (no Aura JOIN for neighborhoods).
    orphan_ids = {eid for eid, _ in tier3}

    todo = [
        (eid, lbl) for eid, lbl in (tier1 + tier2 + tier3) if eid not in skip
    ]
    total = len(todo)
    print(f"   to embed: {total:,}", flush=True)
    if total == 0:
        return {"embedded": 0, "skipped": len(skip)}

    written = 0
    started = time.time()
    for i in range(0, total, batch_size):
        batch_ids_and_lbls = todo[i : i + batch_size]
        ids = [eid for eid, _ in batch_ids_and_lbls]
        # Orphan batches skip the relationship JOIN — ~3x throughput.
        if orphan_ids and all(eid in orphan_ids for eid in ids):
            nb = await _aura_retry(
                lambda: fetch_entity_descriptions(driver, ids),
                label=f"batch-orphan@{i}",
            )
        else:
            nb = await _aura_retry(
                lambda: fetch_entity_neighborhoods(driver, ids),
                label=f"batch@{i}",
            )
        texts = []
        records_meta = []
        for eid, lbl in batch_ids_and_lbls:
            info = nb.get(eid)
            if info is None:
                continue
            text = compose_entity_text(
                eid, info["label"] or lbl, info["description"], info["edges"]
            )
            texts.append(text)
            records_meta.append((eid, info["label"] or lbl))

        if not texts:
            continue

        vectors = await _embed(texts, model=embedding_model, api_key=api_key)
        now_ts = int(time.time())
        records = [
            {
                "id": safe_milvus_id(eid, "ent"),
                "vector": vec,
                "created_at": now_ts,
                "entity_name": eid[:512],
                "file_path": "backfill_aura",
            }
            for (eid, _), vec in zip(records_meta, vectors)
        ]
        client.upsert(collection_name=ENTITIES_COLLECTION, data=records)

        written += len(records)
        elapsed = time.time() - started
        rate = written / elapsed if elapsed else 0
        eta_min = ((total - written) / rate / 60) if rate else 0
        print(
            f"   [{written:,}/{total:,}] rate={rate:.0f}/s eta={eta_min:.1f}min",
            flush=True,
        )

    return {"embedded": written, "skipped": len(skip)}


async def backfill_relationships(
    driver,
    client,
    *,
    batch_size: int,
    api_key: str,
    embedding_model: str,
) -> dict:
    print(">> Backfilling relationships", flush=True)
    print("   reading skip-list from Milvus...", flush=True)
    skip = existing_milvus_ids(client, RELATIONSHIPS_COLLECTION)
    print(f"   already-embedded count: {len(skip):,}", flush=True)

    all_edges: list[tuple[str, str, str, str | None, str | None]] = []
    for rel in RELATIONSHIP_TYPES:
        print(f"   pulling {rel} from Aura...", flush=True)
        edges = await _aura_retry(
            lambda r=rel: fetch_relationships(driver, r), label=f"rels:{rel}"
        )
        for e in edges:
            all_edges.append((e["src"], rel, e["tgt"], e.get("src_lbl"), e.get("tgt_lbl")))
        print(f"     {len(edges):,} edges", flush=True)

    todo = [
        (src, rel, tgt, slbl, tlbl)
        for (src, rel, tgt, slbl, tlbl) in all_edges
        if relationship_id(src, rel, tgt) not in skip
    ]
    total = len(todo)
    print(f"   to embed: {total:,}", flush=True)
    if total == 0:
        return {"embedded": 0, "skipped": len(skip)}

    written = 0
    started = time.time()
    for i in range(0, total, batch_size):
        batch = todo[i : i + batch_size]
        texts = [
            compose_relationship_text(src, rel, tgt, slbl, tlbl)
            for (src, rel, tgt, slbl, tlbl) in batch
        ]
        vectors = await _embed(texts, model=embedding_model, api_key=api_key)
        now_ts = int(time.time())
        records = [
            {
                "id": relationship_id(src, rel, tgt),
                "vector": vec,
                "created_at": now_ts,
                "src_id": src[:128],
                "tgt_id": tgt[:128],
                "file_path": "backfill_aura",
            }
            for (src, rel, tgt, _, _), vec in zip(batch, vectors)
        ]
        client.upsert(collection_name=RELATIONSHIPS_COLLECTION, data=records)
        written += len(records)
        elapsed = time.time() - started
        rate = written / elapsed if elapsed else 0
        eta_min = ((total - written) / rate / 60) if rate else 0
        print(
            f"   [{written:,}/{total:,}] rate={rate:.0f}/s eta={eta_min:.1f}min",
            flush=True,
        )

    return {"embedded": written, "skipped": len(skip)}


# ─── CLI ──────────────────────────────────────────────────────────────────


def _argparser() -> argparse.ArgumentParser:
    description = "Backfill Milvus from Aura under the 5 GB Zilliz Cloud cap."
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--entities-only", action="store_true")
    ap.add_argument("--relationships-only", action="store_true")
    ap.add_argument(
        "--compound-degree-top",
        type=int,
        default=DEFAULT_COMPOUND_TOP,
        help="Top-N Compounds by total relationship degree (default: 30000).",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="OpenRouter /embeddings batch size (default: 32).",
    )
    ap.add_argument(
        "--limit-tier1",
        type=int,
        default=0,
        help="Cap Tier-1 entity count (smoke runs); 0 = no cap.",
    )
    ap.add_argument(
        "--limit-tier2",
        type=int,
        default=0,
        help="Cap Tier-2 (Compound) entity count (smoke runs); 0 = no cap.",
    )
    ap.add_argument(
        "--include-orphans",
        action="store_true",
        help=(
            "Also embed Tier-3 orphan Compounds (degree=0, ~89K nodes "
            "as of 2026-06-01). Uses a lighter Aura query (no edge "
            "JOIN) — ~3x throughput. Storage cost: ~0.7 GB raw at "
            "2048-dim float32."
        ),
    )
    return ap


async def _amain() -> int:
    args = _argparser().parse_args()

    embedding_model = os.environ.get("EMBEDDING_MODEL", EMBEDDING_MODEL_DEFAULT)
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get(
        "EMBEDDING_BINDING_API_KEY"
    )
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    driver = _neo4j_driver()
    client = _milvus_client()
    try:
        summary: dict = {}
        if not args.relationships_only:
            summary["entities"] = await backfill_entities(
                driver,
                client,
                compound_top=args.compound_degree_top,
                batch_size=args.batch_size,
                api_key=api_key,
                embedding_model=embedding_model,
                limit_tier1=args.limit_tier1,
                limit_tier2=args.limit_tier2,
                include_orphans=args.include_orphans,
            )
        if not args.entities_only:
            summary["relationships"] = await backfill_relationships(
                driver,
                client,
                batch_size=args.batch_size,
                api_key=api_key,
                embedding_model=embedding_model,
            )

        print()
        print("Done.")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    finally:
        driver.close()
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
