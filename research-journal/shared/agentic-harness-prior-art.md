# Agentic Harness for Clinical Reasoning — Prior Art Survey

> Distilled from web-researcher survey 2026-04-22. For the primary paper's Related Work section and for positioning our contribution.

## Critical correction

**MassGen is not a citable system.** No paper, preprint, or repo under that name exists in the multi-agent LLM literature as of April 2026. All references to "MassGen" in our planning should be replaced with **MedAgents** (consensus-debate primitive) or **MDAgents** (adaptive team structure) — both peer-reviewed and open-source.

## Related Work structure for primary paper

The most direct related-work cluster is: (1) MedAgents + MDAgents for expert-panel deliberation mechanism, (2) KGARevion + KG4Diagnosis for KG-grounded clinical reasoning, (3) JMIR behavioral nutrition agent (Yang et al., 2025) as the closest diet-domain agentic system and our primary comparator, (4) TCMChat / TCM-DS / BianCang for TCM LLM context, (5) AgentClinic for benchmark methodology contrast.

## Multi-agent LLM systems (deliberation primitives)

### MedAgents (ACL Findings 2024)

**Citation:** Tang, X., Zou, A., Zhang, Z., Li, Z., Zhao, Y., Zhang, X., Cohan, A., Gerstein, M. (2024). *MedAgents: Large Language Models as Collaborators for Zero-shot Medical Reasoning*. Findings of ACL 2024, pp. 599–621. arXiv:2311.10537.
**Architecture:** Training-free five-step pipeline — assemble domain-specialist role agents, each produces independent analysis, analyses merged, multi-round discussion to consensus, final decision. Debate-then-vote with shared written workspace.
**Evaluation:** MedQA, MedMCQA, PubMedQA, 6 MMLU medical subtasks.
**Relevance to us:** We adopt their debate-consensus mechanism verbatim for Stage 3.

### MDAgents (NeurIPS 2024)

**Citation:** Kim, Y., Park, C., Jeong, H., Chan, Y.S., Xu, X., McDuff, D., Lee, H., Ghassemi, M., Breazeal, C., Park, H.W. (2024). *MDAgents: An Adaptive Collaboration of LLMs for Medical Decision-Making*. NeurIPS 2024. arXiv:2404.15155.
**Architecture:** Triage classifies query complexity into three tiers (solo PCP / Multi-disciplinary Team with moderator / Integrated Care Team with external KB). Team size and structure are dynamic.
**Evaluation:** 10 benchmarks including USMLE, MedBench. Best on 7/10; +11.8% group-vs-solo accuracy at high complexity (p < 0.05).
**Relevance to us:** We adopt the complexity-triaged adaptive panel structure for Stage 3.

### AgentClinic

**Citation:** Schmidgall, S., Ziaei, R., Harris, C., Reis, E., Jopling, J., Moor, M. (2024). *AgentClinic: A Multimodal Agent Benchmark to Evaluate AI in Simulated Clinical Environments*. arXiv:2405.07960.
**Architecture:** Four interacting agents (patient, doctor, measurement, moderator) in an OSCE loop. 9 specialties, 7 languages.
**Key finding:** Sequential agentic decision-making drops diagnostic accuracy to < 1/10th of static QA accuracy — benchmark inflation on MedQA does not translate to agentic performance.
**Relevance to us:** No nutrition/herbal OSCE exists. Our DietBench-Clinical fills this gap.

## KG-grounded clinical reasoning

### KGARevion (ICLR 2025)

**Citation:** Su, J., et al. (2025). *AI Agent for Knowledge-Intensive Biomedical QA*. ICLR 2025. arXiv:2410.04660. Harvard Zitnik Lab. Repo: [mims-harvard/KGARevion](https://github.com/mims-harvard/KGARevion).
**Mechanism:** Generate candidate KG triplets from LLM latent knowledge → verify against grounded biomedical KG → filter erroneous triplets → construct verified subgraph for final answer.
**Result:** +5.2% over 15 baselines; +10.4% on curated QA sets.
**Relevance:** We extend the triple-verification idea from per-triple to chain-level provenance (C4). Their verification is internal; ours is user-facing.

### KG4Diagnosis (AAAI-25 Bridge)

**Citation:** Zuo, K., Jiang, Y., Mo, F., Lio, P. (2024). *KG4Diagnosis: A Hierarchical Multi-Agent LLM Framework with Knowledge Graph Enhancement for Medical Diagnosis*. AAAI Bridge 2025. arXiv:2412.16833.
**Architecture:** Two-tier GP-agent + specialist-agent hierarchy over dynamic KG of 362 diseases.
**Relevance:** Precedent for multi-agent + KG combination; informs our Stage 3 + Stage 2 composition.

### KARE (ICLR 2025)

**Citation:** Jiang, P., et al. (2024). *Reasoning-Enhanced Healthcare Predictions with Knowledge Graph Community Retrieval*. ICLR 2025. arXiv:2410.04585.
**Mechanism:** Multi-source biomedical KG → hierarchical community detection + summarization → LLM reasoning over community summaries.
**Result:** +10.8–15.0% over leading models on MIMIC-III/IV mortality/readmission.
**Relevance to us:** Contrast baseline — not conversational, no panel deliberation, no user-facing provenance chains.

### Process-Supervised Multi-Agent RL (ICML 2025)

**Citation:** Lee, C., et al. (2025). *Process-Supervised Multi-Agent RL for Clinical Reasoning*. ICML 2025. arXiv:2602.14160.
**Mechanism:** GRPO with dual process+outcome rewards; supervisor routes to 6 evidence-category sub-agents; produces auditable evidence traces.
**Relevance to us:** Only system we found that produces "evidence-specific reasoning traces" with traceability claims evaluated against a clinical standard (ClinGen SOP). Cite as precedent for our provenance-chain output format (C4).

## Diet / nutrition agentic systems (our direct comparators)

### JMIR Behavioral Nutrition Agent (Yang et al., Verily, 2025)

**Citation:** Yang, Y., et al. (2025). *Behavioral Science-Informed Agentic Nutrition Coaching*. JMIR Formative Research. DOI: 10.2196/75421.
**Architecture:** Two-agent Gemini-1.5 Pro system — motivational-interviewing barrier identifier (28-barrier taxonomy) + strategy executor (50+ strategies, 100+ tactics).
**Result:** >90% barrier-identification accuracy; preferred over single-agent in 66.7% of blinded evaluations.
**Relevance to us:** Closest published diet-agentic system. **Our primary comparator.** Their system is purely behavioral — no KG, no molecular targets, no TCM, no herb-drug safety. Our contribution extends along all four of those dimensions.

### ChatDiet (Jiang et al., 2024)

**Citation:** arXiv:2403.00781. RAG-based food recommender with orchestrator + causal model.
**Relevance:** Baseline — no multi-agent deliberation, no clinical safety layer.

## TCM LLM context

### TCMChat, TCM-DS, BianCang, Taiyi, ShizhenGPT

- **TCMChat** (ScienceDirect 2024, S1043661824004754): generative TCM LLM, not agentic.
- **TCM-DS** (Springer Chinese Medicine 2025, 10.1186/s13020-025-01249-0): DeepSeek R1 + LoRA + RAG for edible-herbal formulas; 0.9924 precision; not agentic.
- **BianCang / Taiyi** (2024): bilingual CN+EN TCM models via continual pretraining on Qwen2/2.5; not multi-agent.
- **ShizhenGPT** (arXiv:2508.14706): multimodal TCM LLM.

None of these uses a KG or multi-agent deliberation. Our bilingual TCM work (via SymMap + HERB 2.0 + Jina reranker) reconciles CN herb names with molecular targets — unpublished combination.

## Pre-retrieval clarification

### ClarQ-LLM (arXiv:2409.06097)

Benchmark for clarification-question generation in task-oriented dialogue. Generic, not clinical. Precedent for our Stage 1 clarification loop design.

### Multi-Agent Conversation (MAC; npj Digital Medicine 2025, s41746-025-01550-0)

MDT-inspired conversational framework; higher diagnostic accuracy in primary + follow-up vs. single models. Cite as precedent for multi-turn clinical conversation.

### DoctorAgent-RL (arXiv:2505.19630)

Multi-agent RL for clinical dialogue; Markov Decision Process formulation. Closest to structured symptom-elicitation agent. Informs our Stage 1 design.

## Safety layer

- Red-team medical-AI benchmarks: npj Digital Medicine 2025 (s41746-025-01542-0) — 20.1% inappropriate-response rate; medRxiv 2026 (2026.02.26.26347212v1) — 8-category attack taxonomy, authority-impersonation primary vulnerability.
- DDI LLM detection (PMC12084699, 2025): zero-shot sensitivity 0.5463; fine-tuned Phi-3.5 achieves 0.978.
- NutriOrion (arXiv:2602.18650): hard drug-food constraints via external constraint engine — not KG-derived.

**Gap:** no published system derives safety predicates from KG edge types (e.g., `INTERACTS_WITH`) within a retrieval layer. Our Safety Reviewer (Stage 3) + HDI-Safe 50 ingestion (Task A8) fills this.

## Novelty scorecard (positioning statement)

| Candidate claim | Status |
|---|---|
| Pre-retrieval clinical-intake agent (OPQRST + SOCRATES + NCP/ADIME) | **Genuinely open** — no published LLM formalization |
| MDAgents-style panel applied to diet / TCM domain | **Partially covered** — claim composition, not primitive |
| KG-grounded herb→compound→target→symptom provenance chain as user artifact | **Genuinely open** for this chain topology and domain |
| Compositional confidence calibration (evidence × HDI × context) | **Genuinely open** |
| Bilingual CN+EN TCM ↔ molecular-target reconciliation in unified KG | **Partially covered** — no prior work unifies within one KG |
| Dietitian-gold-standard benchmark for clinical diet-AI | **Genuinely open** |

**Consolidated claim:** the **integration** of structured-first KG + agentic pre-retrieval clarification + adaptive expert-panel deliberation + compositional confidence + KG-grounded provenance + bilingual CN/EN TCM, evaluated on a dietitian-gold-standard benchmark. No prior system combines more than two of these five elements, and none operates on the diet + TCM + molecular-target domain simultaneously.
