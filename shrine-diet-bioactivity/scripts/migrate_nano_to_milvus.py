"""Path-A migration: transfer NanoVectorDB vectors into Milvus.

Reads ``rag_storage_clinical_embed/<workspace>/vdb_entities.json`` (and the
sibling ``vdb_relationships.json`` / ``vdb_chunks.json`` if present),
decodes the base64-packed float32 matrix, and bulk-upserts into the
LightRAG-managed Milvus collection. Avoids re-embedding entirely.

Why Path A: the existing 26,141 entities × 2048-dim file was produced by
``embed_clinical_entities.py`` against OpenRouter
``nvidia/llama-nemotron-embed-vl-1b-v2:free``. The same model serves
queries via ``scoped_server.py``; the vectors are still query-consistent
and re-embedding would burn 27 minutes for an identical index.

Schema alignment: this script does NOT bypass LightRAG's collection
bootstrap. It boots a LightRAG instance pointing at Milvus (so LightRAG
creates the collection with its expected schema), then uses ``pymilvus``
directly to upsert rows. That guarantees the schema LightRAG expects at
query time matches what we write at migration time.

Usage::

    cd shrine-diet-bioactivity/lightrag
    KG_VECTOR_BACKEND=milvus \\
    WORKSPACE=unified_diet_kg \\
    infisical run --env=prod --path=/mcp/kg/ -- \\
        python ../scripts/migrate_nano_to_milvus.py \\
            --working-dir ./rag_storage_clinical_embed \\
            --dry-run            # preview counts without writing

Drop ``--dry-run`` to commit. The script is idempotent — re-running on a
fully-migrated collection is a no-op (Milvus upsert semantics).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
LIGHTRAG_DIR = SCRIPT_DIR.parent / "lightrag"
sys.path.insert(0, str(LIGHTRAG_DIR))


# ---------------------------------------------------------------------------
# NanoVectorDB JSON reader
# ---------------------------------------------------------------------------


def _decode_nano(path: Path) -> tuple[int, list[dict], list[list[float]]]:
    """Return ``(embedding_dim, data_rows, matrix)`` from a vdb_*.json file."""
    raw = json.loads(path.read_text())
    dim = int(raw.get("embedding_dim") or 0)
    data = raw.get("data") or []
    matrix_b64 = raw.get("matrix") or ""
    if not (matrix_b64 and dim and data):
        return dim, [], []
    blob = base64.b64decode(matrix_b64)
    n_floats = len(blob) // 4
    unpacked = struct.unpack(f"<{n_floats}f", blob)
    matrix = [list(unpacked[i : i + dim]) for i in range(0, n_floats, dim)]
    return dim, data, matrix


# ---------------------------------------------------------------------------
# LightRAG bootstrap — ensure the Milvus collection exists with the right schema
# ---------------------------------------------------------------------------


async def _bootstrap_lightrag_milvus() -> Any:
    """Boot LightRAG with KG_VECTOR_BACKEND=milvus so it creates the
    Milvus collection at the schema LightRAG itself expects to read."""
    from scoped_server import _build_scoped_rag  # noqa: E402

    rag = await _build_scoped_rag()
    return rag


# ---------------------------------------------------------------------------
# Migration core
# ---------------------------------------------------------------------------


def _milvus_client():
    """Return a pymilvus client built from the (already-shimmed) env."""
    from pymilvus import MilvusClient  # noqa: E402

    uri = os.environ["MILVUS_URI"]
    token = os.environ.get("MILVUS_TOKEN")
    user = os.environ.get("MILVUS_USER")
    password = os.environ.get("MILVUS_PASSWORD")

    if token:
        return MilvusClient(uri=uri, token=token)
    if user and password:
        return MilvusClient(uri=uri, user=user, password=password)
    raise RuntimeError(
        "Migration needs MILVUS_TOKEN or MILVUS_USER + MILVUS_PASSWORD."
    )


def _migrate_file(
    nano_path: Path,
    collection_name: str,
    batch_size: int,
    *,
    dry_run: bool,
) -> dict:
    """Migrate a single vdb_*.json into the named Milvus collection."""
    print(f"  reading {nano_path.name} ...", flush=True)
    dim, data, matrix = _decode_nano(nano_path)
    n = len(data)
    print(f"    {n} entries × {dim}-dim", flush=True)
    if n == 0:
        return {"file": nano_path.name, "written": 0, "skipped": 0}
    assert len(matrix) == n, f"row mismatch in {nano_path}"

    if dry_run:
        return {"file": nano_path.name, "written": 0, "would_write": n}

    client = _milvus_client()
    written = 0
    started = time.time()
    for offset in range(0, n, batch_size):
        batch_rows = data[offset : offset + batch_size]
        batch_vecs = matrix[offset : offset + batch_size]
        records = [
            {
                "id": row.get("__id__", ""),
                "vector": batch_vecs[i],
                "created_at": int(row.get("__created_at__", 0)),
                "content": (row.get("content") or "")[:8000],
                "entity_name": row.get("entity_name", ""),
                "source_id": row.get("source_id", ""),
                "file_path": row.get("file_path", ""),
            }
            for i, row in enumerate(batch_rows)
        ]
        client.upsert(collection_name=collection_name, data=records)
        written += len(records)
        elapsed = time.time() - started
        rate = written / elapsed if elapsed else 0
        print(
            f"    [{written}/{n}] rate={rate:.0f}/s",
            flush=True,
        )
    return {"file": nano_path.name, "written": written, "total": n}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _argparser() -> argparse.ArgumentParser:
    description = "Migrate NanoVectorDB vectors into Milvus (Path A)."
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument(
        "--working-dir",
        type=Path,
        required=True,
        help="Path to the rag_storage_* directory containing the workspace folder.",
    )
    ap.add_argument(
        "--workspace",
        default=os.environ.get("WORKSPACE", "unified_diet_kg"),
        help="LightRAG workspace name (matches Aura :workspace label).",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Upsert batch size (Zilliz serverless caps payload; default 500).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts only; do not write to Milvus.",
    )
    return ap


def main() -> int:
    args = _argparser().parse_args()

    workspace_dir = args.working_dir / args.workspace
    if not workspace_dir.exists():
        print(
            f"ERROR: working dir not found: {workspace_dir}", file=sys.stderr
        )
        return 2

    # Step 1: env shim + verify the secrets are present.
    from scoped_server import _apply_zilliz_env_shim  # noqa: E402

    _apply_zilliz_env_shim(os.environ)
    if not args.dry_run and not os.environ.get("MILVUS_URI"):
        print(
            "ERROR: MILVUS_URI (or ZILLIZ_URI) not set. "
            "Source from Infisical /mcp/kg/. ",
            file=sys.stderr,
        )
        return 2

    # Step 2: bootstrap LightRAG against Milvus so the collection exists
    # at the LightRAG-expected schema. Skipped in dry-run mode.
    if not args.dry_run:
        os.environ["KG_VECTOR_BACKEND"] = "milvus"
        print("Bootstrapping LightRAG → Milvus (creates collection on first run)")
        rag = asyncio.run(_bootstrap_lightrag_milvus())
        # ``rag.entities_vdb`` is the LightRAG-side wrapper; its
        # ``namespace`` is the actual Milvus collection name.
        entities_col = rag.entities_vdb.namespace
        rels_col = rag.relationships_vdb.namespace
        chunks_col = rag.chunks_vdb.namespace
    else:
        entities_col = rels_col = chunks_col = "<dry-run>"

    # Step 3: walk the workspace dir and migrate each known vdb file.
    files = {
        "vdb_entities.json": entities_col,
        "vdb_relationships.json": rels_col,
        "vdb_chunks.json": chunks_col,
    }

    summary = []
    for fname, col in files.items():
        path = workspace_dir / fname
        if not path.exists():
            print(f"  skipping {fname} — not present in {workspace_dir}")
            continue
        print(f"\n>>> Migrating {fname} → collection {col!r}")
        result = _migrate_file(
            path, col, args.batch_size, dry_run=args.dry_run
        )
        summary.append(result)

    print("\nDone.")
    for s in summary:
        print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
