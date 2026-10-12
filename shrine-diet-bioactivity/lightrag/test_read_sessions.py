"""#118: every Neo4j session the scoped server opens is READ.

The KG is read-only shared data [PRINCIPAL-RULED 2026-10-03], and Aura Free has a
single, write-capable user (no RBAC). Every query today is a fixed MATCH … RETURN,
so a READ session changes nothing now; it makes a FUTURE write query fail at the
session instead of committing.

Unit-level: a fake driver records the kwargs of every session it opens.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit]

SERVER = Path(__file__).resolve().parent / "scoped_server.py"


class _EmptyResult:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def single(self):
        return {"x": 1}


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def run(self, *a: Any, **k: Any) -> _EmptyResult:
        return _EmptyResult()


class _RecordingDriver:
    def __init__(self) -> None:
        self.session_kwargs: list[dict[str, Any]] = []

    def session(self, **kw: Any) -> _Session:
        self.session_kwargs.append(kw)
        return _Session()

    async def close(self) -> None:
        return None


@pytest.fixture
def client_and_driver(monkeypatch, tmp_path):
    import scoped_server as ss
    from audit_log import AuditLog
    from fastapi.testclient import TestClient

    drv = _RecordingDriver()
    rag = MagicMock(finalize_storages=AsyncMock())

    async def _fake_build():
        return rag

    async def _fake_init_driver():
        ss._neo4j_driver = drv

    async def _ping():
        return True

    monkeypatch.setenv("SHRINE_CONFIG", "no_such_profile_for_tests")
    monkeypatch.setattr(ss, "_preflight_scope_check", lambda: None)
    monkeypatch.setattr(ss, "_build_scoped_rag", _fake_build)
    monkeypatch.setattr(ss, "_init_neo4j_driver", _fake_init_driver)
    monkeypatch.setattr(ss, "_ping_driver", _ping)
    monkeypatch.setattr(ss, "_probe_llm", AsyncMock())
    monkeypatch.setattr(ss, "_audit", AuditLog(db_path=tmp_path / "audit.db"))
    with TestClient(ss.app) as c:
        yield c, drv


@pytest.mark.parametrize(
    "route,body",
    [
        ("/bilingual_term", {"term": "黄连"}),
        ("/hdi_check", {"drug": "Warfarin", "herb": "Ginkgo"}),
        (
            "/traverse",
            {"start_label": "Compound", "edge_types": ["TARGETS_PROTEIN"], "seed": "CURCUMIN"},
        ),
    ],
)
def test_read_routes_open_only_read_sessions(client_and_driver, route, body) -> None:
    client, drv = client_and_driver
    before = len(drv.session_kwargs)
    resp = client.post(route, json=body)
    assert resp.status_code < 500, resp.text
    opened = drv.session_kwargs[before:]
    assert opened, f"{route} opened no session (test would be vacuous)"
    assert all(kw.get("default_access_mode") == "READ" for kw in opened), opened


def test_no_session_in_the_server_is_opened_without_read_mode() -> None:
    """Source pin: every `<x>.session(...)` call in scoped_server.py passes
    default_access_mode="READ" (covers routes and helpers not exercised above)."""
    tree = ast.parse(SERVER.read_text())
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "session"
    ]
    assert len(calls) >= 6
    bad = []
    for c in calls:
        modes = [k.value for k in c.keywords if k.arg == "default_access_mode"]
        if not (modes and isinstance(modes[0], ast.Constant) and modes[0].value == "READ"):
            bad.append(c.lineno)
    assert bad == [], f"sessions opened without READ at lines {bad}"
