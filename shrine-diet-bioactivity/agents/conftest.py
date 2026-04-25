"""Pytest configuration for the agents package.

Adds the local lightrag/ directory to sys.path so that
`from config_loader import load_data_sources` resolves to
shrine-diet-bioactivity/lightrag/config_loader.py — not to the
pip-installed lightrag package (which does not have config_loader).
"""
from __future__ import annotations

import sys
from pathlib import Path

# shrine-diet-bioactivity/ is the parent of agents/
_SHRINE_ROOT = Path(__file__).resolve().parents[1]
_LIGHTRAG_DIR = _SHRINE_ROOT / "lightrag"

if str(_LIGHTRAG_DIR) not in sys.path:
    sys.path.insert(0, str(_LIGHTRAG_DIR))
