# Diet-OS — Design Spec (Paper γ-split, β-primary)

> **Status:** Approved through brainstorming 2026-04-22. Execution proceeds via plans under `./plans/`.
> **Two-paper program:** primary = β (clinical-AI application). Companion = γ (KG + infra resource paper).

## 1. Positioning and contributions

### 1.1 Primary paper (β)

**Working title:** *Diet-OS: A provenance-grounded agentic harness for safe clinical dietary and herbal recommendations.*

**Target venue:** npj Digital Medicine (preferred) or JAMIA.

**Single-sentence claim:** a four-stage agentic harness (clinical-intake clarification → KG-grounded candidate retrieval → adaptive expert-panel deliberation → compositional confidence calibration) that produces dietary and herbal recommendations with auditable `herb → compound → target → symptom` provenance chains, and outperforms single-LLM and behavioral two-agent baselines on a new dietitian-gold-standard benchmark.

**Five contributions:**

| # | Contribution | Novelty anchor |
|---|---|---|
| C1 | Diet-OS harness architecture — four-stage pipeline with specified inputs/outputs per stage | First MDAgents-style adaptive panel applied to dietary/herbal domain |
| C2 | Pre-retrieval clinical-intake agent grounded in OPQRST + SOCRATES + NCP/ADIME | No published work formalizes clinical-intake schemas as LLM prompts for pre-retrieval query structuring |
| C3 | Compositional confidence calibration: Bayesian linear fusion of evidence-tier × HDI-risk × context-fit, weights tuned via Bayesian optimization, post-hoc Platt/isotonic calibration | No system composes evidence grade × interaction risk for herbal recommendations |
| C4 | Provenance-chain output format: typed KG path `herb → compound → target → symptom` with per-edge source citations and evidence tier | KGARevion verifies internally; no system surfaces this specific chain topology for diet/TCM |
| C5 | DietBench-Clinical — 200-scenario benchmark with dietitian + pharmacist gold standards, HDI ground truth on HDI-Safe 50 subset, evidence tiers | AgentClinic has no nutrition/herbal OSCE; JMIR Yang et al. 2025 used 30-conversation expert eval only |

### 1.2 Companion paper (γ)

**Working title:** *Shrine-KG: A unified phytochemistry–nutrition–TCM knowledge graph for LLM-agent clinical reasoning.*

**Target venue:** Scientific Data (Nature) or Database (Oxford).

**Six deferred contributions:**

| # | Contribution |
|---|---|
| D1 | Unified 7-database KG (Duke + FooDB + CMAUP + CTD + TTD + OpenNutrition + HERB 2.0 + SymMap) |
| D2 | First published use of LightRAG's `ainsert_custom_kg` for structured biomedical ingestion |
| D3 | 5-strategy FooDB ↔ OpenNutrition food bridge |
| D4 | Bilingual CN+EN TCM alignment (Jina multilingual reranker + text-embedding-3-large) |
| D5 | `ScopedNeo4JStorage` + `ContextVar` multi-tenant extension + preflight + isolation canary |
| D6 | HDI edge extension (DrugBank open subset + NIH ODS + MSK About Herbs + LiverTox) |

### 1.3 Scope boundary

- **Primary answers:** "Can LLM agents safely handle clinical dietary/herbal reasoning?" → harness + benchmark + calibration.
- **Companion answers:** "What is the data substrate and how is it served?" → KG + infrastructure.
- Primary cites companion as "Methods — KG substrate"; companion cites primary as "Representative downstream application."
- Multi-tenancy (D5) is cut from primary entirely; may appear as a PoC/deployment appendix only if space allows.

## 2. Architecture — four-stage Diet-OS harness

```
User query
    ↓
[Stage 1] Clinical Intake Agent   (OPQRST + SOCRATES + NCP/ADIME)
    → structured_intake JSON
    ↓  (clarification loop ≤ 2 rounds, ≤ 3 questions per round)
[Stage 2] KG-Grounded Candidate Retrieval   (LightRAG hybrid mode + typed-chain extractor)
    → candidate_chains[]
    ↓
[Stage 3] Adaptive Expert Panel   (MDAgents-style triage → 6 role agents → MedAgents-style debate)
    → (ranked_candidates, panel_critique, dissenting_opinions)
    ↓
[Stage 4] Compositional Calibrator + Provenance Formatter
    → recommendation_artifact (ranked + confidence-decomposed + typed chains)
    ↓
Clinician-facing output
```

### 2.1 Stage 1 — Clinical Intake Agent (C2)

**Grounding (historical clinical lineage):**

| Schema | Origin | Role |
|---|---|---|
| OPQRST | Emergency-medicine triage mnemonic (Lyon; Walsh et al.) | Symptom phenomenology |
| SOCRATES | UK Resuscitation Council (Ashelford 2005) | Deeper symptom + association characterization |
| NCP / ADIME | Academy of Nutrition and Dietetics Nutrition Care Process (2003, revised 2023) | Nutrition-specific context: anthropometric, biochemical, clinical, dietary, behavioral |

**Output schema (strict JSON, schema-validated):**

```
{
  "chief_complaint": str,
  "symptom_profile": {
    "onset": str, "provocation": str, "quality": str,
    "region": str, "severity": 1-10, "timing": str,
    "associated": [str], "exacerbating": [str], "relieving": [str]
  },
  "nutrition_context": {
    "anthropometric": {...}, "biochemical": {...},
    "clinical": {...}, "dietary": {...}, "behavioral": {...}
  },
  "medications_current": [drug, ...],
  "red_flags": [str],
  "needs_clarification": bool,
  "clarification_questions": [str]  // ≤ 3
}
```

**Bounds:** clarification loop capped at 2 rounds (ClarQ-LLM finding: intake fatigue).

**Citations:** Lyon (OPQRST); Ashelford 2005 (SOCRATES); Academy of Nutrition & Dietetics NCP/ADIME; ClarQ-LLM (arXiv:2409.06097); DoctorAgent-RL (arXiv:2505.19630); MAC (npj Digital Medicine 2025 s41746-025-01550-0).

### 2.2 Stage 2 — KG-grounded candidate retrieval

- **Keyword derivation:** intake → LightRAG dual-level keywords (`k_local` = symptoms/targets/explicit entities; `k_global` = mechanism themes).
- **Retrieval:** LightRAG `/query` in hybrid mode (reported best on UltraDomain).
- **Chain extraction:** post-process returned subgraph; traverse typed paths starting from Symptom nodes matching intake; emit chains with per-edge `source_id`, `weight`, evidence-tier label.
- **Stub filter:** drop chains with `entity_type="UNKNOWN"` using `fix_unknown_entities.py` classifier.

**Citations:** LightRAG (Guo et al. Findings of EMNLP 2025); KGARevion (Su et al. ICLR 2025, Harvard Zitnik Lab); GraphRAG (Edge et al. 2024, contrast baseline).

### 2.3 Stage 3 — Adaptive expert panel (C1)

**Triage → 3 team configurations (MDAgents-style):**

| Complexity | Team | Triggered by |
|---|---|---|
| Low | Solo Dietitian | No red flags, < 3 medications, no pregnancy/organ-failure |
| Moderate | Dietitian + Pharmacologist + TCM Practitioner | Polypharmacy or herb-drug stacking |
| High | + Clinical Research Scientist + Safety Reviewer + Defer-to-Clinician | Red flags, pregnancy, hepatic/renal, weak-evidence request |

**Six role agents:**

| Role | Focus | KG edges consulted |
|---|---|---|
| Dietitian | Nutrition adequacy, pattern fit | `Food → nutrition_100g`, `Herb → TREATS_SYMPTOM` |
| Pharmacologist | Mechanism, PK/PD plausibility | `Compound → TARGETS_PROTEIN → Target → ASSOC_WITH_DISEASE` |
| TCM Practitioner | Classical formula context, syndrome pattern (辨證), bilingual terminology | CN-labeled Herb nodes, SymMap syndrome labels, HERB 2.0 evidence tiers |
| Clinical Research Scientist | Study design, evidence hierarchy (GRADE/Cochrane), methodological rigor; writes dissenting-minority report on weak-evidence recs | Evidence-tier labels across all edges |
| Safety Reviewer | HDI, contraindications, dose/duration warnings | `INTERACTS_WITH` (HDI-Safe 50), `CONTRAINDICATES` |
| Defer-to-Clinician | Scope boundary; flags queries that must exit | Rule-based + LLM classifier |

**Deliberation protocol (MedAgents-style debate-consensus):** each agent produces (support, concerns, per-candidate verdict ∈ {prefer, caution, reject}) → 1 round structured rebuttal (hard cap) → moderator produces final ranking + dissenting-minority report.

**Citations:** MDAgents (Kim et al. NeurIPS 2024, arXiv:2404.15155); MedAgents (Tang et al. ACL Findings 2024, arXiv:2311.10537); MAC (npj Digital Medicine 2025 s41746-025-01550-0).

### 2.4 Stage 4 — Compositional calibrator + provenance formatter (C3, C4)

**Composition function (primary):** Bayesian linear fusion on logit scale:

```
logit(conf) = β₀ + β₁·evidence_tier + β₂·(1 − HDI_risk) + β₃·context_fit + ε
```

| Component | Derivation | Range |
|---|---|---|
| evidence_tier | Max tier across chain edges via HERB 2.0 + source_id tagging (clinical trial > observational > in vivo > in vitro > traditional use) | ordinal → [0,1] |
| HDI_risk | Max severity across `INTERACTS_WITH` edges from chain's compounds to patient's current medications | [0,1] |
| context_fit | Patient attributes (age, pregnancy, conditions) vs. `CONTRAINDICATES` edges | [0,1] |

**Weight tuning:** Bayesian Optimization (GP surrogate, EI acquisition) on DietBench-Clinical train split. **Post-hoc calibration:** Platt scaling + isotonic regression on val split; reliability diagram + ECE on test split.

**Ablation baselines:**
- Fixed geometric mean (interpretable baseline)
- Dempster-Shafer evidence combination (historical ground: MYCIN certainty factors → modern DS)
- Single-component (evidence-only, HDI-only, context-only)

**Provenance artifact schema:**

```
{
  "recommendation": str,
  "confidence": 0-1,
  "components": {"evidence_tier": 0-1, "HDI_risk": 0-1, "context_fit": 0-1},
  "provenance_chain": [
    {"from": str, "edge": str, "to": str, "source_id": str, "weight": 0-1, "evidence_tier": str},
    ...
  ],
  "panel_notes": {role: {support, concerns, verdict}, ...},
  "dissenting_opinions": [...],
  "defer_to_clinician": bool
}
```

**Citations:** HERB 2.0 (NAR 2025, DOI:10.1093/nar/gkae1054); Platt 1999; Niculescu-Mizil & Caruana 2005; Guo et al. 2017 (calibration of modern NN); Snoek et al. 2012 (BayesOpt); Dempster 1967 / Shafer 1976 / Shortliffe 1976 (DS historical); PMC12084699 (DDI LLM 2025).

## 3. Dataset moat

### 3.1 Current baseline

SQLite intermediate has full breadth: Duke (herbs/compounds/herb_compounds), FooDB (compound_foods), CMAUP (compound_targets/targets), CTD+TTD (target_diseases, chemical_diseases), OpenNutrition (326K foods with 90 nutrients). LightRAG KG is a **pinned 50K-edge prototype subsample** (`MAX_RELATIONSHIPS=50000`). No dedicated TCM dataset ingested today — "TCM support" is Duke ethnobotany + a bilingual reranker with no CN entities.

### 3.2 Tier-1 additions for primary paper (pre-submission critical path)

| Dataset | Adds | Licensing | Ingest effort |
|---|---|---|---|
| SymMap v2 | ~5.2K TCM symptoms + CN/EN herb names + 14 syndromes | Free academic | ~2 weeks (+3–5 days symptom-alignment crosswalk) |
| HERB 2.0 (full) | Evidence-tier labels (clinical/experimental), 1241 herbs bilingual | Open academic | ~2 weeks |
| NIH ODS Fact Sheets | Open HDI narratives, safety notes for ~90 top herbs | Public domain | ~1 week (part of HDI-Safe 50) |
| MSK About Herbs | Curated HDI, mechanism, evidence tier, ~280 herbs | Free non-commercial + citation | ~1 week (part of HDI-Safe 50) |
| LiverTox | Hepatotoxicity profiles, evidence-graded | Public domain | ~3 days (part of HDI-Safe 50) |
| Populate food_nutrition_bridge | 90-nutrient enrichment for Food nodes (scripts exist, not executed) | — | ~1 day |

### 3.3 Tier-2 (companion paper)

TCMSP, ETCM, HIT 2.0, KNApSAcK, Phenol-Explorer, PubChem, ChEMBL, full DrugBank HDI, SNOMED/ICD-10 alignment.

### 3.4 HDI-Safe 50 subset — methodology PoC

~50 well-documented herb-drug interactions spanning 5 mechanism classes (CYP450 induction/inhibition, P-gp, PD antagonism, coagulation, serotonergic). Manual curation from NIH ODS + MSK + LiverTox. Sufficient to demonstrate C3 Safety Reviewer end-to-end; full HDI coverage deferred to D6.

## 4. Evaluation protocol (DietBench-Clinical)

### 4.1 Benchmark composition

- **200 scenarios** across 4 categories (~50 each):
  1. Single-symptom herbal query
  2. Nutrition recommendation (symptom + dietary context)
  3. Multi-drug patient (HDI concern; uses HDI-Safe 50)
  4. TCM syndrome pattern (bilingual CN/EN)
- **Annotation:** 2 dietitians + 1 pharmacist per scenario, double-blind.
- **Gold-standard fields per scenario:** ranked recommendations (ordinal), evidence tier per recommendation, HDI flags, contraindications, defer-to-clinician (bool).
- **Inter-annotator agreement:** Cohen's kappa for categorical fields, Kendall's tau for ranked recommendations. Target κ > 0.70; rescope annotations below 0.60.

### 4.2 ML-fair data splitting (prototype-scale KG)

- **Stratified split:** 4 scenario categories × 3 MDAgents complexity tiers = 12 strata.
- **Ratios:** 60% train (weight tuning), 20% val (calibration fitting), 20% test (final reporting).
- **Entity-level leakage control:** herbs and drugs appearing in test MUST NOT appear in train as the primary entity of another scenario. This bounds the generalization claim to unseen entities.
- **5-fold CV** on train+val for confidence-weight BayesOpt.
- **Held-out test set** — single evaluation run, pre-registered.
- **Reproducibility:** splits pinned by seed + JSON manifest checked into repo.

### 4.3 Baselines

1. GPT-4 zero-shot (no tools)
2. GPT-4 + LightRAG naive mode (flat-RAG baseline)
3. Yang et al. 2025 JMIR two-agent behavioral (no KG)
4. MedAgents (ACL 2024) — debate-consensus, no KG
5. MDAgents (NeurIPS 2024) — adaptive panel, generic KG (not ours)
6. **Diet-OS full harness** (ours)
7. **Ablations of ours:** no intake agent, no panel, no calibration, no provenance, single-role panel

### 4.4 Primary metrics

- **Ranking agreement:** Kendall's tau vs. gold standard
- **Calibration:** Expected Calibration Error (ECE) + reliability diagram
- **HDI safety recall:** % of true herb-drug interactions correctly flagged (HDI-Safe 50)
- **Contraindication precision/recall:** vs. gold contraindication flags
- **Defer-to-clinician accuracy:** binary classification
- **Provenance faithfulness:** % of output edges that actually exist in KG (Cypher verification)

### 4.5 Secondary metrics

- Panel agreement (Fleiss' κ across 6 role agents) — high κ flags groupthink; report dispersion
- Dissenting-minority detection: does dissent surface when gold standard marks weak evidence?
- Token cost and latency per recommendation
- Clarification-round count (Stage 1 loop behavior)

## 5. Companion paper architecture

See §1.2. Companion paper is authored in parallel once primary data moat is complete (Subsystem A). Manuscript drafting is Subsystem G.2 (follows primary's G.1).

## 6. research-journal/ folder structure

```
research-journal/
├── DESIGN.md                                 # this file
├── README.md                                 # orientation
├── plans/
│   ├── 2026-04-22-program.md                 # subsystem program plan
│   ├── 2026-04-22-subsystem-a-data-moat.md   # first detailed plan (this turn)
│   └── <future subsystem plans>
├── primary/                                  # β paper artifacts (populated in Subsystem G)
├── companion/                                # γ paper artifacts (populated in Subsystem G)
└── shared/
    ├── bibliography.bib
    ├── dataset-moat.md                       # adjacent-dataset survey (this turn)
    ├── lightrag-contributions-audit.md       # our delta over upstream (this turn)
    └── agentic-harness-prior-art.md          # MedAgents/MDAgents/etc review (this turn)
```

## 7. Non-goals (for primary paper)

- **NOT** evaluating at full-scale KG — prototype-scale with ML-fair splits is the methodology PoC.
- **NOT** claiming multi-tenant generalization — D5 is companion-only.
- **NOT** covering all herb-drug interactions — HDI-Safe 50 is the demonstration set.
- **NOT** running a prospective clinical trial — retrospective benchmark only.
- **NOT** fine-tuning any LLM — all agents are prompt-engineered over stock GPT-4-class models.

## 8. Open risks

| Risk | Mitigation |
|---|---|
| Inter-annotator agreement < 0.60 | Rescope ambiguous scenarios; add annotation rubric |
| SymMap symptom vocabulary doesn't align with Duke's 47 symptoms | Manual crosswalk table (+3–5 days budget) |
| Bayesian weight tuning overfits on 200 scenarios | Hard cap on posterior variance; report frequentist baseline as sanity |
| Panel groupthink / collusion | Role framing + mandatory dissent-surfacing protocol; report Fleiss' κ dispersion |
| Provenance-chain faithfulness below 95% | Cypher round-trip verification at Stage 4 output time; drop chains that fail |
| LLM provider drift during eval window | Pin model versions + date-stamped eval runs |
