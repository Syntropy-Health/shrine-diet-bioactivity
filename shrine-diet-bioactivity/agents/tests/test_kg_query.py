# shrine-diet-bioactivity/agents/tests/test_kg_query.py
"""KG-query tool tests — LightRAG-only contract (no SQLite fallback)."""
import pytest
from unittest.mock import patch

from agents.tools.kg_query import kg_query, KGQueryError  # type: ignore[import-not-found]
from agents.models import KGResult  # type: ignore[import-not-found]

pytestmark = [pytest.mark.unit]


def test_kg_query_lightrag_path_on_success():
    fake_chains = [{
        "edges": [{"src": "Zingiber officinale", "edge": "CONTAINS_COMPOUND",
                   "tgt": "6-gingerol", "source_id": "duke:1",
                   "weight": 0.9, "evidence_tier": "experimental"}]
    }]
    with patch("agents.tools.kg_query._lightrag_query") as m:
        m.return_value = {"chains": fake_chains, "node_count": 5, "edge_count": 4}
        result = kg_query("test", mode="hybrid")
    assert isinstance(result, KGResult)
    assert len(result.chains) == 1
    assert result.chains[0].edges[0].tgt == "6-gingerol"
    assert result.raw_subgraph_node_count == 5


def test_kg_query_raises_on_lightrag_unreachable():
    with patch("agents.tools.kg_query._lightrag_query", side_effect=KGQueryError("unreachable")):
        with pytest.raises(KGQueryError, match="unreachable"):
            kg_query("ginger nausea evidence", mode="hybrid")


def test_kg_query_validates_mode():
    with pytest.raises(ValueError):
        kg_query("test", mode="invalid")  # type: ignore[arg-type]


def test_kg_query_returns_empty_chains_when_lightrag_returns_empty():
    with patch("agents.tools.kg_query._lightrag_query") as m:
        m.return_value = {"chains": [], "node_count": 0, "edge_count": 0}
        result = kg_query("nonexistent topic", mode="local")
    assert result.chains == []
    assert result.raw_subgraph_node_count == 0
    assert result.query_mode == "local"
