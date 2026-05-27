"""Unit tests for mcp/tests/e2e/_helpers.py.

These run by default (no `e2e` mark, no live-gateway dependency).
Locks in SYN-89's fix — _payload must descend into structuredContent;
_extract_source_ids must iterate chain edges.
"""
from __future__ import annotations

import pytest

# Relative import from sibling test package — mcp/tests has __init__.py
from ..e2e._helpers import (  # type: ignore[import-not-found]
    _extract_chains,
    _extract_source_ids,
    _is_error,
    _payload,
)


pytestmark = [pytest.mark.unit]


# ─── _payload ──────────────────────────────────────────────────────────────


class TestPayload:
    def test_descends_into_structured_content(self):
        envelope = {
            "result": {
                "content": [{"type": "text", "text": "{\"english\": \"X\"}"}],
                "structuredContent": {
                    "english": "Astragalus membranaceus",
                    "confidence": 1.0,
                },
                "isError": False,
            }
        }
        assert _payload(envelope) == {
            "english": "Astragalus membranaceus",
            "confidence": 1.0,
        }

    def test_returns_envelope_when_structured_content_absent(self):
        """Backward-compat: pre-MCP-typed-output gateways returned the
        typed payload at the envelope level."""
        envelope = {"result": {"nodes": [{"id": 1}], "edges": []}}
        assert _payload(envelope) == {"nodes": [{"id": 1}], "edges": []}

    def test_returns_empty_dict_on_no_result_key(self):
        assert _payload({}) == {}

    def test_returns_empty_dict_on_non_dict_result(self):
        assert _payload({"result": None}) == {}
        assert _payload({"result": "string"}) == {}

    def test_isError_envelope_is_still_unwrapped(self):
        """An isError=true response still has structuredContent (with the
        error detail). The probe checks _is_error first; _payload returns
        the structured payload regardless."""
        envelope = {
            "result": {
                "content": [{"type": "text", "text": "{\"detail\": \"...\"}"}],
                "structuredContent": {"detail": "validation failed"},
                "isError": True,
            }
        }
        assert _payload(envelope) == {"detail": "validation failed"}


# ─── _extract_source_ids ──────────────────────────────────────────────────


class TestExtractSourceIds:
    def test_descends_into_chain_edges(self):
        chain = {
            "edges": [
                {
                    "src_id": "Astragalus",
                    "tgt_id": "Aging",
                    "source_id": "duke:treats_symptom",
                },
                {
                    "src_id": "Astragalus",
                    "tgt_id": "Diabetes",
                    "source_id": "herb2:herb_disease",
                },
            ]
        }
        assert _extract_source_ids(chain) == [
            "duke:treats_symptom",
            "herb2:herb_disease",
        ]

    def test_returns_empty_for_chain_with_no_edges(self):
        assert _extract_source_ids({"edges": []}) == []
        assert _extract_source_ids({}) == []

    def test_returns_empty_for_non_dict_chain(self):
        assert _extract_source_ids(None) == []
        assert _extract_source_ids("string") == []
        assert _extract_source_ids([]) == []

    def test_handles_flat_entity_shape_backward_compat(self):
        """Earlier chain variants returned flat entity dicts (no edges)
        with the source_id at the top level."""
        chain = {"source_id": "duke:targets_protein", "entity_id": "CURCUMIN"}
        # Edges array absent → backward-compat path
        assert "duke:targets_protein" in _extract_source_ids(chain)

    def test_edge_without_source_id_skipped(self):
        chain = {
            "edges": [
                {"src_id": "A", "tgt_id": "B"},
                {"src_id": "A", "tgt_id": "C", "source_id": "duke:foo"},
            ]
        }
        assert _extract_source_ids(chain) == ["duke:foo"]


# ─── _is_error / _extract_chains (lock current behaviour) ─────────────────


class TestIsError:
    def test_no_error_key(self):
        assert _is_error({"result": {}}) is False

    def test_null_error(self):
        assert _is_error({"error": None}) is False

    def test_real_error(self):
        assert _is_error({"error": {"code": -32603, "message": "internal"}}) is True


class TestExtractChains:
    def test_chains_at_result_level(self):
        envelope = {"result": {"chains": [{"edges": [{"src_id": "A"}]}]}}
        assert _extract_chains(envelope) == [{"edges": [{"src_id": "A"}]}]

    def test_chains_in_content_text(self):
        envelope = {
            "result": {
                "content": [
                    {"type": "text", "text": '{"chains": [{"edges": []}]}'}
                ]
            }
        }
        assert _extract_chains(envelope) == [{"edges": []}]

    def test_no_chains_returns_empty(self):
        assert _extract_chains({"result": {}}) == []
        assert _extract_chains({}) == []
