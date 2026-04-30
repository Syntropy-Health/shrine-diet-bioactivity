"""Unit tests for the typed endpoints — POST /traverse, /hdi_check, /bilingual_term.

These endpoints run direct Cypher against Aura via the Neo4j driver (rather
than going through LightRAG's NL synthesis). Tests mock ``_get_driver`` so
they exercise the Cypher construction + scope filter + allow-list validation
without needing a live Neo4j.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """TestClient with mocked driver + audit + scope-preflight."""
    import scoped_server as ss
    from audit_log import AuditLog

    fake_session = MagicMock()
    fake_session.run = MagicMock()
    fake_session.__enter__ = MagicMock(return_value=fake_session)
    fake_session.__exit__ = MagicMock(return_value=False)

    fake_driver = MagicMock()
    fake_driver.session = MagicMock(return_value=fake_session)

    async def _fake_build():
        rag = MagicMock()
        rag.finalize_storages = MagicMock(return_value=None)

        async def _noop_finalize():
            return None

        rag.finalize_storages = _noop_finalize
        return rag

    monkeypatch.setattr(ss, "_preflight_scope_check", lambda: None)
    monkeypatch.setattr(ss, "_build_scoped_rag", _fake_build)
    monkeypatch.setattr(ss, "_audit", AuditLog(db_path=tmp_path / "audit.db"))
    monkeypatch.setattr(ss, "_get_driver", lambda: fake_driver)

    with TestClient(ss.app) as c:
        c._fake_session = fake_session  # type: ignore[attr-defined]
        c._fake_driver = fake_driver  # type: ignore[attr-defined]
        yield c


def _result_with_records(records: list[dict[str, Any]]) -> MagicMock:
    """Build a synchronous neo4j-like Result that yields the given records."""
    res = MagicMock()
    res.__iter__ = lambda self: iter(
        [_record(d) for d in records]
    )
    return res


def _record(d: dict[str, Any]) -> MagicMock:
    rec = MagicMock()
    rec.__getitem__ = lambda self, k: d[k]
    rec.get = lambda k, default=None: d.get(k, default)
    rec.data = lambda: d
    return rec


# ─── POST /traverse ───────────────────────────────────────────────────────


def test_traverse_rejects_unknown_start_label(client: TestClient) -> None:
    resp = client.post("/traverse", json={
        "start_label": "EvilLabel; DROP DATABASE",
        "edge_types": ["TARGETS_PROTEIN"],
        "seed": "Curcumin",
        "direction": "outbound",
        "depth": 1,
        "top_k": 10,
    })
    assert resp.status_code == 400
    assert "label" in resp.text.lower()


def test_traverse_rejects_unknown_edge_type(client: TestClient) -> None:
    resp = client.post("/traverse", json={
        "start_label": "Compound",
        "edge_types": ["FORGED_EDGE"],
        "seed": "Curcumin",
        "direction": "outbound",
        "depth": 1,
        "top_k": 10,
    })
    assert resp.status_code == 400


def test_traverse_rejects_invalid_direction(client: TestClient) -> None:
    resp = client.post("/traverse", json={
        "start_label": "Compound",
        "edge_types": ["TARGETS_PROTEIN"],
        "seed": "Curcumin",
        "direction": "sideways",
        "depth": 1,
        "top_k": 10,
    })
    assert resp.status_code == 422  # pydantic Literal mismatch


def test_traverse_depth_1_outbound_emits_typed_cypher(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]

    resp = client.post("/traverse", json={
        "start_label": "Compound",
        "edge_types": ["TARGETS_PROTEIN"],
        "seed": "Curcumin",
        "direction": "outbound",
        "depth": 1,
        "top_k": 10,
    })
    assert resp.status_code == 200, resp.text
    cypher = client._fake_session.run.call_args.args[0]  # type: ignore[attr-defined]
    # The Cypher must scope-filter on both endpoints + relationship
    assert "start.scope IN $scope_filter" in cypher
    assert "tgt.scope IN $scope_filter" in cypher
    assert "r.scope IN $scope_filter" in cypher
    # The label and edge type must be inlined (validated allow-list)
    assert ":`Compound`" in cypher
    assert ":`TARGETS_PROTEIN`" in cypher
    # Direction = outbound
    assert "(start)-[r:`TARGETS_PROTEIN`]->(tgt)" in cypher


def test_traverse_depth_1_inbound_uses_reverse_arrow(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]

    resp = client.post("/traverse", json={
        "start_label": "Food",
        "edge_types": ["FOUND_IN_FOOD"],
        "seed": "Garlic",
        "direction": "inbound",
        "depth": 1,
        "top_k": 5,
    })
    assert resp.status_code == 200, resp.text
    cypher = client._fake_session.run.call_args.args[0]  # type: ignore[attr-defined]
    assert "(start)<-[r:`FOUND_IN_FOOD`]-(tgt)" in cypher


def test_traverse_depth_2_chain_uses_two_typed_edges(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]

    resp = client.post("/traverse", json={
        "start_label": "Compound",
        "edge_types": ["TARGETS_PROTEIN", "ASSOCIATED_WITH_DISEASE"],
        "seed": "Aspirin",
        "direction": "outbound",
        "depth": 2,
        "top_k": 10,
    })
    assert resp.status_code == 200
    cypher = client._fake_session.run.call_args.args[0]  # type: ignore[attr-defined]
    assert "[r1:`TARGETS_PROTEIN`]" in cypher
    assert "[r2:`ASSOCIATED_WITH_DISEASE`]" in cypher
    assert "mid.scope IN $scope_filter" in cypher


def test_traverse_depth_2_requires_two_edge_types(client: TestClient) -> None:
    resp = client.post("/traverse", json={
        "start_label": "Compound",
        "edge_types": ["TARGETS_PROTEIN"],  # only 1
        "seed": "Aspirin",
        "direction": "outbound",
        "depth": 2,
        "top_k": 10,
    })
    assert resp.status_code == 400


def test_traverse_returns_typed_chains(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([
        {
            "src_id": "Curcumin", "tgt_id": "TNF",
            "rel_type": "TARGETS_PROTEIN",
            "description": "binds NF-kB pathway",
            "evidence_tier": "experimental",
            "source_id": "duke:targets_protein",
        },
        {
            "src_id": "Curcumin", "tgt_id": "COX2",
            "rel_type": "TARGETS_PROTEIN",
            "description": "inhibition",
            "evidence_tier": "clinical",
            "source_id": "cmaup:compound_target",
        },
    ])  # type: ignore[attr-defined]

    resp = client.post("/traverse", json={
        "start_label": "Compound",
        "edge_types": ["TARGETS_PROTEIN"],
        "seed": "Curcumin",
        "direction": "outbound",
        "depth": 1,
        "top_k": 10,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "chains" in body
    assert len(body["chains"]) == 2
    assert body["chains"][0]["edges"][0]["src_id"] == "Curcumin"
    assert body["chains"][0]["edges"][0]["tgt_id"] == "TNF"
    assert body["raw_subgraph_edge_count"] == 2


def test_traverse_passes_seed_and_scope_filter_as_params(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]
    resp = client.post("/traverse", json={
        "start_label": "Compound",
        "edge_types": ["TARGETS_PROTEIN"],
        "seed": "Curcumin",
        "direction": "outbound",
        "depth": 1,
        "top_k": 10,
        "scope_filter": ["shared", "tenant:alpha"],
    })
    assert resp.status_code == 200
    kwargs = client._fake_session.run.call_args.kwargs  # type: ignore[attr-defined]
    assert kwargs["seed"] == "Curcumin"
    assert kwargs["scope_filter"] == ["shared", "tenant:alpha"]
    assert kwargs["top_k"] == 10


# ─── POST /hdi_check ──────────────────────────────────────────────────────


def test_hdi_check_returns_found_when_match(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([{
        "severity": "moderate",
        "mechanism_class": "CYP450",
        "evidence_tier": "clinical",
        "source_id": "hdi-safe-50:warfarin-ginkgo",
    }])  # type: ignore[attr-defined]

    resp = client.post("/hdi_check", json={"drug": "warfarin", "herb": "Ginkgo biloba"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["severity"] == "moderate"
    assert body["mechanism_class"] == "CYP450"
    assert body["evidence_tier"] == "clinical"


def test_hdi_check_returns_not_found_when_no_match(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]
    resp = client.post("/hdi_check", json={"drug": "x", "herb": "y"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["severity"] is None


def test_hdi_check_rejects_empty_inputs(client: TestClient) -> None:
    resp = client.post("/hdi_check", json={"drug": "", "herb": "y"})
    assert resp.status_code == 422


def test_hdi_check_uses_case_insensitive_match(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]
    resp = client.post("/hdi_check", json={"drug": "Warfarin", "herb": "GINKGO BILOBA"})
    assert resp.status_code == 200
    cypher = client._fake_session.run.call_args.args[0]  # type: ignore[attr-defined]
    assert "toLower" in cypher  # case-insensitive on entity_id


# ─── POST /bilingual_term ─────────────────────────────────────────────────


def test_bilingual_term_resolves_chinese_to_triple(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([{
        "english": "Coptis chinensis",
        "chinese": "黄连",
        "pinyin": "huang lian",
    }])  # type: ignore[attr-defined]

    resp = client.post("/bilingual_term", json={"term": "黄连"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["chinese"] == "黄连"
    assert body["english"] == "Coptis chinensis"
    assert body["pinyin"] == "huang lian"
    assert body["source"] == "symmap"


def test_bilingual_term_returns_empty_when_unknown(client: TestClient) -> None:
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]
    resp = client.post("/bilingual_term", json={"term": "unknown-term"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["english"] is None
    assert body["chinese"] is None
    assert body["pinyin"] is None


def test_bilingual_term_searches_all_three_aliases(client: TestClient) -> None:
    """Cypher must check entity_id, chinese_name, pinyin_name (case-insensitive)."""
    client._fake_session.run.return_value = _result_with_records([])  # type: ignore[attr-defined]
    resp = client.post("/bilingual_term", json={"term": "huang lian"})
    assert resp.status_code == 200
    cypher = client._fake_session.run.call_args.args[0]  # type: ignore[attr-defined]
    assert "entity_id" in cypher
    assert "chinese_name" in cypher
    assert "pinyin_name" in cypher
    assert "toLower" in cypher
