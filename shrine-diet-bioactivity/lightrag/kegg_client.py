"""KEGG REST client + TSV parsers (Phase 4).

Pure-logic parsers + a thin HTTP client with on-disk caching. KEGG's REST
API is unauthenticated for academic use; commercial deployments need a
license (see ADR 0009 + DATASET_PROVENANCE.md).

Endpoints used:
  GET /list/pathway/<org>            → pathway list  (path:hsa01100\\tname)
  GET /link/cpd/pathway/<org>        → pathway↔compound  (path:hsa00010\\tcpd:C00031)
  GET /link/<org>/pathway            → pathway↔gene  (path:hsa00010\\thsa:1234)
  GET /list/<id1>+<id2>+...          → gene aliases  (hsa:1234\\tGCK; HK4; ...)

Caching: every successful response written to <cache_dir>/<endpoint>.tsv;
re-runs read from cache so the API is hit at most once per endpoint per
machine. Cache invalidation = manual delete of the file.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

KEGG_BASE = "https://rest.kegg.jp"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_RATE_LIMIT_SLEEP_S = 0.35  # KEGG soft limit ~3 req/s
DEFAULT_BATCH_SIZE = 50  # /list/<a+b+c> — keep URL length manageable


# ---------------------------------------------------------------------------
# TSV parsers (pure functions — no HTTP)
# ---------------------------------------------------------------------------


# Trailing organism annotation that KEGG attaches to pathway names:
#   "Metabolic pathways - Homo sapiens (human)"
# We strip it so the canonical name reads naturally.
_ORG_SUFFIX = re.compile(r" - [A-Z][a-z]+ [a-z]+ \([a-z ]+\)$")


def parse_pathway_list(raw: str, *, organism: str) -> list[dict]:
    """Parse `/list/pathway/<org>` TSV → list of {id, name, organism} dicts.

    KEGG accepts both prefixed (``path:hsa01100``) and unprefixed (``hsa01100``)
    forms. As of 2026-05-08, ``/list/pathway/hsa`` returns unprefixed; older
    cache files may have the prefixed form. Strip if present, accept either.
    """
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        path_id, name = line.split("\t", 1)
        path_id = path_id.strip()
        if path_id.startswith("path:"):
            path_id = path_id[len("path:") :]
        # Sanity check: should look like an organism+digits ID (e.g. hsa01100).
        if not path_id or not path_id.startswith(organism):
            continue
        clean_name = _ORG_SUFFIX.sub("", name).strip()
        out.append({"id": path_id, "name": clean_name, "organism": organism})
    return out


def parse_pathway_links(
    raw: str,
    *,
    target_prefix: str,
    strip_target_prefix: bool = True,
) -> list[tuple[str, str]]:
    """Parse `/link/<X>/pathway` TSV → list of (pathway_id, target_id) tuples.

    Like parse_pathway_list, the ``path:`` prefix on the left column is
    optional — KEGG's response format has been inconsistent across endpoints
    and across recent API revisions. Accept both prefixed and unprefixed.
    The right column's prefix (cpd:, hsa:, etc.) is required so we can
    confirm we're parsing the right link type.

    target_prefix examples:
      "cpd:" for compound links → strips prefix → "C00031"
      "hsa:" for gene links → keep prefix → "hsa:1234" (set strip=False)
    """
    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        left, right = line.split("\t", 1)
        if left.startswith("path:"):
            left = left[len("path:") :]
        if not right.startswith(target_prefix):
            continue
        target = right[len(target_prefix) :] if strip_target_prefix else right
        out.append((left, target))
    return out


def parse_gene_aliases(raw: str) -> dict[str, str]:
    """Parse `/list/<ids>` TSV → {kegg_gene_id: hugo_symbol}.

    KEGG returns: "hsa:1234\\tGCK; HK4; HXK4; glucokinase".
    The first semicolon-separated token is the HUGO symbol; downstream
    aliases are gene-name variants we don't keep. Missing or empty
    aliases mean the gene is unanchored — drop it from the map.
    """
    out: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or "\t" not in line:
            continue
        kid, aliases = line.split("\t", 1)
        first = aliases.split(";", 1)[0].strip()
        if first:
            out[kid] = first
    return out


# ---------------------------------------------------------------------------
# KeggClient with on-disk cache + retry
# ---------------------------------------------------------------------------


class KeggClient:
    def __init__(
        self,
        *,
        cache_dir: Path,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        rate_limit_sleep_s: float = DEFAULT_RATE_LIMIT_SLEEP_S,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = 3,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s
        self.rate_limit_sleep_s = rate_limit_sleep_s
        self.batch_size = batch_size
        self.max_retries = max_retries

    def _cache_path(self, key: str) -> Path:
        flat = key.replace("/", "_").lstrip("_")
        return self.cache_dir / f"{flat}.tsv"

    def _get(self, endpoint: str, *, cache_key: Optional[str] = None) -> str:
        """GET; cache; retry on 5xx; return body or '' on persistent failure."""
        import httpx

        key = cache_key or endpoint
        cache_file = self._cache_path(key)
        if cache_file.exists():
            return cache_file.read_text()

        url = f"{KEGG_BASE}{endpoint}"
        for attempt in range(self.max_retries):
            try:
                resp = httpx.get(url, timeout=self.timeout_s)
            except httpx.RequestError:
                time.sleep(self.rate_limit_sleep_s * (2**attempt))
                continue
            time.sleep(self.rate_limit_sleep_s)
            if resp.status_code == 200:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(resp.text)
                return resp.text
            if 500 <= resp.status_code < 600:
                time.sleep(self.rate_limit_sleep_s * (2**attempt))
                continue
            # 4xx is final; do not cache.
            return ""
        return ""

    def list_pathways(self, *, organism: str = "hsa") -> list[dict]:
        body = self._get(f"/list/pathway/{organism}")
        return parse_pathway_list(body, organism=organism)

    def list_compound_pathway_links(
        self, *, organism: str = "hsa"
    ) -> list[tuple[str, str]]:
        """Returns (pathway_id, kegg_compound_id) tuples in <organism> namespace.

        KEGG's compound-pathway links live in the organism-agnostic ``map`` namespace
        (e.g. ``map00010`` = "Glycolysis" reference pathway). We fetch
        ``/link/pathway/cpd`` and translate ``mapXXXXX → <organism>XXXXX`` so the
        result joins our ``kegg_pathways`` table (populated from ``/list/pathway/<org>``,
        which uses the ``<organism>`` prefix). Reference and organism-specific
        pathway IDs share the trailing 5-digit code by design.

        Note that ``/link/pathway/cpd`` returns tuples in the order
        ``(compound, pathway)`` — opposite of ``/link/<org>/pathway`` — so we
        swap to maintain the (pathway_id, target_id) contract.
        """
        body = self._get("/link/pathway/cpd")
        out: list[tuple[str, str]] = []
        for line in body.splitlines():
            line = line.strip()
            if not line or "\t" not in line:
                continue
            cpd_field, path_field = line.split("\t", 1)
            cpd_field = cpd_field.strip()
            path_field = path_field.strip()
            if not cpd_field.startswith("cpd:"):
                continue
            kegg_compound_id = cpd_field[len("cpd:") :]
            # Strip optional 'path:' prefix.
            if path_field.startswith("path:"):
                path_field = path_field[len("path:") :]
            # Translate map00010 → <organism>00010 if applicable.
            if path_field.startswith("map"):
                path_field = organism + path_field[len("map") :]
            # Skip pathways that aren't in our organism's namespace.
            if not path_field.startswith(organism):
                continue
            out.append((path_field, kegg_compound_id))
        return out

    def list_pathway_gene_links(
        self, *, organism: str = "hsa"
    ) -> list[tuple[str, str]]:
        body = self._get(f"/link/{organism}/pathway")
        return parse_pathway_links(
            body, target_prefix=f"{organism}:", strip_target_prefix=False
        )

    def resolve_gene_symbols(self, kegg_gene_ids: list[str]) -> dict[str, str]:
        """Batch-resolve `hsa:1234` IDs to HUGO symbols via `/list/<ids>`."""
        out: dict[str, str] = {}
        if not kegg_gene_ids:
            return out
        for i in range(0, len(kegg_gene_ids), self.batch_size):
            batch = kegg_gene_ids[i : i + self.batch_size]
            joined = "+".join(batch)
            body = self._get(
                f"/list/{joined}",
                cache_key=f"list_genes_batch_{len(batch)}_{batch[0].replace(':', '_')}",
            )
            out.update(parse_gene_aliases(body))
        return out
