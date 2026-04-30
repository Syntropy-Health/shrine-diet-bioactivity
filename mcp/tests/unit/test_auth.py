"""Tests for the MCP auth layer.

Static-key path tested directly. Clerk path tested via mocked PyJWKClient.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from kg_mcp.auth import (  # type: ignore[import-not-found]
    AuthMiddleware,
    _is_public,
    verify_clerk_token,
    verify_static_key,
)


# ─── Public path detection ────────────────────────────────────────────────


def test_health_is_public():
    assert _is_public("/health") is True


def test_health_with_subpath_is_public():
    assert _is_public("/health/ready") is True


def test_mcp_is_not_public():
    assert _is_public("/mcp") is False
    assert _is_public("/mcp/anything") is False


# ─── verify_static_key ────────────────────────────────────────────────────


def test_static_key_matches_env(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret123")
    assert verify_static_key("secret123") is True


def test_static_key_mismatch(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret123")
    assert verify_static_key("wrong") is False


def test_static_key_empty_env_rejects(monkeypatch):
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    assert verify_static_key("anything") is False


def test_static_key_empty_token_with_set_env_rejects(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret123")
    assert verify_static_key("") is False


def test_static_key_constant_time_compare(monkeypatch):
    """Sanity: hmac.compare_digest accepts same-length strings."""
    monkeypatch.setenv("MCP_API_KEY", "x" * 32)
    assert verify_static_key("x" * 32) is True
    assert verify_static_key("x" * 31) is False


# ─── verify_clerk_token ───────────────────────────────────────────────────


@pytest.fixture
def clerk_env(monkeypatch):
    """Configure Clerk env vars for tests."""
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_live_Y2xlcmsuc3ludHJvcHloZWFsdGguYmlvJA")
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_live_FAKE")


def test_clerk_returns_false_when_admin_set_empty():
    """Even with valid token, no admin allow-list → rejected."""
    assert verify_clerk_token("any-token", set()) is False


def test_clerk_returns_false_when_publishable_key_missing(monkeypatch):
    monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
    assert verify_clerk_token("any-token", {"admin@x.com"}) is False


def test_clerk_returns_false_when_jwt_decode_fails(clerk_env):
    """Bad token → False, no exception."""
    with patch("kg_mcp.auth.PyJWKClient" if False else "jwt.PyJWKClient") as mock_client:
        mock_client.return_value.get_signing_key_from_jwt.side_effect = Exception("bad sig")
        assert verify_clerk_token("not-a-jwt", {"admin@x.com"}) is False


def test_clerk_accepts_when_email_in_admin_list(clerk_env):
    """Mock the JWT decode to return our admin email."""
    fake_signing_key = MagicMock(key="fake-key")
    with patch("jwt.PyJWKClient") as mock_client_cls, patch("jwt.decode") as mock_decode:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = fake_signing_key
        mock_client_cls.return_value = mock_client
        mock_decode.return_value = {"email": "mymm.psu@gmail.com", "exp": 9999999999, "iss": "x"}
        assert verify_clerk_token("ey.fake.jwt", {"mymm.psu@gmail.com"}) is True


def test_clerk_rejects_email_not_in_admin_list(clerk_env):
    fake_signing_key = MagicMock(key="fake-key")
    with patch("jwt.PyJWKClient") as mock_client_cls, patch("jwt.decode") as mock_decode:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = fake_signing_key
        mock_client_cls.return_value = mock_client
        mock_decode.return_value = {"email": "intruder@x.com", "exp": 9999999999, "iss": "x"}
        assert verify_clerk_token("ey.fake.jwt", {"mymm.psu@gmail.com"}) is False


def test_clerk_handles_missing_email_claim(clerk_env):
    """Token without email claim → reject."""
    fake_signing_key = MagicMock(key="fake-key")
    with patch("jwt.PyJWKClient") as mock_client_cls, patch("jwt.decode") as mock_decode:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = fake_signing_key
        mock_client_cls.return_value = mock_client
        mock_decode.return_value = {"exp": 9999999999, "iss": "x"}
        assert verify_clerk_token("ey.fake.jwt", {"mymm.psu@gmail.com"}) is False


# ─── AuthMiddleware end-to-end ────────────────────────────────────────────


def _hello(request):
    return JSONResponse({"ok": True})


@pytest.fixture
def guarded_app():
    app = Starlette(routes=[
        Route("/health", _hello),
        Route("/mcp", _hello, methods=["GET", "POST"]),
        Route("/admin/data", _hello, methods=["GET"]),
    ])
    app.add_middleware(AuthMiddleware)
    return app


def test_health_bypasses_auth(guarded_app):
    client = TestClient(guarded_app)
    assert client.get("/health").status_code == 200


def test_mcp_without_bearer_returns_401(guarded_app):
    client = TestClient(guarded_app)
    r = client.get("/mcp")
    assert r.status_code == 401
    assert r.json()["error"] == "missing_bearer"


def test_mcp_with_invalid_bearer_returns_401(guarded_app, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "expected-key")
    monkeypatch.setenv("MCP_ADMIN_EMAILS", "")
    client = TestClient(guarded_app)
    r = client.get("/mcp", headers={"Authorization": "Bearer wrong-key"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


def test_mcp_with_valid_static_key_passes(guarded_app, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "expected-key")
    client = TestClient(guarded_app)
    r = client.get("/mcp", headers={"Authorization": "Bearer expected-key"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_mcp_falls_back_to_clerk_when_static_fails(guarded_app, monkeypatch):
    """Wrong static key → middleware tries Clerk; if Clerk succeeds, allow."""
    monkeypatch.setenv("MCP_API_KEY", "real-static-key")
    monkeypatch.setenv("MCP_ADMIN_EMAILS", "mymm.psu@gmail.com")
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_live_Y2xlcmsuc3ludHJvcHloZWFsdGguYmlvJA")
    fake_signing_key = MagicMock(key="fake")
    with patch("jwt.PyJWKClient") as mock_client_cls, patch("jwt.decode") as mock_decode:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = fake_signing_key
        mock_client_cls.return_value = mock_client
        mock_decode.return_value = {"email": "mymm.psu@gmail.com", "exp": 9999999999, "iss": "x"}
        client = TestClient(guarded_app)
        r = client.get("/mcp", headers={"Authorization": "Bearer ey.fake.jwt"})
    assert r.status_code == 200


def test_arbitrary_path_requires_auth(guarded_app):
    client = TestClient(guarded_app)
    assert client.get("/admin/data").status_code == 401


def test_lowercase_authorization_header_accepted(guarded_app, monkeypatch):
    """Starlette normalizes header names; HTTP is case-insensitive."""
    monkeypatch.setenv("MCP_API_KEY", "k")
    client = TestClient(guarded_app)
    r = client.get("/mcp", headers={"authorization": "Bearer k"})
    assert r.status_code == 200


def test_bearer_prefix_is_case_insensitive(guarded_app, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "k")
    client = TestClient(guarded_app)
    # "bearer" lowercase
    r = client.get("/mcp", headers={"Authorization": "bearer k"})
    assert r.status_code == 200


# ─── Helpers (coverage for auth internals) ────────────────────────────────


def test_clerk_frontend_api_decodes_publishable_key(monkeypatch):
    from kg_mcp.auth import _clerk_frontend_api  # type: ignore[import-not-found]

    # Live key from Infisical (pk_live_<base64>$ → "clerk.<domain>$")
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_live_Y2xlcmsuc3ludHJvcHloZWFsdGguYmlvJA")
    assert _clerk_frontend_api() == "clerk.syntropyhealth.bio"


def test_clerk_frontend_api_returns_none_when_unset(monkeypatch):
    from kg_mcp.auth import _clerk_frontend_api  # type: ignore[import-not-found]

    monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
    assert _clerk_frontend_api() is None


def test_clerk_frontend_api_handles_malformed_key(monkeypatch):
    from kg_mcp.auth import _clerk_frontend_api  # type: ignore[import-not-found]

    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "not-a-real-key")
    # Either None (no underscores) or some lenient decode that doesn't crash.
    out = _clerk_frontend_api()
    assert out is None or isinstance(out, str)


def test_fetch_jwks_caches_result(monkeypatch):
    from unittest.mock import MagicMock

    from kg_mcp import auth as auth_mod  # type: ignore[import-not-found]

    # Reset the module cache between tests.
    auth_mod._JWKS_CACHE.clear()

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"keys": [{"kid": "x"}]}
    fake_resp.raise_for_status = MagicMock(return_value=None)

    with patch("httpx.get", return_value=fake_resp) as get:
        first = auth_mod._fetch_jwks("clerk.example.com")
        second = auth_mod._fetch_jwks("clerk.example.com")
    assert first == second == {"keys": [{"kid": "x"}]}
    # Cached → only one HTTP call across two reads.
    assert get.call_count == 1


def test_fetch_jwks_returns_none_on_network_error():
    from unittest.mock import patch as _patch

    from kg_mcp import auth as auth_mod  # type: ignore[import-not-found]

    auth_mod._JWKS_CACHE.clear()
    with _patch("httpx.get", side_effect=Exception("boom")):
        out = auth_mod._fetch_jwks("unreachable.example.com")
    assert out is None


def test_install_with_starlette_app_calls_add_middleware():
    """install() short-circuits to add_middleware on Starlette apps."""
    from kg_mcp.auth import install  # type: ignore[import-not-found]

    app = Starlette()
    out = install(app)
    assert out is app
    # No public way to introspect the middleware list pre-build, but the call
    # must not raise.


def test_admin_emails_csv_is_parsed_lowercase(monkeypatch):
    from kg_mcp.auth import _admin_emails  # type: ignore[import-not-found]

    monkeypatch.setenv("MCP_ADMIN_EMAILS", "Admin@X.com, secondary@y.com,  ")
    assert _admin_emails() == {"admin@x.com", "secondary@y.com"}


def test_admin_emails_empty_when_unset(monkeypatch):
    from kg_mcp.auth import _admin_emails  # type: ignore[import-not-found]

    monkeypatch.delenv("MCP_ADMIN_EMAILS", raising=False)
    assert _admin_emails() == set()
