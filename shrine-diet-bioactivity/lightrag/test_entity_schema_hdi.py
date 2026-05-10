"""Tests for INTERACTS_WITH + CONTRAINDICATES schema extensions (Task 7)."""
from __future__ import annotations

import pytest

from entity_schema import (  # type: ignore[import-not-found]
    RELATIONSHIP_TYPES,
    describe_contraindicates,
    describe_interacts_with,
)

pytestmark = [pytest.mark.unit]


def test_interacts_with_registered() -> None:
    assert "INTERACTS_WITH" in RELATIONSHIP_TYPES
    spec = RELATIONSHIP_TYPES["INTERACTS_WITH"]
    assert spec["source_table"] is None
    assert spec["src_type"] == "Herb"
    assert spec["tgt_type"] == "Drug"


def test_contraindicates_registered_polymorphic() -> None:
    assert "CONTRAINDICATES" in RELATIONSHIP_TYPES
    spec = RELATIONSHIP_TYPES["CONTRAINDICATES"]
    assert spec["source_table"] is None
    # Polymorphic: must cover both HDI (Herb → Condition) and legacy
    # tenant (Compound → Disease) semantics.
    assert "Herb" in spec["src_type"]
    assert "Condition" in spec["tgt_type"]


def test_describe_interacts_with() -> None:
    d = describe_interacts_with({
        "herb_name": "St. John's Wort",
        "drug_name": "Sertraline",
        "severity": "severe",
        "mechanism_class": "serotonergic",
        "evidence_tier": "clinical_trial",
    })
    assert "St. John's Wort" in d
    assert "Sertraline" in d
    assert "severe" in d
    assert "serotonergic" in d


def test_describe_contraindicates_herb_condition() -> None:
    d = describe_contraindicates({
        "herb_name": "Ginger",
        "condition": "pregnancy",
        "severity": "moderate",
    })
    assert "Ginger" in d
    assert "pregnancy" in d
    assert "moderate" in d


def test_describe_contraindicates_legacy_compound_disease() -> None:
    d = describe_contraindicates({
        "compound_name": "Caffeine",
        "disease_name": "Hypertension",
        "severity": "mild",
    })
    assert "Caffeine" in d
    assert "Hypertension" in d
