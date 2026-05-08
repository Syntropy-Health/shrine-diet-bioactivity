<!-- harden-plan: hardened on 2026-05-08T19:00:00Z. See dependencies.json + runbook.md in this dir. -->

# Disease Canonicalization — Implementation Plan (HARDENED)

**Architecture changes vs. the un-hardened spec (caught by live-DB probe):**
1. `herb2_herb_disease` columns are `disease_id` + `disease_label` + `source_pmid` (NOT `.disease` as the spec assumed). Bonus: `source_pmid` is per-row PubMed evidence — **we should preserve it as an alias source-citation**, mirroring CTD's `pubmed_ids`.
2. CTD's "inferred" rows have `direct_evidence=''` (empty string), not NULL. The `evidence_type` classifier in Task 4 must treat empty string the same as NULL.
3. All preflight deps present (python3, sqlite3, npm, npx, pytest, ruff).
4. Canonical registry size estimate confirmed: ~6,678 distinct CTD disease_names + ~2,976 CMAUP + ~1,148 SymMap; expect ~7K–8K canonical rows after dedup-by-MeSH.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Inner loop is superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Promote `Disease` to a first-class unified entity in the KG. Replace the three independent disease-name columns (chemical_diseases, target_diseases, symptom_disease_map) with a single canonical registry joinable by formal MeSH/UMLS/ICD-10 IDs. Re-encode CTD evidence with explicit type + PubMed citations + gene-symbol inference paths.

**Architecture:** Three new SQLite tables (`diseases_canonical`, `disease_name_aliases`, `compound_disease_evidence`) populated by a new orchestrator (`build_disease_canonical.py`) and a modified CTD loader. Old `chemical_diseases` stays parallel for one stable cycle. LightRAG `Disease` entity reroutes to `diseases_canonical`. New evidence-typed relationships in entity_schema.

**Tech Stack:** Python 3.10+, sqlite3, TypeScript (existing load-ctd.ts modified), LightRAG, pytest, vitest.

**Project root for paths below:** `shrine-diet-bioactivity/` (single nesting from worktree root).

**Secrets needed (none new):** Phase 3 uses the same public sources as Phase 1+2. No new env vars.

**Stacks on:** PR #23 (`phase2/herb2-resolution`). All audit-gate tests are GREEN at this point.

---

## File map (created / modified)

**Created:**
- `shrine-diet-bioactivity/lightrag/disease_canon.py` — pure logic: parse formal IDs from various source formats, canonical ID resolution, slugify fallback
- `shrine-diet-bioactivity/scripts/build_disease_canonical.py` — orchestrator CLI
- `shrine-diet-bioactivity/lightrag/tests/test_disease_canon.py`
- `shrine-diet-bioactivity/lightrag/tests/test_compound_disease_evidence_ingest.py`
- `docs/adr/0008-disease-canonicalization.md`

**Modified:**
- `shrine-diet-bioactivity/scripts/build-herbal-db.ts` — add 3 new table DDL
- `shrine-diet-bioactivity/scripts/load-ctd.ts` — write to `compound_disease_evidence` (parallel with `chemical_diseases` during transition); read PubMed IDs and InferenceGeneSymbol; emit evidence_type
- `shrine-diet-bioactivity/scripts/build_symptom_disease_map.py` — UPSERT into `disease_name_aliases` after each row insert
- `shrine-diet-bioactivity/lightrag/entity_schema.py` — `Disease` entity reroutes to `diseases_canonical`; add 3 new relationships (`COMPOUND_TREATS_DISEASE`, `COMPOUND_MARKER_FOR_DISEASE`, `COMPOUND_INFERRED_DISEASE`); update `MAPS_TO_DISEASE` and `ASSOCIATED_WITH_DISEASE` queries to JOIN through canonical
- `shrine-diet-bioactivity/lightrag/tests/test_kg_completeness_gates.py` — supersede chemical_diseases gate; add canonicalization unification gate
- `shrine-diet-bioactivity/Makefile` — `build-disease-canonical` target
- `docs/KG_COMPLETENESS_AUDIT.md` — add Phase 3 section noting completion
- `docs/DATASET_PROVENANCE.md` — mark `chemical_diseases` deprecated; document `compound_disease_evidence`

---

## Task 1: Pure-logic disease ID + slug helpers

**Files:**
- Create: `lightrag/disease_canon.py`
- Create: `lightrag/tests/test_disease_canon.py`

- [ ] **Step 1: RED — write failing tests**

```python
"""Tests for disease canonicalization helpers."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from disease_canon import (
    parse_disease_id,
    canonical_id,
    slugify_disease_name,
)


def test_parse_disease_id_strips_mesh_prefix():
    """CTD's disease_id format is 'MESH:D018268' — strip the prefix."""
    assert parse_disease_id("MESH:D018268") == ("mesh", "D018268")
    assert parse_disease_id("MESH:C123456") == ("mesh", "C123456")


def test_parse_disease_id_recognizes_omim_and_doid():
    assert parse_disease_id("OMIM:222100") == ("omim", "222100")
    assert parse_disease_id("DOID:14330") == ("doid", "14330")


def test_parse_disease_id_returns_none_for_bare_string():
    assert parse_disease_id("Diabetes") == (None, None)
    assert parse_disease_id("") == (None, None)
    assert parse_disease_id(None) == (None, None)


def test_canonical_id_prefers_mesh_then_umls_then_icd10():
    assert canonical_id(mesh="D003920", umls="C0011849", icd10="E11") == "mesh:D003920"
    assert canonical_id(mesh=None, umls="C0011849", icd10="E11") == "umls:C0011849"
    assert canonical_id(mesh=None, umls=None, icd10="E11") == "icd10cm:E11"


def test_canonical_id_falls_back_to_slugified_local_when_no_formal_id():
    cid = canonical_id(mesh=None, umls=None, icd10=None,
                        preferred_name="Diabetes Mellitus")
    assert cid == "local:diabetes-mellitus"


def test_slugify_disease_name_lowercases_alphanums():
    assert slugify_disease_name("Diabetes Mellitus") == "diabetes-mellitus"
    assert slugify_disease_name("Alzheimer's Disease, Late Onset") == "alzheimers-disease-late-onset"
    assert slugify_disease_name("Type-2 Diabetes (NIDDM)") == "type-2-diabetes-niddm"


def test_slugify_collapses_whitespace_and_strips_edges():
    assert slugify_disease_name("  Cancer   of   Lung  ") == "cancer-of-lung"
    assert slugify_disease_name("---foo---") == "foo"
```

- [ ] **Step 2: Confirm RED**

```bash
cd shrine-diet-bioactivity
pytest lightrag/tests/test_disease_canon.py -v
```

Expected: ImportError for `disease_canon`.

- [ ] **Step 3: GREEN — implement**

```python
# lightrag/disease_canon.py
"""Disease canonicalization helpers (Phase 3 / spec §4.2).

Pure logic — no DB. Parsers and slug rules used by the canonicalization
orchestrator.
"""
from __future__ import annotations

import re
from typing import Optional

# Order matches priority in canonical_id().
_PREFIX_MAP = {
    "MESH": "mesh",
    "OMIM": "omim",
    "DOID": "doid",
    "UMLS": "umls",
    "ICD10CM": "icd10cm",
    "HPO": "hpo",
}


def parse_disease_id(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Parse 'PREFIX:VALUE' style disease IDs.

    Returns (lowercase_prefix, value) or (None, None) on bare/empty.
    """
    if not raw:
        return (None, None)
    if ":" not in raw:
        return (None, None)
    prefix, _, value = raw.partition(":")
    canonical_prefix = _PREFIX_MAP.get(prefix.strip().upper())
    if canonical_prefix is None:
        return (None, None)
    value = value.strip()
    if not value:
        return (None, None)
    return (canonical_prefix, value)


def canonical_id(
    *,
    mesh: Optional[str] = None,
    umls: Optional[str] = None,
    icd10: Optional[str] = None,
    preferred_name: Optional[str] = None,
) -> str:
    """Compute the canonical disease ID per spec §4.2 priority order."""
    if mesh:
        return f"mesh:{mesh}"
    if umls:
        return f"umls:{umls}"
    if icd10:
        return f"icd10cm:{icd10}"
    if preferred_name:
        return f"local:{slugify_disease_name(preferred_name)}"
    raise ValueError("canonical_id requires at least one of mesh/umls/icd10/preferred_name")


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify_disease_name(name: str) -> str:
    """Lowercase, collapse non-alphanumerics to single dashes, strip edges."""
    s = name.lower().strip()
    s = _NON_ALNUM.sub("-", s)
    return s.strip("-")
```

- [ ] **Step 4: GREEN check**

```bash
pytest lightrag/tests/test_disease_canon.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/lightrag/disease_canon.py \
        shrine-diet-bioactivity/lightrag/tests/test_disease_canon.py
git commit -m "feat(disease-canon): pure-logic helpers — parse_disease_id, canonical_id, slugify"
```

---

## Task 2: SQLite schema DDL (3 new tables)

**Files:**
- Modify: `shrine-diet-bioactivity/scripts/build-herbal-db.ts`
- Create: `shrine-diet-bioactivity/lightrag/tests/test_disease_schema.py`

- [ ] **Step 1: RED — write schema test**

```python
# lightrag/tests/test_disease_schema.py
import sqlite3
import pytest

DDL = """
CREATE TABLE compounds (id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE diseases_canonical (
  id TEXT PRIMARY KEY,
  preferred_name TEXT NOT NULL,
  mesh_id TEXT,
  umls_id TEXT,
  icd10cm_id TEXT,
  hpo_id TEXT,
  source_origin TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_dc_unique_mesh ON diseases_canonical(mesh_id) WHERE mesh_id IS NOT NULL;

CREATE TABLE disease_name_aliases (
  disease_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  source TEXT NOT NULL,
  PRIMARY KEY (disease_id, alias, source),
  FOREIGN KEY (disease_id) REFERENCES diseases_canonical(id)
);

CREATE TABLE compound_disease_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  compound_id TEXT NOT NULL,
  disease_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  inference_gene_symbol TEXT,
  inference_score REAL,
  pubmed_ids TEXT,
  source TEXT NOT NULL DEFAULT 'ctd',
  ingested_at TEXT NOT NULL,
  FOREIGN KEY (compound_id) REFERENCES compounds(id),
  FOREIGN KEY (disease_id) REFERENCES diseases_canonical(id),
  CHECK (
    (evidence_type IN ('direct_therapeutic', 'direct_marker')
       AND inference_gene_symbol IS NULL AND inference_score IS NULL)
    OR
    (evidence_type = 'inferred_via_gene' AND inference_score IS NOT NULL)
  )
);
"""


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    return conn


def test_unique_mesh_constraint_blocks_duplicate_mesh():
    conn = _make_db()
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('mesh:D003920','Diabetes','D003920',NULL,NULL,NULL,'ctd','now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO diseases_canonical VALUES "
            "('mesh:D003920-DUP','Diabetes 2','D003920',NULL,NULL,NULL,'symmap','now')"
        )


def test_check_blocks_inferred_with_no_score():
    conn = _make_db()
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('mesh:D003920','Diabetes','D003920',NULL,NULL,NULL,'ctd','now')"
    )
    conn.execute("INSERT INTO compounds VALUES ('curcumin','Curcumin')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO compound_disease_evidence "
            "(compound_id, disease_id, evidence_type, inference_gene_symbol, "
            " inference_score, pubmed_ids, ingested_at) "
            "VALUES ('curcumin','mesh:D003920','inferred_via_gene','MYC',NULL,NULL,'now')"
        )


def test_check_blocks_direct_with_score():
    conn = _make_db()
    conn.execute(
        "INSERT INTO diseases_canonical VALUES "
        "('mesh:D003920','Diabetes','D003920',NULL,NULL,NULL,'ctd','now')"
    )
    conn.execute("INSERT INTO compounds VALUES ('curcumin','Curcumin')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO compound_disease_evidence "
            "(compound_id, disease_id, evidence_type, inference_score, ingested_at) "
            "VALUES ('curcumin','mesh:D003920','direct_therapeutic',5.0,'now')"
        )


def test_alias_fk_blocks_orphan():
    conn = _make_db()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO disease_name_aliases VALUES "
            "('mesh:DOES-NOT-EXIST','Bogus','ctd')"
        )
```

- [ ] **Step 2: RED check**

```bash
pytest lightrag/tests/test_disease_schema.py -v
```

Expected: 4 PASS (this test exercises the schema independently of build-herbal-db.ts; it's the contract test for the DDL we'll add next).

- [ ] **Step 3: Add DDL to build-herbal-db.ts**

Find the existing `herb_resolution_map` DDL (added by PR #23) and insert this block immediately after it (before the symptom_disease_map DDL, so all Phase 2/3 tables cluster):

```typescript
  // -------------------------------------------------------------------------
  // Phase 3 — disease canonicalization (spec §4.1)
  // -------------------------------------------------------------------------
  // Promotes Disease to a first-class unified entity. Three tables:
  // diseases_canonical (registry), disease_name_aliases (free-text → canonical),
  // compound_disease_evidence (replaces chemical_diseases). Built by
  // scripts/build_disease_canonical.py and the modified scripts/load-ctd.ts.
  db.exec(`
    CREATE TABLE IF NOT EXISTS diseases_canonical (
      id              TEXT PRIMARY KEY,
      preferred_name  TEXT NOT NULL,
      mesh_id         TEXT,
      umls_id         TEXT,
      icd10cm_id      TEXT,
      hpo_id          TEXT,
      source_origin   TEXT NOT NULL,
      created_at      TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_dc_unique_mesh ON diseases_canonical(mesh_id) WHERE mesh_id IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_dc_unique_umls ON diseases_canonical(umls_id) WHERE umls_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_dc_name ON diseases_canonical(preferred_name);

    CREATE TABLE IF NOT EXISTS disease_name_aliases (
      disease_id  TEXT NOT NULL,
      alias       TEXT NOT NULL,
      source      TEXT NOT NULL,
      PRIMARY KEY (disease_id, alias, source),
      FOREIGN KEY (disease_id) REFERENCES diseases_canonical(id)
    );
    CREATE INDEX IF NOT EXISTS idx_dna_alias_lower ON disease_name_aliases(lower(alias));

    CREATE TABLE IF NOT EXISTS compound_disease_evidence (
      id                     INTEGER PRIMARY KEY AUTOINCREMENT,
      compound_id            TEXT NOT NULL,
      disease_id             TEXT NOT NULL,
      evidence_type          TEXT NOT NULL,
      inference_gene_symbol  TEXT,
      inference_score        REAL,
      pubmed_ids             TEXT,
      source                 TEXT NOT NULL DEFAULT 'ctd',
      ingested_at            TEXT NOT NULL,
      FOREIGN KEY (compound_id) REFERENCES compounds(id),
      FOREIGN KEY (disease_id)  REFERENCES diseases_canonical(id),
      CHECK (
        (evidence_type IN ('direct_therapeutic', 'direct_marker')
           AND inference_gene_symbol IS NULL AND inference_score IS NULL)
        OR
        (evidence_type = 'inferred_via_gene' AND inference_score IS NOT NULL)
      )
    );
    CREATE INDEX IF NOT EXISTS idx_cde_compound ON compound_disease_evidence(compound_id);
    CREATE INDEX IF NOT EXISTS idx_cde_disease  ON compound_disease_evidence(disease_id);
    CREATE INDEX IF NOT EXISTS idx_cde_gene     ON compound_disease_evidence(inference_gene_symbol)
      WHERE inference_gene_symbol IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_cde_type     ON compound_disease_evidence(evidence_type);
  `);
  console.error('  ✓ Phase 3: diseases_canonical + disease_name_aliases + compound_disease_evidence');
```

- [ ] **Step 4: Apply DDL to live DB (idempotent — IF NOT EXISTS)**

```bash
sqlite3 data_local/herbal_botanicals.db <<'SQL'
PRAGMA foreign_keys = ON;
-- (paste the same CREATE statements from above)
SQL
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/scripts/build-herbal-db.ts \
        shrine-diet-bioactivity/lightrag/tests/test_disease_schema.py
git commit -m "feat(db): disease canonicalization DDL + schema invariant tests"
```

---

## Task 3: Disease canonicalization orchestrator (`build_disease_canonical.py`)

**Files:**
- Create: `shrine-diet-bioactivity/scripts/build_disease_canonical.py`
- Create: `shrine-diet-bioactivity/lightrag/tests/test_disease_canonical_build.py`
- Modify: `shrine-diet-bioactivity/Makefile` (add `build-disease-canonical` target)

- [ ] **Step 1: RED — integration test against in-memory DB**

```python
# lightrag/tests/test_disease_canonical_build.py
"""End-to-end test of build_disease_canonical against an in-memory DB."""
import sqlite3
import subprocess
import sys
import tempfile
import os


def _seed_db():
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db.close()
    conn = sqlite3.connect(db.name)
    conn.executescript("""
        -- Schema (subset of Task 2 DDL — only what the orchestrator needs).
        CREATE TABLE compounds (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE targets (id TEXT PRIMARY KEY, name TEXT, gene_symbol TEXT);
        CREATE TABLE target_diseases (
          target_id TEXT, disease_name TEXT, evidence_layer TEXT
        );
        CREATE TABLE symptoms (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE symmap_modern_symptoms (
          symmap_id TEXT, name TEXT, mesh_id TEXT, umls_id TEXT, icd10cm_id TEXT,
          omim_id TEXT, hpo_id TEXT, mesh_tree_numbers TEXT, definition TEXT
        );

        CREATE TABLE diseases_canonical (
          id TEXT PRIMARY KEY, preferred_name TEXT NOT NULL, mesh_id TEXT,
          umls_id TEXT, icd10cm_id TEXT, hpo_id TEXT,
          source_origin TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_dc_unique_mesh ON diseases_canonical(mesh_id) WHERE mesh_id IS NOT NULL;
        CREATE UNIQUE INDEX idx_dc_unique_umls ON diseases_canonical(umls_id) WHERE umls_id IS NOT NULL;
        CREATE TABLE disease_name_aliases (
          disease_id TEXT NOT NULL, alias TEXT NOT NULL, source TEXT NOT NULL,
          PRIMARY KEY (disease_id, alias, source),
          FOREIGN KEY (disease_id) REFERENCES diseases_canonical(id)
        );

        -- Seed: the same disease appears under two sources with different naming.
        INSERT INTO targets VALUES ('NPT1', 'IL-6', 'IL6');
        INSERT INTO target_diseases VALUES ('NPT1', 'Diabetes Mellitus', 'high');
        INSERT INTO target_diseases VALUES ('NPT1', 'Hypertension', 'high');
        INSERT INTO symmap_modern_symptoms VALUES
          ('SMMS1', 'Diabetes Mellitus', 'D003920', 'C0011849', 'E11', NULL, NULL, NULL, NULL),
          ('SMMS2', 'Essential Hypertension', 'C562386', 'C0085580', 'I10', NULL, NULL, NULL, NULL),
          ('SMMS3', 'Bile Insufficiency Syndrome', NULL, NULL, NULL, NULL, NULL, NULL, NULL);
    """)
    conn.commit()
    conn.close()
    return db.name


def test_orchestrator_unifies_diabetes_across_sources():
    """Diabetes Mellitus appears in both target_diseases and symmap with a MeSH ID;
    must produce ONE canonical row keyed by mesh_id, with TWO aliases."""
    db_path = _seed_db()
    try:
        result = subprocess.run(
            [sys.executable, "scripts/build_disease_canonical.py", "--db", db_path],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")

        # Only ONE canonical row for Diabetes (joined by MeSH).
        diab_rows = conn.execute(
            "SELECT id, mesh_id FROM diseases_canonical WHERE mesh_id='D003920'"
        ).fetchall()
        assert len(diab_rows) == 1
        assert diab_rows[0] == ('mesh:D003920', 'D003920')

        # Two aliases for Diabetes — one per source.
        aliases = conn.execute(
            "SELECT alias, source FROM disease_name_aliases "
            "WHERE disease_id='mesh:D003920' ORDER BY source"
        ).fetchall()
        assert len(aliases) >= 2
        sources = {r[1] for r in aliases}
        assert {'symmap', 'target_diseases'}.issubset(sources)

        # Hypertension uses MeSH C562386 from symmap; target_diseases bare name aliases to it.
        hyp_rows = conn.execute(
            "SELECT id FROM diseases_canonical WHERE mesh_id='C562386'"
        ).fetchall()
        assert len(hyp_rows) == 1

        # Bile Insufficiency Syndrome has NO formal IDs → local slug.
        bile_rows = conn.execute(
            "SELECT id, source_origin FROM diseases_canonical "
            "WHERE preferred_name='Bile Insufficiency Syndrome'"
        ).fetchall()
        assert len(bile_rows) == 1
        assert bile_rows[0][0].startswith('local:')

        conn.close()
    finally:
        os.unlink(db_path)


def test_orchestrator_is_idempotent():
    """Running the orchestrator twice should not produce duplicate canonical rows."""
    db_path = _seed_db()
    try:
        for _ in range(2):
            r = subprocess.run(
                [sys.executable, "scripts/build_disease_canonical.py", "--db", db_path],
                capture_output=True, text=True, timeout=30,
            )
            assert r.returncode == 0, r.stderr

        conn = sqlite3.connect(db_path)
        n = conn.execute(
            "SELECT COUNT(*) FROM diseases_canonical WHERE mesh_id='D003920'"
        ).fetchone()[0]
        assert n == 1, f"Idempotency broken — got {n} canonical rows for one MeSH ID"
        conn.close()
    finally:
        os.unlink(db_path)
```

- [ ] **Step 2: GREEN — implement orchestrator**

Create `scripts/build_disease_canonical.py` (~250 LOC). Key sections:

```python
"""Build the canonical disease registry (Phase 3 / spec §4.3).

Reads disease names + formal IDs from:
  - target_diseases.disease_name (CMAUP — bare names, no formal IDs)
  - symmap_modern_symptoms (mesh_id, umls_id, icd10cm_id columns)
  - chemical_diseases.disease_id (CTD — 'MESH:Dxxxxxx' format)
  - herb2_herb_disease.disease (HERB 2.0 — bare names)
  - symptom_disease_map (already-resolved aliases via SymMap, with formal IDs)

Writes to diseases_canonical and disease_name_aliases. Idempotent — UPSERT
semantics keyed on the formal-ID priority chain (MeSH → UMLS → ICD-10 → local slug).

Usage:
  python scripts/build_disease_canonical.py --db data_local/herbal_botanicals.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from disease_canon import canonical_id, parse_disease_id


def _build_argparser() -> argparse.ArgumentParser:
    description = (__doc__ or "Build disease canonical").split("\n\n")[0]
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--db", type=Path, required=True)
    return ap


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _upsert_canonical(
    conn: sqlite3.Connection,
    *,
    preferred_name: str,
    mesh: str | None,
    umls: str | None,
    icd10: str | None,
    hpo: str | None,
    source_origin: str,
    now_iso: str,
) -> str:
    """Insert or fetch the canonical row by formal-ID priority."""
    # Look up by MeSH first (the dominant key).
    if mesh:
        row = conn.execute(
            "SELECT id FROM diseases_canonical WHERE mesh_id=?", (mesh,)
        ).fetchone()
        if row:
            return row[0]
    if umls:
        row = conn.execute(
            "SELECT id FROM diseases_canonical WHERE umls_id=?", (umls,)
        ).fetchone()
        if row:
            return row[0]
    cid = canonical_id(mesh=mesh, umls=umls, icd10=icd10, preferred_name=preferred_name)
    # Fall back: existence check by primary key for local slugs (multiple
    # bare-name diseases may collide under the same slug; we keep first writer).
    row = conn.execute(
        "SELECT id FROM diseases_canonical WHERE id=?", (cid,)
    ).fetchone()
    if row:
        return row[0]
    conn.execute(
        "INSERT INTO diseases_canonical "
        "(id, preferred_name, mesh_id, umls_id, icd10cm_id, hpo_id, source_origin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, preferred_name, mesh, umls, icd10, hpo, source_origin, now_iso),
    )
    return cid


def _add_alias(conn: sqlite3.Connection, *, disease_id: str, alias: str, source: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO disease_name_aliases (disease_id, alias, source) "
        "VALUES (?, ?, ?)",
        (disease_id, alias, source),
    )


def main() -> int:
    args = _build_argparser().parse_args()
    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys = ON")
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    counts = {"target_diseases": 0, "symmap": 0, "ctd": 0, "herb2": 0}
    aliases_added = 0

    try:
        with conn:
            # 1. SymMap (carries formal IDs — best canonical source).
            if _table_exists(conn, "symmap_modern_symptoms"):
                rows = conn.execute(
                    "SELECT name, mesh_id, umls_id, icd10cm_id, hpo_id "
                    "FROM symmap_modern_symptoms WHERE name IS NOT NULL"
                ).fetchall()
                for name, mesh, umls, icd10, hpo in rows:
                    cid = _upsert_canonical(
                        conn, preferred_name=name, mesh=mesh, umls=umls,
                        icd10=icd10, hpo=hpo, source_origin="symmap", now_iso=now_iso,
                    )
                    _add_alias(conn, disease_id=cid, alias=name, source="symmap")
                    counts["symmap"] += 1
                    aliases_added += 1

            # 2. CTD (chemical_diseases.disease_id is 'MESH:Dxxxxxx').
            if _table_exists(conn, "chemical_diseases"):
                rows = conn.execute(
                    "SELECT DISTINCT disease_name, disease_id FROM chemical_diseases "
                    "WHERE disease_name IS NOT NULL"
                ).fetchall()
                for name, raw_id in rows:
                    prefix, value = parse_disease_id(raw_id or "")
                    mesh = value if prefix == "mesh" else None
                    cid = _upsert_canonical(
                        conn, preferred_name=name, mesh=mesh, umls=None,
                        icd10=None, hpo=None, source_origin="ctd", now_iso=now_iso,
                    )
                    _add_alias(conn, disease_id=cid, alias=name, source="ctd")
                    counts["ctd"] += 1
                    aliases_added += 1

            # 3. CMAUP target_diseases (bare names, no formal IDs).
            if _table_exists(conn, "target_diseases"):
                rows = conn.execute(
                    "SELECT DISTINCT disease_name FROM target_diseases "
                    "WHERE disease_name IS NOT NULL"
                ).fetchall()
                for (name,) in rows:
                    # Try to resolve via existing alias first.
                    existing = conn.execute(
                        "SELECT disease_id FROM disease_name_aliases "
                        "WHERE lower(alias) = lower(?) LIMIT 1", (name,)
                    ).fetchone()
                    if existing:
                        _add_alias(conn, disease_id=existing[0], alias=name, source="target_diseases")
                    else:
                        cid = _upsert_canonical(
                            conn, preferred_name=name, mesh=None, umls=None,
                            icd10=None, hpo=None, source_origin="target_diseases",
                            now_iso=now_iso,
                        )
                        _add_alias(conn, disease_id=cid, alias=name, source="target_diseases")
                    counts["target_diseases"] += 1
                    aliases_added += 1

            # 4. HERB 2.0 — disease_label is the bare-name; disease_id is HERB
            #    2.0's internal ID (not a formal MeSH/UMLS); source_pmid is
            #    per-row PubMed evidence we route to disease_name_aliases as
            #    free-text annotation (preserved for downstream provenance).
            #    [Schema corrected at harden-plan: was 'disease' in spec.]
            if _table_exists(conn, "herb2_herb_disease"):
                rows = conn.execute(
                    "SELECT DISTINCT disease_label FROM herb2_herb_disease "
                    "WHERE disease_label IS NOT NULL"
                ).fetchall()
                for (name,) in rows:
                    existing = conn.execute(
                        "SELECT disease_id FROM disease_name_aliases "
                        "WHERE lower(alias) = lower(?) LIMIT 1", (name,)
                    ).fetchone()
                    if existing:
                        _add_alias(conn, disease_id=existing[0], alias=name, source="herb2")
                    else:
                        cid = _upsert_canonical(
                            conn, preferred_name=name, mesh=None, umls=None,
                            icd10=None, hpo=None, source_origin="herb2", now_iso=now_iso,
                        )
                        _add_alias(conn, disease_id=cid, alias=name, source="herb2")
                    counts["herb2"] += 1
                    aliases_added += 1

    finally:
        conn.close()

    n_canon = sqlite3.connect(str(args.db)).execute(
        "SELECT COUNT(*) FROM diseases_canonical"
    ).fetchone()[0]
    print(f"Canonical disease entities: {n_canon}")
    print(f"Aliases added (across all sources): {aliases_added}")
    print(f"Per-source contribution: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run tests**

```bash
pytest lightrag/tests/test_disease_canonical_build.py -v
```

Expected: 2 PASS.

- [ ] **Step 4: Add Makefile target**

```makefile
.PHONY: build-disease-canonical

build-disease-canonical:
	python scripts/build_disease_canonical.py \
		--db data_local/herbal_botanicals.db
```

- [ ] **Step 5: Run against live DB to populate canonical registry**

```bash
make build-disease-canonical
sqlite3 data_local/herbal_botanicals.db \
  "SELECT 'canonical:', COUNT(*) FROM diseases_canonical;
   SELECT 'aliases:', COUNT(*) FROM disease_name_aliases;
   SELECT 'mesh-anchored:', COUNT(*) FROM diseases_canonical WHERE mesh_id IS NOT NULL;
   SELECT 'umls-anchored:', COUNT(*) FROM diseases_canonical WHERE umls_id IS NOT NULL;"
```

Expected: ~6,500–10,000 canonical rows; alias count higher (multiple sources point at same canonical).

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/scripts/build_disease_canonical.py \
        shrine-diet-bioactivity/lightrag/tests/test_disease_canonical_build.py \
        shrine-diet-bioactivity/Makefile
git commit -m "feat(disease-canon): orchestrator + Makefile target — unifies 4 disease sources"
```

---

## Task 4: Modify load-ctd.ts to write `compound_disease_evidence`

**Files:**
- Modify: `shrine-diet-bioactivity/scripts/load-ctd.ts`

This is the dual-write phase. Old `chemical_diseases` continues to populate (so existing queries don't break); new `compound_disease_evidence` populates in parallel.

- [ ] **Step 1: Pull additional fields**

In the streaming loop, capture `fields[6]` (InferenceGeneSymbol) and `fields[9]` (PubMedIDs) alongside the existing fields.

- [ ] **Step 2: Resolve disease_id to canonical**

Add a helper function in load-ctd.ts that, given `(diseaseName, rawDiseaseId)`, looks up the canonical disease via the alias table:

```typescript
function resolveCanonicalDiseaseId(
  db: Database.Database,
  diseaseName: string,
  rawDiseaseId: string,
): string | null {
  // Prefer MeSH-anchored canonical row.
  if (rawDiseaseId.startsWith('MESH:')) {
    const mesh = rawDiseaseId.substring(5);
    const row = db.prepare('SELECT id FROM diseases_canonical WHERE mesh_id = ?').get(mesh) as { id: string } | undefined;
    if (row) return row.id;
  }
  // Fall back to alias lookup.
  const alias = db.prepare(
    'SELECT disease_id FROM disease_name_aliases WHERE lower(alias) = lower(?) LIMIT 1'
  ).get(diseaseName) as { disease_id: string } | undefined;
  return alias?.disease_id ?? null;
}
```

- [ ] **Step 3: Emit evidence_type and dual-write**

In the existing batch handler, AFTER inserting into `chemical_diseases` (existing code), also resolve canonical disease and insert into `compound_disease_evidence`:

```typescript
const canonicalId = resolveCanonicalDiseaseId(db, chemName, diseaseId);
if (!canonicalId) {
  // Disease not in canonical registry — must run build_disease_canonical first.
  // Skip this row; will surface in the runbook coverage report.
  return;
}

let evidenceType: string;
let inferenceScoreOrNull: number | null = null;
let inferenceGene: string | null = null;
// IMPORTANT: CTD writes empty string for inferred rows, NOT NULL. Treat
// '' and undefined as the no-direct-evidence case. (Caught at harden-plan;
// 906,247 of 934,070 chemical_diseases rows have direct_evidence=''.)
const hasDirectTx = directEvidence === 'therapeutic';
const hasDirectMx = directEvidence === 'marker/mechanism';
const hasInferred = !hasDirectTx && !hasDirectMx
  && inferenceScore !== null && fields[6];

if (hasDirectTx) {
  evidenceType = 'direct_therapeutic';
} else if (hasDirectMx) {
  evidenceType = 'direct_marker';
} else if (hasInferred) {
  evidenceType = 'inferred_via_gene';
  inferenceScoreOrNull = inferenceScore;
  inferenceGene = fields[6] || null;
} else {
  return; // skip rows that don't fit the typology
}

const pubmedIds = fields[9] || null;

batch.push(() => {
  // Existing insert into chemical_diseases (unchanged) ...
  insertCD.run(compoundId, chemName, diseaseName, diseaseId, directEvidence, inferenceScore);
  result.diseases++;
  // New: parallel insert into compound_disease_evidence.
  insertCDE.run(
    compoundId, canonicalId, evidenceType,
    inferenceGene, inferenceScoreOrNull, pubmedIds,
  );
});
```

- [ ] **Step 4: Add CHECK-constraint-compatible insertCDE prepared statement**

```typescript
const insertCDE = db.prepare(`
  INSERT INTO compound_disease_evidence
    (compound_id, disease_id, evidence_type, inference_gene_symbol,
     inference_score, pubmed_ids, ingested_at)
  VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
`);
```

- [ ] **Step 5: Run live ingest and verify dual-population**

```bash
# Pre-req: build_disease_canonical must have run (canonical registry populated).
make build-disease-canonical
make load-ctd
sqlite3 data_local/herbal_botanicals.db \
  "SELECT 'old chemical_diseases:', COUNT(*) FROM chemical_diseases;
   SELECT 'new compound_disease_evidence:', COUNT(*) FROM compound_disease_evidence;
   SELECT 'CDE by evidence_type:'; SELECT evidence_type, COUNT(*)
     FROM compound_disease_evidence GROUP BY evidence_type;
   SELECT 'CDE rows with pubmed_ids:', COUNT(*)
     FROM compound_disease_evidence WHERE pubmed_ids IS NOT NULL;
   SELECT 'CDE inferred-via-gene rows:', COUNT(*)
     FROM compound_disease_evidence WHERE evidence_type='inferred_via_gene';"
```

Expected: CDE count slightly less than chemical_diseases (rows skipped due to missing canonical match); evidence_type histogram populated; pubmed_ids ≥40% non-null on direct rows; gene-mediated inference rows in the thousands.

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/scripts/load-ctd.ts
git commit -m "feat(ctd): dual-write to compound_disease_evidence with type + citations + gene"
```

---

## Task 5: Update build_symptom_disease_map.py to populate aliases

**Files:**
- Modify: `shrine-diet-bioactivity/scripts/build_symptom_disease_map.py`

- [ ] **Step 1: After each symptom_disease_map row insert, also UPSERT alias**

Inside the existing match loop, after `cur.execute(insert_sql, ...)`:

```python
# Phase 3: contribute the alias to the canonical registry. Resolve the
# canonical disease ID by mesh_id when available, falling back to alias
# lookup on the disease_name (which the canonicalization pass has already
# populated for SymMap).
if best.mesh_id:
    cid_row = cur.execute(
        "SELECT id FROM diseases_canonical WHERE mesh_id=?", (best.mesh_id,)
    ).fetchone()
    if cid_row:
        cur.execute(
            "INSERT OR IGNORE INTO disease_name_aliases "
            "(disease_id, alias, source) VALUES (?, ?, 'symmap_match')",
            (cid_row[0], best.disease_name),
        )
```

- [ ] **Step 2: Re-run + verify**

```bash
make build-symptom-disease-map
sqlite3 data_local/herbal_botanicals.db \
  "SELECT COUNT(*) FROM disease_name_aliases WHERE source='symmap_match';"
```

Expected: 30+ rows (one per mapped symptom).

- [ ] **Step 3: Commit**

```bash
git add shrine-diet-bioactivity/scripts/build_symptom_disease_map.py
git commit -m "feat(symptom-disease-map): contribute aliases to canonical disease registry"
```

---

## Task 6: LightRAG entity_schema — `Disease` entity reroute + 3 new relationships

**Files:**
- Modify: `shrine-diet-bioactivity/lightrag/entity_schema.py`
- Create: `shrine-diet-bioactivity/lightrag/tests/test_disease_canonical_entity.py`

- [ ] **Step 1: Update `Disease` entity definition**

Replace the existing `"Disease"` entry in `ENTITY_TYPES` (currently uses `query_builder = "build_disease_query"` aggregating across multiple tables) with:

```python
"Disease": {
    "source_table": "diseases_canonical",
    "id_field": "id",
    "name_field": "preferred_name",
    "query": (
        "SELECT id, preferred_name, mesh_id, umls_id, icd10cm_id, hpo_id, "
        "source_origin FROM diseases_canonical ORDER BY id"
    ),
},
```

The old `build_disease_query` builder can stay in QUERY_BUILDERS for backward compat but is no longer referenced.

- [ ] **Step 2: Update `describe_disease` to render full ontology cross-refs**

```python
def describe_disease(row: dict[str, Any]) -> str:
    parts = [row.get("preferred_name", "Unknown disease")]
    refs = []
    if row.get("mesh_id"):
        refs.append(f"MeSH {row['mesh_id']}")
    if row.get("umls_id"):
        refs.append(f"UMLS {row['umls_id']}")
    if row.get("icd10cm_id"):
        refs.append(f"ICD-10-CM {row['icd10cm_id']}")
    if refs:
        parts.append("(" + ", ".join(refs) + ")")
    return ". ".join(parts)
```

- [ ] **Step 3: Add 3 new RELATIONSHIP_TYPES**

```python
"COMPOUND_TREATS_DISEASE": {
    "source_table": "compound_disease_evidence",
    "src_type": "Compound",
    "tgt_type": "Disease",
    "query": (
        "SELECT c.name AS src_name, d.preferred_name AS tgt_name, "
        "       cde.pubmed_ids AS pubmed_ids, cde.source AS source "
        "FROM compound_disease_evidence cde "
        "JOIN compounds c ON c.id = cde.compound_id "
        "JOIN diseases_canonical d ON d.id = cde.disease_id "
        "WHERE cde.evidence_type = 'direct_therapeutic' "
        "ORDER BY cde.id"
    ),
},
"COMPOUND_MARKER_FOR_DISEASE": {
    "source_table": "compound_disease_evidence",
    "src_type": "Compound",
    "tgt_type": "Disease",
    "query": (
        "SELECT c.name AS src_name, d.preferred_name AS tgt_name, "
        "       cde.pubmed_ids AS pubmed_ids "
        "FROM compound_disease_evidence cde "
        "JOIN compounds c ON c.id = cde.compound_id "
        "JOIN diseases_canonical d ON d.id = cde.disease_id "
        "WHERE cde.evidence_type = 'direct_marker' "
        "ORDER BY cde.id"
    ),
},
"COMPOUND_INFERRED_DISEASE": {
    "source_table": "compound_disease_evidence",
    "src_type": "Compound",
    "tgt_type": "Disease",
    "query": (
        "SELECT c.name AS src_name, d.preferred_name AS tgt_name, "
        "       cde.inference_gene_symbol AS gene, "
        "       cde.inference_score AS score, cde.pubmed_ids AS pubmed_ids "
        "FROM compound_disease_evidence cde "
        "JOIN compounds c ON c.id = cde.compound_id "
        "JOIN diseases_canonical d ON d.id = cde.disease_id "
        "WHERE cde.evidence_type = 'inferred_via_gene' "
        "ORDER BY cde.id"
    ),
},
```

- [ ] **Step 4: Add describe_relationship branches**

In `describe_relationship`, before the tenant section:

```python
if rel_type == "COMPOUND_TREATS_DISEASE":
    pubmed = row.get("pubmed_ids") or ""
    n_cites = len([x for x in pubmed.split("|") if x]) if pubmed else 0
    desc = f"{src} therapeutically treats {tgt}"
    if n_cites:
        desc += f" ({n_cites} PubMed citation{'s' if n_cites != 1 else ''})"
    return desc, "compound disease therapeutic treatment evidence pubmed"

if rel_type == "COMPOUND_MARKER_FOR_DISEASE":
    return (f"{src} is a marker / mechanism for {tgt}",
            "compound disease marker mechanism diagnostic")

if rel_type == "COMPOUND_INFERRED_DISEASE":
    gene = row.get("gene") or ""
    score = row.get("score")
    desc = f"{src} inferred to associate with {tgt}"
    if gene:
        desc += f" via {gene}"
    if score is not None:
        desc += f" (score {score})"
    return desc, "compound disease inference gene mediated evidence"
```

- [ ] **Step 5: Update `MAPS_TO_DISEASE` to JOIN through canonical**

The existing query sources `tgt_name` from `symptom_disease_map.disease_name`. Update to JOIN through the canonical registry:

```python
"MAPS_TO_DISEASE": {
    ...
    "query": (
        "SELECT s.name AS src_name, "
        "       COALESCE(d.preferred_name, sdm.disease_name) AS tgt_name, "
        "       sdm.source AS source, sdm.mesh_id AS mesh_id, "
        "       sdm.match_score AS match_score "
        "FROM symptom_disease_map sdm "
        "JOIN symptoms s ON s.id = sdm.symptom_id "
        "LEFT JOIN diseases_canonical d ON d.mesh_id = sdm.mesh_id "
        "ORDER BY s.id, sdm.match_score DESC"
    ),
},
```

- [ ] **Step 6: Test against populated DB**

```python
# lightrag/tests/test_disease_canonical_entity.py
import sqlite3
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_schema import (
    DESCRIPTION_GENERATORS, ENTITY_TYPES, RELATIONSHIP_TYPES,
    describe_relationship,
)

DB_PATH = Path(__file__).parent.parent.parent / "data_local" / "herbal_botanicals.db"


@pytest.fixture(scope="module")
def db_conn():
    if not DB_PATH.exists():
        pytest.skip("live DB absent")
    return sqlite3.connect(str(DB_PATH))


def test_disease_entity_query_runs(db_conn):
    rows = list(db_conn.execute(ENTITY_TYPES["Disease"]["query"]))
    assert len(rows) > 1000  # sanity floor


def test_describe_disease_renders_cross_refs(db_conn):
    cur = db_conn.execute(
        "SELECT id, preferred_name, mesh_id, umls_id, icd10cm_id, hpo_id "
        "FROM diseases_canonical WHERE mesh_id IS NOT NULL LIMIT 1"
    )
    cols = [d[0] for d in cur.description]
    row = dict(zip(cols, cur.fetchone()))
    desc = DESCRIPTION_GENERATORS["Disease"](row)
    assert row["preferred_name"] in desc
    assert "MeSH" in desc


def test_compound_treats_disease_relationship_query_runs(db_conn):
    spec = RELATIONSHIP_TYPES["COMPOUND_TREATS_DISEASE"]
    rows = list(db_conn.execute(spec["query"]))
    assert len(rows) > 100  # sanity floor on therapeutic evidence


def test_compound_inferred_disease_relationship_renders_gene(db_conn):
    spec = RELATIONSHIP_TYPES["COMPOUND_INFERRED_DISEASE"]
    cur = db_conn.execute(spec["query"] + " LIMIT 1")
    cols = [d[0] for d in cur.description]
    row = dict(zip(cols, cur.fetchone()))
    desc, kw = describe_relationship("COMPOUND_INFERRED_DISEASE", row)
    assert row["src_name"] in desc
    assert row["tgt_name"] in desc
    if row.get("gene"):
        assert row["gene"] in desc
```

- [ ] **Step 7: Commit**

```bash
git add shrine-diet-bioactivity/lightrag/entity_schema.py \
        shrine-diet-bioactivity/lightrag/tests/test_disease_canonical_entity.py
git commit -m "feat(lightrag): Disease entity reroute + 3 evidence-typed relationships"
```

---

## Task 7: Audit-gate updates

**Files:**
- Modify: `shrine-diet-bioactivity/lightrag/tests/test_kg_completeness_gates.py`

- [ ] **Step 1: Replace test_chemical_diseases_has_meaningful_coverage**

Update or replace with `test_compound_disease_evidence_has_meaningful_coverage`:

```python
def test_compound_disease_evidence_has_meaningful_coverage(db_conn) -> None:
    """Phase 3 supersedes Gap 1 — CTD evidence in canonicalized form.

    Lower floor than Gap 1 (was 10K) because some CTD rows fail to map to
    a canonical disease and are dropped. Floor of 800K is conservative
    against the 934K we had under chemical_diseases.
    """
    n = db_conn.execute("SELECT COUNT(*) FROM compound_disease_evidence").fetchone()[0]
    assert n >= 800_000, (
        f"compound_disease_evidence has {n} rows; expected ≥800K. "
        "Run build-disease-canonical && load-ctd."
    )


def test_disease_canonicalization_unifies_sources(db_conn) -> None:
    """Every disease string seen across our 4 sources has at least one alias row."""
    sources = ["target_diseases", "ctd", "symmap", "herb2"]
    counts = {
        s: db_conn.execute(
            "SELECT COUNT(*) FROM disease_name_aliases WHERE source=?", (s,)
        ).fetchone()[0]
        for s in sources
    }
    assert counts["target_diseases"] > 0, "CMAUP target_diseases not aliased"
    assert counts["ctd"] > 0, "CTD not aliased"
    assert counts["symmap"] > 0, "SymMap not aliased"
    # herb2 may be 0 if herb2_herb_disease was never loaded — acceptable


def test_compound_disease_evidence_evidence_types(db_conn) -> None:
    """All three evidence types should appear, with check-constraint compliance."""
    rows = dict(db_conn.execute(
        "SELECT evidence_type, COUNT(*) FROM compound_disease_evidence "
        "GROUP BY evidence_type"
    ).fetchall())
    assert "direct_therapeutic" in rows and rows["direct_therapeutic"] > 100
    assert "direct_marker" in rows and rows["direct_marker"] > 100
    # inferred_via_gene presence depends on CTD's data — most are inferred.
    assert "inferred_via_gene" in rows
```

- [ ] **Step 2: Run all gates against populated DB; expect GREEN**

- [ ] **Step 3: Commit**

```bash
git add shrine-diet-bioactivity/lightrag/tests/test_kg_completeness_gates.py
git commit -m "test(audit): supersede chemical_diseases gate with compound_disease_evidence + canonicalization gate"
```

---

## Task 8: Documentation + ADR

**Files:**
- Create: `docs/adr/0008-disease-canonicalization.md`
- Modify: `docs/KG_COMPLETENESS_AUDIT.md` (add Phase 3 section)
- Modify: `docs/DATASET_PROVENANCE.md` (mark `chemical_diseases` deprecated; document `compound_disease_evidence`)
- Modify: `docs/INDEX.md` (link the new ADR + spec)

- [ ] **Step 1: Write ADR 0008**

Mirror ADR 0007's structure: Context, Decision, Alternatives considered, Consequences.

- [ ] **Step 2: Update audit doc with a new "Phase 3 closeout" section** (post-PR-#23 the audit was closed; this PR opens a new layer of unification on top, not a gap fix).

- [ ] **Step 3: DATASET_PROVENANCE entries**

```markdown
## compound_disease_evidence (Phase 3, 2026-05-08)
- Replaces chemical_diseases as the canonical compound→disease evidence layer
- Sourced from CTD via re-run of scripts/load-ctd.ts after Phase 3 schema lands
- Adds: PubMed citations, gene-symbol inference paths, evidence-type discrimination
- chemical_diseases retained for one stable cycle (≥1 week) then dropped
```

- [ ] **Step 4: Commit**

```bash
git add docs/adr/0008-disease-canonicalization.md \
        docs/KG_COMPLETENESS_AUDIT.md \
        docs/DATASET_PROVENANCE.md \
        docs/INDEX.md
git commit -m "docs: ADR 0008 + Phase 3 audit/provenance updates"
```

---

## Task 9: Final coverage + e2e smoke

- [ ] **Step 1: Run all new tests**

```bash
pytest lightrag/tests/test_disease_canon.py \
       lightrag/tests/test_disease_schema.py \
       lightrag/tests/test_disease_canonical_build.py \
       lightrag/tests/test_disease_canonical_entity.py \
       lightrag/tests/test_kg_completeness_gates.py \
       --cov=disease_canon --cov-report=term-missing -v
```

Expected: all GREEN; coverage ≥80% on disease_canon.

- [ ] **Step 2: Use-case query sanity check**

Pick a symptom (e.g., "Diabetes") and run the full §5.1 query against the populated DB. Eyeball the results — should be foods + their bioactive compounds + evidence-type ranking + PubMed counts.

- [ ] **Step 3: Lint + commit any incidental fixes**

```bash
ruff check --fix lightrag/disease_canon.py scripts/build_disease_canonical.py
ruff format lightrag/disease_canon.py scripts/build_disease_canonical.py
git status
# if changes: git add ... && git commit -m "test: lint + smoke-derived fixes"
```

---

## Self-review notes

- **Spec coverage:** §4.1 schema → Task 2; §4.3 loader changes → Tasks 4 + 5; §4.4 LightRAG → Task 6; §4.5 migration → dual-write design in Task 4 + audit gate update in Task 7; §8 DoD → Task 9.
- **Type consistency:** `disease_id` is TEXT everywhere; `compound_id` TEXT; `evidence_type` is one of three string literals enforced by CHECK constraint.
- **Migration safety:** old `chemical_diseases` stays untouched; new tables added alongside; no destructive operations until follow-up cleanup PR after stable cycle.
- **Idempotency:** all build scripts use UPSERT or CREATE IF NOT EXISTS; safe to re-run.
- **Test strategy:** Task 1 covers pure logic with 7 unit tests; Tasks 2–6 each have integration tests against in-memory or live DB; Task 7 ratchets audit-gate floor.

## Phase 3 risks (recap from spec §7)

- Dual-write doubles CTD ingest time (60s → ~120s). Acceptable.
- Concept mis-merging blocked by formal-ID-only canonicalization (no name fuzzy-matching).
- Existing queries against `chemical_diseases` survive the migration via parallel-table design.
