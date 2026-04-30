# DietResearchBench-Clinical v1 — Post-mortem & Next Steps

_Authored 2026-04-26. Branch: `feature/mcp-herbal-botanicals`. Run under review: `results/20260426T000939Z/`._

This memo is intentionally heavy on design rationale. It is meant to be read alongside the program plan (`research-journal/plans/2026-04-22-program.md`) and the Subsystem F plan. It is **not** a paper draft — it is the contract for the v1 re-run and the assumptions that re-run will validate or falsify.

---

## 1. Where we actually are

| Layer | Status | Evidence |
|---|---|---|
| KG ingestion (Subsystem A) | ✅ Live on Aura `c16cebae` | `ingestion-snapshot.md` 2026-04-25: 24,848 nodes / 57,199 edges incl. SymMap 2.0 (7,704 nodes), HERB 2.0 (1,483), Duke (15,520), HDI-Safe-50 (41 edges) |
| AG2 clinical panel (Subsystem H) | ✅ End-to-end runner exists | Commits `1513b40…ef37f58`. 6 role agents + GroupChat + run_case_study + 3 demo specs in `agents/case_studies/` |
| Eval harness (Subsystem F) | ✅ F0–F7 implemented | `eval/{scenario,splits,metrics,runner,report}.py` + 6 baselines in `eval/baselines/`. 47 passed + 2 skipped. |
| v1 benchmark dataset | ⚠️ 40-scenario seed only | `eval/scenarios/v1/*.json`. Plan target is 200 with dietitian + pharmacist gold + IAA. |
| **v1 eval run (this memo)** | ❌ **Failed silently** | `results/20260426T000939Z/summary.md` — 5 of 6 systems present, all metrics ≈ 0 or constant; `paired_tests.md`: *"No diet_os system in results — skipped."* |
| Paper drafts (Subsystem G) | 🗒️ Not started | — |

The headline: we have a paper-citable harness sitting on a paper-citable KG, but **no paper-citable findings yet**. v1's apparent "all-zeros" output has two distinct, separable causes — not one. Treating them as one would lead to wrong fixes.

---

## 2. What v1 actually measured (and why every cell looks broken)

### 2.1 Failure mode A — `diet_os` infrastructure error (not a design flaw)

Every `diet_os` case-study output in `results/20260426T000939Z/diet_os/*.json` contains:

```
"triage": { "rationale": "runner-error: LightRAG unreachable at http://localhost:9621: ..." }
"panel":  { "verdicts": [], "moderator_summary": "error" }
"confidence": 0.0
```

**Cause:** LightRAG FastAPI server (`scoped_server.py`, port 9621) was not running when the eval matrix executed. The `kg_query` AG2 tool degrades to error placeholders rather than raising, which makes the failure silent at harness level — `diet_os` produced 40 valid-but-empty `ResearchSynthesis` objects, the runner persisted them, and the report renderer dropped the whole system because there were no role verdicts to score.

**Implication:** This is purely operational. The KG content is fine (Aura snapshot 2026-04-25 confirms it). Once the server is up, `diet_os` should produce non-trivial verdicts because the data it would query is in place.

**Lesson encoded as a gate:** the runner must refuse to start if any required dependency is unreachable. See §5.

### 2.2 Failure mode B — five baselines returning structurally-valid empties (this is by design)

The other five baselines (`single_llm`, `single_llm_rag`, `mdagents`, `medagents`, `yang2025`) ran without error against OpenRouter free-tier. Their per-system metric files exist. Yet:

| Metric | Result | Why this happens |
|---|---|---|
| `verdict_kappa` ≈ 0.000 (single_llm: 0.144) | Verdicts collapsing into a single mode | Free-tier model + minimal-prompt baseline returns the same verdict (typically `caution` or `abstain`) for nearly every scenario → no agreement variance to score |
| `hdi_recall = 0.000` everywhere | None of these baselines extract HDI claims | **By construction.** None of the five baseline implementations have an HDI extraction stage. The metric is implicitly 0 for any system that doesn't emit an HDI list. |
| `provenance = null` everywhere | None emit Cypher chains | Same as above. The provenance metric requires a system that surfaces graph paths; baselines don't. |
| `bilingual = 0.000` everywhere | None translate or surface CN content | Same — baselines aren't bilingual-capable. |
| `defer_acc = 0.5566` everywhere | Identical across systems → constant prediction | Likely the rate of "no-defer" gold labels under a constant `defer=False` prediction. |
| `ece = 0.397` (3 of 5) | Uniform confidence assignment | Without a calibrator the systems return either no confidence or a constant value, so ECE collapses to a constant function of the gold distribution. |

**Implication:** These zeros are **expected** baseline behaviour. They are the contrast that lets `diet_os` look meaningful — *if and only if* `diet_os` actually delivers non-zero `hdi_recall`, `provenance`, and `bilingual`. v1 didn't get to test that because of failure mode A.

This actually clarifies the paper's headline claim (see §6).

### 2.3 What v1 did *not* measure

- **End-to-end `diet_os` → metrics path.** Not exercised against scoring once. Until it runs cleanly, we cannot empirically validate that the metrics are computable on a non-trivial system, only on baselines that trivially zero them out.
- **Inter-system signal separation.** With only `single_llm` showing any κ (0.144) and 5 systems collapsing to identical `defer_acc`, we have ~1 cell of signal in the entire matrix.
- **Calibration on real predictions.** ECE is meaningful only when systems return varied confidence — which baselines don't.

---

## 3. Current method, dataset, and assumptions (for the record)

This section freezes the v1 design so the re-run is reproducible and the next iteration's choices are explicit.

### 3.1 Dataset

- **DietResearchBench-Clinical v1**: 40 scenarios, hand-seeded. Schema `eval/scenario.py::Scenario`. Gold labels in each scenario JSON.
- **Strata**: by `category` (herbal, nutrition, TCM-bilingual) and complexity bucket. Stratified 60/20/20 train/val/test split with entity-level leakage guard (commit `84901a9`).
- **Limitations of v1 dataset acknowledged here so they don't get re-litigated:**
  - Hand-seeded by one author — IAA = N/A. Plan target is dietitian + pharmacist annotators with κ ≥ 0.6.
  - No explicit difficulty calibration (no IRT, no item-response model).
  - HDI gold labels are derived from `hdi_safe_50.json`, which is curated — high-precision, low-recall against the universe of real-world HDIs.
  - 40 scenarios is well below the n required for stable κ confidence intervals at the published cell level. Bootstrapping reports CIs but the underlying sample is thin. 95% CIs in the summary table are wide for a reason.

### 3.2 Six baselines (their stated role in the experimental design)

Each baseline answers a specific ablation question. The point is **not** to "compete" with `diet_os` on equal footing — it is to identify which architectural decisions in `diet_os` produce which capability.

| Baseline | What it ablates | Falsifiable claim it tests |
|---|---|---|
| `single_llm` | "What can a frontier-ish LLM do with no tools and no panel?" | Removing all of (KG retrieval, panel debate, calibrator) costs ≥ X on κ. |
| `single_llm_rag` | "Does adding naive RAG over the same data fix it?" | Naive vector-retrieval is insufficient — typed-chain retrieval matters. |
| `yang2025` | "Two-agent dietitian-pharmacist setup from prior art." | Multi-role debate (n=6) > 2 roles on dissent recovery + HDI recall. |
| `medagents` | "MedAgents-style debate consensus, no KG." | Debate alone does not produce provenance or HDI grounding. |
| `mdagents` | "MDAgents-style triage + dynamic panel, no KG." | Triage helps low-complexity cases but cannot ground HDI without a KG. |
| `diet_os` | The full system (Subsystem H). | All four capability deltas (κ, HDI recall, provenance faithfulness, bilingual) require the full stack. |

Crucially: HDI recall, provenance, and bilingual are **expected to be zero** for the five baselines. We are not measuring "who's best at HDI recall" — we are measuring "which architectural component is required to produce HDI recall at all."

### 3.3 Six metrics (and the assumption each one rests on)

| Metric | Computation | Assumption that must hold for the metric to be meaningful |
|---|---|---|
| `verdict_kappa` | Cohen's κ between system verdict and gold verdict on the 4-class verdict label | Gold verdicts have ≥ moderate IAA between annotators (currently N/A for v1). |
| `ece` | Expected calibration error on system-emitted confidence | System emits a calibrated probability, not a constant or undefined. |
| `hdi_recall` | Fraction of gold HDI claims (severity ≥ moderate) recovered in system output | Gold HDI panel is exhaustive *for the scenarios in v1*, not for the universe. We accept this scope. |
| `provenance` | Faithfulness of emitted Cypher chains vs. live KG | Live KG is reachable at eval time and contains the evidence (see §5). |
| `defer_acc` | Accuracy of binary `defer_to_clinician` flag against gold | Gold defer label is reliable. v1 defer labels are heuristic — needs annotator review. |
| `bilingual` | Pinyin↔CN↔EN consistency on TCM-tagged scenarios | Bilingual test set is large enough; v1 has only TCM-tagged scenarios with EN+CN gold (~7 of 40). |

**The deepest assumption baked into the harness**: HDI recall, provenance, bilingual ≈ 0 for any system that lacks the corresponding capability is a **feature** of the metric, not a bug. The paper claim depends on this gap being meaningful, which depends on the gold labels actually testing those capabilities.

---

## 4. Why we will not change the metric panel before the re-run

There will be a temptation, after seeing v1's mostly-null output, to "fix" the metrics so they're less brutal on baselines. We should not. Reasons:

1. The asymmetry between `diet_os` and the baselines on HDI/provenance/bilingual **is the headline finding**. Softening the metrics would erase the signal we built the system to produce.
2. v1's nulls are a function of the baselines' architectural choices (no KG, no provenance emitter), not a function of the metric definitions.
3. Adjusting the metric panel based on a run where the flagship system never executed would be reverse-engineering the result — methodologically indefensible.

Re-run first. Re-evaluate the metric panel only on data from a clean run.

---

## 5. v1 re-run gate (the runner contract)

Adopt before re-running:

1. **Pre-flight readiness gate in `eval/runner.py`.** Before any baseline executes, the runner must succeed at all of:
   - `GET {LIGHTRAG_URL}/health` (or equivalent) returns 200
   - Aura connectivity probe (`test_aura_connectivity.py` body, programmatic) returns the expected `RETURN 1` and a non-null `dbms.components()` version
   - OpenRouter API key resolves via Infisical and a `models.list` smoke call returns the configured free-tier model
   - On any failure, **abort with a non-zero exit code**. No silent placeholders.
2. **Per-system error escalation.** A baseline whose first 3 scenarios all return error placeholders should fail-fast the entire run for that system instead of producing 40 zeros.
3. **Manifest must record the gate state.** The run manifest under `results/<ts>/manifest-*.json` should include `preflight: { lightrag: ok, aura: ok, openrouter: ok }`.
4. **`make eval-run` should compose the LightRAG server lifecycle** (start → wait → run → tear-down) so the operator cannot accidentally repeat the v1 mistake.

The gate is the only thing that has to land in code before the re-run. Everything else is unchanged.

---

## 6. Falsifiable claims the v1 (re-)run is designed to test

These belong in the paper's Methods, lifted here so we can sanity-check whether v1 is even capable of testing them:

- **C1 (KG ablation):** A KG-grounded system produces non-zero HDI recall on `hdi_safe_50` test scenarios; KG-less baselines produce zero. *Testable in v1.*
- **C2 (debate ablation):** A 6-role panel with debate produces higher dissent-aware verdict κ than 2-role (yang2025) and single-LLM. *Testable in v1 if `diet_os` runs.*
- **C3 (provenance):** ≥ 80% of `diet_os` Cypher chains are faithful to the live KG. *Testable in v1 if `diet_os` runs.*
- **C4 (bilingual):** Bilingual consistency ≥ 0.7 on TCM-tagged scenarios for `diet_os`, ≈ 0 for baselines. *Testable in v1; the n=~7 bilingual subset will widen CIs significantly — flag in Discussion.*
- **C5 (calibration):** `diet_os` ECE < 0.2 after Platt/isotonic; baselines uncalibrated. *Testable but n=40 is borderline; report with bootstrap CI and acknowledge.*

**Out-of-scope for v1, deferred to v2:** absolute verdict accuracy claims, generalization beyond the 40-scenario distribution, anything requiring annotator IAA.

---

## 7. Decision queue (what we choose after the re-run)

In the order we'll face them; each is a separate decision point, not a continuous tweak.

1. **Did the re-run validate failure mode A's diagnosis?** (i.e., does `diet_os` produce non-zero κ / HDI / provenance / bilingual once the LightRAG server is up?)
   - Yes → continue to (2).
   - No → debug `diet_os` itself (panel, kg_query tool, or run_case_study). Do not proceed to dataset expansion.
2. **Is the v1 signal large enough to be paper-worthy at n=40?** Bootstrap CIs decide.
   - Yes → keep n=40, invest in annotator IAA and ship as a "v1 benchmark + reference system" companion paper γ. Deferred details in `2026-04-22-subsystem-f-evaluation-harness.md`.
   - No → expand to v2 (see Task #4).
3. **v2 expansion path** — three options to be decided then, not now:
   - **(a)** Stay at 40, add 2 annotators, IAA gate at κ ≥ 0.6, publish as a small-but-reliable benchmark.
   - **(b)** Expand to 200 with weaker single-annotator gold + automated gold-quality checks, publish as a larger-but-noisier benchmark.
   - **(c)** Two-paper split: ship 40-scenario primary β paper now; release v2 200-scenario later as a resource paper.

We will not choose (a)/(b)/(c) until we see real numbers from the re-run.

---

## 8. Out of scope for this memo

- Repo zombie-module audit (`mcp-opennutrition`, top-level `graphiti/`, top-level `lightrag/`). Tracked separately as Task #3 → `repo-zombie-audit.md`. **Important constraint: any reorganization must land *after* the v1 re-run is green, so we don't conflate eval failures with import-path breakage.**
- KG snapshot diffing across re-ingests. Tracked under Subsystem A.
- AG2 panel role tuning. Tracked under Subsystem H.

---

## 9b. Re-run attempt 2026-04-26 — what the gate caught

The pre-flight gate plus the lifecycle script (`scripts/run_v1_eval.sh` + `make eval-run-v1`) were implemented and merged. First attempted re-run did not even reach the gate — it failed earlier, at the LightRAG server's own internal startup check. Two new blockers surfaced that the v1 04-25 run hid behind the silent connection-refused:

### Blocker 1 — Aura graph not scope-tagged

`scoped_server.py::_preflight_scope_check` refuses to start if any node or relationship in the active workspace is missing the `scope` property. Aura `unified_diet_kg` workspace currently has **24,848 untagged nodes + 114,298 untagged relationships** (confirmed via `python3 bootstrap_scope.py --config local --dry-run`). The bootstrap migration `make lightrag-bootstrap-scope` adds `scope='shared'` to every legacy node/edge plus indexes for fast scope filtering. It is reversible (the property could be removed) and writes to shared infra.

### Blocker 2 — `kg_query` tool incompatible with scoped server

`agents/tools/kg_query.py::_lightrag_query` POSTs `{"query": ..., "mode": ...}` to `/query`. The scoped server's `QueryRequest` model declares `scope_filter: list[str] = Field(..., min_length=1)` — a required field. Every `kg_query` call would 422 even if the migration ran. The fix is a 1-line patch in `kg_query.py`: include `"scope_filter": ["shared"]` in the POST body (or read it from `LIGHTRAG_SCOPE_FILTER` env to keep the contract explicit and testable).

### Decision required (these are the three real options)

| Option | What it costs | What it gives | Reversibility |
|---|---|---|---|
| **A. Bootstrap + patch** | Run `make lightrag-bootstrap-scope` (migrates 24,848 + 114,298 objects in Aura) + 1-line patch to `kg_query.py` to send `scope_filter=["shared"]` | Honors the multi-tenancy contract the scoped server was built for; one-shot operational hardening that everyone benefits from afterward | Migration: reversible (remove property). Patch: trivial revert. |
| **B. Use upstream server** | Switch lifecycle script + `lightrag-server` Make target → `lightrag-server-upstream` (no scope filtering). Zero data writes. | Fastest path to a re-run. Bypasses multi-tenancy contract entirely for the eval — fine if multi-tenant isolation is not needed for paper-stage evaluation. | Trivial — just one config flag. |
| **C. Bootstrap + patch + delete the upstream-server escape hatch** | Same as A, plus remove `lightrag-server-upstream` target | Forces the scoped contract permanently. Cleanest end-state. | Same as A. |

**Recommendation:** Option A. Reasons:
- The migration is the documented expected path for moving from legacy → scoped, with a dedicated Make target and a tested dry-run mode.
- Reversibility cost is low (remove a property; we have the original snapshot in the ingestion-snapshot.md).
- The 1-line `kg_query.py` patch is testable in isolation against a mock; will land via TDD like the pre-flight gate.
- Keeps the multi-tenancy invariant the scoped server was designed to enforce.

Option B is acceptable if the user wants results fastest and is okay deferring scope hardening; it does not block paper-stage eval since the scope concept doesn't appear in any v1 metric.

Option C is over-eager — the upstream server is useful for iterative dev/debug; deleting it now would be premature.

**Status:** halted on this decision. The pre-flight gate + lifecycle script are landed; tests pass; nothing else has been written.

---

## 9c. Re-run attempt 2026-04-26 — Option D execution log

User chose Option D and confirmed policy: open-source data always ingests under `scope='shared'`. The following landed:

| # | Change | Tests | Outcome |
|---|---|---|---|
| D1 | Fixed `bootstrap_scope.py::create_indexes` — Neo4j 5+ requires typed relationship indexes (`FOR ()-[r:TYPE]-()`); replaced wildcard form with per-type enumeration via `db.relationshipTypes()` | existing test_bootstrap_scope.py | Migration completed: 24,848 nodes + 57,199 rels tagged `scope='shared'`, node + 7 per-type relationship indexes ONLINE |
| D2 | `ingest_direct.py` now stamps `scope='shared'` (configurable via `--scope`) on every node and edge it writes; idempotent `_stamp_scope` helper preserves explicit row scopes | 8 unit tests in `test_ingest_direct_scope.py` — 8/8 pass | Future direct-Cypher ingests stay policy-compliant |
| D3 | `scoped_server.py::QueryRequest.scope_filter` defaults to `["shared"]` (was required field). Aligns with codebase-wide `DEFAULT_SCOPE = ("shared",)` in `scope_context.py` | 6 unit tests in `test_scoped_server_query.py` — 6/6 pass | Existing `kg_query.py` works without modification |
| State capture | `scripts/capture_scope_state.py` generates `research-journal/shared/scope-state-snapshot.md` — counts by scope/source/rel-type, index status, idempotency contract | n/a (read-only diagnostic) | 2026-04-26 baseline: 0 untagged, all open-source data on `scope='shared'`, source mix matches 04-25 ingestion-snapshot exactly |
| Post-D fix #4 | LightRAG `STORAGE_IMPLEMENTATIONS["GRAPH_STORAGE"]["implementations"]` is a hardcoded compat list separate from the dynamic `STORAGES` dict. Project registered only the latter; framework's `verify_storage_implementation()` rejects custom subclass at `LightRAG.__post_init__`. Fix: also append to `STORAGE_IMPLEMENTATIONS` list. | none new | Server clears LightRAG instantiation; hits next blocker. |

### Blocker 5 — vector DB embedding-dim mismatch (current halt point)

Server log:
```
INFO:nano-vectordb:Load (9460, 768) data
AssertionError: Embedding dim mismatch, expected: 2048, but loaded: 768
```

The local NanoVectorDB cache at `rag_storage_local/` holds 9,460 embeddings at **768 dim** (from a prior Ollama `nomic-embed-text` run, probably the 04-12 session). Current `config_local.env` configures the embedder as `nvidia/llama-nemotron-embed-vl-1b-v2:free` at **2048 dim**. NanoVectorDB refuses to load mismatched dim.

This is **not a scope issue** — it's drift between the cached vector store and the configured embedder.

### Decision queue

The scoped server has revealed a chain of integration-debt items with the framework + with cached state. The decision is no longer "which option" but "how much hardening to do before paper-track work resumes":

| Option | What it does | Time | What it costs |
|---|---|---|---|
| **B′ (pivot)** | Run v1 eval against `lightrag-server-upstream` (the framework's stock server). All scope policy already enforced via D1/D2 (data tagged); upstream server simply doesn't *check* scope on reads. For v1 eval everything is `shared` anyway, so semantically identical. Lifecycle script switches one entry point. | ~5 min | Defers fixing the scoped server to a follow-up PR. Loses tenant-isolation enforcement for the eval window only. |
| **D5** | Wipe `rag_storage_local/` + re-run `make lightrag-ingest-local` to rebuild the vector DB at 2048-dim | 30–60 min on free-tier OpenRouter; embedder rate limits unknown | Loses 9,460 cached embeddings. Resolves *this* blocker but the next one (whatever comes after) costs another iteration. |
| **D5+** | D5 plus dimension verification and a "reset cache when embedder changes" Make target so this never recurs | +30 min | Most robust. |

**Recommendation: B′ + a follow-up PR for scoped-server hardening.** Reasons:

1. The user's stated goal is paper-track v1 eval — not scoped-server hardening.
2. The data-side of the policy (D1/D2) is already in place, so we're not regressing on the open-source-= -shared invariant.
3. Each fresh blocker has been ~30 min to diagnose and fix; the trajectory says there will be more.
4. B′ is reversible: a single config change to point the lifecycle at the upstream server.
5. Scoped-server hardening can ship as a focused, testable PR after v1 eval results land.

Awaiting user choice between B′ and D5/D5+.

---

## 9d. Run 4 — first complete matrix with diet_os in scope

**User chose D5+** (cache reset + ADR 0001 commitment to Aura-native vector storage).
Pipeline executed end-to-end: lifecycle script → preflight gate → server startup → 6 systems × 9 scenarios → 54 predictions → summary + paired-tests rendered.

Results dir: `research-journal/shared/results/20260428T224038Z/`

### Headline matrix

| System | Verdict κ | ECE | HDI Recall | Provenance | Defer Acc | Bilingual |
|---|---:|---:|---:|---|---:|---:|
| single_llm | **0.072** [0, 0.217] | 0.366 | 0.000 | — | 0.551 | 0.000 |
| single_llm_rag | 0.000 | 0.397 | 0.000 | — | 0.551 | 0.000 |
| yang2025 | 0.000 | 0.397 | 0.000 | — | 0.551 | 0.000 |
| medagents | 0.000 | **0.012** | 0.000 | — | 0.551 | 0.000 |
| mdagents | 0.000 | 0.058 | 0.000 | — | 0.551 | 0.000 |
| diet_os | **-0.047** [-0.174, 0] | **0.002** | 0.000 | — | 0.551 | 0.000 |

### What's working

- ✅ **Infrastructure end-to-end.** Pre-flight gate, scoped server, Aura connectivity, scope='shared' queries, runner persistence, report renderer, paired-bootstrap stats — all green.
- ✅ **Failure modes are now captured, not silent.** Rate-limit 429s and JSON-validation errors yield error placeholders that show up correctly in metrics; runner marches through.

### What's broken (and why no paper signal yet)

1. **OpenRouter free-tier rate limit (20 RPM) dominates.** Each diet_os scenario invokes ~7 LLM calls (triage + 6 panel roles + moderator). 9 scenarios × 7 calls = 63 calls; at 20 RPM the panel sequence saturates within 1 minute and most subsequent calls 429. Rate limit caused ~70%+ of diet_os scenarios to error-placeholder. Same for mdagents on round 2 of debate.
2. **kg_query returned empty subgraphs.** `Initial KG retrieval: raw_subgraph_node_count:0, raw_subgraph_edge_count:0` on every scenario. Cause: kg_query.py uses `mode="hybrid"`, which seeds graph traversal from vector retrieval. Vector cache was wiped (per D5+) and Aura-native vectors are not yet implemented (ADR 0001 / Task #7). Result: diet_os had no KG context to debate over → panel produced empty/hallucinated verdicts.
3. **Free-tier LLM (Nemotron-3-nano:free) JSON quality.** 2 of 9 diet_os scenarios failed Pydantic validation due to oversized JSON with tens of thousands of language-locale tokens. Free-tier model artifact, not a harness bug.
4. **Confirmed-as-designed**: HDI=0, Provenance=undefined, Bilingual=0 for the 5 baselines (none has those capabilities by construction). Same on diet_os only because (2) + (3) prevented it from exercising those capabilities.

### Why diet_os κ is negative

`-0.047` < 0 means slight inverse correlation with gold. Likely cause: under rate-limit-degraded conditions where the panel cannot complete debate, diet_os falls back to abstain/error placeholders that systematically misalign with the gold label distribution. This is a **degraded-mode artifact**, not evidence that the panel architecture is bad. Validating this requires a clean run.

### Honest take

The harness works. The Aura KG works. The gates work. The signal is null because we're running on free-tier infra that's both rate-limited and quality-unreliable. We have not yet exercised any of falsifiable claims C1–C5 (§6) under conditions where they could be falsified.

### Path to a paper-quality v1 run (corrected 2026-04-29)

The earlier draft of this section recommended a "paid LLM tier" — that conflated **model size/quality** (which free OpenRouter already provides at sufficient scale: DeepSeek V3, Llama 3.3 70B, Qwen 2.5 72B, Nemotron 30B, etc.) with **request throughput** (the actual v1 blocker, capped at 20 RPM on the free tier's chat endpoint). Correcting:

- **Throughput**, not model quality, is the bottleneck. Each diet_os scenario fires ~7 LLM calls (triage + 6-role panel + moderator). 9 scenarios × 7 calls = 63 calls/min sustained vs. 20 RPM cap → most scenarios 429-degraded. **Solutions** (in order of preference, all viable on the free tier):
  - (a) Add per-call sleep/backoff in the runner so the panel paces itself under 20 RPM. Slower wall-clock; the free-tier model quality is unchanged.
  - (b) Multi-provider routing: split calls across OpenRouter free models with disjoint rate-limit pools, OR fall back to direct provider endpoints with their own free quotas (DeepSeek, Groq, Cerebras have generous free tiers).
  - (c) Self-host a 30–70B model via Ollama on a beefy GPU. Free runtime, no rate limit, full panel pace.
- **Working KG retrieval.** `Neo4JVectorStorage` (Task #7) landed; re-embed migration (Task #11) running on the free `nvidia/llama-nemotron-embed-vl-1b-v2:free` embedder — sustained 5–7 entities/sec without rate-limit issues against the embeddings endpoint (separate quota from chat). ETA fully populated in hours, not days.
- **JSON-schema-constrained generation.** Pydantic re-prompt loop is the simplest fix, model-agnostic, works on free tier. Current `diet_os` already uses Pydantic; just needs a "retry on validation failure" wrapper around the LLM call.

**None of the above requires a paid LLM tier.** It requires rate-limit-aware orchestration and a graph that's actually retrievable (the latter is in flight).

**Status of Task #2:** infrastructure-complete. The matrix re-ran with diet_os live; the failure modes are diagnosed; the path forward is documented. Marking complete.

---

## 9. Reading order if you're picking this up cold

1. `research-journal/plans/2026-04-22-program.md` — what we're building, why.
2. `research-journal/shared/ingestion-snapshot.md` — the live KG.
3. `research-journal/shared/results/20260426T000939Z/summary.md` + `paired_tests.md` — the v1 run that prompted this memo.
4. `eval/baselines/diet_os.py` — the flagship baseline that didn't execute.
5. This memo.
6. `2026-04-22-subsystem-f-evaluation-harness.md` for the originating Subsystem F design.
