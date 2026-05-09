"""Shared pytest configuration for the lightrag Python tests."""

from __future__ import annotations

import asyncio

import pytest


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    """Register custom markers used across the scope / bootstrap / audit tests."""
    config.addinivalue_line(
        "markers",
        "unit: fast, hermetic test — no network, no Neo4j",
    )
    config.addinivalue_line(
        "markers",
        "integration: live Neo4j / scoped_server required; gated by "
        "LIGHTRAG_RUN_INTEGRATION=true",
    )


@pytest.fixture(autouse=True)
def _reset_event_loop() -> None:
    """Ensure each test function starts with a fresh asyncio event loop.

    ``asyncio.run()`` (called by e.g. ``test_ingest_hdi``) closes the loop it
    creates, leaving ``asyncio.get_event_loop()`` unable to return a usable
    loop for subsequent tests on Python 3.10.  This fixture creates a new loop,
    sets it as the current loop for the thread, runs the test, then closes and
    clears the loop regardless of outcome — preventing suite-order failures in
    ``test_scope_enforcement.py``.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)
