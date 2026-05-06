"""Tests for compound identity bridge."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

# Make lightrag/ importable when pytest runs from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx  # noqa: E402

from identity_bridge import (  # noqa: E402
    PubChemResult,
    ResolvedIdentity,
    UNICHEM_SRC,
    compute_inchikey,
    load_unichem_mapping,
    resolve_compound_by_name,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Task 1 — compute_inchikey
# ---------------------------------------------------------------------------


def test_compute_inchikey_curcumin():
    """Curcumin SMILES → known InChIKey."""
    smiles = "COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O"
    result = compute_inchikey(smiles)
    assert result is not None
    assert isinstance(result, ResolvedIdentity)
    assert result.inchikey == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    assert result.inchi.startswith("InChI=1S/")
    assert result.method == "rdkit_smiles"


def test_compute_inchikey_invalid_smiles_returns_none():
    assert compute_inchikey("not-a-valid-smiles") is None


def test_compute_inchikey_empty_returns_none():
    assert compute_inchikey("") is None
    assert compute_inchikey(None) is None


# ---------------------------------------------------------------------------
# Task 2 — UniChem cross-reference loader
# ---------------------------------------------------------------------------


def test_load_unichem_mapping_returns_xrefs_by_inchikey():
    mapping = load_unichem_mapping(FIXTURES / "unichem_subset.tsv")
    curcumin = mapping["VFLDPWHFBUODDF-FCXRPNKRSA-N"]
    assert curcumin["chembl_id"] == "CHEMBL116438"
    assert curcumin["pubchem_cid"] == 969516
    assert curcumin["chebi_id"] == 3962
    assert "drugbank_id" not in curcumin


def test_load_unichem_mapping_handles_multi_source():
    mapping = load_unichem_mapping(FIXTURES / "unichem_subset.tsv")
    ethanol = mapping["LFQSCWFLJHTTHZ-UHFFFAOYSA-N"]
    assert ethanol["chembl_id"] == "CHEMBL545"
    assert ethanol["pubchem_cid"] == 702
    assert ethanol["drugbank_id"] == "DB00898"
    assert ethanol["unichem_src_count"] == 3


def test_load_unichem_mapping_skips_unknown_src_ids(tmp_path: Path):
    bogus = tmp_path / "bogus.tsv"
    bogus.write_text(
        "inchikey\tsrc_id\tsrc_compound_id\n"
        "AAA-BBB\t9999\tX\n"
        "AAA-BBB\t1\tCHEMBL999\n"
    )
    mapping = load_unichem_mapping(bogus)
    assert "AAA-BBB" in mapping
    assert mapping["AAA-BBB"]["chembl_id"] == "CHEMBL999"
    # The unknown src_id=9999 row is silently dropped.
    assert mapping["AAA-BBB"]["unichem_src_count"] == 1


def test_unichem_src_constants_match_ebi_codes():
    assert UNICHEM_SRC["chembl"] == 1
    assert UNICHEM_SRC["drugbank"] == 2
    assert UNICHEM_SRC["kegg"] == 6
    assert UNICHEM_SRC["chebi"] == 7
    assert UNICHEM_SRC["pubchem"] == 22


# ---------------------------------------------------------------------------
# Task 3 — PubChem PUG-REST name resolver
# ---------------------------------------------------------------------------


def test_resolve_compound_by_name_returns_inchikey_and_smiles(tmp_path: Path):
    cache = tmp_path / "pubchem_cache.json"
    body = (
        "CID,InChIKey,CanonicalSMILES\n"
        "969516,VFLDPWHFBUODDF-FCXRPNKRSA-N,COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O\n"
    )
    fake_response = httpx.Response(status_code=200, text=body)
    with patch("httpx.get", return_value=fake_response) as mock_get:
        result = resolve_compound_by_name("Curcumin", cache_path=cache)
    assert result is not None
    assert isinstance(result, PubChemResult)
    assert result.inchikey == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    assert result.cid == 969516
    assert result.smiles is not None and "COc1cc" in result.smiles
    mock_get.assert_called_once()
    assert cache.exists()


def test_resolve_compound_by_name_uses_cache(tmp_path: Path):
    cache = tmp_path / "pubchem_cache.json"
    cache.write_text(
        json.dumps({"Curcumin": {
            "cid": 969516,
            "inchikey": "VFLDPWHFBUODDF-FCXRPNKRSA-N",
            "smiles": "C...",
        }})
    )
    with patch("httpx.get") as mock_get:
        result = resolve_compound_by_name("Curcumin", cache_path=cache)
    assert result is not None
    assert result.inchikey == "VFLDPWHFBUODDF-FCXRPNKRSA-N"
    mock_get.assert_not_called()


def test_resolve_compound_by_name_404_returns_none_and_caches_negative(tmp_path: Path):
    cache = tmp_path / "c.json"
    fake_404 = httpx.Response(status_code=404, text="")
    with patch("httpx.get", return_value=fake_404):
        result = resolve_compound_by_name("Bogus-Compound", cache_path=cache)
    assert result is None
    cached = json.loads(cache.read_text())
    assert cached["Bogus-Compound"] is None


def test_resolve_compound_by_name_500_returns_none_without_caching(tmp_path: Path):
    cache = tmp_path / "c.json"
    fake_500 = httpx.Response(status_code=500, text="")
    with patch("httpx.get", return_value=fake_500):
        assert resolve_compound_by_name("Some Compound", cache_path=cache) is None
    # Unexpected status should not poison the cache (allow retry next run).
    assert not cache.exists()
