# UniChem source-mapping files

Source: https://www.ebi.ac.uk/unichem/

These files are freely available for academic and commercial use following
ChEMBL's CC BY-SA 3.0 terms (UniChem distributes the same compound
identifiers that ChEMBL maps to other sources).

We download the InChIKey ↔ external-ID mappings for `src_id` ∈ {1, 2, 6, 7, 22}
(ChEMBL, DrugBank, KEGG, ChEBI, PubChem). The PubChem and ChEBI columns
parse as integers; the rest are opaque strings.

Files referenced by the build pipeline:
- `data/unichem_src1_22_2_6_7.tsv` — concatenated source-mapping export
  (download via EBI FTP; see `scripts/build_compound_identity.py --unichem-tsv`).

The fixture at `lightrag/tests/fixtures/unichem_subset.tsv` is a 8-row
hand-curated slice of the same format used in unit tests.
