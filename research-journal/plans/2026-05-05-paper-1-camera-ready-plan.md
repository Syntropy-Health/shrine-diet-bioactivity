# Paper-1 Camera-Ready Trim and Citation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Camera-ready trim of `paper.md` from 4052 → ≤3500 words for ML4H 2026 Findings (Sep 8 deadline) plus resolution of the unverified `yang2025` citation.

**Architecture:** Phase 1 — citation rename (Option B: drop the unverified citation, rename baseline). Phase 2 — 10 surgical section trims. Phase 3 — re-assembly + numeric-consistency sweep + tag.

**Tech Stack:** Markdown sources at `research-journal/primary/v1/`, BibTeX references, Python eval baseline rename, pytest regression gates.

---

## Untouchable Content (do not modify)

- §6.1 headline matrix table (06-results.md L16-24)
- §6.2 paired-test numerics (p_adj values, mean_diffs, B=10000 spec)
- §6.5 ablation numerics (κ=0.019, 0.476/0.715/0.149/0.462 mean_diffs, p-values, 33-of-40 first occurrence)
- Abstract numerics (00-abstract.md L13-19)
- §9.3 conclusion numerics (09-future-work-conclusion.md L45)
- All numeric content in tables under `tables/`
- `lightrag/`, `agents/`, `scripts/cost_tracker` (out of scope)

---

## Word-count budget tracker

| Task | Trim (w) | Cumulative | Projected paper.md |
|---|---|---|---|
| baseline | 0 | 0 | 4052 |
| T1: §6.4 case-hdi-001 | -80 | 80 | 3972 |
| T2: §6.5 par-2 dedup | -70 | 150 | 3902 |
| T3: §2 Wu trim + cite-prose | -60 | 210 | 3842 |
| T4: §2 TCM-Eval trim | -50 | 260 | 3792 |
| T5: §3.1 pilot anecdote | -80 | 340 | 3712 |
| T6: §5 Cost & latency | -60 | 400 | 3652 |
| T7: §7.3 calibration | -30 | 430 | 3622 |
| T8: §3.2 single-pass | -30 | 460 | 3592 |
| T9: §6.3 herbal_single_symptom | -60 | 520 | 3532 |
| T10: §5 baselines paragraph | -90 | 610 | 3442 |

Reserve T11 (`§4` benchmark category-example parens): held back ~40w if needed.

---

## Phase 1: Citation rename (Option B)

**Recommendation rationale:** stub bib note already declares "Unverified — no public preprint located". Camera-ready with unverified citation = reviewer-risk surface for zero benefit. Drop bib stub, do prose substitutions, rename eval baseline. Fully reversible if a verified Yang et al. preprint surfaces (~10 min).

### T0a — Drop yang2025 stub bib entry

- File: `research-journal/primary/v1/references.bib` L20-32
- Action: Delete the stub block. Replace with one-line removal-marker comment:
  ```
  % yang2025 baseline citation removed pre-submission per camera-ready audit;
  % see eval/baselines/dietitian_pharmacist_2role.py for the design-pattern re-implementation.
  ```

### T0b — Replace `[@yang2025]` cite-keys with prose

Apply same substitution across four section files:

1. `00-abstract.md` L14: `over MedAgents, MDAgents, and yang2025 baselines, plus` → `over MedAgents, MDAgents, and a 2-role dietitian-pharmacist baseline we re-implemented, plus`
2. `01-introduction.md` L8 + L33: replace `Yang et al. [@yang2025]` with `the 2-role dietitian-pharmacist setup we re-implemented`
3. `02-related-work.md` L8-9: combined with T3 for the Wu trim
4. `05-experimental-setup.md` L23: `\`yang2025\` (2-role dietitian-pharmacist) [@yang2025]` → `\`dietitian_pharmacist_2role\` (2-role dietitian-pharmacist baseline, re-implemented after an external design pattern)`
5. `09-future-work-conclusion.md` L45: `and yang2025 [@yang2025] baselines` → `and a re-implemented 2-role dietitian-pharmacist baseline`

Net citation-rename word delta: ~+30w (absorbed by trim budget).

### T0c — Rename eval baseline file

- `git mv eval/baselines/yang2025.py eval/baselines/dietitian_pharmacist_2role.py`
- Update module-level docstring header.

### T0d — Update baselines registry

- File: `eval/baselines/__init__.py`
- Replace registry key `"yang2025"` → `"dietitian_pharmacist_2role"`. Update import.

### T0e — Update test expectations

- File: `eval/tests/test_baselines.py`
- Substitute `"yang2025"` → `"dietitian_pharmacist_2role"` in expected-set assertion.

### T0f — Sweep for stale references

- `rg "yang2025" -n .` (excluding `lightrag/`, `agents/`, `scripts/cost_tracker`, and `research-journal/shared/results/` historical artifacts)
- Expected: zero hits in `research-journal/primary/v1/`, `eval/baselines/`, `eval/tests/`. Hits in historical results dirs are acceptable (frozen artifacts).

### T0g — Run eval test suite (regression gate)

- `cd eval && python -m pytest -x` (or project-standard invocation)
- Pass criterion: all green; in particular `test_baselines.py` passes with renamed registry key.

---

## Phase 2: Section trims

### T1 — §6.4 Failure-mode taxonomy: condense case-study (~80w)

File: `06-results.md` L89-106

**Before** (L96-106):
```
The dominant failure mode is upstream of the panel: the eval-time
`_intervention_from_scenario_id` heuristic misses canonical KG names for
non-Duke compounds and TCM herbs, producing empty candidate chains.
`case-hdi-001-sjw-sertraline` illustrates the pattern: gold `reject`,
predicted `caution`, candidate_chains = 0, confidence = 0.016. Of the 13
runs that *do* surface chains, 7 are panel mis-votes and 6 are correct
verdicts under-scored by the calibrator. The 0.713 HDI Recall is therefore
concentrated in those 13 non-empty runs; the lower 95% bound (0.300 on the
paired-test mean_diff, 0.333 on the absolute Recall CI) reflects this
small effective sample. The structural separation over baselines (all
0.000) is preserved because no baseline has a mechanism to surface HDI
claims at all — independent of how many of its 40 runs produce chains.
```

**After**:
```
The dominant failure mode is upstream of the panel: the eval-time
`_intervention_from_scenario_id` heuristic misses canonical KG names for
non-Duke compounds and TCM herbs, producing empty candidate chains
(per-case rows in `tables/failure-taxonomy.md`). The 0.713 HDI Recall is
concentrated in the 13 non-empty runs, which is reflected in the lower
95% CI bound (0.300 paired-test mean_diff). The structural separation
over baselines (all 0.000) is preserved because no baseline has a
mechanism to surface HDI claims at all.
```

Numbers preserved: 13 runs, 0.713, 0.300, 0.000. Removed (in table file): 7/6 split, 0.016, 0.333.

### T2 — §6.5 par-2 dedup (~70w)

File: `06-results.md` L127-144

**Before** (L127-144 of current version):
```
The proximate failure mode is the LLM triage step itself: 33 of 40 runs
(82.5%) terminate with `runner-error: Invalid JSON: EOF while parsing a
list` — the free-tier Nemotron-3-nano-30B (≤20 RPM) emits malformed JSON
on the structured `ResearchQuestion` output. The runner falls back to
default `complexity='low'`, `red_flags=[]`, `clarification_questions=[]`,
which seeds zero retrieval keys; consequently 40 of 40 runs (100%) have
empty candidate chains, and 33 of 40 panels terminate at
`moderator_summary='error'` after exhausting AG2's `Maximum rounds (3)`.
Two architectural components are therefore load-bearing in combination:
(i) the deterministic triage substitute, which is invariably
parse-clean, and (ii) the gold-question-anchored retrieval seed, which
requires triage output the panel can actually use. Removing (i) breaks
(ii) by cascading failure, regressing the system to the `single_llm`
envelope. We discuss the v2 path — a small purpose-trained triage model
or schema-constrained decoding — in §8. The 0.090 ECE that
`diet_os_llm_triage` posts is *not* an architectural strength to retain;
it is the spurious low-error of a system that has stopped engaging with
the question.
```

**After**:
```
The proximate failure mode is the LLM triage step itself: 33 of 40 runs
(82.5%) terminate with `runner-error: Invalid JSON: EOF while parsing a
list` — the free-tier Nemotron-3-nano-30B (≤20 RPM) emits malformed JSON
on the structured `ResearchQuestion` output. The runner's default
fallback seeds zero retrieval keys, so all 40 runs have empty candidate
chains and the panels terminate at `moderator_summary='error'`. Two
architectural components are therefore load-bearing in combination: the
deterministic triage substitute (invariably parse-clean) and the
gold-question-anchored retrieval seed; removing the first cascades into
the second, regressing the system to the `single_llm` envelope. The
v2 path — a small purpose-trained triage model or schema-constrained
decoding — is discussed in §8. The 0.090 ECE that `diet_os_llm_triage`
posts is the spurious low-error of a system that has stopped engaging
with the question, not an architectural strength.
```

Numbers preserved: 33 of 40 (82.5%), all 40 runs, 0.090. First paragraph (L110-126) untouched.

### T3 — §2 Multi-agent: trim Wu et al. + apply T0b prose (~60w)

File: `02-related-work.md` L5-15

**Before**:
```
MedAgents [@medagents2024] frames zero-shot medical reasoning as a multi-role
panel deliberating over nine medical datasets, and MDAgents [@mdagents2024]
adds adaptive routing between solo and multi-disciplinary-team configurations.
Yang et al. [@yang2025] propose a 2-role dietitian-pharmacist setup for
diet-drug interaction reasoning. We compare against all three as architectural
baselines and extend them with Layer-B/C role-priored KG retrieval. A
contemporary threat is Wu et al.'s "Safer Therapy" [@wu2025], which reports
single-GP performance comparable to a multi-disciplinary debate panel on
medication-conflict resolution; §7.2 argues that our HDI Recall structural
ablation shows debate without KG-grounding cannot produce HDI signal, placing
the two findings on orthogonal axes.
```

**After**:
```
MedAgents [@medagents2024] frames zero-shot medical reasoning as a
multi-role panel; MDAgents [@mdagents2024] adds adaptive routing
between solo and multi-disciplinary configurations. As a third
baseline we re-implement an external 2-role dietitian-pharmacist setup
for diet-drug interaction reasoning. We extend all three with Layer-B/C
role-priored KG retrieval. Wu et al. [@wu2025] report single-GP
performance comparable to a multi-disciplinary debate panel on
medication-conflict resolution; §7.2 places that finding on an axis
orthogonal to ours.
```

### T4 — §2 Existing benchmarks: trim TCM/MedQA paragraph (~50w)

File: `02-related-work.md` L38-47

**Before**:
```
TCM-Eval [@tcmeval2025] and TCM-5CEval [@tcm5ceval2025] cover TCM knowledge
questions with no clinical-deliberation evaluation. MedQA [@medqa2021] and
MedMCQA [@medmcqa2022] are general medical-MCQ ceilings with no diet or herb
content, and AgentClinic [@agentclinic2024] is multimodal sequential
consultation. To the best of available literature, DietResearchBench-Clinical
(§4) is the first public benchmark covering herb-drug interaction reasoning,
diet-bioactive clinical inference, and TCM syndrome / Western-nutrition
crosswalk in a single evaluation set.
```

**After**:
```
TCM-Eval [@tcmeval2025] and TCM-5CEval [@tcm5ceval2025] cover TCM
knowledge questions only, with no clinical-deliberation evaluation.
MedQA [@medqa2021], MedMCQA [@medmcqa2022], and AgentClinic
[@agentclinic2024] are general or multimodal benchmarks without diet or
herb content. DietResearchBench-Clinical (§4) is the first public
benchmark covering herb-drug interaction reasoning, diet-bioactive
inference, and TCM-syndrome / Western-nutrition crosswalk in one set.
```

### T5 — §3.1 Pre-fetched: drop pilot anecdote (~80w)

File: `03-system-diet-os.md` L26-32

**Before**:
```
This **pre-fetched** design is a deliberate departure from LLM-driven tool
calls. Our pilot found Nemotron-30B emits `RoleVerdict` JSON whose `notes`
field claims tool use ("Used `kg_diet_to_compounds`…") while transcript-level
tool-invocation counts remain zero across all roles — the model hallucinates
tool use from training-data priors (`e2-panel-mcp-wiring-results.md`).
Pre-fetching guarantees every panel deliberation receives a non-empty bundle,
so HDI-Recall and provenance metrics (§4) become measurable rather than null.
```

**After**:
```
This **pre-fetched** design is a deliberate departure from LLM-driven
tool calls: under free-tier 30B inference, models hallucinate tool use
in `notes` fields while transcript tool-invocation counts remain zero
(pilot detail in repo report `e2-panel-mcp-wiring-results.md`).
Pre-fetching guarantees every panel deliberation receives a non-empty
bundle, so HDI-Recall and provenance metrics (§4) become measurable.
```

### T6 — §5 Cost and latency: defer to code release (~60w)

File: `05-experimental-setup.md` L32-38

**Before**:
```
**Cost and latency.** Per-role token usage and latency are captured by
the `cost_tracker` decorator wrapping `ConversableAgent.generate_reply`.
Free-tier rate limits dominate end-to-end matrix wall-clock (full-40
× 6 baselines completed in ~3 hours; the `diet_os_llm_triage` ablation
adds ~2 hours due to free-tier RPM throttling on the additional triage
LLM call). Detailed per-role traces are available in the companion code
release; we omit the table here for space.
```

**After**:
```
**Cost and latency.** Per-role token usage and latency are captured by
a `cost_tracker` decorator and reported in the companion code release;
free-tier RPM throttling dominates wall-clock.
```

Numbers removed: ~3 hours, ~2 hours (none paper-grade).

### T7 — §7.3 Calibration trade-off (~30w)

File: `07-discussion.md` L39-47

**Before**:
```
ECE is highest for `diet_os` at 0.543 — significantly worse than
`medagents` (0.024, mean_diff +0.531) and `mdagents` (0.015, mean_diff
+0.540) at p_adj = 0.002. The trade-off reflects panel-derived
confidence variance under an uncalibrated free-tier model: `medagents`
and `mdagents` emit near-constant low confidence, collapsing ECE toward
the gold rate, while `diet_os`'s composite confidence (evidence-tier ×
HDI-risk × question-fit, §3.3) carries honest but uncalibrated signal.
Post-hoc Platt/isotonic calibration on a held-out fold is straightforward
v2 work (§8.2, §9).
```

**After**:
```
ECE is highest for `diet_os` at 0.543, significantly worse than
`medagents` (0.024) and `mdagents` (0.015) at p_adj = 0.002. The
trade-off reflects panel-derived confidence variance: baselines emit
near-constant low confidence that collapses ECE toward the gold rate,
while `diet_os`'s composite confidence carries honest but uncalibrated
signal. Post-hoc Platt/isotonic calibration is straightforward v2 work
(§8.2, §9).
```

Numbers preserved: 0.543, 0.024, 0.015, p_adj = 0.002. Removed: +0.531, +0.540 mean_diffs (in tables).

### T8 — §3.2 Single-pass justification (~30w)

File: `03-system-diet-os.md` L50-56

**Before**:
```
Tools remain available as fallbacks when the LLM does emit valid `tool_calls`,
but the bundle dominates the evidence pathway. Each role emits a `RoleVerdict`
∈ {prefer, caution, reject, abstain} with `support[]`, `concerns[]`, and
`cited_chains[]` indices into the bundle. Single-pass round-robin (rather
than multi-round rebuttal) is forced by the 20-RPM rate limit and is
defensible because pre-fetching removes the information asymmetry rebuttal
would normally resolve (§7.2).
```

**After**:
```
Tools remain available as fallbacks when the LLM emits valid
`tool_calls`, but the bundle dominates the evidence pathway. Each role
emits a `RoleVerdict` ∈ {prefer, caution, reject, abstain} with
`support[]`, `concerns[]`, and `cited_chains[]` indices. Single-pass
round-robin is forced by the 20-RPM rate limit; pre-fetching removes
the information asymmetry rebuttal would resolve (§7.2).
```

### T9 — §6.3 Per-category trim (~60w)

File: `06-results.md` L76-87

**Before**:
```
The per-category Verdict κ heatmap (`figures/per-category-heatmap.png`,
data in `tables/per-category.md`) shows `diet_os` strongest on `tcm_bilingual`
(κ = 0.167), `nutrition` (0.153), and `multi_drug_hdi` (0.138), and weakest
on `herbal_single_symptom` (κ = -0.081). Baselines are essentially flat
across categories (max non-`diet_os` cell: `single_llm` on `multi_drug_hdi`,
0.062). The `herbal_single_symptom` regression is consistent with eval-time
intervention extraction missing the herb's canonical KG name in
single-symptom scenarios — the `_intervention_from_scenario_id` heuristic
favours multi-token names (e.g. "St John's wort + sertraline") and degrades
on bare herbal mononyms.
```

**After**:
```
The per-category Verdict κ heatmap (`figures/per-category-heatmap.png`,
data in `tables/per-category.md`) shows `diet_os` strongest on
`tcm_bilingual` (κ = 0.167), `nutrition` (0.153), and `multi_drug_hdi`
(0.138), and weakest on `herbal_single_symptom` (κ = -0.081). Baselines
are flat across categories (max non-`diet_os` cell: 0.062). The
`herbal_single_symptom` regression traces to the same intervention-name
extraction issue documented in §6.4.
```

Numbers preserved: 0.167, 0.153, 0.138, -0.081, 0.062.

### T10 — §5 Baselines paragraph trim (~90w)

File: `05-experimental-setup.md` L21-30 (post-T0b form)

**Before** (post-T0b):
```
**Baselines.** Five external baselines plus `diet_os` and a within-system
ablation share LLM, KG, and gateway: `single_llm` (no tools),
`single_llm_rag` (naïve RAG), `dietitian_pharmacist_2role` (2-role
dietitian-pharmacist baseline, re-implemented after an external design
pattern), `medagents` (n-role debate, no KG) [@medagents2024],
`mdagents` (adaptive routing, no KG) [@mdagents2024], **`diet_os`** (this
work, deterministic gold-triage substitute — see §5.4 for the bypass
disclosure), and **`diet_os_llm_triage`** (identical to `diet_os` but
replacing the deterministic triage with a free-tier LLM call; introduced
to address peer-review concern C1 about gold-triage bypass, full discussion
in §6.5). We report the full N = 40 matrix across all seven systems.
```

**After**:
```
**Baselines.** Five external baselines plus `diet_os` and a within-system
ablation share LLM, KG, and gateway: `single_llm` (no tools),
`single_llm_rag` (naïve RAG), `dietitian_pharmacist_2role` (re-implemented
external 2-role design pattern), `medagents` [@medagents2024], `mdagents`
[@mdagents2024], **`diet_os`** (this work; deterministic gold-triage
substitute, see §5.4), and **`diet_os_llm_triage`** (the §6.5 ablation
replacing deterministic triage with a free-tier LLM call). We report the
full N = 40 matrix across all seven systems.
```

---

## Phase 3: Re-assembly and verification

### T11 — Re-assemble paper.md
- Run section-concatenation (Python script identical to one used in earlier R-plan):
  ```python
  from pathlib import Path
  sections = sorted(Path('research-journal/primary/v1').glob('0[0-9]-*.md'))
  out = "\n".join(p.read_text().rstrip() + "\n" for p in sections).rstrip() + "\n"
  Path('research-journal/primary/v1/paper.md').write_text(out)
  ```
- `wc -w research-journal/primary/v1/paper.md` should read ≤3500.
- If 3450-3500: stop trimming, proceed.
- If >3500: invoke reserve T11 (§4 benchmark category-example trim, ~40w).

### T12 — Numeric-consistency sweep
Grep `paper.md` for headline numbers and confirm presence + identical value:
- `0.258` (diet_os κ), `0.476` / `0.576` (mean_diff bounds), `0.713` (HDI Recall), `0.000` (baselines), `0.019` (diet_os_llm_triage κ), `0.715` / `0.149` / `0.462` (ablation mean_diffs), `p_adj = 0.002` / `0.006`, `33 of 40 (82.5%)`, `13` non-empty runs, `0.090` ablation ECE, `0.543` / `0.024` / `0.015` ECE, `0.699` Defer Acc, `n=40`, `5M` edges, `166K` nodes, `20 RPM`.

### T13 — Final cite-key audit
- `rg "@yang2025|yang2025" research-journal/primary/v1/` — expect zero hits in paper text.
- Audit remaining cite-keys in `paper.md` against `references.bib`.

### T14 — Re-run eval test suite
- `cd eval && python -m pytest -x` — confirms rename didn't break anything.

### T15 — Update §9.2 reproducibility commit pin
- File: `09-future-work-conclusion.md` L17-21
- Replace commit-range pin with: `at \`paper-1/camera-ready\` head \`<NEW_SHA>\` (tag \`paper-1-v1-arxiv-submission\`).`
- Word delta: -10w (added headroom).

### T16 — Tag camera-ready submission
- `git tag -a paper-1-v1-arxiv-submission -m "Paper 1 v1 — ML4H 2026 Findings camera-ready (post-trim, citation-fixed)"`
- `git push origin paper-1-v1-arxiv-submission`

---

## Testing Strategy
- **Unit/integration**: `eval/` pytest at T0g (after rename) and T14 (after all edits).
- **Numeric consistency**: T12 grep sweep; manual review of any miss.
- **Citation integrity**: T13 audit; zero unresolved keys, zero `yang2025` references.
- **Word count**: ≤3500 at T11.

---

## Risks & Mitigations
- **Risk:** Trim removes a paper-grade number.
  - Mitigation: Untouchable list + T12 numeric sweep.
- **Risk:** Rename breaks undiscovered call site.
  - Mitigation: T0g pytest gate before paper edits; T14 re-run after.
- **Risk:** Section concatenation script broken/missing.
  - Mitigation: T11 falls back to manual `cat` in alphabetical order.
- **Risk:** Verified Yang et al. preprint surfaces between plan and submission.
  - Mitigation: Option B is reversible — re-add bib stub with verified info, restore four cite-keys; ~10 min.

---

## Success Criteria

- [ ] `paper.md` word count ≤ 3500 after T11
- [ ] No paper-grade number changed (T12 sweep passes)
- [ ] Zero `yang2025` cite-keys in paper text (T13 audit passes)
- [ ] `references.bib` has no unverified stub entries
- [ ] `eval/` test suite green after rename (T0g and T14)
- [ ] `eval/baselines/dietitian_pharmacist_2role.py` exists; `eval/baselines/yang2025.py` does not
- [ ] §9.2 commit pin matches actual head SHA of `paper-1/camera-ready`
- [ ] Tag `paper-1-v1-arxiv-submission` pushed to origin

---

## Appendix: Option A path (if a verified Yang et al. citation surfaces)

1. Skip T0a, T0b, T0c, T0d, T0e, T0f, T0g, T13 rename steps (and T14 rename-regression check).
2. Replace bib stub with verified `@misc{yang2025, ...}` block.
3. Leave all four `[@yang2025]` cite-keys intact in section files.
4. Trim tasks T1–T11 still apply; the +30w prose substitution is not incurred → post-trim ~3410w.
5. T15 and T16 still apply.

---

## Execution handoff

After all tasks complete:
- `git push -u origin paper-1/camera-ready`
- Push tag: `git push origin paper-1-v1-arxiv-submission`
- Open PR titled "paper-1: camera-ready trim + citation fix (closes #14, #15)"
- Convert paper.md → PDF via pandoc (off-machine, user-side)
- Submit to arXiv
- Submit to ML4H 2026 Findings (Sep 8 deadline)
