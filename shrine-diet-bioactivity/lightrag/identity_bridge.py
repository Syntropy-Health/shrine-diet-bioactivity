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

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote


@dataclass(frozen=True)
class ResolvedIdentity:
    """Result of identity resolution from SMILES via RDKit."""

    inchikey: str
    inchi: str
    method: str  # 'rdkit_smiles' | 'pubchem_name' | 'pubchem_cid'


@dataclass(frozen=True)
class PubChemResult:
    """Result of identity resolution by name via PubChem PUG-REST."""

    cid: int
    inchikey: str
    smiles: Optional[str]


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


# ---------------------------------------------------------------------------
# UniChem cross-reference loader
# ---------------------------------------------------------------------------

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


def _xref_field(src_name: str) -> str:
    if src_name == "kegg":
        return "kegg_compound_id"
    if src_name == "pubchem":
        return "pubchem_cid"
    return f"{src_name}_id"


def load_unichem_mapping(tsv_path: Path) -> dict[str, dict[str, Any]]:
    """Load a UniChem source-mapping TSV into ``{inchikey: {chembl_id, ...}}``.

    Expected columns: ``inchikey \\t src_id \\t src_compound_id``.

    Returns a dict keyed by InChIKey. Each value contains zero or more of:
    ``chembl_id, drugbank_id, kegg_compound_id, chebi_id, pubchem_cid`` plus
    ``unichem_src_count`` (number of distinct sources matched for that key).
    """
    out: dict[str, dict[str, Any]] = {}
    with open(tsv_path, encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            ikey = (row.get("inchikey") or "").strip()
            if not ikey:
                continue
            try:
                src_id = int(row["src_id"])
            except (TypeError, ValueError, KeyError):
                continue
            src_name = _SRC_BY_ID.get(src_id)
            if src_name is None:
                continue
            entry = out.setdefault(ikey, {})
            value: Any = (row.get("src_compound_id") or "").strip()
            if not value:
                continue
            if src_name in _INTEGER_SRCS:
                try:
                    value = int(value)
                except ValueError:
                    continue
            entry[_xref_field(src_name)] = value

    for entry in out.values():
        # unichem_src_count = number of source-id-derived columns set for this row.
        entry["unichem_src_count"] = sum(1 for k in entry if k != "unichem_src_count")
    return out


# ---------------------------------------------------------------------------
# PubChem PUG-REST name resolver (with on-disk cache)
# ---------------------------------------------------------------------------

PUBCHEM_PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_RATE_LIMIT_SLEEP_S = 0.25  # ~4 req/s, under PubChem's 5/s soft cap.


def resolve_compound_by_name(
    name: str,
    *,
    cache_path: Path,
    timeout_s: float = 10.0,
) -> Optional[PubChemResult]:
    """Resolve a compound name to (CID, InChIKey, SMILES) via PubChem PUG-REST.

    Caches results on disk at ``cache_path`` as JSON. A cached ``null`` value
    means "PubChem returned 404 for this name" — do not re-query.
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
    # Wrap network call in try/finally so the rate-limit sleep always fires
    # (we want to spread requests evenly even when one fails) and so a
    # transient RequestError doesn't abort a 25K-compound batch. Transient
    # errors return None and are NOT cached — the next run can retry.
    try:
        resp = httpx.get(url, timeout=timeout_s)
    except httpx.RequestError:
        return None
    finally:
        time.sleep(PUBCHEM_RATE_LIMIT_SLEEP_S)

    parsed: Any
    if resp.status_code == 404:
        parsed = None
    elif resp.status_code == 200:
        parsed = _parse_pubchem_csv(resp.text)
    else:
        # Unexpected status — surface as None, do NOT cache (allow retry).
        return None

    cache[name] = parsed
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))
    if parsed is None:
        return None
    return PubChemResult(
        cid=parsed["cid"],
        inchikey=parsed["inchikey"],
        smiles=parsed.get("smiles"),
    )


def _parse_pubchem_csv(text: str) -> Optional[dict[str, Any]]:
    """Parse PubChem PUG-REST CSV body into the cache row.

    PubChem returns a header line ``CID,InChIKey,CanonicalSMILES`` followed by
    one or more data rows. We index columns by header NAME (not position) so
    the parser is robust if PubChem ever reorders columns or adds new ones.
    Uses csv.reader so embedded commas inside quoted SMILES strings (e.g.
    ``[Na+].[Cl-]``) are handled correctly.
    """
    import csv as _csv
    import io as _io

    reader = _csv.reader(_io.StringIO(text))
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    header = [h.strip() for h in rows[0]]
    try:
        cid_idx = header.index("CID")
        inchikey_idx = header.index("InChIKey")
    except ValueError:
        # Header doesn't contain the columns we asked for — fail closed.
        return None
    smiles_idx: Optional[int]
    try:
        smiles_idx = header.index("CanonicalSMILES")
    except ValueError:
        smiles_idx = None

    data = rows[1]
    if max(cid_idx, inchikey_idx, smiles_idx or 0) >= len(data):
        return None
    cid_raw = data[cid_idx].strip()
    inchikey = data[inchikey_idx].strip()
    smiles = data[smiles_idx].strip() if smiles_idx is not None else None
    try:
        cid = int(cid_raw)
    except ValueError:
        return None
    if not inchikey:
        return None
    return {"cid": cid, "inchikey": inchikey, "smiles": smiles or None}
