#!/usr/bin/env python3
"""Keep the Aura Free instance from auto-pausing, without changing its size.

[PRINCIPAL-DIRECTED 2026-10-12] Aura Free pauses after 72 h of inactivity and
deletes an instance paused for 30 days. Neo4j's sources disagree on whether reads
count as activity, so this does a WRITE — but a property-only write on the
existing WorkspaceMeta node, because the graph sits at the Free node cap
(199,840 of ~200k) and must not grow.

Evidence, not claims (CTO #14245):
  * node AND relationship counts are read before and after; any delta FAILS;
  * a missing WorkspaceMeta node (a MATCH that finds nothing writes nothing) FAILS
    instead of reporting a keep-alive that Aura never saw;
  * if the previous successful keep-alive is older than 48 h, the write still
    happens (a missed day must not also cost the instance) and then the run FAILS
    so the gap is visible before the 72 h pause;
  * over the Free cap FAILS.

Never prints credentials. Exit 0 only when every assertion holds.

Usage (env NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD; optional NEO4J_DATABASE,
WORKSPACE):  python scripts/ci/aura_keepalive.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

FREE_NODE_CAP = 200_000
MAX_GAP_HOURS = 48.0

_KEEPALIVE = (
    "MATCH (m:WorkspaceMeta {workspace: $workspace}) "
    "WITH m, m.keepalive_at AS prev "
    "SET m.keepalive_at = datetime() "
    "RETURN prev, m.keepalive_at AS at"
)


class KeepAliveError(RuntimeError):
    """The keep-alive did not provably happen, or changed the graph's size."""


def _count(session: Any, cypher: str) -> int:
    return int(session.run(cypher).single()["c"])


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if hasattr(value, "to_native"):  # neo4j.time.DateTime
        value = value.to_native()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def keepalive(driver: Any, *, workspace: str, database: str | None = None) -> dict[str, Any]:
    kw = {"database": database} if database else {}
    with driver.session(**kw) as s:
        nodes_before = _count(s, "MATCH (n) RETURN count(n) AS c")
        rels_before = _count(s, "MATCH ()-[r]->() RETURN count(r) AS c")
        res = s.run(_KEEPALIVE, workspace=workspace)
        rec = res.single()
        updated = res.consume().counters.properties_set
        nodes_after = _count(s, "MATCH (n) RETURN count(n) AS c")
        rels_after = _count(s, "MATCH ()-[r]->() RETURN count(r) AS c")

    if rec is None or updated < 1:
        raise KeepAliveError(
            f"no WorkspaceMeta node for workspace {workspace!r}: nothing was written, "
            "so Aura saw no activity"
        )
    if nodes_before != nodes_after or rels_before != rels_after:
        raise KeepAliveError(
            f"graph size changed during keep-alive: nodes {nodes_before}->{nodes_after}, "
            f"rels {rels_before}->{rels_after} (the keep-alive must be property-only)"
        )
    if nodes_after > FREE_NODE_CAP:
        raise KeepAliveError(f"node count {nodes_after} is over the Free cap {FREE_NODE_CAP}")

    prev, at = _as_utc(rec["prev"]), _as_utc(rec["at"])
    gap_hours = None if prev is None else round((at - prev).total_seconds() / 3600, 2)
    out = {
        "workspace": workspace,
        "keepalive_at": at.isoformat() if at else None,
        "previous_keepalive_at": prev.isoformat() if prev else None,
        "gap_hours": gap_hours,
        "nodes_before": nodes_before,
        "nodes_after": nodes_after,
        "rels_before": rels_before,
        "rels_after": rels_after,
        "headroom": FREE_NODE_CAP - nodes_after,
    }
    if gap_hours is not None and gap_hours > MAX_GAP_HOURS:
        raise KeepAliveError(
            f"last successful keep-alive was {gap_hours} h before this one (> {MAX_GAP_HOURS} h): "
            "a scheduled run was missed; Aura pauses at 72 h. This run DID write. "
            + json.dumps(out)
        )
    return out


def main() -> int:
    missing = [k for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD") if not os.environ.get(k)]
    if missing:
        print(f"::error::aura keep-alive: missing env {missing} — refusing to report a keep-alive that never ran")
        return 1
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
    )
    try:
        out = keepalive(
            driver,
            workspace=os.environ.get("WORKSPACE", "unified_diet_kg"),
            database=os.environ.get("NEO4J_DATABASE") or None,
        )
    except KeepAliveError as e:
        print(f"::error::aura keep-alive FAILED: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 - auth/paused/network: say which, never the message (may hold the URI)
        print(f"::error::aura keep-alive FAILED: could not run against Aura ({type(e).__name__})")
        return 1
    finally:
        driver.close()
    print("aura keep-alive OK " + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
