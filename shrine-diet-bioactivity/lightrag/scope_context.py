"""
Per-request scope filter for multi-tenant LightRAG queries.

Uses ``contextvars.ContextVar`` so a value set in a FastAPI request
handler propagates through every ``await`` chain — including deep into
``ScopedNeo4JStorage`` — without threading an extra argument through
LightRAG internals (``QueryParam`` has no ``scope_filter`` field).

Contract:

    token = set_scope_filter(["shared", "tenant:clinic-a"])
    try:
        await rag.aquery(...)   # ScopedNeo4JStorage reads the filter
    finally:
        reset_scope_filter(token)

The default when nothing is set is ``("shared",)`` — fail-safe.

See ``multi-tenant-enforcement-bootstrap.plan.md`` for the full design.
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token

DEFAULT_SCOPE: tuple[str, ...] = ("shared",)

_SCOPE_FILTER_VAR: ContextVar[tuple[str, ...]] = ContextVar(
    "scope_filter", default=DEFAULT_SCOPE
)

# Mirrors the TypeScript tenant ID pattern in src/tenant.ts.
_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


def validate_scope(value: str) -> str:
    """Validate a single scope string, returning it on success.

    Accepts ``"shared"`` or ``"tenant:<slug>"`` where ``<slug>`` matches
    the canonical tenant regex.
    """
    if value == "shared":
        return value
    if value.startswith("tenant:"):
        slug = value[len("tenant:"):]
        if not _TENANT_ID_PATTERN.fullmatch(slug):
            raise ValueError(
                f"Invalid tenant slug in scope '{value}': "
                "must be 3-64 lowercase alphanumeric characters or hyphens"
            )
        return value
    raise ValueError(
        f"Invalid scope '{value}': must be 'shared' or 'tenant:<slug>'"
    )


def set_scope_filter(scopes: list[str]) -> Token[tuple[str, ...]]:
    """Set the per-request scope filter. Returns a reset token.

    ``scopes`` must be non-empty and every element must pass
    ``validate_scope``. Caller is expected to pair this with
    ``reset_scope_filter`` in a ``try/finally``.
    """
    if not scopes:
        raise ValueError("scope_filter cannot be empty")
    validated: tuple[str, ...] = tuple(validate_scope(s) for s in scopes)
    return _SCOPE_FILTER_VAR.set(validated)


def reset_scope_filter(token: Token[tuple[str, ...]]) -> None:
    """Reset the scope filter using the token from ``set_scope_filter``."""
    _SCOPE_FILTER_VAR.reset(token)


def get_scope_filter() -> list[str]:
    """Return the current scope filter as a list (Cypher param type)."""
    return list(_SCOPE_FILTER_VAR.get())
