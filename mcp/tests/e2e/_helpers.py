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

    NOTE: this function is the SYN-89 fix point. Currently returns the
    outer envelope, which is wrong (the envelope keys are
    ``content``/``structuredContent``/``isError``, not the typed
    payload). The next commit fixes this — keeping the buggy body here
    verbatim so the extract-then-fix diff is bisectable.
    """
    payload = result.get("result", {})
    return payload if isinstance(payload, dict) else {}


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
    """Pull ``source_id`` values from a chain.

    NOTE: this function is the SYN-89 fix point. The buggy body below
    checks the chain dict for ``entity_id``/``id``/``source_id`` — but
    chains are ``{"edges":[{...}]}`` and the source_id lives on each
    EDGE, not on the chain. The next commit fixes this; the body here
    is preserved for bisectability.
    """
    # BUG (fixed in next commit): doesn't descend into edges.
    if isinstance(chain, dict):
        sid = chain.get("entity_id") or chain.get("id") or chain.get("source_id")
        return [sid] if sid else []
    return []
