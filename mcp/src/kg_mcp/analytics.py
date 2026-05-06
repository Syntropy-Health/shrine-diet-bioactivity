"""PostHog analytics client for the kg-mcp gateway.

Initialised once (module-level singleton). Callers import ``posthog_client``
and call ``posthog_client.capture(...)`` or ``posthog_client.capture_exception(...)``.

If ``POSTHOG_PROJECT_TOKEN`` is not set the client is ``None`` and all helper
functions become no-ops, so the server runs fine without analytics configured.

Distinct-ID strategy
--------------------
This is a server-side MCP service with no end-user login flow.  The stable
identifier for events is ``"kg-mcp-server"`` (the service itself).  For
auth-related events we use ``"kg-mcp-auth"`` so they can be segmented
separately.  No PII is ever sent in ``capture()`` properties.
"""
from __future__ import annotations

import atexit
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ─── Singleton initialisation ─────────────────────────────────────────────

_posthog_client = None

try:
    from posthog import Posthog

    _token = os.getenv("POSTHOG_PROJECT_TOKEN", "")
    _host = os.getenv("POSTHOG_HOST", "")

    if _token and _host:
        _posthog_client = Posthog(
            _token,
            host=_host,
            enable_exception_autocapture=True,
        )
        atexit.register(_posthog_client.shutdown)
        logger.info("PostHog analytics initialised (host=%s)", _host)
    else:
        logger.debug("POSTHOG_PROJECT_TOKEN or POSTHOG_HOST not set — analytics disabled")

except ImportError:
    logger.debug("posthog package not installed — analytics disabled")


# ─── Public helpers ───────────────────────────────────────────────────────

#: The stable server-level distinct ID used for most server-side events.
SERVER_DISTINCT_ID = "kg-mcp-server"

#: Distinct ID used for auth-plane events.
AUTH_DISTINCT_ID = "kg-mcp-auth"


def capture(distinct_id: str, event: str, properties: dict[str, Any] | None = None) -> None:
    """Fire a PostHog event.  Silent no-op when analytics is disabled."""
    if _posthog_client is None:
        return
    _posthog_client.capture(
        distinct_id=distinct_id,
        event=event,
        properties=properties or {},
    )


def capture_exception(exc: Exception, distinct_id: str = SERVER_DISTINCT_ID) -> None:
    """Manually capture a handled exception.  Silent no-op when analytics is disabled."""
    if _posthog_client is None:
        return
    _posthog_client.capture_exception(exc, distinct_id=distinct_id)
