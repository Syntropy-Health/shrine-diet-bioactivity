"""Unit tests for the PostHog analytics layer.

The module is a thin wrapper around the optional ``posthog`` SDK with a
module-level singleton client.  When ``POSTHOG_PROJECT_TOKEN`` /
``POSTHOG_HOST`` are unset (or the package is missing), every helper must
silently no-op so the gateway runs without analytics configured.

Tests patch the singleton via ``monkeypatch.setattr`` instead of touching
real env vars.  Init-time branches (lines 36-42, 46-47 in analytics.py) are
exercised by reloading the module under controlled conditions.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from kg_mcp import analytics


# ─── No-op paths (client is None) ─────────────────────────────────────────


def test_capture_is_noop_when_client_unset(monkeypatch):
    """capture() must silently return when analytics is disabled."""
    monkeypatch.setattr(analytics, "_posthog_client", None)
    # Should not raise — the assertion is the absence of an exception.
    analytics.capture("test-id", "test_event", {"foo": 1})


def test_capture_exception_is_noop_when_client_unset(monkeypatch):
    """capture_exception() must silently return when analytics is disabled."""
    monkeypatch.setattr(analytics, "_posthog_client", None)
    analytics.capture_exception(Exception("boom"))


def test_capture_with_no_properties_when_client_unset(monkeypatch):
    """No-op path also covers the default-properties branch."""
    monkeypatch.setattr(analytics, "_posthog_client", None)
    analytics.capture("id", "event")  # properties omitted entirely


# ─── Forwarding paths (client is set) ─────────────────────────────────────


def test_capture_forwards_to_client_when_set(monkeypatch):
    """capture() must forward distinct_id, event, properties verbatim."""
    mock_client = MagicMock()
    monkeypatch.setattr(analytics, "_posthog_client", mock_client)
    analytics.capture("user-1", "kg_query_executed", {"k": 5})
    mock_client.capture.assert_called_once_with(
        distinct_id="user-1",
        event="kg_query_executed",
        properties={"k": 5},
    )


def test_capture_called_with_default_properties_dict(monkeypatch):
    """Omitted/None ``properties`` must become {} on the wire — never None."""
    mock_client = MagicMock()
    monkeypatch.setattr(analytics, "_posthog_client", mock_client)
    analytics.capture("id", "event")
    mock_client.capture.assert_called_once_with(
        distinct_id="id",
        event="event",
        properties={},
    )


def test_capture_explicit_none_properties_becomes_empty_dict(monkeypatch):
    """Explicit ``properties=None`` must also degrade to {}."""
    mock_client = MagicMock()
    monkeypatch.setattr(analytics, "_posthog_client", mock_client)
    analytics.capture("id", "event", None)
    mock_client.capture.assert_called_once_with(
        distinct_id="id",
        event="event",
        properties={},
    )


def test_capture_exception_forwards_to_client(monkeypatch):
    """capture_exception() forwards exc + default distinct_id."""
    mock_client = MagicMock()
    monkeypatch.setattr(analytics, "_posthog_client", mock_client)
    exc = Exception("boom")
    analytics.capture_exception(exc)
    mock_client.capture_exception.assert_called_once_with(
        exc,
        distinct_id=analytics.SERVER_DISTINCT_ID,
    )


def test_capture_exception_accepts_explicit_distinct_id(monkeypatch):
    """A caller-supplied distinct_id (e.g. AUTH_DISTINCT_ID) is forwarded."""
    mock_client = MagicMock()
    monkeypatch.setattr(analytics, "_posthog_client", mock_client)
    exc = ValueError("auth-fail")
    analytics.capture_exception(exc, distinct_id=analytics.AUTH_DISTINCT_ID)
    mock_client.capture_exception.assert_called_once_with(
        exc,
        distinct_id="kg-mcp-auth",
    )


# ─── Public constants ─────────────────────────────────────────────────────


def test_constants_exposed():
    """Stable distinct-IDs are part of the module's contract."""
    assert analytics.SERVER_DISTINCT_ID == "kg-mcp-server"
    assert analytics.AUTH_DISTINCT_ID == "kg-mcp-auth"


# ─── Module-init branches (covered via importlib.reload) ──────────────────


def test_init_creates_client_when_env_vars_present(monkeypatch):
    """With token + host set and posthog available → singleton initialised."""
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test_token")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")

    fake_posthog_cls = MagicMock()
    fake_instance = MagicMock()
    fake_posthog_cls.return_value = fake_instance

    fake_module = MagicMock()
    fake_module.Posthog = fake_posthog_cls

    with patch.dict(sys.modules, {"posthog": fake_module}):
        reloaded = importlib.reload(analytics)
        try:
            assert reloaded._posthog_client is fake_instance
            fake_posthog_cls.assert_called_once_with(
                "phc_test_token",
                host="https://us.i.posthog.com",
                enable_exception_autocapture=True,
            )
        finally:
            # Restore module-under-test to env-free state for other tests.
            monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)
            monkeypatch.delenv("POSTHOG_HOST", raising=False)
            importlib.reload(analytics)


def test_init_skips_client_when_env_vars_missing(monkeypatch):
    """Without token/host the singleton stays None even if posthog imports."""
    monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)
    monkeypatch.delenv("POSTHOG_HOST", raising=False)

    fake_posthog_cls = MagicMock()
    fake_module = MagicMock()
    fake_module.Posthog = fake_posthog_cls

    with patch.dict(sys.modules, {"posthog": fake_module}):
        reloaded = importlib.reload(analytics)
        try:
            assert reloaded._posthog_client is None
            fake_posthog_cls.assert_not_called()
        finally:
            importlib.reload(analytics)


def test_init_handles_missing_posthog_package(monkeypatch):
    """ImportError on ``from posthog import Posthog`` is swallowed."""
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test_token")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")

    # Force the import to fail by stashing a non-importable sentinel.
    # patch.dict with the key set to None makes ``import posthog`` raise.
    with patch.dict(sys.modules, {"posthog": None}):
        reloaded = importlib.reload(analytics)
        try:
            assert reloaded._posthog_client is None
        finally:
            monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)
            monkeypatch.delenv("POSTHOG_HOST", raising=False)
            importlib.reload(analytics)
