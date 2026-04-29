# Repo Zombie-Module Audit & Reorganization Proposal

_Authored 2026-04-26. Scope: `apps/shrine-diet-bioactivity/` worktree. Companion to the v1 post-mortem._

This memo classifies every top-level module/submodule by **runtime role**, identifies zombies (modules referenced by docs/Makefile but not by code), and proposes a reorganization. **No moves are executed in this memo.** The recommended PR sequencing in §6 must run *after* the v1 eval re-run lands, so module-path breakage cannot be confused with eval failures.

---

## 1. Classification

| Path | Type | `.gitmodules` declares | Runtime role | Status |
|---|---|---|---|---|
| `lightrag/` (top-level) | git submodule, HKUDS upstream | "Active dependency" | **Core framework.** 23 Python imports of `from lightrag…` in `shrine-diet-bioactivity/lightrag/` (project wrapper code) — `Neo4JStorage` subclassed, graph routes mounted on `scoped_server.py`. | ✅ Active — but **mis-placed**. Should live under `libs/`. |
| `mcp-opennutrition/` (top-level) | git submodule, deadletterq upstream | "Reference-only — NOT wired into runtime" | None. Used historically to derive food → KG mapping; the resulting data already lives in Aura. | ⚠️ **Reference data source.** Move to `data/mcp-opennutrition/` per user 2026-04-26. |
| `graphiti/` (top-level) | _not_ in `.gitmodules` (removed in commit 77c5e57) | n/a | Superseded by LightRAG. No Python import path to graphiti from project code. Only references: 4 `graphiti-*` Makefile targets marked "Legacy". | ❌ **Dead code zombie.** |
| `mcp-knowledge-graph/` (top-level) | _not_ in `.gitmodules`, project-owned code | n/a | Currently an empty scaffold (`.ruff_cache/` only — no source files). Per user 2026-04-26: this is the intended future home for the MCP-protocol gateway over the LightRAG KG (the actual KG service is currently the FastAPI `scoped_server.py` exposing `/health`, `/query`, `/documents/custom_kg`, `/graphs`). | 🔧 **Rename to `mcp/`.** Future home for the KG MCP gateway. |
| `shrine-diet-bioactivity/` (nested, project package) | n/a | n/a | The actual application code (eval, agents, lightrag wrappers, mcp_server, data, Makefile). | ✅ Active. Keep. |
| `research-journal/` | n/a | n/a | Plans, results, datasets, this memo. | ✅ Active. Keep. |
| `scripts/`, `docs/`, top-level `.claude/` | n/a | n/a | Operator scripts, top-level docs, Claude command/skill config. | ✅ Active. Keep. |

---

## 2. Evidence by zombie

### 2.1 `mcp-opennutrition/` — reference zombie

`.gitmodules` is unambiguous (verbatim):
```
# Reference-only: kept as upstream source of OpenNutrition's TSV→KG
# mapping methodology. NOT wired into runtime — the shrine-diet-bioactivity
# MCP thin-adapter no longer composes over the OpenNutrition MCP server.
```

But five docs **still describe it as live runtime infra**, all with broken paths (`data/mcp-opennutrition/` doesn't exist; module is at top-level `mcp-opennutrition/`):

| File | Drift |
|---|---|
| `PRD.md:39-40,113` | "Source: `data/mcp-opennutrition/` (git submodule)" + path in architecture diagram |
| `AGENT.md:43,114-116,232` | Lists it as Active, configures it as a mounted MCP server |
| `README.md:33,106,172-173,183-198,334` | Describes it as a `build/index.js` MCP entrypoint with mount instructions |
| `DATA_SOURCES.md:42,46` | "Status: Git submodule at `data/mcp-opennutrition/`" |
| `CLAUDE.md:17,52` | "Git submodule: OpenNutrition MCP server (326k+ foods, 90 nutrient keys)" + build target |

**Disposition (decided 2026-04-26):** Move the submodule to `data/mcp-opennutrition/`. Co-locate it with the dataset manifest already at `shrine-diet-bioactivity/data/manifest.yaml` and any extracted per-source documentation. Scrub all "active runtime MCP server" framing from PRD.md / AGENT.md / README.md / DATA_SOURCES.md / CLAUDE.md, replacing it with "vendored data source — methodology and raw fixtures used during ingest." This treats `data/` as the canonical location for upstream dataset sources that feed the KG (whether currently mounted as MCP servers or not).

### 2.2 `graphiti/` — dead code zombie

`.gitmodules` no longer lists graphiti (commit `77c5e57`: "chore: remove redundant usda-fdc-data submodule" appears to be from a sister repo, but the same cleanup pattern was applied here per the 04-12 session notes). The directory was *not* deleted alongside the submodule entry.

Live references:
- `shrine-diet-bioactivity/Makefile:33,297-331` — 4 targets: `graphiti-setup`, `graphiti-dry-run`, `graphiti-ingest`, `graphiti-ingest-direct`. All marked "Legacy" but still in `.PHONY` and discoverable via `make help`.
- `shrine-diet-bioactivity/data/herb2/herbs.json:6188,6195` — false-positive substring matches in botanical Latin names (`Herba andrographitis`). Not real references.
- Zero Python imports.

**Proposed disposition:** Delete `graphiti/` directory and the 4 Makefile targets. Retain a one-paragraph note in `docs/kg-ingestion-comparison.md` documenting the LightRAG ↔ Graphiti decision (already exists per 04-12 session) so the design rationale isn't lost when the code goes.

### 2.3 `mcp-knowledge-graph/` — rename to `mcp/` (decided 2026-04-26)

Current state: empty scaffold. `src/kg_mcp/tools/` directory exists but contains zero source files; `tests/unit/` is empty. Only filesystem presence is `.ruff_cache/`.

The actual live KG service today is the FastAPI app in `shrine-diet-bioactivity/lightrag/scoped_server.py` — `GET /health`, `POST /query`, `POST /documents/custom_kg`, `GET /graphs`, `GET /graph/label/popular`. AG2's `kg_query` tool consumes this HTTP API.

**Disposition:** Rename `mcp-knowledge-graph/` → `mcp/`. This becomes the future home for an MCP-protocol gateway that wraps the existing FastAPI service (or absorbs it). The rename is cheap (cache-only directory move) and stops the name from misleading reviewers into thinking there's a working KG-MCP server when only the FastAPI HTTP service exists today.

**Follow-on (not part of the rename PR):** decide whether the LightRAG KG MCP gateway is built (a) by porting `scoped_server.py`'s endpoints to MCP tools under `mcp/`, or (b) by writing a thin MCP-over-HTTP shim in `mcp/` that delegates to the FastAPI service. (b) is faster, (a) is cleaner. Out of scope for the rename.

### 2.4 `lightrag/` (top-level) — active but mis-placed

23 Python imports across `shrine-diet-bioactivity/lightrag/*.py`:
- `from lightrag import LightRAG`
- `from lightrag.utils import EmbeddingFunc, logger`
- `from lightrag.llm.{ollama,openai} import …`
- `from lightrag.kg.neo4j_impl import READ_RETRY, Neo4JStorage`

This is unambiguously a third-party framework dependency. Two cosmetic problems with its current location:

1. **Naming collision.** Both the framework submodule (`lightrag/`) and the project's wrapper package (`shrine-diet-bioactivity/lightrag/`) live one path component apart. Readers (and tools like `pytest`'s sys.path discovery) confuse them.
2. **Top-level placement implies it's application code.** It is not — it's a vendored framework with its own Dockerfile, CI, and license.

**Proposed disposition:** Move to `libs/lightrag/`. Update `.gitmodules` path. Verify imports still resolve (they should — the import path is the inner Python package name `lightrag`, which is unaffected by the directory move; only the editable-install or `PYTHONPATH` configuration changes).

---

## 3. Drift cost (why this matters now)

If we hand the repo to a new contributor today they will:
1. Clone the submodules (per CLAUDE.md instruction `git submodule update --init --recursive`).
2. Read AGENT.md / README.md and try to wire `mcp-opennutrition` into their MCP client at the path `data/mcp-opennutrition/build/index.js` — **fails, path doesn't exist**.
3. Run `make help` and discover `graphiti-*` targets next to `lightrag-*` targets, with no signal that one is dead.
4. See two `lightrag/` paths and not know which is the framework vs. the wrapper.

Every one of these is a 30-minute confused-onboarding tax. They compound for paper reviewers reproducing our work.

---

## 4. Constraints on the reorganization PR

- **MUST not break the v1 re-run path.** All of `shrine-diet-bioactivity/lightrag/{ingest_unified,scoped_server,scoped_neo4j_storage,bootstrap_scope}.py` and the `make lightrag-*` targets must work post-move.
- **MUST land after the v1 re-run is green.** See post-mortem §8.
- **MUST update CLAUDE.md, AGENT.md, README.md, PRD.md, DATA_SOURCES.md** in the same PR — keeping docs as a separate follow-up causes the next round of drift.
- **SHOULD preserve git history** for moved directories using `git mv`. Submodule moves require `.gitmodules` edits + `git submodule sync`; this is an irreversible-feeling operation, so confirm with user before execution.
- **SHOULD NOT bundle disposition of `mcp-knowledge-graph/` with the other moves** — it's a separate question awaiting a user call.

---

## 5. Final layout (decided 2026-04-26)

```
apps/shrine-diet-bioactivity/
├── libs/
│   └── lightrag/                     ← moved from top-level (HKUDS submodule)
├── data/
│   ├── manifest.yaml                 ← existing per-source dataset manifest
│   ├── mcp-opennutrition/            ← moved here (deadletterq submodule, ref-only)
│   └── <per-source docs>/            ← extracted documentation per dataset indexed into KG
├── mcp/                              ← renamed from mcp-knowledge-graph; future MCP gateway over LightRAG KG
├── shrine-diet-bioactivity/          ← project package, unchanged
│   ├── lightrag/                     ← project's wrapper code (scoped_server, ingest, etc.)
│   ├── agents/                       ← AG2 panel (Subsystem H)
│   ├── eval/                         ← Subsystem F harness
│   ├── data/                         ← project's working data (manifest.yaml lives here)
│   └── …
├── research-journal/                 ← unchanged
├── scripts/                          ← unchanged
├── docs/                             ← unchanged
├── .claude/                          ← unchanged
├── CLAUDE.md, AGENT.md, README.md, PRD.md, DATA_SOURCES.md   ← scrubbed
└── (REMOVED) graphiti/
```

**Note on `data/` location:** the project already has `shrine-diet-bioactivity/data/manifest.yaml` (the inner package's data dir) which contains the per-dataset manifest. The new top-level `data/` is for **upstream source vendoring** — `mcp-opennutrition` and any extracted source-method documentation. The two `data/` directories serve different purposes: top-level is "where vendored upstream sources live", inner is "where the project's working dataset bundles live" (Duke CSVs, HERB2 JSON, etc.). If this duplication becomes confusing, a follow-up PR can consolidate, but not in the initial reorg.

---

## 6. PR sequencing

**Order matters and ALL PRs land *after* the v1 eval re-run is green** (post-mortem §8). Each PR is small enough to review and revert independently.

1. **PR-A — graphiti deletion** (smallest, no path implications)
   - `git rm -r graphiti/`
   - Remove the 4 `graphiti-*` targets from `Makefile` + `.PHONY` line
   - Add/confirm a 1-paragraph note in `docs/kg-ingestion-comparison.md` documenting the LightRAG ↔ Graphiti decision
   - CI: green if existing tests pass.

2. **PR-B — `mcp-opennutrition` → `data/mcp-opennutrition/` + doc scrub**
   - `git mv mcp-opennutrition data/mcp-opennutrition` + `git submodule sync`
   - Reframe in PRD/AGENT/README/DATA_SOURCES/CLAUDE: "vendored upstream data source" — drop "active MCP server" claims
   - Add per-source documentation under `data/<source>/README.md` for each dataset already indexed (Duke, SymMap 2.0, HERB 2.0, FooDB, OpenNutrition, HDI-Safe-50) — link to `manifest.yaml` entries
   - CI: green if no MCP client integration tests assume the old path (none found).

3. **PR-C — `mcp-knowledge-graph` → `mcp/` rename**
   - `git mv mcp-knowledge-graph mcp` (cache-only directory at the moment; cheap)
   - Add `mcp/README.md` stating the intent: "future MCP-protocol gateway over the LightRAG KG; currently a scaffold. Live KG service is `shrine-diet-bioactivity/lightrag/scoped_server.py`'s FastAPI app."
   - CI: no-op.

4. **PR-D — `lightrag` framework → `libs/lightrag/`**
   - `git mv lightrag libs/lightrag` + `git submodule sync`
   - Verify framework imports still resolve (Python package name `lightrag` is independent of dir location; only editable-install + Makefile `cd` paths change)
   - Update `Makefile` `cd lightrag` (top-level) refs → `cd libs/lightrag`. **Do not touch** `cd lightrag` references inside the nested `shrine-diet-bioactivity/Makefile` that target the project's wrapper package.
   - Update CLAUDE.md, AGENT.md, README.md
   - CI: full test suite + a smoke ingest dry-run gate against Aura.

---

## 7. Resolved 2026-04-26

- `mcp-knowledge-graph/` → rename to `mcp/`; future home for KG MCP gateway.
- `mcp-opennutrition/` → keep, move to `data/mcp-opennutrition/` co-located with manifest + per-source docs.
- `libs/` (active framework) vs `data/` (reference data sources) split adopted. No `vendor/` directory.

All four PRs (A → D) gated behind a green v1 eval re-run.
