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
    describe_compound,
    describe_food,
    describe_herb,
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
