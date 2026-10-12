"""Aura Free keep-alive [PRINCIPAL-DIRECTED 2026-10-12]: keep the instance from
auto-pausing (72 h inactivity) WITHOUT changing the node count, which sits at the
Free-tier cap (199,840 of ~200k).

The keep-alive is a property-only write on the existing WorkspaceMeta node, with
node and relationship counts asserted unchanged before vs after. Unit-level: a
fake driver records every Cypher statement. No network.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/ci/aura_keepalive.py"
WORKFLOW = REPO_ROOT / ".github/workflows/aura-keepalive.yml"


def _load():
    spec = importlib.util.spec_from_file_location("aura_keepalive", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Rec(dict):
    def __getitem__(self, k):
        return dict.__getitem__(self, k)


class _Result:
    def __init__(self, rec, updated=0):
        self._rec, self._updated = rec, updated

    def single(self):
        return self._rec

    def consume(self):
        class _C:
            pass

        c = _C()

        class _Counters:
            properties_set = self._updated

        c.counters = _Counters()
        return c


class _Session:
    def __init__(self, world):
        self.w = world

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.w["cypher"].append(cypher)
        c = " ".join(cypher.split())
        if c.startswith("MATCH (n) RETURN count(n)"):
            n = self.w["nodes"].pop(0)
            return _Result(_Rec(c=n))
        if c.startswith("MATCH ()-[r]->() RETURN count(r)"):
            r = self.w["rels"].pop(0)
            return _Result(_Rec(c=r))
        if "SET m.keepalive_at" in c:
            if not self.w["meta"]:
                return _Result(None, updated=0)
            return _Result(_Rec(prev=self.w["prev"], at=self.w["now"]), updated=1)
        raise AssertionError(f"unexpected cypher: {c}")


class _Driver:
    def __init__(self, world):
        self.w = world

    def session(self, **kw):
        self.w["session_kwargs"].append(kw)
        return _Session(self.w)


def _world(nodes=(199840, 199840), rels=(221009, 221009), meta=True, prev=None) -> dict[str, Any]:
    from datetime import datetime

    return {
        "nodes": list(nodes), "rels": list(rels), "meta": meta, "prev": prev,
        "now": datetime(2026, 10, 12, 12, 0, tzinfo=UTC), "cypher": [], "session_kwargs": [],
    }


def test_keepalive_writes_one_property_and_keeps_counts() -> None:
    mod = _load()
    w = _world()
    out = mod.keepalive(_Driver(w), workspace="unified_diet_kg")
    assert out["nodes_before"] == out["nodes_after"] == 199840
    assert out["rels_before"] == out["rels_after"] == 221009
    assert out["headroom"] == 200000 - 199840
    writes = [c for c in w["cypher"] if "SET" in c.upper()]
    assert len(writes) == 1


def test_keepalive_never_creates_merges_or_deletes() -> None:
    mod = _load()
    w = _world()
    mod.keepalive(_Driver(w), workspace="unified_diet_kg")
    for c in w["cypher"]:
        assert not re.search(r"\b(CREATE|MERGE|DELETE|DETACH|REMOVE)\b", c, re.IGNORECASE), c


def test_missing_workspace_meta_is_a_failure_not_a_silent_noop() -> None:
    # A MATCH that finds nothing writes nothing: the keep-alive would report
    # success while Aura saw no write. It must fail instead.
    mod = _load()
    with pytest.raises(mod.KeepAliveError, match="WorkspaceMeta"):
        mod.keepalive(_Driver(_world(meta=False)), workspace="unified_diet_kg")


@pytest.mark.parametrize("nodes,rels", [((199840, 199841), (221009, 221009)), ((199840, 199840), (221009, 221008))])
def test_count_drift_is_a_failure(nodes, rels) -> None:
    mod = _load()
    with pytest.raises(mod.KeepAliveError, match="changed"):
        mod.keepalive(_Driver(_world(nodes=nodes, rels=rels)), workspace="unified_diet_kg")


def test_over_the_free_cap_is_reported_as_a_failure() -> None:
    mod = _load()
    with pytest.raises(mod.KeepAliveError, match="cap"):
        mod.keepalive(_Driver(_world(nodes=(200001, 200001))), workspace="unified_diet_kg")


# ─── workflow ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _on(wf):
    return wf.get("on", wf.get(True))


def test_runs_on_a_schedule_well_inside_72_hours_and_on_demand(wf) -> None:
    on = _on(wf)
    assert "workflow_dispatch" in on
    crons = [c["cron"] for c in on["schedule"]]
    assert crons
    # Daily or more often: the day-of-month / day-of-week fields must be '*'.
    for c in crons:
        fields = c.split()
        assert len(fields) == 5 and fields[2] == "*" and fields[4] == "*", c


def test_uses_the_mirrored_aura_secrets_and_fails_loudly_without_them(wf) -> None:
    text = WORKFLOW.read_text()
    for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        assert f"secrets.{k}" in text
    job = next(iter(wf["jobs"].values()))
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "scripts/ci/aura_keepalive.py" in runs
    assert "missing" in runs.lower() and "exit 1" in runs


# ─── the 48-hour "last successful keep-alive" assertion (CTO #14245) ───────


def test_a_recent_previous_keepalive_passes() -> None:
    from datetime import datetime

    mod = _load()
    out = mod.keepalive(
        _Driver(_world(prev=datetime(2026, 10, 11, 12, 0, tzinfo=UTC))), workspace="unified_diet_kg"
    )
    assert out["gap_hours"] == pytest.approx(24.0)


def test_first_ever_keepalive_has_no_gap_and_passes() -> None:
    mod = _load()
    out = mod.keepalive(_Driver(_world(prev=None)), workspace="unified_diet_kg")
    assert out["gap_hours"] is None


def test_a_gap_over_48h_still_writes_but_fails_loud() -> None:
    from datetime import datetime

    mod = _load()
    w = _world(prev=datetime(2026, 10, 9, 0, 0, tzinfo=UTC))  # 84 h earlier
    with pytest.raises(mod.KeepAliveError, match="last successful keep-alive"):
        mod.keepalive(_Driver(w), workspace="unified_diet_kg")
    # The write still happened first: a missed day must not also cost the instance.
    assert sum("SET m.keepalive_at" in c for c in w["cypher"]) == 1


def test_driver_construction_failure_is_red_with_type_only_no_host(monkeypatch, capsys) -> None:
    import neo4j

    mod = _load()
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://secret-host.databases.neo4j.io")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")

    def boom(*a, **k):
        raise ValueError("cannot resolve secret-host.databases.neo4j.io")

    monkeypatch.setattr(neo4j.GraphDatabase, "driver", boom)
    assert mod.main() == 1
    out = capsys.readouterr()
    assert "ValueError" in out.out
    assert "secret-host" not in out.out + out.err


def test_summary_reports_relationship_headroom() -> None:
    mod = _load()
    out = mod.keepalive(_Driver(_world()), workspace="unified_diet_kg")
    assert out["rel_headroom"] == 400000 - 221009
