"""Structural tests for eval-* Make targets in the project Makefile.

These do NOT execute Make — they parse the Makefile text and assert ordering
properties of recipe lines. The bug they guard against is the env-var check
running BEFORE `.env` is sourced, which makes `make eval-run` fail even when
the key is correctly placed in `.env`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest  # noqa: F401  -- kept for skip in eval-embed-ingest test

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"


def _extract_recipe(target: str) -> str:
    """Return the recipe body for a single Make target.

    Recipe lines start with TAB; the recipe ends at the next blank line or
    the next non-tab-non-comment line. Lines inside a continuation (\\) are
    joined into the same logical line.
    """
    text = MAKEFILE.read_text()
    pattern = re.compile(rf"^{re.escape(target)}:.*?$", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        raise AssertionError(f"target {target!r} not found in Makefile")

    lines: list[str] = []
    started = False
    for line in text[m.end():].splitlines():
        if line.startswith("\t"):
            started = True
            lines.append(line)
            continue
        if not started:
            # blank lines between target line and recipe are allowed
            if line.strip() == "":
                continue
            break
        # ended (next target or blank-then-target)
        break
    return "\n".join(lines)


def test_eval_run_sources_env_before_openrouter_check() -> None:
    """`make eval-run` must source .env BEFORE checking OPENROUTER_API_KEY.

    Otherwise users who put the key in .env (the canonical place) still see
    the recipe exit with 'ERROR: OPENROUTER_API_KEY not set'. The fix is to
    have `set -a && . ./.env && set +a` (or equivalent) appear BEFORE the
    OPENROUTER_API_KEY presence check inside the recipe body.
    """
    recipe = _extract_recipe("eval-run")
    assert "OPENROUTER_API_KEY" in recipe, (
        "eval-run recipe lost its OPENROUTER_API_KEY guard — refusing to run "
        "without the key is a deliberate safety check; restore it."
    )
    assert ".env" in recipe, (
        "eval-run recipe must source .env so users don't have to "
        "set -a && . ./.env && set +a manually before invoking make."
    )

    # Find line indices of the env-source and the env-check.
    lines = recipe.splitlines()
    env_source_idx = next(
        (i for i, ln in enumerate(lines) if ". ./.env" in ln or "include .env" in ln),
        None,
    )
    check_idx = next(
        (i for i, ln in enumerate(lines)
         if "OPENROUTER_API_KEY" in ln and ("-z" in ln or "if [" in ln)),
        None,
    )

    assert env_source_idx is not None, (
        "eval-run recipe doesn't source .env. Found recipe:\n" + recipe
    )
    assert check_idx is not None, (
        "eval-run recipe doesn't check OPENROUTER_API_KEY. Found recipe:\n"
        + recipe
    )
    assert env_source_idx < check_idx, (
        f"eval-run sources .env at line {env_source_idx} but checks "
        f"OPENROUTER_API_KEY at line {check_idx} — the check fires before "
        f"the env is loaded, so users with .env populated still see ERROR.\n"
        f"Recipe:\n{recipe}"
    )


def test_eval_embed_ingest_sources_env_before_openrouter_check() -> None:
    """Same ordering constraint applies to eval-embed-ingest, which has the
    same bug pattern."""
    recipe = _extract_recipe("eval-embed-ingest")
    if "OPENROUTER_API_KEY" not in recipe:
        pytest.skip("eval-embed-ingest does not gate on OPENROUTER_API_KEY")

    lines = recipe.splitlines()
    env_source_idx = next(
        (i for i, ln in enumerate(lines) if ". ./.env" in ln or "include .env" in ln),
        None,
    )
    check_idx = next(
        (i for i, ln in enumerate(lines)
         if "OPENROUTER_API_KEY" in ln and ("-z" in ln or "if [" in ln)),
        None,
    )

    assert env_source_idx is not None, (
        "eval-embed-ingest must source .env. Found recipe:\n" + recipe
    )
    assert check_idx is not None
    assert env_source_idx < check_idx, (
        f"eval-embed-ingest sources .env at line {env_source_idx} but "
        f"checks OPENROUTER_API_KEY at line {check_idx}.\n"
        f"Recipe:\n{recipe}"
    )
