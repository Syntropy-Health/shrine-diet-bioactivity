# Grounded but Not Faithful: Provenance Integrity as a Safety Prerequisite in Multi-Agent LLM Systems for Supplement–Drug Reasoning

# Abstract

Knowledge-graph grounding is widely proposed to make multi-agent clinical
LLM systems trustworthy: if every claim cites a retrieved evidence chain,
the reasoning becomes auditable. We stress-test this premise on
supplement–drug safety reasoning and find that grounding can manufacture a
new failure mode rather than remove one. We build `diet_os`, a 6-role
multi-agent system over a unified 5M-edge diet/herb/TCM knowledge graph
served through a streamable-HTTP MCP gateway, instrumented so that every
tool call emits a runtime trace span and every agent claim carries explicit
chain citations. Running the full DietResearchBench-Clinical matrix (40
scenarios × 7 systems) on a free-tier open-weight model (gpt-oss-120b), we
audit each citation against the evidence actually retrieved. We report three
findings. **(1) Fabricated provenance:** `diet_os` cites at least one
non-existent evidence chain in 40% of predictions; its citation faithfulness
is 0.66 (mean over citing predictions; 30% of individual citations are
unfaithful), dropping to 0.27 when triage is also model-driven — including
agents that cite specific chain indices when *zero* chains were retrieved. These failures are invisible to the verdict-agreement
and safety-recall metrics by which such systems are usually judged. **(2) A
verdict-agreement confound:** the architectural κ "lift" reported for
KG-grounded panels over non-grounded baselines vanishes under a stronger
base model — every baseline reaches κ 0.20–0.35, erasing the gap. **(3) A
safety-recall confound:** the system's high herb–drug-interaction recall
traces to a gold-derived triage substitute, not to retrieval — an ablation
that removes it more than halves recall even when real KG chains are
supplied. We argue that for clinically deployed grounded LLMs,
citation-faithfulness must be measured and enforced as a first-class safety
property, and we release the auditing instrumentation and benchmark to
enable it.

## 1. Introduction

Supplement–drug interactions are a high-stakes clinical blind spot: patients
combine herbs and supplements with prescription drugs, and the supporting
evidence is scattered across heterogeneous resources (Duke, FooDB, CMAUP,
SymMap v2.0, HERB 2.0, HDI-Safe-50). Multi-agent LLM systems are an
attractive interface for this setting — a dietitian, a pharmacologist, a TCM
practitioner, a safety reviewer, and a deferral authority can each contribute
a different prior — and a now-common design move is to *ground* such panels
on a knowledge graph (KG): agents retrieve typed evidence chains and cite
them, so that recommendations are not free-floating model assertions but
auditable, source-linked claims. The implicit safety argument is that
citation makes the system trustworthy.

We test that argument directly. We build `diet_os`, a 6-role multi-agent
system over a unified 5M-edge diet/herb/TCM KG served through a
streamable-HTTP MCP gateway, and we make its provenance *checkable*: every
tool call emits a runtime trace span, and every agent verdict records the
indices of the KG chains it claims to cite. This instrumentation lets us do
something the verdict-level metrics in prior work cannot — open each
recommendation and ask whether the cited evidence was actually retrieved.

On the full DietResearchBench-Clinical matrix (40 scenarios × 7 systems) run
on a free-tier open-weight model, the audit is unflattering, and that is the
point. `diet_os` cites a non-existent evidence chain in 40% of predictions;
agents routinely cite specific chain indices when no chains were retrieved at
all. Worse, the apparent advantages that would normally justify the
architecture do not survive scrutiny: the verdict-agreement "lift" over
non-grounded baselines disappears under a stronger base model, and the
herb–drug-interaction recall traces to a gold-derived triage substitute
rather than to the KG.

We make three contributions:

1. **Citation-faithfulness as a measurable safety property.** We formalize
   two metrics — citation faithfulness (fraction of cited indices that
   resolve to a retrieved chain) and fabrication rate (fraction of
   predictions citing ≥1 non-existent chain) — and the auditing
   instrumentation (MCP-gateway trace spans + per-claim chain indices) that
   makes them computable. The metrics expose fabrication that
   verdict-agreement and safety-recall scores hide.

2. **An empirical audit of a grounded clinical panel.** On
   DietResearchBench-Clinical, `diet_os` achieves 66% citation faithfulness
   with a 40% fabrication rate (27% / 35% under model-driven triage), while
   the five non-grounded baselines make no citations and so cannot fabricate
   — the grounding apparatus *creates* the hallucinated-provenance surface.

3. **Two confounds in multi-agent-KG evaluation.** We show, by re-running a
   prior KG-grounded vs. non-grounded comparison, that (a) the verdict-κ
   "architectural lift" is an artifact of a weak base model, and (b) the
   herb–drug-interaction recall is an artifact of a gold-derived triage
   substitute, isolated by ablation. Both cautionary results bear directly on
   how grounded medical-LLM systems should be benchmarked.

We release the benchmark, the auditing instrumentation, and the full result
matrix. Our claim is not that knowledge grounding is unhelpful, but that
*unverified* grounding is unsafe: for clinical deployment, citation
faithfulness must be measured and enforced, not assumed.

## 2. Related Work

### Multi-agent clinical reasoning

MedAgents [@medagents2024] frames zero-shot medical reasoning as a
multi-role panel; MDAgents [@mdagents2024] adds adaptive routing
between solo and multi-disciplinary configurations. CAMP [@camp2026]
adds case-adaptive panel composition with three-valued voting on
MIMIC-IV, the closest methodological peer to our verdict-κ + abstain
framing, but operates without KG-grounded retrieval. Yang et al.
[@yang2025], the JMIR baseline of behavioral-science-informed agentic
workflows, propose a two-agent design (barrier-identification +
strategy-execution) for personalized-nutrition adherence coaching,
which we re-implement as our third behavioral baseline. NutriOrion
[@nutriorion2026] forward-extends the JMIR Yang design with a
four-specialist panel, validating that the behavioral-nutrition
multi-agent design space remains active. We extend MedAgents, MDAgents,
and Yang with Layer-B/C role-priored KG retrieval; CAMP and NutriOrion
are positioning peers, not re-implemented baselines. Wu et al. [@wu2025] report
single-GP performance comparable to a multi-disciplinary debate panel
on medication-conflict resolution; §7.2 places that finding on an axis
orthogonal to ours.

### KG-grounded LLM clinical reasoning

AMG-RAG [@amgrag2025] constructs a medical knowledge graph agentically and
reports F1 74.1 % on MedQA; MedRAG [@medrag2025] fuses a four-tier
hierarchical diagnostic KG with EHR retrieval; KG-SMILE [@kgsmile2025] adds
explainability to KG-RAG. Our pre-fetched typed-Cypher retrieval is
offline-constructed and queried deterministically through the MCP gateway
(§3.1), so live KG construction is orthogonal rather than competing.
KG4Diagnosis [@kg4diagnosis2025] (AAAI Bridge on AI for Medicine, PMLR 281,
2025) couples hierarchical multi-agent diagnosis with KG augmentation; we share the KG-grounded
multi-agent thesis but target diet/herb evidence rather than diagnostic
reasoning. Across this line of work, evaluation reports task accuracy, F1, or
extraction precision — measures of *whether the answer is right* — but not
whether the evidence a grounded agent *cites* was actually retrieved. We treat
that gap, citation faithfulness, as a first-class safety property (§3.4, §6.3)
rather than assuming it from the presence of a retrieval step.

### TCM multi-agent and KG systems

The closest direct competitor is JingFang [@jingfang2025], a multi-agent TCM
consultation system with syndrome differentiation and dual-stage retrieval.
JingFang is prescription-only, has no Western-nutrition coverage, lacks an
English/bilingual interface, and exposes no KG query layer. OpenTCM
[@opentcm2025] applies GraphRAG over a 48K-entity TCM KG (P = 98.55 % on
classical-text extraction) but is TCM-only; our 5M-edge KG is a superset
combining Western nutrition with TCM. AgentClinic [@agentclinic2024]
introduced multimodal sequential clinical decision benchmarks; we operate in
the static-question evaluation paradigm.

### Citation faithfulness, attribution, and hallucination-despite-retrieval

A parallel literature studies whether grounded generations are actually
supported by their sources. Attribution-evaluation work formalizes the
question: ALCE [@gao2023alce] benchmarks citation precision and recall for
LLM-generated text, Attributed QA [@bohnet2022attributedqa] frames answers as
(claim, source-pointer) pairs scored by attributability, and a human study of
commercial generative search engines [@liu2023verifiability] finds only ~51.5%
of generated sentences are fully supported by their citations — establishing
that an inline-citation interface does not guarantee verifiable attribution.
On the RAG side, faithfulness is now a standard evaluation axis (RAGAS
[@es2023ragas]) and dedicated corpora document hallucination *despite*
retrieved context: RAGTruth [@niu2024ragtruth] provides ~18K
LLM responses with word-level hallucination annotations in RAG settings,
FActScore [@min2023factscore]
measures atomic factual precision against a source, and "lost-in-the-middle"
effects [@liu2023lostmiddle] give a mechanism by which models fail to use
evidence that is present in the prompt. In medicine the stakes are explicit:
Med-HALT [@pal2023medhalt] benchmarks medical-domain hallucination, broad
surveys catalogue it [@zhang2023sirens], and clinical reviews flag fabricated
diagnoses and recommendations as a patient-safety concern [@thirunavukarasu2023llmmedicine].
Multi-agent debate has been proposed as a factuality mitigation
[@du2024debate; @liang2024mad], though agents sharing one base model can
reinforce rather than correct a shared error.

Our work differs in three ways. First, prior attribution evaluation targets
single-model generative search or QA in the general domain; we measure
attribution inside a *multi-agent KG-grounded clinical panel*, where each role
agent emits its own citations. Second, where ALCE-style metrics ask whether a
cited source *semantically supports* a claim, we measure a stricter, more basic
precondition — whether the cited chain index *resolves to evidence that was
retrieved at all* — and surface the limiting failure of citing specific indices
when retrieval returned nothing (§6.3). Third, we show this fabrication is a
hazard the grounding apparatus *introduces*: the non-grounded baselines emit no
citations and cannot fabricate. To our knowledge no prior work measures
citation faithfulness in a multi-agent KG-grounded system for supplement–drug
safety specifically.

### Existing benchmarks

TCM-Eval [@tcmeval2025] and TCM-5CEval [@tcm5ceval2025] cover TCM
knowledge questions only, with no clinical-deliberation evaluation.
MedQA [@medqa2021], MedMCQA [@medmcqa2022], and AgentClinic
[@agentclinic2024] are general or multimodal benchmarks without diet or
herb content. DietResearchBench-Clinical (§4) is the first public
benchmark covering herb-drug interaction reasoning, diet-bioactive
inference, and TCM-syndrome / Western-nutrition crosswalk in one set.

## 3. System: diet_os

`diet_os` is a six-role multi-agent pipeline implemented in AG2 [@ag2v0_12]
over a 5M-edge unified diet/herb/TCM knowledge graph served by a
streamable-HTTP MCP gateway. We describe it not as a system we advocate but as
the instrument through which the audit of §6 is performed: its defining
property for this paper is that every retrieval and every claim is made
*checkable*. Figure 1 shows the end-to-end flow.

![Figure 1. diet_os pipeline: triage extracts a PICO-typed `ResearchQuestion`; a deterministic retrieval plan dispatches typed MCP traversals into a chain bundle; six role agents deliberate over the bundle in a round-robin GroupChat; the moderator summarizes, the calibrator scores composite confidence, and synthesis emits a `ResearchSynthesis` artifact carrying per-claim chain citations.](figures/architecture-diagram.png)

### 3.1 Triage and pre-fetched retrieval

Triage converts the user's free-text question into a typed `ResearchQuestion`
(PICO-shaped: population, intervention, comparator, outcome, language hints)
plus a `Triage` record carrying complexity, suspected red flags, and language
tags. In the canonical `diet_os` configuration this triage is a deterministic
gold-derived substitute (§5.4); the `diet_os_llm_triage` ablation replaces it
with a base-model call.

A deterministic retrieval plan then dispatches typed MCP traversals *before*
any panel agent runs, keyed on the question's intent: a herb intervention
resolves the canonical Latin binomial from the question text and calls
`kg_herb_to_symptoms`; a compound intervention calls `kg_compound_to_targets`;
a herb–drug interaction calls `kg_hdi_check` and, because that lookup is sparse,
the herb's mechanism profile via `kg_herb_to_symptoms`; nutrition and TCM
intents call the corresponding traversals. Results fuse into a list of
`ProvenanceChain`s with edge-level `source_id` attribution. Pre-fetching is a
deliberate departure from LLM-driven tool calls: under free-tier inference,
models frequently *describe* tool use in prose while emitting no actual
`tool_calls`, so pre-fetching guarantees the panel receives whatever evidence
the KG can supply — including, importantly, an *empty* bundle when the KG does
not cover the entity, which is the condition under which fabrication arises
(§6.3).

### 3.2 Role-priored panel

The panel is an AG2 `GroupChat` round-robin (`max_round = len(roles) + 2`,
enough for each selected role to emit one verdict plus a moderator turn).
Triage complexity selects the role subset: low-complexity questions convene a
Dietitian + Safety Reviewer pair, higher-complexity questions the full
six-role panel (Dietitian, Pharmacologist, TCM Practitioner, Clinical Research
Scientist, Safety Reviewer, Defer-to-Clinician). Each role carries a
real-world information prior — the Pharmacologist reasons over
compound→target chains, the TCM Practitioner over herb→symptom chains, the
Safety Reviewer over interaction lookups — but, because the base model emits
structured `RoleVerdict` output and the provider rejects simultaneous tools +
structured output, the agents do not call tools live; they reason over the
pre-fetched bundle. Each role emits a `RoleVerdict` ∈ {prefer, caution, reject,
abstain} with `support[]`, `concerns[]`, and — central to this paper — a
`cited_chains[]` list of indices into the bundle.

### 3.3 Moderator, calibrator, synthesis

The moderator concatenates the role verdicts into a textual summary plus
dissent list. The calibrator computes composite confidence as a weighted
product of evidence-tier strength, HDI risk, and question-fit, each in [0, 1].
The terminal artifact is a `ResearchSynthesis` Pydantic model carrying the
panel verdicts, `candidate_chains` (the retrieved bundle), `confidence`,
`components`, a `defer_to_clinician` boolean, and the runtime trace-span IDs of
every tool call. This single object is scored by all benchmark metrics,
including the two faithfulness metrics of §3.4.

### 3.4 Provenance instrumentation and the faithfulness metrics

Two design choices make `diet_os`'s reasoning auditable, and the audit is the
contribution. First, the MCP gateway wraps every tool handler in a runtime
trace span and returns the span ID with the result, so each retrieval has a
stable, externally-resolvable handle recorded on the prediction
(`bt_span_ids`). Second, each `RoleVerdict.cited_chains` entry is an integer
index into the prediction's `candidate_chains`, so a citation is a precise,
checkable reference rather than free text.

Together these let us define two metrics computed directly from the committed
predictions. **Citation faithfulness** is the fraction of cited indices `i`
that satisfy `0 ≤ i < len(candidate_chains)` — i.e. that resolve to a chain
actually retrieved (micro-averaged over citations; the headline reports the
per-prediction mean). **Fabrication rate** is the fraction of predictions in
which at least one cited index is out of range, including the limiting case of
citing any index when `candidate_chains` is empty. The metric is structural,
not semantic: it checks that cited evidence *exists*, not that it *supports the
attached claim* (§8). A non-grounded baseline that emits no citations has
undefined faithfulness and a fabrication rate of zero — fabrication is a hazard
that only the act of grounding introduces.

## 4. Benchmark: DietResearchBench-Clinical v1

DietResearchBench-Clinical v1 is a 40-scenario benchmark across four clinical
categories: **herbal_single_symptom** (10; e.g. turmeric × osteoarthritis,
valerian × insomnia), **nutrition** (10; e.g. vitamin D, omega-3,
Mediterranean pattern), **multi_drug_hdi** (10; from the HDI-Safe-50 panel,
e.g. SJW × warfarin, grapefruit × simvastatin), and **tcm_bilingual** (10;
herb-name and modern-symptom bilingual lookups via SymMap v2.0).

Each scenario carries a `GoldStandard` record:
`expected_complexity` ∈ {low, moderate, high}, `expected_panel_verdict` ∈
{prefer, caution, reject, abstain}, `expected_evidence_tier` ∈
{clinical_trial, observational, mechanistic, unknown}, `expected_min_chains`,
`expected_defer`, `expected_red_flags` (mechanism classes such as
`serotonergic_interaction`, `coagulation`), `expected_hdi_severity`, and
`languages`.

Six metrics score every prediction:
**Verdict κ** (Cohen's quadratic-weighted κ);
**ECE** (10-bin equal-width on `confidence`);
**HDI Recall** (severe-or-moderate gold HDI claims surfaced via
`kg_hdi_check`); **Provenance** (source-attribution v1: fraction of
`cited_chains` whose edges carry a `source_id` prefix in
`{cmaup:, duke:, herb2:, symmap:, hdi-safe-50:}`); **Defer Accuracy**
(binary agreement on `defer_to_clinician`); **Bilingual Coverage**
(CJK-character detection over `candidate_chains` on `tcm_bilingual`).
Means use 95 % bootstrap CIs (1000 iters); paired comparisons use
paired-bootstrap with Bonferroni correction over five `diet_os`-vs-baseline
contrasts (α' = 0.01).

Scenarios are split 60/20/20 with seed 42 (`splits_seed42.json`). The
entity-level leakage guard is enforced with one documented v1 exemption:
`case-nutrition-008-probiotics-ibs` shares the *probiotics* entity across
train and test, an unavoidable artefact at N = 40. The companion v2 release
(n = 200, two-annotator IAA target κ ≥ 0.6 on verdict and κ ≥ 0.7 on binary
HDI) closes this gap [@v2benchmark2026].

## 5. Experimental setup

**LLM.** All seven systems share one free-tier open-weight base model,
gpt-oss-120b (OpenAI open-weight 120B MoE), served by Cerebras Inference at
`reasoning_effort = low`, temperature 0, seed 42. Holding the base model
constant across systems isolates architectural differences; running on a
free-tier model keeps the constrained-inference framing while — unlike the
30B model used in the earlier comparison of §6.2 — being capable enough that
the non-grounded baselines are not artificially near zero. Free-tier rate
limits (5 requests/min, 150/hr, 1M tokens/day) are respected by a
sliding-window client-side limiter; the full 40 × 7 matrix runs in ~5.5 h.

**Orchestration.** AG2 v0.12.1 (the AG2AI Apache-2.0 fork) with a `GroupChat`
round-robin and Pydantic-typed messages. Panel agents emit structured
`RoleVerdict` output and therefore do not register live MCP tools — Cerebras
rejects simultaneous `tools` + `response_format`, and the pre-fetch design
(§3.1) supplies retrieval before deliberation regardless — so retrieval is
fully pre-fetched and the agents' role of *citing* it is what the audit
measures.

**Knowledge graph.** Neo4j AuraDB hosting `unified_diet_kg` (166K nodes,
~5M relationships) ingested from Duke phytochemical, FooDB, CMAUP, SymMap
v2.0, HERB 2.0, HDI-Safe-50, and OpenNutrition. The deployed graph resolves
herbs primarily by Latin binomial; coverage is sparse for foods, nutrients,
TCM terms, and direct interaction pairs (§6.5).

**MCP gateway.** Streamable-HTTP at `kg-mcp-test.up.railway.app/mcp` exposing
typed traversal + lookup tools across three layers (Layer A `kg_query`;
Layer B six typed traversals; Layer C `kg_hdi_check`, `kg_bilingual_term`,
`kg_node_neighborhood`). Every tool invocation is wrapped in a runtime trace
span whose ID is returned to the caller (§3.4), giving each retrieval a stable
provenance handle. The session is singleton-per-process across the matrix.

**Baselines.** Five external baselines plus `diet_os` and its triage ablation
share base model, KG, and gateway: `single_llm` (no tools), `single_llm_rag`
(naïve semantic-search RAG), `yang2025` (two-agent
barrier-identification + strategy-execution) [@yang2025],
`medagents` [@medagents2024], `mdagents` [@mdagents2024], **`diet_os`** (this
work; deterministic gold-triage substitute, §5.4), and **`diet_os_llm_triage`**
(the triage ablation replacing the deterministic substitute with a base-model
call). We report the full N = 40 matrix across all seven systems.

**Cost and latency.** Per-role token usage and latency are captured by a
`cost_tracker` decorator and reported in the companion code release and
Appendix A.2; free-tier rate-limit pacing dominates wall-clock.

### 5.4 The gold-triage substitute

In its canonical configuration `diet_os` does not run the triage stage with
the base model; it substitutes a deterministic `Triage` derived from the
scenario's gold metadata — `expected_complexity` selects the panel size and
`expected_red_flags` are injected as the suspected red flags. This is a
disclosed evaluation simplification: free-tier models emit unreliable
structured triage output, so the substitute removes triage noise to isolate
downstream behaviour. It also imports gold-derived safety signal, which is
precisely why the herb–drug-interaction recall must be read with the ablation
of §6.4 rather than at face value. The `diet_os_llm_triage` system is the
ablation that removes the substitute, running triage with the base model
instead; comparing the two isolates how much of `diet_os`'s safety behaviour
is the substitute rather than the retrieval.

## 6. Results

We report the full N = 40 × 7-system matrix run on the free-tier open-weight
model gpt-oss-120b (reasoning_effort = low; §5). All values are mean
[95% bootstrap CI, B = 10 000]. The headline matrix, paired tests, per-category
breakdown, and reliability diagram are bundled as `summary.md`,
`paired_tests.md`, `category_breakdown_verdict_kappa.md`, and
`reliability_diagram.png`. Two columns — **Cite-Faith** (citation faithfulness)
and **Fabricate** (fabrication rate) — are the audit instruments introduced in
§3 and are the focus of this paper.

### 6.1 Headline matrix

| System | Verdict κ | ECE | HDI Recall | Defer Acc | Cite-Faith | Fabricate |
| --- | --- | --- | --- | --- | --- | --- |
| single_llm | 0.267 | 0.190 | 0.000 | 0.550 | — | 0.000 |
| single_llm_rag | 0.267 | 0.190 | 0.000 | 0.550 | — | 0.000 |
| yang2025 | 0.297 | 0.220 | 0.000 | 0.550 | — | 0.000 |
| medagents | 0.345 | 0.469 | 0.000 | 0.550 | — | 0.000 |
| mdagents | 0.203 | 0.346 | 0.142 | 0.625 | — | 0.000 |
| **diet_os** | 0.303 | 0.556 | 1.000 | 0.749 | **0.657** | **0.400** |
| diet_os_llm_triage | 0.217 | 0.456 | 0.429 | 0.625 | **0.269** | **0.350** |

The only systems that can fabricate are the two that cite: the five
non-grounded baselines emit no chain citations (Cite-Faith undefined,
Fabricate 0.000) because they have no retrieval to cite. The grounding
apparatus is what creates the citation surface — and, as the next subsections
show, the fabrication surface. The headline that a reader would normally take
from this table — `diet_os` posts the top HDI Recall (1.000) and a respectable
mid-pack κ — is exactly the headline the audit columns undercut.

### 6.2 The verdict-agreement "lift" is a base-model artifact

The motivating claim for KG-grounded panels is a verdict-agreement lift over
non-grounded baselines. On a weak base model that lift is real; under a
stronger one it disappears. Re-running the identical 7-system comparison
across two free-tier base models:

| | weak base (Nemotron-30B) | strong base (gpt-oss-120b) |
| --- | --- | --- |
| diet_os Verdict κ | 0.258 | 0.303 |
| best non-grounded baseline κ | 0.056 (single_llm) | 0.345 (medagents) |
| diet_os lead over best baseline | **+0.202** | **−0.042** |

On Nemotron-30B, `diet_os` leads the strongest baseline by +0.202 κ; on
gpt-oss-120b every baseline reaches κ 0.20–0.35 and the gap inverts
(`medagents` 0.345 > `diet_os` 0.303). The grounding does not get worse — the
baselines get better, because a capable base model already encodes much of the
verdict-relevant prior the KG was supplying. A KG-vs-no-KG κ comparison is
therefore only informative relative to a stated base-model capability; reported
in isolation it measures the base model, not the architecture.

### 6.3 Citation faithfulness: grounded panels fabricate provenance

Because every agent verdict records the indices of the chains it cites and the
retrieval executor records the chains actually returned, we can check each
citation directly. A citation is *faithful* iff its index `i` satisfies
`0 ≤ i < len(candidate_chains)`; otherwise it is *fabricated* — the agent
claims provenance for evidence that was never retrieved (§3.4).

`diet_os` achieves citation faithfulness 0.657 [0.262, 0.858] with a
fabrication rate of 0.400 [0.250, 0.550]: in 40% of predictions at least one
agent cites a chain that does not exist, and a third of all citations are
unfaithful. Under model-driven triage (`diet_os_llm_triage`) faithfulness
falls to 0.269 and fabrication to 0.350. The starkest pattern is citation
*without retrieval*: in 13/40 `diet_os` scenarios the retrieval returned zero
chains, yet agents still emitted specific chain indices. In
`case-hdi-005-ginkgo-aspirin` (candidate_chains = 0) the Pharmacologist cites
chains `[101, 112]` and the TCM Practitioner cites `[1, 2, 3]` — five
references into an empty evidence set (full trace, with runtime span IDs, in
§A.3).

These failures are invisible to the metrics by which such systems are usually
judged. The same `diet_os` predictions that fabricate at 40% post the
matrix-best HDI Recall (1.000) and a competitive κ (0.303): verdict-level
scores certify the *answer* and say nothing about whether the *evidence trail
behind it is real*. A clinician auditing a `diet_os` recommendation by
following its citations would, two times in five, be led to a chain that was
never retrieved.

### 6.4 The herb–drug-interaction recall is a triage artifact, not retrieval

`diet_os`'s headline safety number — HDI Recall 1.000 on severe interactions —
does not come from the knowledge graph. HDI Recall counts a severe-HDI scenario
as caught when the panel returns a `reject` verdict or sets
`defer_to_clinician`. The deferral is driven by red-flag tokens injected
through the deterministic gold-triage substitute (§5.4), not by retrieved
evidence. Two observations isolate this:

1. **Deferral is independent of retrieval.** `diet_os` flags severe-HDI
   scenarios identically whether the panel received 20 KG chains or zero — the
   defer flag fires from the injected red flags either way.

2. **Removing the gold substitute halves recall, even with KG chains.** We
   re-ran the 10 herb–drug-interaction scenarios after wiring the
   interaction-check intent to a mechanism-traversal tool that *does* return
   evidence (e.g. `Hypericum perforatum` → 20 chains). With real chains in
   hand, `diet_os` (gold triage) catches 7/7 severe cases, but
   `diet_os_llm_triage` (model triage, no injected red flags) catches only 3/7
   — the supplied KG evidence does not recover the safety signal. The herb's
   pharmacological profile is not interaction-specific evidence; the recall was
   the gold substitute all along.

The corollary is a benchmarking caution: a KG-grounded system that imports gold
red flags through its triage stage will show a safety-recall advantage that an
ablation, not a baseline comparison, is needed to detect.

### 6.5 Where grounding does work, and why coverage is the real limit

The audit is not an argument against grounding — it is an argument for checking
it. Where the KG returns evidence, agents reason from it correctly and cite it
faithfully. In `case-hdi-010-yohimbe-clonidine` (candidate_chains = 10) all
three speaking roles cite chain `[1]`, and the Pharmacologist's note reasons
explicitly from the retrieved adrenergic-signalling chain to the
clonidine-antagonism mechanism (§A.3). The working cases share one property:
the KG actually covers the entity. Only 10/40 `diet_os` predictions carry any
real chains (6 herbal, 4 interaction), because the deployed graph resolves
herbs by Latin binomial and is sparse for foods, nutrients, TCM terms, and
direct interaction pairs. Faithful grounding is achievable here — the yohimbe
and ginger (20-chain) cases show it — but only to the extent the graph is
populated and the retrieval is verified. The combination of sparse coverage and
unchecked citation is what produces the 40% fabrication rate: when retrieval
returns nothing, an instructed-to-cite agent invents a reference rather than
abstaining.

## 7. Discussion

### 7.1 Fabricated provenance is a distinct clinical risk

A wrong verdict and a fabricated citation are different failures with
different clinical consequences. A wrong verdict can be caught by a
disagreeing clinician; a fabricated citation actively misleads the audit that
is supposed to catch wrong verdicts. The entire value proposition of grounding
— "don't trust the model, trust the cited evidence" — inverts when 40% of
predictions cite evidence that was never retrieved. A clinician who follows a
`diet_os` citation to verify a supplement–drug claim is, two times in five,
sent to a chain that does not exist; the citation manufactures false
confidence precisely where the system was meant to earn real confidence. This
is why we argue citation faithfulness belongs with sensitivity and calibration
as a first-class safety metric for grounded clinical LLMs, rather than being
assumed from the presence of a retrieval step.

### 7.2 Why grounding manufactures the failure

The fabrication is structural, not incidental. The five non-grounded baselines
cannot fabricate citations because they make none (§6.1); fabrication appears
only once the architecture instructs agents to cite. Two ingredients combine.
First, the agents are prompted to ground their claims in retrieved chains, an
instruction they satisfy syntactically (emitting indices) even when there is
nothing to ground in. Second, the deployed KG is sparse — only 10/40 scenarios
return any chain — so the "cite your evidence" instruction is frequently issued
against an empty evidence set. An instructed-to-cite agent facing no evidence
invents an index rather than abstaining. The fix is therefore not "more
prompting to cite" but the opposite: constrain citations to the retrieved set
and require abstention-with-disclosure when it is empty (§7.4).

### 7.3 Implications for benchmarking grounded medical LLMs

Our two confounds (§6.2, §6.4) generalize beyond `diet_os`. A KG-vs-no-KG
verdict-agreement comparison reported on a single weak base model will
overstate the architecture's contribution, because a stronger base model
closes the gap (the lift inverted from +0.202 to −0.042 κ here). And a
multi-agent system that imports gold-derived red flags through a triage or
preprocessing stage will show a safety-recall advantage attributable to the
substitute, not the retrieval — detectable only by ablating the substitute,
not by comparing against external baselines that lack it. Both patterns are
common in the multi-agent-medical-KG literature; both inflate apparent
architectural gains. We recommend that grounded-LLM evaluations report
base-model sensitivity and substitute ablations as standard, alongside
faithfulness.

### 7.4 Toward faithful grounding

The instrumentation that exposed the problem also points at the remedy.
Because the retrieval executor already records the exact chain set returned for
each scenario, citation faithfulness can be *enforced* at decode or
post-process time: reject or strip any cited index outside the retrieved range,
and surface an explicit "no KG evidence retrieved" state instead of allowing
free-form citation against an empty set. Pairing this with denser coverage —
the working cases (yohimbe, ginger) show faithful grounding is achievable where
the graph is populated — and with curated interaction data for the herb–drug
setting specifically, is the path from an auditable-in-principle system to an
auditable-in-fact one. We frame these as deployment prerequisites rather than
future niceties: for a clinical supplement-safety tool, an unenforced citation
channel is a liability, not a feature.

# 8. Limitations

**Scale and single run.** The benchmark is n = 40 with a single-author gold
standard, and the matrix is a single seed at temperature 0; the bootstrap CIs
on the faithfulness columns are correspondingly wide (e.g. `diet_os`
Cite-Faith 0.657 [0.262, 0.858]). The fabrication *direction* is robust — it is
a structural property of an instructed-to-cite agent facing empty retrieval,
and the most damning cases (citation into an empty chain set) are
deterministic, not statistical — but the point estimates should be read as
indicative, not precise. A larger benchmark with multi-annotator agreement
(companion v2, n = 200) and multiple seeds is needed to tighten them.

**The faithfulness metric is structural, not semantic.** Our metric verifies
that a cited index points to a chain that was *retrieved*; it does not verify
that the retrieved chain *supports the claim it is attached to*. A citation can
be faithful in our sense (index in range) yet semantically irrelevant. We
therefore report faithfulness as a necessary, not sufficient, condition for
trustworthy grounding; semantic citation-support checking is future work.

**Single base model.** All results are on gpt-oss-120b at reasoning_effort =
low; the confound in §6.2 is established across two base models (Nemotron-30B
and gpt-oss-120b) but a fuller base-model sweep would strengthen the claim that
the verdict-agreement lift is generically capability-dependent.

**KG coverage, not architecture, bounds the working set.** Only 10/40 scenarios
return real chains because the deployed graph resolves herbs by Latin binomial
and is sparse for foods, nutrients, TCM terms, and direct interaction pairs.
The fabrication rate is thus entangled with coverage; on a denser graph the
absolute rate would differ, though the failure mode (cite-when-empty) would
persist wherever coverage gaps remain. Bilingual recall is 0.000 for every
system — gpt-oss-120b is weak on Chinese and the TCM-term coverage is sparse —
so the bilingual setting is out of scope for the present claims.

**HDI recall is in-panel.** Recall is measured against the benchmark's
severe-HDI subset, not against a universe of real-world interactions; the
ablation in §6.4 isolates the gold-triage substitute as its driver but does not
establish an absolute safety ceiling.

**Orchestration-specific.** The system is AG2-specific and the citation channel
is a property of our prompt + parsing contract; other multi-agent frameworks
may surface or suppress fabrication differently. The general point — that a
citation channel must be verified, not assumed — is framework-independent, but
the specific rates are not portable.

# 9. Future Work and Conclusion

## 9.1 Future Work

- **Enforced faithful citation:** constrain cited indices to the retrieved set
  at decode/post-process time; require an explicit "no KG evidence" state
  instead of free-form citation against an empty set (§7.4).
- **Semantic citation-support checking:** verify that a cited chain *supports*
  the claim it is attached to, not only that it was retrieved (§8).
- **Denser, interaction-specific coverage:** curated supplement–drug interaction
  data and improved entity resolution beyond Latin-binomial matching, to close
  the 10/40 coverage gap that drives most fabrication.
- **Base-model sweep + multi-seed:** establish that the verdict-agreement
  confound (§6.2) and the faithfulness rates are stable across base models and
  seeds; companion v2 benchmark (n = 200, two-annotator IAA).
- **Bilingual grounding:** TCM-term coverage + a citation-faithfulness check
  that reads panel deliberation text, not only `candidate_chains`.

## 9.2 Reproducibility

All numbers in this paper are reproducible from the public repository at
`https://github.com/Syntropy-Health/shrine-health-bioactivity`. The full 40 × 7
prediction matrix, per-system summary with the Cite-Faith / Fabricate columns,
and the herb–drug-interaction ablation are committed under
`research-journal/shared/results/`; Appendix A.6 gives re-render commands,
statistics configuration, base-model and KG-gateway details, and pinned commit
SHAs.

## 9.3 Conclusion

Knowledge-graph grounding is offered as the route to trustworthy clinical
LLMs: cite the evidence and the reasoning becomes auditable. Auditing the
citations of a 6-role grounded panel on supplement–drug safety, we find that
grounding instead manufactures a new failure mode — `diet_os` fabricates a
provenance citation in 40% of predictions, citing chains that were never
retrieved, while posting the matrix-best safety recall and a competitive
verdict-agreement score that hide it entirely. We further show that the two
advantages such systems usually claim are confounded: the verdict-agreement
"lift" over non-grounded baselines is a weak-base-model artifact that vanishes
under a stronger model, and the herb–drug-interaction recall is a gold-triage
artifact that an ablation halves even when real KG chains are supplied. Where
the graph is populated, grounding works and agents cite it faithfully — so the
remedy is not to abandon grounding but to *verify* it: measure
citation-faithfulness, enforce it against the retrieved set, and treat unchecked
citation as the safety liability it is. We release the benchmark, the auditing
instrumentation, and the full result matrix at
`https://github.com/Syntropy-Health/shrine-health-bioactivity`.

# References

<div id="refs"></div>

# Appendix

This appendix follows the bibliography and is excluded from the ML4H Findings 4-page body budget per venue convention. Sections relocated here from the body retain full numerical content and reviewer-relevant detail.

## A.1 Pre-fetch design rationale and pilot data

_Source: relocated from §3.1 (T14.9). Body keeps a one-clause back-reference._

The §3.1 pre-fetched design choice is motivated by the following pilot observation:

This **pre-fetched** design is a deliberate departure from LLM-driven tool
calls. Our pilot found Nemotron-30B emits `RoleVerdict` JSON whose `notes`
field claims tool use ("Used `kg_diet_to_compounds`…") while transcript-level
tool-invocation counts remain zero across all roles — the model hallucinates
tool use from training-data priors (`e2-panel-mcp-wiring-results.md`).
Pre-fetching guarantees every panel deliberation receives a non-empty bundle,
so HDI-Recall and provenance metrics (§4) become measurable rather than null.

## A.2 Cost & latency per-role traces

_Source: relocated from §5 cost-and-latency paragraph (T14.10). Body keeps a one-clause "see A.2" pointer._

Per-role cost and latency detail relocated from §5:

**Cost and latency.** Per-role token usage and latency are captured by
the `cost_tracker` decorator wrapping `ConversableAgent.generate_reply`.
Free-tier rate limits dominate end-to-end matrix wall-clock (full-40
× 6 baselines completed in ~3 hours; the `diet_os_llm_triage` ablation
adds ~2 hours due to free-tier RPM throttling on the additional triage
LLM call). Detailed per-role traces are available in the companion code
release; we omit the table here for space.

## A.3 Citation-faithfulness case studies

Each `diet_os` prediction records the runtime trace-span IDs of its kg-mcp
tool calls and, per agent verdict, the indices of the chains it cites. The
three cases below — a fabrication, a faithful citation, and a working herbal
grounding — illustrate the §6.3 findings at the level of an individual
recommendation. Span IDs resolve in the `diet-os-eval` trace project; chain
counts and cited indices are read directly from the committed prediction JSON.

**Case 1 — Fabricated provenance: `case-hdi-005-ginkgo-aspirin`.** Retrieval
returned **zero** chains (the gateway did not resolve "ginkgo"/"aspirin" to KG
entities; trace spans `c7e5b6fd-…` and `162900a7-…`), so `candidate_chains = 0`.
Nonetheless the Pharmacologist verdict cites chains `[101, 112]` and the TCM
Practitioner cites `[1, 2, 3]` — five references into an empty evidence set.
Only the Dietitian abstains from citing. This is fabrication in its starkest
form: the agents emit specific, confident-looking chain indices for evidence
that does not exist, and a downstream reader following those citations finds
nothing. The verdict itself (`caution`, with deferral) is not unreasonable —
which is exactly why the verdict-level metrics do not flag the problem.

**Case 2 — Faithful citation: `case-hdi-010-yohimbe-clonidine`.** Retrieval
returned 10 chains via the mechanism-traversal tool (spans `4a8779b9-…`,
`80108f23-…`), `candidate_chains = 10`. All three speaking roles (Dietitian,
Pharmacologist, TCM Practitioner) cite chain `[1]` — a valid index — and the
Pharmacologist's note reasons explicitly from the retrieved adrenergic-signalling
chain to the mechanism of concern: yohimbine is an α2-antagonist that opposes
clonidine's central α2-agonism, risking rebound hypertension. Here the citation
channel does what grounding promises: the claim is traceable to a real,
on-topic chain.

**Case 3 — Working herbal grounding: `case-herbal-001-ginger-cinv`.**
Canonical-binomial resolution ("Zingiber officinale") returns 20 chains
(span `ebcaaf3c-…`), `candidate_chains = 20`; the Dietitian and Safety Reviewer
each cite chain `[19]`, in range. The case shows that where the KG covers the
entity, faithful grounding is the default rather than the exception — the
fabrication in Case 1 is a coverage-gap behaviour, not an intrinsic property of
the model.

**Aggregate.** Across all 40 `diet_os` predictions there are 352 individual
chain citations, of which 246 are faithful and 106 (30%) are not. The
per-prediction mean citation faithfulness reported in §6.1 is 0.657 [0.262,
0.858] (averaged over predictions that cite at least once; the pooled
citation-level fraction is 0.699). 16/40 predictions contain ≥1 fabricated
citation (fabrication rate 0.400), of which 13 cite chains while
`candidate_chains` is empty. Only 10/40 predictions carry any real chains
(6 herbal, 4 interaction), the rest reflecting the KG coverage gaps of §6.5.

## A.4 Extended related work

_Reserve target for any §2 prose squeezed out by C-ADDS (T14.13–T14.15) or for HealthGenie / additional comparators if they need framing without body weight._

(Content placeholder — populated only if needed during C-ASSEMBLE.)

## A.5 Limitations and Broader Impact

_Source: relocated from §8 in entirety (T14.11). Body §8 keeps only a 3-line stub referencing this section._

The body §8 stub references this section. Below are the full limitation subsections relocated from §8:

### 8.1 Single-author gold standard at n=40

DietResearchBench-Clinical v1 uses single-author gold annotations across 40 scenarios with no inter-annotator agreement (IAA) measurement. A v2 expansion (n=200, two-annotator design with κ ≥ 0.6 gating and calibration-aware Platt/isotonic scoring) is in progress as a companion paper [@v2benchmark2026].

### 8.2 Free-tier base model

The matrix runs on free-tier gpt-oss-120b (Cerebras, `reasoning_effort = low`,
5 req/min · 150/hr · 1M tok/day). We adopt a free-tier model deliberately to
keep the constrained-inference framing, while choosing one capable enough that
the non-grounded baselines are not artificially near zero (the weaker
Nemotron-3-nano-30B used for the §6.2 base-model comparison drives every
baseline to κ ≈ 0, which is exactly the confound §6.2 documents). Results are
base-model-version-sensitive; a fuller base-model sweep is future work (§8).

### 8.3 HDI Recall is in-panel, not universe-recall

Per the KG coverage audit (`docs/kg-coverage-audit.md`), HDI-Safe-50 covers 86.2% of the curated public HDI universe known to NIH ODS and NCCIH (n=15 reference pairs). Reported HDI Recall is therefore in-panel recall against the curated v1 panel, not absolute recall against the broader herb-drug interaction literature.

### 8.4 Source-attribution provenance, not Cypher round-trip

Provenance metric uses the source-id-prefix proxy (`cmaup:`, `duke:`, `herb2:`, `symmap:`, `hdi-safe-50:`) rather than full Cypher round-trip verification against Aura. Edges retrieved through Layer-B/C MCP traversals are KG-faithful by construction; Cypher verification for adversarial cases is deferred to v2.

### 8.5 AG2-specific orchestration

diet_os is implemented in AG2 v0.12. Pydantic-AI re-ports (estimated 1.5-day migration; native MCP streamable-HTTP, Logfire observability) are deferred to v2 as a framework ablation.

## A.6 Reproducibility extended

_Source: relocated from §9.2 reproducibility detail (T14.12). Body §9.2 keeps the URL + commit pin + a forward-pointer; full commands, stats config, LLM/KG details live here. Plan B integrity bullet (T14.20) inserts here._

Full reproducibility detail relocated from §9.2 of the body:

- **Eval matrix.** The full 40 × 7 prediction matrix, per-system
  `summary.md` (with the Cite-Faith / Fabricate columns), and the
  herb–drug-interaction ablation are committed at
  `research-journal/shared/results/20260605T053102Z-gptoss120b-v1mcp-btspans/`.
  Each `diet_os` / `diet_os_llm_triage` prediction JSON carries
  `candidate_chains`, per-verdict `cited_chains`, and `bt_span_ids`.
- **Re-render.** `python3 -m eval.report --results-dir <dir>` regenerates
  `summary.md`, `paired_tests.md`, `category_breakdown_verdict_kappa.md`, and
  `reliability_diagram.png`. The Cite-Faith / Fabricate columns are computed
  by `eval.metrics.citation_faithfulness` and `citation_fabrication_rate`
  directly from the committed predictions (no live KG needed).
- **Citation-faithfulness audit.** Faithfulness = fraction of
  `cited_chains` indices `i` with `0 ≤ i < len(candidate_chains)`
  (per-prediction mean for the headline; pooled fraction also reported in
  §A.3). Fabrication rate = fraction of predictions with ≥1 out-of-range
  citation. Both are deterministic functions of the committed JSON.
- **Stats.** Per-metric bootstrap CIs with B = 10 000, Davison-Hinkley
  `(k+1)/(B+1)` p-value, fixed seed = 42. The base-model confound (§6.2)
  compares the same 7-system matrix against the earlier Nemotron-30B run at
  `research-journal/shared/results/20260504T230617Z-final-7sys/`.
- **LLM.** Free-tier gpt-oss-120b (Cerebras Inference, `reasoning_effort = low`,
  temperature 0, seed 42; 5 req/min · 150/hr · 1M tok/day). The earlier
  base-model comparison uses free-tier Nemotron-3-nano-30B.
- **KG.** Neo4j AuraDB hosting `unified_diet_kg` (166K nodes, ~5M
  relationships). Read-only Bearer-auth streamable-HTTP gateway at
  `kg-mcp-test.up.railway.app/mcp`; every tool call emits a runtime trace
  span whose ID is recorded on the prediction.
