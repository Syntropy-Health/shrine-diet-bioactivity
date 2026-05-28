"""Smoke + format-decoder tests for migrate_nano_to_milvus.py.

The full migration is a network operation against Zilliz that we don't
exercise in unit tests. These tests cover the pure-logic surface:

* CLI parses --help and --dry-run cleanly.
* ``_decode_nano`` correctly parses the LightRAG vdb_*.json shape and
  returns matched ``(dim, data, matrix)`` triples.
* Missing workspace dir exits 2 (not 0).
"""
from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parent.parent / "migrate_nano_to_milvus.py"
)


pytestmark = [pytest.mark.unit]


# ─── CLI smoke ────────────────────────────────────────────────────────────


def test_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    out = (proc.stdout + proc.stderr).lower()
    assert "migrate" in out
    assert "--working-dir" in out
    assert "--dry-run" in out


def test_missing_working_dir_exits_2(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--working-dir",
            str(tmp_path / "absent"),
            "--workspace",
            "ws",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2
    assert "not found" in (proc.stdout + proc.stderr).lower()


# ─── _decode_nano ─────────────────────────────────────────────────────────


def _build_fixture(tmp_path: Path, dim: int = 4, n: int = 3) -> Path:
    """Write a minimal vdb_*.json mirroring the LightRAG shape."""
    floats = [float((i * dim + j) % 7) for i in range(n) for j in range(dim)]
    blob = struct.pack(f"<{len(floats)}f", *floats)
    payload = {
        "embedding_dim": dim,
        "data": [
            {
                "__id__": f"ent-{i}",
                "__created_at__": 1779676637 + i,
                "entity_name": f"E{i}",
                "content": f"content {i}",
                "source_id": f"duke:{i}",
                "file_path": "clinical_anchors",
            }
            for i in range(n)
        ],
        "matrix": base64.b64encode(blob).decode("ascii"),
    }
    path = tmp_path / "vdb_entities.json"
    path.write_text(json.dumps(payload))
    return path


def test_decode_nano_reads_shape(tmp_path):
    # Import via subprocess-free runtime path so we exercise the actual module.
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        from migrate_nano_to_milvus import _decode_nano  # type: ignore

        path = _build_fixture(tmp_path, dim=4, n=3)
        dim, data, matrix = _decode_nano(path)
        assert dim == 4
        assert len(data) == 3
        assert len(matrix) == 3
        assert len(matrix[0]) == 4
        assert data[0]["__id__"] == "ent-0"
    finally:
        sys.path.remove(str(SCRIPT.parent))


def test_decode_nano_handles_empty_file(tmp_path):
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        from migrate_nano_to_milvus import _decode_nano  # type: ignore

        empty_path = tmp_path / "vdb_entities.json"
        empty_path.write_text(json.dumps({"embedding_dim": 0, "data": [], "matrix": ""}))
        dim, data, matrix = _decode_nano(empty_path)
        assert dim == 0
        assert data == []
        assert matrix == []
    finally:
        sys.path.remove(str(SCRIPT.parent))
