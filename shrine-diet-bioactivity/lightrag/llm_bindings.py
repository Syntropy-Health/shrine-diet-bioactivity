"""Answer-synthesis LLM bindings for the scoped server (#121, CTO #14273).

``LLM_BINDING`` selects how /query turns retrieved context into an answer:

  gemini   Gemini on Vertex AI via google-genai, using the gateway's existing service
           account [PRINCIPAL-RULED 2026-10-12]. ``LLM_VERTEX_LOCATION`` is
           separate from ``GOOGLE_CLOUD_LOCATION`` (the embedder's): the Gemini 3.x
           models are served from ``global`` only (MEASURED 2026-10-12: 404 in
           us-central1), and the embedder must not move with them. That is also why
           LightRAG's bundled ``lightrag.llm.gemini`` is not used — it reads
           ``GOOGLE_CLOUD_LOCATION`` for every client.
  none     No synthesis. /query returns retrieved context + references marked
           ``answer_mode: retrieval_only`` — visibly not an answer.
  openai   OpenAI-compatible endpoint (OpenRouter / local); built in scoped_server.
  ollama   Local pipeline development; built in scoped_server.

Every binding is wrapped by :func:`tracked`, which turns an empty answer into an
error. /query decides each request from its OWN result and, on failure, names the
reason with a direct probe — there is deliberately no shared "last error" (a
process-global one let one request's failure turn a neighbour's good answer into a
502; review of #121).
"""
from __future__ import annotations

import functools
import os
from collections.abc import Awaitable, Callable
from typing import Any

LLM_BINDINGS = frozenset({"openai", "ollama", "gemini", "none"})

LlmFunc = Callable[..., Awaitable[Any]]


class EmptyCompletionError(RuntimeError):
    """The LLM call returned without error but with no text."""


class LlmDisabledError(RuntimeError):
    """LLM_BINDING=none: something asked for a completion."""


def tracked(func: LlmFunc) -> LlmFunc:
    """Wrap an llm_model_func so an empty ANSWER is an error, not a blank 200.

    Structured calls (``response_format`` set — LightRAG's keyword extraction) pass
    through untouched: LightRAG tolerates empty keyword output by falling back to
    the query text, and failing it here would turn that recovery into a 502.
    """

    @functools.wraps(func)
    async def _call(*args: Any, **kwargs: Any) -> Any:
        out = await func(*args, **kwargs)
        if kwargs.get("response_format") is None and (out is None or (isinstance(out, str) and not out.strip())):
            raise EmptyCompletionError("LLM returned an empty completion")
        return out

    return _call


def resolve_binding(env: dict[str, str] | Any = None) -> str:
    env = os.environ if env is None else env
    binding = (env.get("LLM_BINDING") or "openai").strip().lower()
    if binding not in LLM_BINDINGS:
        raise ValueError(f"LLM_BINDING must be one of {sorted(LLM_BINDINGS)}, got {binding!r}")
    return binding


def gemini_problem(env: dict[str, str] | Any = None) -> str | None:
    """Why the gemini binding cannot run here, or None. Names only, never values."""
    env = os.environ if env is None else env
    missing = [k for k in ("LLM_MODEL", "GOOGLE_CLOUD_PROJECT", "LLM_VERTEX_LOCATION") if not env.get(k)]
    if missing:
        # No defaults: each names a real external resource (root CLAUDE.md).
        return f"gemini LLM binding needs {', '.join(missing)} (no defaults are assumed)"
    # Same precondition as the Vertex embedder (scoped_server._embedder_problem): a
    # missing service account is a named reason at boot, not an auth error at query.
    creds = env.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds or not os.path.isfile(creds) or not os.access(creds, os.R_OK):
        return "service-account credentials not found (GOOGLE_APPLICATION_CREDENTIALS unset or unreadable)"
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return "google-genai is not installed"
    return None


def _contents(prompt: str, history: list[dict[str, Any]] | None) -> list[Any]:
    from google.genai import types

    out = []
    for m in history or []:
        role = "model" if m.get("role") == "assistant" else "user"
        out.append(types.Content(role=role, parts=[types.Part(text=str(m.get("content", "")))]))
    out.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
    return out


def make_gemini_llm(env: dict[str, str] | Any = None, client: Any = None) -> LlmFunc:
    """Async llm_model_func over Vertex Gemini. ``client`` is injectable for tests."""
    env = os.environ if env is None else env
    problem = gemini_problem(env)
    if problem:
        raise RuntimeError(problem)
    model = env["LLM_MODEL"]
    if client is None:
        from google import genai

        client = genai.Client(
            vertexai=True, project=env["GOOGLE_CLOUD_PROJECT"], location=env["LLM_VERTEX_LOCATION"]
        )

    async def _llm(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, Any]] | None = None,
        response_format: Any = None,
        **_ignored: Any,  # other OpenAI-shaped kwargs LightRAG passes (stream, enable_cot, ...)
    ) -> str:
        from google.genai import types

        cfg: dict[str, Any] = {}
        if system_prompt:
            cfg["system_instruction"] = system_prompt
        # Keyword extraction asks for {"type": "json_object"}; Gemini's equivalent.
        if isinstance(response_format, dict) and response_format.get("type") in ("json_object", "json_schema"):
            cfg["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**cfg) if cfg else None
        resp = await client.aio.models.generate_content(
            model=model, contents=_contents(prompt, history_messages), config=config
        )
        return resp.text or ""

    return _llm


def make_disabled_llm() -> LlmFunc:
    async def _llm(*_a: Any, **_k: Any) -> str:
        raise LlmDisabledError("LLM_BINDING=none: answer synthesis is disabled")

    return _llm
