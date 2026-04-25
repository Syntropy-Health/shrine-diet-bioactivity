"""Shared LLMConfig factory — pins model snapshot, seed, and temperature.
Reads pinned model from config/llm_models.yaml (loaded via config_loader).

Reproducibility contract (all three MUST be present per plan spec):
  - cache_seed=42  : AG2-level response cache deduplication seed
  - temperature=0  : deterministic sampling
  - extra_body={"seed": 42} : forwarded to OpenAI seed parameter at request time
    (lives inside the config entry, not at LLMConfig top level, because AG2 v0.12+
    routes entry-level fields through OpenAILLMConfigEntry.extra_body → OpenAI API)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_MODELS_YAML = Path(__file__).resolve().parents[1] / "config" / "llm_models.yaml"


def _load_models_yaml() -> dict[str, Any]:
    return yaml.safe_load(_MODELS_YAML.read_text())


def default_llm_config(response_format: type | None = None) -> dict[str, Any]:
    """Return an AG2-compatible LLMConfig dict with reproducibility pins.
    Response format is optional — if None, the agent emits free-form text.

    All three reproducibility pins are included:
      cache_seed=42, temperature=0, extra_body={"seed": 42}
    """
    cfg = _load_models_yaml()["default"]
    # extra_body must live inside the config entry so AG2 v0.12+ routes it
    # through OpenAILLMConfigEntry → openai_kwargs → OpenAI API seed param.
    entry: dict[str, Any] = {
        "model": cfg["model"],
        "api_type": cfg["provider"],
        "api_key": os.environ.get(cfg["api_key_env"], "test-key-placeholder"),
        "extra_body": {"seed": 42},
    }
    llm_cfg: dict[str, Any] = {
        "config_list": [entry],
        "cache_seed": 42,
        "temperature": 0,
    }
    if response_format is not None:
        llm_cfg["response_format"] = response_format
    return llm_cfg
