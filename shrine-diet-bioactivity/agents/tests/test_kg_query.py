# shrine-diet-bioactivity/agents/tests/test_kg_query.py
"""KG-query tool tests — exercises both LightRAG and SQLite fallback paths."""
import pytest
from unittest.mock import patch

from agents.tools.kg_query import kg_query, KGQueryError  # type: ignore[import-not-found]
from agents.models import KGResult


def test_kg_query_falls_back_to_sqlite_on_lightrag_unreachable():
    with patch("agents.tools.kg_query._lightrag_query", side_effect=KGQueryError("unreachable")):
        result = kg_query("ginger nausea evidence", mode="hybrid")
    assert isinstance(result, KGResult)
    # SQLite fallback should still find Duke ginger entries
    assert result.raw_subgraph_node_count > 0


def test_kg_query_lightrag_path_on_success():
    fake_chains = [{
        "edges": [{"src": "Zingiber officinale", "edge": "CONTAINS_COMPOUND",
                   "tgt": "6-gingerol", "source_id": "duke:1",
                   "weight": 0.9, "evidence_tier": "experimental"}]
    }]
    with patch("agents.tools.kg_query._lightrag_query") as m:
        m.return_value = {"chains": fake_chains, "node_count": 5, "edge_count": 4}
        result = kg_query("test", mode="hybrid")
    assert len(result.chains) == 1
    assert result.chains[0].edges[0].tgt == "6-gingerol"


def test_kg_query_validates_mode():
    with pytest.raises(ValueError):
        kg_query("test", mode="invalid")
