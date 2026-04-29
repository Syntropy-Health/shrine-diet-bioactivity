"""Unit tests — verify ingest_direct.py tags every node and edge with `scope`.

Without this, direct-Cypher ingestion (the speed-optimized fallback) writes
unscoped data into Aura, which would re-create the bootstrap_scope migration
debt every time. These tests pin the contract: scope is always present on
the row, default is 'shared', explicit overrides win.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from ingest_direct import (  # type: ignore[import-not-found]
    _stamp_scope,
    upsert_entities,
    upsert_relationships,
)


# ─── _stamp_scope ─────────────────────────────────────────────────────────


def test_stamp_scope_adds_default_to_unscoped_rows():
    rows = [{"entity_id": "Ginger"}, {"entity_id": "Curcumin"}]
    out = _stamp_scope(rows, "shared")
    assert all(r["scope"] == "shared" for r in out)


def test_stamp_scope_preserves_existing_scope():
    rows = [{"entity_id": "X", "scope": "tenant:clinic-a"}]
    out = _stamp_scope(rows, "shared")
    assert out[0]["scope"] == "tenant:clinic-a"


def test_stamp_scope_does_not_mutate_input():
    rows = [{"entity_id": "Y"}]
    _stamp_scope(rows, "shared")
    assert "scope" not in rows[0]


def test_stamp_scope_idempotent():
    rows = [{"entity_id": "Z"}]
    once = _stamp_scope(rows, "shared")
    twice = _stamp_scope(once, "shared")
    assert twice == once


# ─── upsert_entities ──────────────────────────────────────────────────────


def test_upsert_entities_writes_scope_via_set_plus_equals():
    """Every UNWIND row carries scope='shared'; SET n += row propagates it."""
    session = MagicMock()
    session.run.return_value = MagicMock()
    entities = [
        {"entity_id": "Ginger", "entity_type": "Herb", "description": "x"},
        {"entity_id": "Curcumin", "entity_type": "Compound", "description": "y"},
    ]
    upsert_entities(session, entities, workspace="unified_diet_kg", scope="shared")

    # Inspect every call's rows arg — every row must have scope='shared'.
    assert session.run.call_count >= 1
    for call in session.run.call_args_list:
        rows = call.kwargs.get("rows") or call.args[1]["rows"] if len(call.args) > 1 else call.kwargs["rows"]
        for row in rows:
            assert row["scope"] == "shared"


def test_upsert_entities_respects_explicit_tenant_scope():
    session = MagicMock()
    session.run.return_value = MagicMock()
    upsert_entities(
        session,
        [{"entity_id": "X", "entity_type": "Herb", "description": "d"}],
        workspace="ws",
        scope="tenant:clinic-a",
    )
    rows = session.run.call_args_list[0].kwargs["rows"]
    assert rows[0]["scope"] == "tenant:clinic-a"


# ─── upsert_relationships ─────────────────────────────────────────────────


def test_upsert_relationships_sets_scope_in_cypher_and_rows():
    """Both the Cypher SET clause and the row payload must carry scope."""
    session = MagicMock()
    session.run.return_value = MagicMock()
    rels = [
        {
            "src_id": "Ginger", "tgt_id": "Curcumin", "rel_type": "INTERACTS_WITH",
            "description": "test", "keywords": "k", "weight": 1.0,
            "file_path": "test", "source_id": "test:rel", "evidence_tier": "",
        },
    ]
    upsert_relationships(session, rels, workspace="ws", scope="shared")

    cypher_arg = session.run.call_args_list[0].args[0]
    assert "r.scope = row.scope" in cypher_arg
    rows = session.run.call_args_list[0].kwargs["rows"]
    assert rows[0]["scope"] == "shared"


def test_upsert_relationships_does_not_overwrite_explicit_row_scope():
    session = MagicMock()
    session.run.return_value = MagicMock()
    rels = [
        {
            "src_id": "A", "tgt_id": "B", "rel_type": "RELATED",
            "description": "d", "keywords": "k", "weight": 1.0,
            "file_path": "", "source_id": "", "evidence_tier": "",
            "scope": "tenant:special",
        }
    ]
    upsert_relationships(session, rels, workspace="ws", scope="shared")
    rows = session.run.call_args_list[0].kwargs["rows"]
    assert rows[0]["scope"] == "tenant:special"
