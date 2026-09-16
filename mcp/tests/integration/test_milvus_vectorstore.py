"""Live integration tests for MilvusVectorStore against Zilliz/Milvus.

Three-way verdict (#156), keyed on a LIVE reachability probe — NOT on env
presence, so it self-heals when the endpoint returns and cannot be silently
disabled by a forgotten secret:
  * credential ABSENT or MALFORMED  -> FAIL  (our config problem)
  * endpoint UNREACHABLE            -> SKIP loud + surfaced in the job summary
                                       (infra absence, e.g. Zilliz serverless
                                       expired — not a code failure)
  * reachable + credential good     -> run; failures are the real signal
The same-repo `if:` gate in mcp-ci.yml already excludes fork PRs, so an absent
credential in a run that reaches here is a genuine misconfiguration, not a fork.

These are *not* unit tests — they hit a real cluster. The collection used
is a per-run sentinel (``test_kg_entities_<uuid>``) so we never collide
with the prod ``kg_entities`` collection. The tests drop the sentinel
collection on teardown so a failed run doesn't leak storage.
"""
from __future__ import annotations

import os
import uuid

import pytest

from kg_mcp.storage import VectorEntry
from kg_mcp.storage.milvus import MilvusConfig, MilvusVectorStore

# #156 verdict lives in ONE place — the shared probe module, which the mcp-ci
# ``milvus-integration`` workflow ALSO runs (``python -m kg_mcp.milvus_probe``)
# to gate its pre-flight step. One classifier, one decision, both consumers, so
# the pre-flight gate and this fixture can never disagree about reachability.
# Back-compat aliases keep the by-name unit import stable.
from kg_mcp.milvus_probe import (  # noqa: E402
    _emit_summary as _job_summary,
    classify_probe_error as _classify_probe_error,
    probe_milvus as _probe_milvus,
    resolve_env as _resolve_milvus_env,
    verdict as _milvus_verdict,
)

# Braintrust tracing — silent no-op without BRAINTRUST_API_KEY env. Wrap
# each test so live cluster round-trips show up in the dashboard with
# input + result-shape metadata for retroactive debugging.
try:
    from ..e2e._braintrust_logger import bt_span  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — defensive
    from contextlib import contextmanager

    @contextmanager
    def bt_span(name: str, **inputs):  # type: ignore[no-redef]
        class _Stub:
            def log(self, **kwargs):
                pass

        yield _Stub()


# ``milvus`` marks these as the dedicated live-cluster tier: the general
# ``-m integration`` run (functional-integration job, no Zilliz creds) deselects
# them via ``-m "integration and not milvus"`` — they run ONLY in the
# milvus-integration job, behind the reachability gate.
pytestmark = [pytest.mark.integration, pytest.mark.milvus]


# The reachability signatures, the pure classifier (`_classify_probe_error`),
# the live probe (`_probe_milvus`) and the job-summary emitter (`_job_summary`)
# now live in ``kg_mcp.milvus_probe`` — imported above as back-compat aliases so
# the workflow's pre-flight gate and this fixture share ONE decision. See the
# module for the verdict semantics.


_PROBE_CACHE: dict[str, tuple[str, str]] = {}


def _milvus_env() -> dict[str, str]:
    """Snapshot Milvus env and apply the #156 three-way verdict via a live probe."""
    env = {
        k: os.environ[k]
        for k in (
            "MILVUS_URI",
            "MILVUS_TOKEN",
            "MILVUS_USER",
            "MILVUS_PASSWORD",
            "ZILLIZ_URI",
            "ZILLIZ_TOKEN",
            "ZILLIZ_DB_USER",
            "ZILLIZ_DB_PASSWORD",
            "EMBEDDING_DIM",
        )
        if k in os.environ
    }
    # Normalise to the names MilvusConfig.from_env expects.
    if "MILVUS_URI" in env and "ZILLIZ_URI" not in env:
        env["ZILLIZ_URI"] = env["MILVUS_URI"]
    if "MILVUS_TOKEN" in env and "ZILLIZ_TOKEN" not in env:
        env["ZILLIZ_TOKEN"] = env["MILVUS_TOKEN"]

    uri, token = _resolve_milvus_env(env)

    # ONE verdict — the same `kg_mcp.milvus_probe.verdict` the mcp-ci pre-flight
    # step gates on. Cached: one round-trip per (uri, token) per session.
    key = f"{uri}|{bool(token)}"
    if key not in _PROBE_CACHE:
        _PROBE_CACHE[key] = _milvus_verdict(uri, token)
    status, detail = _PROBE_CACHE[key]

    if status == "unreachable":
        _job_summary(
            "⚠️ Milvus/Zilliz UNREACHABLE — vector-store coverage is ABSENT this "
            f"run (skipped, NOT passing) [reason=unreachable]: {detail}. Infra "
            "absence (e.g. Zilliz serverless expired); tests re-run automatically "
            "when it returns [#156]."
        )
        pytest.skip(f"Milvus endpoint unreachable — infra absent [#156]: {detail}")
    if status == "absent":
        pytest.fail(
            "ZILLIZ_URI / MILVUS_URI not set — vector-store credential missing. "
            "Per #156 this FAILS loudly (a config gap someone must fix), rather "
            "than skipping silently and disabling the test forever."
        )
    if status == "malformed":
        pytest.fail(
            f"ZILLIZ_URI malformed — {detail}. Config error, not infra absence [#156]."
        )
    if status == "auth":
        pytest.fail(
            f"Milvus reachable but credential REJECTED: {detail} — our problem "
            "(bad/expired token), failing per #156 rather than skipping."
        )
    if status == "unknown":
        pytest.fail(
            f"Milvus probe failed with an unclassified error: {detail} — failing "
            "rather than skipping, so an unrecognised failure is not masked [#156]."
        )
    # status == 'ok' -> reachable + credential good; test failures are the real signal.
    return env


@pytest.fixture
def milvus_store():
    """Yield a MilvusVectorStore bound to a per-test sentinel collection."""
    env = _milvus_env()
    collection = f"test_kg_entities_{uuid.uuid4().hex[:8]}"
    env["ZILLIZ_COLLECTION"] = collection
    env.setdefault("EMBEDDING_DIM", "4")  # tiny dim for fast schema bootstrap

    cfg = MilvusConfig.from_env(env)
    store = MilvusVectorStore(cfg)
    try:
        yield store
    finally:
        # Best-effort cleanup; a leaked sentinel is loud-but-harmless.
        try:
            store.drop()
        except Exception as exc:  # noqa: BLE001 — defensive teardown
            import warnings

            warnings.warn(f"Milvus sentinel cleanup failed: {exc}")


def test_health_via_count_zero_on_fresh_collection(milvus_store):
    """Smoke probe: the live cluster responds + a fresh collection is empty."""
    with bt_span(
        "test_health_via_count_zero_on_fresh_collection",
        backend="milvus",
        collection=milvus_store._config.collection,
    ) as span:
        count = milvus_store.count()
        span.log(output={"count": count})
        assert count == 0


def test_upsert_then_query_returns_entry(milvus_store):
    """Round-trip a tiny vector through the live cluster."""
    with bt_span(
        "test_upsert_then_query_returns_entry",
        backend="milvus",
        collection=milvus_store._config.collection,
        upsert_count=1,
        top_k=1,
    ) as span:
        milvus_store.upsert(
            [
                VectorEntry(
                    entity_id="ent-roundtrip",
                    vector=[1.0, 0.0, 0.0, 0.0],
                    entity_name="RoundTrip",
                    content="probe entity for live Milvus",
                    source_id="integration:probe",
                    file_path="test",
                    scope="shared",
                ),
            ]
        )
        # Milvus's flush-on-search is eventual; the search call below
        # waits for consistent read by default.
        hits = milvus_store.query([1.0, 0.0, 0.0, 0.0], top_k=1)
        span.log(
            output={
                "hit_count": len(hits),
                "top_entity_id": hits[0].entry.entity_id if hits else None,
                "top_score": hits[0].score if hits else None,
            }
        )
        assert len(hits) == 1
        assert hits[0].entry.entity_id == "ent-roundtrip"
        assert hits[0].entry.source_id == "integration:probe"


def test_scope_filter_excludes_other_scopes(milvus_store):
    """The metadata-filter path actually filters at the cluster level."""
    with bt_span(
        "test_scope_filter_excludes_other_scopes",
        backend="milvus",
        collection=milvus_store._config.collection,
        upsert_count=2,
        scope_filter="shared",
        top_k=5,
    ) as span:
        milvus_store.upsert(
            [
                VectorEntry(
                    entity_id="ent-shared",
                    vector=[0.0, 1.0, 0.0, 0.0],
                    entity_name="Shared",
                    scope="shared",
                ),
                VectorEntry(
                    entity_id="ent-private",
                    vector=[0.0, 1.0, 0.0, 0.0],
                    entity_name="Private",
                    scope="tenant-foo",
                ),
            ]
        )
        shared_hits = milvus_store.query([0.0, 1.0, 0.0, 0.0], top_k=5, scope="shared")
        shared_ids = {h.entry.entity_id for h in shared_hits}
        span.log(
            output={
                "shared_hit_count": len(shared_hits),
                "shared_ids": sorted(shared_ids),
            }
        )
        assert "ent-shared" in shared_ids
        assert "ent-private" not in shared_ids
