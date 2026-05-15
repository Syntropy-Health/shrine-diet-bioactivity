"""Tests for KEGG REST client + TSV parsers (Phase 4)."""

import sys
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from kegg_client import (  # noqa: E402
    KeggClient,
    parse_pathway_list,
    parse_pathway_links,
    parse_gene_aliases,
)


# ---- TSV parsers -------------------------------------------------------


def test_parse_pathway_list_handles_real_format():
    raw = (
        "path:hsa01100\tMetabolic pathways - Homo sapiens (human)\n"
        "path:hsa01200\tCarbon metabolism - Homo sapiens (human)\n"
        "path:hsa04110\tCell cycle - Homo sapiens (human)\n"
    )
    rows = parse_pathway_list(raw, organism="hsa")
    assert len(rows) == 3
    assert rows[0] == {
        "id": "hsa01100",
        "name": "Metabolic pathways",
        "organism": "hsa",
    }
    # Trailing " - Homo sapiens (human)" stripped from name.
    assert " - Homo sapiens" not in rows[0]["name"]


def test_parse_pathway_list_strips_path_prefix():
    raw = "path:hsa00010\tGlycolysis / Gluconeogenesis - Homo sapiens (human)\n"
    rows = parse_pathway_list(raw, organism="hsa")
    assert rows[0]["id"] == "hsa00010"
    # Name retains internal slashes
    assert rows[0]["name"] == "Glycolysis / Gluconeogenesis"


def test_parse_pathway_list_skips_empty_lines():
    raw = "path:hsa01100\tMetabolic pathways - Homo sapiens (human)\n\n\n"
    rows = parse_pathway_list(raw, organism="hsa")
    assert len(rows) == 1


def test_parse_pathway_list_returns_empty_on_empty_input():
    assert parse_pathway_list("", organism="hsa") == []


def test_parse_pathway_list_accepts_unprefixed_ids():
    """KEGG's current /list/pathway/<org> response omits the 'path:' prefix.
    Parser must accept both prefixed (legacy cached) and unprefixed (current).
    """
    raw_unprefixed = (
        "hsa01100\tMetabolic pathways - Homo sapiens (human)\n"
        "hsa01200\tCarbon metabolism - Homo sapiens (human)\n"
    )
    rows = parse_pathway_list(raw_unprefixed, organism="hsa")
    assert len(rows) == 2
    assert rows[0]["id"] == "hsa01100"


def test_parse_pathway_list_rejects_wrong_organism():
    """Defensive: rows for a different organism shouldn't leak through."""
    raw = (
        "hsa01100\tMetabolic pathways - Homo sapiens (human)\n"
        "mmu01100\tMetabolic pathways - Mus musculus (mouse)\n"
    )
    rows = parse_pathway_list(raw, organism="hsa")
    assert len(rows) == 1
    assert rows[0]["id"] == "hsa01100"


# ---- compound/gene link parsers ----------------------------------------


def test_parse_pathway_links_compound():
    raw = (
        "path:hsa00010\tcpd:C00031\n"
        "path:hsa00010\tcpd:C00022\n"
        "path:hsa00020\tcpd:C00149\n"
    )
    links = parse_pathway_links(raw, target_prefix="cpd:")
    assert links == [
        ("hsa00010", "C00031"),
        ("hsa00010", "C00022"),
        ("hsa00020", "C00149"),
    ]


def test_parse_pathway_links_gene():
    raw = "path:hsa00010\thsa:1234\npath:hsa00010\thsa:5678\npath:hsa00020\thsa:9999\n"
    links = parse_pathway_links(raw, target_prefix="hsa:", strip_target_prefix=False)
    assert links == [
        ("hsa00010", "hsa:1234"),
        ("hsa00010", "hsa:5678"),
        ("hsa00020", "hsa:9999"),
    ]


def test_parse_pathway_links_skips_malformed_rows():
    raw = (
        "path:hsa00010\tcpd:C00031\n"
        "GARBAGE_LINE\n"
        "path:hsa00010\twrongprefix:X123\n"  # wrong target prefix
        "path:hsa00020\tcpd:C00149\n"
    )
    links = parse_pathway_links(raw, target_prefix="cpd:")
    assert links == [("hsa00010", "C00031"), ("hsa00020", "C00149")]


def test_parse_pathway_links_accepts_unprefixed_left_column():
    """Same robustness as parse_pathway_list — KEGG omits 'path:' on /list endpoints
    and inconsistently across /link endpoints across API versions."""
    raw = (
        "hsa00010\tcpd:C00031\n"  # no 'path:' prefix
        "path:hsa00020\tcpd:C00149\n"  # legacy prefixed
    )
    links = parse_pathway_links(raw, target_prefix="cpd:")
    assert links == [("hsa00010", "C00031"), ("hsa00020", "C00149")]


# ---- gene alias parsing ------------------------------------------------


def test_parse_gene_aliases_picks_first_token_as_hugo():
    raw = "hsa:1234\tGCK; HK4; HXK4; glucokinase\nhsa:5678\tINS; IDDM2; ILPR; insulin\n"
    out = parse_gene_aliases(raw)
    assert out == {"hsa:1234": "GCK", "hsa:5678": "INS"}


def test_parse_gene_aliases_handles_missing_aliases():
    raw = "hsa:9999\t\nhsa:1234\tGCK\n"
    out = parse_gene_aliases(raw)
    # Missing alias means the gene is filtered out (we can't anchor it).
    assert "hsa:9999" not in out
    assert out["hsa:1234"] == "GCK"


def test_parse_gene_aliases_strips_whitespace():
    raw = "hsa:1234\t  GCK  ; HK4\n"
    out = parse_gene_aliases(raw)
    assert out["hsa:1234"] == "GCK"


# ---- KeggClient with mocked httpx --------------------------------------


def test_client_list_pathways_uses_cache(tmp_path):
    cache_dir = tmp_path / "kegg_cache"
    fake_resp = httpx.Response(
        status_code=200,
        text="path:hsa01100\tMetabolic pathways - Homo sapiens (human)\n",
    )
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        client = KeggClient(cache_dir=cache_dir)
        rows1 = client.list_pathways(organism="hsa")
        rows2 = client.list_pathways(organism="hsa")  # second call hits cache
    assert len(rows1) == 1
    assert rows1 == rows2
    # Only one HTTP call — second was cache hit.
    assert mock_get.call_count == 1
    # Cache file written.
    assert (cache_dir / "list_pathway_hsa.tsv").exists()


def test_client_handles_500_with_retry_then_returns_empty(tmp_path):
    cache_dir = tmp_path / "kegg_cache"
    fake_500 = httpx.Response(status_code=500, text="")
    with patch("httpx.get", return_value=fake_500):
        client = KeggClient(cache_dir=cache_dir, max_retries=2)
        rows = client.list_pathways(organism="hsa")
    assert rows == []
    # No cache write on persistent failure.
    assert not (cache_dir / "list_pathway_hsa.tsv").exists()


def test_client_resolve_gene_symbols_batches_by_chunk(tmp_path):
    """KEGG /find/genes accepts multiple IDs separated by '+'; batch in chunks."""
    cache_dir = tmp_path / "kegg_cache"
    fake_resp = httpx.Response(
        status_code=200,
        text="hsa:1\tA\nhsa:2\tB\nhsa:3\tC\n",
    )
    with patch("httpx.get", return_value=fake_resp) as mock_get:
        client = KeggClient(cache_dir=cache_dir, batch_size=10)
        out = client.resolve_gene_symbols(["hsa:1", "hsa:2", "hsa:3"])
    assert out == {"hsa:1": "A", "hsa:2": "B", "hsa:3": "C"}
    # 3 IDs in one batch (batch_size=10 ≥ 3).
    assert mock_get.call_count == 1
