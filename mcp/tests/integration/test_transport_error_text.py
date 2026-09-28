"""Does httpx's transport-error text carry the internal host? MEASURED, not assumed.

``ScopedServerClient._check`` sanitises HTTPStatusError only; ``httpx.RequestError``
(connect refused, timeouts) propagates as-is to MCP consumers via ``str(exc)``.
This test opens a real loopback socket, closes it so the port is refused, and
asserts the resulting ConnectError message names no host/port. Integration tier
because it performs (loopback) I/O; it needs no network beyond 127.0.0.1.
"""
from __future__ import annotations

import socket

import httpx
import pytest

from kg_mcp.client import ScopedServerClient

pytestmark = [pytest.mark.integration]


def _refused_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.asyncio
async def test_connect_refused_message_carries_no_host() -> None:
    port = _refused_port()
    client = ScopedServerClient(base_url=f"http://127.0.0.1:{port}", timeout=2.0)
    try:
        with pytest.raises(httpx.ConnectError) as ei:
            await client.health()
    finally:
        await client.aclose()
    msg = str(ei.value)
    assert "127.0.0.1" not in msg and str(port) not in msg and "http://" not in msg, msg
