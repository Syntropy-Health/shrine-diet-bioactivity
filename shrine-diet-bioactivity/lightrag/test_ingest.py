"""
Tests for the unified ingestion pipeline.

Validates entity extraction from SQLite, description generation,
and batch formatting — without requiring LightRAG or Neo4j.

Usage:
    python -m pytest test_ingest.py -v
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from entity_schema import (
    DESCRIPTION_GENERATORS,
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
    describe_biomarker,
    describe_compound,
    describe_food,
    describe_herb,
    describe_intervention,
    describe_outcome,
    describe_protocol,
    describe_relationship,
)
from ingest_unified import batch_items, extract_entities, extract_relationships, table_exists

DB_PATH = Path(__file__).parent / ".." / "data_local" / "herbal_botanicals.db"
DB_EXISTS = DB_PATH.exists()


# ---------------------------------------------------------------------------
# Unit tests (no DB required)
# ---------------------------------------------------------------------------


class TestDescriptionGenerators:
    def test_describe_herb_basic(self):
        row = {"scientific_name": "Curcuma longa", "common_name": "Turmeric", "family": "Zingiberaceae"}
        desc = describe_herb(row)
        assert "Curcuma longa" in desc
        assert "Turmeric" in desc
        assert "Zingiberaceae" in desc

    def test_describe_herb_with_chinese_name(self):
        row = {
            "scientific_name": "Panax ginseng",
            "common_name": "Ginseng",
            "family": "Araliaceae",
            "alternate_names": '["人参", "Korean ginseng"]',
        }
        desc = describe_herb(row)
        assert "Panax ginseng" in desc
        assert "人参" in desc

    def test_describe_herb_missing_fields(self):
        row = {"scientific_name": "Unknown plant"}
        desc = describe_herb(row)
        assert "Unknown plant" in desc

    def test_describe_compound_with_bioactivities(self):
        row = {
            "name": "Curcumin",
            "compound_class": "Polyphenol",
            "bioactivities": '["anti-inflammatory", "antioxidant"]',
        }
        desc = describe_compound(row)
        assert "Curcumin" in desc
        assert "Polyphenol" in desc
        assert "anti-inflammatory" in desc

    def test_describe_food_with_nutrition(self):
        row = {
            "food_name": "Garlic",
            "food_group": "Vegetables",
            "nutrition_100g": '{"calories": 149, "protein": 6.36, "vitamin_c": 31.2}',
        }
        desc = describe_food(row)
        assert "Garlic" in desc
        assert "149 kcal" in desc
        assert "6.36g protein" in desc

    def test_describe_food_no_nutrition(self):
        row = {"food_name": "Mystery fruit", "food_group": "Fruits"}
        desc = describe_food(row)
        assert "Mystery fruit" in desc
        assert "Fruits" in desc

    def test_describe_relationship_contains_compound(self):
        row = {"src_name": "Turmeric", "tgt_name": "Curcumin", "plant_part": "rhizome",
               "concentration_low_ppm": 1000, "concentration_high_ppm": 5000}
        desc, kw = describe_relationship("CONTAINS_COMPOUND", row)
        assert "Turmeric contains Curcumin" in desc
        assert "rhizome" in desc
        assert "herb" in kw

    def test_describe_relationship_found_in_food(self):
        row = {"src_name": "Quercetin", "tgt_name": "Apple", "content_value": 4.42, "content_unit": "mg/100g"}
        desc, kw = describe_relationship("FOUND_IN_FOOD", row)
        assert "Quercetin found in Apple" in desc
        assert "food" in kw

    # -- Tenant entity description generators --

    def test_describe_protocol_full(self):
        row = {
            "name": "Anti-Inflammation IV Protocol",
            "description": "Targeted IV therapy for chronic inflammation",
            "phase": "treatment",
            "target_conditions": '["rheumatoid arthritis", "chronic fatigue"]',
            "duration": "12 weeks",
        }
        desc = describe_protocol(row)
        assert "Anti-Inflammation IV Protocol" in desc
        assert "treatment" in desc
        assert "rheumatoid arthritis" in desc
        assert "12 weeks" in desc

    def test_describe_protocol_minimal(self):
        row = {"name": "Basic Protocol"}
        desc = describe_protocol(row)
        assert "Basic Protocol" in desc

    def test_describe_protocol_bad_json_conditions(self):
        row = {"name": "Test", "target_conditions": "not valid json ["}
        desc = describe_protocol(row)
        assert "Test" in desc  # should not crash

    def test_describe_intervention_full(self):
        row = {
            "name": "Glutathione IV",
            "compound": "Glutathione",
            "route": "IV",
            "dosage": "2000mg",
            "frequency": "2x/week",
            "form": "injection",
        }
        desc = describe_intervention(row)
        assert "Glutathione IV" in desc
        assert "IV" in desc
        assert "2000mg" in desc
        assert "2x/week" in desc

    def test_describe_intervention_minimal(self):
        row = {"name": "Turmeric supplement"}
        desc = describe_intervention(row)
        assert "Turmeric supplement" in desc

    def test_describe_outcome_full(self):
        row = {
            "name": "hsCRP reduction post-protocol",
            "observation": "Significant reduction in inflammatory markers",
            "direction": "improved",
            "magnitude": "40% decrease",
            "timeframe": "12 weeks",
            "condition": "chronic inflammation",
        }
        desc = describe_outcome(row)
        assert "hsCRP reduction" in desc
        assert "improved" in desc
        assert "40% decrease" in desc
        assert "12 weeks" in desc

    def test_describe_biomarker_full(self):
        row = {
            "name": "hsCRP",
            "category": "inflammatory",
            "unit": "mg/L",
            "normal_range": "<1.0",
            "target_gene": "CRP",
        }
        desc = describe_biomarker(row)
        assert "hsCRP" in desc
        assert "inflammatory" in desc
        assert "mg/L" in desc
        assert "<1.0" in desc
        assert "CRP" in desc

    def test_describe_biomarker_minimal(self):
        row = {"name": "Cortisol"}
        desc = describe_biomarker(row)
        assert "Cortisol" in desc

    # -- Tenant relationship descriptions --

    def test_describe_relationship_includes(self):
        row = {"src_name": "Anti-Inflammation Protocol", "tgt_name": "Glutathione IV", "phase": "treatment", "order": 2}
        desc, kw = describe_relationship("INCLUDES", row)
        assert "includes intervention" in desc
        assert "treatment" in desc
        assert "protocol" in kw

    def test_describe_relationship_uses(self):
        row = {"src_name": "Glutathione IV", "tgt_name": "Glutathione", "route": "IV", "dosage": "2000mg"}
        desc, kw = describe_relationship("USES", row)
        assert "uses" in desc
        assert "IV" in desc
        assert "intervention" in kw

    def test_describe_relationship_resulted_in(self):
        row = {"src_name": "Glutathione IV", "tgt_name": "hsCRP reduction", "timeframe": "12 weeks"}
        desc, kw = describe_relationship("RESULTED_IN", row)
        assert "resulted in" in desc
        assert "12 weeks" in desc
        assert "outcome" in kw

    def test_describe_relationship_measured_by(self):
        row = {"src_name": "hsCRP reduction", "tgt_name": "hsCRP", "value": 0.8, "unit": "mg/L"}
        desc, kw = describe_relationship("MEASURED_BY", row)
        assert "measured by" in desc
        assert "0.8" in desc
        assert "biomarker" in kw

    def test_describe_relationship_indicates(self):
        row = {"src_name": "hsCRP", "tgt_name": "Chronic Inflammation", "evidence_level": "strong"}
        desc, kw = describe_relationship("INDICATES", row)
        assert "indicates" in desc
        assert "strong" in desc
        assert "biomarker" in kw

    def test_describe_relationship_contraindicates(self):
        row = {"src_name": "Warfarin", "tgt_name": "Bleeding disorders", "severity": "high", "reason": "anticoagulant interaction"}
        desc, kw = describe_relationship("CONTRAINDICATES", row)
        assert "contraindicated" in desc
        assert "high" in desc
        assert "contraindication" in kw

    def test_describe_relationship_synergizes_with(self):
        row = {"src_name": "Curcumin", "tgt_name": "Piperine", "mechanism": "bioavailability enhancement"}
        desc, kw = describe_relationship("SYNERGIZES_WITH", row)
        assert "synergizes" in desc
        assert "bioavailability" in desc
        assert "synergy" in kw


class TestBatchItems:
    def test_batch_items_even(self):
        items = list(range(10))
        batches = batch_items(items, 5)
        assert len(batches) == 2
        assert batches[0] == [0, 1, 2, 3, 4]
        assert batches[1] == [5, 6, 7, 8, 9]

    def test_batch_items_uneven(self):
        items = list(range(7))
        batches = batch_items(items, 3)
        assert len(batches) == 3
        assert batches[2] == [6]

    def test_batch_items_empty(self):
        assert batch_items([], 10) == []

    def test_batch_items_single(self):
        batches = batch_items([1], 10)
        assert len(batches) == 1
        assert batches[0] == [1]


class TestEntitySchema:
    def test_all_entity_types_have_generators(self):
        for et in ENTITY_TYPES:
            assert et in DESCRIPTION_GENERATORS, f"Missing generator for {et}"

    def test_all_entity_types_have_queries(self):
        for et, spec in ENTITY_TYPES.items():
            assert "query" in spec, f"Missing query for {et}"

    def test_all_relationship_types_have_queries(self):
        for rt, spec in RELATIONSHIP_TYPES.items():
            assert "query" in spec, f"Missing query for {rt}"
            assert "src_type" in spec
            assert "tgt_type" in spec

    def test_tenant_entity_types_have_no_source_table(self):
        tenant_types = ["Protocol", "Intervention", "Outcome", "Biomarker"]
        for et in tenant_types:
            assert et in ENTITY_TYPES, f"Missing tenant entity type: {et}"
            spec = ENTITY_TYPES[et]
            assert spec["source_table"] is None, f"{et} should have no source_table"
            assert spec["query"] is None, f"{et} should have no query"

    def test_tenant_relationship_types_have_no_source_table(self):
        tenant_rels = [
            "INCLUDES", "USES", "RESULTED_IN", "MEASURED_BY",
            "INDICATES", "CONTRAINDICATES", "SYNERGIZES_WITH",
        ]
        for rt in tenant_rels:
            assert rt in RELATIONSHIP_TYPES, f"Missing tenant rel type: {rt}"
            spec = RELATIONSHIP_TYPES[rt]
            assert spec["source_table"] is None, f"{rt} should have no source_table"
            assert spec["query"] is None, f"{rt} should have no query"

    def test_shared_entity_types_count(self):
        shared = [k for k, v in ENTITY_TYPES.items() if v.get("source_table") is not None or "query_builder" in v]
        assert len(shared) == 6, f"Expected 6 shared entity types, got {len(shared)}: {shared}"

    def test_shared_relationship_types_count(self):
        shared = [k for k, v in RELATIONSHIP_TYPES.items() if v.get("source_table") is not None]
        assert len(shared) == 5, f"Expected 5 shared rel types, got {len(shared)}: {shared}"


# ---------------------------------------------------------------------------
# Integration tests (DB required)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not DB_EXISTS, reason="herbal_botanicals.db not found")
class TestExtractFromDB:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self.conn = sqlite3.connect(str(DB_PATH))
        yield
        self.conn.close()

    def test_extract_herbs(self):
        entities = extract_entities(self.conn, "Herb", max_count=10)
        assert len(entities) > 0
        assert entities[0]["entity_type"] == "Herb"
        assert len(entities[0]["entity_name"]) > 0
        assert len(entities[0]["description"]) > 0

    def test_extract_compounds(self):
        entities = extract_entities(self.conn, "Compound", max_count=10)
        assert len(entities) > 0
        assert entities[0]["entity_type"] == "Compound"

    def test_extract_foods(self):
        entities = extract_entities(self.conn, "Food", max_count=10)
        assert len(entities) > 0
        assert entities[0]["entity_type"] == "Food"

    def test_extract_relationships_contains_compound(self):
        rels = extract_relationships(self.conn, "CONTAINS_COMPOUND", max_count=10)
        assert len(rels) > 0
        assert "src_id" in rels[0]
        assert "tgt_id" in rels[0]
        assert "description" in rels[0]
        assert "keywords" in rels[0]

    def test_extract_relationships_found_in_food(self):
        rels = extract_relationships(self.conn, "FOUND_IN_FOOD", max_count=10)
        assert len(rels) > 0

    def test_table_exists_true(self):
        assert table_exists(self.conn, "herbs") is True

    def test_table_exists_false(self):
        assert table_exists(self.conn, "nonexistent_table_xyz") is False

    def test_entity_names_unique(self):
        entities = extract_entities(self.conn, "Herb", max_count=100)
        names = [e["entity_name"] for e in entities]
        assert len(names) == len(set(names)), "Duplicate entity names detected"
