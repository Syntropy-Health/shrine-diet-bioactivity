# Design Pivot — Clinical Research Team as Primary Implementation

> **Status:** Approved 2026-04-22 after Subsystem A local-SQLite phase complete.
> **Supersedes:** the implementation focus in `DESIGN.md §2` (the four-stage *patient-facing recommendation* harness). The paper's **claim** (β = clinical-AI application) is unchanged; the **showcase implementation** pivots.

## TL;DR

We are reframing the primary system implementation from a *patient-facing four-stage recommendation harness* to a **clinical research team multi-agent system** built on AG2 over the unified phytochemistry-nutrition-TCM-evidence KG completed in Subsystem A. The intake-agent (former Subsystem B) becomes a supporting role inside the team rather than its own standalone subsystem. This is the edge of innovation that the adjacent-space research we produced points to.

## What changed and why

### 1. The dataset asset turned out richer than the original plan assumed

After Subsystem A:

- **HERB 2.0 ingestion** delivered **1,797,785 herb-disease evidence relationships** (141 PMID-backed clinical + 1.8M GEO experimental) — three orders of magnitude beyond plan estimates.
- **SymMap v2.0 ingestion** delivered **51,131 entities** including **UMLS-anchored modern symptoms (100% coverage)** plus PubChem / HGNC cross-references on molecules and genes.
- **Duke↔SymMap symptom crosswalk** produced 30 high-confidence modern matches and 25 high-confidence TCM matches with **classical Chinese vocabulary** (消渴 Xiao Ke for diabetes, 胸痹 Xiong Bi for ischemic heart disease, 瘀血阻络 for poor circulation).

This data substrate is **clinical-research-grade**, not just patient-recommender-grade. Forcing it into a single-patient recommendation pipeline under-utilizes its breadth.

### 2. The adjacent-space research we produced (in `shared/`) all points the same direction

| Artifact | What it told us |
|---|---|
| `lightrag-contributions-audit.md` | Our LightRAG extensions are clinical-grade infrastructure (`ScopedNeo4JStorage`, isolation canary). Better suited to a research-team backend than a single-user recommender. |
| `agentic-harness-prior-art.md` | Closest published systems (MedAgents, MDAgents, KGARevion, KARE) are *clinical reasoning* systems, not recommenders. The closest diet-domain agentic system (JMIR Yang 2025) is purely *behavioral* with no KG — leaves a wide research-grounded gap. |
| `dataset-moat.md` | The 7-DB unified KG's three-property moat (cross-ontology + bilingual + evidence-tier) is exactly what a clinical research team needs as a substrate. |
| `multi-agent-framework-comparison.md` | AG2's `ConversableAgent` + `GroupChat` + structured output map cleanly to a research-team workflow. AG2's prior art is itself in clinical multi-agent literature (TeamMedAgents, ClinicalAgents). |
| `hdi_safe_50.json` | Curated herb-drug interactions cite NIH ODS / MSK / LiverTox — these are research-evidence sources, not consumer guidance. They want a research team consuming them. |

Every adjacent-space artifact reinforces the same direction: **the system we are best-positioned to ship — and the one with the cleanest novelty story — is a clinical research team, not a patient-facing recommender.**

### 3. The competitive landscape rewards this framing

- **Recommendation systems** in nutrition/herbal AI are crowded (ChatDiet, JMIR Yang, LLM-driven food recommenders). Differentiation requires defending a behavioral-vs-KG comparison.
- **Multi-agent clinical research** systems are nascent. Process-Supervised MARL (Lee et al. ICML 2025) does gene-disease curation; nothing exists for herbal/dietary clinical-research synthesis. **This is open whitespace.**
- **Bilingual TCM + molecular-target reconciliation** as a research substrate has zero published prior art. The combination "AG2 multi-agent + bilingual KG + 3-tier evidence + provenance chains for clinical research" is unpublished.

### 4. Safety story is cleaner

A research-synthesis output ("here is the evidence; here are the risks; here is the panel's deliberation") is auditable and clinician-reviewable. A patient-facing recommendation ("you should take ginger") carries direct clinical liability and requires regulatory framing that a research paper cannot easily provide. The pivot reduces the paper's safety burden without weakening the methods contribution.

## What stays the same

- **Paper positioning (β):** still clinical-AI application targeting npj Digital Medicine / JAMIA.
- **Five contributions (C1–C5):** unchanged at the *concept* level. C1 (architecture), C2 (intake clarification), C3 (compositional calibration), C4 (provenance chains), C5 (DietBench-Clinical) all reframe naturally for the research-team setting:
  - C1 architecture: still 4-stage (intake → retrieval → panel → calibration) but the user is a *clinician researcher*, not a patient.
  - C2 intake: clarification now elicits the *research question* (what intervention, what condition, what evidence level needed), not patient-side symptoms.
  - C3 calibration: still evidence × HDI-risk × context-fit, but context-fit measures *research-question fit* rather than *patient fit*.
  - C4 provenance chains: even more central — the research-synthesis output IS the provenance.
  - C5 DietBench-Clinical: scenario format reframes from "patient asks X" to "clinician asks X about evidence Y" — same complexity tiers, same gold-standard structure, easier to annotate (clinicians evaluate research synthesis routinely).
- **Companion paper γ (Shrine-KG resource):** unchanged.

## What changes

### Subsystem reordering

| Old plan | New plan |
|---|---|
| **Primary:** Subsystem B (intake agent), built first | **Primary:** Subsystem H (AG2 clinical research team), built first |
| **Supporting:** Subsystem H (massgen demo, optional case study) | **Supporting:** Subsystem B (intake elicitation as a *role* within Subsystem H, not its own deliverable) |
| Subsystems C, D, E, F follow B | Subsystems C, D, E, F either fold into H or follow H |

### Subsystem B's new status

Subsystem B is **kept in the program plan as a supporting layer**, not implemented as a standalone deliverable. Its responsibilities (OPQRST + SOCRATES + NCP/ADIME structured intake) are absorbed by the Triage role inside Subsystem H. The intake schema is preserved verbatim — only the execution context changes (intake happens *inside* the team's first turn, not as a separate service).

### Implementation focus

- **Subsystem H** is now the lead implementation. Its plan is at `plans/2026-04-22-subsystem-h-clinical-research-team.md` (this turn).
- The plan covers: AG2 install, Pydantic typed models, KG-query tool, triage role, 6 specialist roles, GroupChat + Manager assembly, 3 demo case-study runners.
- Reproducibility: `cache_seed=42`, `temperature=0`, pinned model snapshots, deterministic case-study seeds.

## Documents updated this turn

- `DESIGN-PIVOT-2026-04-22.md` (this file) — captures the rationale for the pivot.
- `plans/2026-04-22-program.md` — Subsystem H promoted to primary; B annotated as supporting.
- `plans/2026-04-22-subsystem-h-clinical-research-team.md` (new) — detailed TDD plan for the AG2 implementation.

## Open dependencies

- **Aura credentials** — Subsystem H requires the LightRAG KG to be queryable. Subsystem A Tasks 0/8/9/10 are blocked on Aura auth (separate user action). Subsystem H's KG-query tool will fall back to direct SQLite reads against `data_local/herbal_botanicals.db` if the LightRAG `/query` endpoint is unavailable, so prototyping can begin without Aura.

## Non-decisions (kept open)

- The exact set of 3 demo case studies in Subsystem H — proposed in the plan, but reviewable.
- Whether to publish Subsystem H's case-study transcripts as a supplementary dataset alongside the paper.
- Whether to re-run DietBench-Clinical evaluation under the research-team framing or build a separate ResearchBench-Clinical — defer to Subsystem F replan.
