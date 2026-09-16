"""Unit tests for the Milvus reachability-probe classifier (#156).

Proves the three-way verdict's discrimination WITHOUT a live cluster: the
classifier is the pure core that decides skip-vs-fail, so both arms are testable
here. (The live round-trip in _probe_milvus is exercised only in CI with the
secret; the decision logic it feeds is proven below.)
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]

# The classifier's home is the shared probe module — the SAME code the mcp-ci
# ``milvus-integration`` workflow runs as its pre-flight reachability gate
# (``python -m kg_mcp.milvus_probe``). Pure stdlib, no cluster dependency.
from kg_mcp.milvus_probe import classify_probe_error as classify  # noqa: E402


def test_dead_zilliz_signature_is_unreachable():
    # The exact string the expired Zilliz serverless returned.
    assert classify(
        "Fail connecting to in03-xxx.serverless.gcp-us-west1.cloud.zilliz.com:443, "
        "illegal connection params or server unavailable"
    ) == "unreachable"


@pytest.mark.parametrize("msg", [
    "connection refused",
    "context deadline exceeded: timed out",
    "failed to connect to all addresses",
    "name or service not known",
    "server unavailable",
])
def test_transport_errors_are_unreachable(msg):
    assert classify(msg) == "unreachable"


@pytest.mark.parametrize("msg", [
    "Unauthorized: invalid token",
    "authentication failed",
    "permission denied for database",
    "403 Forbidden",
])
def test_auth_errors_fail_not_skip(msg):
    assert classify(msg) == "auth"


def test_auth_wins_over_transport_when_both_present():
    # A rejected credential must not be masked as a connectivity skip.
    assert classify("connection to host failed: unauthorized token") == "auth"


def test_unclassified_error_is_unknown_not_skipped():
    # An error we do not recognise must FAIL (caller), never silently skip.
    assert classify("ValueError: schema dimension mismatch 4 != 1024") == "unknown"
    assert classify("") == "unknown"
    assert classify(None) == "unknown"  # type: ignore[arg-type]
