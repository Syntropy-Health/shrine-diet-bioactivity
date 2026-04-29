"""Pre-flight readiness gate for the eval runner.

Why this exists: the v1 eval run on 2026-04-25 produced a silent all-zeros
result because LightRAG was unreachable while the runner was happily emitting
error placeholders. The post-mortem (`research-journal/shared/2026-04-26-v1-postmortem-and-next-steps.md`)
identified the missing readiness gate as the single most important fix
before any v1 re-run.

Each probe returns a ProbeResult — non-raising — so the aggregator
`run_preflight()` can build a complete picture even if one dependency is
down. The runner CLI then decides whether to abort. We deliberately avoid
mixing the probe logic with the abort decision to keep both testable in
isolation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single readiness probe.

    `detail` carries a version string on success or an error class+message on
    failure — not for parsing, just for human/log diagnosis.
    """

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    """Aggregate of all probe results. `ok` is the AND across probes."""

    probes: tuple[ProbeResult, ...]

    @property
    def ok(self) -> bool:
        return all(p.ok for p in self.probes)

    def as_manifest_dict(self) -> dict:
        """Stable, JSON-serializable form for run manifests."""
        return {p.name: {"ok": p.ok, "detail": p.detail} for p in self.probes}

    def render(self) -> str:
        """Human-readable multi-line summary, suitable for stderr."""
        lines = [f"Preflight: {'OK' if self.ok else 'FAILED'}"]
        for p in self.probes:
            mark = "✓" if p.ok else "✗"
            lines.append(f"  {mark} {p.name}: {p.detail}")
        return "\n".join(lines)


def probe_lightrag(url: str, timeout: float = 5.0) -> ProbeResult:
    """GET <url>/health. Expects a JSON object with status == 'ok'."""
    import requests

    try:
        resp = requests.get(f"{url.rstrip('/')}/health", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ok":
            return ProbeResult("lightrag", True, f"config={data.get('config', '?')}")
        return ProbeResult("lightrag", False, f"unhealthy response: {data}")
    except Exception as exc:  # noqa: BLE001 — broad catch is intentional for a probe
        return ProbeResult("lightrag", False, f"{type(exc).__name__}: {exc}")


def probe_aura(uri: str, user: str, password: str, timeout: float = 10.0) -> ProbeResult:
    """Run `RETURN 1` against Aura and capture the dbms.components version."""
    try:
        from neo4j import GraphDatabase

        with GraphDatabase.driver(uri, auth=(user, password), connection_timeout=timeout) as driver:
            with driver.session() as s:
                ping = s.run("RETURN 1 AS x").single()
                if ping is None or ping["x"] != 1:
                    return ProbeResult("aura", False, "RETURN 1 did not return 1")
                rec = s.run(
                    "CALL dbms.components() YIELD name, versions "
                    "RETURN versions[0] AS v LIMIT 1"
                ).single()
                version = rec["v"] if rec else "unknown"
                return ProbeResult("aura", True, f"neo4j {version}")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("aura", False, f"{type(exc).__name__}: {exc}")


def probe_openrouter(api_key: str, model: str, timeout: float = 30.0) -> ProbeResult:
    """Smoke a 1-token completion through OpenRouter — verifies auth + model availability.

    We don't use models.list because free-tier model presence is inconsistent there;
    a tiny completion is the truthful test of "can we actually invoke this model now?".
    """
    if not api_key:
        return ProbeResult("openrouter", False, "OPENROUTER_API_KEY is empty")
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            timeout=timeout,
        )
        reply = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            temperature=0,
        )
        if reply.choices and reply.choices[0].message.content is not None:
            return ProbeResult("openrouter", True, f"model {model} reachable")
        return ProbeResult("openrouter", False, f"model {model} returned empty content")
    except Exception as exc:  # noqa: BLE001
        return ProbeResult("openrouter", False, f"{type(exc).__name__}: {exc}")


def run_preflight(
    *,
    lightrag_url: str | None = None,
    aura_uri: str | None = None,
    aura_user: str | None = None,
    aura_password: str | None = None,
    openrouter_api_key: str | None = None,
    openrouter_model: str = "nvidia/nemotron-3-nano-30b-a3b:free",
) -> PreflightReport:
    """Run all probes, returning a report. None args fall back to env vars.

    Falling back to env keeps the call site of the runner CLI simple, and lets
    tests inject explicit values without touching os.environ.
    """
    lightrag_url = lightrag_url or os.environ.get("LIGHTRAG_URL", "http://localhost:9621")
    aura_uri = aura_uri or os.environ.get("NEO4J_URI", "")
    aura_user = aura_user or os.environ.get("NEO4J_USERNAME", "")
    aura_password = aura_password or os.environ.get("NEO4J_PASSWORD", "")
    openrouter_api_key = openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")

    probes = (
        probe_lightrag(lightrag_url),
        probe_aura(aura_uri, aura_user, aura_password),
        probe_openrouter(openrouter_api_key, openrouter_model),
    )
    return PreflightReport(probes=probes)


__all__ = [
    "ProbeResult",
    "PreflightReport",
    "probe_lightrag",
    "probe_aura",
    "probe_openrouter",
    "run_preflight",
]
