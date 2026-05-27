"""Shared helpers for the e2e probe suite.

Single source of truth for two repeatedly-broken concerns:

* ``_payload`` — unwrap the MCP ``tools/call`` envelope to reach the
  typed tool output. MCP wraps every tool's return in
  ``{"content":[{"type":"text","text":"<json>"}], "structuredContent":{...},
  "isError": bool}``. Probes want ``structuredContent``; the text wrapper
  is for display.

* ``_extract_source_ids`` — pull the ``source_id`` attribution off
  chain edges. Chains from Layer-B traversals are
  ``{"edges":[{"src_id","tgt_id","rel_type","source_id",...}]}`` —
  the source_id lives one level deep, on each edge.

Keep this module dependency-light (no httpx, no pytest fixtures) so the
unit suite in ``mcp/tests/unit/test_e2e_helpers.py`` can import + assert
without booting a live gateway.
"""
from __future__ import annotations

import json
from typing import Any


def _is_error(result: dict) -> bool:
    """True if the JSON-RPC envelope carries an error."""
    return "error" in result and result.get("error") is not None


def _payload(result: dict) -> dict:
    """The tool result payload (the structured tool output).

    MCP ``tools/call`` wraps every tool's return in
    ``{"content":[{"type":"text","text":"..."}], "structuredContent":{...},
    "isError": bool}``. The ``structuredContent`` field is the
    Pydantic-validated typed payload — assert against this. The
    ``content[].text`` wrapper is a JSON-string mirror for display.

    Falls back to the envelope itself when ``structuredContent`` is
    absent (pre-typed-output gateway versions).
    """
    envelope = result.get("result", {})
    if not isinstance(envelope, dict):
        return {}
    sc = envelope.get("structuredContent")
    if isinstance(sc, dict):
        return sc
    return envelope


def _extract_chains(result: dict) -> list:
    """Pull a chains list out of an MCP tools/call response.

    Tries (in order):
      1. ``result.chains`` (direct JSON return)
      2. ``result.data.chains`` (envelope variant)
      3. ``result.content[0].text`` parsed as JSON, then ``.chains``

    Returns ``[]`` when no chains can be located.
    """
    payload = result.get("result", {})
    if not isinstance(payload, dict):
        return []
    chains = payload.get("chains")
    if chains:
        return chains
    data = payload.get("data")
    if isinstance(data, dict) and data.get("chains"):
        return data["chains"]
    content_list = payload.get("content")
    if isinstance(content_list, list) and content_list:
        first = content_list[0]
        if isinstance(first, dict):
            text = first.get("text", "")
            if text:
                try:
                    parsed = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return []
                if isinstance(parsed, dict):
                    return parsed.get("chains") or parsed.get("data", {}).get("chains") or []
    return []


def _extract_source_ids(chain: Any) -> list[str]:
    """Pull ``source_id`` attribution off chain edges.

    Chain shape from Layer-B traversals is
    ``{"edges":[{src_id, tgt_id, rel_type, source_id, ...}]}``;
    the source_id lives one level deep on each edge. Earlier variants
    used flat entity dicts (top-level source_id) — handled as fallback.
    """
    if not isinstance(chain, dict):
        return []
    edges = chain.get("edges")
    if isinstance(edges, list):
        return [
            e["source_id"]
            for e in edges
            if isinstance(e, dict) and e.get("source_id")
        ]
    # Fallback: flat entity-shape chain (no edges array).
    sid = chain.get("source_id") or chain.get("entity_id") or chain.get("id")
    return [sid] if sid else []
