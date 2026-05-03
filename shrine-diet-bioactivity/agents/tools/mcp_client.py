"""MCP streamable-HTTP client for the staged KG gateway.

Speaks the JSON-RPC subset of MCP that the kg-mcp server (v1.27.0) accepts:
  initialize → notifications/initialized → tools/list / tools/call

The server replies in text/event-stream; this client walks each `data:` line
and returns the first one whose payload is non-empty JSON (handles
keep-alive prefix lines).

Configuration:
  MCP_URL      — defaults to https://kg-mcp-test.up.railway.app/mcp
  MCP_API_KEY  — bearer token; required

Module-level `default_client()` returns a lazily-initialized singleton so
the eval matrix reuses one MCP session across all (system × scenario × call)
permutations instead of paying the initialize round-trip on every tool use.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any

import requests

_log = logging.getLogger(__name__)

DEFAULT_MCP_URL = "https://kg-mcp-test.up.railway.app/mcp"
DEFAULT_TIMEOUT = 30.0


class MCPError(RuntimeError):
    """MCP transport or protocol error. Callers may catch + abstain."""


class MCPClient:
    """Thin streamable-HTTP MCP client. Not thread-safe across initialize."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.url = url or os.environ.get("MCP_URL", DEFAULT_MCP_URL)
        self.api_key = api_key or os.environ.get("MCP_API_KEY", "")
        self.timeout = timeout
        self._session_id: str | None = None
        self._next_id = 1
        self._lock = threading.Lock()

    # ---- session lifecycle -------------------------------------------------

    def connect(self) -> None:
        """Initialize handshake + initialized notification. Idempotent."""
        if self._session_id is not None:
            return
        if not self.api_key:
            raise MCPError("MCP_API_KEY not set; cannot authenticate to gateway")

        init_payload = {
            "jsonrpc": "2.0",
            "id": self._claim_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "shrine-eval", "version": "0.1"},
            },
        }
        try:
            resp = requests.post(
                self.url,
                json=init_payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise MCPError(f"MCP initialize failed: {exc}") from exc

        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if not sid:
            raise MCPError("MCP initialize succeeded but server returned no Mcp-Session-Id")
        self._session_id = sid

        # Notify the server we're ready (per MCP spec). Best-effort: the
        # server already issued the session id, so a failure here just means
        # the server didn't see our acknowledgement. Logging at WARNING gives
        # operators visibility without leaving the client half-initialized.
        try:
            requests.post(
                self.url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=self._headers(with_session=True),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            _log.warning(
                "MCP initialized notification failed (session %s already issued, "
                "continuing best-effort): %s", self._session_id, exc,
            )

    # ---- tool calls --------------------------------------------------------

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool by name; return the structured result.

        Returns the contents of `result.structuredContent` if present, else
        `result.content` parsed as JSON, else the raw `result` dict.
        Raises MCPError on transport failure or `isError=true`.
        """
        self.connect()
        payload = {
            "jsonrpc": "2.0",
            "id": self._claim_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers=self._headers(with_session=True),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise MCPError(f"MCP call_tool({name!r}) transport error: {exc}") from exc

        return self._extract_result(resp.text, tool=name)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the tool registry (tools/list)."""
        self.connect()
        payload = {
            "jsonrpc": "2.0",
            "id": self._claim_id(),
            "method": "tools/list",
        }
        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers=self._headers(with_session=True),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise MCPError(f"MCP tools/list transport error: {exc}") from exc

        body = self._parse_sse(resp.text)
        return body.get("result", {}).get("tools", [])

    # ---- internals ---------------------------------------------------------

    def _claim_id(self) -> int:
        with self._lock:
            i = self._next_id
            self._next_id += 1
            return i

    def _headers(self, with_session: bool = False) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if with_session and self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        """Parse the first JSON-bearing `data: ...` line from an SSE response.

        The Railway gateway sometimes emits an empty `data: ` keep-alive
        line before the JSON payload. The walker iterates every match and
        returns the first non-empty payload that parses as JSON.
        """
        matches = re.findall(r"^data:\s*(.*)$", text, re.MULTILINE)
        if not matches:
            raise MCPError(f"MCP SSE response had no data line: {text[:200]!r}")
        last_err: str | None = None
        for payload in matches:
            payload = payload.strip()
            if not payload:
                continue
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                last_err = f"{exc}: {payload[:200]!r}"
                continue
        raise MCPError(f"MCP SSE data not JSON ({len(matches)} data line(s)): {last_err}")

    def _extract_result(self, text: str, tool: str) -> dict[str, Any]:
        body = self._parse_sse(text)
        if "error" in body:
            err = body["error"]
            raise MCPError(f"MCP {tool!r} returned error: {err}")
        result = body.get("result", {})
        if result.get("isError"):
            content = result.get("content", [])
            msg = content[0].get("text", "<no text>") if content else "<no content>"
            raise MCPError(f"MCP tool {tool!r} reported isError=true: {msg}")
        # Prefer structuredContent (Pydantic-shaped); fall back to text content
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            try:
                return json.loads(content[0]["text"])
            except json.JSONDecodeError:
                return {"text": content[0]["text"]}
        return result


# --- module-level singleton -------------------------------------------------

_default: MCPClient | None = None
_default_lock = threading.Lock()


def default_client() -> MCPClient:
    """Lazy-init singleton. Reuses one MCP session across the eval run."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = MCPClient()
    return _default


def reset_default_client() -> None:
    """Test hook — drop the singleton so a fresh client is built next call."""
    global _default
    with _default_lock:
        _default = None
