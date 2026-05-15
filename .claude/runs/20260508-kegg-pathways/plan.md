<!-- harden-plan: hardened on 2026-05-08T20:00:00Z. KEGG REST API verified reachable. -->

# KEGG Pathway Overlay — Implementation Plan (HARDENED)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans + test-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Add a self-contained KEGG pathway layer to the KG. Closes the use-case-D mechanistic chain (Food→Compound→Pathway→Gene→Target→Disease) by introducing `Pathway` as a first-class entity and `PATHWAY_INCLUDES_TARGET` / `COMPOUND_IN_PATHWAY` relationships.

**Architecture:** Three new SQLite tables (`kegg_pathways`, `kegg_compound_pathways`, `kegg_pathway_genes`) populated from KEGG REST API. LightRAG schema gains 1 new entity + 2 new relationships. Self-contained: no Phase 1 ingest dependency for the gene-symbol-anchored path; the compound-anchored path activates lazily when `compound_identity` is populated.

**Tech Stack:** Python 3.10+, sqlite3, httpx (already in env), LightRAG, pytest.

**Project root:** `shrine-diet-bioactivity/` (single nesting from worktree root).

**Secrets needed:** none. KEGG REST API is unauthenticated for academic use.

**Stacks on:** PR #25 (Phase 3).

**Harden-plan probes:**
- ✅ KEGG REST API reachable (HTTP 200 on `/list/pathway`)
- ✅ Sample pathway list parses cleanly (TSV: `hsa01100\tMetabolic pathways - Homo sapiens (human)`)
- ⚠ `compound_identity` table not yet populated on live DB → `COMPOUND_IN_PATHWAY` will be 0 rows initially. Spec acknowledges this; gate floor on `PATHWAY_INCLUDES_TARGET` only.

---

## File map

**Created:**
- `shrine-diet-bioactivity/lightrag/kegg_client.py` — pure HTTP client + parsers
- `shrine-diet-bioactivity/scripts/build_kegg_pathways.py` — orchestrator CLI
- `shrine-diet-bioactivity/lightrag/tests/test_kegg_client.py` — parser unit tests
- `shrine-diet-bioactivity/lightrag/tests/test_kegg_ingest.py` — integration test
- `docs/adr/0009-kegg-pathway-overlay.md`

**Modified:**
- `shrine-diet-bioactivity/scripts/build-herbal-db.ts` — add 3 KEGG table DDL
- `shrine-diet-bioactivity/lightrag/entity_schema.py` — `Pathway` entity + 2 relationships
- `shrine-diet-bioactivity/lightrag/tests/test_kg_completeness_gates.py` — Phase 4 gates
- `shrine-diet-bioactivity/Makefile` — `build-kegg-pathways` target
- `docs/DATASET_PROVENANCE.md` — KEGG license note
- `docs/KG_COMPLETENESS_AUDIT.md` — Phase 4 closeout
- `docs/INDEX.md` — link to new ADR
- `docs/ARCHITECTURE.md` — update phase roadmap; add Pathway to entity graph

---

## Task 1: KEGG REST client (pure HTTP + parsers)

**Files:**
- Create: `lightrag/kegg_client.py`
- Create: `lightrag/tests/test_kegg_client.py`

KEGG returns TSV. Parsers must handle the standard formats:
- `/list/pathway/hsa` → `path:hsa01100\tMetabolic pathways - Homo sapiens (human)`
- `/link/cpd/pathway/hsa` → `path:hsa00010\tcpd:C00031`
- `/link/hsa/pathway` → `path:hsa00010\thsa:1234`
- `/find/genes/<ids>` → `hsa:1234\tGCK; HK4; HXK4; ...`

- [ ] **RED**: Write parser unit tests covering each TSV format with realistic samples (including pathway names with embedded dashes/parens, gene-aliases pipe-separated)
- [ ] **GREEN**: Implement `KeggClient` with methods `list_pathways(organism="hsa")`, `list_compound_pathway_links(...)`, `list_pathway_gene_links(...)`, `resolve_gene_symbols(kegg_gene_ids)`. Use httpx with timeout + retry. Parsers as pure functions for testability.
- [ ] **REFACTOR**: Cache hits to disk (`data_local/kegg_cache/<endpoint>.tsv`) so re-runs don't hit KEGG.

**Acceptance:** ≥6 unit tests covering each parser + the cache layer. Mocked HTTP — no live calls in unit tests.

---

## Task 2: SQLite schema DDL + invariant tests

**Files:**
- Modify: `scripts/build-herbal-db.ts`
- Create: `lightrag/tests/test_kegg_schema.py`

DDL block from spec §5.1 with FK + index constraints.

- [ ] **RED**: schema invariant tests (FK enforcement, PK collision behavior)
- [ ] **GREEN**: insert DDL into build-herbal-db.ts; apply to live DB
- [ ] **Verify**: in-memory schema test + live-DB sanity probe

---

## Task 3: Orchestrator CLI

**Files:**
- Create: `scripts/build_kegg_pathways.py`
- Create: `lightrag/tests/test_kegg_ingest.py`
- Modify: `Makefile` (`build-kegg-pathways` target)

- [ ] **RED**: integration test against in-memory DB + mocked KeggClient
- [ ] **GREEN**: orchestrator pulls 3 KEGG endpoints, writes to 3 tables in idempotent transaction
- [ ] **Live run**: against live DB; expect ~340 pathways, ~5K compound-pathway links, ~30K pathway-gene links

---

## Task 4: LightRAG schema additions

**Files:**
- Modify: `lightrag/entity_schema.py`
- Create: `lightrag/tests/test_kegg_entity.py`

- [ ] Add `Pathway` to `ENTITY_TYPES`; `describe_pathway()` renders `name (category, organism)`
- [ ] Add `COMPOUND_IN_PATHWAY` and `PATHWAY_INCLUDES_TARGET` to `RELATIONSHIP_TYPES`
- [ ] Add `describe_relationship` branches for both new types
- [ ] Test against live DB: `Pathway` entity query returns ≥300 rows; `PATHWAY_INCLUDES_TARGET` returns ≥1,000

---

## Task 5: Audit-gate updates

**Files:**
- Modify: `lightrag/tests/test_kg_completeness_gates.py`

Three new gates:

```python
def test_kegg_pathways_table_populated(db_conn):
    n = db_conn.execute("SELECT COUNT(*) FROM kegg_pathways").fetchone()[0]
    assert n >= 300, f"kegg_pathways has {n} rows; expected ≥300 (KEGG hsa baseline)"

def test_kegg_pathway_gene_resolution_coverage(db_conn):
    total = db_conn.execute("SELECT COUNT(*) FROM kegg_pathway_genes").fetchone()[0]
    with_symbol = db_conn.execute(
        "SELECT COUNT(*) FROM kegg_pathway_genes WHERE gene_symbol IS NOT NULL"
    ).fetchone()[0]
    assert total > 0
    assert with_symbol / total >= 0.80, (
        f"only {with_symbol/total:.1%} of KEGG genes have HUGO symbols; expected ≥80%"
    )

def test_pathway_includes_target_query_runs(db_conn):
    # Closes Phase 4 — pathway↔target join via gene_symbol works at scale.
    n = db_conn.execute(
        "SELECT COUNT(*) FROM kegg_pathway_genes kpg "
        "JOIN targets t ON t.gene_symbol = kpg.gene_symbol"
    ).fetchone()[0]
    assert n >= 1_000, f"only {n} pathway-target joins; expected ≥1000"
```

---

## Task 6: ADR + docs

**Files:**
- Create: `docs/adr/0009-kegg-pathway-overlay.md`
- Modify: `docs/DATASET_PROVENANCE.md` (KEGG license box)
- Modify: `docs/KG_COMPLETENESS_AUDIT.md` (Phase 4 section)
- Modify: `docs/ARCHITECTURE.md` (add Pathway to entity graph; update roadmap)
- Modify: `docs/INDEX.md`

---

## Task 7: Final coverage + smoke + PR

- [ ] Run all new tests with coverage: ≥80% on `kegg_client.py`
- [ ] Live-DB sanity check on full chain query (Food → … → Disease via KEGG path)
- [ ] Lint + commit + push + open PR stacked on #25

---

## Self-review notes

- **Spec coverage:** §5.1 schema → Task 2; §5.2 ingest → Tasks 1+3; §5.3 LightRAG → Task 4; §6 DoD → Task 5.
- **Type consistency:** `kegg_compound_id` is TEXT (KEGG's `Cxxxxx` format); `kegg_pathway_id` TEXT (`hsaxxxxx`); `gene_symbol` TEXT.
- **License posture:** academic-only flag in DATASET_PROVENANCE.md; build-time toggle so commercial deployments can opt out cleanly.
- **Phase 1 decoupling:** `COMPOUND_IN_PATHWAY` returning 0 rows initially is acceptable; gate is on `PATHWAY_INCLUDES_TARGET` which works without Phase 1.
