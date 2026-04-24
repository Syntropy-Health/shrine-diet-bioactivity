# Multi-Agent Framework Comparison — AG2 vs MassGen

> Decision artifact 2026-04-22. Distilled from web-researcher survey. Informs Subsystem H (case-study clinical research team demo).

**Decision:** use **AG2 (`ag2ai/ag2`)**. MassGen is rejected.

## TL;DR

AG2 (formerly AutoGen, governed as `ag2ai` from November 2024) is a mature, code-first multi-agent framework whose primitives — `ConversableAgent`, `GroupChat`, `GroupChatManager`, `response_format=PydanticModel` — map directly to the requirements of our 6-role clinical panel with MDAgents-style triage and MedAgents-style 1-round rebuttal. MassGen is a CLI-first homogeneous parallel voter with no per-agent role API, no structured output, no medical-multi-agent prior art — architectural mismatch.

## Side-by-side (abridged; full research in `shared/` archive)

| Dimension | AG2 v0.12.0 | MassGen v0.1.80 |
|---|---|---|
| GitHub stars | 54,000+ | ~965 |
| Latest release | 2026-04-17 | 2026-04-22 |
| Python | ≥ 3.10 | ≥ 3.11 |
| Role specialization | First-class (`system_message` + `description`) | Not in public API — agents differ only by model |
| Group-chat + moderator | Native `GroupChat` + `GroupChatManager` with speaker selection (auto/round_robin/custom) | Parallel broadcast with vote-based convergence |
| Structured output | Native `response_format=PydanticModel` on OpenAI/Anthropic/Gemini/Bedrock | Undocumented; `final_answer` is plain string |
| Custom tool / HTTP | `@register_for_llm()` + `@register_for_execution()` decorators; trivially plug KG-query | MCP server integration only; no per-agent Python function registration |
| Adaptive team sizing (MDAgents) | Hand-roll (conditional instantiation before `GroupChat`) | Not applicable (fixed parallel fan-out) |
| 1-round rebuttal (MedAgents) | Hand-roll (`max_round=2` + `round_robin` + moderator) | Not applicable (convergence is vote-based) |
| Reproducibility | `cache_seed` + `temperature=0` + pinned model snapshot; OpenAI `seed` passthrough | No documented determinism API |
| Clinical-multi-agent prior art | MDAgents (arXiv 2404.15155), TeamMedAgents (arXiv 2508.08115), ClinicalAgents (arXiv 2603.26182) all use AutoGen-family primitives | None found |

## Subsystem H sketch (written in full in the forthcoming plan)

- 6 `ConversableAgent` instances (Dietitian, Pharmacologist, TCM Practitioner, Clinical Research Scientist, Safety Reviewer, Defer-to-Clinician) each with a role-specific `system_message`.
- Shared tool `kg_query` registered via `@register_for_execution()` → `requests.post` to the LightRAG `/query` endpoint, returns a Pydantic `KGResult`.
- `TriageAgent` runs first in a 2-agent `initiate_chat` with a `UserProxyAgent`, emits `TriageResult` via `response_format`.
- Based on triage complexity, conditionally assemble `GroupChat` with the correct agent subset (`solo` / `moderate` / `full_panel`).
- `speaker_selection_method="round_robin"`, `max_round=2` (verdict + rebuttal), `GroupChatManager` moderator with `system_message` casting it as a synthesizer.
- Terminate on `"CONSENSUS:"` token via `is_termination_msg`.
- Final `AssistantAgent` with `response_format=ClinicalVerdict` produces the structured JSON output for the paper's case study.
- Pin `cache_seed=42`, `temperature=0`, `"model": "gpt-4o-2026-xx-xx"`, and `{"seed": 42}` in `extra_body`.

## Critical gotchas planned around

1. **Dual API surface** — commit to v0 legacy API (`GroupChat`, `GroupChatManager`). The `autogen.beta` event-driven API is still maturing.
2. **Speaker-selection cost** — use `"round_robin"` (deterministic, cheap) instead of `"auto"` which fires an LLM call every turn.
3. **Structured output + tool calling coexistence** — test `response_format=PydanticVerdict` alongside `kg_query` on the chosen provider before building the full pipeline. Anthropic strict mode has subtle constraints.
4. **`cache_seed` is local file cache, not OpenAI `seed`** — pass both for true reproducibility.

## Not cited in primary paper

The primary paper (β) cites MedAgents (Tang et al. ACL 2024) and MDAgents (Kim et al. NeurIPS 2024) as the deliberation-primitive prior art. AG2 is implementation scaffolding, not a cited method. Subsystem H is a case-study appendix / demonstration, not the primary contribution.

## Sources

- [AG2 GitHub](https://github.com/ag2ai/ag2)
- [AG2 Docs](https://docs.ag2.ai/latest/)
- [AG2 v0.9 Release — GroupChat overhaul](https://docs.ag2.ai/latest/docs/blog/2025/04/28/0.9-Release-Announcement/)
- [AG2 Structured Output Notebook](https://docs.ag2.ai/docs/use-cases/notebooks/notebooks/agentchat_structured_outputs)
- [MassGen GitHub](https://github.com/massgen/MassGen)
- [MassGen Docs](https://docs.massgen.ai/en/latest/)
- [MDAgents paper (arXiv:2404.15155)](https://arxiv.org/abs/2404.15155)
- [TeamMedAgents (arXiv:2508.08115)](https://arxiv.org/abs/2508.08115)
- [Microsoft AutoGen → ag2ai split](https://dev.to/maximsaplin/microsoft-autogen-has-split-in-2-wait-3-no-4-parts-2p58)
