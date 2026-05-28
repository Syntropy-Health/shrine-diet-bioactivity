"""Unit tests for the KG_VECTOR_BACKEND switch + ZILLIZ_*→MILVUS_* shim.

The shim lives in scoped_server.py (helper: ``_apply_zilliz_env_shim``).
It maps the Infisical-stored Zilliz creds onto the env-var names LightRAG's
``MilvusVectorDBStorage`` actually reads. Locking this so a future rename
of either side doesn't silently break ingestion.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoped_server import (  # noqa: E402
    _apply_zilliz_env_shim,
    _resolve_vector_storage,
)


pytestmark = [pytest.mark.unit]


# ─── env shim ─────────────────────────────────────────────────────────────


class TestZillizEnvShim:
    def test_maps_token_when_milvus_unset(self):
        env = {
            "ZILLIZ_URI": "https://x.zilliz.cloud",
            "ZILLIZ_TOKEN": "tok-abc",
            "ZILLIZ_DB_USER": "u",
            "ZILLIZ_DB_PASSWORD": "p",
        }
        _apply_zilliz_env_shim(env)
        assert env["MILVUS_URI"] == "https://x.zilliz.cloud"
        assert env["MILVUS_TOKEN"] == "tok-abc"
        assert env["MILVUS_USER"] == "u"
        assert env["MILVUS_PASSWORD"] == "p"

    def test_preserves_existing_milvus_values(self):
        """Operator override wins: if both ZILLIZ_* and MILVUS_* are set, the
        MILVUS_* value takes precedence (it's the more specific name)."""
        env = {
            "MILVUS_URI": "https://override.zilliz.cloud",
            "ZILLIZ_URI": "https://from-infisical.zilliz.cloud",
        }
        _apply_zilliz_env_shim(env)
        assert env["MILVUS_URI"] == "https://override.zilliz.cloud"

    def test_no_zilliz_no_change(self):
        env = {"OPENROUTER_API_KEY": "x"}
        before = dict(env)
        _apply_zilliz_env_shim(env)
        assert env == before

    def test_partial_secrets_partial_shim(self):
        """Only the secrets actually present are forwarded — no empty
        MILVUS_PASSWORD when ZILLIZ_DB_PASSWORD wasn't set."""
        env = {"ZILLIZ_URI": "u", "ZILLIZ_TOKEN": "t"}
        _apply_zilliz_env_shim(env)
        assert env.get("MILVUS_URI") == "u"
        assert env.get("MILVUS_TOKEN") == "t"
        assert "MILVUS_USER" not in env
        assert "MILVUS_PASSWORD" not in env


# ─── KG_VECTOR_BACKEND selection ──────────────────────────────────────────


class TestVectorStorageSelection:
    def test_default_is_nano(self):
        """Backwards-compat: an unset env keeps the existing NanoVectorDB
        behaviour so PR1+PR2 land without changing the live gateway."""
        assert _resolve_vector_storage({}) == "NanoVectorDBStorage"

    def test_explicit_nano(self):
        assert (
            _resolve_vector_storage({"KG_VECTOR_BACKEND": "nano"})
            == "NanoVectorDBStorage"
        )

    def test_milvus_switch(self):
        assert (
            _resolve_vector_storage({"KG_VECTOR_BACKEND": "milvus"})
            == "MilvusVectorDBStorage"
        )

    def test_case_insensitive(self):
        assert (
            _resolve_vector_storage({"KG_VECTOR_BACKEND": "Milvus"})
            == "MilvusVectorDBStorage"
        )

    def test_invalid_backend_raises(self):
        with pytest.raises(ValueError, match="KG_VECTOR_BACKEND"):
            _resolve_vector_storage({"KG_VECTOR_BACKEND": "redis"})
