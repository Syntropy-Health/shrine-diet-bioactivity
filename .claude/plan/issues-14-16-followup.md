# Multi-Plan: Issues #14, #15, #16 — Follow-up

**Source skill**: `/ccg:plan` (multi-model collaborative planning), substituted Codex/Gemini with Claude `architect` + `planner` subagents per user direction.

**Generated**: 2026-05-07.

**Trust rules per skill**: code/engineering mechanics follow the architect plan; prose strategy + related-work positioning follow the planner plan.

**Inputs synthesized**:
- Web research A: industry KG-MCP architecture + multi-tenant ContextVar isolation + LightRAG storage adapter + neo4j v5 Result protocol + PEP 661 fail-loud convention
- Web research B: ML4H 2026 Findings format (4-page body, unlimited appendix, no word limit), Yang et al. JMIR forward-citation graph, comparable systems (CAMP, KG4Diagnosis, NutriOrion, HealthGenie, MDAgents)
- Architect plan (eng lens, see agent output)
- Planner plan (writing lens, see agent output)
- Existing plan: `.worktrees/paper-1-camera-ready/research-journal/plans/2026-05-05-paper-1-camera-ready-plan.md`

---

## Sequence + worktree assignment

1. **Plan A → Issue #15** — bib-only, lowest blast radius. Done first. Worktree: `paper-1-camera-ready`.
2. **Plan B → Issue #16** — TDD code refactor of `_neutral_stub`, isolated from paper edits. Done second. Worktree: `lightrag-test-debt`. Merges to `main` so Plan C can reference its SHA in §9.2 / App.F.
3. **Plan C → Issue #14** — paper trim + move-to-appendix + 3 new related-work citations. Done last; depends on Plan A merged on the same worktree, Plan B merged on `main`. Worktree: `paper-1-camera-ready`.

---

## Plan A — Issue #15: yang2025 citation update

**Citation verified** (web research B): Yang E, Garcia T, Williams HG, Kumar B, Rame M, Rivera E, Ma Y, Amar J, Catalani C, Jia Y. "A Behavioral Science-Informed Agentic Workflow for Personalized Nutrition Coaching: Development and Validation Study." *JMIR Formative Research* 2025; Vol 9. DOI 10.2196/75421. URL: https://formative.jmir.org/2025/1/e75421.

**Strategy**: Option A — replace stub with verified `@article` entry; do NOT rename `eval/baselines/yang2025.py`; correct §2 + §5 prose to match the actual JMIR architecture (NOT "dietitian-pharmacist diet-drug interaction"; IS "two-agent barrier-identification + strategy-execution for behavioral nutrition coaching").

### Tasks

- [ ] **T15.1 — Replace yang2025 BibTeX stub**
  - File: `research-journal/primary/v1/references.bib` L20-32
  - Action: Replace stub block with `@article{yang2025, title={A Behavioral Science-Informed Agentic Workflow for Personalized Nutrition Coaching: Development and Validation Study}, author={Yang, Eric and Garcia, Tomas and Williams, Hannah G. and Kumar, Bhawesh and Rame, Martin and Rivera, Eileen and Ma, Yiran and Amar, Jonathan and Catalani, Caricia and Jia, Yugang}, journal={JMIR Formative Research}, volume={9}, year={2025}, doi={10.2196/75421}, url={https://formative.jmir.org/2025/1/e75421}, note={Published 2025-09-24}}`
  - Decision: cite the JMIR DOI (canonical published version), not the arXiv:2410.14041 preprint

- [ ] **T15.2 — Correct §2 Yang mislabel + add JMIR-Yang framing handle (writing-lens)**
  - File: `02-related-work.md`
  - Before: `Yang et al. [@yang2025] propose a 2-role dietitian-pharmacist setup for diet-drug interaction reasoning.`
  - After: `Yang et al. [@yang2025], the JMIR baseline of behavioral-science-informed agentic workflows, propose a two-agent design (barrier-identification + strategy-execution) for personalized-nutrition adherence coaching, which we re-implement as our third behavioral baseline.`
  - Word delta: **+8w**

- [ ] **T15.3 — Correct §5 baselines parenthetical (writing-lens)**
  - File: `05-experimental-setup.md`
  - Before: `\`yang2025\` (2-role dietitian-pharmacist) [@yang2025]`
  - After: `\`yang2025\` (two-agent barrier-identification + strategy-execution; JMIR Yang behavioral baseline) [@yang2025]`
  - Word delta: **+2w**

- [ ] **T15.4 — Verify rendering**
  - Command: `cd research-journal/primary/v1 && pandoc paper.md --bibliography references.bib --citeproc -o /tmp/paper-cite-check.html 2>&1 | tee /tmp/pandoc-warnings.txt`
  - Pass criterion: zero `[WARNING] Citeproc: citation yang2025 not found`. Bibliography renders the JMIR entry.

- [ ] **T15.5 — Commit + push**
  - `git add research-journal/primary/v1/references.bib research-journal/primary/v1/02-related-work.md research-journal/primary/v1/05-experimental-setup.md`
  - Message: `docs(paper): replace yang2025 stub with verified JMIR Formative Research 2025 entry (closes #15)`
  - Push: `git push origin paper-1/camera-ready`

### Success criteria + gh closure

- Pandoc citeproc emits no `yang2025` warnings
- Author list, DOI, year match JMIR record exactly
- §2 / §5 in-text descriptions match actual JMIR architecture
- `eval/baselines/yang2025.py` untouched
- `gh issue comment 15 --body "Resolved in <SHA>: bib stub replaced with verified JMIR entry (DOI 10.2196/75421); §2/§5 prose corrected to match actual two-agent behavioral-coaching architecture; baseline file unchanged." && gh issue close 15`

---

## Plan B — Issue #16: `_neutral_stub` fail-loud refactor

**Strategy** (validated by web research A — PEP 661, SRE convention, structlog/nulltype ecosystem): replace silent synthetic-gold stub with `RuntimeError` by default; add `--allow-stubs` CLI flag for explicit opt-in lenient mode. TDD: write failing test → fix → verify → coverage.

**Worktree**: `.worktrees/lightrag-test-debt/` (branch `fix/lightrag-test-debt`). Merges to `main` so Plan C can reference its SHA.

### Tasks

- [ ] **T16.1 — Read current site + surrounding API**
  - Read `eval/report.py` L850-920 (`_neutral_stub` function and caller)
  - Read top-of-file imports + CLI argparse setup to locate where `--allow-stubs` flag will be added
  - Read `eval/tests/` directory listing + one neighboring test for fixture conventions
  - Locate the canonical paper-1 v1 render command (Makefile target or script) — confirm no stub-related flag is passed today

- [ ] **T16.2 — RED: write failing regression tests**
  - New file: `eval/tests/test_report_integrity.py`
  - Test 1 `test_missing_scenario_id_fails_render`: build manifest with `scenario_id="not-in-benchmark-xyz"`, call render with default args, assert `pytest.raises(RuntimeError)` whose message contains `not in benchmark` and the offending id
  - Test 2 `test_missing_scenario_id_allowed_with_flag`: same setup, pass `allow_stubs=True`; assert renders without raising; assert synthetic gold has `expected_panel_verdict='abstain'`
  - Test 3 `test_full_benchmark_render_unaffected`: all manifest scenario_ids ∈ benchmark (paper-1 v1 condition); default args render identically (regression guard)
  - Run: `pytest eval/tests/test_report_integrity.py -x` → tests 1, 2 FAIL; test 3 PASS
  - Commit: `test(eval): add report-integrity regression test for missing scenario_id (failing, refs #16)`

- [ ] **T16.3 — GREEN: implement fail-loud refactor**
  - Edit `eval/report.py`:
    - Replace `_neutral_stub(sid)` body with conditional behavior driven by `allow_stubs: bool` parameter
    - Default `allow_stubs=False` → `raise RuntimeError(f"scenario_id {sid!r} not in benchmark — refusing to render with synthetic gold (re-run with --allow-stubs to permit lenient mode)")`
    - When `allow_stubs=True` → return prior synthetic dict; keep dict-construction in renamed helper `_synthetic_neutral_gold(sid)` so lenient path is explicit
  - Add CLI flag: `parser.add_argument("--allow-stubs", action="store_true", default=False, help="Permit synthetic neutral gold for scenario_ids not in benchmark (lenient mode; default fails loud).")`
  - Thread `args.allow_stubs` into render function's `allow_stubs` kwarg
  - Run: `pytest eval/tests/test_report_integrity.py -x` → all 3 tests PASS

- [ ] **T16.4 — Verify no regression on paper-1 v1 render**
  - Re-run canonical paper-1 v1 render command. Expect: completes without `RuntimeError` (paper-1 manifest set-difference with benchmark = 0)
  - Diff produced report against prior paper-1 render: byte-identical (or differs only in timestamp fields). If anything substantive changes, STOP and investigate

- [ ] **T16.5 — Full eval suite + coverage**
  - `cd eval && python -m pytest -x`
  - `python -m pytest --cov=report --cov-report=term-missing tests/test_report_integrity.py` → ≥ 80% coverage on new function paths

- [ ] **T16.6 — Commit GREEN + push + PR**
  - Commit: `fix(eval): make _neutral_stub fail-loud by default; add --allow-stubs opt-in (closes #16)`
  - Body cites PEP 661 + fail-loud SRE convention; notes observational identity on paper-1 v1 render
  - Push: `git push origin fix/lightrag-test-debt`
  - `gh pr create --base main --title "fix(eval): _neutral_stub fail-loud refactor (closes #16)" --body <see plan>`

### Success criteria + gh closure

- All 3 tests in `test_report_integrity.py` pass
- Full `eval/` suite green
- Paper-1 v1 render byte-identical (modulo timestamps)
- Default CLI invocation errors loudly on missing scenario_id; `--allow-stubs` restores lenient mode
- After PR merges to `main`: capture the merge SHA for Plan C T14.7 §9.2 pin
- `gh issue comment 16 --body "Resolved in <SHA>: fail-loud default + --allow-stubs opt-in; regression test at eval/tests/test_report_integrity.py." && gh issue close 16`

---

## Plan C — Issue #14: paper word count via move-don't-cut + 3 new citations

**Strategic shift** (validated by web research B): ML4H 2026 Findings has **no word limit; only 4-page body limit**. References, appendices, ethics, limitations, broader-impact are **excluded from page count and unlimited**. Therefore: move don't cut is the high-yield first pass; trims are only for genuine prose redundancy. Adds (3 new related-work citations) are affordable because the appendix absorbs the surplus.

**Prereqs**: Plan A merged on `paper-1/camera-ready`; Plan B merged on `main` with SHA captured.

**Final budget projection**: body ≈ **3166w** (well under 3500 target, comfortably within 4 pages); appendix ≈ 700w of moved content + 3 new bib entries.

### C0. Setup

- [ ] **T14.0 — Add appendix scaffold**
  - New file: `research-journal/primary/v1/A0-appendix.md` with anchors:
    - `## A.1 Pre-fetch design rationale and pilot data`
    - `## A.2 Cost & latency per-role traces`
    - `## A.3 Failure-mode case studies`
    - `## A.4 Extended related work`
    - `## A.5 Limitations and Broader Impact`
    - `## A.6 Reproducibility extended`
  - Update section-concat script to emit appendix sections AFTER the bibliography directive: `00-…` → `09-…` → `references` → `A0-appendix.md`. Confirm pandoc/LaTeX template places appendix post-references and excludes from page count

### C1. Body trims (apply prior plan T2, T3, T4, T7, T8, T9 verbatim)

- [ ] **T14.1 — T2 §6.5 par-2 dedup** (-70w)
  - File: `06-results.md` L127-144
  - Apply trim from `2026-05-05-paper-1-camera-ready-plan.md` T2 verbatim

- [ ] **T14.2 — T3 §2 Wu trim** (-60w)
  - File: `02-related-work.md` L5-15
  - Apply T3 verbatim WITH JMIR description correction (Plan A T15.2 already landed; verify alignment)

- [ ] **T14.3 — T4 §2 TCM-Eval trim** (-50w)
  - File: `02-related-work.md` L38-47
  - Apply T4 verbatim

- [ ] **T14.4 — T7 §7.3 calibration** (-30w)
  - File: `07-discussion.md` L39-47
  - Apply T7 verbatim

- [ ] **T14.5 — T8 §3.2 single-pass** (-30w)
  - File: `03-system-diet-os.md` L50-56
  - Apply T8 verbatim

- [ ] **T14.6 — T9 §6.3 herbal_single_symptom** (-60w)
  - File: `06-results.md` L76-87
  - Apply T9 verbatim (cross-ref to §6.4)

- [ ] **T14.7 — T10 partial trim §5 baselines** (-30w, NOT -90w)
  - File: `05-experimental-setup.md` L21-30
  - Apply T10 trim BUT keep yang2025 JMIR-correct framing from Plan A T15.3
  - Reduce trim from 90w to ~30w (cut just the C1-peer-review-framing parenthetical for `diet_os_llm_triage`)

### C2. Body→Appendix moves (the high-yield wins)

- [ ] **T14.8 — MOVE T1 §6.4 case-hdi-001 → A.3 Failure-mode case studies** (-80w body, +80w appendix)
  - Cut detailed case walkthrough from `06-results.md` L96-106; paste into A.3 with back-reference
  - Body keeps headline summary: "13 non-empty runs / 0.713 HDI Recall / 0.300 lower CI / 0.000 baselines (full case detail in App. A.3)"

- [ ] **T14.9 — MOVE T5 §3.1 pilot anecdote → A.1 Pre-fetch design rationale** (-80w body, +80w appendix)
  - Cut from `03-system-diet-os.md` L26-32
  - Body keeps one-clause: "(pilot evidence in App. A.1; e.g. transcript-level tool-invocation counts remain zero across all roles)"

- [ ] **T14.10 — MOVE T6 §5 cost-and-latency → A.2 Cost & latency** (-60w body, +60w appendix)
  - Cut from `05-experimental-setup.md` L32-38
  - Body keeps: "(cost & latency traces in App. A.2)"

- [ ] **T14.11 — MOVE §8 Limitations → A.5 Limitations and Broader Impact** (-240w body, +280w appendix)
  - Cut entire `08-limitations.md` content
  - Body keeps a 3-line stub §8 referencing App. A.5: "We discuss limitations and broader impact in App. A.5: (i) single-author gold standard at n=40; (ii) free-tier 30B LLM ceiling; (iii) HDI Recall is in-panel; (iv) source-attribution provenance not Cypher round-trip; (v) AG2-specific orchestration."
  - **Major win** — saves 240w of body at zero content cost

- [ ] **T14.12 — MOVE §9.2 Reproducibility detail → A.6** (-180w body, +200w appendix)
  - Cut detailed Reproducibility bullets from `09-future-work-conclusion.md`
  - Body §9.2 keeps: "We release code and a reference results dir at https://github.com/Syntropy-Health/shrine-diet-bioactivity (commit pin in App. A.6); full reproducibility instructions in App. A.6."
  - Append the §9.2 Plan C insertion (T14.18) to App. A.6 instead

### C3. Add 3 new related-work citations (writing-lens)

- [ ] **T14.13 — ADD-1: CAMP** (closest methodological peer; +28w body)
  - Bib: add `@misc{camp2026, title={CAMP: Case-Adaptive Multi-agent Panel for clinical prediction with three-valued voting}, year={2026}, eprint={2604.00085}, archivePrefix={arXiv}, url={https://arxiv.org/abs/2604.00085}}` to `references.bib`
  - Insertion: §2 "Multi-agent clinical reasoning" para, after MDAgents sentence
  - Prose (28w): "CAMP [@camp2026] adds case-adaptive panel composition with three-valued voting on MIMIC-IV, the closest methodological peer to our verdict-κ + abstain framing, but operates without KG-grounded retrieval."
  - Why ADD: directly parallels our verdict {prefer/caution/reject/abstain} + κ scoring; pre-empts reviewer absence-of-citation note

- [ ] **T14.14 — ADD-2: KG4Diagnosis** (venue-fit credibility; +24w body)
  - Bib: add `@inproceedings{kg4diagnosis2025, title={KG4Diagnosis: Hierarchical multi-agent diagnosis with knowledge-graph augmentation}, booktitle={Proceedings of Machine Learning for Health (PMLR 281)}, year={2025}, eprint={2412.16833}, archivePrefix={arXiv}, url={https://proceedings.mlr.press/v281/zuo25a.html}}` to `references.bib`
  - Insertion: §2 "KG-grounded LLM clinical reasoning" para, after MedRAG sentence
  - Prose (24w): "KG4Diagnosis [@kg4diagnosis2025] (ML4H 2025) couples hierarchical multi-agent diagnosis with KG augmentation; we share the KG-grounded multi-agent thesis but target diet/herb evidence rather than diagnostic reasoning."
  - Why ADD: same venue → demonstrates conversation awareness; pre-empts "should cite the obvious neighbor" reviewer note

- [ ] **T14.15 — ADD-3: NutriOrion** (validates Yang design-space activity; +22w body)
  - Bib: add `@misc{nutriorion2026, title={NutriOrion: A four-specialist agent panel extending two-agent nutrition coaching}, year={2026}, eprint={2602.18650}, archivePrefix={arXiv}, url={https://arxiv.org/abs/2602.18650}}` to `references.bib`
  - Insertion: §2 "Multi-agent clinical reasoning" para, immediately after the Yang sentence (Plan A T15.2)
  - Prose (22w): "NutriOrion [@nutriorion2026] forward-extends the JMIR Yang design with a four-specialist panel, validating that the behavioral-nutrition multi-agent design space remains active."
  - Why ADD: positions Yang as foundational lineage, strengthens §2 narrative arc

- [ ] **HOLD: HealthGenie** — DO NOT add unless §7.2 differentiation paragraph is rewritten. Risk: too close to our positioning; reviewer attack surface

- [ ] **VERIFY-only: MDAgents** — already cited; verify framing is unchanged after T3 trim. No new prose

### C4. Re-assemble + verify

- [ ] **T14.16 — Re-assemble paper.md**
  - Run section-concat script extended for appendix ordering
  - Render: `pandoc paper.md --bibliography references.bib --citeproc --template=<existing> -o /tmp/paper-1-v1.pdf`
  - Inspect: confirm body (everything before "References" heading) ≤ 4 pages; appendix follows after references with no page constraint
  - If body > 4 pages: invoke reserve task — additional move target is §6.4's remaining failure-mode prose to A.3. Do NOT silently delete numeric content

- [ ] **T14.17 — Numeric-consistency sweep**
  - Grep `paper.md` (concatenated) for: `0.258, 0.476, 0.576, 0.713, 0.000, 0.019, 0.715, 0.149, 0.462, p_adj = 0.002, p_adj = 0.006, 33 of 40 (82.5%), 13, 0.090, 0.543, 0.024, 0.015, 0.699, n=40, 5M, 166K, 20 RPM`
  - Each must appear at least once and match `tables/` source of truth

- [ ] **T14.18 — Cite-key audit**
  - `grep -oE '\[@[a-z0-9_]+\]' paper.md | sort -u` and diff against keys in `references.bib`
  - Expect zero unresolved. Confirm `[@yang2025]` resolves to JMIR; `[@camp2026]`, `[@kg4diagnosis2025]`, `[@nutriorion2026]` resolve to new entries

- [ ] **T14.19 — eval test no-regression check**
  - `cd eval && python -m pytest -x` — must be green; confirms Plan B's tests still pass on the camera-ready worktree after rebase

### C5. §9.2 / App. A.6 reproducibility update + tag

- [ ] **T14.20 — Add fail-loud bullet to A.6 (writing-lens, ties to Plan B)**
  - Insert in App. A.6 after the "Re-render" bullet:
  - New bullet (32w): "**Stub safety.** The `eval.report` renderer fails-fast when manifest `scenario_ids` and benchmark `scenario_ids` diverge; permissive rendering for partial debug runs requires explicit `--allow-stubs`. Paper-grade renders use the default fail-loud mode."

- [ ] **T14.21 — Update commit pin in App. A.6**
  - Replace prior commit-range pin with: `at \`paper-1/camera-ready\` head \`<SHA-after-this-plan-merge>\` (tag \`paper-1-v1-arxiv-submission\`); eval-pipeline integrity fix at \`main\` \`<SHA-from-Plan-B-merge>\``

- [ ] **T14.22 — Commit + tag + push**
  - Commit: `paper-1: camera-ready move-don't-cut + 3 new citations + commit-pin (closes #14)`
  - Tag: `git tag -a paper-1-v1-arxiv-submission -m "Paper 1 v1 — ML4H 2026 Findings camera-ready (move-don't-cut, 3 new citations, citation-fixed)"`
  - Push: `git push origin paper-1/camera-ready && git push origin paper-1-v1-arxiv-submission`

### Success criteria + gh closure

- Body ≤ 4 rendered pages (pandoc PDF; gate is pages, not words)
- Appendix `A0-appendix.md` exists post-references with all moved content intact (~700w relocated)
- All headline numbers present and unchanged (T14.17 sweep clean)
- All cite-keys resolve including yang2025 → JMIR + 3 new entries (T14.18 clean)
- `eval/` test suite green on camera-ready worktree (T14.19 clean)
- §9.2 / A.6 commit pin matches actual SHAs of `paper-1/camera-ready` and Plan-B merge into `main`
- Tag `paper-1-v1-arxiv-submission` pushed
- `gh issue comment 14 --body "Resolved in <SHA> on paper-1/camera-ready, tag paper-1-v1-arxiv-submission. Strategy: move-don't-cut to A0-appendix.md per ML4H Findings unlimited-appendix policy. Body ≤ 4 pages; all numerics preserved; 3 new related-work citations added (CAMP, KG4Diagnosis, NutriOrion)." && gh issue close 14`

---

## Cross-plan budget tracker (final)

| Phase | Body Δ (w) | Cumulative body | Appendix Δ (w) | Body word count |
|---|---|---|---|---|
| baseline | 0 | 0 | 0 | 4052 |
| Plan A T15.2 (§2 Yang reframe) | +8 | -8 | 0 | 4060 |
| Plan A T15.3 (§5 Yang one-line) | +2 | -10 | 0 | 4062 |
| Plan C T14.13 ADD-1 CAMP §2 | +28 | -38 | 0 | 4090 |
| Plan C T14.14 ADD-2 KG4Diagnosis §2 | +24 | -62 | 0 | 4114 |
| Plan C T14.15 ADD-3 NutriOrion §2 | +22 | -84 | 0 | 4136 |
| Plan C T14.8 MOVE §6.4 case → A.3 | -80 | -4 | +80 | 4056 |
| Plan C T14.1 TRIM §6.5 par-2 | -70 | +66 | 0 | 3986 |
| Plan C T14.2 TRIM §2 Wu | -60 | +126 | 0 | 3926 |
| Plan C T14.3 TRIM §2 TCM-Eval | -50 | +176 | 0 | 3876 |
| Plan C T14.9 MOVE §3.1 pilot → A.1 | -80 | +256 | +80 | 3796 |
| Plan C T14.10 MOVE §5 cost → A.2 | -60 | +316 | +60 | 3736 |
| Plan C T14.4 TRIM §7.3 calibration | -30 | +346 | 0 | 3706 |
| Plan C T14.5 TRIM §3.2 single-pass | -30 | +376 | 0 | 3676 |
| Plan C T14.6 TRIM §6.3 per-cat | -60 | +436 | 0 | 3616 |
| Plan C T14.7 TRIM §5 baselines (partial) | -30 | +466 | 0 | 3586 |
| Plan C T14.11 MOVE §8 → A.5 | -240 | +706 | +280 | 3346 |
| Plan C T14.12 MOVE §9.2 → A.6 | -180 | +886 | +200 | 3166 |

**Final body**: ≈ **3166w** body (target ≤3500w, hard constraint = 4 rendered pages)
**Appendix**: ≈ 700w relocated reproducible content + new related-work cites
**Net effect**: substantial reviewer-cycle headroom; appendix gains rigor

---

## Constraints across all plans

- **Untouchable numbers** (do NOT modify): §6.1 headline matrix (all 7 rows × 6 cols), §6.2 paired tests (p_adj=0.002/0.006, B=10000), §6.5 ablation (κ=0.019, mean_diffs 0.476/0.715/0.149/0.462), §00 abstract numerics, §09.3 conclusion numerics, all `tables/` files
- **Out-of-lane** (do NOT touch): `lightrag/`, `agents/`, `scripts/cost_tracker`
- **TDD required for #16**: write failing test, fix, verify, coverage
- **Move-don't-cut is the strategy**: every removal from body is either a TRIM (genuine redundancy) or a MOVE (relocate to appendix); never a DELETE of reviewer-relevant content

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| pandoc/LaTeX template doesn't honor "appendix excluded from 4-page body" | Verify with template ahead of T14.16; if template lacks the directive, manually split into `paper.tex` + `appendix.tex` and submit appendix as supplementary material |
| HealthGenie reviewer asks "why not cited" | Add HealthGenie to App. A.4 (Extended related work) with 1-line differentiation note; do NOT add to body |
| Plan B `_neutral_stub` regression breaks paper-1 v1 render | T16.4 byte-diff gate; if non-trivial diff, STOP and investigate |
| Word count drifts above 3500w during edits | Track per-task in budget table; reserve T11 (§4 benchmark category-example MOVE) held back ~40w |
| Plan C rebase on main pulls in unintended Plan B changes | Only `eval/report.py` + `eval/tests/test_report_integrity.py` should diff after rebase |

---

## Files to be modified

| File | Plan | Operation |
|---|---|---|
| `research-journal/primary/v1/references.bib` | A T15.1, C T14.13-15 | Replace yang2025 stub; add 3 new entries |
| `research-journal/primary/v1/02-related-work.md` | A T15.2, C T14.2/3, C T14.13-15 | §2 prose corrections + adds |
| `research-journal/primary/v1/03-system-diet-os.md` | C T14.5, C T14.9 | T8 trim, T5 MOVE |
| `research-journal/primary/v1/05-experimental-setup.md` | A T15.3, C T14.7, C T14.10 | §5 prose, T10 partial trim, T6 MOVE |
| `research-journal/primary/v1/06-results.md` | C T14.1, C T14.6, C T14.8 | T2 trim, T9 trim, T1 MOVE |
| `research-journal/primary/v1/07-discussion.md` | C T14.4 | T7 trim |
| `research-journal/primary/v1/08-limitations.md` | C T14.11 | MOVE entire to A.5; replace with 3-line stub |
| `research-journal/primary/v1/09-future-work-conclusion.md` | C T14.12, C T14.20-21 | MOVE §9.2 to A.6 + commit pin |
| `research-journal/primary/v1/A0-appendix.md` | C T14.0, C T14.8-12, C T14.20 | NEW file with 6 sections |
| `research-journal/primary/v1/paper.md` | C T14.16 | Re-assembled |
| `eval/report.py` | B T16.3 | _neutral_stub fail-loud refactor + --allow-stubs |
| `eval/tests/test_report_integrity.py` | B T16.2 | NEW regression test (3 cases) |

---

## SESSION_ID handoff (for `/ccg:execute` use)

The codeagent-wrapper Codex/Gemini sessions were not available on this system; Claude `architect` and `planner` subagents substituted per user direction. SESSION_IDs are not applicable for this fallback path.

If you want to re-run with actual Codex/Gemini next time:
- Install `~/.claude/bin/codeagent-wrapper`
- Install `~/.claude/.ccg/prompts/{codex,gemini}/{analyzer,architect}.md` role prompts
- Re-invoke `/ccg:plan follow-up on 14-16`

---

## Delta vs prior `2026-05-05-paper-1-camera-ready-plan.md`

The prior plan treated the word-count overrun as a pure-trim problem (T1-T10 all classified TRIM, target 3442w body via 610w of cuts) and made no related-work additions. This plan **(a)** re-frames per ML4H 2026 Findings actual venue rules — 4-page body limit, unlimited appendix — converting 4 of 10 trims into appendix MOVES at zero body cost; **(b)** moves §8 Limitations and §9.2 Reproducibility detail wholesale to appendix (~440w body savings the prior plan missed); **(c)** adds 3 new citations (CAMP, KG4Diagnosis, NutriOrion) to §2 to address venue-fit and methodological-peer absence risks the prior plan did not flag, with HealthGenie deferred for differentiation safety; **(d)** corrects the prior plan's own residual mislabel of Yang et al. as "dietitian-pharmacist diet-drug interaction" by introducing a "JMIR Yang baseline of behavioral-science-informed agentic workflows" framing handle reused across §2 and §5; **(e)** introduces an entirely new Plan B (Issue #16, `_neutral_stub` fail-loud refactor with TDD and `--allow-stubs` opt-in flag) which has no analog in the prior plan; **(f)** lands at body ≈ 3166w (vs prior 3442w target), giving substantial reviewer-cycle headroom for any reviewer-requested addition.
