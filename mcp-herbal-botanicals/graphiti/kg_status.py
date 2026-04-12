"""KG analytics — node/edge breakdown, ingestion sources, growth rate tracking."""

import json
import os
import time

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://metro.proxy.rlwy.net:22971")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "demodemo")
SNAP_FILE = os.path.expanduser("~/.cache/kg-snapshot.json")

GRAPHITI_LABELS = {"Entity", "Episodic", "Community"}
GRAPHITI_RELS = {"MENTIONS", "RELATES_TO", "HAS_MEMBER", "IS_RELATED_TO"}


def main():
    d = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    s = d.session()

    W = 52
    print(f"╔{'═' * W}╗")
    print(f"║{'Unified Phytochemical KG — Status':^{W}}║")
    print(f"╠{'═' * W}╣")
    print(f"║  Neo4j: {NEO4J_URI:<{W - 10}}║")
    print(f"║  Time:  {time.strftime('%Y-%m-%d %H:%M:%S'):<{W - 10}}║")

    # --- Nodes ---
    print(f"╠{'═' * W}╣")
    print(f"║{'NODES BY LABEL':^{W}}║")
    print(f"╠{'─' * 28}┬{'─' * (W - 29)}╣")

    direct_n = 0
    graphiti_n = 0
    rows = s.run(
        "MATCH (n) RETURN labels(n)[0] AS label, COUNT(n) AS count ORDER BY count DESC"
    )
    for r in rows:
        label, cnt = r["label"], r["count"]
        src = "(graphiti)" if label in GRAPHITI_LABELS else "(direct)"
        if label in GRAPHITI_LABELS:
            graphiti_n += cnt
        else:
            direct_n += cnt
        print(f"║  {label:<26}│ {cnt:>8}  {src:<12}║")

    total_n = direct_n + graphiti_n
    print(f"╠{'─' * 28}┼{'─' * (W - 29)}╣")
    print(f"║  {'TOTAL NODES':<26}│ {total_n:>8}{' ' * 14}║")
    print(f"║    {'Direct-ingested':<24}│ {direct_n:>8}{' ' * 14}║")
    print(f"║    {'Graphiti-extracted':<24}│ {graphiti_n:>8}{' ' * 14}║")

    # --- Relationships ---
    print(f"╠{'═' * W}╣")
    print(f"║{'RELATIONSHIPS BY TYPE':^{W}}║")
    print(f"╠{'─' * 28}┬{'─' * (W - 29)}╣")

    direct_r = 0
    graphiti_r = 0
    rows = s.run(
        "MATCH ()-[r]->() RETURN type(r) AS type, COUNT(r) AS count ORDER BY count DESC"
    )
    for r in rows:
        rt, cnt = r["type"], r["count"]
        src = "(graphiti)" if rt in GRAPHITI_RELS else "(direct)"
        if rt in GRAPHITI_RELS:
            graphiti_r += cnt
        else:
            direct_r += cnt
        print(f"║  {rt:<26}│ {cnt:>8}  {src:<12}║")

    total_r = direct_r + graphiti_r
    print(f"╠{'─' * 28}┼{'─' * (W - 29)}╣")
    print(f"║  {'TOTAL RELATIONSHIPS':<26}│ {total_r:>8}{' ' * 14}║")

    # --- Graphiti Queue ---
    print(f"╠{'═' * W}╣")
    print(f"║{'GRAPHITI PROCESSING':^{W}}║")
    print(f"╠{'─' * 28}┬{'─' * (W - 29)}╣")

    ep_count = s.run("MATCH (e:Episodic) RETURN COUNT(e) AS c").single()["c"]
    ent_count = s.run("MATCH (e:Entity) RETURN COUNT(e) AS c").single()["c"]
    avg_ent = round(ent_count / max(ep_count, 1), 1)

    print(f"║  {'Episodes processed':<26}│ {ep_count:>8}{' ' * 14}║")
    print(f"║  {'Entities discovered':<26}│ {ent_count:>8}{' ' * 14}║")
    print(f"║  {'Avg entities/episode':<26}│ {avg_ent:>8}{' ' * 14}║")

    # --- Growth Tracking ---
    print(f"╠{'═' * W}╣")
    print(f"║{'GROWTH TRACKING':^{W}}║")
    print(f"╠{'─' * 28}┬{'─' * (W - 29)}╣")

    now = time.time()
    current = {
        "nodes": total_n,
        "rels": total_r,
        "entities": ent_count,
        "episodes": ep_count,
        "ts": now,
    }

    prev = None
    try:
        with open(SNAP_FILE) as f:
            prev = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    os.makedirs(os.path.dirname(SNAP_FILE), exist_ok=True)
    with open(SNAP_FILE, "w") as f:
        json.dump(current, f)

    if prev:
        dt = max(now - prev["ts"], 1)
        mins = dt / 60.0
        dn = total_n - prev["nodes"]
        dr = total_r - prev["rels"]
        de = ent_count - prev["entities"]
        dep = ep_count - prev["episodes"]
        rate_n = dn / mins if mins > 0.01 else 0
        rate_e = dep / mins if mins > 0.01 else 0

        interval = f"{mins:.0f}m ago" if mins < 60 else f"{mins / 60:.1f}h ago"
        print(f"║  {'Last snapshot':<26}│ {interval:>22}║")
        print(f"║  {'Δ Nodes':<26}│ {dn:>+8}{' ' * 14}║")
        print(f"║  {'Δ Relationships':<26}│ {dr:>+8}{' ' * 14}║")
        print(f"║  {'Δ Graphiti entities':<26}│ {de:>+8}{' ' * 14}║")
        print(f"║  {'Δ Graphiti episodes':<26}│ {dep:>+8}{' ' * 14}║")
        print(f"║  {'Node growth rate':<26}│ {rate_n:>+8.1f}/min{' ' * 8}║")
        print(f"║  {'Episode process rate':<26}│ {rate_e:>+8.1f}/min{' ' * 8}║")
    else:
        print(f"║  {'First snapshot saved':<26}│ {'(run again to see Δ)':>22}║")

    print(f"╚{'═' * W}╝")

    s.close()
    d.close()


if __name__ == "__main__":
    main()
