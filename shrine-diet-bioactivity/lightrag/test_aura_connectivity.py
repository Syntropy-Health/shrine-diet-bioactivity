# shrine-diet-bioactivity/lightrag/test_aura_connectivity.py
"""Preflight integration test: verify Neo4j Aura is reachable and responsive.

Credentials are read from os.environ, populated by load_dotenv() below.
The .env file is gitignored — never committed to source control.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load .env from shrine-diet-bioactivity/ (one level above this file's directory)
load_dotenv(Path(__file__).parent.parent / ".env")


@pytest.mark.integration
def test_aura_reachable_and_returns_constant():
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    assert uri.startswith("neo4j+s://"), "expected Aura secure URI"
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as s:
            assert s.run("RETURN 1 AS ok").single()["ok"] == 1


@pytest.mark.integration
def test_aura_version_string():
    """Capture Aura version via dbms.components() for sanity-check reporting."""
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session() as s:
            record = s.run(
                "CALL dbms.components() YIELD name, versions RETURN name, versions[0] AS v"
            ).single()
            assert record is not None, "dbms.components() returned no records"
            assert record["name"] is not None
            assert record["v"] is not None
