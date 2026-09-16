"""Milvus/Zilliz reachability probe + verdict — the SINGLE source of truth for
the #156 three-way skip, shared by BOTH consumers:

  * the mcp-ci ``milvus-integration`` workflow (``python -m kg_mcp.milvus_probe``
    as an early step that GATES the pre-flight cleanup), and
  * the pytest fixture in ``tests/integration/test_milvus_vectorstore.py``.

One classifier, one decision — so the pre-flight step and the test fixture can
never disagree about whether the endpoint is reachable. The verdict:

  credential ABSENT / MALFORMED   -> FAIL  (a config gap someone must fix)
  endpoint    UNREACHABLE          -> SKIP  (infra absence, e.g. dead Zilliz
                                             serverless — loud, self-heals)
  reachable + credential REJECTED  -> FAIL  (our problem: bad/expired token)
  probe raised an UNCLASSIFIED err -> FAIL  (never silently skip a failure we
                                             do not understand)
  reachable + credential good      -> OK    (run; failures are the real signal)

The classifier is pure stdlib (unit-tested without a cluster); ``pymilvus`` is
imported lazily only when an actual round-trip is made.
"""
from __future__ import annotations

import os
import re
import sys

# Connection-class error substrings -> the endpoint is UNREACHABLE (infra
# absence). The dead-Zilliz-serverless signature is "illegal connection params
# or server unavailable"; the rest are the usual transport failures.
UNREACHABLE_SIGNS: tuple[str, ...] = (
    "illegal connection params or server unavailable",
    "server unavailable",
    "connection refused",
    "failed to connect",
    "fail connecting",
    "cannot connect",
    "timed out",
    "timeout",
    "name or service not known",
    "temporary failure in name resolution",
    "no route to host",
    "connection error",
    "connection reset",
)
# Auth-class error substrings -> credential REJECTED (our problem -> FAIL).
AUTH_SIGNS: tuple[str, ...] = (
    "unauthorized",
    "unauthenticated",
    "permission denied",
    "forbidden",
    "invalid token",
    "authentication failed",
    "access denied",
)


def classify_probe_error(msg: str) -> str:
    """Map a probe exception message to 'unreachable' | 'auth' | 'unknown'.

    Auth is checked FIRST: a rejected credential is our problem and must not be
    masked as a connectivity skip. Anything unclassifiable is 'unknown' — which
    the caller FAILs on rather than silently skipping (a skip on an error we do
    not understand could hide a real regression).
    """
    m = (msg or "").lower()
    if any(s in m for s in AUTH_SIGNS):
        return "auth"
    if any(s in m for s in UNREACHABLE_SIGNS):
        return "unreachable"
    return "unknown"


def probe_milvus(uri: str, token: str | None) -> tuple[str, str]:
    """Live reachability probe: returns ('ok'|'unreachable'|'auth'|'unknown', detail).
    A real round-trip (list_collections) with a short timeout."""
    try:
        from pymilvus import MilvusClient  # type: ignore[import-not-found]
    except ImportError as exc:  # the vector-milvus extra is a declared test dep
        return ("unknown", f"pymilvus not importable: {exc}")
    try:
        client = MilvusClient(uri=uri, token=token or "", timeout=10)
        client.list_collections()
        return ("ok", "")
    except Exception as exc:  # noqa: BLE001 — classify, do not swallow
        return (classify_probe_error(str(exc)), str(exc)[:200])


def resolve_env(env: dict[str, str] | None = None) -> tuple[str, str | None]:
    """Resolve (uri, token) from ZILLIZ_* with MILVUS_* fallbacks."""
    e = os.environ if env is None else env
    uri = e.get("ZILLIZ_URI") or e.get("MILVUS_URI") or ""
    token = e.get("ZILLIZ_TOKEN") or e.get("MILVUS_TOKEN") or None
    return uri, token


def verdict(uri: str, token: str | None) -> tuple[str, str]:
    """Full #156 verdict over (uri, token): returns (status, detail) where status
    is one of 'ok' | 'unreachable' | 'auth' | 'unknown' | 'absent' | 'malformed'.

    Pure decision logic (calls the live probe only when uri is present + well
    formed) — the one place the skip-vs-fail decision is made for BOTH consumers.
    """
    if not uri:
        return ("absent", "ZILLIZ_URI / MILVUS_URI not set")
    if not re.match(r"^https?://", uri):
        return ("malformed", f"expected an https:// endpoint, got {uri!r}")
    return probe_milvus(uri, token)


# Statuses on which the job SKIPS (green) vs FAILS (red).
_SKIP_OK = {"ok", "unreachable"}


def _emit_summary(line: str) -> None:
    """Write a line to the GitHub job summary (not only a log nobody opens) and
    stdout. Best-effort."""
    print(line, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001 — summary is best-effort
            pass


def _emit_output(status: str) -> None:
    """Expose the classification to later workflow steps via $GITHUB_OUTPUT."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"status={status}\n")
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    """Workflow entrypoint: probe once, publish the classification, and gate.

    Exit 0 on ok|unreachable (the job proceeds / skips-loud); exit 1 on
    absent|malformed|auth|unknown (a real problem someone must fix). The
    classification is written to $GITHUB_OUTPUT as ``status=<...>`` so the
    pre-flight step can gate on ``steps.<id>.outputs.status == 'ok'``.
    """
    uri, token = resolve_env()
    status, detail = verdict(uri, token)
    _emit_output(status)

    if status == "ok":
        _emit_summary("✅ Milvus probe: OK — endpoint reachable, credential accepted [#156].")
        return 0
    if status == "unreachable":
        _emit_summary(
            "⚠️ Milvus probe: UNREACHABLE — vector-store coverage is ABSENT this run "
            f"(skipped, NOT passing) [reason=unreachable] [#156]: {detail}. "
            "Infra absence (e.g. Zilliz serverless expired); pre-flight + tests skip "
            "loud and re-run automatically when it returns."
        )
        return 0
    # Fail-closed statuses.
    reasons = {
        "absent": "credential ABSENT — a config gap someone must fix, not infra absence",
        "malformed": "credential MALFORMED — a config error",
        "auth": "credential REJECTED (bad/expired token) — our problem",
        "unknown": "probe failed with an UNCLASSIFIED error — failing so it is not masked",
    }
    _emit_summary(
        f"❌ Milvus probe: {status.upper()} [reason={status}] [#156]: "
        f"{reasons.get(status, status)}: {detail}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
