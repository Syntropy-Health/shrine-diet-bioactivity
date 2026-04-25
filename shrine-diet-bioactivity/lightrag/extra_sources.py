"""Extra entity / relationship extractors for SymMap v2 and HERB 2.0.

These are NEW data sources layered on top of the legacy
``ENTITY_TYPES`` / ``RELATIONSHIP_TYPES`` registries in
``entity_schema.py``. They extend the same six entity types (Herb,
Compound, Symptom, Target, Disease) with additional rows from the
SymMap and HERB 2.0 SQLite tables loaded by ``scripts/load-symmap.ts``
and ``scripts/load-herb2.ts``.

We keep them in a separate module rather than mutating
``ENTITY_TYPES`` so that:

  * Each extra source carries its own per-row description generator
    (SymMap herbs add CN/EN names + meridian / property metadata that
    the Duke describe_herb does not understand).
  * Cross-references go in source_id (e.g. ``symmap:SMHB-0001``,
    ``herb2:HERB000001``) so the snapshot report (Task 10) and Cypher
    queries can attribute by data source.
  * HERB 2.0's experimental tier (1.79 M edges) is sampled here, not
    in ingest_unified, so the cap is visible in code review.

Each extractor returns LightRAG-ready dicts ready to flatten into
``all_entities`` / ``all_relationships`` in ingest_unified.main.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Caps — the only place the experimental-tier explosion is bounded
# ---------------------------------------------------------------------------

# HERB 2.0 has ~141 clinical edges + ~1.79M experimental + 0 traditional.
# Embedding 1.79M descriptions on Ollama would blow the budget; sampling
# the experimental tier keeps the KG retrievable while preserving the
# clinical tier in full. Override via env if running with OpenAI.
HERB2_CLINICAL_CAP = 0  # 0 = unlimited (only ~141 rows anyway)
HERB2_EXPERIMENTAL_CAP_DEFAULT = 50_000


def _fetch(conn: sqlite3.Connection, sql: str, limit: int | None = None) -> list[dict]:
    if limit and limit > 0:
        sql = f"{sql} LIMIT {limit}"
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


# ---------------------------------------------------------------------------
# Description generators
# ---------------------------------------------------------------------------


def describe_symmap_herb(row: dict[str, Any]) -> str:
    parts: list[str] = []
    en = row.get("english_name") or ""
    cn = row.get("chinese_name") or ""
    pinyin = row.get("pinyin_name") or ""
    latin = row.get("latin_name") or ""
    head = en or latin or pinyin or cn or "Unknown SymMap herb"
    parts.append(head)
    if cn and cn != head:
        parts.append(f"Chinese: {cn}")
    if pinyin and pinyin != head:
        parts.append(f"Pinyin: {pinyin}")
    if latin and latin != head:
        parts.append(f"Latin: {latin}")
    if row.get("class_en"):
        parts.append(f"TCM class: {row['class_en']}")
    if row.get("properties_en"):
        parts.append(f"Properties: {row['properties_en']}")
    if row.get("meridians_en"):
        parts.append(f"Meridians: {row['meridians_en']}")
    if row.get("use_part"):
        parts.append(f"Part used: {row['use_part']}")
    return ". ".join(parts)


def describe_symmap_tcm_symptom(row: dict[str, Any]) -> str:
    head = row.get("name_en") or row.get("name_cn") or row.get("pinyin") or "Unknown TCM symptom"
    parts = [head]
    if row.get("name_cn") and row["name_cn"] != head:
        parts.append(f"Chinese: {row['name_cn']}")
    if row.get("locus"):
        parts.append(f"Locus: {row['locus']}")
    if row.get("property"):
        parts.append(f"Property: {row['property']}")
    if row.get("symptom_type"):
        parts.append(f"Type: {row['symptom_type']}")
    return ". ".join(parts)


def describe_symmap_modern_symptom(row: dict[str, Any]) -> str:
    parts = [row.get("name") or "Unknown modern symptom"]
    if row.get("umls_id"):
        parts.append(f"UMLS: {row['umls_id']}")
    if row.get("mesh_id"):
        parts.append(f"MeSH: {row['mesh_id']}")
    if row.get("icd10cm_id"):
        parts.append(f"ICD-10-CM: {row['icd10cm_id']}")
    if row.get("hpo_id"):
        parts.append(f"HPO: {row['hpo_id']}")
    return ". ".join(parts)


def describe_symmap_ingredient(row: dict[str, Any]) -> str:
    parts = [row.get("name") or "Unknown SymMap ingredient"]
    if row.get("formula"):
        parts.append(f"Formula: {row['formula']}")
    if row.get("pubchem_cid"):
        parts.append(f"PubChem CID: {row['pubchem_cid']}")
    if row.get("cas_id"):
        parts.append(f"CAS: {row['cas_id']}")
    if row.get("molecular_weight"):
        parts.append(f"MW: {row['molecular_weight']:.2f}")
    if row.get("ob_score"):
        parts.append(f"OB score: {row['ob_score']:.2f}")
    return ". ".join(parts)


def describe_symmap_gene(row: dict[str, Any]) -> str:
    head = row.get("gene_symbol") or row.get("gene_name") or "Unknown SymMap gene"
    parts = [head]
    if row.get("gene_name") and row["gene_name"] != head:
        parts.append(row["gene_name"])
    if row.get("uniprot_id"):
        parts.append(f"UniProt: {row['uniprot_id']}")
    if row.get("hgnc_id"):
        parts.append(f"HGNC: {row['hgnc_id']}")
    if row.get("ensembl_id"):
        parts.append(f"Ensembl: {row['ensembl_id']}")
    return ". ".join(parts)


def describe_herb2_herb(row: dict[str, Any]) -> str:
    head = row.get("name_en") or row.get("latin") or row.get("pinyin") or "Unknown HERB 2.0 herb"
    parts = [head]
    if row.get("name_cn") and row["name_cn"] != head:
        parts.append(f"Chinese: {row['name_cn']}")
    if row.get("pinyin") and row["pinyin"] != head:
        parts.append(f"Pinyin: {row['pinyin']}")
    if row.get("latin") and row["latin"] != head:
        parts.append(f"Latin: {row['latin']}")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# Source-adapter registry — entity types
# ---------------------------------------------------------------------------

EntityAdapter = dict[str, Any]


SYMMAP_HERB_QUERY = (
    "SELECT symmap_id, chinese_name, pinyin_name, latin_name, english_name, "
    "properties_cn, properties_en, meridians_cn, meridians_en, "
    "class_cn, class_en, use_part FROM symmap_herbs ORDER BY symmap_id"
)
SYMMAP_TCM_SYMPTOM_QUERY = (
    "SELECT symmap_id, name_cn, name_en, pinyin, locus, property, symptom_type "
    "FROM symmap_tcm_symptoms ORDER BY symmap_id"
)
SYMMAP_MODERN_SYMPTOM_QUERY = (
    "SELECT symmap_id, name, definition, umls_id, mesh_id, icd10cm_id, hpo_id "
    "FROM symmap_modern_symptoms ORDER BY symmap_id"
)
SYMMAP_INGREDIENT_QUERY = (
    "SELECT mol_id, name, pubchem_cid, cas_id, formula, molecular_weight, ob_score "
    "FROM symmap_ingredients ORDER BY mol_id"
)
SYMMAP_GENE_QUERY = (
    "SELECT gene_id, gene_symbol, gene_name, protein_name, uniprot_id, "
    "ensembl_id, hgnc_id, ncbi_id FROM symmap_genes ORDER BY gene_id"
)
HERB2_HERB_QUERY = (
    "SELECT herb_id, name_en, name_cn, pinyin, latin FROM herb2_herbs ORDER BY herb_id"
)


EXTRA_ENTITY_ADAPTERS: list[EntityAdapter] = [
    {
        "source": "symmap",
        "table": "symmap_herbs",
        "entity_type": "Herb",
        # latin_name first so SymMap herbs dedupe against Duke
        # ``herbs.scientific_name`` (also Latin). Falls back to English /
        # Pinyin / Chinese for the ~50 rows missing a Latin binomial.
        "id_field": "latin_name",
        "fallback_id_fields": ("english_name", "pinyin_name", "chinese_name"),
        "source_id_field": "symmap_id",
        "query": SYMMAP_HERB_QUERY,
        "describe": describe_symmap_herb,
        "extra_props": (
            "chinese_name",
            "pinyin_name",
            "english_name",
            "properties_en",
            "meridians_en",
            "use_part",
            "class_en",
        ),
    },
    {
        "source": "symmap",
        "table": "symmap_tcm_symptoms",
        "entity_type": "Symptom",
        "id_field": "name_en",
        "fallback_id_fields": ("pinyin", "name_cn"),
        "source_id_field": "symmap_id",
        "query": SYMMAP_TCM_SYMPTOM_QUERY,
        "describe": describe_symmap_tcm_symptom,
        "extra_props": ("name_cn", "pinyin", "symptom_type"),
    },
    {
        "source": "symmap",
        "table": "symmap_modern_symptoms",
        "entity_type": "Symptom",
        "id_field": "name",
        "fallback_id_fields": (),
        "source_id_field": "symmap_id",
        "query": SYMMAP_MODERN_SYMPTOM_QUERY,
        "describe": describe_symmap_modern_symptom,
        "extra_props": ("umls_id", "mesh_id", "icd10cm_id", "hpo_id"),
    },
    {
        "source": "symmap",
        "table": "symmap_ingredients",
        "entity_type": "Compound",
        "id_field": "name",
        "fallback_id_fields": ("pubchem_cid", "mol_id"),
        "source_id_field": "mol_id",
        "query": SYMMAP_INGREDIENT_QUERY,
        "describe": describe_symmap_ingredient,
        "extra_props": ("pubchem_cid", "cas_id", "formula"),
    },
    {
        "source": "symmap",
        "table": "symmap_genes",
        "entity_type": "Target",
        "id_field": "gene_symbol",
        "fallback_id_fields": ("uniprot_id", "gene_id"),
        "source_id_field": "gene_id",
        "query": SYMMAP_GENE_QUERY,
        "describe": describe_symmap_gene,
        "extra_props": ("uniprot_id", "hgnc_id", "ensembl_id"),
    },
    {
        "source": "herb2",
        "table": "herb2_herbs",
        "entity_type": "Herb",
        "id_field": "latin",
        "fallback_id_fields": ("name_en", "pinyin"),
        "source_id_field": "herb_id",
        "query": HERB2_HERB_QUERY,
        "describe": describe_herb2_herb,
        "extra_props": ("name_cn", "pinyin", "name_en"),
    },
]


def extract_extra_entities(
    conn: sqlite3.Connection,
    adapter: EntityAdapter,
    max_count: int | None = None,
) -> list[dict]:
    """Run an EXTRA_ENTITY_ADAPTERS spec → LightRAG entity dict list."""
    if not _table_exists(conn, adapter["table"]):
        print(f"  ⚠ Table '{adapter['table']}' not found, skipping {adapter['source']}/{adapter['entity_type']}")
        return []

    rows = _fetch(conn, adapter["query"], limit=max_count)
    entities: list[dict] = []
    seen: set[str] = set()
    describe: Callable[[dict[str, Any]], str] = adapter["describe"]
    primary = adapter["id_field"]
    fallbacks: tuple[str, ...] = adapter.get("fallback_id_fields", ())

    for row in rows:
        name: str = ""
        for field in (primary,) + fallbacks:
            v = row.get(field)
            if v:
                name = str(v).strip()
                break
        if not name or name in seen:
            continue
        seen.add(name)

        ent: dict[str, Any] = {
            "entity_name": name,
            "entity_type": adapter["entity_type"],
            "description": describe(row),
            "scope": "shared",
            "source_id": f"{adapter['source']}:{row[adapter['source_id_field']]}",
        }
        # Pass through extra props for downstream filtering / snapshot.
        for prop in adapter.get("extra_props", ()):
            v = row.get(prop)
            if v is not None and v != "":
                ent[prop] = v
        entities.append(ent)

    return entities


# ---------------------------------------------------------------------------
# HERB 2.0 herb_disease extractor (relationship)
# ---------------------------------------------------------------------------


def extract_herb2_relationships(
    conn: sqlite3.Connection,
    experimental_cap: int | None = None,
) -> list[dict]:
    """Extract HERB 2.0 herb→disease ASSOCIATED_WITH_DISEASE edges.

    Caps the experimental tier (1.79M rows) by default so the embedding
    pipeline stays tractable. Clinical tier (~141 rows) is always
    ingested in full. Pass ``experimental_cap=0`` to ingest everything.
    """
    if not _table_exists(conn, "herb2_herb_disease"):
        print("  ⚠ Table 'herb2_herb_disease' not found, skipping HERB 2.0 edges")
        return []
    if not _table_exists(conn, "herb2_herbs"):
        print("  ⚠ Table 'herb2_herbs' not found, skipping HERB 2.0 edges")
        return []

    cap = HERB2_EXPERIMENTAL_CAP_DEFAULT if experimental_cap is None else experimental_cap

    # Clinical first (always in full).
    clinical_sql = (
        "SELECT h.latin AS src_name, h.name_en AS src_name_en, "
        "h.name_cn AS src_name_cn, hd.disease_label AS tgt_name, "
        "hd.evidence_tier, hd.source_pmid "
        "FROM herb2_herb_disease hd "
        "JOIN herb2_herbs h ON hd.herb_id = h.herb_id "
        "WHERE hd.evidence_tier = 'clinical' "
        "ORDER BY hd.herb_id, hd.disease_id"
    )
    clinical = _fetch(conn, clinical_sql)

    experimental_sql = (
        "SELECT h.latin AS src_name, h.name_en AS src_name_en, "
        "h.name_cn AS src_name_cn, hd.disease_label AS tgt_name, "
        "hd.evidence_tier, hd.source_pmid "
        "FROM herb2_herb_disease hd "
        "JOIN herb2_herbs h ON hd.herb_id = h.herb_id "
        "WHERE hd.evidence_tier = 'experimental' "
        "ORDER BY hd.herb_id, hd.disease_id"
    )
    experimental = _fetch(conn, experimental_sql, limit=cap if cap > 0 else None)

    rels: list[dict] = []
    for row in clinical + experimental:
        src = (row.get("src_name") or row.get("src_name_en") or "").strip()
        tgt = str(row.get("tgt_name") or "").strip()
        if not src or not tgt:
            continue
        tier = row["evidence_tier"]
        weight = {"clinical": 1.0, "experimental": 0.55, "traditional": 0.2}.get(tier, 0.5)
        desc = f"{src} associated with {tgt} (HERB 2.0 {tier} evidence"
        if row.get("source_pmid"):
            desc += f", PMID {row['source_pmid']}"
        desc += ")"
        rels.append(
            {
                "src_id": src,
                "tgt_id": tgt,
                "description": desc,
                "keywords": f"herb disease association {tier} herb2",
                "weight": weight,
                "scope": "shared",
                "source_id": "herb2:herb_disease",
                "evidence_tier": tier,
            }
        )
    print(
        f"  HERB 2.0: {len(clinical)} clinical + "
        f"{min(len(experimental), cap if cap else len(experimental))} experimental "
        f"(cap={cap}) = {len(rels)} edges"
    )
    return rels
