# Multi-stage Dockerfile for the shrine-diet-bioactivity KG MCP service.
#
# Combines scoped_server (FastAPI :9621, internal) + MCP gateway (FastMCP HTTP
# transport on $PORT, public) into a single Railway service. See
# docs/adr/0001-vector-storage-on-aura.md and
# research-journal/plans/2026-04-29-mcp-gateway-design.md for context.

# ─── Build stage ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install LightRAG first — heaviest dependency. Cached when only project code changes.
COPY lightrag/requirements.txt /tmp/lightrag-requirements.txt
RUN pip install --no-cache-dir --user -r /tmp/lightrag-requirements.txt

# Install MCP gateway package
COPY mcp/pyproject.toml /tmp/mcp/pyproject.toml
COPY mcp/src /tmp/mcp/src
RUN pip install --no-cache-dir --user /tmp/mcp

# Server-side runtime deps used by scoped_server.py
RUN pip install --no-cache-dir --user \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27" \
    "neo4j>=5.26" \
    "pydantic>=2.0" \
    "python-dotenv>=1.0" \
    "openai>=1.40.0" \
    "requests>=2.31"

# ─── Runtime stage ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root for safety
RUN useradd -m -u 1000 app
WORKDIR /app

COPY --from=builder /root/.local /home/app/.local
ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy only what the runtime needs.
# IMPORTANT: data/ (raw TSVs, ~hundreds of MB) and data_local/ (SQLite, ~1 GB)
# are dev-only; the deployed service reads everything from Aura, never from
# local files. Do NOT add them here — .dockerignore excludes them as a
# defense in depth.
COPY shrine-diet-bioactivity/lightrag/ /app/lightrag/
COPY mcp/src/kg_mcp/ /app/kg_mcp/
COPY scripts/start_combined.sh /app/start_combined.sh
RUN chmod +x /app/start_combined.sh && chown -R app:app /app

# Internal scoped_server port (not exposed); MCP gateway binds to $PORT.
ENV INTERNAL_LIGHTRAG_PORT=9621 \
    LIGHTRAG_URL=http://127.0.0.1:9621 \
    PORT=8080 \
    SHRINE_CONFIG=local

USER app

# Healthcheck hits the MCP gateway HTTP transport. Railway also runs an
# external healthcheck per railway.toml.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

EXPOSE 8080

CMD ["/app/start_combined.sh"]
