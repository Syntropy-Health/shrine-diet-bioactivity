# shrine-diet-bioactivity

A **unified diet knowledge graph** spanning macronutrients, foods, herbs, phytochemical compounds, molecular targets, and diseases. Aggregates 7+ authoritative open datasets into a semantic KG powered by LightRAG (Neo4j graph + vector embeddings), queryable by LLM agents via a Python MCP gateway and a TypeScript thin-adapter.

Data foundation for the [Diet Insight Engine](https://github.com/Syntropy-Health/diet-insight-engine) Symptom-Diet Optimizer (SDO). Part of the [Syntropy Health](https://github.com/Syntropy-Health) ecosystem.

## Start here

| Audience | Read |
|---|---|
| AI coding agent | [`CLAUDE.md`](CLAUDE.md) |
| Newcomer / architect / researcher | [`docs/INDEX.md`](docs/INDEX.md) — audience-grouped navigation |
| KG remediation roadmap | [`docs/KG_COMPLETENESS_AUDIT.md`](docs/KG_COMPLETENESS_AUDIT.md) |
| Test-coverage uplift plan | [`research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md`](research-journal/plans/2026-05-08-integration-test-coverage-uplift-plan.md) |

## Data sources

| Source | Description | Items | Key required |
|---|---|---|---|
| **USDA FoodData Central** | Public-domain US nutrition database | 900k+ foods | No |
| **OpenNutrition (vendored fixture)** | Nutrition data; previously a submodule, now embedded under `shrine-diet-bioactivity/data/` | 300k+ foods | No |
| **NIH DSLD** | Dietary supplement label database | 100k+ products | No |
| **ChEMBL 36 + UniChem + PubChem** | Compound-identity bridge → drug-target bioactivity (see [`docs/adr/0007-compound-identity-bridge.md`](docs/adr/0007-compound-identity-bridge.md)) | ~25k active compounds | No |
| **Duke / FooDB / CMAUP / TTD / CTD / SymMap / HERB 2.0** | Herb-compound-target-disease evidence (Phase 1–6.5) | Multi-million edges | No |

## Build

```bash
# Submodules — lightrag only (upstream HKUDS/LightRAG)
git submodule update --init --recursive

# Application package: data pipeline + LightRAG ingest
cd shrine-diet-bioactivity && make setup

# kg-mcp Python gateway tests
cd mcp && python3 -m pytest -m unit
```

Full build/setup commands and architecture diagrams: see [`CLAUDE.md`](CLAUDE.md).

## Integration

- [`Syntropy-Health/diet-insight-engine`](https://github.com/Syntropy-Health/diet-insight-engine) — Symptom-Diet Optimizer (SDO)
- Internal: AG2 multi-agent panel in [`shrine-diet-bioactivity/agents/`](shrine-diet-bioactivity/agents/) consumes the KG via the gateway

## Licenses

- USDA FoodData Central — Public Domain (US Government)
- NIH DSLD — Public Domain (US Government)
- OpenNutrition fixture — MIT (upstream license preserved)
- Scripts and documentation — MIT
