# research-journal/

Staging area for two peer-reviewed publications under the Diet-OS program:

- **Primary (β):** *Diet-OS — provenance-grounded agentic harness for clinical dietary/herbal recommendations* → npj Digital Medicine / JAMIA
- **Companion (γ):** *Shrine-KG — unified phytochemistry-nutrition-TCM knowledge graph* → Scientific Data / Database (Oxford)

## Start here

1. [`DESIGN.md`](./DESIGN.md) — consolidated design spec, approved 2026-04-22
2. [`plans/2026-04-22-program.md`](./plans/2026-04-22-program.md) — 7-subsystem program plan with dependencies + sequencing
3. [`plans/2026-04-22-subsystem-a-data-moat.md`](./plans/2026-04-22-subsystem-a-data-moat.md) — first executable plan (TDD)
4. [`shared/`](./shared/) — literature research and audit artifacts shared by both papers

## Folder conventions

- `plans/YYYY-MM-DD-subsystem-<letter>-<name>.md` — detailed TDD plans, one per subsystem
- `primary/` — β manuscript artifacts (outline, figures, tables, related-work); populated in Subsystem G.1
- `companion/` — γ manuscript artifacts; populated in Subsystem G.2
- `shared/` — bibliography + research that informs both papers

## Working rules

- Plans are executable — every code step has concrete file path + code block + test command + commit
- Papers cite code commits by SHA where relevant
- Evaluation artifacts (DietBench-Clinical scenarios, splits) live under `shared/datasets/` once constructed
- Redact credentials; secrets come from Infisical "SyntropyHealth App"
