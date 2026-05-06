# lightrag/ Test Debt Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

## Real-data integrity preamble (2026-05-05 audit)

This plan only modifies **unit-test infrastructure** (mocks for the neo4j
driver protocol and pytest fixtures for ContextVar isolation) and one
**module-load-time registration** (registering a custom Python class with
upstream LightRAG's storage compatibility map). None of these changes
introduce synthetic data, fabricated KG entities, or stubbed result
generation:

- `_FakeResult` mock in `test_bootstrap_scope.py` is a unit-test
  scaffold for verifying that `create_indexes` runs against a session
  without requiring a live Neo4j server. It does not appear in any
  ingestion or query path that produces KG content.
- `ContextVar` isolation fixtures (Issue #11 fix) reset state between
  tests; they don't generate any data.
- Storage-class registration (Issue #13) is a 2-line monkey-patch of an
  upstream framework dict; it doesn't write to the KG.
- Production ingestion paths (`ingest_hdi.py`, `ingest_unified.py`) and
  query paths (`scoped_server.py`, `kg_query`) are not modified by this
  plan. The KG content (Duke 15k nodes, SymMap 7.7k, HERB 1.5k,
  HDI-Safe-50, custom_kg) remains organic and externally sourced.

**Goal:** Bring the 10 failing tests in `shrine-diet-bioactivity/lightrag/` to green (issues #11, #12, #13).

**Architecture:** Three independent fixes — (1) pytest fixture state-leak isolation, (2) test mock conformance to neo4j Result protocol, (3) custom storage class registration with upstream LightRAG. Each fix is local and reversible; no LightRAG submodule pointer changes.

**Tech Stack:** Python 3.10, pytest 9.0.1, neo4j 5+ driver protocol, LightRAG framework (upstream submodule).

---

## Pre-flight (one-time, no commit)

- Worktree path: `/home/mo/projects/SyntropyHealth/apps/shrine-diet-bioactivity/.worktrees/lightrag-test-debt/`
- Branch: `fix/lightrag-test-debt` (already created off main @ 8f1ccf0)
- All work in subdir `shrine-diet-bioactivity/lightrag/` of the worktree
- Confirm baseline:
  - `cd <worktree>/shrine-diet-bioactivity && pytest lightrag/ -q` should reproduce: 8 failures in `test_scope_enforcement.py`, 1 in `test_bootstrap_scope.py`, 1 in `test_ingest_hdi.py`. Total: 10 failing / 147 passing.
  - `pytest lightrag/test_scope_enforcement.py -q` (in isolation) should be all green — confirms #11 is a state-leak.
- Constraint reminder: do NOT touch `eval/`, `agents/`, `scripts/`, `research-journal/primary/v1/`, or the LightRAG submodule pointer.

---

## Issue #12 — `_FakeResult` is not iterable (start here, lowest risk)

**Why first?** Smallest blast radius; confirms the test harness still works before larger changes.

### Root cause
- `lightrag/bootstrap_scope.py::create_indexes` (~line 119) drains `session.run()` via list comprehension or `for ... in`.
- `lightrag/test_bootstrap_scope.py::test_create_indexes_uses_if_not_exists` defines a local `_FakeResult` stub that lacks `__iter__`.

### TDD task list

- [ ] **T1.1: Verify root cause** (no commit)
  - Read `shrine-diet-bioactivity/lightrag/bootstrap_scope.py` and locate the iteration site (~line 119).
  - Read `shrine-diet-bioactivity/lightrag/test_bootstrap_scope.py` and locate `_FakeResult`.
  - Reproduce the failure: `pytest lightrag/test_bootstrap_scope.py::test_create_indexes_uses_if_not_exists -q`. Record exact traceback.

- [ ] **T1.2: RED — tighten the failing test**
  - File: `shrine-diet-bioactivity/lightrag/test_bootstrap_scope.py`
  - Add a docstring stating the contract: "session.run() returns an iterable of records; create_indexes consumes it eagerly so the driver actually executes the Cypher."

- [ ] **T1.3: GREEN — fix the `_FakeResult` mock**
  - Same file. Add `__iter__(self): return iter([])`.
  - If `bootstrap_scope.create_indexes` calls `.consume()`, also implement `consume()` returning `Mock()` with `.counters`.

- [ ] **T1.4: Verify**
  - `pytest lightrag/test_bootstrap_scope.py -q` → all green.
  - `pytest lightrag/ -q --deselect lightrag/test_scope_enforcement.py --deselect lightrag/test_ingest_hdi.py` → 1 fewer failure.

- [ ] **T1.5: Commit**
  - `fix(lightrag): make _FakeResult iterable to match neo4j Result contract`
  - Body: cite traceback, explain the contract.

---

## Issue #11 — `test_scope_enforcement.py` state leak (8 fails in suite, pass in isolation)

### Hypotheses ranked by likelihood

- **H1 (most likely): `ContextVar` not reset.** A previous test calls `scope.set(<value>)` (or imports a module that does on import). The var persists across test functions. When `test_scope_enforcement.py` runs, the var is already set.
- **H2: Singleton driver/storage mock.** A `_default_driver` or `LightRAG` instance cached at module level; a previous test patches it, the patch persists.
- **H3: Monkeypatch bleed via `os.environ`.** A previous test sets env vars without `monkeypatch.setenv` (which auto-undoes).

### Diagnostic steps (no commits)

- [ ] **T2.1: Confirm pass-in-isolation**
  - `pytest lightrag/test_scope_enforcement.py -q` → expect all green.

- [ ] **T2.2: Bisect the offender** with pair-runs:
  - `pytest lightrag/test_bootstrap_scope.py lightrag/test_scope_enforcement.py -q` → if fails, bootstrap_scope is leaker.
  - `pytest lightrag/test_ingest_hdi.py lightrag/test_scope_enforcement.py -q` → if fails, ingest_hdi is leaker.
  - If both fail, check `lightrag/conftest.py` for shared fixtures.

- [ ] **T2.3: Pinpoint the leaked symbol**
  - Read `lightrag/scope.py` and `lightrag/scope_context.py` to identify ContextVar names.
  - Grep each suspected leaker for `ContextVar`, `.set(`, `os.environ[`, `STORAGE_IMPLEMENTATIONS`, `_default_*`, module-level `LightRAG(`.
  - Add temporary `print(<contextvar>.get())` at start/end of each test in the suspect file to find the mutation point.

### TDD task list

- [ ] **T2.4: RED — write a state-leak repro test**
  - File: `shrine-diet-bioactivity/lightrag/test_scope_isolation.py` (new)
  - Test imports the suspected leaker module, invokes a representative function from it, then asserts `scope.<context_var>.get()` raises `LookupError` (or returns its default sentinel).

- [ ] **T2.5: GREEN — fix variant A (preferred): reset at source**
  - File(s): whichever leaker test/module bisect identifies.
  - Wrap `ContextVar.set()` calls in tests with `Token`/`reset` pattern, OR move the `set()` into a fixture with teardown:
    ```python
    @pytest.fixture
    def scoped_var():
        token = scope.context_var.set("test-scope")
        yield
        scope.context_var.reset(token)
    ```

- [ ] **T2.6: GREEN — fix variant B (fallback if multiple leakers)**
  - File: `shrine-diet-bioactivity/lightrag/conftest.py` (already exists per directory listing)
  - Add session-scoped autouse fixture that snapshots and restores all `ContextVar`s in `lightrag.scope` plus environ keys with prefixes `LIGHTRAG_`, `NEO4J_`, `OPENAI_`, `OLLAMA_`.

- [ ] **T2.7: Verify**
  - `pytest lightrag/ -q` → 8 + 1 fewer failures (only #13 remaining).
  - If `pytest-randomly` available: `pytest lightrag/ -q --count=2 --random-order` to confirm no order-dependence.

- [ ] **T2.8: Commit**
  - `fix(lightrag): reset scope.ContextVar across tests to stop suite-order leak`
  - Body: name offending test/module, cite line, explain Token/reset vs autouse choice.

- [ ] **T2.9 (Optional): Commit autouse fixture if variant B was needed**
  - `test(lightrag): add autouse fixture isolating scope ContextVars + scoped env`

---

## Issue #13 — `ScopedNeo4JVectorStorage` not in upstream `STORAGE_IMPLEMENTATIONS["VECTOR_STORAGE"]`

### Root cause
- LightRAG's `lightrag/kg/__init__.py` defines a `STORAGE_IMPLEMENTATIONS` dict mapping role → list of allowed class names.
- The custom `ScopedNeo4JVectorStorage` subclass isn't whitelisted; `verify_storage_implementation` raises `ValueError`.

### Decision: registration vs xfail
- **Preferred: register at import time** — non-invasive monkeypatch, no upstream PR needed.
- **Fallback: skip with `xfail(strict=True)`** — only if import-time patch is brittle.

### TDD task list

- [ ] **T3.1: Verify the registry surface**
  - Read upstream `lightrag/lightrag/kg/__init__.py` (the LightRAG submodule) to confirm dict name, key, and value type (list vs dict-of-list).
  - Find our subclass file (likely `shrine-diet-bioactivity/lightrag/scoped_storage.py` or in `lightrag_init.py`); confirm class name and parent.

- [ ] **T3.2: RED — failing test already in place**
  - `lightrag/test_ingest_hdi.py::test_hdi_edges_land_in_aura` is a valid RED.
  - Optional: add `lightrag/test_scoped_storage.py` (new) asserting `"ScopedNeo4JVectorStorage" in STORAGE_IMPLEMENTATIONS["VECTOR_STORAGE"]`.

- [ ] **T3.3: GREEN — register at import time (preferred)**
  - File: wherever `ScopedNeo4JVectorStorage` is defined.
  - At module bottom:
    ```python
    from lightrag.kg import STORAGE_IMPLEMENTATIONS
    _vec = STORAGE_IMPLEMENTATIONS["VECTOR_STORAGE"]
    if "ScopedNeo4JVectorStorage" not in _vec["implementations"]:
        _vec["implementations"].append("ScopedNeo4JVectorStorage")
    ```
  - Wrap in `try/except (ImportError, KeyError, AttributeError)` to fail safe if upstream dict shape changes.

- [ ] **T3.4: GREEN alt — xfail (fallback)**
  - File: `lightrag/test_ingest_hdi.py`
  - Add `@pytest.mark.xfail(strict=True, reason="awaiting upstream LightRAG storage-registration hook; tracked in #13")` to `test_hdi_edges_land_in_aura`.

- [ ] **T3.5: Verify**
  - `pytest lightrag/test_ingest_hdi.py -q` → green.
  - `pytest lightrag/ -q` → 0 failures, 147+ passing.

- [ ] **T3.6: Commit**
  - If registered: `fix(lightrag): register ScopedNeo4JVectorStorage in upstream STORAGE_IMPLEMENTATIONS`
  - If xfail: `test(lightrag): xfail test_hdi_edges_land_in_aura pending upstream register hook`

---

## Final verification (no commit)

- `pytest lightrag/ -q` → 0 failures.
- `pytest lightrag/ -q -p no:randomly && pytest lightrag/ -q --randomly-seed=12345` → both green; confirms order-independence.
- `git diff main -- shrine-diet-bioactivity/lightrag/` → confirm no edits outside `lightrag/`.
- `git submodule status` → confirm submodule pointer unchanged.

---

## Risks & Mitigations

- **Risk:** ContextVar reset in autouse fixture interferes with async tests using `asyncio.run` inside fixtures.
  - **Mitigation:** Prefer per-fixture `Token`/`reset` (variant A) over autouse (variant B); only escalate if multiple modules leak.
- **Risk:** Registry-patch (#13) breaks if upstream renames `STORAGE_IMPLEMENTATIONS` in a submodule bump.
  - **Mitigation:** Wrap patch in `try/except` and emit warning; the unit test from T3.2 catches silent drops.
- **Risk:** Bisect (#11) misidentifies leaker because the leak is from `conftest.py` collection.
  - **Mitigation:** Include `conftest.py` in the grep for `ContextVar` and `os.environ`.

---

## Success Criteria

- [ ] `pytest lightrag/ -q` shows 0 failures, ≥147 passing
- [ ] `pytest lightrag/test_scope_enforcement.py -q` and full-suite both pass (no order dependence)
- [ ] `_FakeResult` mock is iterable and documents the neo4j Result contract surface
- [ ] `ScopedNeo4JVectorStorage` either registered or explicitly xfail with tracking note
- [ ] No diff in `eval/`, `agents/`, `scripts/`, `research-journal/primary/v1/`, or LightRAG submodule pointer
- [ ] 3–4 commits, each green-on-its-own (`pytest lightrag/ -q` after each)
- [ ] GitHub issues #11, #12, #13 closed with commit references

---

## Execution handoff

After all tasks complete:
- `git push -u origin fix/lightrag-test-debt`
- Open PR titled "fix(lightrag): close out test debt #11, #12, #13"
- PR body lists each issue with the commit that fixes it
- Coordinate with parallel KG-engineering session for review
