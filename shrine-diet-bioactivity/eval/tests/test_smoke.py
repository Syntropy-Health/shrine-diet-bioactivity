"""Smoke test — confirms OpenRouter LLM is reachable with the configured model.
Skipped without OPENROUTER_API_KEY."""
from __future__ import annotations

import os

import pytest


@pytest.mark.live_llm
@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
def test_openrouter_nemotron_reachable():
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    reply = client.chat.completions.create(
        model="nvidia/nemotron-3-nano-30b-a3b:free",
        messages=[{"role": "user", "content": "Reply with exactly the word OK."}],
        max_tokens=10,
        temperature=0,
    )
    assert reply.choices[0].message.content is not None
    assert len(reply.choices[0].message.content.strip()) > 0


@pytest.mark.unit
def test_eval_package_imports():
    """Structural check — eval/ must be a package."""
    import eval  # type: ignore[import-not-found]
    assert eval is not None
