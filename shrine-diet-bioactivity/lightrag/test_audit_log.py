"""Unit tests for audit_log — temp SQLite DB, no server dependency."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from audit_log import AuditLog, AuditRow, hash_query


@pytest.fixture()
def audit_db(tmp_path: Path) -> Path:
    """Disposable audit DB in a tmp dir."""
    return tmp_path / "mcp_audit.db"


@pytest.mark.unit
def test_emit_ok_row(audit_db: Path) -> None:
    log = AuditLog(db_path=audit_db)
    with log.record(
        tool="semantic-search",
        scope_filter=["shared", "tenant:clinic-a"],
        tenant_id="clinic-a",
        query_body={"query": "hello", "mode": "hybrid"},
    ) as row:
        row.result_count = 42
        row.token_usage = 1_234

    rows = _dump_rows(audit_db)
    assert len(rows) == 1
    r = rows[0]
    assert r["tenant_id"] == "clinic-a"
    assert r["tool"] == "semantic-search"
    assert r["status"] == "ok"
    assert r["error_class"] is None
    assert r["result_count"] == 42
    assert r["token_usage"] == 1_234
    assert json.loads(r["scope_filter"]) == ["shared", "tenant:clinic-a"]
    assert r["query_hash"] is not None
    assert r["latency_ms"] >= 0


@pytest.mark.unit
def test_emit_error_row_captures_exception(audit_db: Path) -> None:
    log = AuditLog(db_path=audit_db)
    with pytest.raises(ValueError):
        with log.record(
            tool="semantic-search",
            scope_filter=["shared"],
        ):
            raise ValueError("boom")

    rows = _dump_rows(audit_db)
    assert len(rows) == 1
    assert rows[0]["status"] == "error"
    assert rows[0]["error_class"] == "ValueError"


@pytest.mark.unit
def test_emit_swallows_audit_failure(audit_db: Path) -> None:
    """A broken DB path must not propagate to the caller."""
    # Point the log at a directory that can't be created (root-owned on
    # most systems). Even if we can create it, the real emit should fail
    # silently — not raise.
    log = AuditLog(db_path=audit_db)
    # Corrupt the DB file so writes fail.
    audit_db.write_bytes(b"not a sqlite file")

    # emit must not raise
    with log.record(tool="x", scope_filter=["shared"]) as _:
        pass


@pytest.mark.unit
def test_query_hash_is_stable_regardless_of_key_order() -> None:
    a = hash_query({"query": "hello", "mode": "hybrid", "top_k": 60})
    b = hash_query({"top_k": 60, "mode": "hybrid", "query": "hello"})
    assert a == b
    assert len(a) == 64  # sha-256 hex


@pytest.mark.unit
def test_query_hash_differs_for_different_queries() -> None:
    a = hash_query({"query": "hello"})
    b = hash_query({"query": "world"})
    assert a != b


@pytest.mark.unit
def test_tenant_id_null_is_audited(audit_db: Path) -> None:
    log = AuditLog(db_path=audit_db)
    with log.record(
        tool="semantic-search",
        scope_filter=["shared"],
        tenant_id=None,
        query_body={"query": "shared-only"},
    ) as _:
        pass
    rows = _dump_rows(audit_db)
    assert rows[0]["tenant_id"] is None


@pytest.mark.unit
def test_row_latency_increases_with_time() -> None:
    import time

    row = AuditRow(tool="x", scope_filter=["shared"])
    time.sleep(0.02)
    assert row.latency_ms() >= 15  # allow jitter; should be ~20ms


def _dump_rows(db_path: Path) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM mcp_audit ORDER BY id")
        return [dict(row) for row in cur.fetchall()]
