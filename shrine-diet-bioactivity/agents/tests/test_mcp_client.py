"""Unit tests for agents.tools.mcp_client and kg_tools.

Mocks the requests layer so tests are hermetic — no live MCP gateway.
Covers:
  - initialize handshake + session-id capture
  - tools/call payload + SSE parsing of structuredContent
  - MCPError on transport failure / isError responses
  - kg_tools.normalize_seed casing rules
  - kg_tools wrappers returning typed Pydantic models
"""
from unittest.mock import MagicMock, patch

import pytest

from agents.tools.mcp_client import (
    DEFAULT_MCP_URL, MCPClient, MCPError, default_client, reset_default_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(payload_json: str) -> str:
    return f"event: message\ndata: {payload_json}\n\n"


def _make_init_response(session_id: str = "sess-abc") -> MagicMock:
    """Mock a successful initialize HTTP response (200 + Mcp-Session-Id)."""
    r = MagicMock()
    r.headers = {"Mcp-Session-Id": session_id}
    r.text = _sse('{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",'
                  '"capabilities":{"tools":{}},"serverInfo":{"name":"kg-mcp","version":"1.0"}}}')
    r.raise_for_status = MagicMock()
    return r


def _make_tool_call_response(structured: dict, is_error: bool = False) -> MagicMock:
    import json
    r = MagicMock()
    body = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "content": [{"type": "text", "text": json.dumps(structured)}],
            "structuredContent": structured,
            "isError": is_error,
        },
    }
    r.headers = {}
    r.text = _sse(json.dumps(body))
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# MCPClient — initialize / connect
# ---------------------------------------------------------------------------

def test_connect_captures_session_id_and_is_idempotent():
    init_resp = _make_init_response("sid-xyz")
    notify_resp = MagicMock()
    notify_resp.raise_for_status = MagicMock()

    with patch("agents.tools.mcp_client.requests.post") as mock_post:
        mock_post.side_effect = [init_resp, notify_resp]
        c = MCPClient(api_key="test-key")
        c.connect()
        assert c._session_id == "sid-xyz"
        # Second connect is a no-op — no new POSTs.
        c.connect()
        assert mock_post.call_count == 2  # init + initialized notify only


def test_connect_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    c = MCPClient(api_key="")
    with pytest.raises(MCPError, match="MCP_API_KEY"):
        c.connect()


def test_connect_raises_when_initialize_returns_no_session_id():
    bad_resp = MagicMock()
    bad_resp.headers = {}  # no Mcp-Session-Id
    bad_resp.text = _sse('{"jsonrpc":"2.0","id":1,"result":{}}')
    bad_resp.raise_for_status = MagicMock()

    with patch("agents.tools.mcp_client.requests.post", return_value=bad_resp):
        c = MCPClient(api_key="test-key")
        with pytest.raises(MCPError, match="no Mcp-Session-Id"):
            c.connect()


def test_connect_swallows_initialized_notification_failure(caplog):
    """Per code review C1: a transient failure on the initialized notification
    must not leave the client half-initialized. The session_id is already
    captured; the notification is best-effort. Re-raising would cause the
    next call_tool to skip re-handshake and reuse a never-acknowledged session.
    """
    import logging
    init_resp = _make_init_response("sid-half-init")
    import requests as _req

    def post_side_effect(url, **kwargs):  # noqa: ARG001
        body = kwargs.get("json", {})
        if body.get("method") == "initialize":
            return init_resp
        # initialized notification — fail
        raise _req.ConnectionError("notification network blip")

    with patch("agents.tools.mcp_client.requests.post", side_effect=post_side_effect):
        c = MCPClient(api_key="test-key")
        with caplog.at_level(logging.WARNING):
            c.connect()  # must NOT raise
        assert c._session_id == "sid-half-init"
        # The failure must surface at WARNING level so operators see it
        assert any("initialized notification" in r.getMessage() for r in caplog.records)


def test_connect_raises_when_request_fails():
    import requests as _req
    with patch("agents.tools.mcp_client.requests.post",
               side_effect=_req.ConnectionError("network down")):
        c = MCPClient(api_key="test-key")
        with pytest.raises(MCPError, match="MCP initialize failed"):
            c.connect()


# ---------------------------------------------------------------------------
# MCPClient — call_tool / list_tools
# ---------------------------------------------------------------------------

def test_call_tool_returns_structured_content_after_connect():
    init_resp = _make_init_response("s1")
    notify_resp = MagicMock(); notify_resp.raise_for_status = MagicMock()
    tool_resp = _make_tool_call_response({"chains": [], "seeds_resolved": ["X"]})

    with patch("agents.tools.mcp_client.requests.post") as mock_post:
        mock_post.side_effect = [init_resp, notify_resp, tool_resp]
        c = MCPClient(api_key="test-key")
        out = c.call_tool("kg_compound_to_targets", {"seed": "X", "top_k": 5})
        assert out == {"chains": [], "seeds_resolved": ["X"]}


def test_call_tool_raises_on_isError():
    init_resp = _make_init_response("s1")
    notify_resp = MagicMock(); notify_resp.raise_for_status = MagicMock()
    err_resp = _make_tool_call_response({"chains": []}, is_error=True)
    # Override structured to make sure error path uses content text
    import json
    err_resp.text = _sse(json.dumps({
        "jsonrpc": "2.0", "id": 2,
        "result": {
            "content": [{"type": "text", "text": "Error executing tool: 400 bad"}],
            "isError": True,
        },
    }))

    with patch("agents.tools.mcp_client.requests.post") as mock_post:
        mock_post.side_effect = [init_resp, notify_resp, err_resp]
        c = MCPClient(api_key="test-key")
        with pytest.raises(MCPError, match="reported isError"):
            c.call_tool("kg_node_neighborhood", {"seed": "Curcumin"})


def test_call_tool_propagates_jsonrpc_error_object():
    init_resp = _make_init_response("s1")
    notify_resp = MagicMock(); notify_resp.raise_for_status = MagicMock()
    err_resp = MagicMock()
    err_resp.text = _sse('{"jsonrpc":"2.0","id":2,"error":{"code":-32601,"message":"unknown method"}}')
    err_resp.headers = {}
    err_resp.raise_for_status = MagicMock()

    with patch("agents.tools.mcp_client.requests.post") as mock_post:
        mock_post.side_effect = [init_resp, notify_resp, err_resp]
        c = MCPClient(api_key="test-key")
        with pytest.raises(MCPError, match="returned error"):
            c.call_tool("nonsense", {})


def test_call_tool_falls_back_to_text_content_when_no_structured():
    init_resp = _make_init_response("s1")
    notify_resp = MagicMock(); notify_resp.raise_for_status = MagicMock()
    text_only_resp = MagicMock()
    import json
    text_only_resp.text = _sse(json.dumps({
        "jsonrpc": "2.0", "id": 2,
        "result": {"content": [{"type": "text", "text": '{"k":"v"}'}], "isError": False},
    }))
    text_only_resp.headers = {}
    text_only_resp.raise_for_status = MagicMock()

    with patch("agents.tools.mcp_client.requests.post") as mock_post:
        mock_post.side_effect = [init_resp, notify_resp, text_only_resp]
        c = MCPClient(api_key="test-key")
        assert c.call_tool("anything", {}) == {"k": "v"}


def test_parse_sse_raises_on_no_data_line():
    c = MCPClient(api_key="x")
    with pytest.raises(MCPError, match="no data line"):
        c._parse_sse("event: message\nno-data-here")


def test_parse_sse_skips_empty_keepalive_data_line(caplog):
    """Per code review C3 (live bug): the Railway gateway sometimes prefixes a
    keep-alive `data: ` line before the JSON `data: {...}` line. The previous
    regex grabbed the first match (empty), causing json.loads to fail. The
    fix must walk through each `data:` line and return the first one whose
    payload is non-empty JSON.
    """
    c = MCPClient(api_key="x")
    sse = (
        ": ping\n"
        "data: \n"  # empty keep-alive
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"k":"v"}}\n'
        "\n"
    )
    out = c._parse_sse(sse)
    assert out["result"]["k"] == "v"


def test_parse_sse_handles_no_space_after_data_colon():
    c = MCPClient(api_key="x")
    out = c._parse_sse('data:{"k":1}\n\n')
    assert out == {"k": 1}


def test_default_client_is_singleton():
    reset_default_client()
    a = default_client()
    b = default_client()
    assert a is b
    assert a.url == DEFAULT_MCP_URL or a.url.endswith("/mcp")
    reset_default_client()


# ---------------------------------------------------------------------------
# kg_tools — normalize_seed + wrappers
# ---------------------------------------------------------------------------

from agents.tools.kg_tools import (  # type: ignore[import-not-found]  # noqa: E402
    BilingualTermOutput, HDICheckOutput, TraversalOutput,
    kg_bilingual_term, kg_compound_to_targets, kg_diet_to_compounds, kg_hdi_check,
    kg_herb_to_diseases, normalize_seed,
)


def test_normalize_seed_compound_uppercases():
    assert normalize_seed("compound", "curcumin") == "CURCUMIN"
    assert normalize_seed("compound", "Curcumin") == "CURCUMIN"
    assert normalize_seed("compound", "CURCUMIN") == "CURCUMIN"


def test_normalize_seed_herb_food_titlecase_only_when_uniform():
    assert normalize_seed("herb", "ginkgo biloba") == "Ginkgo Biloba"
    # Already mixed-case: pass through (Latin spp. like 'Ginkgo biloba' have lowercase species)
    assert normalize_seed("herb", "Ginkgo biloba") == "Ginkgo biloba"
    assert normalize_seed("food", "garlic") == "Garlic"
    assert normalize_seed("food", "Garlic") == "Garlic"


def test_normalize_seed_term_passthrough():
    # bilingual lookup accepts EN/CN/Pinyin verbatim
    assert normalize_seed("term", "黄连") == "黄连"
    assert normalize_seed("term", "Huanglian") == "Huanglian"


def test_normalize_seed_handles_empty_and_whitespace():
    assert normalize_seed("compound", "") == ""
    assert normalize_seed("compound", "   curcumin   ") == "CURCUMIN"


def _patched_call(structured: dict):
    """Helper to patch agents.tools.kg_tools._call → return a fixed dict."""
    return patch("agents.tools.kg_tools._call", return_value=structured)


def test_kg_compound_to_targets_returns_typed_traversal():
    fixture = {
        "chains": [{"edges": [
            {"src_id": "CURCUMIN", "tgt_id": "COX-2",
             "rel_type": "TARGETS_PROTEIN", "source_id": "cmaup:1"}
        ]}],
        "seeds_resolved": ["CURCUMIN"],
        "raw_subgraph_node_count": 0,
        "raw_subgraph_edge_count": 1,
    }
    with _patched_call(fixture):
        out = kg_compound_to_targets(seed="curcumin", top_k=5)
    assert isinstance(out, TraversalOutput)
    assert out.seeds_resolved == ["CURCUMIN"]
    assert len(out.chains) == 1
    assert out.chains[0].edges[0].tgt_id == "COX-2"


def test_kg_compound_to_targets_normalizes_seed_before_call():
    captured = {}
    def fake_call(_name, args):
        captured["args"] = args
        return {"chains": [], "seeds_resolved": [], "raw_subgraph_node_count": 0,
                "raw_subgraph_edge_count": 0}
    with patch("agents.tools.kg_tools._call", side_effect=fake_call):
        kg_compound_to_targets(seed="curcumin", top_k=5)
    assert captured["args"]["seed"] == "CURCUMIN"
    assert captured["args"]["top_k"] == 5


def test_kg_diet_to_compounds_titlecases_seed():
    captured = {}
    def fake_call(_name, args):
        captured.update(args)
        return {"chains": [], "seeds_resolved": [], "raw_subgraph_node_count": 0,
                "raw_subgraph_edge_count": 0}
    with patch("agents.tools.kg_tools._call", side_effect=fake_call):
        kg_diet_to_compounds(seed="garlic")
    assert captured["seed"] == "Garlic"


def test_kg_herb_to_diseases_passes_latin_through_unchanged():
    captured = {}
    def fake_call(_name, args):
        captured.update(args)
        return {"chains": [], "seeds_resolved": ["Ginkgo biloba"],
                "raw_subgraph_node_count": 0, "raw_subgraph_edge_count": 0}
    with patch("agents.tools.kg_tools._call", side_effect=fake_call):
        kg_herb_to_diseases(seed="Ginkgo biloba")
    # mixed-case Latin is preserved (not re-title-cased)
    assert captured["seed"] == "Ginkgo biloba"


def test_kg_hdi_check_returns_typed_output():
    fixture = {
        "found": True, "severity": "severe", "mechanism_class": "CYP450",
        "evidence_tier": "clinical", "citations": ["pmid:12345"],
    }
    with _patched_call(fixture):
        out = kg_hdi_check(drug="Warfarin", herb="St. John's Wort")
    assert isinstance(out, HDICheckOutput)
    assert out.found is True
    assert out.severity == "severe"
    assert out.mechanism_class == "CYP450"
    assert out.citations == ["pmid:12345"]


def test_hdi_check_validator_rejects_found_with_none_severity():
    """Per code review I5: found=True with severity=None is an invalid
    state — Safety Reviewer would consume None severity. Validator
    enforces the invariant."""
    import pydantic
    with pytest.raises(pydantic.ValidationError, match="severity"):
        HDICheckOutput(found=True, severity=None, mechanism_class=None)


def test_hdi_check_validator_allows_not_found_with_none_severity():
    out = HDICheckOutput(found=False, severity=None, mechanism_class=None)
    assert out.found is False


def test_bilingual_term_confidence_bounded():
    """Per code review I5: confidence is a [0, 1] match score."""
    import pydantic
    from agents.tools.kg_tools import BilingualTermOutput  # type: ignore[import-not-found]
    BilingualTermOutput(confidence=0.0)
    BilingualTermOutput(confidence=1.0)
    with pytest.raises(pydantic.ValidationError):
        BilingualTermOutput(confidence=1.5)
    with pytest.raises(pydantic.ValidationError):
        BilingualTermOutput(confidence=-0.1)


def test_kg_bilingual_term_handles_all_null():
    fixture = {"english": None, "chinese": None, "pinyin": None,
               "source": "symmap", "confidence": 0.0}
    with _patched_call(fixture):
        out = kg_bilingual_term(term="阴虚")
    assert isinstance(out, BilingualTermOutput)
    assert out.english is None
    assert out.confidence == 0.0


def test_kg_call_retries_once_on_mcp_error(caplog):
    """_call should retry once on MCPError before propagating, AND log the
    first error per code review C2 (don't silently swallow diagnostic info)."""
    import logging
    from agents.tools.kg_tools import _call  # type: ignore[import-not-found]

    client = MagicMock()
    call_count = {"n": 0}

    def flaky(_name, _args):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise MCPError("transient first-attempt detail")
        return {"chains": [], "seeds_resolved": [],
                "raw_subgraph_node_count": 0, "raw_subgraph_edge_count": 0}

    client.call_tool = flaky
    with patch("agents.tools.kg_tools.default_client", return_value=client):
        with caplog.at_level(logging.WARNING):
            out = _call("kg_compound_to_targets", {"seed": "X"})
    assert call_count["n"] == 2
    assert out["chains"] == []
    # The first-attempt error message MUST be logged so paper-grade eval
    # debugging can distinguish transient from permanent failures.
    assert any("transient first-attempt detail" in r.getMessage() for r in caplog.records)


def test_kg_call_propagates_after_two_failures():
    from agents.tools.kg_tools import _call  # type: ignore[import-not-found]

    client = MagicMock()
    client.call_tool = MagicMock(side_effect=MCPError("dead"))
    with patch("agents.tools.kg_tools.default_client", return_value=client):
        with pytest.raises(MCPError, match="dead"):
            _call("kg_compound_to_targets", {"seed": "X"})
    assert client.call_tool.call_count == 2
