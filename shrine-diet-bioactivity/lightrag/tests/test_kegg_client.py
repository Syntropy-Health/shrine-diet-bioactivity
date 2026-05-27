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


# ---- Issue #60: cache-key collision across distinct batches ------------


def test_resolve_gene_symbols_cache_distinguishes_batches_with_same_len_and_first_id(tmp_path):
    """Two distinct batches with identical ``len`` and identical ``batch[0]``
    must NOT share a cache file.

    Before the fix, the key was ``list_genes_batch_{len(batch)}_{batch[0]}``
    so batches ``[hsa:1, hsa:2]`` and ``[hsa:1, hsa:9999]`` collided →
    the second batch silently served stale results from the first.

    The fix must produce different cache files for the two batches.
    """
    cache_dir = tmp_path / "kegg_cache"
    resp_a = httpx.Response(status_code=200, text="hsa:1\tA\nhsa:2\tB\n")
    resp_b = httpx.Response(status_code=200, text="hsa:1\tA\nhsa:9999\tZ\n")

    # First call: batch A
    with patch("httpx.get", return_value=resp_a):
        client = KeggClient(cache_dir=cache_dir, batch_size=10, rate_limit_sleep_s=0)
        out_a = client.resolve_gene_symbols(["hsa:1", "hsa:2"])
    assert out_a == {"hsa:1": "A", "hsa:2": "B"}

    # Second call: batch B (same length=2, same first=hsa:1, different second)
    with patch("httpx.get", return_value=resp_b):
        client = KeggClient(cache_dir=cache_dir, batch_size=10, rate_limit_sleep_s=0)
        out_b = client.resolve_gene_symbols(["hsa:1", "hsa:9999"])

    # The fix is observable as: batch B's lookup hit the HTTP layer (no
    # cache collision served stale A). out_b must include hsa:9999.
    assert "hsa:9999" in out_b, (
        "Cache key collision: batch B served stale data from batch A "
        "(see #60)."
    )


# ---- Issue #61: unconditional rate-limit sleep doubles retry wait -------


def test_get_does_not_double_sleep_on_5xx_retry(tmp_path, monkeypatch):
    """On a 5xx response, the retry backoff is the only delay; the polite
    rate-limit sleep must NOT also fire on the same attempt.

    Before the fix, the polite ``time.sleep(rate_limit_sleep_s)`` fired
    after EVERY HTTP response, so a 5xx retry waited
    ``rate_limit_sleep_s + rate_limit_sleep_s * 2**attempt``. With the
    fix, only the backoff fires on the failure path.
    """
    sleeps: list[float] = []
    monkeypatch.setattr("kegg_client.time.sleep", lambda s: sleeps.append(s))

    # Two 503s then a 200 — one retry, one final success.
    responses = [
        httpx.Response(status_code=503, text=""),
        httpx.Response(status_code=503, text=""),
        httpx.Response(status_code=200, text="path:hsa01100\tMetabolic pathways\n"),
    ]
    rate = 1.0  # explicit, easy to assert against
    cache_dir = tmp_path / "kegg_cache"

    with patch("httpx.get", side_effect=responses):
        client = KeggClient(
            cache_dir=cache_dir,
            rate_limit_sleep_s=rate,
            max_retries=3,
        )
        body = client.list_pathways(organism="hsa")

    assert body != []  # eventual success

    # Expected sleeps with the fix:
    #   attempt 0 (503) → backoff rate * 2**0 = 1.0
    #   attempt 1 (503) → backoff rate * 2**1 = 2.0
    #   attempt 2 (200) → polite rate-limit  = 1.0  (only on success path)
    # Sum = 4.0. With the bug, sum was 1.0 + 1.0 + 2.0 + 1.0 + 2.0 + 1.0 = 8.0
    # (polite sleep fired on each of the three responses, plus the two
    # backoffs). The fix's total budget must be ≤ 5.0.
    assert sum(sleeps) <= 5.0, (
        f"Total sleep budget {sum(sleeps)}s exceeds expected ≤5.0s "
        f"(see #61). Sleeps observed: {sleeps}"
    )
