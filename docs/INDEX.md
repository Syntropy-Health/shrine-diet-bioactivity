# Documentation Index

> Single source of navigation for the unified diet KG. Grouped by audience; each entry has a one-line description so you can locate the right doc in <30 seconds.
>
> **Last refreshed:** 2026-05-07. If you add a doc, link it here.

---

## TL;DR — what is this project?

A **unified diet knowledge graph** spanning macronutrients, foods, herbs, phytochemical compounds, molecular targets, and diseases — aggregated from 7+ open-source datasets, indexed in Neo4j (graph + vector embeddings) via LightRAG, and queried by LLM agents through 5 thin-adapter MCP primitives.

Primary use cases driving the design:
- **A. Symptom → food.** Given a symptom, surface foods/herbs whose bioactives have evidence-graded drug-target activity for the implicated targets/diseases.
- **D. Diet → predicted physiological effects.** Given a recorded diet (foods + portions), aggregate bioactive compound exposure → target modulation → predicted pathway/disease effects.
- **C. Compound mechanism dossier** (free from the same backbone): unified evidence card for any bioactive (e.g. quercetin) — structure, drug-likeness, targets, pathways, food sources.

---

## Newcomer onboarding (read in this order)

| File | One-line description |
|---|---|
| [`README.md`](../README.md) | Project elevator pitch + data sources table + entry points to install / setup |
| [`CLAUDE.md`](../CLAUDE.md) | Repo layout, build commands, and convention guidance for AI-assisted development |
| [`docs/RESEARCHER_GUIDE.md`](RESEARCHER_GUIDE.md) | How researchers should query the KG — persona-first usage manual |
| [`docs/INDEX.md`](INDEX.md) | This file |

---

## Architecture & system design

| File | One-line description |
|---|---|
| [`docs/unified-diet-kg-architecture.md`](unified-diet-kg-architecture.md) | Authoritative diagram of structured-vs-unstructured ingest, entity types, and query flows |
| [`docs/kg-architecture-design.md`](kg-architecture-design.md) | Design rationale for SQLite + LightRAG + Neo4j three-tier architecture, including alternatives rejected |
| [`docs/kg-ingestion-comparison.md`](kg-ingestion-comparison.md) | Comparison of ingest paths (`ainsert_custom_kg` vs LLM extraction) and when to use each |
| [`docs/data-sources-catalog.md`](data-sources-catalog.md) | Per-dataset schema, file format, and join keys for Duke, FooDB, OpenNutrition, CMAUP, TTD, CTD, SymMap, HERB 2.0 |
| [`docs/DATASET_PROVENANCE.md`](DATASET_PROVENANCE.md) | Per-source license, version pin, refresh cadence — the doc a paper reviewer reads |
| [`shrine-diet-bioactivity/docs/integration-guide.md`](../shrine-diet-bioactivity/docs/integration-guide.md) | How the MCP thin-adapter integrates with downstream consumer apps |
| [`mcp/README.md`](../mcp/README.md) | kg-mcp gateway: deployment URL, auth flow (static API key / Clerk JWT), tool catalog |

---

## Architectural Decision Records (ADRs)

ADRs capture decisions that meaningfully shape the system; each is dated, justified, and lists alternatives considered.

| ADR | Title |
|---|---|
| [0001](adr/0001-vector-storage-on-aura.md) | Vector storage on Neo4j Aura (vs separate vector DB) |
| 0002–0006 | _Reserved — see git history; not yet captured as ADRs_ |
| [0007](adr/0007-compound-identity-bridge.md) | Compound identity bridge + ChEMBL evidence layer (Phase 1 drug-bioactive) |

> **Convention:** new ADRs use the next free number, never reuse a number. If a decision is reversed, write a new ADR that supersedes the old one (don't edit the old one).

---

## Active feature specs & plans

These describe in-flight or recently-shipped work. Each pairs with an implementation plan and a runbook in `.claude/runs/`.

| Spec | Status |
|---|---|
| [`docs/superpowers/specs/2026-05-06-drug-bioactive-bridge-design.md`](superpowers/specs/2026-05-06-drug-bioactive-bridge-design.md) | Phase 1 — landed via PR #19; ADR 0007; runbook at `.claude/runs/20260506-013000-drug-bioactive-bridge/` |
| [`docs/KG_COMPLETENESS_AUDIT.md`](KG_COMPLETENESS_AUDIT.md) | KG audit (this PR) — identifies 5 concrete completeness gaps + remediation specs |

PRD/plan/report/review documents from earlier phases live in `.claude/PRPs/{prds,plans,reports,reviews}/`. The legacy plans under `.claude/PRPs/plans/completed/` are kept for archaeology but should not be the primary reference for current architecture.

---

## Data engineers / ingest pipelines

| File | One-line description |
|---|---|
| [`shrine-diet-bioactivity/Makefile`](../shrine-diet-bioactivity/Makefile) | Canonical entrypoints: `make download`, `make build`, `make migrate`, `make food-bridge`, `make build-identity`, `make build-bioactivity`, `make lightrag-ingest-*` |
| [`docs/data-audit-results.md`](data-audit-results.md) | OpenNutrition coverage stats (calories 95.5%, protein 74.7%, etc.) — informs `data_completeness` flagging |
| [`docs/kg-coverage-audit.md`](kg-coverage-audit.md) | HDI-Safe-50 vs public references coverage audit |
| [`docs/KG_COMPLETENESS_AUDIT.md`](KG_COMPLETENESS_AUDIT.md) | This audit — entity-type counts, gap analysis vs use cases A/D, remediation specs |

---

## Researchers, paper, evaluation

| File | One-line description |
|---|---|
| [`research-journal/README.md`](../research-journal/README.md) | Top of the research journal — design, handoffs, primary work |
| [`research-journal/DESIGN.md`](../research-journal/DESIGN.md) | Initial program spec |
| [`research-journal/DESIGN-PIVOT-2026-04-22.md`](../research-journal/DESIGN-PIVOT-2026-04-22.md) | Pivot rationale (clinical research team as primary impl) |
| [`research-journal/HANDOFF-research-via-mcp.md`](../research-journal/HANDOFF-research-via-mcp.md) | How researchers use the staged MCP gateway |
| [`research-journal/HANDOFF-blockers-to-engineering.md`](../research-journal/HANDOFF-blockers-to-engineering.md) | Open blockers needing engineering attention |
| [`research-journal/primary/`](../research-journal/primary/) | Paper drafts (v1) — figures, tables, references |
| [`docs/TESTING.md`](TESTING.md) | Testing strategy: unit (vitest, pytest), integration, E2E patterns |

---

## Tenant / clinical layer

| File | One-line description |
|---|---|
| [`shrine-diet-bioactivity/docs/clinical-integration-notes.md`](../shrine-diet-bioactivity/docs/clinical-integration-notes.md) | Why clinical/culinary reasoning lives in the agent layer, not the MCP surface |
| [`shrine-diet-bioactivity/agents/`](../shrine-diet-bioactivity/agents/) | AG2 multi-agent panel — triage, role verdicts, kg_query tool (formerly described in the deleted top-level AGENT.md) |

---

## Operations / deployment

| File | One-line description |
|---|---|
| [`mcp/README.md`](../mcp/README.md) | kg-mcp gateway deploy: Railway URL, auth setup, healthcheck |
| [`research-journal/HANDOFF-railway-deploy.md`](../research-journal/HANDOFF-railway-deploy.md) | Railway deployment runbook for the gateway |
| [`docs/graphiti-neo4j-guide.md`](graphiti-neo4j-guide.md) | _Legacy_ — Graphiti PoC notes (superseded by LightRAG; kept for context only) |

---

## Conventions

- **One canonical doc per topic.** If you find duplicate coverage, consolidate and link.
- **Cross-reference using relative paths** so renames are easier to track.
- **ADRs are append-only.** Reverse a decision by writing a new ADR; never edit a closed one.
- **Specs live under `docs/superpowers/specs/`** and follow `YYYY-MM-DD-<topic>-design.md` naming.
- **Runbooks live under `.claude/runs/<run-id>/`** when they accompany a dispatch-pvp execution.
- **Stale references** are a bug. If a doc points at a moved/deleted file, fix the link or remove the reference.

---

## Known gaps in this index

- ADRs 0002–0006 do not exist; the numbering jumps. Either re-number or add stub ADRs explaining what wasn't captured.
- `.claude/PRPs/plans/` has both active and completed plans, but the in-tree completed/ subdir is a partial archive — some "completed" plans live in the parent.
- No top-level `CHANGELOG.md` exists; release-level changes are tracked only via git tags + paper drafts.

---

## Phase 3 — disease canonicalization (added 2026-05-08)

| File | One-line description |
|---|---|
| [`adr/0008-disease-canonicalization.md`](adr/0008-disease-canonicalization.md) | Architectural decision record — promotes Disease to a first-class unified entity |
| [`superpowers/specs/2026-05-08-disease-canonicalization-design.md`](superpowers/specs/2026-05-08-disease-canonicalization-design.md) | Phase 3 design spec |

Run via `make build-disease-canonical && make load-ctd`. See ADR 0008 for live-DB outcomes (24K canonical diseases, 2.9M evidence rows with 94% PubMed citation preservation).

---

## Phase 4 — KEGG pathway overlay (added 2026-05-08)

| File | One-line description |
|---|---|
| [`adr/0009-kegg-pathway-overlay.md`](adr/0009-kegg-pathway-overlay.md) | Architectural decision record — KEGG pathway entity + 2 relationships |
| [`superpowers/specs/2026-05-08-kegg-pathway-overlay-design.md`](superpowers/specs/2026-05-08-kegg-pathway-overlay-design.md) | Phase 4 design spec |

Run via `make build-kegg-pathways`. **License:** KEGG is academic-use-only — see ADR 0009 for commercial-deployment opt-out path.

---

## Phase 5 — diet scoring (added 2026-05-08)

| File | One-line description |
|---|---|
| [`adr/0010-diet-scoring.md`](adr/0010-diet-scoring.md) | Architectural decision record — diet scoring algorithm + weight rationale |
| [`superpowers/specs/2026-05-08-diet-scoring-design.md`](superpowers/specs/2026-05-08-diet-scoring-design.md) | Phase 5 design spec |

Run via `make score-diet-sample` or `python scripts/score_diet.py --diet '{...}'`. **Closes the audit.**
