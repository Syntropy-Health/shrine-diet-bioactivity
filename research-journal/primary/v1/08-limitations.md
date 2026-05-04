# 8. Limitations

## 8.1 Single-author gold standard at n=40

DietResearchBench-Clinical v1 uses single-author gold annotations across 40 scenarios with no inter-annotator agreement (IAA) measurement. A v2 expansion (n=200, two-annotator design with κ ≥ 0.6 gating and calibration-aware Platt/isotonic scoring) is in progress as a companion paper [@v2benchmark2026].

## 8.2 Free-tier 30B LLM — not a calibration ceiling

Free-tier Nemotron-3-nano-30B has known JSON-quality issues at long contexts and is rate-limited to 20 RPM. We adopt this constraint deliberately to validate the architectural-headline framing under cost-zero inference. v2 ablates against Qwen-3-235B-Instruct via Cerebras (1M tok/day free tier) and paid-tier alternatives (Sonnet 4.6).

## 8.3 HDI Recall is in-panel, not universe-recall

Per the KG coverage audit (`docs/kg-coverage-audit.md`), HDI-Safe-50 covers 86.2% of the curated public HDI universe known to NIH ODS and NCCIH (n=15 reference pairs). Reported HDI Recall is therefore in-panel recall against the curated v1 panel, not absolute recall against the broader herb-drug interaction literature.

## 8.4 Source-attribution provenance, not Cypher round-trip

Provenance metric uses the source-id-prefix proxy (`cmaup:`, `duke:`, `herb2:`, `symmap:`, `hdi-safe-50:`) rather than full Cypher round-trip verification against Aura. Edges retrieved through Layer-B/C MCP traversals are KG-faithful by construction; Cypher verification for adversarial cases is deferred to v2.

## 8.5 AG2-specific orchestration

diet_os is implemented in AG2 v0.12. Pydantic-AI re-ports (estimated 1.5-day migration; native MCP streamable-HTTP, Logfire observability) are deferred to v2 as a framework ablation.
