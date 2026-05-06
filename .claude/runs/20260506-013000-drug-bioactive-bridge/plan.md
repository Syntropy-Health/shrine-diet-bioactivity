<!-- harden-plan: hardened on 2026-05-06T01:32:00Z. See dependencies.json + runbook.md in this dir. -->

# Drug ↔ Bioactive Bridge — Phase 1 Implementation Plan (HARDENED)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Inner loop is superpowers:test-driven-development.

**Goal:** Add a compound-identity bridge (name→PubChem→UniChem cross-refs) and a ChEMBL-backed bioactivity-evidence layer to the existing Diet KG so symptom→food and diet→effects queries can traverse measured drug-target evidence end-to-end.

**Architecture (post-harden):** New SQLite tables `compound_identity` and `bioactivity_evidence` in `data_local/herbal_botanicals.db`, populated from PubChem PUG-REST name resolution + UniChem source-mapping files + a pinned ChEMBL 36 SQLite dump (via `chembl-downloader`). New LightRAG entity type `BioactivityEvidence` with two new relationship types, ingested through the existing `ainsert_custom_kg` path. Zero new MCP tools — the existing thin-adapter primitives surface the new entities for free.

**Architecture changes vs. original plan (set during harden-plan probe):**
1. **No SMILES, no PubChem CIDs in current `compounds` table** (94,512 rows, 0 with cid, no smiles column). RDKit-from-SMILES path replaced by name→PubChem PUG-REST as primary; RDKit retained for verification only when PubChem returns SMILES. See runbook `harden-plan/data/missing-smiles-column`.
2. **Phase 1 scope reduced** from "all 94K compounds" to "compounds in active relationships" (`herb_compounds` ∪ `compound_targets` ≈ 25K). Full backfill is Phase 2. See runbook `harden-plan/scope/full-94k-name-resolution-deferred`.
3. **`compounds.id` is TEXT** (not INTEGER); DDL adjusted accordingly.
4. **`lightrag/` lacks `__init__.py`**; Task 0 adds it so test imports work.
5. **`targets.uniprot_id` IS populated** — bonus path: target-anchored ChEMBL extract via UniProt accession (still compound-anchored at the spec level — we filter the result set by our resolved InChIKey set, but query ChEMBL via UniProt to short-circuit the join).

**Tech Stack:** Python 3.10+, RDKit (`rdkit-pypi`), `chembl-downloader`, `httpx`, sqlite3, LightRAG, Neo4j 5.26+, pytest. TypeScript-side: vitest regression on `tools.ts` label catalog only.

**Project root for paths below:** `shrine-diet-bioactivity/shrine-diet-bioactivity/` (the inner project dir). All file paths in tasks are relative to that directory unless explicitly absolute.

**Secrets needed (none new):** Phase 1 uses only public, unauthenticated data sources. ChEMBL/UniChem/PubChem all public; LightRAG continues to use existing `OLLAMA_BASE_URL` (local) or `OPENAI_API_KEY` (production) per `lightrag/config_local.env` / `config_production.env`.

---

## File map (created / modified)

**Created:**
- `lightrag/__init__.py` — empty marker file (Task 0)
- `lightrag/identity_bridge.py`
- `lightrag/chembl_extractor.py`
- `scripts/build_compound_identity.py`
- `scripts/build_bioactivity_evidence.py`
- `lightrag/tests/__init__.py` — empty
- `lightrag/tests/test_identity_bridge.py`
- `lightrag/tests/test_chembl_extractor.py`
- `lightrag/tests/test_schema.py`
- `lightrag/tests/test_entity_schema.py`
- `lightrag/tests/test_ingest_bioactivity.py`
- `lightrag/tests/fixtures/chembl_subset.sqlite`
- `lightrag/tests/fixtures/_make_chembl_subset.py`
- `lightrag/tests/fixtures/unichem_subset.tsv`
- `data/UNICHEM_LICENSE.md`
- `docs/adr/0007-compound-identity-bridge.md`

**Modified:**
- `lightrag/entity_schema.py` — add `BioactivityEvidence`
- `lightrag/ingest_unified.py` — wire bioactivity flow + `--only-entities` flag
- `lightrag/requirements.txt` — add `rdkit-pypi`, `chembl-downloader` (httpx already present transitively)
- `scripts/build-herbal-db.ts` — add DDL for new tables
- `Makefile` — add `build-identity`, `build-bioactivity`, `lightrag-ingest-bioactivity` targets
- `src/tools.ts` — update label-vocabulary docstring
- `src/__tests__/tool_catalog.test.ts` — extend label-presence assertions
- `DATASET_PROVENANCE.md`
- `docs/unified-diet-kg-architecture.md`
- `README.md`

---

## Task 0: Pre-flight setup (NEW — added by harden-plan)

**Files:**
- Modify: `lightrag/requirements.txt`
- Create: `lightrag/__init__.py`
- Create: `lightrag/tests/__init__.py`

- [ ] **Step 1: Add deps to `lightrag/requirements.txt`**

Append at the bottom of the file:

```
rdkit-pypi>=2023.9.5
chembl-downloader>=0.5.0
```

(`httpx` is already pulled in transitively via `lightrag-hku[api]`; verify before adding.)

- [ ] **Step 2: Install**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag
pip install -r requirements.txt
```

If `rdkit-pypi` install fails on a minimal container, install OS deps first:

```bash
sudo apt-get install -y libxrender1 libxext6
pip install -r requirements.txt
```

- [ ] **Step 3: Verify imports**

```bash
python3 -c "from rdkit import Chem; from rdkit.Chem.inchi import MolToInchi, MolToInchiKey; m = Chem.MolFromSmiles('CCO'); print(MolToInchiKey(m))"
python3 -c "import chembl_downloader; print(chembl_downloader.__version__)"
python3 -c "import httpx; print(httpx.__version__)"
```

Expected: ethanol's InChIKey `LFQSCWFLJHTTHZ-UHFFFAOYSA-N`; non-empty version strings.

- [ ] **Step 4: Make `lightrag/` importable as a package**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
touch lightrag/__init__.py
touch lightrag/tests/__init__.py
mkdir -p lightrag/tests/fixtures
```

This is a deliberate change — existing scripts use flat imports (`from entity_schema import …`) which still work because Python adds the running script's directory to `sys.path`. The empty `__init__.py` adds package-style imports (`from lightrag.identity_bridge import …`) for tests run from the project root, without breaking the existing pattern.

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/requirements.txt \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/__init__.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/__init__.py
git commit -m "chore(lightrag): add rdkit + chembl-downloader deps and package markers"
```

---

## Task 1: Identity-bridge module skeleton (RDKit InChIKey)

**Files:**
- Create: `lightrag/identity_bridge.py`
- Create: `lightrag/tests/test_identity_bridge.py`

> NOTE: imports use flat-style `from identity_bridge import …` since the test file lives inside the `lightrag/` package and `lightrag/tests/` is itself a sub-package. This sidesteps any pytest rootdir confusion between `lightrag.identity_bridge` and the parent directory naming collision (project root is also called `shrine-diet-bioactivity`).

- [ ] **Step 1: Write the failing test**

Create `lightrag/tests/test_identity_bridge.py`:

```python
"""Tests for compound identity bridge."""
import sys
from pathlib import Path

# Make lightrag/ importable when pytest runs from project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from identity_bridge import compute_inchikey, ResolvedIdentity


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

- [ ] **Step 2: Run test — confirm it fails**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
pytest lightrag/tests/test_identity_bridge.py -v
```

Expected: `ImportError` for `identity_bridge`.

- [ ] **Step 3: Implement `compute_inchikey`**

Create `lightrag/identity_bridge.py`:

```python
"""Compound identity bridge — name→PubChem + UniChem cross-references.

Phase 1 architecture (post-harden):

  PRIMARY    : compound name → PubChem PUG-REST → InChIKey + (optional) SMILES
  SECONDARY  : InChIKey → UniChem source-mapping files → ChEMBL/KEGG/ChEBI/DrugBank IDs
  VERIFY     : RDKit recomputes InChIKey from SMILES (when PubChem returns one)

The original SMILES-first plan was inverted because the project's compounds
table contains 0 SMILES strings (no such column) and 0 populated PubChem CIDs.
RDKit is retained for InChIKey verification only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResolvedIdentity:
    """Result of identity resolution for a single compound."""
    inchikey: str
    inchi: str
    method: str   # 'rdkit_smiles' | 'pubchem_name' | 'pubchem_cid'


def compute_inchikey(smiles: Optional[str]) -> Optional[ResolvedIdentity]:
    """Compute Standard InChI + InChIKey from a SMILES string via RDKit.

    Returns None for empty/None input or RDKit-unparseable SMILES.
    """
    if not smiles:
        return None
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

- [ ] **Step 4: Run tests — confirm they pass**

```bash
pytest lightrag/tests/test_identity_bridge.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/identity_bridge.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_identity_bridge.py
git commit -m "feat(lightrag): add identity-bridge skeleton with RDKit InChIKey verifier"
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

- [ ] **Step 2: Append failing tests for UniChem loader**

Append to `lightrag/tests/test_identity_bridge.py`:

```python
from pathlib import Path
from identity_bridge import load_unichem_mapping, UNICHEM_SRC


FIXTURES = Path(__file__).parent / "fixtures"


def test_load_unichem_mapping_returns_xrefs_by_inchikey():
    mapping = load_unichem_mapping(FIXTURES / "unichem_subset.tsv")
    curcumin = mapping["VFLDPWHFBUODDF-FCXRPNKRSA-N"]
    assert curcumin["chembl_id"] == "CHEMBL116438"
    assert curcumin["pubchem_cid"] == 969516
    assert curcumin["chebi_id"] == 3962
    assert curcumin.get("drugbank_id") is None


def test_load_unichem_mapping_handles_multi_source():
    mapping = load_unichem_mapping(FIXTURES / "unichem_subset.tsv")
    ethanol = mapping["LFQSCWFLJHTTHZ-UHFFFAOYSA-N"]
    assert ethanol["chembl_id"] == "CHEMBL545"
    assert ethanol["pubchem_cid"] == 702
    assert ethanol["drugbank_id"] == "DB00898"
    assert ethanol["unichem_src_count"] == 3


def test_unichem_src_constants_match_ebi_codes():
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

_SRC_BY_ID: dict[int, str] = {v: k for k, v in UNICHEM_SRC.items()}
_INTEGER_SRCS = {"pubchem", "chebi"}


def load_unichem_mapping(tsv_path: Path) -> dict[str, dict[str, Any]]:
    """Load a UniChem source-mapping TSV into {inchikey: {chembl_id, ...}}.

    Expected columns: inchikey \\t src_id \\t src_compound_id

    Returns a dict keyed by InChIKey. Each value contains zero or more of:
    chembl_id, drugbank_id, kegg_compound_id, chebi_id, pubchem_cid,
    plus unichem_src_count.
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
            field = (
                "kegg_compound_id" if src_name == "kegg"
                else "pubchem_cid" if src_name == "pubchem"
                else f"{src_name}_id"
            )
            entry[field] = value
    for entry in out.values():
        entry["unichem_src_count"] = sum(
            1 for k in entry if k != "unichem_src_count"
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
git commit -m "feat(lightrag): UniChem cross-reference loader"
```

---

## Task 3: PubChem PUG-REST name resolver (with cache + InChIKey + SMILES)

**Files:**
- Modify: `lightrag/identity_bridge.py`
- Modify: `lightrag/tests/test_identity_bridge.py`

> Patched from original Task 3: now returns InChIKey **and** SMILES (when present) so RDKit can verify and the SMILES can be cached for future ingest cycles. This becomes the **primary** resolution method given the missing-SMILES-column finding.

- [ ] **Step 1: Append failing tests (mocked HTTP)**

Append to `lightrag/tests/test_identity_bridge.py`:

```python
import httpx
from unittest.mock import patch

from identity_bridge import resolve_compound_by_name, PubChemResult


def test_resolve_compound_by_name_returns_inchikey_and_smiles(tmp_path):
    cache = tmp_path / "pubchem_cache.json"
    # PubChem returns CSV-like with header when properties are requested
    body = "CID,InChIKey,CanonicalSMILES\n969516,VFLDPWHFBUODDF-FCXRPNKRSA-N,COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O\n"
    fake_response = httpx.Response(status_code=200, text=body)
    with patch("httpx.get", return_value=fake_response) as mock_get:
        result = resolve_compound_by_name("Curcumin", cache_path=cache)
    assert result is not None
    assert result.inchikey == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    assert result.cid == 969516
    assert "COc1cc" in result.smiles
    mock_get.assert_called_once()
    assert cache.exists()


def test_resolve_compound_by_name_uses_cache(tmp_path):
    cache = tmp_path / "pubchem_cache.json"
    cache.write_text(
        '{"Curcumin": {"cid": 969516, "inchikey": "VFLDPWHFBUODDF-FCXRPNKRSA-N", "smiles": "C..."}}'
    )
    with patch("httpx.get") as mock_get:
        result = resolve_compound_by_name("Curcumin", cache_path=cache)
    assert result is not None
    assert result.inchikey == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    mock_get.assert_not_called()


def test_resolve_compound_by_name_404_returns_none_and_caches_negative(tmp_path):
    cache = tmp_path / "c.json"
    fake_404 = httpx.Response(status_code=404, text="")
    with patch("httpx.get", return_value=fake_404):
        result = resolve_compound_by_name("Bogus-Compound", cache_path=cache)
    assert result is None
    # Negative result must be cached so we do not re-query.
    import json
    assert json.loads(cache.read_text())["Bogus-Compound"] is None
```

- [ ] **Step 2: Confirm failure**

```bash
pytest lightrag/tests/test_identity_bridge.py -v -k resolve_compound
```

- [ ] **Step 3: Implement**

Append to `lightrag/identity_bridge.py`:

```python
import json
import time
from urllib.parse import quote

PUBCHEM_PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_RATE_LIMIT_SLEEP_S = 0.25  # 4 req/s; PubChem soft limit is 5/s.


@dataclass(frozen=True)
class PubChemResult:
    cid: int
    inchikey: str
    smiles: Optional[str]


def resolve_compound_by_name(
    name: str,
    *,
    cache_path: Path,
    timeout_s: float = 10.0,
) -> Optional[PubChemResult]:
    """Resolve a compound name via PubChem PUG-REST.

    Cache file maps {name: {cid, inchikey, smiles} | null}. A cached null means
    "PubChem returned 404 for this name" — do not re-query.
    """
    import httpx

    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cache = {}

    if name in cache:
        cached = cache[name]
        if cached is None:
            return None
        return PubChemResult(
            cid=cached["cid"],
            inchikey=cached["inchikey"],
            smiles=cached.get("smiles"),
        )

    safe_name = quote(name, safe="")
    url = (
        f"{PUBCHEM_PUG_REST}/compound/name/{safe_name}"
        f"/property/InChIKey,CanonicalSMILES/CSV"
    )
    resp = httpx.get(url, timeout=timeout_s)
    time.sleep(PUBCHEM_RATE_LIMIT_SLEEP_S)

    parsed: Any
    if resp.status_code == 404:
        parsed = None
    elif resp.status_code == 200:
        text = resp.text.strip()
        # Skip header line; first data line is "<cid>,<inchikey>,<smiles>".
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            parsed = None
        else:
            cols = lines[1].split(",", 2)
            if len(cols) < 2:
                parsed = None
            else:
                cid_s, inchikey = cols[0].strip(), cols[1].strip()
                smiles = cols[2].strip() if len(cols) > 2 else None
                try:
                    parsed = {"cid": int(cid_s), "inchikey": inchikey, "smiles": smiles or None}
                except ValueError:
                    parsed = None
    else:
        # Unexpected status — surface as None, do NOT cache (allow retry on next run).
        return None

    cache[name] = parsed
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))
    if parsed is None:
        return None
    return PubChemResult(cid=parsed["cid"], inchikey=parsed["inchikey"], smiles=parsed.get("smiles"))
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
git commit -m "feat(lightrag): PubChem PUG-REST name resolver returning CID + InChIKey + SMILES"
```

---

## Task 4: SQLite schema for compound_identity + bioactivity_evidence

**Files:**
- Modify: `scripts/build-herbal-db.ts` (add DDL only)
- Create: `lightrag/tests/test_schema.py`

> Patched from original Task 4: `compound_id` is **TEXT** (matches existing `compounds.id` type). `pubchem_cid` is INTEGER (UniChem returns numeric CIDs).

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


def _table_columns(conn: sqlite3.Connection, name: str) -> dict[str, str]:
    return {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({name})")}


@pytest.mark.skipif(not DB_PATH.exists(), reason="DB not built yet")
def test_compound_identity_table_exists():
    with sqlite3.connect(DB_PATH) as conn:
        cols = _table_columns(conn, "compound_identity")
    assert "compound_id" in cols
    assert cols["compound_id"] == "TEXT"
    assert {"inchikey", "pubchem_cid", "chembl_id", "kegg_compound_id",
            "drugbank_id", "chebi_id", "unichem_src_count",
            "resolution_method", "resolved_at"}.issubset(cols.keys())


@pytest.mark.skipif(not DB_PATH.exists(), reason="DB not built yet")
def test_bioactivity_evidence_table_exists():
    with sqlite3.connect(DB_PATH) as conn:
        cols = _table_columns(conn, "bioactivity_evidence")
    assert "compound_id" in cols
    assert cols["compound_id"] == "TEXT"
    assert {"chembl_compound_id", "chembl_target_id",
            "target_pref_name", "target_organism", "activity_type",
            "relation", "value", "units", "pchembl",
            "assay_confidence", "chembl_doc_id", "publication_year"}.issubset(cols.keys())
```

- [ ] **Step 3: Add DDL to build-herbal-db.ts**

Find the section that creates other tables (search for `CREATE TABLE compounds`). After the last `CREATE TABLE` statement and before any `INSERT`, add:

```typescript
db.exec(`
  CREATE TABLE IF NOT EXISTS compound_identity (
    compound_id          TEXT PRIMARY KEY,
    inchikey             TEXT,
    inchi                TEXT,
    smiles               TEXT,
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
    compound_id          TEXT NOT NULL,
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

- [ ] **Step 4: Apply DDL via direct sqlite3 (preserves the 5.5GB DB without rebuild)**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
sqlite3 data_local/herbal_botanicals.db <<'SQL'
CREATE TABLE IF NOT EXISTS compound_identity (
  compound_id          TEXT PRIMARY KEY,
  inchikey             TEXT,
  inchi                TEXT,
  smiles               TEXT,
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
  compound_id          TEXT NOT NULL,
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
SQL
```

- [ ] **Step 5: Run schema tests — confirm pass**

```bash
pytest lightrag/tests/test_schema.py -v
```

Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build-herbal-db.ts \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_schema.py
git commit -m "feat(db): add compound_identity and bioactivity_evidence tables (TEXT compound_id)"
```

---

## Task 5: build_compound_identity.py CLI (REWRITTEN — name→PubChem primary)

**Files:**
- Create: `scripts/build_compound_identity.py`
- Modify: `Makefile`

> **Major rewrite from original Task 5.** Plan now uses `compounds.name` → PubChem PUG-REST as the primary resolution path, since the schema probe revealed no SMILES column and 0 populated CIDs. RDKit becomes a verification step on PubChem-returned SMILES. Active-subset filter (`herb_compounds` ∪ `compound_targets`) caps the build to ~25K names instead of 94K.

- [ ] **Step 1: Write the script**

Create `shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build_compound_identity.py`:

```python
"""Populate compound_identity for active compounds in herbal_botanicals.db.

Phase 1 pipeline (post-harden):
  1. Pick active subset: compounds in herb_compounds ∪ compound_targets
     (avoid wasting API calls on unused compounds)
  2. PubChem PUG-REST: name → CID + InChIKey + SMILES (cached on disk)
  3. RDKit verify: recompute InChIKey from returned SMILES; flag mismatches
  4. UniChem cross-refs: InChIKey → ChEMBL/KEGG/ChEBI/DrugBank IDs

Usage:
  # Smoke (fixture UniChem, no PubChem network call → all rows unresolved):
  python scripts/build_compound_identity.py \\
      --db data_local/herbal_botanicals.db \\
      --unichem-tsv lightrag/tests/fixtures/unichem_subset.tsv \\
      --pubchem-cache /tmp/pc_smoke.json \\
      --no-pubchem --limit 50

  # Real run on active subset (~25K compounds; expect ~1.5h with cache cold):
  python scripts/build_compound_identity.py \\
      --db data_local/herbal_botanicals.db \\
      --unichem-tsv data/unichem_src1_22_2_6_7.tsv \\
      --pubchem-cache data_local/pubchem_name_cache.json
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from identity_bridge import (
    compute_inchikey,
    load_unichem_mapping,
    resolve_compound_by_name,
)

# Active subset query — compounds appearing in any structural relationship.
# Skips orphan compounds (no herb, no food, no target) to keep Phase 1 bounded.
ACTIVE_SUBSET_SQL = """
SELECT DISTINCT c.id, c.name
FROM compounds c
WHERE c.id IN (SELECT compound_id FROM herb_compounds)
   OR c.id IN (SELECT compound_id FROM compound_targets)
ORDER BY c.id
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--unichem-tsv", type=Path, required=True)
    ap.add_argument("--pubchem-cache", type=Path, required=True)
    ap.add_argument("--no-pubchem", action="store_true",
                    help="skip online PubChem fallback (smoke mode)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--include-orphans", action="store_true",
                    help="resolve all compounds, not just the active subset")
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

    if args.include_orphans:
        query = "SELECT id, name FROM compounds"
    else:
        query = ACTIVE_SUBSET_SQL
    if args.limit:
        query += f" LIMIT {args.limit}"

    rows = list(cur.execute(query))
    total = len(rows)
    print(f"Resolving {total} compound names ...")

    resolved_pubchem = 0
    resolved_rdkit_verified = 0
    matched_unichem = 0
    rdkit_mismatches = 0
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    upsert_sql = """
        INSERT OR REPLACE INTO compound_identity
          (compound_id, inchikey, inchi, smiles, pubchem_cid, chembl_id,
           kegg_compound_id, drugbank_id, chebi_id,
           unichem_src_count, resolution_method, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    started = time.time()
    for idx, row in enumerate(rows):
        compound_id = row["id"]
        name = row["name"]
        inchikey = inchi = smiles = None
        cid = None
        method = None

        if name and not args.no_pubchem:
            pubchem = resolve_compound_by_name(
                name, cache_path=args.pubchem_cache
            )
            if pubchem:
                inchikey = pubchem.inchikey
                cid = pubchem.cid
                smiles = pubchem.smiles
                method = "pubchem_name"
                resolved_pubchem += 1
                # RDKit verification: recompute InChIKey from returned SMILES.
                if smiles:
                    rdkit_id = compute_inchikey(smiles)
                    if rdkit_id and rdkit_id.inchikey == inchikey:
                        resolved_rdkit_verified += 1
                        inchi = rdkit_id.inchi
                    elif rdkit_id and rdkit_id.inchikey != inchikey:
                        rdkit_mismatches += 1

        xrefs = unichem.get(inchikey, {}) if inchikey else {}
        if xrefs:
            matched_unichem += 1
            cid = cid or xrefs.get("pubchem_cid")

        if not (inchikey or xrefs):
            continue

        cur.execute(upsert_sql, (
            compound_id, inchikey, inchi, smiles,
            cid,
            xrefs.get("chembl_id"),
            xrefs.get("kegg_compound_id"),
            xrefs.get("drugbank_id"),
            xrefs.get("chebi_id"),
            xrefs.get("unichem_src_count", 0),
            method or "unknown",
            now_iso,
        ))

        if (idx + 1) % 500 == 0:
            conn.commit()
            elapsed = time.time() - started
            rate = (idx + 1) / elapsed if elapsed else 0
            eta_s = (total - idx - 1) / rate if rate else 0
            print(f"  [{idx + 1}/{total}] resolved_pubchem={resolved_pubchem} "
                  f"matched_unichem={matched_unichem} "
                  f"rate={rate:.1f}/s eta={eta_s/60:.1f}min")

    conn.commit()
    conn.close()

    coverage = matched_unichem / total if total else 0.0
    print(f"\nResolved via PubChem: {resolved_pubchem} "
          f"(RDKit-verified: {resolved_rdkit_verified}, mismatches: {rdkit_mismatches})")
    print(f"UniChem cross-refs matched: {matched_unichem}/{total} ({coverage:.1%})")
    if coverage < 0.50:
        print("WARNING: cross-ref coverage below 50% — see runbook stub "
              "harden-plan/scope/full-94k-name-resolution-deferred.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add Makefile targets**

Append to `shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile`:

```makefile
# ─── Compound identity bridge ───────────────────────────────
.PHONY: build-identity build-identity-smoke build-identity-full

UNICHEM_TSV ?= data/unichem_src1_22_2_6_7.tsv
PUBCHEM_CACHE ?= data_local/pubchem_name_cache.json

# Active subset (~25K compounds in herb_compounds ∪ compound_targets)
build-identity:
	python scripts/build_compound_identity.py \
		--db data_local/herbal_botanicals.db \
		--unichem-tsv $(UNICHEM_TSV) \
		--pubchem-cache $(PUBCHEM_CACHE)

# Full backfill (all 94K compounds, ~6.5h cold-cache) — Phase 2 use only.
build-identity-full:
	python scripts/build_compound_identity.py \
		--db data_local/herbal_botanicals.db \
		--unichem-tsv $(UNICHEM_TSV) \
		--pubchem-cache $(PUBCHEM_CACHE) \
		--include-orphans

# Smoke (no network; fixture UniChem; tiny limit)
build-identity-smoke:
	python scripts/build_compound_identity.py \
		--db data_local/herbal_botanicals.db \
		--unichem-tsv lightrag/tests/fixtures/unichem_subset.tsv \
		--pubchem-cache /tmp/pubchem_cache_smoke.json \
		--no-pubchem --limit 50
```

- [ ] **Step 3: Smoke-run**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
make build-identity-smoke
```

Expected output: "Resolving 50 compound names ...", "Resolved via PubChem: 0", "UniChem cross-refs matched: 0/50 (0.0%)" (zero is OK — `--no-pubchem` means no resolutions attempted; the smoke just verifies the SQL queries and CLI plumbing). The WARNING line about coverage is expected.

- [ ] **Step 4: Verify the active subset filter works**

```bash
sqlite3 data_local/herbal_botanicals.db <<'SQL'
SELECT COUNT(*) AS active_compounds FROM (
  SELECT DISTINCT c.id FROM compounds c
  WHERE c.id IN (SELECT compound_id FROM herb_compounds)
     OR c.id IN (SELECT compound_id FROM compound_targets)
);
SQL
```

Expected: a number around 25,000 (matches probe finding).

- [ ] **Step 5: Optional — small online smoke against real PubChem (10 compounds only)**

Only run if network is available; verifies the PubChem path with real responses:

```bash
sqlite3 data_local/herbal_botanicals.db -cmd ".timeout 5000" \
  "SELECT id, name FROM compounds WHERE name LIKE 'CURCUMIN' OR name LIKE 'QUERCETIN' OR name LIKE 'CAFFEINE' LIMIT 5;"
# If those compounds exist, run a 10-row real PubChem resolution:
python scripts/build_compound_identity.py \
  --db data_local/herbal_botanicals.db \
  --unichem-tsv lightrag/tests/fixtures/unichem_subset.tsv \
  --pubchem-cache /tmp/pubchem_real_smoke.json \
  --limit 10
```

Expected: "Resolved via PubChem: N>=1" if any of the 10 active-subset compounds match a PubChem name. If 0 — possibly the compounds-table names are too unusual (e.g. "(+)-1-HYDROXYPINORESINOL-4.4'-GLUCOPYRANOSIDE"); that's a real signal that name normalization may be needed in a follow-up.

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build_compound_identity.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile
git commit -m "feat(scripts): build_compound_identity (name→PubChem→UniChem, active-subset)"
```

---

## Task 6: ChEMBL extractor module

**Files:**
- Create: `lightrag/chembl_extractor.py`
- Create: `lightrag/tests/test_chembl_extractor.py`
- Create: `lightrag/tests/fixtures/_make_chembl_subset.py` and `chembl_subset.sqlite`

> Imports: tests use flat-style `from chembl_extractor import …`.

- [ ] **Step 1: Build the test fixture**

Create `lightrag/tests/fixtures/_make_chembl_subset.py`:

```python
"""Generate a tiny ChEMBL-shaped SQLite fixture (~50 KB)."""
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

INSERT INTO compound_structures VALUES (1, 'VFLDPWHFBUODDF-FCXRPNKRSA-N');
INSERT INTO molecule_dictionary VALUES (1, 'CHEMBL116438');
INSERT INTO target_dictionary VALUES (100, 'CHEMBL1741221', 'Nuclear factor NF-kappa-B p65', 'SINGLE PROTEIN', 'Homo sapiens');
INSERT INTO assays VALUES (1000, 100, 8);
INSERT INTO docs VALUES (5000, 'CHEMBL1129589', 2018);
INSERT INTO activities VALUES (10000, 1, 1000, 5000, 'IC50', '=', 5000.0, 'nM', 5.30, NULL);

INSERT INTO compound_structures VALUES (2, 'RYYVLZVUVIJVGH-UHFFFAOYSA-N');
INSERT INTO molecule_dictionary VALUES (2, 'CHEMBL113');
INSERT INTO target_dictionary VALUES (200, 'CHEMBL251', 'Adenosine A2a receptor', 'SINGLE PROTEIN', 'Homo sapiens');
INSERT INTO assays VALUES (2000, 200, 9);
INSERT INTO docs VALUES (5001, 'CHEMBL1100001', 2019);
INSERT INTO activities VALUES (10001, 2, 2000, 5001, 'Ki', '=', 2400.0, 'nM', 5.62, NULL);

INSERT INTO assays VALUES (3000, 200, 3);
INSERT INTO activities VALUES (10002, 2, 3000, 5001, 'IC50', '=', 1e9, 'nM', 0.0, 'noisy');
""")
conn.commit()
conn.close()
print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
```

Run once to generate the fixture:

```bash
python shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/fixtures/_make_chembl_subset.py
```

- [ ] **Step 2: Write failing tests**

Create `lightrag/tests/test_chembl_extractor.py`:

```python
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from chembl_extractor import extract_bioactivities_for_inchikeys

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
    assert len(rows) == 1
    assert rows[0]["assay_confidence"] == 9


def test_extract_batches_inchikeys():
    keys = [f"FAKE{i:040d}-X" for i in range(2500)]
    keys[0] = "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    rows = extract_bioactivities_for_inchikeys(_fixture_conn(), inchikeys=keys)
    assert any(r["chembl_compound_id"] == "CHEMBL116438" for r in rows)


def test_extract_empty_inchikey_list_returns_empty():
    rows = extract_bioactivities_for_inchikeys(_fixture_conn(), inchikeys=[])
    assert rows == []
```

- [ ] **Step 3: Run — confirm failure**

```bash
pytest lightrag/tests/test_chembl_extractor.py -v
```

- [ ] **Step 4: Implement**

Create `lightrag/chembl_extractor.py`:

```python
"""ChEMBL bioactivity extraction — compound-anchored intersect.

For a given list of InChIKeys (the project's resolved compound universe),
return all measured bioactivities meeting the min_pchembl and
min_confidence thresholds.
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

    Batches the IN-list to stay under SQLite parameter limits.
    """
    keys = [k for k in inchikeys if k]
    if not keys:
        return []
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

Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/chembl_extractor.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_chembl_extractor.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/fixtures/chembl_subset.sqlite \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/fixtures/_make_chembl_subset.py
git commit -m "feat(lightrag): ChEMBL bioactivity extractor"
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
  # Smoke (use fixture)
  python scripts/build_bioactivity_evidence.py \\
      --db data_local/herbal_botanicals.db \\
      --chembl-sqlite lightrag/tests/fixtures/chembl_subset.sqlite \\
      --min-pchembl 5.0 --min-confidence 5

  # Production (chembl-downloader fetches ChEMBL 36 SQLite ~12GB)
  python scripts/build_bioactivity_evidence.py \\
      --db data_local/herbal_botanicals.db \\
      --chembl-version 36
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lightrag"))

from chembl_extractor import extract_bioactivities_for_inchikeys


def _open_chembl(args: argparse.Namespace) -> sqlite3.Connection:
    if args.chembl_sqlite:
        return sqlite3.connect(args.chembl_sqlite)
    import chembl_downloader  # type: ignore[import-not-found]
    sqlite_path = chembl_downloader.download_extract_sqlite(version=str(args.chembl_version))
    print(f"Using ChEMBL {args.chembl_version} at {sqlite_path}")
    return sqlite3.connect(sqlite_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--chembl-sqlite", type=Path)
    src.add_argument("--chembl-version", type=int)
    ap.add_argument("--min-pchembl", type=float, default=5.0)
    ap.add_argument("--min-confidence", type=int, default=5)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: DB not found: {args.db}", file=sys.stderr)
        return 2

    target_conn = sqlite3.connect(args.db)
    target_conn.row_factory = sqlite3.Row
    cur = target_conn.cursor()

    rows = list(cur.execute(
        "SELECT inchikey, compound_id FROM compound_identity "
        "WHERE inchikey IS NOT NULL"
    ))
    if not rows:
        print("ERROR: compound_identity has no InChIKey rows yet. Run build-identity first.",
              file=sys.stderr)
        return 3
    inchikey_to_compound: dict[str, str] = {r["inchikey"]: r["compound_id"] for r in rows}
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

- [ ] **Step 3: Smoke seed compound_identity then run**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
sqlite3 data_local/herbal_botanicals.db <<SQL
INSERT OR REPLACE INTO compound_identity
  (compound_id, inchikey, resolution_method, resolved_at)
VALUES
  ('curcumin', 'VFLDPWHFBUODDF-FCXRPNKRSA-N', 'manual_smoke', datetime('now')),
  ('caffeine', 'RYYVLZVUVIJVGH-UHFFFAOYSA-N', 'manual_smoke', datetime('now'));
SQL
make build-bioactivity-smoke
sqlite3 data_local/herbal_botanicals.db "SELECT compound_id, chembl_compound_id, target_pref_name, pchembl FROM bioactivity_evidence;"
```

Expected:

```
curcumin|CHEMBL116438|Nuclear factor NF-kappa-B p65|5.3
caffeine|CHEMBL113|Adenosine A2a receptor|5.62
```

- [ ] **Step 4: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/scripts/build_bioactivity_evidence.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile
git commit -m "feat(scripts): build_bioactivity_evidence with chembl-downloader integration"
```

---

## Task 8: Extend LightRAG entity_schema with BioactivityEvidence

**Files:**
- Modify: `lightrag/entity_schema.py`
- Create: `lightrag/tests/test_entity_schema.py`

- [ ] **Step 1: Read existing schema dictionaries**

```bash
grep -n "ENTITY_TYPES\|RELATIONSHIP_TYPES\|DESCRIPTION_GENERATORS" \
  shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/entity_schema.py | head -20
```

- [ ] **Step 2: Write failing tests**

Create `lightrag/tests/test_entity_schema.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_schema import (
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
        "compound_id": "curcumin",
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
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "Homo sapiens" in desc
    assert "CHEMBL1129589" in desc


def test_describe_bioactivity_evidence_handles_missing_fields():
    """Should not crash when target_pref_name / organism are None."""
    gen = DESCRIPTION_GENERATORS["BioactivityEvidence"]
    desc = gen({
        "id": 2,
        "chembl_compound_id": "CHEMBL?",
        "chembl_target_id": "CHEMBL?",
        "activity_type": "Ki",
        "value": None, "units": "", "relation": None,
        "target_pref_name": None, "target_organism": None,
        "assay_confidence": None, "publication_year": None,
        "chembl_doc_id": None, "pchembl": None,
    })
    assert "BioactivityEvidence" in desc


def test_has_evidence_relationship_described():
    desc, kw = describe_relationship("HAS_EVIDENCE", {
        "src_name": "Curcumin",
        "tgt_name": "BioactivityEvidence#1",
        "pchembl": 5.3,
        "activity_type": "IC50",
    })
    assert "Curcumin" in desc


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

- [ ] **Step 4: Add entity definition to ENTITY_TYPES**

In `lightrag/entity_schema.py`, find the `ENTITY_TYPES` dict and add this entry alongside the existing ones (after `Symptom`, before tenant entity types):

```python
"BioactivityEvidence": {
    "source_table": "bioactivity_evidence",
    "id_field": "id",
    "name_field": "id",
    "query": (
        "SELECT id, compound_id, chembl_compound_id, chembl_target_id, "
        "target_pref_name, target_type, target_organism, activity_type, "
        "relation, value, units, pchembl, assay_confidence, chembl_doc_id, "
        "publication_year FROM bioactivity_evidence ORDER BY id"
    ),
},
```

- [ ] **Step 5: Add description generator**

Add this function near the other entity describers (e.g., after `describe_symptom`):

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
        parts.append(f" ({organism})")
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
"BioactivityEvidence": describe_bioactivity_evidence,
```

- [ ] **Step 6: Add relationship branches to describe_relationship**

Add these branches before the final fallback `return`:

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

Add entries mirroring the shape used by `TARGETS_PROTEIN`. Read first, mirror the keys exactly:

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

- [ ] **Step 8: Run tests — confirm pass**

```bash
pytest lightrag/tests/test_entity_schema.py -v
```

Expected: 5 PASS

- [ ] **Step 9: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/entity_schema.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_entity_schema.py
git commit -m "feat(lightrag): register BioactivityEvidence + HAS_EVIDENCE/EVIDENCE_FOR_TARGET"
```

---

## Task 9: Wire bioactivity into ingest_unified.py

**Files:**
- Modify: `lightrag/ingest_unified.py`
- Create: `lightrag/tests/test_ingest_bioactivity.py`

- [ ] **Step 1: Skim ingest_unified.py to learn the integration pattern**

```bash
grep -n "ENTITY_TYPES\|RELATIONSHIP_TYPES\|extract_entities\|extract_relationships\|table_exists" \
  shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/ingest_unified.py | head -30
```

- [ ] **Step 2: Write failing integration test**

Create `lightrag/tests/test_ingest_bioactivity.py`:

```python
"""End-to-end check that bioactivity_evidence flows through extract_entities."""
import sys
import sqlite3
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_schema import ENTITY_TYPES, DESCRIPTION_GENERATORS


@pytest.fixture
def populated_db(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE compounds (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE bioactivity_evidence (
          id INTEGER PRIMARY KEY,
          compound_id TEXT,
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
        INSERT INTO compounds VALUES ('curcumin', 'Curcumin');
        INSERT INTO bioactivity_evidence VALUES (
          1, 'curcumin', 'CHEMBL116438', 'CHEMBL1741221',
          'Nuclear factor NF-kappa-B p65', 'SINGLE PROTEIN', 'Homo sapiens',
          'IC50', '=', 5000.0, 'nM', 5.3, 8, 'CHEMBL1129589', 2018
        );
    """)
    conn.commit()
    return conn


def test_bioactivity_query_runs_against_real_schema(populated_db):
    """The ENTITY_TYPES['BioactivityEvidence'] query must execute cleanly."""
    et = ENTITY_TYPES["BioactivityEvidence"]
    rows = list(populated_db.execute(et["query"]))
    assert len(rows) == 1


def test_description_generator_renders_real_row(populated_db):
    cur = populated_db.execute(ENTITY_TYPES["BioactivityEvidence"]["query"])
    cols = [d[0] for d in cur.description]
    row = dict(zip(cols, cur.fetchone()))
    desc = DESCRIPTION_GENERATORS["BioactivityEvidence"](row)
    assert "Nuclear factor NF-kappa-B p65" in desc
    assert "IC50" in desc
```

- [ ] **Step 3: Run test — should pass already (since Task 8 shipped the entity)**

```bash
pytest lightrag/tests/test_ingest_bioactivity.py -v
```

If anything fails, the failure tells you whether Task 8 wired the schema correctly.

- [ ] **Step 4: Add a graceful skip in ingest_unified.py for missing tables**

In `extract_entities`, ensure the `BioactivityEvidence` extraction path is wrapped in a `table_exists(conn, "bioactivity_evidence")` check (the helper exists at the head of the file). If missing, log "skipping BioactivityEvidence — table not present" and continue.

Concretely, find the loop that walks `ENTITY_TYPES` and add the guard. If the existing pattern already does this for tenant tables, mirror that pattern verbatim.

- [ ] **Step 5: Add `--only-entities` / `--only-relationships` flags**

In `argparse` setup of `ingest_unified.py`, add:

```python
ap.add_argument("--only-entities", default=None,
                help="comma-separated entity type names to include")
ap.add_argument("--only-relationships", default=None,
                help="comma-separated relationship type names to include")
```

In the loop over `ENTITY_TYPES`, filter:

```python
allowed = set(args.only_entities.split(",")) if args.only_entities else None
for entity_type in ENTITY_TYPES:
    if allowed and entity_type not in allowed:
        continue
    ...
```

Same pattern for relationships.

- [ ] **Step 6: Add Makefile target**

Append to `Makefile`:

```makefile
.PHONY: lightrag-ingest-bioactivity

lightrag-ingest-bioactivity:
	python lightrag/ingest_unified.py --config local \
		--only-entities BioactivityEvidence \
		--only-relationships HAS_EVIDENCE,EVIDENCE_FOR_TARGET \
		--batch-size 1000
```

- [ ] **Step 7: Commit**

```bash
git add shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/ingest_unified.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/lightrag/tests/test_ingest_bioactivity.py \
        shrine-diet-bioactivity/shrine-diet-bioactivity/Makefile
git commit -m "feat(lightrag): scoped ingest flags + bioactivity guard in extract_entities"
```

---

## Task 10: MCP label-vocabulary docstring + test

**Files:**
- Modify: `src/tools.ts`
- Modify: `src/__tests__/tool_catalog.test.ts`

- [ ] **Step 1: Update the file docstring in src/tools.ts**

Locate the file header comment in `src/tools.ts` and add (or augment) a vocabulary block:

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

- [ ] **Step 2: Extend tool_catalog test**

Open `src/__tests__/tool_catalog.test.ts`. Add:

```typescript
import fs from 'node:fs';
import path from 'node:path';

it('tools.ts header lists BioactivityEvidence vocabulary', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'tools.ts'),
    'utf8',
  );
  expect(src).toContain('BioactivityEvidence');
  expect(src).toContain('HAS_EVIDENCE');
  expect(src).toContain('EVIDENCE_FOR_TARGET');
});
```

- [ ] **Step 3: Run TS tests**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
npm test -- tool_catalog
```

Expected: PASS

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

- [ ] **Step 1: DATASET_PROVENANCE.md additions** — see plan.original.md for full text; identical here.

(Append the same three blocks: ChEMBL 36, UniChem source-mapping, PubChem PUG-REST.)

- [ ] **Step 2: Update unified-diet-kg-architecture.md** — add `BioactivityEvidence` to the entity-types section; add `HAS_EVIDENCE`/`EVIDENCE_FOR_TARGET` to relationships. Add a note that compound identity is name-based via PubChem (Phase 1) with a TODO for Phase 2 SMILES enrichment.

- [ ] **Step 3: Create ADR `docs/adr/0007-compound-identity-bridge.md`**

```markdown
# ADR 0007: Compound identity bridge + ChEMBL evidence layer

**Date:** 2026-05-06
**Status:** Accepted

## Context

The KG holds ~94K compounds across multiple sources (Duke, FooDB, CMAUP, CTD, TTD)
with no shared identifier and (post-probe) no SMILES column at all in the local DB.
Without a normalized identity layer, we cannot join measured drug-target evidence
(ChEMBL) into the same graph that holds dietary occurrence (FooDB).

## Decision

Build a `compound_identity` SQLite table populated by:
1. PubChem PUG-REST `/compound/name/{name}/property/InChIKey,CanonicalSMILES`
   (primary path; cached on disk)
2. RDKit `MolToInchiKey` to verify InChIKeys when PubChem returns SMILES
3. UniChem source-mapping files for ChEMBL/KEGG/ChEBI/DrugBank cross-refs

Then load ChEMBL bioactivities as a new `BioactivityEvidence` entity in LightRAG,
joined to existing `Compound` and `Target` nodes.

**Phase 1 scope:** ~25K active compounds (in `herb_compounds` ∪ `compound_targets`).
Full 94K backfill is Phase 2.

## Alternatives considered

- **Full ChEMBL mirror.** Rejected — multi-GB, drug-heavy.
- **Online-only PubChem resolver for everything.** Adopted by necessity (no SMILES).
  Mitigated by aggressive caching and active-subset scoping.
- **New MCP tool surface for evidence queries.** Rejected — violates the project's
  thin-adapter MCP architecture (`FORBIDDEN_USECASE_VERBS` in `src/tools.ts`).

## Consequences

- ChEMBL release pin is part of reproducibility (recorded in `DATASET_PROVENANCE.md`).
- PubChem-cache becomes a regenerable but slow-to-rebuild artifact (~1.5h cold
  for 25K names).
- New entity is queryable through existing `semantic-search`, `get-entity`,
  `get-subgraph` primitives — no MCP tool surface change.
- Coverage <50% on cross-refs surfaces in build script output and runbook —
  does not block ingest.
```

- [ ] **Step 4: Create `data/UNICHEM_LICENSE.md`** — copy from plan.original.md.

- [ ] **Step 5: One-line README update** — add to data-sources section: `- ChEMBL 36 + UniChem (compound-identity bridge → bioactivity evidence) — see ADR 0007`.

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

- [ ] **Step 1: Run all new tests with coverage**

```bash
cd shrine-diet-bioactivity/shrine-diet-bioactivity
pytest lightrag/tests/test_identity_bridge.py \
       lightrag/tests/test_chembl_extractor.py \
       lightrag/tests/test_schema.py \
       lightrag/tests/test_entity_schema.py \
       lightrag/tests/test_ingest_bioactivity.py \
       --cov=identity_bridge --cov=chembl_extractor \
       --cov-report=term-missing -v
```

Expected: all PASS, coverage ≥80% on the two new modules.

- [ ] **Step 2: Run TS regression**

```bash
npm test -- tool_catalog
```

Expected: PASS

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

Expected: bioactivity_evidence > 0 (the seed-and-run pattern from Task 7); compound_identity may be 0 in `--no-pubchem` smoke mode — expected.

- [ ] **Step 4: Commit any incidental fixes**

```bash
git status
# if anything: git add ... && git commit -m "test: smoke fixes from end-to-end validation"
```

---

## Self-review notes

- Spec coverage: §4.1 → Tasks 1-3, 5; §4.2 → 6, 7; §4.3 → 8, 9; §4.4 → 10; §4.5 → 12; §6 → 11; §9 → 12.
- Type consistency: `compound_id` is **TEXT** everywhere post-harden (DDL, scripts, tests).
- Imports: flat-style `from identity_bridge import …`, `from chembl_extractor import …` — consistent across all test files.
- Scope: ≤25K compounds in Phase 1; full backfill explicitly stubbed for Phase 2.

## Hardened-plan log

- 2026-05-06T01:32:00Z — added Task 0 (deps + package markers).
- 2026-05-06T01:32:00Z — Task 5 rewritten: name→PubChem primary; active-subset scope.
- 2026-05-06T01:32:00Z — DDL `compound_id` changed INTEGER→TEXT in Tasks 4, 7, 9.
- 2026-05-06T01:32:00Z — all test imports flattened (no `lightrag.` prefix).
- 2026-05-06T01:32:00Z — runbook stubs filed: 5 entries (see runbook.md).
