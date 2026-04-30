"""Re-embed all workspace entity nodes via OpenRouter free-tier embedder
and populate Aura native vector index (per ADR 0001 / Task #11).

Design notes:

- **Idempotent resume.** Skips entities whose corresponding ``:VectorEntity``
  node already exists. Re-running after interruption picks up where it left
  off — important on free-tier infra where multi-hour runs may stall.
- **Rate-limit aware.** OpenRouter free tier rate-limits embeddings around
  20 RPM. We batch (default 16/req) and back off exponentially on 429.
- **Scope-policy honoring.** Every vector node carries ``scope='shared'``,
  matching the contract enforced by ``ScopedNeo4JVectorStorage`` (Task #7).
  Indexes are auto-used for retrieval — no extra setup beyond the
  ``initialize()`` call ScopedNeo4JVectorStorage performs.
- **Schema-matched.** Writes to the same ``(id, embedding, namespace,
  scope)`` shape ``ScopedNeo4JVectorStorage.upsert()`` produces; the live
  vector index built by that class will index these rows automatically.

Run:
    python3 scripts/migrate_embeddings_to_aura.py                     # entities namespace, default batch
    python3 scripts/migrate_embeddings_to_aura.py --limit 100         # smoke run
    python3 scripts/migrate_embeddings_to_aura.py --resume false      # force re-embed everything
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Iterator

import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, TransientError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _safe_label(s: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s)


def _ensure_index(driver, workspace_label: str, dim: int, index_name: str) -> None:
    """Create the VectorEntity vector index if missing.

    Idempotent (IF NOT EXISTS). Mirrors what ScopedNeo4JVectorStorage.initialize
    would do — running this script before the server first starts doesn't break
    the server, since the server's call is also idempotent.
    """
    cypher = (
        f"CREATE VECTOR INDEX {index_name} IF NOT EXISTS "
        f"FOR (n:`VectorEntity`) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        "`vector.dimensions`: $dim, "
        "`vector.similarity_function`: 'cosine'"
        "}}"
    )
    with driver.session() as s:
        s.run(cypher, dim=dim).consume()
    print(f"  vector index {index_name} ensured (dim={dim})", file=sys.stderr)


def _iter_entities(driver, workspace_label: str, batch: int, resume: bool) -> Iterator[list[dict]]:
    """Yield batches of {id, text} for entities not yet vectorized."""
    cypher = (
        f"MATCH (n:`{workspace_label}`) "
        f"WHERE n.entity_type IS NOT NULL AND n.scope = 'shared' "
    )
    if resume:
        cypher += (
            f"AND NOT EXISTS {{ MATCH (v:`{workspace_label}`:`VectorEntity` "
            f"{{id: n.entity_id}}) }} "
        )
    cypher += (
        "RETURN n.entity_id AS id, "
        "       coalesce(n.description, n.entity_id) AS text "
        "ORDER BY n.entity_id"
    )

    rows: list[dict] = []
    with driver.session() as s:
        for r in s.run(cypher):
            rid = r["id"]
            txt = r["text"]
            if not rid or not txt:
                continue
            rows.append({"id": rid, "text": str(txt)[:8000]})  # cap text size
            if len(rows) >= batch:
                yield rows
                rows = []
    if rows:
        yield rows


def _embed_with_retry(
    base_url: str,
    api_key: str,
    model: str,
    texts: list[str],
    max_attempts: int = 6,
) -> list[list[float]] | None:
    """Single embedding call with exponential backoff on 429/network errors.

    Bypasses the OpenAI Python client — it raises ``ValueError: No embedding
    data received`` against OpenRouter's response shape, even though the raw
    JSON contains the embeddings (verified 2026-04-29). Going direct via
    requests.post avoids the client-library bug entirely.
    """
    url = f"{base_url.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "input": texts}

    delay = 2.0
    for attempt in range(max_attempts):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=120.0)
        except requests.RequestException as e:
            if attempt == max_attempts - 1:
                print(f"  network-exhausted: {e}", file=sys.stderr)
                return None
            print(f"  network error; backing off {delay:.1f}s: {e}", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code == 429:
            if attempt == max_attempts - 1:
                print(f"  rate-limit-exhausted after {max_attempts} attempts", file=sys.stderr)
                return None
            print(f"  rate-limited; backing off {delay:.1f}s (attempt {attempt + 1}/{max_attempts})", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code >= 500:
            if attempt == max_attempts - 1:
                print(f"  server-error-exhausted: {r.status_code} {r.text[:200]}", file=sys.stderr)
                return None
            print(f"  server error {r.status_code}; backing off {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code >= 400:
            print(f"  client error {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return None

        try:
            data = r.json().get("data", [])
        except ValueError as e:
            print(f"  json decode error: {e}", file=sys.stderr)
            return None
        if len(data) != len(texts):
            print(f"  embedding count mismatch: {len(data)} vs {len(texts)}", file=sys.stderr)
            return None
        return [item["embedding"] for item in data]
    return None


def _write_vectors(
    driver,
    workspace_label: str,
    rows: list[dict],
    embeddings: list[list[float]],
    max_attempts: int = 8,
) -> int:
    """MERGE :VectorEntity nodes with embeddings + scope='shared'.

    Retries on Neo4j TransientError (Aura cluster maintenance, replication
    pauses, leader elections). These are non-deterministic and usually
    resolve in seconds; without retry, an 8-hour migration can die at hour 4
    on a single hiccup.
    """
    if not rows or not embeddings or len(rows) != len(embeddings):
        return 0
    payload = [
        {
            "id": r["id"],
            "embedding": embeddings[i],
            "created_at": int(time.time()),
        }
        for i, r in enumerate(rows)
    ]
    cypher = (
        f"UNWIND $rows AS row "
        f"MERGE (n:`{workspace_label}`:`VectorEntity` {{id: row.id}}) "
        f"SET n.embedding = row.embedding, "
        f"    n.created_at = row.created_at, "
        f"    n.scope = 'shared', "
        f"    n.namespace = 'entities'"
    )
    delay = 2.0
    for attempt in range(max_attempts):
        try:
            with driver.session() as s:
                s.run(cypher, rows=payload).consume()
            return len(payload)
        except (TransientError, ServiceUnavailable) as e:
            if attempt == max_attempts - 1:
                print(f"  aura-write-exhausted after {max_attempts} attempts: {e}", file=sys.stderr)
                raise
            print(
                f"  aura transient ({type(e).__name__}); backing off {delay:.1f}s "
                f"(attempt {attempt + 1}/{max_attempts})",
                file=sys.stderr,
            )
            time.sleep(delay)
            delay *= 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=16, help="Texts per embedding API call")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N nodes (0 = unbounded)")
    parser.add_argument(
        "--resume",
        type=lambda s: s.lower() != "false",
        default=True,
        help="Skip nodes that already have a VectorEntity (default: true)",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=200,
        help="Print progress + elapsed every N entities",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / "lightrag" / "config_local.env", override=False)

    workspace = os.environ.get("WORKSPACE", "unified_diet_kg")
    workspace_label = _safe_label(workspace)
    embedding_model = os.environ.get(
        "EMBEDDING_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2:free"
    )
    embedding_dim = int(os.environ.get("EMBEDDING_DIM", "2048"))
    embedding_host = os.environ.get(
        "EMBEDDING_BINDING_HOST", "https://openrouter.ai/api/v1"
    )
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("EMBEDDING_BINDING_API_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY (or EMBEDDING_BINDING_API_KEY) not set", file=sys.stderr)
        return 1

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]

    print(f"workspace={workspace} embedder={embedding_model} dim={embedding_dim}", file=sys.stderr)
    print(f"resume={args.resume} batch={args.batch} limit={args.limit or 'unbounded'}", file=sys.stderr)

    started = time.time()
    total_emb = 0
    total_written = 0
    failures = 0

    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        _ensure_index(driver, workspace_label, embedding_dim, "vec_unified_diet_kg_entities")

        for batch in _iter_entities(driver, workspace_label, args.batch, args.resume):
            texts = [r["text"] for r in batch]
            emb = _embed_with_retry(embedding_host, api_key, embedding_model, texts)
            if emb is None:
                failures += 1
                if failures > 5:
                    print(f"ABORT: too many embedding failures; resuming next run will skip already-done", file=sys.stderr)
                    break
                continue
            written = _write_vectors(driver, workspace_label, batch, emb)
            total_emb += len(batch)
            total_written += written

            if total_emb % args.checkpoint_every == 0 or len(batch) < args.batch:
                elapsed = time.time() - started
                rate = total_emb / max(elapsed, 0.001)
                print(
                    f"  checkpoint: {total_emb} embedded, {total_written} written, "
                    f"{elapsed:.0f}s elapsed, {rate:.1f} entities/sec",
                    file=sys.stderr,
                )

            if args.limit and total_emb >= args.limit:
                print(f"  limit {args.limit} reached", file=sys.stderr)
                break

    elapsed = time.time() - started
    print(
        f"\nDone. {total_written} vectors written in {elapsed:.0f}s "
        f"({total_written / max(elapsed, 0.001):.1f}/sec). failures={failures}",
        file=sys.stderr,
    )
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
