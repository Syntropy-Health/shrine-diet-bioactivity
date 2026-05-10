"""Mirrors agents/conftest.py — adds project-local lightrag/ + agents/ to sys.path
so eval modules can `from agents.* import ...` and `from config_loader import ...`
without a project-level pyrightconfig or pip install."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Generator

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_SUBPATH = _HERE.parent  # shrine-diet-bioactivity/ (the inner project root)

# Put the project root first so `import eval` resolves to our package, not the builtin
if str(_REPO_SUBPATH) not in sys.path:
    sys.path.insert(0, str(_REPO_SUBPATH))

for sub in ("lightrag", "agents"):
    p = _REPO_SUBPATH / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# Synced with lightrag/conftest.py — keep in sync.
# Some downstream tests (eval/runner subprocess CLIs, agents/run_case_study)
# transitively call asyncio.run() which closes the loop it created. On Python
# 3.10 this leaves asyncio.get_event_loop() returning a closed loop for the
# next test, causing suite-order failures. This autouse fixture issues a fresh
# loop per test and tears it down regardless of outcome.
@pytest.fixture(autouse=True)
def _reset_event_loop() -> Generator[None, None, None]:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)
