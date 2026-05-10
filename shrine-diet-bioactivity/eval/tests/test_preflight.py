"""Tests for the pre-flight readiness gate.

These are pure unit tests — every external call is mocked. The gate is the
contract; live integration is exercised by running `make eval-run-v1`.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eval.preflight import (  # type: ignore[import-not-found]
    PreflightReport,
    ProbeResult,
    probe_aura,
    probe_lightrag,
    probe_openrouter,
    run_preflight,
)

pytestmark = [pytest.mark.unit]


# ─── ProbeResult / PreflightReport ────────────────────────────────────────


def test_preflight_report_ok_when_all_probes_pass():
    report = PreflightReport(probes=(
        ProbeResult("a", True, ""),
        ProbeResult("b", True, ""),
    ))
    assert report.ok is True


def test_preflight_report_fails_if_any_probe_fails():
    report = PreflightReport(probes=(
        ProbeResult("a", True, "ok"),
        ProbeResult("b", False, "BOOM"),
    ))
    assert report.ok is False


def test_preflight_report_as_manifest_dict_is_json_safe():
    report = PreflightReport(probes=(
        ProbeResult("lightrag", True, "config=local"),
        ProbeResult("aura", False, "TimeoutError: x"),
    ))
    d = report.as_manifest_dict()
    assert d == {
        "lightrag": {"ok": True, "detail": "config=local"},
        "aura": {"ok": False, "detail": "TimeoutError: x"},
    }


def test_preflight_render_includes_each_probe():
    report = PreflightReport(probes=(
        ProbeResult("lightrag", True, "config=local"),
        ProbeResult("aura", False, "down"),
    ))
    s = report.render()
    assert "lightrag" in s and "aura" in s
    assert "OK" in s or "FAILED" in s


# ─── probe_lightrag ───────────────────────────────────────────────────────


def test_probe_lightrag_returns_ok_on_status_ok():
    fake = MagicMock()
    fake.json.return_value = {"status": "ok", "config": "local"}
    fake.raise_for_status.return_value = None
    with patch("requests.get", return_value=fake):
        result = probe_lightrag("http://localhost:9621")
    assert result.ok is True
    assert result.name == "lightrag"
    assert "local" in result.detail


def test_probe_lightrag_fails_on_unhealthy_payload():
    fake = MagicMock()
    fake.json.return_value = {"status": "degraded"}
    fake.raise_for_status.return_value = None
    with patch("requests.get", return_value=fake):
        result = probe_lightrag("http://localhost:9621")
    assert result.ok is False
    assert "degraded" in result.detail


def test_probe_lightrag_fails_on_connection_error():
    with patch("requests.get", side_effect=ConnectionError("refused")):
        result = probe_lightrag("http://localhost:9621")
    assert result.ok is False
    assert "ConnectionError" in result.detail


def test_probe_lightrag_strips_trailing_slash():
    fake = MagicMock()
    fake.json.return_value = {"status": "ok", "config": "local"}
    fake.raise_for_status.return_value = None
    with patch("requests.get", return_value=fake) as get:
        probe_lightrag("http://localhost:9621/")
    called_url = get.call_args[0][0]
    assert called_url == "http://localhost:9621/health"


# ─── probe_aura ───────────────────────────────────────────────────────────


def _fake_aura_driver(*, return_one: int = 1, version: str = "5.26.0"):
    """Build a MagicMock chain mimicking neo4j.GraphDatabase.driver context."""
    driver = MagicMock()
    sess = MagicMock()
    # Two successive `s.run(...)` calls — first returns 1, second yields version row.
    rec1 = MagicMock()
    rec1.__getitem__.return_value = return_one
    rec1.single.return_value = rec1
    rec2 = MagicMock()
    rec2.__getitem__.return_value = version
    rec2.single.return_value = rec2
    sess.run.side_effect = [rec1, rec2]
    sess.__enter__.return_value = sess
    sess.__exit__.return_value = False
    driver.session.return_value = sess
    driver.__enter__.return_value = driver
    driver.__exit__.return_value = False
    return driver


def test_probe_aura_returns_ok_with_version():
    driver = _fake_aura_driver(return_one=1, version="5.26.0")
    with patch("neo4j.GraphDatabase.driver", return_value=driver):
        result = probe_aura("neo4j+s://x.databases.neo4j.io", "neo4j", "pw")
    assert result.ok is True
    assert "5.26.0" in result.detail


def test_probe_aura_fails_on_wrong_value():
    driver = _fake_aura_driver(return_one=999)
    with patch("neo4j.GraphDatabase.driver", return_value=driver):
        result = probe_aura("neo4j+s://x.databases.neo4j.io", "neo4j", "pw")
    assert result.ok is False
    assert "RETURN 1" in result.detail


def test_probe_aura_fails_on_driver_exception():
    with patch("neo4j.GraphDatabase.driver", side_effect=RuntimeError("auth failed")):
        result = probe_aura("neo4j+s://x", "neo4j", "wrong")
    assert result.ok is False
    assert "RuntimeError" in result.detail


# ─── probe_openrouter ─────────────────────────────────────────────────────


def test_probe_openrouter_fails_with_empty_key():
    result = probe_openrouter("", "nvidia/nemotron-3-nano-30b-a3b:free")
    assert result.ok is False
    assert "empty" in result.detail.lower()


def test_probe_openrouter_returns_ok_on_completion():
    msg = MagicMock()
    msg.content = "x"
    choice = MagicMock()
    choice.message = msg
    reply = MagicMock()
    reply.choices = [choice]

    client = MagicMock()
    client.chat.completions.create.return_value = reply

    with patch("openai.OpenAI", return_value=client):
        result = probe_openrouter("sk-or-...", "nvidia/nemotron-3-nano-30b-a3b:free")
    assert result.ok is True
    assert "nvidia/nemotron-3-nano-30b-a3b:free" in result.detail


def test_probe_openrouter_fails_on_empty_content():
    msg = MagicMock()
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    reply = MagicMock()
    reply.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = reply

    with patch("openai.OpenAI", return_value=client):
        result = probe_openrouter("sk-or-...", "model-x")
    assert result.ok is False


def test_probe_openrouter_fails_on_api_exception():
    client = MagicMock()
    client.chat.completions.create.side_effect = TimeoutError("network")
    with patch("openai.OpenAI", return_value=client):
        result = probe_openrouter("sk-or-...", "model-x")
    assert result.ok is False
    assert "TimeoutError" in result.detail


# ─── run_preflight aggregator ─────────────────────────────────────────────


def test_run_preflight_aggregates_all_three_probes():
    with (
        patch("eval.preflight.probe_lightrag", return_value=ProbeResult("lightrag", True, "ok")),
        patch("eval.preflight.probe_aura", return_value=ProbeResult("aura", True, "ok")),
        patch("eval.preflight.probe_openrouter", return_value=ProbeResult("openrouter", True, "ok")),
    ):
        report = run_preflight(
            lightrag_url="http://localhost:9621",
            aura_uri="neo4j+s://x",
            aura_user="u",
            aura_password="p",
            openrouter_api_key="k",
        )
    assert report.ok is True
    names = {p.name for p in report.probes}
    assert names == {"lightrag", "aura", "openrouter"}


def test_run_preflight_reports_failure_when_one_probe_fails():
    with (
        patch("eval.preflight.probe_lightrag", return_value=ProbeResult("lightrag", False, "down")),
        patch("eval.preflight.probe_aura", return_value=ProbeResult("aura", True, "ok")),
        patch("eval.preflight.probe_openrouter", return_value=ProbeResult("openrouter", True, "ok")),
    ):
        report = run_preflight(
            lightrag_url="http://localhost:9621",
            aura_uri="neo4j+s://x", aura_user="u", aura_password="p",
            openrouter_api_key="k",
        )
    assert report.ok is False


def test_run_preflight_reads_env_when_args_missing(monkeypatch):
    monkeypatch.setenv("LIGHTRAG_URL", "http://test:9999")
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://envuri")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "envpw")
    monkeypatch.setenv("OPENROUTER_API_KEY", "envkey")

    captured: dict = {}

    def fake_lightrag(url, timeout=5.0):
        captured["lightrag_url"] = url
        return ProbeResult("lightrag", True, "ok")

    def fake_aura(uri, user, password, timeout=10.0):
        captured["aura_uri"] = uri
        captured["aura_user"] = user
        return ProbeResult("aura", True, "ok")

    def fake_or(api_key, model, timeout=30.0):
        captured["or_key"] = api_key
        return ProbeResult("openrouter", True, "ok")

    with (
        patch("eval.preflight.probe_lightrag", side_effect=fake_lightrag),
        patch("eval.preflight.probe_aura", side_effect=fake_aura),
        patch("eval.preflight.probe_openrouter", side_effect=fake_or),
    ):
        run_preflight()

    assert captured == {
        "lightrag_url": "http://test:9999",
        "aura_uri": "neo4j+s://envuri",
        "aura_user": "neo4j",
        "or_key": "envkey",
    }
