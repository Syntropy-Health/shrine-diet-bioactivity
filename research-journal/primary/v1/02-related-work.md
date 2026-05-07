## 2. Related Work

### Multi-agent clinical reasoning

MedAgents [@medagents2024] frames zero-shot medical reasoning as a multi-role
panel deliberating over nine medical datasets, and MDAgents [@mdagents2024]
adds adaptive routing between solo and multi-disciplinary-team configurations.
Yang et al. [@yang2025], the JMIR baseline of behavioral-science-informed agentic workflows, propose a two-agent design (barrier-identification + strategy-execution) for personalized-nutrition adherence coaching, which we re-implement as our third behavioral baseline. We compare against all three as architectural
baselines and extend them with Layer-B/C role-priored KG retrieval. A
contemporary threat is Wu et al.'s "Safer Therapy" [@wu2025], which reports
single-GP performance comparable to a multi-disciplinary debate panel on
medication-conflict resolution; §7.2 argues that our HDI Recall structural
ablation shows debate without KG-grounding cannot produce HDI signal, placing
the two findings on orthogonal axes.

### KG-grounded LLM clinical reasoning

AMG-RAG [@amgrag2025] constructs a medical knowledge graph agentically and
reports F1 74.1 % on MedQA; MedRAG [@medrag2025] fuses a four-tier
hierarchical diagnostic KG with EHR retrieval; KG-SMILE [@kgsmile2025] adds
explainability to KG-RAG. Our pre-fetched typed-Cypher retrieval is
offline-constructed and queried deterministically through the MCP gateway
(§3.1), so live KG construction is orthogonal rather than competing.

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

### Existing benchmarks

TCM-Eval [@tcmeval2025] and TCM-5CEval [@tcm5ceval2025] cover TCM knowledge
questions with no clinical-deliberation evaluation. MedQA [@medqa2021] and
MedMCQA [@medmcqa2022] are general medical-MCQ ceilings with no diet or herb
content, and AgentClinic [@agentclinic2024] is multimodal sequential
consultation. To the best of available literature, DietResearchBench-Clinical
(§4) is the first public benchmark covering herb-drug interaction reasoning,
diet-bioactive clinical inference, and TCM syndrome / Western-nutrition
crosswalk in a single evaluation set.
