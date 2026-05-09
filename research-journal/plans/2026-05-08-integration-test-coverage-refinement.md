# Plan refinement: post-lightrag-fix audit + 7 sharpening questions

**Status:** Draft — pending user approval
**Date:** 2026-05-08
**Refines:** `research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md` (commit `b21801a` on main)
**Trigger:** lightrag test-debt fixes (#11, #12, #13) landed on `fix/lightrag-tests` (commits `caca026..720635a`); audit baseline shifted

---

## Updated baseline (post-lightrag-fix)

| Lane | Files | Tests | Real-integration | Mocked/unit | Delta vs. plan |
|---|---|---|---|---|---|
| eval/ | 14 | 72 | ~5 | ~67 | unchanged |
| agents/ | 13 | 94 | ~2 | ~92 | unchanged |
| lightrag/ | 16 | 101 | ~8 + 19 (scoped_server, blocked) | ~74 | +15 tests, +19 *claimable* once env-gated |
| mcp/unit | 4 | 64 | 0 | 64 | unchanged |
| mcp/e2e | 1 | 5 | 5 | 0 | unchanged |
| scripts/ | 1 | 6 | 0 | 6 | unchanged |
| **Total** | **49** | **~342** | **~20 today** | **~303** | denominator grew by 15 |

Naive ratio: 20 / 342 = **5.8%**. With scoped_server env-gating folded in: 39 / 342 = **11.4%**.

---

## 7 sharpening questions answered

### 1. Fold scoped_server env-gating into Phase 1?

**Answer:** Yes — fold as sub-task **1c**.

19 tests already exist with integration shape (FastAPI TestClient + driver-shaped client). Cost is small: a `lightrag/conftest.py` fixture detecting missing `NEO4J_URI` and `pytest.skip(allow_module_level=True)` on the scoped_server test files, plus a `LIGHTRAG_RUN_INTEGRATION=true` opt-in.

**Plan impact:** Phase 1 effort grows 0.5 dev-day (1.0 → 1.5). Ratio numerator gains +19 nightly. `@pytest.mark.integration` + `@pytest.mark.aura` applied at file level.

### 2. Recategorization — sharper count

**Answer:** Plan's "80-100 reclassifiable" is biased high. After auditing conftest topology:

- `eval/conftest.py` is sys.path plumbing — 50 of 72 are pure unit; ~15 are file-IO integration.
- `agents/conftest.py` injects lightrag onto path — 85 of 94 pure unit; ~9 wiring integration.
- `lightrag/conftest.py` registers `unit`/`integration` markers — 60 of 101 unit; ~22 integration-shaped; ~19 scoped_server.
- `mcp/tests/unit/` no conftest — all 64 httpx-mocked, genuinely unit.

**Tighter estimate:** **60-70 reclassifiable**, not 80-100. Adjusted ratio after Phase 1+2: (39 + 12 + 60) / 342 = **32%**. Plan's claimed "47% with 5-7 extra Phase 5 tests" is optimistic; **realistic is 35-40%**, requiring 15-20 additional tests to hit 50%.

**Plan impact:** Phase 5 grows by ~15 tests OR threshold drops to 40% interim with 50% target by Q3.

### 3. Integration tests the plan missed

**Answer:** Four genuine gaps:

- **Cost-tracker correctness (per-role trace)** — paper §A.2 cites per-role token counts. New `eval/tests/integration/test_cost_tracker_roles.py` (Phase 3, +1 test).
- **Provenance / cite-key correctness (§A.6)** — `mcp/tests/e2e/test_source_id_prefixes.py`: each Layer-B tool's `entity_id` matches `^(cmaup|duke|herb2|symmap|hdi-safe-50):` (Phase 2, parametrized, +1 test).
- **Pre-fetched bundle structure (§3.1)** — `eval/tests/integration/test_kg_bundle_contract.py`: `diet_os.run()` returns `KGResult[]` with typed `entity_id`/`source_id`/`confidence` (Phase 3, +1 test).
- **Ablation re-render byte-diff** — `scripts/render_ablation_test.py` paper-grade output (Phase 4, +1 test).

**Plan impact:** +4 tests, +0.5 dev-day across Phases 3 and 4.

### 4. CI cost realism

**Answer:** Plan's "nightly ~15 min" is undercounted.

- Phase 3: 3 scenarios × 8-12 LLM calls × 20 RPM Nemotron = 12-18 min LLM + 30s/scenario KG = 15-25 min.
- Phase 2: 12 × 2-5s = 30-60s.
- Phase 5: 7 × 1-3s = 10-20s.
- New tests Q3: +2 min.
- Phase 4: ~30s.

**Realistic nightly:** 18-30 min on cassette replay; 25-45 min on weekly re-record.

**Recommendation:** Split into **fast-nightly** (Phases 2+4+5 ≈ 3 min, every night) and **slow-nightly** (Phase 3 + cost-tracker ≈ 25 min, Mon/Wed/Fri). Weekly re-record on Sunday.

**Plan impact:** Update Phase 5 CI section; document two cron schedules.

### 5. vcrpy alternative

**Answer:** Cassettes are a soft form of mocking. **Recommend hybrid:**

- Real Nemotron weekly (Sunday); cassette re-record.
- Mon-Sat replay-only.
- Tag replays `@pytest.mark.live_llm_replay` (separate from `live_llm`); count toward integration but report sub-ratio "real-call freshness ≤ 7 days".
- Quarterly: tier-1 paid model run (Claude/GPT-4) for cross-validation; budget cap $25/quarter.

**Plan impact:** Risk-table row updated; new `live_llm_replay` marker + freshness gate in `scripts/test_coverage_ratio.py`.

### 6. Test-ordering safety in other lanes

**Answer:** **Real risk.** The lightrag autouse event-loop fixture is local to `lightrag/`. Audit:

- `agents/tests/`: AG2 sync-by-default, but `agents/llm_workers/` factory tests use `asyncio.run()` — same Python 3.10 closed-loop hazard.
- `eval/tests/test_smoke.py`: async LLM client; safe today only because it's the sole async test in lane.
- `mcp/tests/`: httpx-sync in unit; e2e uses `requests` — no risk.

**Recommendation:** Lift `_reset_event_loop` to `tests/_shared/asyncio_fixture.py`, import into each lane's conftest. Phase 1 sub-task **1d**, +0.25 dev-day.

**Plan impact:** Pre-empts a category of flakes that would surface as Phase 3 lands real `diet_os.run()` integration tests.

### 7. Pre-arXiv blocker dependency (Issues #28, #29 → Sep 8)

**Answer:** **Defer Phase 3-5 to post-arXiv.**

- Phase 1+2: safe pre-arXiv. Marker tagging + gateway smoke = read-only against existing infra.
- Phase 3: vcrpy + scenario re-runs could destabilize the very `summary.md` being byte-diffed. **Lock paper artifacts before Phase 3.**
- Phase 4: re-render byte-diff is paradoxically risky pre-arXiv — could surface non-determinism in the existing render that delays paper.

**Recommendation timeline:**
- **Pre-Sep-8**: Phase 1 (1.5d) + Phase 2 (1.5d) + Q3 source-id-prefix test (0.25d). **Total 3.25 dev-days.**
- **Post-Sep-8** / paper-1 v1 cutover: Phase 3 + 4 + 5 + remaining Q3 additions.

**Plan impact:** Insert "Phasing relative to Issue #28" subsection in existing plan header.

---

## Proposed plan changes (specific edits)

**§ Out of Scope** — change first bullet:
> Was: "lightrag test-debt (issues #11/#12/#13): 10 known failures … Tracked separately."
> Now: "lightrag test-debt issues #11/#12/#13 are merged on `fix/lightrag-tests` (commits `caca026..720635a`); 0 new failures, +15 unit tests. **Scoped_server env-gating (19 tests) folded into Phase 1 sub-task 1c.**"

**§ Phase 1** — append:
> "1c. Env-gate `lightrag/test_scoped_server_*.py`: file-level `pytest.skip` if `NEO4J_URI` unset; mark `integration + aura`. **+19 nightly tests.**
> 1d. Lift autouse `_reset_event_loop` fixture to shared module imported by `agents/conftest.py` and `eval/conftest.py`. Pre-empts asyncio-state ordering flakes."

**§ Phase 4** — add bullet:
> "`eval/tests/integration/test_ablation_rerender.py`: byte-diff `scripts/render_ablation_test.py` output against committed paper-grade ablation table."

**§ Phase 5** — replace ratio threshold:
> "Threshold: 50% (final). **Interim threshold 40% if Phase 5 ships pre-Sep-8** (pre-arXiv); promote to 50% once 15-20 reclassification PRs land in Q3."

**§ Risks table** — add row:
> "vcrpy cassette staleness inflates ratio | Hybrid: weekly re-record + quarterly tier-1 cross-validation; new `live_llm_replay` marker; coverage script reports cassette-freshness sub-metric."

**§ Estimated Effort** — replace table:

| Phase | Effort | Calendar | Pre/Post arXiv |
|---|---|---|---|
| Phase 1 (incl. 1c, 1d) | 1.75 dev-days | Days 1-2 | Pre |
| Phase 2 (12 gateway) | 1.5 dev-days | Days 3-4 | Pre |
| Q3 source-id-prefix test | 0.25 dev-day | Day 4 | Pre |
| **Pre-arXiv subtotal** | **3.5 dev-days** | | |
| Phase 3 (3 e2e + cost-tracker + bundle contract) | 2.5 dev-days | Days 5-7 | Post |
| Phase 4 (4 reproducibility) | 1.25 dev-days | Day 8 | Post |
| Phase 5 (7 probes + 15-20 reclassification) | 2.5 dev-days | Days 9-11 | Post |
| Buffer | 1.0 dev-day | Day 12 | Post |
| **Total** | **~10.75 dev-days** | **~3 calendar weeks** | |

---

## Net-new tasks not in current plan inventory

26. `test_cost_tracker_per_role_trace` — Phase 3, `integration + live_llm_replay`
27. `test_layer_b_source_id_prefixes` — Phase 2, parametrized over 5 tools, `e2e`
28. `test_kg_bundle_contract_typed_fields` — Phase 3, `integration + live_llm_replay`
29. `test_ablation_rerender_byte_diff` — Phase 4, `integration`
30. `test_live_llm_cassette_freshness` — Phase 5, meta-test asserting newest cassette ≤ 7 days

---

## Updated estimate

**10.75 dev-days** (~3 calendar weeks). Pre-arXiv slice is **3.5 days** and self-contained. Final ratio target: **40% interim** (post-Phase-5 pre-arXiv) → **50% Q3** with reclassification batch.

---

## Decisions needed from user

1. Approve **scoped_server env-gating** as Phase 1 sub-task 1c?
2. Approve **autouse-fixture lift** as Phase 1 sub-task 1d?
3. Approve **5 net-new tasks** (#26-#30)?
4. Approve **40% interim threshold** with 50% Q3 promotion?
5. Approve **deferring Phase 3-5 until post-arXiv submission** (Sep 8)?
6. Approve **vcrpy hybrid replay strategy** (Sunday re-record + quarterly tier-1)?
