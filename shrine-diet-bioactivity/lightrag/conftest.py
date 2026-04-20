"""Shared pytest configuration for the lightrag Python tests."""

from __future__ import annotations


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
