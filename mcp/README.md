# `mcp/` — LightRAG KG MCP Gateway

Thin MCP-protocol shim over the `scoped_server.py` HTTP service. The MCP server
the publication's clinical agent connects to. Built per:

- `research-journal/plans/2026-04-29-mcp-gateway-design.md` — toolkit + design tensions
- `research-journal/HANDOFF-research-via-mcp.md` — handoff for the parallel research session

## Status

Scaffolded 2026-04-29. Layer A (`kg_query`) is end-to-end against `scoped_server`'s
`POST /query`. Layers B and C (role-priored tools, lookup primitives) require
small new endpoints on `scoped_server` first — tracked under Task #12.

## Design recap

**10 tools, 3 layers:**

- **Layer A** — `kg_query` (general NL Q&A, default fallback)
- **Layer B** — 6 role-priored traversals enforcing `(start_label, edge_type)`
- **Layer C** — 3 lookup primitives (HDI, bilingual term, neighborhood)

See the design memo for the full table and rationale.

## Run

```
# Prerequisites: scoped_server running on :9621 with re-embedded vector index live
cd /path/to/shrine-diet-bioactivity
make lightrag-server &
python -m kg_mcp.server
```

The MCP server speaks stdio. Configure your MCP client (Claude Desktop, agent SDK)
to spawn `python -m kg_mcp.server` as a stdio child.

## Layout

```
mcp/
├── README.md             ← you are here
├── pyproject.toml        ← package metadata
├── src/kg_mcp/
│   ├── __init__.py
│   ├── schemas.py        ← Pydantic input/output models per design memo §5
│   ├── client.py         ← httpx wrapper around scoped_server
│   └── server.py         ← MCP tool registrations
└── tests/unit/
    └── test_server.py    ← mock-driven smoke (TBD)
```

## Boundary contract

This package never:

- writes to the KG (use `scoped_server`'s `/documents/custom_kg`)
- holds Aura credentials directly (delegates to `scoped_server`)
- runs Cypher on its own (the Layer-B tools delegate to typed endpoints — see Task #12)

This package always:

- speaks MCP stdio
- enforces Pydantic input/output schemas per tool
- propagates `scope_filter=["shared"]` by default; tenant scoped tools are an explicit follow-up
