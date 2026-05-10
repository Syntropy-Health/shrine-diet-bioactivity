"""Pytest configuration for the agents package.

Adds the local lightrag/ directory to sys.path so that
`from config_loader import load_data_sources` resolves to
shrine-diet-bioactivity/lightrag/config_loader.py — not to the
pip-installed lightrag package (which does not have config_loader).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Generator

import pytest

# shrine-diet-bioactivity/ is the parent of agents/
_SHRINE_ROOT = Path(__file__).resolve().parents[1]
_LIGHTRAG_DIR = _SHRINE_ROOT / "lightrag"

if str(_LIGHTRAG_DIR) not in sys.path:
    sys.path.insert(0, str(_LIGHTRAG_DIR))


# Synced with lightrag/conftest.py — keep in sync.
# Some downstream tests (run_case_study, retrieval) transitively call
# asyncio.run() which closes the loop it created. On Python 3.10 this leaves
# asyncio.get_event_loop() returning a closed loop for the next test, causing
# suite-order failures. This autouse fixture issues a fresh loop per test and
# tears it down regardless of outcome.
@pytest.fixture(autouse=True)
def _reset_event_loop() -> Generator[None, None, None]:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)
