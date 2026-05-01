"""Phase 2 — stamp PubChem CID + synonyms (aliases) on Compound nodes.

Per the 2026-05-01 design doc. Uses NCBI's PubChem PUG-REST API:
  - name → CID:        /rest/pug/compound/name/<name>/cids/JSON
  - CID → synonyms:    /rest/pug/compound/cid/<cid>/synonyms/JSON
  - CID → properties:  /rest/pug/compound/cid/<cid>/property/InChIKey,CanonicalSMILES/JSON

PubChem PUG-REST allows ~5 RPS without an API key, but it accepts the same
NCBI API key for higher throughput. Conservative TokenBucket at 5 RPS.

Idempotent: SET on entity_id; re-running is a no-op for already-tagged.

Run:
    python3 scripts/ncbi/phase_2_pubchem_overlay.py --limit 5      # smoke
    python3 scripts/ncbi/phase_2_pubchem_overlay.py --resume       # full pass

Closes Blocker 4 (seed-casing) for Compound seeds — kg_compound_to_targets("curcumin")
will resolve via aliases.
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
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from neo4j import AsyncGraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rate_limiter import TokenBucket  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRESS_FILE = PROJECT_ROOT / "data_local" / "ncbi_progress" / "phase_2_pubchem.json"

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
MAX_SYNONYMS = 25  # cap per compound to keep node size sane


def _safe_label(s: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s)


# ─── PubChem client ───────────────────────────────────────────────────────


async def name_to_cid(
    client: httpx.AsyncClient, bucket: TokenBucket, name: str,
) -> int | None:
    await bucket.acquire()
    try:
        r = await client.get(f"{PUBCHEM}/compound/name/{quote(name)}/cids/JSON", timeout=20.0)
    except httpx.RequestError:
        return None
    if r.status_code != 200:
        return None
    try:
        cids = r.json().get("IdentifierList", {}).get("CID", [])
    except (json.JSONDecodeError, ValueError):
        return None
    return cids[0] if cids else None


async def cid_synonyms(
    client: httpx.AsyncClient, bucket: TokenBucket, cid: int,
) -> list[str]:
    await bucket.acquire()
    try:
        r = await client.get(f"{PUBCHEM}/compound/cid/{cid}/synonyms/JSON", timeout=20.0)
    except httpx.RequestError:
        return []
    if r.status_code != 200:
        return []
    try:
        info = r.json().get("InformationList", {}).get("Information", [{}])[0]
    except (json.JSONDecodeError, ValueError, IndexError):
        return []
    return info.get("Synonym", [])[:MAX_SYNONYMS]


async def cid_props(
    client: httpx.AsyncClient, bucket: TokenBucket, cid: int,
) -> dict[str, str]:
    """Fetch InChI key + canonical SMILES — small structural metadata."""
    await bucket.acquire()
    try:
        r = await client.get(
            f"{PUBCHEM}/compound/cid/{cid}/property/InChIKey,CanonicalSMILES/JSON",
            timeout=20.0,
        )
    except httpx.RequestError:
        return {}
    if r.status_code != 200:
        return {}
    try:
        props = r.json().get("PropertyTable", {}).get("Properties", [{}])[0]
    except (json.JSONDecodeError, ValueError, IndexError):
        return {}
    return {
        "inchi_key": props.get("InChIKey", ""),
        "canonical_smiles": props.get("CanonicalSMILES", ""),
    }


# ─── Aura I/O ─────────────────────────────────────────────────────────────


async def fetch_compounds(
    driver, workspace: str, resume: bool, limit: int,
) -> list[str]:
    ws = _safe_label(workspace)
    cypher = (
        f"MATCH (c:`{ws}`:Compound) "
        f"WHERE c.scope = 'shared' "
    )
    if resume:
        cypher += "AND c.pubchem_cid IS NULL "
    cypher += "RETURN c.entity_id AS eid"
    if limit and limit > 0:
        cypher += f" LIMIT {limit}"

    out: list[str] = []
    async with driver.session() as s:
        result = await s.run(cypher)
        async for rec in result:
            if rec["eid"]:
                out.append(rec["eid"])
    return out


async def stamp_compound(
    driver, workspace: str, rows: list[dict],
) -> int:
    if not rows:
        return 0
    ws = _safe_label(workspace)
    cypher = (
        f"UNWIND $rows AS row "
        f"MATCH (c:`{ws}`:Compound {{entity_id: row.entity_id}}) "
        f"SET c.pubchem_cid = row.cid, "
        f"    c.inchi_key = coalesce(row.inchi_key, ''), "
        f"    c.canonical_smiles = coalesce(row.smiles, ''), "
        f"    c.aliases = coalesce(row.aliases, []) "
        f"RETURN count(c) AS c"
    )
    async with driver.session() as s:
        result = await s.run(cypher, rows=rows)
        rec = await result.single()
    return int(rec["c"]) if rec else 0


# ─── Progress ─────────────────────────────────────────────────────────────


def _load_progress() -> dict[str, Any]:
    if not PROGRESS_FILE.exists():
        return {}
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_progress(p: dict[str, Any]) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(p, sort_keys=True))


# ─── Orchestrator ─────────────────────────────────────────────────────────


async def run(
    *, limit: int, resume: bool, api_key: str, batch: int = 50,
) -> tuple[int, int]:
    load_dotenv(PROJECT_ROOT / ".env")
    workspace = os.environ.get("WORKSPACE", "unified_diet_kg")
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd = os.environ["NEO4J_PASSWORD"]

    bucket = TokenBucket(rate=5.0, capacity=5)  # PubChem ~5 RPS
    progress = _load_progress() if resume else {}

    matched = 0
    stamped = 0

    async with AsyncGraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        targets = await fetch_compounds(driver, workspace, resume, limit)
        print(f"Targets: {len(targets)} compound(s); resume={resume}", file=sys.stderr)

        async with httpx.AsyncClient(timeout=20.0) as client:
            t0 = time.time()
            for i in range(0, len(targets), batch):
                chunk = targets[i : i + batch]
                rows: list[dict] = []
                for eid in chunk:
                    if eid in progress and progress[eid] is None:
                        # Previously-confirmed no-match; skip without re-querying.
                        continue
                    cid = await name_to_cid(client, bucket, eid)
                    progress[eid] = cid
                    if cid is None:
                        continue
                    syns = await cid_synonyms(client, bucket, cid)
                    props = await cid_props(client, bucket, cid)
                    rows.append({
                        "entity_id": eid,
                        "cid": cid,
                        "inchi_key": props.get("inchi_key", ""),
                        "smiles": props.get("canonical_smiles", ""),
                        # Always include the original entity_id in aliases so it
                        # round-trips through the Layer-B alias matcher.
                        "aliases": list({eid, *syns}),
                    })
                if rows:
                    n = await stamp_compound(driver, workspace, rows)
                    stamped += n
                    matched += len(rows)

                _save_progress(progress)

                if (i + len(chunk)) % 200 == 0 or (i + len(chunk)) == len(targets):
                    elapsed = time.time() - t0
                    rate = (i + len(chunk)) / max(elapsed, 0.001)
                    print(
                        f"  progress: {i + len(chunk)}/{len(targets)} "
                        f"matched={matched} stamped={stamped} "
                        f"elapsed={elapsed:.1f}s ({rate:.1f}/s)",
                        file=sys.stderr,
                    )

    return matched, stamped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("NCBI_API_KEY", "")
    if not api_key:
        print("WARNING: NCBI_API_KEY unset; PubChem still works at lower RPS", file=sys.stderr)

    matched, stamped = asyncio.run(run(limit=args.limit, resume=args.resume, api_key=api_key))
    print(f"\nDone. matched={matched}, stamped={stamped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
