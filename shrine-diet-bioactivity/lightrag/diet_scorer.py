"""Diet → physiological-effect scoring (Phase 5 / spec §4.2).

Pure logic + a thin SQL-orchestration entrypoint. Pipeline:

  Stage 1: per-food unit normalization → mg/g exposure aggregated per compound
  Stage 2: fan out to targets / diseases / pathways via per-layer evidence weights
  Stage 3: roll up + rank, top-N per output category

The weights and citation_factor formula are public constants documented in
ADR 0010. Treat the output scores as ordinal (rank-comparable within one run),
not cardinal (comparable across diets or absolute thresholds).
"""

from __future__ import annotations

import math
import sqlite3
from typing import Iterable, Optional

from unit_normalizer import to_mg_per_gram

# Single-place tuning for evidence weights. Direct binding (compound_targets)
# is the gold-standard 1.0; disease-layer evidence is below 1.0 because it
# rolls up many rows per (compound, disease) pair.
#
# Weight rationale (ADR 0010):
#   direct_therapeutic  0.90  — CTD direct evidence; treatment relationship
#   direct_marker       0.70  — CTD direct evidence; biomarker (informative
#                                but doesn't imply causation)
#   inferred_via_gene   0.50  — CTD inference layer; gated by InferenceScore
#                                upstream so non-zero already means meaningful
EVIDENCE_WEIGHTS: dict[str, float] = {
    "direct_therapeutic": 0.90,
    "direct_marker": 0.70,
    "inferred_via_gene": 0.50,
}

TARGET_BINDING_WEIGHT = 1.0  # compound_targets — direct CMAUP binding
PATHWAY_MEMBERSHIP_WEIGHT = 0.60  # KEGG pathway → target via gene_symbol

CITATION_FACTOR_CAP = 3.0  # heavy-cited diseases shouldn't dominate the rank
TOP_N = 20


# ---- Stage 1: exposure aggregation --------------------------------------


def aggregate_exposures(
    diet: list[tuple[str, float]],
    compound_food_rows: Iterable[tuple[str, str, Optional[float], Optional[str]]],
) -> dict:
    """Compute per-compound exposure (mg consumed) for the given diet.

    Args:
      diet: list of (food_name, grams_consumed) — duplicates aggregate.
      compound_food_rows: tuples of (food_name, compound_id, content_value,
        content_unit) sourced from compound_foods.

    Returns dict with:
      exposures: {compound_id: total_mg}
      warnings:  list of strings (unmappable foods, unsupported units)
    """
    # Aggregate duplicate-food entries first.
    grams_by_food: dict[str, float] = {}
    for food, grams in diet:
        if grams < 0:
            raise ValueError(f"negative grams for {food!r}: {grams}")
        grams_by_food[food] = grams_by_food.get(food, 0.0) + grams

    # Index compound_food rows by food_name for O(1) lookup per food.
    rows_by_food: dict[str, list[tuple[str, Optional[float], Optional[str]]]] = {}
    for food_name, compound_id, value, unit in compound_food_rows:
        rows_by_food.setdefault(food_name, []).append((compound_id, value, unit))

    exposures: dict[str, float] = {}
    warnings: list[str] = []

    for food, grams in grams_by_food.items():
        if food not in rows_by_food:
            warnings.append(f"{food}: 0 compounds in compound_foods (food not found)")
            continue
        for compound_id, value, unit in rows_by_food[food]:
            mg_per_g = to_mg_per_gram(value, unit)
            if mg_per_g is None:
                warnings.append(
                    f"{food}/{compound_id}: unsupported unit {unit!r} "
                    f"(value={value}); row skipped"
                )
                continue
            exposures[compound_id] = exposures.get(compound_id, 0.0) + grams * mg_per_g

    return {"exposures": exposures, "warnings": warnings}


# ---- Stage 2 helpers -----------------------------------------------------


def citation_factor(n_pubmed: int) -> float:
    """Logarithmic boost capped at CITATION_FACTOR_CAP. Negative inputs → 1.0."""
    if n_pubmed <= 0:
        return 1.0
    return min(1.0 + math.log10(1 + n_pubmed), CITATION_FACTOR_CAP)


def _count_pubmed_ids(pubmed_ids: Optional[str]) -> int:
    if not pubmed_ids:
        return 0
    return len([x for x in pubmed_ids.split("|") if x.strip()])


# ---- Stage 2: target fan-out --------------------------------------------


def score_targets(
    exposures: dict[str, float],
    target_rows: Iterable[tuple[str, str, str]],
) -> list[dict]:
    """Score each target by sum of (exposure × TARGET_BINDING_WEIGHT) across
    contributing compounds.

    Args:
      exposures: {compound_id: mg}
      target_rows: (compound_id, target_id, target_name) tuples.

    Returns list of dicts sorted by score desc, top TOP_N:
      {"target_id", "target", "score", "evidence_count", "top_compounds"}
    """
    # per (target_id) → {score: float, name: str, contributors: {cid: contribution}}
    bucket: dict[str, dict] = {}
    for compound_id, target_id, target_name in target_rows:
        exposure = exposures.get(compound_id)
        if exposure is None or exposure <= 0:
            continue
        contribution = exposure * TARGET_BINDING_WEIGHT
        slot = bucket.setdefault(
            target_id,
            {"name": target_name, "score": 0.0, "contributors": {}},
        )
        slot["score"] += contribution
        slot["contributors"][compound_id] = (
            slot["contributors"].get(compound_id, 0.0) + contribution
        )

    out: list[dict] = []
    for tid, slot in bucket.items():
        contributors = sorted(
            slot["contributors"].items(), key=lambda kv: kv[1], reverse=True
        )
        out.append(
            {
                "target_id": tid,
                "target": slot["name"],
                "score": slot["score"],
                "evidence_count": len(slot["contributors"]),
                "top_compounds": [c for c, _ in contributors[:5]],
            }
        )
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:TOP_N]


# ---- Stage 2: disease fan-out -------------------------------------------


def score_diseases(
    exposures: dict[str, float],
    cde_rows: Iterable[tuple[str, str, str, str, Optional[str]]],
) -> list[dict]:
    """Score each disease by aggregating compound_disease_evidence rows.

    Args:
      exposures: {compound_id: mg}
      cde_rows: (compound_id, disease_id, disease_name, evidence_type,
                 pubmed_ids) tuples.

    Returns list sorted by score desc, top TOP_N.
    """
    bucket: dict[str, dict] = {}
    for compound_id, disease_id, disease_name, evidence_type, pubmed_ids in cde_rows:
        exposure = exposures.get(compound_id)
        if exposure is None or exposure <= 0:
            continue
        weight = EVIDENCE_WEIGHTS.get(evidence_type)
        if weight is None:
            # Unknown evidence type — defensive skip; the schema CHECK should
            # already prevent these but we don't crash if it ever leaks.
            continue
        n_cites = _count_pubmed_ids(pubmed_ids)
        contribution = exposure * weight * citation_factor(n_cites)
        slot = bucket.setdefault(
            disease_id,
            {
                "name": disease_name,
                "score": 0.0,
                "evidence_breakdown": {
                    "direct_therapeutic": 0,
                    "direct_marker": 0,
                    "inferred_via_gene": 0,
                    "pubmed_total": 0,
                },
            },
        )
        slot["score"] += contribution
        slot["evidence_breakdown"][evidence_type] += 1
        slot["evidence_breakdown"]["pubmed_total"] += n_cites

    out: list[dict] = [
        {
            "disease_id": did,
            "disease": slot["name"],
            "score": slot["score"],
            "evidence_breakdown": slot["evidence_breakdown"],
        }
        for did, slot in bucket.items()
    ]
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:TOP_N]


# ---- Stage 3: pathway roll-up --------------------------------------------


def score_pathways(
    target_scores: Iterable[dict],
    kpg_rows: Iterable[tuple[str, str, str]],
) -> list[dict]:
    """Roll up target scores to pathway level via KEGG pathway-gene membership.

    Args:
      target_scores: output of score_targets() (each has target_id + score)
      kpg_rows: (kegg_pathway_id, pathway_name, target_id_via_gene) tuples.
        ``target_id_via_gene`` is **always a ``targets.id`` value** (resolved
        upstream through ``kegg_pathway_genes`` ↔ ``targets`` via
        ``gene_symbol``). It is NOT a raw gene_symbol; passing a symbol
        silently misses the score lookup. See #64.

    Returns list sorted by score desc, top TOP_N.
    """
    target_score_lookup = {ts["target_id"]: ts["score"] for ts in target_scores}
    bucket: dict[str, dict] = {}
    for pid, pname, tid in kpg_rows:
        ts = target_score_lookup.get(tid)
        if ts is None or ts <= 0:
            continue
        slot = bucket.setdefault(pid, {"name": pname, "score": 0.0, "targets": set()})
        # Apply the documented pathway-membership weight (ADR 0010 §4.2 Stage 2).
        # Without this multiplier, pathway scores are 1.67× higher than the
        # published formula — making the implementation diverge from the ADR.
        slot["score"] += ts * PATHWAY_MEMBERSHIP_WEIGHT
        slot["targets"].add(tid)

    out = [
        {
            "kegg_id": pid,
            "pathway": slot["name"],
            "score": slot["score"],
            "n_targets_hit": len(slot["targets"]),
        }
        for pid, slot in bucket.items()
    ]
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:TOP_N]


# ---- Top-level SQL orchestration ----------------------------------------


def score_diet(
    diet: list[tuple[str, float]],
    *,
    conn: sqlite3.Connection,
) -> dict:
    """Score a diet end-to-end against the live database.

    Returns the JSON-shaped output described in spec §2.
    """
    # Stage 1: pull only the compound_food rows for foods in the diet.
    food_names = list({food for food, _ in diet})
    if not food_names:
        return {
            "exposures": {},
            "targets": [],
            "diseases": [],
            "pathways": [],
            "warnings": [],
            "disclaimer": _DISCLAIMER,
        }
    placeholders = ",".join("?" * len(food_names))
    cf_rows = list(
        conn.execute(
            f"SELECT food_name, compound_id, content_value, content_unit "
            f"FROM compound_foods WHERE food_name IN ({placeholders})",
            food_names,
        )
    )
    stage1 = aggregate_exposures(diet, cf_rows)
    exposures = stage1["exposures"]
    warnings = list(stage1["warnings"])

    if not exposures:
        return {
            "exposures": {},
            "targets": [],
            "diseases": [],
            "pathways": [],
            "warnings": warnings,
            "disclaimer": _DISCLAIMER,
        }

    # Stage 2 — pull only edges for compounds we have exposure for.
    compound_ids = list(exposures)
    cph = ",".join("?" * len(compound_ids))

    target_rows = list(
        conn.execute(
            f"SELECT ct.compound_id, t.id, t.name "
            f"FROM compound_targets ct "
            f"JOIN targets t ON t.id = ct.target_id "
            f"WHERE ct.compound_id IN ({cph})",
            compound_ids,
        )
    )
    targets = score_targets(exposures, target_rows)

    cde_rows = list(
        conn.execute(
            f"SELECT cde.compound_id, cde.disease_id, d.preferred_name, "
            f"       cde.evidence_type, cde.pubmed_ids "
            f"FROM compound_disease_evidence cde "
            f"JOIN diseases_canonical d ON d.id = cde.disease_id "
            f"WHERE cde.compound_id IN ({cph})",
            compound_ids,
        )
    )
    diseases = score_diseases(exposures, cde_rows)

    # Stage 3: pathway roll-up via kegg_pathway_genes ↔ targets ↔ targets we hit.
    target_ids = [t["target_id"] for t in targets]
    pathways: list[dict] = []
    if target_ids:
        tph = ",".join("?" * len(target_ids))
        kpg_rows = list(
            conn.execute(
                f"SELECT kpg.kegg_pathway_id, kp.name, t.id "
                f"FROM kegg_pathway_genes kpg "
                f"JOIN targets t ON t.gene_symbol = kpg.gene_symbol "
                f"JOIN kegg_pathways kp ON kp.id = kpg.kegg_pathway_id "
                f"WHERE t.id IN ({tph})",
                target_ids,
            )
        )
        pathways = score_pathways(targets, kpg_rows)

    return {
        "exposures": exposures,
        "targets": targets,
        "diseases": diseases,
        "pathways": pathways,
        "warnings": warnings,
        "disclaimer": _DISCLAIMER,
    }


_DISCLAIMER = (
    "Research-aid prediction. Not medical advice. "
    "Scores are ordinal (rank within this run), not cardinal "
    "(absolute thresholds). See ADR 0010 for algorithm details."
)
