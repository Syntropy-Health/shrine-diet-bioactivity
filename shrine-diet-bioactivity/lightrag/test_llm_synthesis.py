"""#121 / CTO #14273 — answer synthesis must never fail silently.

#14271 MEASURED: the OpenRouter model 404'd, LightRAG's aquery() swallowed it and
returned None, and /query answered HTTP 200 ``{"response": "None"}``. These tests
pin the replacement contract:

  * a synthesis failure is a 502 ``llm_unavailable`` naming the provider's exception
    TYPE and what retrieval found — never a 200;
  * LLM_BINDING=none is an explicit retrieval-only mode, labelled as such;
  * /health reports the synthesis state (boot probe + every /query), which the
    deploy gate (scripts/ci/assert_semantic_health.sh) requires to be "ok";
  * Gemini on Vertex uses LLM_VERTEX_LOCATION, never the embedder's location.

Unit-level: no network, no Neo4j, no Vertex. The fake rag reproduces LightRAG
1.5.0's aquery_llm shape, including how it swallows an LLM exception.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit]

CHUNKS = [{"content": f"curcumin chunk {i}"} for i in range(20)]
ENTITIES = [
    {"entity_name": "Curcumin", "entity_type": "Compound", "description": "a curcuminoid"},
    {"entity_name": "NFKB1", "entity_type": "Target", "description": "a transcription factor"},
    {"entity_name": "Curcumin", "entity_type": "Compound", "description": "duplicate row"},
]
RELS = [{"src_id": "Curcumin", "tgt_id": "NFKB1", "description": "inhibits"}]


class ClientError(Exception):
    """Stands in for the provider SDK's 404 (google.genai.errors.ClientError /
    openai.NotFoundError): only the TYPE name may reach the wire."""


class _FakeRag:
    """aquery_llm / aquery_data with LightRAG 1.5.0's return shapes. aquery_llm
    calls the server's tracked llm and swallows an exception exactly like
    LightRAG.aquery_llm (status=failure, message embeds str(e), content None)."""

    def __init__(self, *, no_results: bool = False, retrieval_fails: bool = False) -> None:
        self.no_results = no_results
        self.retrieval_fails = retrieval_fails
        self.llm_calls = 0
        self.data_params: list[Any] = []

    def _data(self) -> dict[str, Any]:
        return {"entities": ENTITIES, "relationships": RELS, "chunks": CHUNKS}

    async def aquery_llm(self, query: str, param: Any = None) -> dict[str, Any]:
        import scoped_server as ss

        if self.no_results:
            return {
                "status": "failure",
                "message": "Query returned no results",
                "data": {},
                "metadata": {"failure_reason": "no_results", "mode": param.mode},
                "llm_response": {"content": "Sorry, I'm not able to provide an answer to that question.[no-context]"},
            }
        try:
            if self.retrieval_fails:
                raise ConnectionError("neo4j+s://secret-host:7687 unreachable")
            self.llm_calls += 1
            content = await ss._llm_func(query, system_prompt="answer from context")
        except Exception as e:  # LightRAG.aquery_llm's own handler
            return {
                "status": "failure",
                "message": f"Query failed: {e}",
                "data": {},
                "metadata": {},
                "llm_response": {"content": None, "response_iterator": None, "is_streaming": False},
            }
        return {"status": "success", "data": self._data(), "llm_response": {"content": content}}

    async def aquery_data(self, query: str, param: Any = None) -> dict[str, Any]:
        self.data_params.append(param)
        if self.retrieval_fails:
            raise ConnectionError("neo4j+s://secret-host:7687 unreachable")
        return {"status": "success", "data": self._data()}

    async def finalize_storages(self) -> None:
        return None


def _client(monkeypatch, tmp_path, *, llm=None, rag=None, binding="openai"):
    from fastapi.testclient import TestClient

    import llm_bindings
    import scoped_server as ss
    from audit_log import AuditLog

    rag = rag or _FakeRag()

    async def _fake_build():
        if llm is not None:
            ss._llm_func = llm_bindings.tracked(llm)
        return rag

    async def _fake_init_driver():
        ss._neo4j_driver = MagicMock(close=AsyncMock())

    async def _ping():
        return True

    monkeypatch.setenv("SHRINE_CONFIG", "no_such_profile_for_tests")
    monkeypatch.setenv("LLM_BINDING", binding)
    monkeypatch.setattr(ss, "_preflight_scope_check", lambda: None)
    monkeypatch.setattr(ss, "_build_scoped_rag", _fake_build)
    monkeypatch.setattr(ss, "_init_neo4j_driver", _fake_init_driver)
    monkeypatch.setattr(ss, "_ping_driver", _ping)
    monkeypatch.setattr(ss, "_SEMANTIC_DISABLED_REASON", None)
    monkeypatch.setattr(ss, "_LLM_CONFIG_PROBLEM", None)
    monkeypatch.setattr(ss, "_LLM_STATE", {"llm": "untested", "reason": None})
    monkeypatch.setattr(ss, "_audit", AuditLog(db_path=tmp_path / "audit.db"))
    return TestClient(ss.app), rag


async def _ok_llm(prompt, system_prompt=None, history_messages=None, **kw):
    return "Curcumin inhibits NFKB1."


async def _404_llm(prompt, system_prompt=None, history_messages=None, **kw):
    raise ClientError("404 NOT_FOUND. model unavailable for free; use slug nvidia/...")


Q = {"query": "curcumin targets", "mode": "mix", "scope_filter": ["shared"]}


# ─── red / green arms (CTO #14273 item 1) ──────────────────────────────────


def test_red_arm_llm_404_is_a_502_llm_unavailable_never_a_200_none(monkeypatch, tmp_path) -> None:
    client, rag = _client(monkeypatch, tmp_path, llm=_404_llm)
    with client:
        resp = client.post("/query", json=Q)
    assert resp.status_code == 502, resp.text
    body = resp.json()
    assert body["error"] == "llm_unavailable"
    assert body["reason"] == "ClientError"
    assert body["retrieval"] == {"chunks": 20, "mode": "naive"}
    assert "llm_unavailable: ClientError" in body["detail"]
    assert "None" not in resp.text
    # The provider's message (model slugs, URLs) never reaches the wire.
    assert "nvidia" not in resp.text and "NOT_FOUND" not in resp.text
    # Chunk count came from a naive (LLM-free) retrieval, not the failed graph mode.
    assert rag.data_params[-1].mode == "naive"


def test_green_arm_a_completion_is_a_200_synthesized_answer(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path, llm=_ok_llm)
    with client:
        resp = client.post("/query", json=Q)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response"] == "Curcumin inhibits NFKB1."
    assert body["answer_mode"] == "synthesized"
    assert body["references"] == ["Curcumin", "NFKB1"]  # deduplicated, retrieval order
    assert body["retrieval"] == {"entities": 3, "relationships": 1, "chunks": 20}
    assert body["scope_filter"] == ["shared"]


def test_an_empty_completion_is_a_502_not_an_empty_200(monkeypatch, tmp_path) -> None:
    async def _empty(*a, **k):
        return "   "

    client, _ = _client(monkeypatch, tmp_path, llm=_empty)
    with client:
        resp = client.post("/query", json=Q)
    assert resp.status_code == 502
    assert resp.json()["reason"] == "EmptyCompletionError"


def test_nothing_retrieved_is_a_labelled_200_without_an_llm_call(monkeypatch, tmp_path) -> None:
    rag = _FakeRag(no_results=True)
    client, _ = _client(monkeypatch, tmp_path, llm=_404_llm, rag=rag)
    with client:
        resp = client.post("/query", json=Q)
    assert resp.status_code == 200
    assert resp.json()["answer_mode"] == "no_context"
    assert resp.json()["references"] == []
    assert rag.llm_calls == 0


def test_a_failure_outside_the_llm_is_a_502_with_no_upstream_message(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path, llm=_ok_llm, rag=_FakeRag(retrieval_fails=True))
    with client:
        resp = client.post("/query", json=Q)
    assert resp.status_code == 502
    assert resp.json()["error"] == "query_failed"
    assert "secret-host" not in resp.text


def test_a_stale_llm_error_from_an_earlier_request_does_not_poison_a_success(monkeypatch, tmp_path) -> None:
    import llm_bindings

    client, _ = _client(monkeypatch, tmp_path, llm=_ok_llm)
    with client:
        llm_bindings._last_error = "ClientError"  # left by some previous failure
        resp = client.post("/query", json=Q)
    assert resp.status_code == 200
    assert resp.json()["answer_mode"] == "synthesized"


# ─── /health synthesis state (feeds the deploy gate) ────────────────────────


def test_health_reports_llm_ok_after_a_good_boot_probe(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path, llm=_ok_llm)
    with client:
        h = client.get("/health").json()
    assert h["llm"] == "ok" and h["llm_reason"] is None


def test_health_reports_llm_failing_with_the_type_when_the_probe_fails(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path, llm=_404_llm)
    with client:
        h = client.get("/health").json()
    assert h["llm"] == "failing"
    assert h["llm_reason"] == "ClientError"


def test_a_hung_probe_is_failing_not_a_hung_boot(monkeypatch, tmp_path) -> None:
    import scoped_server as ss

    async def _hang(*a, **k):
        await asyncio.sleep(5)

    monkeypatch.setattr(ss, "LLM_PROBE_TIMEOUT_SECONDS", 0.05)
    client, _ = _client(monkeypatch, tmp_path, llm=_hang)
    with client:
        h = client.get("/health").json()
    assert h["llm"] == "failing"
    assert h["llm_reason"] == "TimeoutError"


def test_query_outcomes_update_the_health_state(monkeypatch, tmp_path) -> None:
    state = {"fail": False}

    async def _flaky(*a, **k):
        if state["fail"]:
            raise ClientError("quota")
        return "fine"

    client, _ = _client(monkeypatch, tmp_path, llm=_flaky)
    with client:
        assert client.get("/health").json()["llm"] == "ok"
        state["fail"] = True
        assert client.post("/query", json=Q).status_code == 502
        h = client.get("/health").json()
        assert h["llm"] == "failing" and h["llm_reason"] == "ClientError"
        state["fail"] = False
        assert client.post("/query", json=Q).status_code == 200
        assert client.get("/health").json()["llm"] == "ok"


def test_a_boot_without_a_built_llm_is_untested(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path, llm=None)
    with client:
        assert client.get("/health").json()["llm"] == "untested"


# ─── retrieval-only mode (CTO #14273 item 2) ────────────────────────────────


def test_retrieval_only_returns_context_marked_as_not_an_answer(monkeypatch, tmp_path) -> None:
    rag = _FakeRag()
    client, _ = _client(monkeypatch, tmp_path, llm=None, rag=rag, binding="none")
    with client:
        resp = client.post("/query", json=Q)
        health = client.get("/health").json()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer_mode"] == "retrieval_only"
    assert body["response"].startswith("RETRIEVAL-ONLY: no answer was synthesized")
    assert "Curcumin (Compound)" in body["response"]
    assert body["references"] == ["Curcumin", "NFKB1"]
    assert body["retrieval"]["chunks"] == 20
    assert rag.llm_calls == 0
    # Keywords preset so graph modes never ask the (absent) LLM to extract them.
    p = rag.data_params[-1]
    assert p.mode == "mix" and p.hl_keywords == [Q["query"]] and p.ll_keywords == [Q["query"]]
    # Explicit fallback, not a synthesizing plane: the deploy gate stays RED.
    assert health["llm"] == "disabled"


def test_retrieval_only_failure_is_a_502(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path, rag=_FakeRag(retrieval_fails=True), binding="none")
    with client:
        resp = client.post("/query", json=Q)
    assert resp.status_code == 502
    assert "secret-host" not in resp.text


# ─── bindings ───────────────────────────────────────────────────────────────


def test_tracked_records_the_type_and_reraises() -> None:
    import llm_bindings

    llm_bindings.clear_last_error()
    with pytest.raises(ClientError):
        asyncio.run(llm_bindings.tracked(_404_llm)("q"))
    assert llm_bindings.last_error() == "ClientError"


@pytest.mark.parametrize("empty", [None, "", "  \n"])
def test_tracked_refuses_empty_completions(empty) -> None:
    import llm_bindings

    async def _f(*a, **k):
        return empty

    with pytest.raises(llm_bindings.EmptyCompletionError):
        asyncio.run(llm_bindings.tracked(_f)("q"))


def test_unknown_binding_is_refused() -> None:
    import llm_bindings

    with pytest.raises(ValueError, match="LLM_BINDING"):
        llm_bindings.resolve_binding({"LLM_BINDING": "gemeni"})
    assert llm_bindings.resolve_binding({}) == "openai"


def test_disabled_llm_raises_if_anything_asks_it() -> None:
    import llm_bindings

    with pytest.raises(llm_bindings.LlmDisabledError):
        asyncio.run(llm_bindings.make_disabled_llm()("q"))


GEMINI_ENV = {
    "LLM_MODEL": "gemini-3.5-flash-lite",
    "GOOGLE_CLOUD_PROJECT": "test-project",
    "LLM_VERTEX_LOCATION": "global",
    "GOOGLE_CLOUD_LOCATION": "us-central1",
}


@pytest.mark.parametrize("missing", ["LLM_MODEL", "GOOGLE_CLOUD_PROJECT", "LLM_VERTEX_LOCATION"])
def test_gemini_names_a_missing_setting_and_assumes_no_default(missing) -> None:
    import llm_bindings

    env = {k: v for k, v in GEMINI_ENV.items() if k != missing}
    problem = llm_bindings.gemini_problem(env)
    assert problem and missing in problem
    with pytest.raises(RuntimeError, match=missing):
        llm_bindings.make_gemini_llm(env)


def test_gemini_sends_model_prompt_history_and_system_prompt() -> None:
    import llm_bindings

    seen: dict[str, Any] = {}

    async def _gen(*, model, contents, config):
        seen.update(model=model, contents=contents, config=config)
        return MagicMock(text="answer")

    client = MagicMock()
    client.aio.models.generate_content = _gen
    llm = llm_bindings.make_gemini_llm(GEMINI_ENV, client=client)
    out = asyncio.run(
        llm(
            "question",
            system_prompt="use the context",
            history_messages=[{"role": "assistant", "content": "earlier"}],
            stream=False,
            enable_cot=True,
        )
    )
    assert out == "answer"
    assert seen["model"] == "gemini-3.5-flash-lite"
    assert [c.role for c in seen["contents"]] == ["model", "user"]
    assert seen["contents"][-1].parts[0].text == "question"
    assert seen["config"].system_instruction == "use the context"


def test_location_split_llm_uses_its_own_location_and_the_embedder_keeps_its_own(monkeypatch) -> None:
    """CTO #14291 condition 2: the trap is one location key for both. LightRAG's
    bundled gemini.py reads GOOGLE_CLOUD_LOCATION for every client; a 'cleanup'
    onto it would move the embedder off the region the Aura vectors were built in
    — or leave the LLM in a region where the 3.x models 404."""
    from google import genai

    import embedder_adapters as ea
    import llm_bindings

    clients: list[dict[str, Any]] = []

    class _Client:
        def __init__(self, **kw):
            clients.append(kw)

    monkeypatch.setattr(genai, "Client", _Client)
    for k, v in GEMINI_ENV.items():
        monkeypatch.setenv(k, v)
    llm_bindings.make_gemini_llm(dict(GEMINI_ENV))
    ea.make_embedder("vertex", model="gemini-embedding-001", dim=1024)
    llm_kw, embed_kw = clients
    assert llm_kw["location"] == "global" and llm_kw["vertexai"] is True
    assert embed_kw["location"] == "us-central1"
    assert llm_kw["project"] == embed_kw["project"] == "test-project"


def test_build_selects_gemini_and_wraps_it(monkeypatch, tmp_path) -> None:
    import lightrag

    import llm_bindings
    import scoped_server as ss

    built: list[dict[str, Any]] = []

    class _LR:
        def __init__(self, **kw):
            built.append(kw)

        async def initialize_storages(self):
            return None

    sentinel_calls: list[Any] = []

    async def _gem(*a, **k):
        sentinel_calls.append(a)
        return "ok"

    monkeypatch.setattr(lightrag, "LightRAG", _LR)
    monkeypatch.setattr(llm_bindings, "make_gemini_llm", lambda env: _gem)
    monkeypatch.setattr(llm_bindings, "gemini_problem", lambda env: None)
    monkeypatch.setattr(ss, "_SEMANTIC_DISABLED_REASON", None)
    monkeypatch.setenv("LLM_BINDING", "gemini")
    monkeypatch.setenv("KG_VECTOR_BACKEND", "nano")
    monkeypatch.setenv("WORKING_DIR", str(tmp_path))
    asyncio.run(ss._build_scoped_rag())
    llm = built[-1]["llm_model_func"]
    assert llm is ss._llm_func
    assert asyncio.run(llm("p")) == "ok" and sentinel_calls == [("p",)]
    assert built[-1]["llm_model_kwargs"] == {}


def test_build_with_a_misconfigured_gemini_boots_and_reports_the_reason(monkeypatch, tmp_path) -> None:
    import lightrag

    import scoped_server as ss

    class _LR:
        def __init__(self, **kw):
            pass

        async def initialize_storages(self):
            return None

    monkeypatch.setattr(lightrag, "LightRAG", _LR)
    monkeypatch.setattr(ss, "_SEMANTIC_DISABLED_REASON", None)
    monkeypatch.setattr(ss, "_LLM_STATE", {"llm": "untested", "reason": None})
    monkeypatch.setenv("LLM_BINDING", "gemini")
    monkeypatch.setenv("KG_VECTOR_BACKEND", "nano")
    monkeypatch.setenv("WORKING_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_VERTEX_LOCATION", raising=False)
    asyncio.run(ss._build_scoped_rag())  # no crash
    asyncio.run(ss._probe_llm())
    assert ss._LLM_STATE["llm"] == "failing"
    assert "LLM_VERTEX_LOCATION" in ss._LLM_STATE["reason"]


# ─── deployed profile pins ──────────────────────────────────────────────────


def _deployed() -> tuple[dict[str, str], str]:
    from pathlib import Path

    text = (Path(__file__).resolve().parent / "config_deployed.env").read_text()
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env, text


def test_deployed_profile_synthesizes_with_gemini_in_global() -> None:
    env, text = _deployed()
    assert env["LLM_BINDING"] == "gemini"
    assert env["LLM_MODEL"] == "gemini-3.5-flash-lite"
    assert env["LLM_VERTEX_LOCATION"] == "global"
    # The embedder's location comes from Railway; the profile must never set it.
    assert "GOOGLE_CLOUD_LOCATION" not in env
    # The withdrawn :free model must not come back.
    assert ":free" not in env.get("LLM_MODEL", "")


def test_deployed_profile_labels_the_price_and_retirement_evidence() -> None:
    # CTO #14291 condition 1: the price is aggregator-sourced -> INFERRED, next to
    # the model; the 2.5-flash retirement date is disputed -> both dates stated.
    _, text = _deployed()
    assert "INFERRED" in text and "$0.30" in text and "$2.50" in text
    assert "2026-10-20" in text and "2026-10-16" in text


def test_aquery_llm_raising_outright_is_a_502_with_no_message(monkeypatch, tmp_path) -> None:
    class _Raises(_FakeRag):
        async def aquery_llm(self, query, param=None):
            raise RuntimeError("bolt://secret-host:7687 refused")

    client, _ = _client(monkeypatch, tmp_path, llm=_ok_llm, rag=_Raises())
    with client:
        resp = client.post("/query", json=Q)
    assert resp.status_code == 502
    assert resp.json()["error"] == "query_failed"
    assert "secret-host" not in resp.text
