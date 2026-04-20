"""Unit tests for bootstrap_scope — uses a fake Neo4j driver.

Integration coverage (real Neo4j) lives in ``test_scope_enforcement.py``
and ``canary_smoke_test.py`` (both gated behind pytest marker
``integration`` / ``LIGHTRAG_RUN_INTEGRATION``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from bootstrap_scope import (
    EDGE_SCOPE_INDEX,
    NODE_SCOPE_INDEX,
    SHARED_SCOPE,
    count_untagged,
    create_indexes,
    tag_shared,
    verify_clean,
)


# ---------------------------------------------------------------------------
# Fake Neo4j driver — records every Cypher statement executed.
# ---------------------------------------------------------------------------


@dataclass
class _FakeRecord:
    data: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


@dataclass
class _FakeResult:
    records: list[_FakeRecord] = field(default_factory=list)

    def single(self) -> _FakeRecord:
        return self.records[0]

    def consume(self) -> None:  # pragma: no cover - trivial
        return None


class _FakeDriver:
    """In-memory stand-in that records Cypher calls and mutates
    node/rel counters on tag_shared writes."""

    def __init__(self, untagged_nodes: int = 0, untagged_rels: int = 0) -> None:
        self.cypher_log: list[tuple[str, dict[str, Any]]] = []
        self.untagged_nodes = untagged_nodes
        self.untagged_rels = untagged_rels

    def session(self) -> "_FakeSession":
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, driver: _FakeDriver) -> None:
        self._driver = driver

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def run(self, query: str, **params: Any) -> _FakeResult:
        self._driver.cypher_log.append((query, params))
        q = " ".join(query.split())
        if "n.scope IS NULL RETURN count(n)" in q:
            return _FakeResult([_FakeRecord({"c": self._driver.untagged_nodes})])
        if "r.scope IS NULL RETURN count(r)" in q:
            return _FakeResult([_FakeRecord({"c": self._driver.untagged_rels})])
        if "SET n.scope = $scope RETURN count(n)" in q:
            count = self._driver.untagged_nodes
            self._driver.untagged_nodes = 0
            return _FakeResult([_FakeRecord({"c": count})])
        if "SET r.scope = $scope RETURN count(r)" in q:
            count = self._driver.untagged_rels
            self._driver.untagged_rels = 0
            return _FakeResult([_FakeRecord({"c": count})])
        # CREATE INDEX ... or any other statement
        return _FakeResult([])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_count_untagged_reads_both_counters() -> None:
    driver = _FakeDriver(untagged_nodes=7722, untagged_rels=1185)
    n, r = count_untagged(driver, "unified_diet_kg")
    assert (n, r) == (7722, 1185)
    assert len(driver.cypher_log) == 2
    node_q = driver.cypher_log[0][0]
    rel_q = driver.cypher_log[1][0]
    assert "`unified_diet_kg`" in node_q
    assert "`unified_diet_kg`" in rel_q


@pytest.mark.unit
def test_tag_shared_sets_scope_and_returns_counts() -> None:
    driver = _FakeDriver(untagged_nodes=100, untagged_rels=50)
    tagged_n, tagged_r = tag_shared(driver, "unified_diet_kg")
    assert (tagged_n, tagged_r) == (100, 50)
    # After tagging, the fake driver has zero remaining.
    assert count_untagged(driver, "unified_diet_kg") == (0, 0)
    # Every write used the scope param.
    sets = [q for q, p in driver.cypher_log if "SET " in q]
    assert all(q.count("$scope") == 1 for q in sets)
    # And the param value was the shared scope.
    for q, p in driver.cypher_log:
        if "SET " in q:
            assert p.get("scope") == SHARED_SCOPE


@pytest.mark.unit
def test_tag_shared_is_idempotent() -> None:
    driver = _FakeDriver(untagged_nodes=5, untagged_rels=3)
    tag_shared(driver, "unified_diet_kg")
    # Re-running finds nothing to tag.
    tagged_n, tagged_r = tag_shared(driver, "unified_diet_kg")
    assert (tagged_n, tagged_r) == (0, 0)


@pytest.mark.unit
def test_create_indexes_uses_if_not_exists() -> None:
    driver = _FakeDriver()
    create_indexes(driver, "unified_diet_kg")
    index_statements = [q for q, _ in driver.cypher_log]
    assert any(NODE_SCOPE_INDEX in q and "IF NOT EXISTS" in q for q in index_statements)
    assert any(EDGE_SCOPE_INDEX in q and "IF NOT EXISTS" in q for q in index_statements)


@pytest.mark.unit
def test_verify_clean_raises_on_residual() -> None:
    driver = _FakeDriver(untagged_nodes=1, untagged_rels=0)
    with pytest.raises(RuntimeError, match="Bootstrap incomplete"):
        verify_clean(driver, "unified_diet_kg")


@pytest.mark.unit
def test_verify_clean_passes_on_zero() -> None:
    driver = _FakeDriver(untagged_nodes=0, untagged_rels=0)
    verify_clean(driver, "unified_diet_kg")  # no raise
