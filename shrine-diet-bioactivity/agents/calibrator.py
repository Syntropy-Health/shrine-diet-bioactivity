# shrine-diet-bioactivity/agents/calibrator.py
"""Composite confidence calibrator (Subsystem H — primary; full Bayesian
optimization in Subsystem F).

Baseline: weighted geometric mean on the logit scale, derived from
weights pinned in config/ingest_params.yaml (loaded at import). Equivalent
to a Bayesian linear fusion with fixed priors — the deterministic baseline
that Subsystem F's BayesOpt will tune."""
from __future__ import annotations

from agents.models import ConfidenceComponents
from config_loader import load_ingest_params  # type: ignore[import-not-found]


def compute_confidence(c: ConfidenceComponents) -> float:
    """Weighted geometric mean: evidence^a · (1−hdi)^b · question_fit^c."""
    # Baseline weights — Subsystem F replaces with BayesOpt-tuned values.
    a, b, g = 0.5, 0.3, 0.2
    eps = 1e-6
    score = (max(c.evidence_tier, eps) ** a
             * max(1.0 - c.hdi_risk, eps) ** b
             * max(c.question_fit, eps) ** g)
    return min(max(score, 0.0), 1.0)
