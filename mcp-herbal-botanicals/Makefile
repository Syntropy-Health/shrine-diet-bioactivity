# ─────────────────────────────────────────────────────────────
# mcp-herbal-botanicals — Phytochemical Knowledge Graph
# ─────────────────────────────────────────────────────────────
#
# Usage:
#   make help              Show all targets
#   make setup             Full pipeline: download → build → migrate → bridge
#   make lightrag-dry-run  Preview LightRAG ingestion (no writes)
#   make lightrag-ingest   Ingest unified KG into LightRAG/Neo4j
#   make neo4j-check       Test Neo4j connection and show KG stats
#
# Prerequisites:
#   - Node.js 18+, npm
#   - Python 3.10+ (for LightRAG)
#   - Ollama running on :11434 with bge-m3 model (for local LightRAG)
#
# Neo4j (Railway):
#   Bolt proxy:  bolt://metro.proxy.rlwy.net:22971
#   Credentials: neo4j / demodemo
#   View in Neo4j Desktop: connect to bolt://metro.proxy.rlwy.net:22971
#   Or use: make neo4j-shell
# ─────────────────────────────────────────────────────────────

.PHONY: help setup download build migrate download-cmaup download-ttd \
        migrate-multi test build-ts check-types \
        food-bridge enrich-nutrition \
        lightrag-setup lightrag-dry-run lightrag-ingest-local lightrag-ingest-prod \
        lightrag-benchmark lightrag-server \
        graphiti-setup graphiti-dry-run graphiti-ingest graphiti-ingest-direct \
        neo4j-check neo4j-shell neo4j-stats neo4j-status neo4j-watch neo4j-clear \
        embedding-check lms-models clean

# Default Neo4j connection (Railway proxy)
NEO4J_URI    ?= bolt://metro.proxy.rlwy.net:22971
NEO4J_USER   ?= neo4j
NEO4J_PASS   ?= demodemo

# LightRAG / Graphiti subsample limits
MAX_HERBS     ?= 2376
MAX_COMPOUNDS ?= 5000
BATCH_SIZE    ?= 500

help: ## Show all targets with descriptions
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Full Pipeline ──────────────────────────────────────────

setup: download build migrate food-bridge enrich-nutrition ## Full pipeline: download → build → migrate → bridge → enrich
	@echo "✅ Setup complete. Run 'make lightrag-dry-run' to preview, then 'make lightrag-ingest-local'."

# ─── Data Download ──────────────────────────────────────────

download: ## Download Duke + FooDB source data (~960 MB)
	npm run download-data

download-cmaup: ## Download CMAUP v2.0 data files (~10 MB)
	npm run download-cmaup

download-ttd: ## Download TTD target data (~5 MB)
	npm run download-ttd

download-all: download download-cmaup download-ttd ## Download all auto-downloadable datasets

# ─── Build & Migrate ────────────────────────────────────────

build: ## Build SQLite DB from downloaded CSVs
	npm run convert-data

migrate: ## Run KG expansion migration (symptoms, targets, food plants)
	npm run migrate-kg

migrate-multi: ## Load CMAUP + CTD + TTD into existing DB
	npm run migrate-multi-source

# ─── TypeScript ─────────────────────────────────────────────

build-ts: ## Compile TypeScript → build/
	npm run build

check-types: ## Type-check without emitting
	npx tsc --noEmit

test: ## Run all tests (vitest)
	npx vitest run

# LM Studio (WSL2 → Windows host)
# LM Studio must listen on 0.0.0.0:1234 (not 127.0.0.1) for WSL2 access.
# In LM Studio: Settings → Server → Listen Address → 0.0.0.0
LMS_HOST ?= $(shell ip route show default 2>/dev/null | awk '{print $$3}')
LMS_URL  ?= http://$(LMS_HOST):1234/v1

# ─── Embedding Server ──────────────────────────────────────

embedding-check: ## Test LM Studio embedding endpoint via WSL2 host
	@echo "Testing $(LMS_URL)/embeddings ..."
	@curl -sf --connect-timeout 5 $(LMS_URL)/embeddings \
		-H "Content-Type: application/json" \
		-d '{"model": "text-embedding-embeddinggemma-300m-qat", "input": "test"}' \
		| python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✅ Embedding dim: {len(d[\"data\"][0][\"embedding\"])}')" \
		|| echo "❌ LM Studio not reachable at $(LMS_URL). Ensure it listens on 0.0.0.0:1234."

lms-models: ## List models loaded in LM Studio
	@curl -sf --connect-timeout 5 $(LMS_URL)/models \
		| python3 -c "import sys,json; [print(f'  {m[\"id\"]}') for m in json.load(sys.stdin).get('data',[])]" \
		|| echo "❌ LM Studio not reachable at $(LMS_URL)"

# ─── Neo4j ──────────────────────────────────────────────────

neo4j-check: ## Test Neo4j connection and show node/edge counts
	@python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
print('=== Neo4j KG Status ==='); \
print('URI: $(NEO4J_URI)'); \
[print(f\"  {r['type']}: {r['count']}\") for r in s.run('MATCH (n) RETURN labels(n) AS type, COUNT(n) AS count ORDER BY count DESC')]; \
[print(f\"  {r['rel']}: {r['count']}\") for r in s.run('MATCH ()-[r]->() RETURN type(r) AS rel, COUNT(r) AS count ORDER BY count DESC')]; \
total_n = s.run('MATCH (n) RETURN COUNT(n) AS c').single()['c']; \
total_r = s.run('MATCH ()-[r]->() RETURN COUNT(r) AS c').single()['c']; \
print(f'Total: {total_n} nodes, {total_r} relationships'); \
s.close(); d.close()"

neo4j-shell: ## Open interactive Cypher shell against Railway Neo4j
	@echo "Connecting to $(NEO4J_URI) ..."
	@docker run --rm -it neo4j:5-community cypher-shell \
		-a $(NEO4J_URI) -u $(NEO4J_USER) -p $(NEO4J_PASS) \
		2>/dev/null || \
	python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
print('Connected. Enter Cypher (empty line to quit):'); \
import sys; \
[None for _ in iter(lambda: (q:=input('> ').strip()) or None, None) if q and [print(r.data()) for r in s.run(q)]]; \
s.close(); d.close()"

neo4j-stats: ## Show detailed KG statistics via Cypher
	@python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
print('=== Detailed KG Stats ==='); \
for r in s.run('MATCH (n) RETURN labels(n)[0] AS label, COUNT(n) AS count ORDER BY count DESC'): print(f'  Nodes [{r[\"label\"]}]: {r[\"count\"]}'); \
for r in s.run('MATCH ()-[r]->() RETURN type(r) AS type, COUNT(r) AS count ORDER BY count DESC'): print(f'  Edges [{r[\"type\"]}]: {r[\"count\"]}'); \
s.close(); d.close()"

neo4j-status: ## Full KG analytics — node/edge breakdown, ingestion sources, growth rate
	@NEO4J_URI=$(NEO4J_URI) NEO4J_USER=$(NEO4J_USER) NEO4J_PASSWORD=$(NEO4J_PASS) \
	python3 graphiti/kg_status.py

neo4j-watch: ## Live-monitor KG growth (polls every 30s, Ctrl+C to stop)
	@echo "Watching KG growth at $(NEO4J_URI) — Ctrl+C to stop"
	@while true; do \
		NEO4J_URI=$(NEO4J_URI) NEO4J_USER=$(NEO4J_USER) NEO4J_PASSWORD=$(NEO4J_PASS) \
		python3 graphiti/kg_status.py 2>/dev/null | tail -1 || true; \
		sleep 30; \
	done

neo4j-clear: ## ⚠️  Delete ALL nodes and relationships in Neo4j
	@echo "⚠️  This will delete ALL data in Neo4j at $(NEO4J_URI)"
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] && \
	python3 -c "\
from neo4j import GraphDatabase; \
d = GraphDatabase.driver('$(NEO4J_URI)', auth=('$(NEO4J_USER)', '$(NEO4J_PASS)')); \
s = d.session(); \
s.run('MATCH (n) DETACH DELETE n'); \
print('✅ All nodes and relationships deleted.'); \
s.close(); d.close()" || echo "Cancelled."

# ─── Food Bridge & Nutrition Enrichment ─────────────────────

food-bridge: ## Build food name bridge between FooDB and OpenNutrition
	npm run build-food-bridge

enrich-nutrition: food-bridge ## Enrich compound_foods with OpenNutrition nutrition data
	npm run enrich-nutrition

# ─── LightRAG ─────────────────────────────────────────────

lightrag-setup: ## Install LightRAG Python dependencies
	cd lightrag && pip install -r requirements.txt

lightrag-dry-run: ## Dry-run ingestion — print entity/relationship counts (no writes)
	cd lightrag && python3 ingest_unified.py --config local --dry-run

lightrag-ingest-local: ## Ingest unified KG into LightRAG (local Ollama embeddings)
	cd lightrag && python3 ingest_unified.py --config local --batch-size $(BATCH_SIZE)

lightrag-ingest-prod: ## Ingest unified KG into LightRAG (production API embeddings)
	cd lightrag && python3 ingest_unified.py --config production --batch-size 200

lightrag-benchmark: ## Run 10 benchmark queries against LightRAG
	cd lightrag && python3 query_benchmark.py --config local

lightrag-server: ## Start LightRAG API server (local config)
	cd lightrag && lightrag-server

# ─── Graphiti (Legacy) ─────────────────────────────────────

graphiti-setup: ## Set up Python venv and install Graphiti dependencies
	cd graphiti && \
	python3 -m venv .venv && \
	. .venv/bin/activate && \
	pip install -r requirements.txt && \
	echo "✅ Graphiti venv ready. Activate with: source graphiti/.venv/bin/activate"

graphiti-dry-run: ## Show what would be ingested (no Neo4j connection needed)
	cd graphiti && \
	OPENAI_API_KEY=not-needed \
	NEO4J_URI=$(NEO4J_URI) NEO4J_USER=$(NEO4J_USER) NEO4J_PASSWORD=$(NEO4J_PASS) \
	MAX_HERBS=$(MAX_HERBS) MAX_COMPOUNDS=$(MAX_COMPOUNDS) BATCH_SIZE=$(BATCH_SIZE) \
	MAX_LINKS=2000 \
	python3 ingest.py --dry-run

graphiti-ingest: ## Ingest subsampled data into Graphiti/Neo4j (requires LM Studio)
	@echo "Checking LM Studio at $(LMS_URL) ..."
	@curl -sf --connect-timeout 5 $(LMS_URL)/models >/dev/null 2>&1 || \
		(echo "❌ LM Studio not reachable at $(LMS_URL). Ensure it listens on 0.0.0.0:1234." && exit 1)
	cd graphiti && \
	OPENAI_API_KEY=not-needed \
	NEO4J_URI=$(NEO4J_URI) NEO4J_USER=$(NEO4J_USER) NEO4J_PASSWORD=$(NEO4J_PASS) \
	MAX_HERBS=$(MAX_HERBS) MAX_COMPOUNDS=$(MAX_COMPOUNDS) BATCH_SIZE=$(BATCH_SIZE) \
	MAX_LINKS=2000 \
	EMBEDDING_BASE_URL=$(LMS_URL) \
	LLM_BASE_URL=$(LMS_URL) \
	python3 ingest.py

graphiti-ingest-direct: ## Ingest structured data directly into Neo4j (no LLM needed, embeddings only)
	@echo "Checking embedding server at $(LMS_URL) ..."
	@curl -sf --connect-timeout 5 $(LMS_URL)/models >/dev/null 2>&1 || \
		(echo "❌ Embedding server not reachable at $(LMS_URL)." && exit 1)
	cd graphiti && \
	PYTHONUNBUFFERED=1 \
	NEO4J_URI=$(NEO4J_URI) NEO4J_USER=$(NEO4J_USER) NEO4J_PASSWORD=$(NEO4J_PASS) \
	MAX_HERBS=$(MAX_HERBS) MAX_COMPOUNDS=$(MAX_COMPOUNDS) \
	MAX_LINKS=2000 BATCH_SIZE=$(BATCH_SIZE) \
	EMBEDDING_BASE_URL=$(LMS_URL) \
	python3 -u ingest_direct.py

# ─── Cleanup ────────────────────────────────────────────────

clean: ## Remove build artifacts and temp data
	rm -rf build data_local_temp
