# dispatch-pvp Feedback — Run 20260506-013000-drug-bioactive-bridge

## Outcome

**State:** parked (with 5 documented hand-off items).
**Branch:** `pvp/20260506-013000-drug-bioactive-bridge`.
**PR:** https://github.com/Syntropy-Health/shrine-open-diet/pull/18

## Phase summary

| Phase | Tasks | Result |
|---|---|---|
| 1 (interactive) | brainstorming → spec → writing-plans → harden-plan → user approval | ✓ approved |
| 2 (autonomous) | 12 plan tasks + 3 critical fixes from code review | ✓ all `[done-auto]`, 33 Python tests + 5 vitest green |

## Step-by-step timing (approximate)

| Step | Activity | Notes |
|---|---|---|
| 0a | Env preflight | Found 2 missing Python pkgs, all CLIs/skills present |
| 0b | Research | web-researcher returned 600-word brief in ~150 s with 5 cited sources |
| 1 | Brainstorming | 2 user questions (Q1 use-case, Q2 ingestion slice); chose A∪D + D-hybrid |
| 2 | writing-plans | 12 tasks, real file paths inlined |
| 2.5 | harden-plan | **Substantial re-architect** — schema probe revealed no SMILES, no PubChem CIDs; primary path inverted to name→PubChem |
| 3a | Worktree | `.worktrees/pvp-drug-bioactive` from main |
| 3b | Execute | Tasks 0-12 sequentially; ~3 commits per task in early tasks, collapsed into single commits where natural |
| 4a/4b | autonomous-qa | Skipped — no preview deployment / no UI to test |
| 5 | finishing-a-development-branch | Draft PR #18 opened |
| 6 | Review | code-reviewer (3 critical) + security-reviewer (clean) in parallel |
| 7 | Iterate | Iter 1 fixed all 3 critical findings + added 4 new tests |
| 7.5 | Documentation | doc-updater not separately dispatched — docs were authored inline as Tasks 11/runbook updates |
| 8 | Merge | DEFERRED — PR is draft+ready for human review (parked, not auto-merged) |
| 9 | Feedback | this commit |
| 10 | Lint | next commit |

## Runbook entries created (5)

All non-blocking; documented for human follow-up:

1. `harden-plan/data/missing-smiles-column` — Phase 2 SMILES backfill plan documented.
2. `harden-plan/data/empty-pubchem-cid-column` — fills as side-effect of Phase 1 resolution.
3. `harden-plan/python-pkg/rdkit-and-chembl-downloader-not-installed` — auto-resolved in Task 0.
4. `harden-plan/code/lightrag-not-a-package` — auto-resolved in Task 0.
5. `harden-plan/scope/full-94k-name-resolution-deferred` — accepted per Q2 user decision.

Plus one inline noted-during-execution side issue: `kg-mcp/auth/sj-token-validator-not-implemented` — separate PR will close upstream issue #10.

## Common failure patterns observed (worth noting for future runs)

1. **`Edit` tool failed silently when target file wasn't `Read` first.** Hit twice (build-herbal-db.ts DDL, README.md edit). Both committed *only* the test/sibling file before noticing the change wasn't there. Fix: always `Read` before `Edit`, even when the change feels trivial; or run `grep` after the edit to verify text landed.
2. **Schema probe BEFORE any code is written paid for itself many times over.** The harden-plan phase caught a fundamental architectural assumption error (RDKit-from-SMILES) that would have wasted hours mid-execution. The spec was patched in place, the plan was rewritten, and Phase 2 ran cleanly because of it.
3. **Stale gitStatus at session start.** The system-reported "Current branch: main" was wrong by the time Phase 2 started — branch had switched to `feature/mcp-posthog-analytics` from a parallel session. Worktree creation from `main` recovered cleanly. Lesson: re-check the live branch state before any worktree operation.

## Novel techniques used (worth keeping)

1. **In-memory SQLite subprocess smoke** — for CLI scripts that operate on the gitignored 5.5GB live DB, build a tiny ephemeral DB inside Python, write fixture rows that exercise the active-subset filter, run the CLI as a subprocess, then assert on the resulting rows. Catches schema-vs-script mismatches without needing the real data.
2. **Header-name-indexed CSV parsing** for external API responses (PubChem PUG-REST). Uses `csv.reader` instead of `.split(',')` so it handles quoted strings with commas correctly AND survives column reorders if the upstream API ever changes its CSV ordering.
3. **`with target_conn:` for atomic multi-statement migrations** — neat pattern for "DELETE then INSERT N rows" where partial completion would corrupt state.

## Suggested CLAUDE.md additions

None high-confidence enough to merge inline. The "Always Read before Edit" reminder is already implicit in the system prompt; the others are too narrow.

## Final stats

- **Commits on branch (excluding base):** 17 (15 feature/fix + 1 docs/spec import + 1 fix-rdkit-pin)
- **Files changed:** 21 created, 6 modified
- **Lines added:** ~2,800 (incl. spec/plan/runbook), ~1,400 of code+tests
- **Tests:** 33 Python (all green) + 5 vitest (all green); 88% coverage on new modules
- **Open runbook items needing human:** 5 (none blocking; all documented)
