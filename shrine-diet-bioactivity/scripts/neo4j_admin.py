#!/usr/bin/env python3
"""Neo4j admin commands behind the Makefile's neo4j-* targets.

Credentials come from the environment only (NEO4J_URI, NEO4J_USERNAME,
NEO4J_PASSWORD), never from argv: a command-line argument is readable by every
user on the host for as long as the process runs (CTO #17617/#17618).

Usage:
    python3 scripts/neo4j_admin.py check     # node/edge counts
    python3 scripts/neo4j_admin.py stats     # counts by label and rel type
    python3 scripts/neo4j_admin.py status    # full breakdown + totals
    python3 scripts/neo4j_admin.py watch     # poll counts every 30s
    python3 scripts/neo4j_admin.py shell     # minimal Cypher REPL
    python3 scripts/neo4j_admin.py clear     # DELETE everything (loopback DB only)
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import sys
import time
from urllib.parse import urlsplit

LOOPBACK_NAMES = {"localhost"}


def _env() -> tuple[str, str, str]:
    uri = os.environ.get("NEO4J_URI", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not password:
        sys.exit(
            "NEO4J_URI and NEO4J_PASSWORD must be set in the environment "
            "(Infisical prod /research/shrine-diet-bioactivity)."
        )
    return uri, os.environ.get("NEO4J_USERNAME") or "neo4j", password


def is_loopback(uri: str) -> bool:
    host = urlsplit(uri).hostname or ""
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _driver():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("The neo4j package is not installed (pip install neo4j).")
    uri, user, password = _env()
    return GraphDatabase.driver(uri, auth=(user, password)), uri


def _totals(s) -> tuple[int, int]:
    n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return n, r


def cmd_check() -> None:
    d, uri = _driver()
    with d, d.session() as s:
        print("=== Neo4j KG Status ===")
        print(f"URI: {uri}")
        for r in s.run("MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC"):
            print(f"  {r['type']}: {r['count']}")
        for r in s.run("MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS count ORDER BY count DESC"):
            print(f"  {r['rel']}: {r['count']}")
        n, r = _totals(s)
        print(f"Total: {n} nodes, {r} relationships")


def cmd_stats() -> None:
    d, _ = _driver()
    with d, d.session() as s:
        print("=== Detailed KG Stats ===")
        for r in s.run("MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC"):
            print(f"  Nodes [{r['label']}]: {r['count']}")
        for r in s.run("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY count DESC"):
            print(f"  Edges [{r['type']}]: {r['count']}")


def cmd_status() -> None:
    d, _ = _driver()
    with d, d.session() as s:
        print("=== KG Status by Workspace ===")
        for r in s.run("MATCH (n) RETURN labels(n) AS labels, count(n) AS count ORDER BY count DESC"):
            print(f"  Nodes {r['labels']}: {r['count']}")
        print()
        for r in s.run("MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY count DESC"):
            print(f"  Edges [{r['type']}]: {r['count']}")
        n, r = _totals(s)
        print(f"\nTotal: {n} nodes, {r} relationships")


def cmd_watch() -> None:
    d, uri = _driver()
    print(f"Watching KG growth at {uri} (Ctrl+C to stop)")
    with d:
        while True:
            try:
                with d.session() as s:
                    n, r = _totals(s)
                print(f"{datetime.datetime.now():%H:%M:%S} {n} nodes, {r} edges")
            except Exception as exc:  # keep polling, but never silently
                print(f"{datetime.datetime.now():%H:%M:%S} poll failed: {type(exc).__name__}")
            time.sleep(30)


def cmd_shell() -> None:
    d, _ = _driver()
    with d, d.session() as s:
        print("Connected. Enter Cypher (empty line to quit):")
        while q := input("> ").strip():
            for r in s.run(q):
                print(r.data())


def cmd_clear() -> None:
    uri, _, _ = _env()
    if not is_loopback(uri):
        sys.exit(f"neo4j-clear refuses {urlsplit(uri).hostname!r}: loopback test DB only.")
    if input(f"Type 'yes' to delete ALL data in {uri}: ").strip() != "yes":
        print("Cancelled.")
        return
    d, _ = _driver()
    with d, d.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    print("All nodes and relationships deleted.")


COMMANDS = {
    "check": cmd_check, "stats": cmd_stats, "status": cmd_status,
    "watch": cmd_watch, "shell": cmd_shell, "clear": cmd_clear,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]]()
