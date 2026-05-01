"""Phase 1 — stamp MeSH UID + tree numbers on Disease + Symptom nodes.

Per the 2026-05-01 NCBI enrichment design doc. Uses NCBI E-utilities:
  - esearch[mesh] term=<entity_id> → MeSH UID (typically one or zero hits)
  - esummary[mesh] id=<uid> → tree numbers (e.g., 'C19.246.099')

Idempotent: writes via MERGE-and-SET on entity_id; re-running stamps
already-tagged nodes the same way.

Run:
    python3 scripts/ncbi/phase_1_mesh_overlay.py            # full pass
    python3 scripts/ncbi/phase_1_mesh_overlay.py --limit 10 # smoke
    python3 scripts/ncbi/phase_1_mesh_overlay.py --resume   # skip already-tagged

Requires NCBI_API_KEY in env (10 RPS quota).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase

# Ensure scripts/ncbi/ is importable when running by path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rate_limiter import TokenBucket  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRESS_FILE = PROJECT_ROOT / "data_local" / "ncbi_progress" / "phase_1_mesh.json"


def _safe_label(s: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s)


# ─── NCBI E-utilities client ──────────────────────────────────────────────


async def search_mesh_uid(
    client: httpx.AsyncClient, bucket: TokenBucket, term: str, api_key: str,
) -> str | None:
    """Return the first MeSH UID for `term`, or None."""
    await bucket.acquire()
    r = await client.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "mesh", "term": term, "retmode": "json", "api_key": api_key},
        timeout=15.0,
    )
    if r.status_code >= 400:
        return None
    data = r.json()
    ids = data.get("esearchresult", {}).get("idlist", [])
    return ids[0] if ids else None


async def fetch_mesh_summary(
    client: httpx.AsyncClient, bucket: TokenBucket, uids: list[str], api_key: str,
) -> dict[str, dict[str, Any]]:
    """Batch summary lookup. Returns {uid: {tree_numbers, ds_meshui, name}}."""
    if not uids:
        return {}
    await bucket.acquire()
    r = await client.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={
            "db": "mesh",
            "id": ",".join(uids),
            "retmode": "json",
            "api_key": api_key,
        },
        timeout=20.0,
    )
    if r.status_code >= 400:
        return {}
    data = r.json().get("result", {})
    out: dict[str, dict[str, Any]] = {}
    for uid in uids:
        rec = data.get(uid)
        if not rec:
            continue
        # Tree numbers come back in `ds_meshterms` with their tree codes;
        # the canonical descriptor UI is `ds_meshui` (e.g. "D003924").
        tree_numbers = rec.get("ds_idxlinks", [])  # not all records expose; falls back
        out[uid] = {
            "ds_meshui": rec.get("ds_meshui", ""),
            "ds_name": rec.get("ds_meshterms", [None])[0] if rec.get("ds_meshterms") else None,
            "tree_numbers": [
                t.strip()
                for t in (rec.get("ds_idxlinks") or [])
                if isinstance(t, str)
            ],
        }
    return out


# ─── Aura readers/writers ─────────────────────────────────────────────────


async def fetch_targets(
    driver, workspace: str, labels: list[str], resume: bool, limit: int,
) -> list[tuple[str, str]]:
    """Return [(entity_id, label), ...] of nodes still needing MeSH UID.

    `resume=True` skips nodes that already have `mesh_uid IS NOT NULL`.
    """
    ws = _safe_label(workspace)
    label_filter = " OR ".join(f"'{_safe_label(L)}' IN labels(n)" for L in labels)
    cypher = (
        f"MATCH (n:`{ws}`) "
        f"WHERE n.scope = 'shared' AND ({label_filter}) "
    )
    if resume:
        cypher += "AND n.mesh_uid IS NULL "
    cypher += "RETURN n.entity_id AS eid, [L IN labels(n) WHERE L <> $ws][0] AS label "
    if limit and limit > 0:
        cypher += f"LIMIT {limit}"

    out: list[tuple[str, str]] = []
    async with driver.session() as s:
        result = await s.run(cypher, ws=ws)
        async for rec in result:
            eid = rec["eid"]
            lbl = rec["label"]
            if eid and lbl:
                out.append((eid, lbl))
    return out


async def stamp_mesh(
    driver, workspace: str, rows: list[dict],
) -> int:
    """SET mesh_uid + tree_numbers on each node. Returns nodes touched."""
    if not rows:
        return 0
    ws = _safe_label(workspace)
    cypher = (
        f"UNWIND $rows AS row "
        f"MATCH (n:`{ws}` {{entity_id: row.entity_id}}) "
        f"SET n.mesh_uid = row.mesh_uid, "
        f"    n.mesh_descriptor = coalesce(row.descriptor, ''), "
        f"    n.mesh_tree_numbers = coalesce(row.tree_numbers, []) "
        f"RETURN count(n) AS c"
    )
    async with driver.session() as s:
        result = await s.run(cypher, rows=rows)
        rec = await result.single()
    return int(rec["c"]) if rec else 0


# ─── Progress / checkpointing ─────────────────────────────────────────────


def _load_progress() -> dict[str, str | None]:
    if not PROGRESS_FILE.exists():
        return {}
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_progress(progress: dict[str, str | None]) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, sort_keys=True))


# ─── Orchestrator ─────────────────────────────────────────────────────────


async def run(
    *, labels: list[str], limit: int, resume: bool,
    api_key: str, batch: int = 50,
) -> tuple[int, int, int]:
    """Returns (matched, stamped, skipped)."""
    load_dotenv(PROJECT_ROOT / ".env")
    workspace = os.environ.get("WORKSPACE", "unified_diet_kg")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]

    bucket = TokenBucket(rate=10.0, capacity=10)
    progress = _load_progress() if resume else {}

    matched = 0
    stamped = 0
    skipped = 0

    async with AsyncGraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        targets = await fetch_targets(driver, workspace, labels, resume, limit)
        print(f"Targets: {len(targets)} (labels={labels}, resume={resume})", file=sys.stderr)

        async with httpx.AsyncClient(timeout=20.0) as client:
            t0 = time.time()
            for i in range(0, len(targets), batch):
                chunk = targets[i : i + batch]

                # 1. esearch each unique term → UID
                eid_to_uid: dict[str, str | None] = {}
                for eid, _label in chunk:
                    if eid in progress:
                        eid_to_uid[eid] = progress[eid]
                        skipped += 1
                        continue
                    uid = await search_mesh_uid(client, bucket, eid, api_key)
                    eid_to_uid[eid] = uid
                    progress[eid] = uid

                # 2. batch esummary on resolved UIDs
                resolved_uids = [u for u in eid_to_uid.values() if u]
                summaries = await fetch_mesh_summary(client, bucket, resolved_uids, api_key)

                # 3. compose write payload
                rows = []
                for eid, uid in eid_to_uid.items():
                    if not uid:
                        continue
                    summary = summaries.get(uid, {})
                    rows.append({
                        "entity_id": eid,
                        "mesh_uid": summary.get("ds_meshui") or uid,
                        "descriptor": summary.get("ds_name"),
                        "tree_numbers": summary.get("tree_numbers", []),
                    })

                if rows:
                    n = await stamp_mesh(driver, workspace, rows)
                    stamped += n
                matched += sum(1 for u in eid_to_uid.values() if u)

                _save_progress(progress)

                if (i + len(chunk)) % 200 == 0 or (i + len(chunk)) == len(targets):
                    elapsed = time.time() - t0
                    print(
                        f"  progress: {i + len(chunk)}/{len(targets)} "
                        f"matched={matched} stamped={stamped} skipped={skipped} "
                        f"elapsed={elapsed:.1f}s",
                        file=sys.stderr,
                    )

    return matched, stamped, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels", default="Disease,Symptom",
        help="Comma-separated node labels to enrich",
    )
    parser.add_argument("--limit", type=int, default=0, help="Stop after N nodes (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Skip already-tagged nodes")
    args = parser.parse_args()

    api_key = os.environ.get("NCBI_API_KEY", "")
    if not api_key:
        load_dotenv(PROJECT_ROOT / ".env")
        api_key = os.environ.get("NCBI_API_KEY", "")
    if not api_key:
        print("ERROR: NCBI_API_KEY not set", file=sys.stderr)
        return 1

    labels = [s.strip() for s in args.labels.split(",") if s.strip()]
    matched, stamped, skipped = asyncio.run(
        run(labels=labels, limit=args.limit, resume=args.resume, api_key=api_key)
    )
    print(
        f"\nDone. matched={matched}, stamped={stamped}, skipped={skipped}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
