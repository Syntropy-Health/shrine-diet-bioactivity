"""#104 — the deployed scoped_server must embed queries with the SAME embedder the
Aura vectors were built with (gemini-embedding-001 @ 1024 via Vertex) and must
read those vectors from Aura (ScopedNeo4JVectorStorage), not a local Nano store.

Unit-level: no network, no Neo4j, no Vertex. The live acceptance check — a
semantic kg_query returning scored, on-topic neighbours — runs against the
deployed plane after landing.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

LIGHTRAG_DIR = Path(__file__).resolve().parent
REPO_ROOT = LIGHTRAG_DIR.parent.parent


# ─── vector backend ────────────────────────────────────────────────────────


def test_neo4j_backend_selects_the_aura_vector_storage() -> None:
    import scoped_server as ss

    assert ss._resolve_vector_storage({"KG_VECTOR_BACKEND": "neo4j"}) == "ScopedNeo4JVectorStorage"
    # Unchanged defaults: nano stays the default, unknown values still raise.
    assert ss._resolve_vector_storage({}) == "NanoVectorDBStorage"
    with pytest.raises(ValueError):
        ss._resolve_vector_storage({"KG_VECTOR_BACKEND": "neo4"})


# ─── embedder selection ────────────────────────────────────────────────────


def test_vertex_binding_uses_the_adapter_with_the_resolved_model_and_dim(monkeypatch) -> None:
    import embedder_adapters as ea
    import scoped_server as ss

    seen: dict[str, Any] = {}
    sentinel_adapter = object()
    sentinel_func = object()

    def fake_make(binding, *, model=None, dim=None, **_):
        seen.update(binding=binding, model=model, dim=dim)
        return sentinel_adapter

    monkeypatch.setattr(ea, "make_embedder", fake_make)
    monkeypatch.setattr(ea, "to_embedding_func", lambda a, **_: sentinel_func if a is sentinel_adapter else None)

    out = ss._adapter_embedding_func("vertex", "unified_diet_kg", "gemini-embedding-001", 1024)
    assert out is sentinel_func
    # The query embedder must be built from the SAME resolved values that the
    # workspace check compares against WorkspaceMeta — never the adapter's own
    # env defaults.
    assert seen == {"binding": "vertex", "model": "gemini-embedding-001", "dim": 1024}


@pytest.mark.parametrize("binding", ["", "openai", "ollama"])
def test_non_gemini_bindings_keep_the_native_path(binding) -> None:
    import scoped_server as ss

    assert ss._adapter_embedding_func(binding, "unified_diet_kg", "m", 1024) is None


def test_local_embedder_against_the_production_workspace_is_refused() -> None:
    import scoped_server as ss

    # 'local' is an adapter binding but unreachable from Railway: the router guard
    # must refuse it for unified_diet_kg rather than build a dead embedder.
    with pytest.raises(SystemExit):
        ss._adapter_embedding_func("local", "unified_diet_kg", "text-embedding-bge-m3", 1024)


# ─── read-only workspace embedding check ───────────────────────────────────


def test_workspace_check_passes_on_an_exact_match() -> None:
    import scoped_server as ss

    rec = {"model": "gemini-embedding-001", "dim": 1024}
    assert ss._workspace_embedding_problem(rec, "gemini-embedding-001", 1024) is None


@pytest.mark.parametrize(
    "rec,expect",
    [
        (None, "no WorkspaceMeta"),
        ({"model": "gemini-embedding-001", "dim": 2048}, "2048"),
        ({"model": "text-embedding-bge-m3", "dim": 1024}, "text-embedding-bge-m3"),
    ],
)
def test_workspace_check_names_the_problem(rec, expect) -> None:
    import scoped_server as ss

    problem = ss._workspace_embedding_problem(rec, "gemini-embedding-001", 1024)
    assert problem is not None and expect in problem


def test_workspace_check_reads_and_never_writes(monkeypatch) -> None:
    """The query side must not stamp WorkspaceMeta: an absent node means the
    vectors are not there, and binding the space from the gateway would let a
    wrong embedder define it. The query must be a READ session with no MERGE."""
    import asyncio
    from unittest.mock import AsyncMock

    import scoped_server as ss

    result = MagicMock()
    result.single = AsyncMock(return_value=None)
    session = MagicMock()
    session.run = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver = MagicMock()
    driver.session = MagicMock(return_value=session)

    rec = asyncio.run(ss._read_workspace_meta(driver, "unified_diet_kg"))
    assert rec is None
    kwargs = driver.session.call_args.kwargs
    assert kwargs.get("default_access_mode") == "READ"
    cypher = session.run.call_args.args[0]
    assert "MATCH" in cypher and "MERGE" not in cypher.upper() and "SET " not in cypher.upper()


# ─── /query is disabled (503) — typed routes unaffected — when the check fails ─


@pytest.fixture
def client(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    import scoped_server as ss
    from audit_log import AuditLog

    rag = MagicMock()
    rag.aquery = AsyncMock(return_value="semantic answer")

    async def _noop():
        return None

    rag.finalize_storages = _noop

    async def _fake_build():
        return rag

    async def _fake_init_driver():
        ss._neo4j_driver = MagicMock(close=AsyncMock())

    # Pin a profile that does not exist so booting never loads config_local.env
    # (override=True) into the real os.environ and leaks into later tests.
    monkeypatch.setenv("SHRINE_CONFIG", "no_such_profile_for_tests")
    monkeypatch.setattr(ss, "_preflight_scope_check", lambda: None)
    monkeypatch.setattr(ss, "_build_scoped_rag", _fake_build)
    monkeypatch.setattr(ss, "_init_neo4j_driver", _fake_init_driver)
    monkeypatch.setattr(ss, "_audit", AuditLog(db_path=tmp_path / "audit.db"))
    with TestClient(ss.app) as c:
        yield c
    ss._SEMANTIC_DISABLED_REASON = None


def test_query_returns_503_with_the_reason_when_semantic_is_disabled(client, monkeypatch) -> None:
    import scoped_server as ss

    monkeypatch.setattr(ss, "_SEMANTIC_DISABLED_REASON", "embedding space mismatch: test")
    resp = client.post("/query", json={"query": "curcumin targets", "mode": "local", "scope_filter": ["shared"]})
    assert resp.status_code == 503
    assert "embedding space mismatch" in resp.json()["detail"]


def test_query_still_answers_when_semantic_is_enabled(client, monkeypatch) -> None:
    import scoped_server as ss

    monkeypatch.setattr(ss, "_SEMANTIC_DISABLED_REASON", None)
    resp = client.post("/query", json={"query": "curcumin targets", "mode": "local", "scope_filter": ["shared"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["response"] == "semantic answer"


# ─── deployed config profile ───────────────────────────────────────────────


def _env_file(name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (LIGHTRAG_DIR / name).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_deployed_profile_pins_the_aura_embedding_space() -> None:
    env = _env_file("config_deployed.env")
    assert env["EMBEDDING_BINDING"] == "vertex"
    assert env["EMBEDDING_MODEL"] == "gemini-embedding-001"
    assert env["EMBEDDING_DIM"] == "1024"
    assert env["KG_VECTOR_BACKEND"] == "neo4j"
    assert env["WORKSPACE"] == "unified_diet_kg"
    # Vertex default quota 429s above 1 concurrent embed (measured 2026-09-11).
    assert env["EMBEDDING_FUNC_MAX_ASYNC"] == "1"
    # The profile must not pin the GCP project/location or carry any credential:
    # those come from the Railway service env (devex #13866).
    for k in env:
        assert not k.startswith("GOOGLE_"), k
    for k, v in env.items():
        if re.search(r"(_KEY|_TOKEN|PASSWORD|SECRET)$", k):
            assert v.startswith("${"), f"{k} must be an env reference, not a literal"


def test_the_image_boots_the_deployed_profile_and_ships_the_genai_client() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "SHRINE_CONFIG=deployed" in dockerfile
    reqs = (LIGHTRAG_DIR / "requirements.txt").read_text()
    assert "google-genai" in reqs


# ─── ADC credential file at boot ───────────────────────────────────────────

# synthetic fixture: not a real key (fake 3-char body), shaped like a service-account JSON
SECRET = '{"type":"service_account","private_key":"-----BEGIN PRIVATE KEY-----\\nZZZ\\n-----END PRIVATE KEY-----\\n","client_email":"kg@x.iam.gserviceaccount.com"}'


def _run_adc(env: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    script = REPO_ROOT / "scripts" / "write_adc.sh"
    probe = (
        f'set -euo pipefail; source "{script}"; '
        'echo "PATH_SET=${GOOGLE_APPLICATION_CREDENTIALS:-}"; '
        'echo "JSON_LEFT=${GOOGLE_APPLICATION_CREDENTIALS_JSON:+yes}"'
    )
    full_env = {"PATH": os.environ["PATH"], "TMPDIR": str(tmp_path), **env}
    return subprocess.run(["bash", "-c", probe], env=full_env, capture_output=True, text=True, check=False)


def test_adc_json_is_written_0600_exported_and_never_echoed(tmp_path) -> None:
    r = _run_adc({"GOOGLE_APPLICATION_CREDENTIALS_JSON": SECRET}, tmp_path)
    assert r.returncode == 0, r.stderr
    lines = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    path = Path(lines["PATH_SET"])
    assert path.is_file()
    assert path.read_text() == SECRET
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # The raw JSON leaves the environment once it is on disk, and never reaches logs.
    assert lines["JSON_LEFT"] == ""
    assert "PRIVATE KEY" not in r.stdout + r.stderr


def test_adc_respects_an_existing_credentials_path(tmp_path) -> None:
    preset = tmp_path / "preset.json"
    preset.write_text("{}")
    r = _run_adc(
        {"GOOGLE_APPLICATION_CREDENTIALS": str(preset), "GOOGLE_APPLICATION_CREDENTIALS_JSON": SECRET}, tmp_path
    )
    assert r.returncode == 0, r.stderr
    assert f"PATH_SET={preset}" in r.stdout


def test_adc_is_a_noop_without_the_json_var(tmp_path) -> None:
    r = _run_adc({}, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "PATH_SET=\n" in r.stdout + "\n"


# ─── startup wiring: the check actually runs at boot ──────────────────────


def _boot_with_meta(monkeypatch, tmp_path, meta: Any):
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    import scoped_server as ss
    from audit_log import AuditLog

    # No config file: a name that does not exist leaves the process env in charge.
    monkeypatch.setenv("SHRINE_CONFIG", "no_such_profile_for_tests")
    monkeypatch.setenv("KG_VECTOR_BACKEND", "neo4j")
    monkeypatch.setenv("WORKSPACE", "unified_diet_kg")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("EMBEDDING_DIM", "1024")

    rag = MagicMock()
    rag.aquery = AsyncMock(return_value="semantic answer")

    async def _noop():
        return None

    rag.finalize_storages = _noop

    async def _fake_build():
        return rag

    async def _fake_init_driver():
        ss._neo4j_driver = MagicMock(close=AsyncMock())

    async def _fake_read(driver, workspace):
        assert workspace == "unified_diet_kg"
        return meta

    monkeypatch.setattr(ss, "_preflight_scope_check", lambda: None)
    monkeypatch.setattr(ss, "_build_scoped_rag", _fake_build)
    monkeypatch.setattr(ss, "_init_neo4j_driver", _fake_init_driver)
    monkeypatch.setattr(ss, "_read_workspace_meta", _fake_read)
    monkeypatch.setattr(ss, "_audit", AuditLog(db_path=tmp_path / "audit.db"))
    return TestClient(ss.app)


@pytest.mark.parametrize(
    "meta,want",
    [
        ({"model": "gemini-embedding-001", "dim": 1024}, 200),
        ({"model": "nvidia/llama-nemotron-embed-vl-1b-v2:free", "dim": 2048}, 503),
        (None, 503),
    ],
)
def test_boot_runs_the_workspace_check_and_gates_query(monkeypatch, tmp_path, meta, want) -> None:
    import scoped_server as ss

    with _boot_with_meta(monkeypatch, tmp_path, meta) as c:
        resp = c.post("/query", json={"query": "curcumin targets", "mode": "local", "scope_filter": ["shared"]})
        assert resp.status_code == want, resp.text
    ss._SEMANTIC_DISABLED_REASON = None


# ─── QG round 2: a semantic precondition failure must never take down the typed routes ─


class _FakeLightRAG:
    """Records constructor kwargs; initialize_storages may be told to fail when the
    Aura vector storage is selected (e.g. an index-dimension mismatch)."""

    calls: ClassVar[list[dict[str, Any]]] = []
    fail_on_neo4j_vectors: ClassVar[bool] = False

    def __init__(self, **kwargs):
        type(self).calls.append(kwargs)
        self.kwargs = kwargs

    async def initialize_storages(self):
        if type(self).fail_on_neo4j_vectors and self.kwargs.get("vector_storage") == "ScopedNeo4JVectorStorage":
            raise RuntimeError("vector index dim mismatch (test)")

    async def finalize_storages(self):
        return None


@pytest.fixture
def fake_lightrag(monkeypatch):
    import lightrag

    _FakeLightRAG.calls = []
    _FakeLightRAG.fail_on_neo4j_vectors = False
    monkeypatch.setattr(lightrag, "LightRAG", _FakeLightRAG)
    return _FakeLightRAG


def _semantic_env(monkeypatch, tmp_path, **over):
    creds = tmp_path / "adc.json"
    creds.write_text("{}")
    env = {
        "SHRINE_CONFIG": "no_such_profile_for_tests",
        "KG_VECTOR_BACKEND": "neo4j",
        "WORKSPACE": "unified_diet_kg",
        "EMBEDDING_BINDING": "vertex",
        "EMBEDDING_MODEL": "gemini-embedding-001",
        "EMBEDDING_DIM": "1024",
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_APPLICATION_CREDENTIALS": str(creds),
    }
    env.update(over)
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def test_build_wires_the_adapter_embedder_and_aura_vectors(monkeypatch, tmp_path, fake_lightrag) -> None:
    import asyncio

    import scoped_server as ss

    _semantic_env(monkeypatch, tmp_path)
    seen = []
    sentinel = object()

    def rec(binding, workspace, model, dim):
        seen.append((binding, workspace, model, dim))
        return sentinel

    monkeypatch.setattr(ss, "_adapter_embedding_func", rec)
    monkeypatch.setattr(ss, "_SEMANTIC_DISABLED_REASON", None)
    asyncio.run(ss._build_scoped_rag())
    kw = fake_lightrag.calls[-1]
    assert kw["embedding_func"] is sentinel
    assert kw["vector_storage"] == "ScopedNeo4JVectorStorage"
    assert seen == [("vertex", "unified_diet_kg", "gemini-embedding-001", 1024)]
    from lightrag.kg import STORAGE_IMPLEMENTATIONS

    assert "ScopedNeo4JVectorStorage" in STORAGE_IMPLEMENTATIONS["VECTOR_STORAGE"]["implementations"]


def test_build_with_semantic_disabled_never_touches_the_aura_vectors(monkeypatch, tmp_path, fake_lightrag) -> None:
    import asyncio

    import scoped_server as ss

    _semantic_env(monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(ss, "_adapter_embedding_func", lambda *a: called.append(a))
    monkeypatch.setattr(ss, "_SEMANTIC_DISABLED_REASON", "embedding space mismatch: test")
    asyncio.run(ss._build_scoped_rag())
    assert fake_lightrag.calls[-1]["vector_storage"] == "NanoVectorDBStorage"
    assert called == []


def _boot(monkeypatch, tmp_path, *, meta: Any = None, read_exc: Exception | None = None):
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    import scoped_server as ss
    from audit_log import AuditLog

    async def _fake_init_driver():
        ss._neo4j_driver = MagicMock(close=AsyncMock())

    reads = []

    async def _fake_read(driver, workspace):
        reads.append(workspace)
        if read_exc is not None:
            raise read_exc
        return meta

    async def _ping():
        return True

    monkeypatch.setattr(ss, "_preflight_scope_check", lambda: None)
    monkeypatch.setattr(ss, "_init_neo4j_driver", _fake_init_driver)
    monkeypatch.setattr(ss, "_read_workspace_meta", _fake_read)
    monkeypatch.setattr(ss, "_ping_driver", _ping)
    monkeypatch.setattr(ss, "_adapter_embedding_func", lambda *a: None)
    monkeypatch.setattr(ss, "_audit", AuditLog(db_path=tmp_path / "audit.db"))
    return TestClient(ss.app), reads


GOOD_META = {"model": "gemini-embedding-001", "dim": 1024}


def test_vector_init_failure_degrades_to_503_instead_of_crashing_boot(monkeypatch, tmp_path, fake_lightrag) -> None:
    import scoped_server as ss

    _semantic_env(monkeypatch, tmp_path)
    fake_lightrag.fail_on_neo4j_vectors = True
    client, _ = _boot(monkeypatch, tmp_path, meta=GOOD_META)
    with client as c:
        assert c.get("/health").status_code == 200
        r = c.post("/query", json={"query": "q", "mode": "local", "scope_filter": ["shared"]})
        assert r.status_code == 503
        assert "vector storage failed to initialise" in r.json()["detail"]
    # Retried without the Aura vectors, so the typed routes have a live rag.
    assert [k["vector_storage"] for k in fake_lightrag.calls] == ["ScopedNeo4JVectorStorage", "NanoVectorDBStorage"]
    ss._SEMANTIC_DISABLED_REASON = None


def test_workspace_read_error_disables_query_without_leaking_the_message(monkeypatch, tmp_path, fake_lightrag) -> None:
    import scoped_server as ss

    _semantic_env(monkeypatch, tmp_path)
    client, _ = _boot(monkeypatch, tmp_path, read_exc=RuntimeError("neo4j+s://user:hunter2@host unreachable"))
    with client as c:
        r = c.post("/query", json={"query": "q", "mode": "local", "scope_filter": ["shared"]})
        assert r.status_code == 503
        assert "could not read WorkspaceMeta: RuntimeError" in r.json()["detail"]
        assert "hunter2" not in r.text
        assert "hunter2" not in c.get("/health").text
    assert fake_lightrag.calls[-1]["vector_storage"] == "NanoVectorDBStorage"
    ss._SEMANTIC_DISABLED_REASON = None


def test_nano_backend_skips_the_semantic_checks(monkeypatch, tmp_path, fake_lightrag) -> None:
    import scoped_server as ss

    _semantic_env(monkeypatch, tmp_path, KG_VECTOR_BACKEND="nano", GOOGLE_CLOUD_PROJECT=None)
    client, reads = _boot(monkeypatch, tmp_path, meta=None)
    with client as c:
        assert c.get("/health").json()["semantic"] == "off"
    assert reads == []
    assert ss._SEMANTIC_DISABLED_REASON is None


@pytest.mark.parametrize(
    "over,expect",
    [
        ({"GOOGLE_CLOUD_PROJECT": None}, "GOOGLE_CLOUD_PROJECT"),
        ({"GOOGLE_APPLICATION_CREDENTIALS": "/nonexistent/adc.json"}, "credentials"),
        ({"EMBEDDING_BINDING": "local"}, "not reachable from the deployed gateway"),
    ],
)
def test_embedder_preconditions_disable_semantic_with_a_named_reason(
    monkeypatch, tmp_path, fake_lightrag, over, expect
) -> None:
    import scoped_server as ss

    _semantic_env(monkeypatch, tmp_path, **over)
    client, _ = _boot(monkeypatch, tmp_path, meta=GOOD_META)
    with client as c:
        h = c.get("/health").json()
        assert h["status"] == "ok"
        assert h["semantic"] == "disabled"
        assert expect in h["semantic_reason"]
    assert fake_lightrag.calls[-1]["vector_storage"] == "NanoVectorDBStorage"
    ss._SEMANTIC_DISABLED_REASON = None


def test_health_reports_semantic_enabled_when_everything_matches(monkeypatch, tmp_path, fake_lightrag) -> None:
    import scoped_server as ss

    _semantic_env(monkeypatch, tmp_path)
    client, _ = _boot(monkeypatch, tmp_path, meta=GOOD_META)
    with client as c:
        h = c.get("/health").json()
        assert (h["status"], h["semantic"], h["semantic_reason"]) == ("ok", "enabled", None)
    assert fake_lightrag.calls[-1]["vector_storage"] == "ScopedNeo4JVectorStorage"
    ss._SEMANTIC_DISABLED_REASON = None


def test_malformed_workspace_dim_is_a_reason_not_a_crash() -> None:
    import scoped_server as ss

    problem = ss._workspace_embedding_problem({"model": "gemini-embedding-001", "dim": "not-a-number"}, "gemini-embedding-001", 1024)
    assert problem is not None and "not-a-number" in problem


# ─── boot script + image wiring (static) ──────────────────────────────────


def _code_lines(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_boot_script_sources_adc_before_uvicorn_and_hides_it_from_the_gateway() -> None:
    lines = _code_lines(REPO_ROOT / "scripts" / "start_combined.sh")
    src = next(i for i, ln in enumerate(lines) if ln.startswith("source ") and "write_adc.sh" in ln)
    uvi = next(i for i, ln in enumerate(lines) if ln.startswith("uvicorn scoped_server:app"))
    gw = next(i for i, ln in enumerate(lines) if ln.startswith("exec python -m kg_mcp.server"))
    unset = next(i for i, ln in enumerate(lines) if ln == "unset GOOGLE_APPLICATION_CREDENTIALS")
    assert src < uvi < unset < gw
    dockerfile = _code_lines(REPO_ROOT / "Dockerfile")
    assert "COPY scripts/write_adc.sh /app/write_adc.sh" in dockerfile
    assert "COPY scripts/start_combined.sh /app/start_combined.sh" in dockerfile


def test_deployed_profile_pins_destructive_index_recreate_off() -> None:
    env = _env_file("config_deployed.env")
    # Empty overrides any inherited =1 (override=True); the storage treats "" as off.
    assert env.get("VECTOR_INDEX_ALLOW_RECREATE", None) == ""


def test_loading_the_deployed_profile_keeps_railway_values(monkeypatch) -> None:
    import scoped_server as ss

    saved = dict(os.environ)
    try:
        for k, v in {
            "SHRINE_CONFIG": "deployed",
            "NEO4J_URI": "neo4j+s://fake-host:7687",
            "NEO4J_USERNAME": "fake-user",
            "NEO4J_PASSWORD": "fake-pass",
            "OPENROUTER_API_KEY": "fake-or-key",
            "GOOGLE_CLOUD_PROJECT": "fake-project",
            "VECTOR_INDEX_ALLOW_RECREATE": "1",
        }.items():
            os.environ[k] = v
        os.environ.pop("NEO4J_DATABASE", None)
        assert ss._load_config() == "deployed"
        assert os.environ["NEO4J_URI"] == "neo4j+s://fake-host:7687"
        assert os.environ["GOOGLE_CLOUD_PROJECT"] == "fake-project"
        assert os.environ["LLM_BINDING_API_KEY"] == "fake-or-key"
        assert os.environ["NEO4J_DATABASE"] == "neo4j"
        assert os.environ["EMBEDDING_BINDING"] == "vertex"
        assert os.environ["VECTOR_INDEX_ALLOW_RECREATE"] == ""
        assert ss._resolve_vector_storage(os.environ) == "ScopedNeo4JVectorStorage"
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_adc_json_is_dropped_even_when_a_preset_path_wins(tmp_path) -> None:
    preset = tmp_path / "preset.json"
    preset.write_text("{}")
    r = _run_adc(
        {"GOOGLE_APPLICATION_CREDENTIALS": str(preset), "GOOGLE_APPLICATION_CREDENTIALS_JSON": SECRET}, tmp_path
    )
    assert r.returncode == 0, r.stderr
    assert "JSON_LEFT=\n" in r.stdout + "\n"
    assert not list(tmp_path.glob("adc.*"))
