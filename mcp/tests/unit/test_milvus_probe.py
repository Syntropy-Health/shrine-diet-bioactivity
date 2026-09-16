"""Unit tests for the shared Milvus reachability-probe module (#156).

Covers the verdict/probe/emit/main paths that the mcp-ci ``milvus-integration``
workflow runs (``python -m kg_mcp.milvus_probe``) — without a live cluster, by
injecting a fake ``pymilvus`` and monkeypatching the verdict. The pure
classifier is proven separately in ``test_milvus_probe_classifier.py``.
"""
from __future__ import annotations

import sys
import types

import pytest

pytestmark = [pytest.mark.unit]

from kg_mcp import milvus_probe as m  # noqa: E402


# ── resolve_env ──────────────────────────────────────────────────────────────


def test_resolve_env_prefers_zilliz():
    uri, token = m.resolve_env({"ZILLIZ_URI": "https://z", "ZILLIZ_TOKEN": "t"})
    assert uri == "https://z"
    assert token == "t"


def test_resolve_env_falls_back_to_milvus():
    uri, token = m.resolve_env({"MILVUS_URI": "https://mv", "MILVUS_TOKEN": "mt"})
    assert uri == "https://mv"
    assert token == "mt"


def test_resolve_env_empty_is_absent():
    uri, token = m.resolve_env({})
    assert uri == ""
    assert token is None


# ── verdict ──────────────────────────────────────────────────────────────────


def test_verdict_absent_when_no_uri():
    status, _ = m.verdict("", None)
    assert status == "absent"


def test_verdict_malformed_when_not_http():
    status, _ = m.verdict("in03-xyz.zilliz.com:443", "t")
    assert status == "malformed"


def test_verdict_delegates_to_probe_when_well_formed(monkeypatch):
    monkeypatch.setattr(m, "probe_milvus", lambda uri, token: ("unreachable", "dead"))
    status, detail = m.verdict("https://in03-xyz.zilliz.com:443", "t")
    assert status == "unreachable"
    assert detail == "dead"


# ── probe_milvus (fake pymilvus injected into sys.modules) ───────────────────


def _install_fake_pymilvus(monkeypatch, client_factory):
    mod = types.ModuleType("pymilvus")
    mod.MilvusClient = client_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pymilvus", mod)


def test_probe_import_error_is_unknown(monkeypatch):
    # A None entry makes ``from pymilvus import MilvusClient`` raise ImportError.
    monkeypatch.setitem(sys.modules, "pymilvus", None)
    status, detail = m.probe_milvus("https://z", "t")
    assert status == "unknown"
    assert "pymilvus not importable" in detail


def test_probe_connect_failure_classifies_unreachable(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            raise Exception(
                "MilvusException: (code=2, message=Fail connecting to server on in03-x)"
            )

    _install_fake_pymilvus(monkeypatch, _Client)
    status, _ = m.probe_milvus("https://z", "t")
    assert status == "unreachable"


def test_probe_auth_failure_classifies_auth(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def list_collections(self):
            raise Exception("unauthorized: invalid token")

    _install_fake_pymilvus(monkeypatch, _Client)
    status, _ = m.probe_milvus("https://z", "t")
    assert status == "auth"


def test_probe_ok_when_round_trip_succeeds(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def list_collections(self):
            return []

    _install_fake_pymilvus(monkeypatch, _Client)
    status, detail = m.probe_milvus("https://z", "t")
    assert status == "ok"
    assert detail == ""


# ── emit helpers ─────────────────────────────────────────────────────────────


def test_emit_output_writes_status(tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    m._emit_output("unreachable")
    assert "status=unreachable" in out.read_text()


def test_emit_output_noop_without_env(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    m._emit_output("ok")  # must not raise


def test_emit_summary_writes_and_prints(tmp_path, monkeypatch, capsys):
    summ = tmp_path / "gh_summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summ))
    m._emit_summary("hello-summary")
    assert "hello-summary" in summ.read_text()
    assert "hello-summary" in capsys.readouterr().out


# ── main (gate: exit 0 on ok|unreachable, 1 otherwise) ───────────────────────


@pytest.mark.parametrize(
    "status,expected_rc",
    [
        ("ok", 0),
        ("unreachable", 0),
        ("absent", 1),
        ("malformed", 1),
        ("auth", 1),
        ("unknown", 1),
    ],
)
def test_main_exit_codes_and_output(status, expected_rc, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "verdict", lambda uri, token: (status, "detail"))
    monkeypatch.setattr(m, "resolve_env", lambda env=None: ("https://z", "t"))
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rc = m.main([])
    assert rc == expected_rc
    assert f"status={status}" in out.read_text()
