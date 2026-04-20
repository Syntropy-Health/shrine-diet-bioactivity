"""
Fix UNKNOWN entity types in Neo4j by rule-based classification.

These 285 nodes were created by LightRAG's ainsert_custom_kg() when relationship
edges referenced entities not in the ingested entity set. LightRAG auto-creates
stub nodes with entity_type=UNKNOWN and description=UNKNOWN.

This script classifies them using pattern matching on entity_id names.

Usage:
    python fix_unknown_entities.py --config local --dry-run
    python fix_unknown_entities.py --config local
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Classification rules (order matters — first match wins)
# ---------------------------------------------------------------------------

# Minerals / elements
MINERALS = {
    "BORON", "CALCIUM", "CHROMIUM", "COPPER", "IODINE", "IRON", "MAGNESIUM",
    "MANGANESE", "NICKEL", "PHOSPHORUS", "POTASSIUM", "SELENIUM", "SODIUM",
    "SULFUR", "ZINC",
}

# Vitamins (by name or pattern)
VITAMINS = {
    "ALPHA-TOCOPHEROL", "GAMMA-TOCOPHEROL", "BETA-CAROTENE", "BIOTIN",
    "CYANOCOBALAMIN", "FOLIC-ACID", "NIACIN", "NICOTINIC-ACID",
    "PANTOTHENIC-ACID", "PHYTOMENADIONE", "PHYTONADIONE", "PYRIDOXINE",
    "RETINOL", "RIBOFLAVIN", "RIBOFLAVINE", "THIAMIN", "VIT-B-6",
    "VITAMIN-D", "VITAMIN-D-3", "VITAMIN-E", "L-ASCORBIC-ACID",
    "ASCORBIC-ACID", "Ergocalciferol", "Retinol", "Riboflavine",
    "Thiamine hydrochloride",
}

# Amino acids
AMINO_ACIDS = {
    "ARGININE", "GLYCINE", "L-ALANINE", "L-ASPARTIC-ACID", "L-CYSTINE",
    "L-GLUTAMIC-ACID", "L-HISTIDINE", "L-LEUCINE", "L-LYSINE", "L-Methionine",
    "L-Proline", "L-Serine", "L-(+)-ISOLEUCINE", "L-(-)-THREONINE",
    "L-(-)-TRYPTOPHAN", "L(+)-TYROSINE", "(+)-VALINE", "SERINE",
    "THREONINE", "TRYPTOPHAN", "TYROSINE", "GABA", "AMINO-ACIDS",
    "DIAMINO-ACID", "4-HYDROXY-PIPECOLIC-ACID",
    "ALPHA-AMINO-BETA-OXALYLAMINO-PROPIONIC-ACID",
    "N,N-DIMETHYL-TRYPTOPHAN", "SPERMIDINE", "HISTAMINE", "TRIGONELLINE",
}

# Fatty acids / lipids
FATTY_ACIDS = {
    "ALPHA-LINOLENIC-ACID", "ARACHIDONIC-ACID", "CHOLESTEROL",
    "DECANOIC-ACID", "DODECANOIC-ACID", "EICOSAPENTAENOIC-ACID",
    "ERUCIC-ACID", "GADOLEIC-ACID", "HEPTANOIC-ACID", "HEXANOIC-ACID",
    "MYRISTOLEIC-ACID", "OCTANOIC-ACID", "PALMITIC-ACID",
    "PENTADECANOIC-ACID", "STEARIC-ACID", "STEARIDONIC ACID",
    "C18:1, n-9", "Vaccenic acid", "Doconexent", "PUFA", "SFA",
    "PHOSPHOLIPIDS", "PHOSPHATIDYL-SERINE",
    "PHOSPHATIDYLSERINE-PLASMALOGEN", "ALPHA-CEPHALIN",
    "(Z,Z)-9,12-Octadecadienoic acid",
}

# Macronutrients / general nutrition
NUTRIENTS = {
    "CARBOHYDRATES", "FAT", "FIBER", "KILOCALORIES", "PROTEIN", "WATER",
    "ASH", "SUGAR", "SUGARS", "STARCH", "SUCROSE", "FRUCTOSE", "GLUCOSE",
    "D-FRUCTOSE", "D-GALACTOSE", "D-GLUCOSE", "D-MANNOSE", "LACTOSE",
    "MALTOSE", "RHAMNOSE", "L-RHAMNOSE", "L-ARABINOSE", "PECTIN",
    "MUCILAGE", "RESIN", "ALPHA-CELLULOSE", "D-GALACTURONIC-ACID",
    "URONIC-ACID", "GLUCOSYLURONIC-ACID", "ALDOBIONIC-ACID",
    "POLYGALACTURONIC-ACIDS",
    "3-(BETA-L-ARABOPYRANOSIDE)-L-ARABINOSE",
    "4-(4-O-METHYL-ALPHA-D-GLUCURONOSIDE)-L-ARABINOSE",
    "3-O-METHYL-L-RHAMNOSE",
}

# Foods (lowercase or mixed-case common food names)
FOODS = {
    "Almond", "Anchovy",
}

# Herbs (binomial Latin names — Genus species pattern)
HERB_PATTERN = re.compile(r"^[A-Z][a-z]+ [a-z]+")

# Enzymes
ENZYMES = {
    "MALATE-DEHYDROGENASE", "PEROXIDASE", "PHOSPHATASE",
}

# Known compound patterns
COMPOUND_INDICATORS = [
    "-OL", "-ONE", "-ENE", "-IDE", "-ATE", "-IN", "-ACID", "-ESTER",
    "FLAVON", "CATECHIN", "TANNIN", "XANTH", "GLYCOSIDE", "GLUCOSIDE",
    "STEROL", "TERPINE", "PINENE",
]

# Biomarker indicators — common clinical lab markers
BIOMARKERS = {
    "HSCRP", "HBA1C", "CORTISOL", "TSH", "INSULIN", "HOMOCYSTEINE",
    "FERRITIN", "TESTOSTERONE", "ESTRADIOL", "DHEA", "IGF-1",
    "CRP", "ESR", "FIBRINOGEN", "IL-6", "TNF-ALPHA",
    "HEMOGLOBIN", "HEMATOCRIT", "CREATININE", "BUN",
    "ALT", "AST", "GGT", "BILIRUBIN", "ALBUMIN",
    "TRIGLYCERIDES", "LDL", "HDL", "VLDL",
    "FASTING-GLUCOSE", "FASTING-INSULIN", "HOMA-IR",
    "25-HYDROXYVITAMIN-D", "VITAMIN-D-25-OH",
}

# Tenant entity types — recognized but not from shared SQLite data
TENANT_ENTITY_TYPES = {"Protocol", "Intervention", "Outcome", "Biomarker"}


def classify_entity(entity_id: str) -> tuple[str, str]:
    """Classify an UNKNOWN entity and return (entity_type, description)."""
    eid = entity_id.strip()
    eid_upper = eid.upper().replace(" ", "-")

    # Biomarker matches (before compound fallback)
    if eid_upper in BIOMARKERS:
        return "Biomarker", f"{eid}. Clinical laboratory biomarker"

    # Exact set matches
    if eid in MINERALS or eid_upper in MINERALS:
        return "Nutrient", f"{eid}. Mineral micronutrient"
    if eid in VITAMINS or eid_upper in VITAMINS:
        return "Nutrient", f"{eid}. Vitamin"
    if eid in AMINO_ACIDS or eid_upper in AMINO_ACIDS:
        return "Compound", f"{eid}. Amino acid"
    if eid in FATTY_ACIDS or eid_upper in FATTY_ACIDS:
        return "Compound", f"{eid}. Fatty acid / lipid"
    if eid in NUTRIENTS or eid_upper in NUTRIENTS:
        return "Nutrient", f"{eid}. Macronutrient / carbohydrate"
    if eid in FOODS:
        return "Food", f"{eid}"
    if eid in ENZYMES or eid_upper in ENZYMES:
        return "Compound", f"{eid}. Enzyme"

    # Pattern: binomial Latin name → Herb
    if HERB_PATTERN.match(eid):
        return "Herb", f"{eid}. Botanical species"

    # Pattern: uppercase chemical name → Compound
    if eid_upper == eid.replace(" ", "-") or eid.startswith("("):
        # All-uppercase or starts with stereochemistry notation
        for indicator in COMPOUND_INDICATORS:
            if indicator in eid_upper:
                return "Compound", f"{eid}. Phytochemical compound"
        # Default uppercase → Compound (most Duke entries are compounds)
        return "Compound", f"{eid}. Phytochemical compound"

    # Mixed case with chemical suffixes
    for indicator in COMPOUND_INDICATORS:
        if indicator.lower() in eid.lower():
            return "Compound", f"{eid}. Phytochemical compound"

    # Fallback: still Compound (these are all from compound_foods/herb_compounds edges)
    return "Compound", f"{eid}. Unclassified bioactive substance"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix UNKNOWN entity types in Neo4j")
    parser.add_argument("--config", choices=["local", "production"], default="local")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR / f"config_{args.config}.env", override=True)

    from neo4j import GraphDatabase
    from entity_schema import safe_label

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    workspace = os.getenv("WORKSPACE", "unified_diet_kg")
    ws = safe_label(workspace)

    with GraphDatabase.driver(uri, auth=(user, password)) as driver, driver.session() as session:
        # Fetch all UNKNOWN entities
        unknowns = []
        for r in session.run(
            f"MATCH (n:`{ws}`) WHERE n.entity_type = $utype "
            "RETURN n.entity_id AS id ORDER BY n.entity_id",
            utype="UNKNOWN",
        ):
            unknowns.append(r["id"])

        print(f"Found {len(unknowns)} UNKNOWN entities\n")

        # Classify
        classifications: dict[str, list[str]] = {}
        updates: list[tuple[str, str, str]] = []
        for eid in unknowns:
            etype, desc = classify_entity(eid)
            updates.append((eid, etype, desc))
            classifications.setdefault(etype, []).append(eid)

        # Print summary
        print("Classification summary:")
        for etype, items in sorted(classifications.items()):
            print(f"  {etype:12s}: {len(items):>4} entities")
            for item in items[:5]:
                print(f"               - {item}")
            if len(items) > 5:
                print(f"               ... and {len(items) - 5} more")
        print()

        if args.dry_run:
            print("DRY RUN — no changes written")
            return

        # Apply updates
        updated = 0
        for eid, etype, desc in updates:
            et = safe_label(etype)
            session.run(
                f"MATCH (n:`{ws}`) WHERE n.entity_id = $eid AND n.entity_type = $old_type "
                f"SET n.entity_type = $etype, n.description = $desc, n:`{et}` "
                "RETURN COUNT(n) AS c",
                eid=eid, old_type="UNKNOWN", etype=etype, desc=desc,
            )
            updated += 1

        # Remove the old UNKNOWN label if it was set
        session.run(
            f"MATCH (n:`{ws}`) WHERE n.entity_type <> $utype REMOVE n:UNKNOWN",
            utype="UNKNOWN",
        )

        print(f"Updated {updated} entities")

        # Verify
        remaining = session.run(
            f"MATCH (n:`{ws}`) WHERE n.entity_type = $utype RETURN COUNT(n) AS c",
            utype="UNKNOWN",
        ).single()["c"]
        print(f"Remaining UNKNOWN: {remaining}")


if __name__ == "__main__":
    main()
