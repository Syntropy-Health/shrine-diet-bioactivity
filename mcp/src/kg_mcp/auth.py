"""Auth layer for the MCP gateway.

Two paths, both via ``Authorization: Bearer <token>``:

1. **Static API key** (temporary). Token compared with constant-time equality
   against ``MCP_API_KEY``. Use case: CI smoke tests, admin curl, anything
   not yet on a Clerk-issued session.

2. **Clerk JWT** (production admin sign-in). Token verified against Clerk's
   JWKS endpoint. The ``email`` claim must be in ``MCP_ADMIN_EMAILS`` (CSV).

Both paths are tried in order; if either succeeds the request continues.

``/health`` is intentionally public (Railway healthcheck must reach it
without a token). Everything else (``/mcp``, ``/mcp/*``) requires a bearer.

Failure modes:
  401 — no bearer / token rejected by both validators
  500 — config error (e.g., neither key nor Clerk configured)
"""
from __future__ import annotations

import base64
import hmac
import logging
import os
import time
from typing import Any

import httpx
from starlette.middleware.base import BaseHTTPMiddleware

from . import analytics
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


# Paths that bypass auth entirely. Keep this minimal.
PUBLIC_PATH_PREFIXES: tuple[str, ...] = ("/health",)


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in PUBLIC_PATH_PREFIXES)


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth[len("Bearer ") :].strip() or None


def _admin_emails() -> set[str]:
    raw = os.environ.get("MCP_ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


# ─── Static-key validator ─────────────────────────────────────────────────


def verify_static_key(token: str) -> bool:
    """Constant-time compare against MCP_API_KEY.

    Constant-time matters even for symmetric tokens so timing-oracle attacks
    can't extract the key one byte at a time.
    """
    expected = os.environ.get("MCP_API_KEY", "").strip()
    if not expected:
        return False
    return hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))


# ─── Clerk JWT validator ──────────────────────────────────────────────────


def _clerk_frontend_api() -> str | None:
    """Derive Clerk frontend API host from the publishable key.

    Clerk publishable keys encode the frontend domain in their base64 tail:
        pk_live_<base64-encoded-domain>$
    Decoded => "clerk.<your-domain>".
    """
    pk = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
    if not pk:
        return None
    # Strip "pk_live_" or "pk_test_"
    parts = pk.split("_", 2)
    if len(parts) < 3:
        return None
    encoded = parts[2].rstrip("$")
    try:
        decoded = base64.b64decode(encoded + "==").decode("ascii")
    except Exception:  # noqa: BLE001
        return None
    return decoded.rstrip("$")


# JWKS cache — fetched once, reused for token TTL. Clerk rotates keys but
# rarely; refresh whenever a kid miss occurs.
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_TTL_SECONDS = 3600.0


def _fetch_jwks(frontend_api: str) -> dict[str, Any] | None:
    now = time.time()
    cached = _JWKS_CACHE.get(frontend_api)
    if cached and now - cached[0] < _JWKS_TTL_SECONDS:
        return cached[1]
    url = f"https://{frontend_api}/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clerk JWKS fetch failed: %s", exc)
        return None
    data = resp.json()
    _JWKS_CACHE[frontend_api] = (now, data)
    return data


def verify_clerk_token(token: str, admin_emails: set[str]) -> bool:
    """Verify Clerk-issued JWT and gate by email claim.

    Returns True iff (a) signature verifies against Clerk JWKS, (b) issuer
    matches Clerk's domain, (c) the ``email`` claim is in ``admin_emails``.

    Lazy import of ``jwt`` so the static-key path works even on minimal
    deploys without pyjwt installed.
    """
    if not admin_emails:
        return False
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError:
        logger.warning("pyjwt not installed; Clerk path disabled")
        return False

    frontend = _clerk_frontend_api()
    if not frontend:
        return False
    issuer = f"https://{frontend}"
    jwks_url = f"{issuer}/.well-known/jwks.json"
    try:
        jwk_client = PyJWKClient(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token).key
        decoded = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "iss"]},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("clerk JWT verification failed: %s", exc)
        return False

    email = (decoded.get("email") or decoded.get("primary_email") or "").lower()
    if email and email in admin_emails:
        return True
    logger.warning("clerk JWT email %r not in admin allow-list", email)
    return False


# ─── Middleware ───────────────────────────────────────────────────────────


class AuthMiddleware(BaseHTTPMiddleware):
    """Gate all non-public paths behind a bearer token.

    Order: static key first (cheap); Clerk JWT only if static fails.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if _is_public(request.url.path):
            return await call_next(request)

        token = _extract_bearer(request)
        if token is None:
            analytics.capture(
                analytics.AUTH_DISTINCT_ID,
                "mcp_auth_failed",
                {"failure_reason": "missing_bearer", "path": request.url.path},
            )
            return JSONResponse(
                {"error": "missing_bearer", "detail": "Authorization: Bearer <token> required"},
                status_code=401,
            )

        if verify_static_key(token):
            return await call_next(request)

        if verify_clerk_token(token, _admin_emails()):
            return await call_next(request)

        analytics.capture(
            analytics.AUTH_DISTINCT_ID,
            "mcp_auth_failed",
            {"failure_reason": "invalid_token", "path": request.url.path},
        )
        return JSONResponse(
            {"error": "invalid_token", "detail": "token rejected by both validators"},
            status_code=401,
        )


def install(app: ASGIApp) -> ASGIApp:
    """Wrap a Starlette/FastMCP app with the auth middleware.

    Use:
        from starlette.applications import Starlette
        from .auth import install
        guarded_app = install(server.streamable_http_app())
    """
    # Starlette apps expose add_middleware; pure ASGI apps don't.
    if hasattr(app, "add_middleware"):
        app.add_middleware(AuthMiddleware)  # type: ignore[attr-defined]
        return app
    # Fallback for plain ASGI: wrap manually.
    return AuthMiddleware(app=app, dispatch=AuthMiddleware.dispatch)  # type: ignore[arg-type]
