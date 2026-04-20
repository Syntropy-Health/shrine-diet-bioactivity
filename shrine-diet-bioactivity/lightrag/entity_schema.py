"""
Domain entity type definitions for the Unified Diet Knowledge Graph.

Maps SQLite tables → LightRAG entity nodes and relationship edges.
Used by ingest_unified.py to generate rich, searchable descriptions
for each entity before insertion via ainsert_custom_kg().
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

# Safe Neo4j label pattern: alphanumeric + underscore, starts with letter/underscore
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_label(value: str) -> str:
    """Validate a string is safe for use as a Neo4j label (no injection)."""
    if not _SAFE_LABEL_RE.match(value):
        raise ValueError(f"Unsafe Neo4j label: {value!r}")
    return value


# ---------------------------------------------------------------------------
# Entity type definitions
# ---------------------------------------------------------------------------

ENTITY_TYPES = {
    "Herb": {
        "source_table": "herbs",
        "id_field": "id",
        "name_field": "scientific_name",
        "query": "SELECT * FROM herbs",
    },
    "Compound": {
        "source_table": "compounds",
        "id_field": "id",
        "name_field": "name",
        "query": "SELECT * FROM compounds",
    },
    "Food": {
        "source_table": "compound_foods",
        "id_field": "food_name",
        "name_field": "food_name",
        # query is built dynamically in extract_entities to handle optional nutrition_100g column
        "query": None,
        "query_builder": "build_food_query",
    },
    "Target": {
        "source_table": "targets",
        "id_field": "id",
        "name_field": "name",
        "query": "SELECT id, name, uniprot_id, gene_symbol, druggability_status FROM targets",
    },
    "Disease": {
        "source_table": None,  # aggregated from multiple tables
        "id_field": "disease_name",
        "name_field": "disease_name",
        "query": None,
        "query_builder": "build_disease_query",
    },
    "Symptom": {
        "source_table": "symptoms",
        "id_field": "id",
        "name_field": "name",
        "query": "SELECT id, name, symptom_type, description FROM symptoms",
    },
    # -- Tenant entity types (clinical practice layer) --
    # These have no SQLite source — ingested via tenant API (Phase 4).
    "Protocol": {
        "source_table": None,
        "id_field": "name",
        "name_field": "name",
        "query": None,
    },
    "Intervention": {
        "source_table": None,
        "id_field": "name",
        "name_field": "name",
        "query": None,
    },
    "Outcome": {
        "source_table": None,
        "id_field": "name",
        "name_field": "name",
        "query": None,
    },
    "Biomarker": {
        "source_table": None,
        "id_field": "name",
        "name_field": "name",
        "query": None,
    },
}


# ---------------------------------------------------------------------------
# Relationship type definitions
# ---------------------------------------------------------------------------

RELATIONSHIP_TYPES = {
    "CONTAINS_COMPOUND": {
        "source_table": "herb_compounds",
        "src_type": "Herb",
        "tgt_type": "Compound",
        "query": (
            "SELECT h.scientific_name as src_name, c.name as tgt_name, "
            "hc.plant_part, hc.concentration_low_ppm, hc.concentration_high_ppm "
            "FROM herb_compounds hc "
            "JOIN herbs h ON hc.herb_id = h.id "
            "JOIN compounds c ON hc.compound_id = c.id"
        ),
    },
    "FOUND_IN_FOOD": {
        "source_table": "compound_foods",
        "src_type": "Compound",
        "tgt_type": "Food",
        "query": (
            "SELECT c.name as src_name, cf.food_name as tgt_name, "
            "cf.content_value, cf.content_unit, cf.food_part "
            "FROM compound_foods cf "
            "JOIN compounds c ON cf.compound_id = c.id"
        ),
    },
    "TARGETS_PROTEIN": {
        "source_table": "compound_targets",
        "src_type": "Compound",
        "tgt_type": "Target",
        "query": (
            "SELECT c.name as src_name, t.name as tgt_name, "
            "ct.activity_value, ct.activity_type "
            "FROM compound_targets ct "
            "JOIN compounds c ON ct.compound_id = c.id "
            "JOIN targets t ON ct.target_id = t.id"
        ),
    },
    "ASSOCIATED_WITH_DISEASE": {
        "source_table": "target_diseases",
        "src_type": "Target",
        "tgt_type": "Disease",
        "query": (
            "SELECT t.name as src_name, td.disease_name as tgt_name, "
            "td.evidence_layer as evidence "
            "FROM target_diseases td "
            "JOIN targets t ON td.target_id = t.id"
        ),
    },
    "TREATS_SYMPTOM": {
        "source_table": "herb_symptoms",
        "src_type": "Herb",
        "tgt_type": "Symptom",
        "query": (
            "SELECT h.scientific_name as src_name, s.name as tgt_name "
            "FROM herb_symptoms hs "
            "JOIN herbs h ON hs.herb_id = h.id "
            "JOIN symptoms s ON hs.symptom_id = s.id"
        ),
    },
    # -- Tenant relationship types (clinical practice layer) --
    # These have no SQLite source — ingested via tenant API (Phase 4).
    "INCLUDES": {
        "source_table": None,
        "src_type": "Protocol",
        "tgt_type": "Intervention",
        "query": None,
    },
    "USES": {
        "source_table": None,
        "src_type": "Intervention",
        "tgt_type": "Compound",  # also Herb, Food
        "query": None,
    },
    "RESULTED_IN": {
        "source_table": None,
        "src_type": "Intervention",
        "tgt_type": "Outcome",
        "query": None,
    },
    "MEASURED_BY": {
        "source_table": None,
        "src_type": "Outcome",
        "tgt_type": "Biomarker",
        "query": None,
    },
    "INDICATES": {
        "source_table": None,
        "src_type": "Biomarker",
        "tgt_type": "Disease",  # also Symptom
        "query": None,
    },
    "CONTRAINDICATES": {
        "source_table": None,
        "src_type": "Compound",  # also Intervention
        "tgt_type": "Disease",   # also Symptom
        "query": None,
    },
    "SYNERGIZES_WITH": {
        "source_table": None,
        "src_type": "Compound",  # also Intervention → Intervention
        "tgt_type": "Compound",
        "query": None,
    },
}


# ---------------------------------------------------------------------------
# Description generators — produce searchable text for each entity
# ---------------------------------------------------------------------------


def describe_herb(row: dict[str, Any]) -> str:
    """Generate a rich description for an Herb entity."""
    parts = [row.get("scientific_name", "Unknown herb")]
    if row.get("common_name"):
        parts[0] += f" ({row['common_name']})"
    if row.get("family"):
        parts.append(f"Family: {row['family']}")
    if row.get("genus") and row.get("species"):
        parts.append(f"Taxonomy: {row['genus']} {row['species']}")
    if row.get("usage_type"):
        parts.append(f"Use: {row['usage_type']}")
    if row.get("alternate_names"):
        try:
            names = json.loads(row["alternate_names"]) if isinstance(
                row["alternate_names"], str
            ) else row["alternate_names"]
            if names:
                parts.append(f"Also known as: {', '.join(names[:5])}")
        except (json.JSONDecodeError, TypeError):
            pass
    return ". ".join(parts)


def describe_compound(row: dict[str, Any]) -> str:
    """Generate a rich description for a Compound entity."""
    parts = [row.get("name", "Unknown compound")]
    if row.get("compound_class"):
        parts.append(f"Class: {row['compound_class']}")
    if row.get("cas_number"):
        parts.append(f"CAS: {row['cas_number']}")
    if row.get("bioactivities"):
        try:
            activities = json.loads(row["bioactivities"]) if isinstance(
                row["bioactivities"], str
            ) else row["bioactivities"]
            if activities:
                parts.append(f"Bioactivities: {', '.join(activities[:10])}")
        except (json.JSONDecodeError, TypeError):
            pass
    return ". ".join(parts)


def describe_food(row: dict[str, Any]) -> str:
    """Generate a rich description for a Food entity."""
    parts = [row.get("food_name", "Unknown food")]
    if row.get("food_name_scientific"):
        parts[0] += f" ({row['food_name_scientific']})"
    if row.get("food_group"):
        parts.append(f"Group: {row['food_group']}")
    if row.get("nutrition_100g"):
        try:
            n = json.loads(row["nutrition_100g"]) if isinstance(
                row["nutrition_100g"], str
            ) else row["nutrition_100g"]
            if n:
                summary_parts = []
                if n.get("calories") is not None:
                    summary_parts.append(f"{n['calories']} kcal")
                if n.get("protein") is not None:
                    summary_parts.append(f"{n['protein']}g protein")
                if n.get("dietary_fiber") is not None:
                    summary_parts.append(f"{n['dietary_fiber']}g fiber")
                if n.get("vitamin_c") is not None and n["vitamin_c"] > 0:
                    summary_parts.append(f"{n['vitamin_c']}mg vitamin C")
                if n.get("iron") is not None and n["iron"] > 0:
                    summary_parts.append(f"{n['iron']}mg iron")
                if summary_parts:
                    parts.append(f"Per 100g: {', '.join(summary_parts)}")
        except (json.JSONDecodeError, TypeError):
            pass
    return ". ".join(parts)


def describe_target(row: dict[str, Any]) -> str:
    """Generate a rich description for a Target entity."""
    parts = [row.get("name", "Unknown target")]
    if row.get("uniprot_id"):
        parts.append(f"UniProt: {row['uniprot_id']}")
    if row.get("gene_symbol"):
        parts.append(f"Gene: {row['gene_symbol']}")
    if row.get("druggability_status"):
        parts.append(f"Druggability: {row['druggability_status']}")
    return ". ".join(parts)


def describe_disease(row: dict[str, Any]) -> str:
    """Generate a description for a Disease entity."""
    return row.get("disease_name", "Unknown disease")


def describe_symptom(row: dict[str, Any]) -> str:
    """Generate a description for a Symptom entity."""
    parts = [row.get("name", "Unknown symptom")]
    if row.get("symptom_type"):
        parts.append(f"Type: {row['symptom_type']}")
    if row.get("description"):
        parts.append(row["description"])
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# Tenant entity description generators (clinical practice layer)
# ---------------------------------------------------------------------------


def describe_protocol(row: dict[str, Any]) -> str:
    """Generate a description for a Protocol entity (tenant-scoped)."""
    parts = [row.get("name", "Unknown protocol")]
    if row.get("description"):
        parts.append(row["description"])
    if row.get("phase"):
        parts.append(f"Phase: {row['phase']}")
    if row.get("target_conditions"):
        try:
            conditions = json.loads(row["target_conditions"]) if isinstance(
                row["target_conditions"], str
            ) else row["target_conditions"]
            if conditions:
                parts.append(f"Conditions: {', '.join(conditions[:5])}")
        except (json.JSONDecodeError, TypeError):
            pass
    if row.get("duration"):
        parts.append(f"Duration: {row['duration']}")
    return ". ".join(parts)


def describe_intervention(row: dict[str, Any]) -> str:
    """Generate a description for an Intervention entity (tenant-scoped)."""
    parts = [row.get("name", "Unknown intervention")]
    if row.get("compound"):
        parts.append(f"Compound: {row['compound']}")
    if row.get("route"):
        parts.append(f"Route: {row['route']}")
    if row.get("dosage"):
        parts.append(f"Dosage: {row['dosage']}")
    if row.get("frequency"):
        parts.append(f"Frequency: {row['frequency']}")
    if row.get("form"):
        parts.append(f"Form: {row['form']}")
    return ". ".join(parts)


def describe_outcome(row: dict[str, Any]) -> str:
    """Generate a description for an Outcome entity (tenant-scoped)."""
    parts = [row.get("name", "Unknown outcome")]
    if row.get("observation"):
        parts.append(row["observation"])
    if row.get("direction"):
        parts.append(f"Direction: {row['direction']}")
    if row.get("magnitude"):
        parts.append(f"Magnitude: {row['magnitude']}")
    if row.get("timeframe"):
        parts.append(f"Timeframe: {row['timeframe']}")
    if row.get("condition"):
        parts.append(f"Condition: {row['condition']}")
    return ". ".join(parts)


def describe_biomarker(row: dict[str, Any]) -> str:
    """Generate a description for a Biomarker entity (tenant-scoped)."""
    parts = [row.get("name", "Unknown biomarker")]
    if row.get("category"):
        parts.append(f"Category: {row['category']}")
    if row.get("unit"):
        parts.append(f"Unit: {row['unit']}")
    if row.get("normal_range"):
        parts.append(f"Normal range: {row['normal_range']}")
    if row.get("target_gene"):
        parts.append(f"Gene: {row['target_gene']}")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# Dynamic query builders (for tables with optional columns)
# ---------------------------------------------------------------------------


def build_food_query(conn: sqlite3.Connection) -> str:
    """Build Food entity query, including nutrition_100g only if it exists."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(compound_foods)").fetchall()]
    if "nutrition_100g" in cols:
        return (
            "SELECT DISTINCT food_name, food_name_scientific, food_group, "
            "nutrition_100g FROM compound_foods"
        )
    return "SELECT DISTINCT food_name, food_name_scientific, food_group FROM compound_foods"


def build_disease_query(conn: sqlite3.Connection) -> str:
    """Build Disease entity query, handling missing tables."""
    parts = []
    for table, col in [("target_diseases", "disease_name"), ("chemical_diseases", "disease_name")]:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists:
            parts.append(f"SELECT DISTINCT {col} AS disease_name FROM {table}")
    if not parts:
        return "SELECT 'none' AS disease_name WHERE 0"
    return " UNION ".join(parts)


QUERY_BUILDERS = {
    "build_food_query": build_food_query,
    "build_disease_query": build_disease_query,
}


DESCRIPTION_GENERATORS = {
    "Herb": describe_herb,
    "Compound": describe_compound,
    "Food": describe_food,
    "Target": describe_target,
    "Disease": describe_disease,
    "Symptom": describe_symptom,
    # Tenant entity types (clinical practice layer)
    "Protocol": describe_protocol,
    "Intervention": describe_intervention,
    "Outcome": describe_outcome,
    "Biomarker": describe_biomarker,
}


# ---------------------------------------------------------------------------
# Relationship description generators
# ---------------------------------------------------------------------------


def describe_relationship(rel_type: str, row: dict[str, Any]) -> tuple[str, str]:
    """Generate (description, keywords) for a relationship edge."""
    src = row.get("src_name", "?")
    tgt = row.get("tgt_name", "?")

    if rel_type == "CONTAINS_COMPOUND":
        part = row.get("plant_part", "")
        conc_lo = row.get("concentration_low_ppm")
        conc_hi = row.get("concentration_high_ppm")
        desc = f"{src} contains {tgt}"
        if part:
            desc += f" in {part}"
        if conc_lo is not None and conc_hi is not None:
            desc += f" ({conc_lo}-{conc_hi} PPM)"
        return desc, "herb compound phytochemical contains"

    if rel_type == "FOUND_IN_FOOD":
        val = row.get("content_value")
        unit = row.get("content_unit", "")
        desc = f"{src} found in {tgt}"
        if val is not None:
            desc += f" ({val} {unit})"
        return desc, "compound food dietary source contains"

    if rel_type == "TARGETS_PROTEIN":
        activity = row.get("activity_value")
        atype = row.get("activity_type", "")
        desc = f"{src} targets {tgt}"
        if activity is not None:
            desc += f" ({atype}: {activity})"
        return desc, "compound target protein interaction mechanism"

    if rel_type == "ASSOCIATED_WITH_DISEASE":
        evidence = row.get("evidence", "")
        desc = f"{src} associated with {tgt}"
        if evidence:
            desc += f" (evidence: {evidence})"
        return desc, "target disease association therapeutic"

    if rel_type == "TREATS_SYMPTOM":
        desc = f"{src} treats {tgt}"
        return desc, "herb symptom treatment traditional medicine"

    # -- Tenant relationship types (clinical practice layer) --

    if rel_type == "INCLUDES":
        phase = row.get("phase", "")
        order = row.get("order")
        desc = f"{src} includes intervention {tgt}"
        if phase:
            desc += f" ({phase} phase)"
        if order is not None:
            desc += f" [step {order}]"
        return desc, "protocol intervention treatment plan includes"

    if rel_type == "USES":
        route = row.get("route", "")
        dosage = row.get("dosage", "")
        desc = f"{src} uses {tgt}"
        if route:
            desc += f" via {route}"
        if dosage:
            desc += f" ({dosage})"
        return desc, "intervention compound administration uses therapeutic"

    if rel_type == "RESULTED_IN":
        timeframe = row.get("timeframe", "")
        desc = f"{src} resulted in {tgt}"
        if timeframe:
            desc += f" over {timeframe}"
        return desc, "intervention outcome result clinical effect"

    if rel_type == "MEASURED_BY":
        value = row.get("value")
        unit = row.get("unit", "")
        desc = f"{src} measured by {tgt}"
        if value is not None:
            desc += f" ({value} {unit})"
        return desc, "outcome biomarker measurement laboratory"

    if rel_type == "INDICATES":
        evidence_level = row.get("evidence_level", "")
        desc = f"{src} indicates {tgt}"
        if evidence_level:
            desc += f" (evidence: {evidence_level})"
        return desc, "biomarker disease indicator diagnostic marker"

    if rel_type == "CONTRAINDICATES":
        reason = row.get("reason", "")
        severity = row.get("severity", "")
        desc = f"{src} contraindicated with {tgt}"
        if severity:
            desc += f" (severity: {severity})"
        if reason:
            desc += f" — {reason}"
        return desc, "contraindication warning interaction safety adverse"

    if rel_type == "SYNERGIZES_WITH":
        mechanism = row.get("mechanism", "")
        desc = f"{src} synergizes with {tgt}"
        if mechanism:
            desc += f" via {mechanism}"
        return desc, "synergy combination interaction enhancement potentiation"

    return f"{src} relates to {tgt}", rel_type.lower().replace("_", " ")
