# Drug ↔ Bioactive Bridge — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inner loop is superpowers:test-driven-development.

**Goal:** Add a compound-identity bridge (RDKit + UniChem) and a ChEMBL-backed bioactivity-evidence layer to the existing Diet KG so symptom→food and diet→effects queries can traverse measured drug-target evidence end-to-end.

**Architecture:** New SQLite tables `compound_identity` and `bioactivity_evidence` in `data_local/herbal_botanicals.db`, populated from RDKit + UniChem source-mapping files + a pinned ChEMBL 36 SQLite dump (via `chembl-downloader`). New LightRAG entity type `BioactivityEvidence` with two new relationship types, ingested through the existing `ainsert_custom_kg` path. Zero new MCP tools — the existing thin-adapter primitives surface the new entities for free.

**Tech Stack:** Python 3.10+, RDKit (`rdkit-pypi`), `chembl-downloader`, `httpx`, sqlite3, LightRAG, Neo4j 5.26+, pytest. TypeScript-side: vitest regression on `tools.ts` label catalog only.

**Project root for paths below:** `shrine-diet-bioactivity/shrine-diet-bioactivity/` (the inner project dir). All file paths in tasks are relative to that directory unless explicitly absolute.

**Secrets needed (none new):** Phase 1 uses only public, unauthenticated data sources. No new env vars or Infisical secrets. ChEMBL/UniChem/PubChem all public; LightRAG continues to use existing `OLLAMA_BASE_URL` (local) or `OPENAI_API_KEY` (production) per `lightrag/config_local.env` / `config_production.env`.

---

## File map (created / modified)

**Created:**
- `lightrag/identity_bridge.py` — RDKit InChIKey computation + UniChem cross-ref pull
- `lightrag/chembl_extractor.py` — ChEMBL SQLite query helper (uses `chembl-downloader`)
- `scripts/build_compound_identity.py` — CLI entrypoint: builds `compound_identity` table
- `scripts/build_bioactivity_evidence.py` — CLI entrypoint: builds `bioactivity_evidence` table
- `lightrag/tests/test_identity_bridge.py`
- `lightrag/tests/test_chembl_extractor.py`
- `lightrag/tests/test_ingest_bioactivity.py`
- `lightrag/tests/fixtures/chembl_subset.sqlite` — ≤5MB ChEMBL slice for tests
- `lightrag/tests/fixtures/unichem_subset.tsv` — small UniChem mapping fixture
- `data/UNICHEM_LICENSE.md` — provenance / license note
- `docs/adr/0007-compound-identity-bridge.md` — architectural decision record

**Modified:**
- `lightrag/entity_schema.py` — add `BioactivityEvidence` to `ENTITY_TYPES`, `RELATIONSHIP_TYPES`, `DESCRIPTION_GENERATORS`; add new branches in `describe_relationship`
- `lightrag/ingest_unified.py` — wire bioactivity-evidence extraction into the ingest loop
- `lightrag/extra_sources.py` — add `bioactivity_evidence` adapter
- `scripts/build-herbal-db.ts` — add `compound_identity` + `bioactivity_evidence` table DDL only (table created empty; population is the Python build scripts)
- `Makefile` — add `build-identity`, `build-bioactivity`, `lightrag-ingest-bioactivity` targets
- `pyproject.toml` (lightrag) — add `rdkit-pypi`, `chembl-downloader`, `httpx` deps
- `src/tools.ts` — update label-vocabulary docstring (line ~5–25 region)
- `src/__tests__/tool_catalog.test.ts` — extend label-presence assertions
- `DATASET_PROVENANCE.md` — add ChEMBL 36, UniChem, PubChem PUG-REST entries
- `docs/unified-diet-kg-architecture.md` — diagram update for new entity + relationships
- `README.md` — one-line note in data sources section

---

## Task 1: Add Python deps and identity-bridge skeleton

**Files:**
- Modify: `lightrag/pyproject.toml` (or `lightrag/requirements.txt` if no pyproject)
- Create: `lightrag/identity_bridge.py`
- Test: `lightrag/tests/test_identity_bridge.py`

- [ ] **Step 1: Probe how Python deps are managed in `lightrag/`**

```bash
ls shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/pyproject.toml shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/requirements*.txt 2>/dev/null
```

If `pyproject.toml` exists, modify it. Otherwise modify `requirements.txt` (or create one alongside the existing pattern). Use whichever the project already uses.

- [ ] **Step 2: Add deps**

For `pyproject.toml` (under `[project] dependencies` or `[tool.poetry.dependencies]`):

```toml
"rdkit-pypi>=2023.9.5",
"chembl-downloader>=0.5.0",
"httpx>=0.27.0",
```

For `requirements.txt`:

```
rdkit-pypi>=2023.9.5
chembl-downloader>=0.5.0
httpx>=0.27.0
```

- [ ] **Step 3: Install deps and verify**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag
pip install -r requirements.txt   # or: pip install -e .
python -c "from rdkit import Chem; from rdkit.Chem.inchi import MolToInchiKey; m = Chem.MolFromSmiles('CCO'); print(MolToInchiKey(Chem.MolToInchi(m)))"
```

Expected output: `LFQSCWFLJHTTHZ-UHFFFAOYSA-N` (ethanol's InChIKey)

- [ ] **Step 4: Write the failing test for `compute_inchikey`**

Create `lightrag/tests/test_identity_bridge.py`:

```python
"""Tests for compound identity bridge."""
from lightrag.identity_bridge import compute_inchikey, ResolvedIdentity


def test_compute_inchikey_curcumin():
    """Curcumin SMILES → known InChIKey."""
    smiles = "COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O"
    result = compute_inchikey(smiles)
    assert result.inchikey == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    assert result.inchi.startswith("InChI=1S/")


def test_compute_inchikey_invalid_smiles_returns_none():
    result = compute_inchikey("not-a-valid-smiles")
    assert result is None


def test_compute_inchikey_empty_returns_none():
    assert compute_inchikey("") is None
    assert compute_inchikey(None) is None
```

- [ ] **Step 5: Run test — confirm it fails**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
pytest lightrag/tests/test_identity_bridge.py::test_compute_inchikey_curcumin -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `lightrag.identity_bridge`.

- [ ] **Step 6: Implement `compute_inchikey`**

Create `lightrag/identity_bridge.py`:

```python
"""Compound identity bridge — RDKit + UniChem cross-references.

Maps internal compound IDs (from herbal_botanicals.db) to canonical
InChIKey and external database IDs (PubChem CID, ChEMBL ID, KEGG, ChEBI,
DrugBank) via:

  1. RDKit: SMILES → InChI → InChIKey
  2. UniChem source-mapping files: InChIKey → external IDs (offline, fast)
  3. PubChem PUG-REST: name → InChIKey (online fallback for nameless rows)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResolvedIdentity:
    """Result of identity resolution for a single compound."""
    inchikey: str
    inchi: str
    method: str   # 'rdkit_smiles' | 'pubchem_name_fallback'


def compute_inchikey(smiles: Optional[str]) -> Optional[ResolvedIdentity]:
    """Compute Standard InChI + InChIKey from a SMILES string via RDKit.

    Returns None for empty/None input or RDKit-unparseable SMILES.
    """
    if not smiles:
        return None
    # RDKit imports kept lazy so module-level import doesn't fail in environments
    # where rdkit is intentionally absent (e.g. CI lint stages).
    from rdkit import Chem
    from rdkit.Chem.inchi import MolToInchi, MolToInchiKey

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    inchi = MolToInchi(mol)
    if not inchi:
        return None
    inchikey = MolToInchiKey(mol)
    if not inchikey:
        return None
    return ResolvedIdentity(inchikey=inchikey, inchi=inchi, method="rdkit_smiles")
```

- [ ] **Step 7: Run tests — confirm they pass**

```bash
pytest lightrag/tests/test_identity_bridge.py -v
```

Expected: 3 PASS

- [ ] **Step 8: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/pyproject.toml \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/identity_bridge.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_identity_bridge.py
git commit -m "feat(lightrag): add identity-bridge module with RDKit InChIKey computation"
```

---

## Task 2: UniChem cross-reference loader

**Files:**
- Modify: `lightrag/identity_bridge.py`
- Create: `lightrag/tests/fixtures/unichem_subset.tsv`
- Modify: `lightrag/tests/test_identity_bridge.py`

- [ ] **Step 1: Create the UniChem fixture**

Create `lightrag/tests/fixtures/unichem_subset.tsv`:

```
inchikey	src_id	src_compound_id
VFLDPWHFBUODDF-FCXRPNKRSA-N	1	CHEMBL116438
VFLDPWHFBUODDF-FCXRPNKRSA-N	22	969516
VFLDPWHFBUODDF-FCXRPNKRSA-N	7	3962
LFQSCWFLJHTTHZ-UHFFFAOYSA-N	1	CHEMBL545
LFQSCWFLJHTTHZ-UHFFFAOYSA-N	22	702
LFQSCWFLJHTTHZ-UHFFFAOYSA-N	2	DB00898
RYYVLZVUVIJVGH-UHFFFAOYSA-N	1	CHEMBL113
RYYVLZVUVIJVGH-UHFFFAOYSA-N	22	2519
```

(Curcumin, ethanol, caffeine — three known compounds with mixed ChEMBL/PubChem/DrugBank/ChEBI cross-refs)

- [ ] **Step 2: Write failing tests for UniChem loader**

Append to `lightrag/tests/test_identity_bridge.py`:

```python
from pathlib import Path
from lightrag.identity_bridge import load_unichem_mapping, UNICHEM_SRC


FIXTURES = Path(__file__).parent / "fixtures"


def test_load_unichem_mapping_returns_xrefs_by_inchikey():
    mapping = load_unichem_mapping(FIXTURES / "unichem_subset.tsv")
    curcumin = mapping["VFLDPWHFBUODDF-FCXRPNKRSA-N"]
    assert curcumin["chembl_id"] == "CHEMBL116438"
    assert curcumin["pubchem_cid"] == 969516
    assert curcumin["chebi_id"] == 3962
    assert curcumin.get("drugbank_id") is None  # not in fixture


def test_load_unichem_mapping_handles_multi_source():
    mapping = load_unichem_mapping(FIXTURES / "unichem_subset.tsv")
    ethanol = mapping["LFQSCWFLJHTTHZ-UHFFFAOYSA-N"]
    assert ethanol["chembl_id"] == "CHEMBL545"
    assert ethanol["pubchem_cid"] == 702
    assert ethanol["drugbank_id"] == "DB00898"
    assert ethanol["unichem_src_count"] == 3


def test_unichem_src_constants_match_ebi_codes():
    """Sanity-check src_id constants against EBI's published codes."""
    assert UNICHEM_SRC["chembl"] == 1
    assert UNICHEM_SRC["drugbank"] == 2
    assert UNICHEM_SRC["kegg"] == 6
    assert UNICHEM_SRC["chebi"] == 7
    assert UNICHEM_SRC["pubchem"] == 22
```

- [ ] **Step 3: Run — confirm failure**

```bash
pytest lightrag/tests/test_identity_bridge.py -v
```

Expected: 3 fails on `ImportError: cannot import name 'load_unichem_mapping'`

- [ ] **Step 4: Implement loader**

Append to `lightrag/identity_bridge.py`:

```python
import csv
from pathlib import Path
from typing import Any

# UniChem source IDs — see https://www.ebi.ac.uk/unichem/sources
UNICHEM_SRC: dict[str, int] = {
    "chembl": 1,
    "drugbank": 2,
    "kegg": 6,
    "chebi": 7,
    "pubchem": 22,
}

# Reverse map for fast lookup during TSV parse.
_SRC_BY_ID: dict[int, str] = {v: k for k, v in UNICHEM_SRC.items()}

# Sources whose IDs are integers (everything else stays string).
_INTEGER_SRCS = {"pubchem", "chebi"}


def load_unichem_mapping(tsv_path: Path) -> dict[str, dict[str, Any]]:
    """Load a UniChem source-mapping TSV into {inchikey: {chembl_id, ...}}.

    Expected columns: inchikey \\t src_id \\t src_compound_id

    Returns a dict keyed by InChIKey. Each value contains zero or more of:
    chembl_id, drugbank_id, kegg_compound_id, chebi_id, pubchem_cid,
    plus unichem_src_count (number of sources matched).
    """
    out: dict[str, dict[str, Any]] = {}
    with open(tsv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            ikey = row["inchikey"].strip()
            try:
                src_id = int(row["src_id"])
            except (TypeError, ValueError):
                continue
            src_name = _SRC_BY_ID.get(src_id)
            if src_name is None:
                continue
            entry = out.setdefault(ikey, {})
            value: Any = row["src_compound_id"].strip()
            if src_name in _INTEGER_SRCS:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            field = "kegg_compound_id" if src_name == "kegg" else f"{src_name}_id"
            field = "pubchem_cid" if src_name == "pubchem" else field
            entry[field] = value
    for entry in out.values():
        entry["unichem_src_count"] = sum(
            1 for k in entry if k not in {"unichem_src_count"}
        )
    return out
```

- [ ] **Step 5: Run — confirm pass**

```bash
pytest lightrag/tests/test_identity_bridge.py -v
```

Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/identity_bridge.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_identity_bridge.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/fixtures/unichem_subset.tsv
git commit -m "feat(lightrag): UniChem cross-reference loader for compound identity"
```

---

## Task 3: PubChem PUG-REST name fallback (with cache)

**Files:**
- Modify: `lightrag/identity_bridge.py`
- Modify: `lightrag/tests/test_identity_bridge.py`

- [ ] **Step 1: Write failing test (mocked HTTP)**

Append to `lightrag/tests/test_identity_bridge.py`:

```python
import httpx
from unittest.mock import patch

from lightrag.identity_bridge import resolve_inchikey_by_name


def test_resolve_inchikey_by_name_hits_pubchem(tmp_path):
    cache = tmp_path / "pubchem_cache.json"
    fake_response = httpx.Response(
        status_code=200,
        text="VFLDPWHFBUODDF-FCXRPNKRSA-N\n",
    )
    with patch("httpx.get", return_value=fake_response) as mock_get:
        result = resolve_inchikey_by_name("Curcumin", cache_path=cache)
    assert result == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    mock_get.assert_called_once()
    assert cache.exists()


def test_resolve_inchikey_by_name_uses_cache(tmp_path):
    cache = tmp_path / "pubchem_cache.json"
    cache.write_text('{"Curcumin": "VFLDPWHFBUODDF-FCXRPNKRSA-N"}')
    with patch("httpx.get") as mock_get:
        result = resolve_inchikey_by_name("Curcumin", cache_path=cache)
    assert result == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    mock_get.assert_not_called()


def test_resolve_inchikey_by_name_404_returns_none(tmp_path):
    fake_404 = httpx.Response(status_code=404, text="")
    with patch("httpx.get", return_value=fake_404):
        result = resolve_inchikey_by_name("Bogus-Compound", cache_path=tmp_path / "c.json")
    assert result is None
```

- [ ] **Step 2: Confirm failure**

```bash
pytest lightrag/tests/test_identity_bridge.py -v -k resolve_inchikey
```

Expected: 3 fails on missing `resolve_inchikey_by_name`.

- [ ] **Step 3: Implement**

Append to `lightrag/identity_bridge.py`:

```python
import json
import time

PUBCHEM_PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_RATE_LIMIT_SLEEP_S = 0.25  # ~4 req/s, well under PubChem's 5/s soft limit


def resolve_inchikey_by_name(
    name: str,
    *,
    cache_path: Path,
    timeout_s: float = 10.0,
) -> Optional[str]:
    """Resolve a compound name to an InChIKey via PubChem PUG-REST.

    Uses a JSON file at ``cache_path`` to memoize {name: inchikey | null}.
    A cached null means "we already asked and got 404" — do not re-query.
    """
    import httpx  # lazy import keeps test stubbing simple

    cache: dict[str, Optional[str]] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cache = {}
    if name in cache:
        return cache[name]

    url = f"{PUBCHEM_PUG_REST}/compound/name/{name}/property/InChIKey/TXT"
    resp = httpx.get(url, timeout=timeout_s)
    time.sleep(PUBCHEM_RATE_LIMIT_SLEEP_S)
    if resp.status_code == 404:
        cache[name] = None
    elif resp.status_code == 200:
        cache[name] = resp.text.strip().split("\n")[0] or None
    else:
        # Unexpected status — do NOT cache, surface to caller as None and let
        # the build script's coverage report flag the gap.
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return cache[name]
```

- [ ] **Step 4: Run — confirm pass**

```bash
pytest lightrag/tests/test_identity_bridge.py -v
```

Expected: 9 PASS total

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/identity_bridge.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_identity_bridge.py
git commit -m "feat(lightrag): PubChem PUG-REST name fallback with disk cache"
```

---

## Task 4: SQLite schema for compound_identity + bioactivity_evidence

**Files:**
- Modify: `scripts/build-herbal-db.ts` (add DDL only — population is Python)
- Create: `lightrag/tests/test_schema.py`

- [ ] **Step 1: Locate the existing DDL section in build-herbal-db.ts**

```bash
grep -n "CREATE TABLE" shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build-herbal-db.ts | head -20
```

- [ ] **Step 2: Write failing schema test**

Create `lightrag/tests/test_schema.py`:

```python
"""Verify expected tables exist in herbal_botanicals.db after build."""
import sqlite3
from pathlib import Path
import pytest

DB_PATH = Path(__file__).parent.parent.parent / "data_local" / "herbal_botanicals.db"


def _table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({name})")}


@pytest.mark.skipif(not DB_PATH.exists(), reason="DB not built yet")
def test_compound_identity_table_exists():
    with sqlite3.connect(DB_PATH) as conn:
        cols = _table_columns(conn, "compound_identity")
    assert {"compound_id", "inchikey", "pubchem_cid", "chembl_id",
            "kegg_compound_id", "drugbank_id", "chebi_id",
            "unichem_src_count", "resolution_method", "resolved_at"}.issubset(cols)


@pytest.mark.skipif(not DB_PATH.exists(), reason="DB not built yet")
def test_bioactivity_evidence_table_exists():
    with sqlite3.connect(DB_PATH) as conn:
        cols = _table_columns(conn, "bioactivity_evidence")
    assert {"id", "compound_id", "chembl_compound_id", "chembl_target_id",
            "target_pref_name", "target_organism", "activity_type",
            "relation", "value", "units", "pchembl",
            "assay_confidence", "chembl_doc_id", "publication_year"}.issubset(cols)
```

- [ ] **Step 3: Run — expect skip (DB not built) initially**

```bash
pytest lightrag/tests/test_schema.py -v
```

Expected: 2 SKIPPED.

- [ ] **Step 4: Add DDL to build-herbal-db.ts**

Find the section that creates other tables (search for `CREATE TABLE compounds`). After the last `CREATE TABLE` statement and before any `INSERT`, add:

```typescript
db.exec(`
  CREATE TABLE IF NOT EXISTS compound_identity (
    compound_id          INTEGER PRIMARY KEY,
    inchikey             TEXT,
    inchi                TEXT,
    pubchem_cid          INTEGER,
    chembl_id            TEXT,
    kegg_compound_id     TEXT,
    drugbank_id          TEXT,
    chebi_id             INTEGER,
    unichem_src_count    INTEGER NOT NULL DEFAULT 0,
    resolution_method    TEXT NOT NULL,
    resolved_at          TEXT NOT NULL,
    FOREIGN KEY (compound_id) REFERENCES compounds(id)
  );
  CREATE INDEX IF NOT EXISTS idx_compound_identity_inchikey ON compound_identity(inchikey);
  CREATE INDEX IF NOT EXISTS idx_compound_identity_chembl ON compound_identity(chembl_id);
  CREATE INDEX IF NOT EXISTS idx_compound_identity_pubchem ON compound_identity(pubchem_cid);

  CREATE TABLE IF NOT EXISTS bioactivity_evidence (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    compound_id          INTEGER NOT NULL,
    chembl_compound_id   TEXT NOT NULL,
    chembl_target_id     TEXT NOT NULL,
    target_pref_name     TEXT,
    target_type          TEXT,
    target_organism      TEXT,
    activity_type        TEXT NOT NULL,
    relation             TEXT,
    value                REAL,
    units                TEXT,
    pchembl              REAL,
    activity_comment     TEXT,
    assay_confidence     INTEGER,
    chembl_doc_id        TEXT,
    publication_year     INTEGER,
    ingested_at          TEXT NOT NULL,
    FOREIGN KEY (compound_id) REFERENCES compounds(id)
  );
  CREATE INDEX IF NOT EXISTS idx_bioactivity_compound ON bioactivity_evidence(compound_id);
  CREATE INDEX IF NOT EXISTS idx_bioactivity_target ON bioactivity_evidence(chembl_target_id);
  CREATE INDEX IF NOT EXISTS idx_bioactivity_pchembl ON bioactivity_evidence(pchembl);
`);
console.log('  ✓ Created compound_identity and bioactivity_evidence tables');
```

- [ ] **Step 5: Rebuild the DB**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
make build   # invokes build-herbal-db.ts
```

If `make build` is destructive and you want to preserve existing data, instead run a one-off migration:

```bash
sqlite3 data_local/herbal_botanicals.db <<'SQL'
CREATE TABLE IF NOT EXISTS compound_identity ( ... );  -- copy DDL from above
CREATE TABLE IF NOT EXISTS bioactivity_evidence ( ... );
SQL
```

- [ ] **Step 6: Run schema tests — confirm pass**

```bash
pytest lightrag/tests/test_schema.py -v
```

Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build-herbal-db.ts \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_schema.py
git commit -m "feat(db): add compound_identity and bioactivity_evidence tables"
```

---

## Task 5: build_compound_identity.py CLI

**Files:**
- Create: `scripts/build_compound_identity.py`
- Modify: `Makefile`

- [ ] **Step 1: Write the script**

Create `shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build_compound_identity.py`:

```python
"""Populate compound_identity for all compounds in herbal_botanicals.db.

Pipeline:
  1. RDKit pass — compute InChIKey from SMILES where available
  2. UniChem pass — bulk-load source-mapping TSV, join on InChIKey
  3. PubChem pass — name-based fallback for compounds with no SMILES

Usage:
  python scripts/build_compound_identity.py \\
      --db data_local/herbal_botanicals.db \\
      --unichem-tsv data/unichem_src1_22_2_6_7.tsv \\
      --pubchem-cache data_local/pubchem_name_cache.json \\
      [--no-pubchem]    # skip online fallback
      [--limit 1000]    # for smoke testing
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make "lightrag" importable when running from project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from lightrag.identity_bridge import (
    compute_inchikey,
    load_unichem_mapping,
    resolve_inchikey_by_name,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--unichem-tsv", type=Path, required=True)
    ap.add_argument("--pubchem-cache", type=Path, required=True)
    ap.add_argument("--no-pubchem", action="store_true",
                    help="skip online PubChem fallback")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2
    if not args.unichem_tsv.exists():
        print(f"ERROR: UniChem TSV not found: {args.unichem_tsv}", file=sys.stderr)
        return 2

    print(f"Loading UniChem mapping from {args.unichem_tsv} ...")
    unichem = load_unichem_mapping(args.unichem_tsv)
    print(f"  {len(unichem)} InChIKeys mapped")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = "SELECT id, name, smiles FROM compounds"
    if args.limit:
        query += f" LIMIT {args.limit}"

    rows = list(cur.execute(query))
    total = len(rows)
    resolved_rdkit = 0
    resolved_pubchem = 0
    matched_unichem = 0
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    upsert_sql = """
        INSERT OR REPLACE INTO compound_identity
          (compound_id, inchikey, inchi, pubchem_cid, chembl_id,
           kegg_compound_id, drugbank_id, chebi_id,
           unichem_src_count, resolution_method, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    for row in rows:
        compound_id = row["id"]
        name = row["name"]
        smiles = row["smiles"]

        identity = compute_inchikey(smiles) if smiles else None
        method = identity.method if identity else None
        inchikey = identity.inchikey if identity else None
        inchi = identity.inchi if identity else None

        if inchikey:
            resolved_rdkit += 1
        elif name and not args.no_pubchem:
            inchikey = resolve_inchikey_by_name(
                name, cache_path=args.pubchem_cache
            )
            if inchikey:
                method = "pubchem_name_fallback"
                resolved_pubchem += 1

        xrefs = unichem.get(inchikey, {}) if inchikey else {}
        if xrefs:
            matched_unichem += 1

        if not (inchikey or xrefs):
            # Nothing to write — leave row unmapped. Coverage report flags it.
            continue

        cur.execute(
            upsert_sql,
            (
                compound_id,
                inchikey,
                inchi,
                xrefs.get("pubchem_cid"),
                xrefs.get("chembl_id"),
                xrefs.get("kegg_compound_id"),
                xrefs.get("drugbank_id"),
                xrefs.get("chebi_id"),
                xrefs.get("unichem_src_count", 0),
                method or "unknown",
                now_iso,
            ),
        )

    conn.commit()
    conn.close()

    coverage = matched_unichem / total if total else 0.0
    print(f"\nResolved: {resolved_rdkit} via RDKit, "
          f"{resolved_pubchem} via PubChem fallback")
    print(f"UniChem cross-refs matched: {matched_unichem}/{total} "
          f"({coverage:.1%})")
    if coverage < 0.70:
        print("WARNING: cross-ref coverage below 70% target — see runbook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add Makefile target**

Append to `shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile`:

```makefile
# ─── Compound identity bridge ───────────────────────────────
.PHONY: build-identity build-identity-smoke

UNICHEM_TSV ?= data/unichem_src1_22_2_6_7.tsv
PUBCHEM_CACHE ?= data_local/pubchem_name_cache.json

build-identity:
	python scripts/build_compound_identity.py \
		--db data_local/herbal_botanicals.db \
		--unichem-tsv $(UNICHEM_TSV) \
		--pubchem-cache $(PUBCHEM_CACHE)

build-identity-smoke:
	python scripts/build_compound_identity.py \
		--db data_local/herbal_botanicals.db \
		--unichem-tsv lightrag/tests/fixtures/unichem_subset.tsv \
		--pubchem-cache /tmp/pubchem_cache.json \
		--no-pubchem \
		--limit 100
```

- [ ] **Step 3: Smoke-run on 100-compound slice with the fixture UniChem**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
make build-identity-smoke
```

Expected: prints "Resolved: N via RDKit, 0 via PubChem fallback" with N>0, and "UniChem cross-refs matched: M/100" (M will be small because the fixture only has 3 InChIKeys).

- [ ] **Step 4: Verify rows landed**

```bash
sqlite3 data_local/herbal_botanicals.db "SELECT COUNT(*), COUNT(chembl_id) FROM compound_identity;"
```

Expected: a non-zero pair. If both are zero, debug before proceeding.

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build_compound_identity.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile
git commit -m "feat(scripts): build_compound_identity CLI with RDKit+UniChem+PubChem pipeline"
```

---

## Task 6: ChEMBL extractor module

**Files:**
- Create: `lightrag/chembl_extractor.py`
- Create: `lightrag/tests/test_chembl_extractor.py`
- Create: `lightrag/tests/fixtures/chembl_subset.sqlite`

- [ ] **Step 1: Build the test fixture**

Create a tiny ChEMBL-shaped SQLite for tests. Generate it with a one-off helper script `lightrag/tests/fixtures/_make_chembl_subset.py`:

```python
"""Generate a tiny ChEMBL-shaped SQLite fixture.

Run once; output committed to git as chembl_subset.sqlite (~50 KB).
"""
import sqlite3
from pathlib import Path

OUT = Path(__file__).parent / "chembl_subset.sqlite"
OUT.unlink(missing_ok=True)

conn = sqlite3.connect(OUT)
conn.executescript("""
CREATE TABLE compound_structures (
    molregno INTEGER PRIMARY KEY,
    standard_inchi_key TEXT
);
CREATE TABLE molecule_dictionary (
    molregno INTEGER PRIMARY KEY,
    chembl_id TEXT
);
CREATE TABLE target_dictionary (
    tid INTEGER PRIMARY KEY,
    chembl_id TEXT,
    pref_name TEXT,
    target_type TEXT,
    organism TEXT
);
CREATE TABLE assays (
    assay_id INTEGER PRIMARY KEY,
    tid INTEGER,
    confidence_score INTEGER
);
CREATE TABLE docs (
    doc_id INTEGER PRIMARY KEY,
    chembl_id TEXT,
    year INTEGER
);
CREATE TABLE activities (
    activity_id INTEGER PRIMARY KEY,
    molregno INTEGER,
    assay_id INTEGER,
    doc_id INTEGER,
    standard_type TEXT,
    standard_relation TEXT,
    standard_value REAL,
    standard_units TEXT,
    pchembl_value REAL,
    activity_comment TEXT
);

-- curcumin (CHEMBL116438) inhibits NF-kB
INSERT INTO compound_structures VALUES (1, 'VFLDPWHFBUODDF-FCXRPNKRSA-N');
INSERT INTO molecule_dictionary VALUES (1, 'CHEMBL116438');
INSERT INTO target_dictionary VALUES (100, 'CHEMBL1741221', 'Nuclear factor NF-kappa-B p65', 'SINGLE PROTEIN', 'Homo sapiens');
INSERT INTO assays VALUES (1000, 100, 8);
INSERT INTO docs VALUES (5000, 'CHEMBL1129589', 2018);
INSERT INTO activities VALUES (10000, 1, 1000, 5000, 'IC50', '=', 5000.0, 'nM', 5.30, NULL);

-- caffeine (CHEMBL113) on adenosine A2A receptor
INSERT INTO compound_structures VALUES (2, 'RYYVLZVUVIJVGH-UHFFFAOYSA-N');
INSERT INTO molecule_dictionary VALUES (2, 'CHEMBL113');
INSERT INTO target_dictionary VALUES (200, 'CHEMBL251', 'Adenosine A2a receptor', 'SINGLE PROTEIN', 'Homo sapiens');
INSERT INTO assays VALUES (2000, 200, 9);
INSERT INTO docs VALUES (5001, 'CHEMBL1100001', 2019);
INSERT INTO activities VALUES (10001, 2, 2000, 5001, 'Ki', '=', 2400.0, 'nM', 5.62, NULL);

-- low-confidence row that must be filtered out
INSERT INTO assays VALUES (3000, 200, 3);
INSERT INTO activities VALUES (10002, 2, 3000, 5001, 'IC50', '=', 1e9, 'nM', 0.0, 'noisy');
""")
conn.commit()
conn.close()
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
```

Then:

```bash
python shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/fixtures/_make_chembl_subset.py
```

- [ ] **Step 2: Write failing tests**

Create `lightrag/tests/test_chembl_extractor.py`:

```python
import sqlite3
from pathlib import Path

from lightrag.chembl_extractor import extract_bioactivities_for_inchikeys

FIX = Path(__file__).parent / "fixtures" / "chembl_subset.sqlite"


def _fixture_conn():
    return sqlite3.connect(FIX)


def test_extract_returns_curcumin_nfkb():
    rows = extract_bioactivities_for_inchikeys(
        _fixture_conn(),
        inchikeys=["VFLDPWHFBUODDF-FCXRPNKRSA-N"],
        min_pchembl=5.0,
        min_confidence=5,
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["chembl_compound_id"] == "CHEMBL116438"
    assert r["target_pref_name"] == "Nuclear factor NF-kappa-B p65"
    assert r["activity_type"] == "IC50"
    assert r["pchembl"] == 5.30


def test_extract_filters_low_confidence_assays():
    rows = extract_bioactivities_for_inchikeys(
        _fixture_conn(),
        inchikeys=["RYYVLZVUVIJVGH-UHFFFAOYSA-N"],
        min_pchembl=5.0,
        min_confidence=5,
    )
    # Two activities exist for caffeine; one in a confidence=3 assay must be dropped.
    assert len(rows) == 1
    assert rows[0]["assay_confidence"] == 9


def test_extract_batches_inchikeys():
    """Ensure the function works with a >1000 InChIKey list (batching path)."""
    keys = [f"FAKE{i:040d}-X" for i in range(2500)]
    keys[0] = "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    rows = extract_bioactivities_for_inchikeys(_fixture_conn(), inchikeys=keys)
    assert any(r["chembl_compound_id"] == "CHEMBL116438" for r in rows)
```

- [ ] **Step 3: Run — confirm failure**

```bash
pytest lightrag/tests/test_chembl_extractor.py -v
```

Expected: ImportError on `lightrag.chembl_extractor`.

- [ ] **Step 4: Implement**

Create `lightrag/chembl_extractor.py`:

```python
"""ChEMBL bioactivity extraction — compound-anchored intersect.

For a given list of InChIKeys (the project's resolved compound universe),
return all measured bioactivities meeting the min_pchembl and
min_confidence thresholds.

The extractor accepts an open sqlite3 connection so callers can choose:
  - a local ChEMBL SQLite dump (production: chembl_36_sqlite.tar.gz unpacked)
  - the test fixture (lightrag/tests/fixtures/chembl_subset.sqlite)
"""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable

_BATCH_SIZE = 1000

_SQL = """
SELECT
  cs.standard_inchi_key       AS inchikey,
  md.chembl_id                AS chembl_compound_id,
  td.chembl_id                AS chembl_target_id,
  td.pref_name                AS target_pref_name,
  td.target_type              AS target_type,
  td.organism                 AS target_organism,
  act.standard_type           AS activity_type,
  act.standard_relation       AS relation,
  act.standard_value          AS value,
  act.standard_units          AS units,
  act.pchembl_value           AS pchembl,
  act.activity_comment        AS activity_comment,
  ass.confidence_score        AS assay_confidence,
  doc.chembl_id               AS chembl_doc_id,
  doc.year                    AS publication_year
FROM compound_structures cs
JOIN molecule_dictionary md  ON md.molregno  = cs.molregno
JOIN activities act          ON act.molregno = cs.molregno
JOIN assays ass              ON ass.assay_id = act.assay_id
JOIN target_dictionary td    ON td.tid       = ass.tid
LEFT JOIN docs doc           ON doc.doc_id   = act.doc_id
WHERE cs.standard_inchi_key IN ({placeholders})
  AND act.standard_value IS NOT NULL
  AND (act.standard_relation IS NULL OR act.standard_relation IN ('=', '<', '<='))
  AND ass.confidence_score >= ?
  AND act.pchembl_value >= ?
"""


def extract_bioactivities_for_inchikeys(
    conn: sqlite3.Connection,
    *,
    inchikeys: Iterable[str],
    min_pchembl: float = 5.0,
    min_confidence: int = 5,
) -> list[dict[str, Any]]:
    """Return bioactivity rows for the given InChIKeys.

    Batches the IN-list to avoid SQLite parameter limits (default 999/2000).
    """
    keys = [k for k in inchikeys if k]
    out: list[dict[str, Any]] = []
    for i in range(0, len(keys), _BATCH_SIZE):
        batch = keys[i:i + _BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        sql = _SQL.format(placeholders=placeholders)
        params = (*batch, min_confidence, min_pchembl)
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            out.append(dict(zip(cols, row)))
    return out
```

- [ ] **Step 5: Run — confirm pass**

```bash
pytest lightrag/tests/test_chembl_extractor.py -v
```

Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/chembl_extractor.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_chembl_extractor.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/fixtures/chembl_subset.sqlite \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/fixtures/_make_chembl_subset.py
git commit -m "feat(lightrag): ChEMBL bioactivity extractor with confidence + pChEMBL filtering"
```

---

## Task 7: build_bioactivity_evidence.py CLI

**Files:**
- Create: `scripts/build_bioactivity_evidence.py`
- Modify: `Makefile`

- [ ] **Step 1: Write the script**

Create `shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build_bioactivity_evidence.py`:

```python
"""Populate bioactivity_evidence in herbal_botanicals.db from a ChEMBL dump.

Reads InChIKeys from compound_identity, intersects against a local ChEMBL
SQLite dump, applies pChEMBL/confidence filters, writes results.

Usage:
  # Production (downloads ChEMBL 36 dump if absent ~12GB)
  python scripts/build_bioactivity_evidence.py \\
      --db data_local/herbal_botanicals.db \\
      --chembl-version 36 \\
      --min-pchembl 5.0 --min-confidence 5

  # Smoke (use fixture)
  python scripts/build_bioactivity_evidence.py \\
      --db data_local/herbal_botanicals.db \\
      --chembl-sqlite lightrag/tests/fixtures/chembl_subset.sqlite \\
      --min-pchembl 5.0 --min-confidence 5
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lightrag.chembl_extractor import extract_bioactivities_for_inchikeys


def _open_chembl(args: argparse.Namespace) -> sqlite3.Connection:
    if args.chembl_sqlite:
        return sqlite3.connect(args.chembl_sqlite)
    # Production path: chembl-downloader returns a context manager.
    import chembl_downloader  # type: ignore[import-not-found]
    sqlite_path = chembl_downloader.download_extract_sqlite(version=str(args.chembl_version))
    print(f"Using ChEMBL {args.chembl_version} at {sqlite_path}")
    return sqlite3.connect(sqlite_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--chembl-sqlite", type=Path,
                     help="path to a local ChEMBL SQLite dump or fixture")
    src.add_argument("--chembl-version", type=int,
                     help="ChEMBL release to fetch via chembl-downloader (e.g. 36)")
    ap.add_argument("--min-pchembl", type=float, default=5.0)
    ap.add_argument("--min-confidence", type=int, default=5)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    target_conn = sqlite3.connect(args.db)
    target_conn.row_factory = sqlite3.Row
    cur = target_conn.cursor()

    # Build InChIKey → compound_id lookup from compound_identity.
    rows = list(cur.execute(
        "SELECT inchikey, compound_id FROM compound_identity "
        "WHERE inchikey IS NOT NULL"
    ))
    if not rows:
        print("ERROR: compound_identity is empty. Run build-identity first.",
              file=sys.stderr)
        return 3
    inchikey_to_compound: dict[str, int] = {r["inchikey"]: r["compound_id"] for r in rows}
    print(f"Querying ChEMBL for {len(inchikey_to_compound)} InChIKeys ...")

    chembl_conn = _open_chembl(args)
    bioactivities = extract_bioactivities_for_inchikeys(
        chembl_conn,
        inchikeys=list(inchikey_to_compound),
        min_pchembl=args.min_pchembl,
        min_confidence=args.min_confidence,
    )
    chembl_conn.close()

    print(f"Got {len(bioactivities)} bioactivity rows passing filters")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_sql = """
        INSERT INTO bioactivity_evidence (
          compound_id, chembl_compound_id, chembl_target_id,
          target_pref_name, target_type, target_organism,
          activity_type, relation, value, units, pchembl,
          activity_comment, assay_confidence, chembl_doc_id,
          publication_year, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    # Idempotent re-runs: drop prior rows first. (Phase 1 simplicity.)
    cur.execute("DELETE FROM bioactivity_evidence")

    inserted = 0
    for r in bioactivities:
        compound_id = inchikey_to_compound.get(r["inchikey"])
        if compound_id is None:
            continue
        cur.execute(insert_sql, (
            compound_id, r["chembl_compound_id"], r["chembl_target_id"],
            r["target_pref_name"], r["target_type"], r["target_organism"],
            r["activity_type"], r["relation"], r["value"], r["units"],
            r["pchembl"], r["activity_comment"], r["assay_confidence"],
            r["chembl_doc_id"], r["publication_year"], now_iso,
        ))
        inserted += 1

    target_conn.commit()
    target_conn.close()
    print(f"Inserted {inserted} bioactivity_evidence rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add Makefile targets**

Append to `Makefile`:

```makefile
.PHONY: build-bioactivity build-bioactivity-smoke

build-bioactivity:
	python scripts/build_bioactivity_evidence.py \
		--db data_local/herbal_botanicals.db \
		--chembl-version 36 \
		--min-pchembl 5.0 --min-confidence 5

build-bioactivity-smoke:
	python scripts/build_bioactivity_evidence.py \
		--db data_local/herbal_botanicals.db \
		--chembl-sqlite lightrag/tests/fixtures/chembl_subset.sqlite \
		--min-pchembl 5.0 --min-confidence 5
```

- [ ] **Step 3: Smoke-run**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
make build-bioactivity-smoke
```

Expected: "Inserted N bioactivity_evidence rows" (N>=0; will be 0 if no compounds in compound_identity match the fixture's 2 InChIKeys — expected for the smoke flow).

- [ ] **Step 4: Verify schema-correct insert via direct fixture seed**

For a more meaningful smoke, manually seed compound_identity with the fixture InChIKeys, then re-run:

```bash
sqlite3 data_local/herbal_botanicals.db <<SQL
INSERT OR REPLACE INTO compound_identity
  (compound_id, inchikey, resolution_method, resolved_at)
VALUES
  (1, 'VFLDPWHFBUODDF-FCXRPNKRSA-N', 'manual_smoke', datetime('now')),
  (2, 'RYYVLZVUVIJVGH-UHFFFAOYSA-N', 'manual_smoke', datetime('now'));
SQL
make build-bioactivity-smoke
sqlite3 data_local/herbal_botanicals.db "SELECT chembl_compound_id, target_pref_name, pchembl FROM bioactivity_evidence;"
```

Expected output:

```
CHEMBL116438|Nuclear factor NF-kappa-B p65|5.3
CHEMBL113|Adenosine A2a receptor|5.62
```

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build_bioactivity_evidence.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile
git commit -m "feat(scripts): build_bioactivity_evidence CLI with chembl-downloader integration"
```

---

## Task 8: Extend LightRAG entity_schema with BioactivityEvidence

**Files:**
- Modify: `lightrag/entity_schema.py`
- Create: `lightrag/tests/test_entity_schema.py`

- [ ] **Step 1: Read the existing schema dictionaries**

```bash
grep -n "ENTITY_TYPES\|RELATIONSHIP_TYPES\|DESCRIPTION_GENERATORS" \
  shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/entity_schema.py | head -20
```

Note the line numbers — you'll add entries to those dictionaries.

- [ ] **Step 2: Write failing tests**

Create `lightrag/tests/test_entity_schema.py`:

```python
from lightrag.entity_schema import (
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
    DESCRIPTION_GENERATORS,
    describe_relationship,
)


def test_bioactivity_evidence_entity_registered():
    assert "BioactivityEvidence" in ENTITY_TYPES
    et = ENTITY_TYPES["BioactivityEvidence"]
    assert et["source_table"] == "bioactivity_evidence"
    assert et["id_field"] == "id"
    assert "BioactivityEvidence" in DESCRIPTION_GENERATORS


def test_describe_bioactivity_evidence_renders_full_text():
    gen = DESCRIPTION_GENERATORS["BioactivityEvidence"]
    desc = gen({
        "id": 1,
        "compound_id": 42,
        "chembl_compound_id": "CHEMBL116438",
        "chembl_target_id": "CHEMBL1741221",
        "target_pref_name": "Nuclear factor NF-kappa-B p65",
        "target_organism": "Homo sapiens",
        "activity_type": "IC50",
        "relation": "=",
        "value": 5000.0,
        "units": "nM",
        "pchembl": 5.3,
        "assay_confidence": 8,
        "chembl_doc_id": "CHEMBL1129589",
        "publication_year": 2018,
    })
    assert "IC50" in desc
    assert "5000" in desc or "5.3" in desc
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "Homo sapiens" in desc
    assert "CHEMBL1129589" in desc


def test_has_evidence_relationship_described():
    desc, kw = describe_relationship("HAS_EVIDENCE", {
        "src_name": "Curcumin",
        "tgt_name": "BioactivityEvidence#1",
        "pchembl": 5.3,
        "activity_type": "IC50",
    })
    assert "Curcumin" in desc
    assert "evidence" in desc.lower() or "ic50" in desc.lower()


def test_evidence_for_target_relationship_described():
    desc, kw = describe_relationship("EVIDENCE_FOR_TARGET", {
        "src_name": "BioactivityEvidence#1",
        "tgt_name": "Nuclear factor NF-kappa-B p65",
        "confidence_score": 8,
        "year": 2018,
    })
    assert "Nuclear factor NF-kappa-B p65" in desc
```

- [ ] **Step 3: Confirm failure**

```bash
pytest lightrag/tests/test_entity_schema.py -v
```

Expected: 4 fails, missing `BioactivityEvidence` keys.

- [ ] **Step 4: Add entity definition to ENTITY_TYPES**

In `lightrag/entity_schema.py`, find the `ENTITY_TYPES` dict and add this entry alongside the existing ones (after `Symptom`, before tenant entity types):

```python
"BioactivityEvidence": {
    "source_table": "bioactivity_evidence",
    "id_field": "id",
    "name_field": "id",  # synthetic name composed in the description
    "query": (
        "SELECT id, compound_id, chembl_compound_id, chembl_target_id, "
        "target_pref_name, target_type, target_organism, activity_type, "
        "relation, value, units, pchembl, assay_confidence, chembl_doc_id, "
        "publication_year FROM bioactivity_evidence ORDER BY id"
    ),
},
```

- [ ] **Step 5: Add description generator**

Find the `describe_*` functions and add a new one. Place near the other entity describers:

```python
def describe_bioactivity_evidence(row: dict[str, Any]) -> str:
    """Render a single ChEMBL bioactivity record as a search-rich description."""
    relation = row.get("relation") or "="
    value = row.get("value")
    units = row.get("units") or ""
    activity_type = row.get("activity_type") or "activity"
    target = row.get("target_pref_name") or row.get("chembl_target_id") or "unknown target"
    organism = row.get("target_organism") or ""
    pchembl = row.get("pchembl")
    confidence = row.get("assay_confidence")
    year = row.get("publication_year")
    doc_id = row.get("chembl_doc_id") or ""
    chembl_compound = row.get("chembl_compound_id") or "?"

    parts: list[str] = [
        f"BioactivityEvidence: {chembl_compound} {relation} "
        f"{value if value is not None else '?'}{units} {activity_type} "
        f"against {target}"
    ]
    if organism:
        parts.append(f"({organism})")
    extras: list[str] = []
    if pchembl is not None:
        extras.append(f"pChEMBL {pchembl}")
    if confidence is not None:
        extras.append(f"assay confidence {confidence}")
    if year:
        extras.append(f"year {year}")
    if doc_id:
        extras.append(f"doc {doc_id}")
    if extras:
        parts.append("; " + ", ".join(extras))
    return "".join(parts)
```

Then add to `DESCRIPTION_GENERATORS`:

```python
DESCRIPTION_GENERATORS = {
    # ... existing entries ...
    "BioactivityEvidence": describe_bioactivity_evidence,
    # ... rest of existing tenant entries unchanged ...
}
```

- [ ] **Step 6: Add relationship branches to describe_relationship**

In `describe_relationship`, add these branches before the final fallback `return`:

```python
if rel_type == "HAS_EVIDENCE":
    pchembl = row.get("pchembl")
    atype = row.get("activity_type", "")
    desc = f"{src} has measured evidence ({atype}"
    if pchembl is not None:
        desc += f", pChEMBL {pchembl}"
    desc += f") in {tgt}"
    return desc, "compound bioactivity evidence chembl measurement"

if rel_type == "EVIDENCE_FOR_TARGET":
    confidence = row.get("confidence_score")
    year = row.get("year")
    desc = f"{src} reports activity against {tgt}"
    extras = []
    if confidence is not None:
        extras.append(f"assay confidence {confidence}")
    if year:
        extras.append(f"year {year}")
    if extras:
        desc += " (" + ", ".join(extras) + ")"
    return desc, "evidence target measurement assay confidence"
```

- [ ] **Step 7: Add to RELATIONSHIP_TYPES**

Find `RELATIONSHIP_TYPES` and add entries for the two new types. Use the same shape as existing entries (likely `{src_table, tgt_table, query}`):

```python
"HAS_EVIDENCE": {
    "src_label": "Compound",
    "tgt_label": "BioactivityEvidence",
    "query": (
        "SELECT c.name AS src_name, be.id AS tgt_name, "
        "be.pchembl AS pchembl, be.activity_type AS activity_type "
        "FROM bioactivity_evidence be "
        "JOIN compounds c ON c.id = be.compound_id "
        "ORDER BY be.id"
    ),
},
"EVIDENCE_FOR_TARGET": {
    "src_label": "BioactivityEvidence",
    "tgt_label": "Target",
    "query": (
        "SELECT be.id AS src_name, "
        "  COALESCE(t.name, be.target_pref_name) AS tgt_name, "
        "  be.assay_confidence AS confidence_score, "
        "  be.publication_year AS year "
        "FROM bioactivity_evidence be "
        "LEFT JOIN targets t ON t.name = be.target_pref_name "
        "ORDER BY be.id"
    ),
},
```

(If RELATIONSHIP_TYPES uses a different shape than this, mirror the shape used by `TARGETS_PROTEIN` exactly — read it first and adjust.)

- [ ] **Step 8: Run tests — confirm pass**

```bash
pytest lightrag/tests/test_entity_schema.py -v
```

Expected: 4 PASS.

- [ ] **Step 9: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/entity_schema.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_entity_schema.py
git commit -m "feat(lightrag): register BioactivityEvidence entity + HAS_EVIDENCE/EVIDENCE_FOR_TARGET edges"
```

---

## Task 9: Wire bioactivity into ingest_unified.py

**Files:**
- Modify: `lightrag/ingest_unified.py`
- Modify: `lightrag/extra_sources.py` (if the ingestor delegates non-core entities there)
- Create: `lightrag/tests/test_ingest_bioactivity.py`

- [ ] **Step 1: Skim ingest_unified.py to learn the integration pattern**

```bash
grep -n "ENTITY_TYPES\|RELATIONSHIP_TYPES\|extract_entities\|extract_relationships" \
  shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/ingest_unified.py | head -30
```

The dictionaries-driven extraction means the new entries from Task 8 should already flow through. This task is to add an integration test confirming that, plus a guarded extraction path that skips bioactivity when the table is empty (so existing CI runs without bioactivity data don't break).

- [ ] **Step 2: Write failing integration test**

Create `lightrag/tests/test_ingest_bioactivity.py`:

```python
"""End-to-end check that bioactivity_evidence flows through extract_entities."""
import sqlite3
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lightrag.entity_schema import ENTITY_TYPES, DESCRIPTION_GENERATORS
from lightrag.ingest_unified import extract_entities


@pytest.fixture
def populated_db(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE compounds (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE bioactivity_evidence (
          id INTEGER PRIMARY KEY,
          compound_id INTEGER,
          chembl_compound_id TEXT,
          chembl_target_id TEXT,
          target_pref_name TEXT,
          target_type TEXT,
          target_organism TEXT,
          activity_type TEXT,
          relation TEXT,
          value REAL,
          units TEXT,
          pchembl REAL,
          assay_confidence INTEGER,
          chembl_doc_id TEXT,
          publication_year INTEGER
        );
        INSERT INTO compounds VALUES (1, 'Curcumin');
        INSERT INTO bioactivity_evidence VALUES (
          1, 1, 'CHEMBL116438', 'CHEMBL1741221',
          'Nuclear factor NF-kappa-B p65', 'SINGLE PROTEIN', 'Homo sapiens',
          'IC50', '=', 5000.0, 'nM', 5.3, 8, 'CHEMBL1129589', 2018
        );
    """)
    conn.commit()
    return conn


def test_extract_entities_yields_bioactivity_evidence(populated_db):
    entities = extract_entities(populated_db, entity_types=["BioactivityEvidence"])
    bio = list(entities.get("BioactivityEvidence", []))
    assert len(bio) == 1
    assert "Nuclear factor NF-kappa-B p65" in bio[0]["description"]
    assert "IC50" in bio[0]["description"]
```

(If `extract_entities` doesn't accept an `entity_types` filter, adapt this test to call the actual ingest entrypoint with a small subset — read the function signature first.)

- [ ] **Step 3: Run test — confirm fail**

```bash
pytest lightrag/tests/test_ingest_bioactivity.py -v
```

Expected: failure either on missing fixture table or on missing `entity_types` param. Adapt:
  - If the failure is "table does not exist" — confirm the test's DDL matches what schema in Task 4 created.
  - If the failure is `extract_entities` signature mismatch — read the function and adjust the test to use the real signature (e.g., loop over `ENTITY_TYPES.keys()` and call the per-type extractor).

- [ ] **Step 4: Add a graceful skip for missing tables in ingest_unified.py**

In `extract_entities` (or wherever the per-type query runs), wrap the SELECT in a `table_exists` check (the helper already exists in ingest_unified.py — see the head of the file). If `bioactivity_evidence` is missing, log a one-line "skipping BioactivityEvidence — table not present" and continue.

The existing dispatcher likely already does this for tenant tables. Mirror the same pattern.

- [ ] **Step 5: Run test — confirm pass**

```bash
pytest lightrag/tests/test_ingest_bioactivity.py -v
```

Expected: PASS.

- [ ] **Step 6: Add a Makefile target for the bioactivity-only ingest**

Append to `Makefile`:

```makefile
.PHONY: lightrag-ingest-bioactivity

lightrag-ingest-bioactivity:
	python lightrag/ingest_unified.py --config local \
		--only-entities BioactivityEvidence \
		--only-relationships HAS_EVIDENCE,EVIDENCE_FOR_TARGET \
		--batch-size 1000
```

(If `ingest_unified.py` doesn't currently support `--only-entities` / `--only-relationships` flags, add them as small additions — they're a clean way to scope a re-ingest without rebuilding the whole graph.)

- [ ] **Step 7: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/ingest_unified.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_ingest_bioactivity.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile
git commit -m "feat(lightrag): wire BioactivityEvidence into extract_entities + add scoped ingest target"
```

---

## Task 10: MCP label-vocabulary docstring + test

**Files:**
- Modify: `src/tools.ts`
- Modify: `src/__tests__/tool_catalog.test.ts`

- [ ] **Step 1: Update the file docstring in src/tools.ts**

Open `src/tools.ts` and locate the comment listing entity-type vocabulary. Add `BioactivityEvidence` to that list. If no such list exists, add one near the file header:

```typescript
/**
 * Entity vocabulary surfaced through these primitives (post-ingest):
 *
 *   Domain:  Herb, Compound, Food, Target, Disease, Symptom,
 *            BioactivityEvidence  ← NEW (ChEMBL drug-target evidence)
 *   Tenant:  Protocol, Intervention, Outcome, Biomarker
 *
 * Relationships (selected):
 *   CONTAINS_COMPOUND, FOUND_IN_FOOD, TARGETS_PROTEIN,
 *   ASSOCIATED_WITH_DISEASE, TREATS_SYMPTOM,
 *   HAS_EVIDENCE, EVIDENCE_FOR_TARGET   ← NEW
 */
```

- [ ] **Step 2: Extend the tool_catalog test**

Open `src/__tests__/tool_catalog.test.ts` and add an assertion that the docstring/region mentions the new vocabulary. If the test reads the source file:

```typescript
import fs from 'node:fs';
import path from 'node:path';

it('tools.ts docstring lists BioactivityEvidence vocabulary', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'tools.ts'),
    'utf8',
  );
  expect(src).toContain('BioactivityEvidence');
  expect(src).toContain('HAS_EVIDENCE');
  expect(src).toContain('EVIDENCE_FOR_TARGET');
});
```

If the existing tests use a different mechanism (importing the tool catalog), mirror that pattern — the goal is just a regression that flags accidental removal.

- [ ] **Step 3: Run TS tests**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
npm test -- tool_catalog
```

Expected: all assertions PASS.

- [ ] **Step 4: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/src/tools.ts \
        shrine-diet-bioactivity/shrine-diet-bioactivity/src/__tests__/tool_catalog.test.ts
git commit -m "docs(mcp): add BioactivityEvidence vocabulary to tools.ts label list"
```

---

## Task 11: Provenance + ADR + arch doc updates

**Files:**
- Modify: `DATASET_PROVENANCE.md`
- Modify: `docs/unified-diet-kg-architecture.md`
- Create: `docs/adr/0007-compound-identity-bridge.md`
- Modify: `README.md`
- Create: `data/UNICHEM_LICENSE.md`

- [ ] **Step 1: Append to DATASET_PROVENANCE.md**

Append:

```markdown
## ChEMBL 36 (added 2026-05-06)

- **Source:** EBI ChEMBL — https://chembl.gitbook.io/chembl-interface-documentation/downloads
- **Version:** Release 36 (July 2025)
- **DOI:** 10.6019/CHEMBL.database.36
- **License:** CC BY-SA 3.0
- **Access:** `chembl-downloader` (PyPI) auto-fetches and unpacks SQLite dump
- **Used by:** `scripts/build_bioactivity_evidence.py`
- **Filters applied at ingest:** assay confidence_score ≥ 5; pChEMBL ≥ 5.0; standard_relation ∈ {=, <, ≤}

## UniChem source-mapping (added 2026-05-06)

- **Source:** EBI UniChem — https://www.ebi.ac.uk/unichem/
- **Sources mapped:** src_id 1 (ChEMBL), 2 (DrugBank), 6 (KEGG), 7 (ChEBI), 22 (PubChem)
- **License:** Free, follows ChEMBL versioning
- **Used by:** `scripts/build_compound_identity.py`
- **License note:** see `data/UNICHEM_LICENSE.md`

## PubChem PUG-REST (added 2026-05-06)

- **Source:** NCBI PubChem — https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
- **License:** Public Domain (US Gov)
- **Access:** REST endpoint `/compound/name/{name}/property/InChIKey/TXT`
- **Rate limit applied:** ~4 req/s (well under 5/s soft limit); on-disk cache prevents re-querying
- **Used by:** `scripts/build_compound_identity.py` (name fallback only)
```

- [ ] **Step 2: Update unified-diet-kg-architecture.md**

In the "Data Sources by Modality" diagram, add a new structured-source box:

```
ChEMBL 36 (compound-anchored intersect)
─────────────────────────────────────
~10–50 bioactivities per matched compound
Filtered: pChEMBL ≥ 5.0, confidence ≥ 5
```

In the entity-types section, add `BioactivityEvidence` (7th entity type). In the relationships section, add `HAS_EVIDENCE` and `EVIDENCE_FOR_TARGET`.

- [ ] **Step 3: Create ADR**

Create `docs/adr/0007-compound-identity-bridge.md`:

```markdown
# ADR 0007: Compound identity bridge + ChEMBL evidence layer

**Date:** 2026-05-06
**Status:** Accepted

## Context

The KG holds ~100K compounds across multiple sources (Duke, FooDB, CMAUP, CTD, TTD) with no single shared identifier. Without a normalized identity layer, we can't join measured drug-target evidence (ChEMBL) into the same graph that holds dietary occurrence (FooDB).

## Decision

Build a `compound_identity` SQLite table populated by:
1. RDKit `MolToInchiKey` on existing SMILES
2. UniChem source-mapping files for cross-refs
3. PubChem PUG-REST for nameless rows

Then load ChEMBL bioactivities as a new `BioactivityEvidence` entity in LightRAG, joined to existing `Compound` and `Target` nodes.

## Alternatives considered

- **Full ChEMBL mirror.** Rejected — multi-GB ingest, mostly drug rows with no dietary relevance.
- **Online-only resolver via PubChem PUG-REST.** Rejected — rate limits make the 100K compound build infeasible; offline UniChem files are bounded and reproducible.
- **New MCP tool surface for evidence queries.** Rejected — violates the project's thin-adapter MCP architecture (`FORBIDDEN_USECASE_VERBS` guard in `src/tools.ts`).

## Consequences

- ChEMBL release pin is part of reproducibility (recorded in DATASET_PROVENANCE.md).
- Coverage <70% on cross-refs surfaces in build script output and runbook — does not block ingest.
- New entity is queryable through existing `semantic-search`, `get-entity`, `get-subgraph` primitives — no MCP tool surface change.
```

- [ ] **Step 4: Create UNICHEM_LICENSE.md**

```markdown
# UniChem source-mapping files

Source: https://www.ebi.ac.uk/unichem/

These files are freely available for academic and commercial use following
ChEMBL's CC BY-SA 3.0 terms (UniChem distributes the same compound
identifiers ChEMBL maps to other sources).

We download the InChIKey↔external-ID mappings for src_id ∈ {1, 2, 6, 7, 22}
(ChEMBL, DrugBank, KEGG, ChEBI, PubChem). The PubChem and ChEBI columns
parse as integers; the rest are opaque strings.
```

- [ ] **Step 5: One-line README update**

In `README.md`, in the data-sources section, add: `- ChEMBL 36 + UniChem (compound-identity bridge → bioactivity evidence) — see ADR 0007`.

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/DATASET_PROVENANCE.md \
        shrine-diet-bioactivity/shrine-diet-bioactivity/docs/unified-diet-kg-architecture.md \
        shrine-diet-bioactivity/shrine-diet-bioactivity/docs/adr/0007-compound-identity-bridge.md \
        shrine-diet-bioactivity/shrine-diet-bioactivity/data/UNICHEM_LICENSE.md \
        shrine-diet-bioactivity/shrine-diet-bioactivity/README.md
git commit -m "docs: ADR 0007 + provenance for ChEMBL/UniChem/PubChem identity bridge"
```

---

## Task 12: Coverage check + final smoke

**Files:**
- (none new)

- [ ] **Step 1: Run all new tests**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
pytest lightrag/tests/test_identity_bridge.py \
       lightrag/tests/test_chembl_extractor.py \
       lightrag/tests/test_schema.py \
       lightrag/tests/test_entity_schema.py \
       lightrag/tests/test_ingest_bioactivity.py \
       --cov=lightrag.identity_bridge \
       --cov=lightrag.chembl_extractor \
       --cov-report=term-missing -v
```

Expected: all PASS, coverage ≥80% on the two new modules. If coverage <80%, add focused tests for any uncovered branches.

- [ ] **Step 2: Run TS regression**

```bash
npm test -- tool_catalog
```

Expected: PASS.

- [ ] **Step 3: Full smoke — identity + bioactivity end-to-end on fixtures**

```bash
make build-identity-smoke
make build-bioactivity-smoke
sqlite3 data_local/herbal_botanicals.db <<'SQL'
SELECT 'compound_identity rows', COUNT(*) FROM compound_identity;
SELECT 'bioactivity_evidence rows', COUNT(*) FROM bioactivity_evidence;
SELECT 'compounds with bioactivity', COUNT(DISTINCT compound_id) FROM bioactivity_evidence;
SQL
```

Expected: non-zero counts on all three.

- [ ] **Step 4: Commit any incidental fixes from smoke**

```bash
git status
# if changes: git add ... && git commit -m "test: smoke fixes from end-to-end validation"
```

---

## Self-review notes (writing-plans skill)

**Spec coverage:**
- §4.1 identity bridge → Tasks 1, 2, 3, 5
- §4.2 ChEMBL slice → Tasks 6, 7
- §4.3 LightRAG schema → Task 8, 9
- §4.4 MCP tool surface (no new tools) → Task 10
- §4.5 tests → present in every code task; final sweep in Task 12
- §6 reproducibility/licensing → Task 11
- §9 DoD → Task 12 covers the verifiable items

**Type consistency:** `compound_id`, `inchikey`, `chembl_id`, `chembl_compound_id`, `chembl_target_id`, `pchembl`, `assay_confidence` used consistently across SQLite DDL (Task 4), extractor (Task 6), CLI insert (Task 7), entity description (Task 8), and tests. No drift.

**Placeholder scan:** none.

**Scope check:** single PR — confirmed in spec §4 and reflected in plan structure (12 tasks, ~hours of execution, all under one feature branch).
